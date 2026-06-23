"""Phase 1 checkpoint — storage vending + tenant-pathed layout.

Invariant #2 (PLATFORM_ARCHITECTURE.md §5.2): access is *vended*, never ambient.
Compute resolves storage through a control-plane capability; the on-disk layout is
tenant-pathed `{root}/{org_id}/{conn_id}/...`. These tests pin the capability's
path resolution, the org-from-context behaviour, and the one-time, idempotent,
crash-safe migration of the legacy flat layout — including the sharp edge of a
connection dir literally named like the org.
"""
from __future__ import annotations

import pytest

from aughor.org import using_org
from aughor.platform import vending
from aughor.platform.vending import (
    StorageCapability,
    migrate_uploads_to_org_layout,
    vend_storage,
)


@pytest.fixture()
def storage_root(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr(vending, "STORAGE_ROOT", root)
    return root


# ── the vended capability ─────────────────────────────────────────────────────

class TestVending:
    def test_resolves_tenant_scoped_path(self, storage_root):
        cap = vend_storage("conn42")
        assert cap.org_id == "default" and cap.conn_id == "conn42"
        assert cap.root == storage_root / "default" / "conn42"
        assert cap.resolve("main", "sales.csv") == storage_root / "default" / "conn42" / "main" / "sales.csv"

    def test_org_comes_from_context(self, storage_root):
        with using_org("acme"):
            cap = vend_storage("conn42")
        assert cap.org_id == "acme"
        assert cap.root == storage_root / "acme" / "conn42"

    def test_explicit_org_overrides_context(self, storage_root):
        with using_org("acme"):
            cap = vend_storage("conn42", org_id="globex")
        assert cap.org_id == "globex"

    def test_empty_conn_falls_back_to_default_slot(self, storage_root):
        assert vend_storage("").conn_id == "default"
        assert StorageCapability("default", "").conn_id == ""  # raw dataclass is literal


# ── the on-disk migration ─────────────────────────────────────────────────────

def _legacy_file(root, conn, schema, name):
    d = root / conn / schema
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text("x")
    return f


class TestMigration:
    def test_no_root_is_noop(self, storage_root):
        assert migrate_uploads_to_org_layout() is False  # nothing to migrate

    def test_flat_layout_moves_under_org_subtree(self, storage_root):
        _legacy_file(storage_root, "workspace", "main", "sales.csv")
        _legacy_file(storage_root, "abc12345", "finance", "ledger.parquet")
        assert migrate_uploads_to_org_layout() is True
        # files now live under {root}/default/{conn}/...
        assert (storage_root / "default" / "workspace" / "main" / "sales.csv").exists()
        assert (storage_root / "default" / "abc12345" / "finance" / "ledger.parquet").exists()
        # legacy top-level conn dirs are gone; marker written
        assert not (storage_root / "workspace").exists()
        assert (storage_root / ".org_layout").read_text() == "default"

    def test_conn_named_like_org_nests_without_collision(self, storage_root):
        # The conn_id fallback dir is literally "default" — it must nest to
        # default/default/, not collide with or clobber the new org dir.
        _legacy_file(storage_root, "default", "main", "y.csv")
        _legacy_file(storage_root, "other", "main", "z.csv")
        assert migrate_uploads_to_org_layout() is True
        assert (storage_root / "default" / "default" / "main" / "y.csv").exists()
        assert (storage_root / "default" / "other" / "main" / "z.csv").exists()

    def test_idempotent_second_run_is_noop(self, storage_root):
        _legacy_file(storage_root, "workspace", "main", "sales.csv")
        assert migrate_uploads_to_org_layout() is True
        before = sorted(p.relative_to(storage_root).as_posix() for p in storage_root.rglob("*"))
        assert migrate_uploads_to_org_layout() is False  # marker present → skip
        after = sorted(p.relative_to(storage_root).as_posix() for p in storage_root.rglob("*"))
        assert before == after

    def test_resumes_after_interrupted_run(self, storage_root):
        # Simulate a crash mid-move: a child already in staging, another still flat,
        # no marker yet. The re-run must finish without losing either.
        _legacy_file(storage_root, "abc12345", "main", "x.csv")              # still flat
        staged = storage_root / ".__org_default__" / "workspace" / "main"
        staged.mkdir(parents=True)
        (staged / "sales.csv").write_text("x")                               # already staged
        assert migrate_uploads_to_org_layout() is True
        assert (storage_root / "default" / "workspace" / "main" / "sales.csv").exists()
        assert (storage_root / "default" / "abc12345" / "main" / "x.csv").exists()
        assert (storage_root / ".org_layout").exists()


# ── connector uses the vended path end-to-end ─────────────────────────────────

class TestConnectorUsesVendedPath:
    def test_upload_dir_is_tenant_scoped(self, storage_root):
        from aughor.connectors.file.local_upload import LocalUploadConnection
        with using_org("acme"):
            conn = LocalUploadConnection(connection_id="c1")
        assert conn._upload_dir == storage_root / "acme" / "c1"
        assert conn._upload_dir.exists()  # __init__ created it
