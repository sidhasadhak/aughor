"""Phase 3 foundation — Volumes (the governed unstructured tier).

Verifies the object bytes land at the tenant-pathed, vended location
({root}/{org}/{catalog}/_volumes/{volume}/...) and the queryable metadata catalog
tracks them; catalog validation; org-scoping; and the read/delete round-trip.
"""
from __future__ import annotations

import pytest

from aughor.org import using_org
from aughor.volumes import (
    create_volume,
    delete_object,
    list_objects,
    list_volumes,
    put_object,
    read_object,
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import aughor.metastore.store as ms_store
    import aughor.volumes.store as vol_store
    from aughor.platform import vending
    monkeypatch.setattr(ms_store, "_DB_PATH", tmp_path / "metastore.db")
    monkeypatch.setattr(vol_store, "_DB_PATH", tmp_path / "volumes.db")
    root = tmp_path / "uploads"
    monkeypatch.setattr(vending, "STORAGE_ROOT", root)
    # a catalog must exist to create a volume under it
    from aughor.metastore import upsert_catalog
    upsert_catalog("cat1", name="Cat One", conn_id="cat1")
    return root


class TestVolumeLifecycle:
    def test_create_is_idempotent_and_listed(self, env):
        v1 = create_volume("cat1", "docs")
        v2 = create_volume("cat1", "docs")           # idempotent
        assert v1.id == v2.id and v1.full_name == "cat1.docs"
        assert {v.name for v in list_volumes("cat1")} == {"docs"}

    def test_create_requires_existing_catalog(self, env):
        with pytest.raises(ValueError):
            create_volume("ghost", "docs")


class TestObjects:
    def test_put_lands_at_tenant_path_and_reads_back(self, env):
        root = env
        vol = create_volume("cat1", "docs")
        obj = put_object(vol.id, "report.pdf", b"%PDF-1.4 hello", mime_type="application/pdf")
        # metadata catalog
        assert obj.name == "report.pdf" and obj.size_bytes == 14 and obj.mime_type == "application/pdf"
        assert {o.name for o in list_objects(vol.id)} == {"report.pdf"}
        # bytes at the tenant-scoped, vended path {root}/default/cat1/_volumes/docs/...
        vdir = root / "default" / "cat1" / "_volumes" / "docs"
        stored = list(vdir.iterdir())
        assert len(stored) == 1 and stored[0].read_bytes() == b"%PDF-1.4 hello"
        # round-trip read
        assert read_object(obj.id) == b"%PDF-1.4 hello"

    def test_mime_guessed_when_absent(self, env):
        vol = create_volume("cat1", "imgs")
        obj = put_object(vol.id, "pic.png", b"\x89PNG")
        assert obj.mime_type == "image/png"

    def test_delete_removes_bytes_and_row(self, env):
        root = env
        vol = create_volume("cat1", "docs")
        obj = put_object(vol.id, "a.txt", b"hi")
        assert delete_object(obj.id) is True
        assert list_objects(vol.id) == []
        assert list((root / "default" / "cat1" / "_volumes" / "docs").iterdir()) == []

    def test_put_into_missing_volume_raises(self, env):
        with pytest.raises(ValueError):
            put_object("nope", "a.txt", b"x")


class TestOrgScoping:
    def test_objects_are_tenant_pathed_by_org(self, env):
        root = env
        from aughor.metastore import upsert_catalog
        with using_org("acme"):
            upsert_catalog("cat1", name="Acme Cat", conn_id="cat1")
            vol = create_volume("cat1", "docs")
            obj = put_object(vol.id, "x.txt", b"acme")
            assert obj.org_id == "acme"
            assert read_object(obj.id) == b"acme"
        # stored under the acme tenant subtree, not default
        assert (root / "acme" / "cat1" / "_volumes" / "docs").exists()
        assert not (root / "default" / "cat1" / "_volumes").exists()
