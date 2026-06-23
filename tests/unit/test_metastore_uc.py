"""Phase 2 checkpoint, increment 3 — the UC-compatible read-only namespace API.

Verifies the Unity-Catalog response shaping + routing (catalogs / schemas / tables)
over the metastore. Live introspection (`_live_entries`) is stubbed so the tests are
hermetic and fast; catalogs + schemas are served from the first-class metastore rows.
"""
from __future__ import annotations

import asyncio

import pytest

import aughor.routers.metastore as uc
from aughor.metastore import upsert_catalog, upsert_schema


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    import aughor.metastore.store as ms_store
    monkeypatch.setattr(ms_store, "_DB_PATH", tmp_path / "metastore.db")
    upsert_catalog("workspace", name="Workspace", conn_id="workspace")
    upsert_schema("workspace", "missimi")
    # Stub live introspection: one connection entry with one schema + two tables.
    async def _fake_entries():
        return [{"conn_id": "workspace", "schemas": [
            {"name": "missimi", "tables": [
                {"name": "orders", "row_count": 100},
                {"name": "products", "row_count": 50},
            ]},
        ]}]
    monkeypatch.setattr(uc, "_live_entries", _fake_entries)


class TestCatalogs:
    def test_list_and_get(self, seeded):
        cats = uc.uc_list_catalogs()["catalogs"]
        assert any(c["name"] == "workspace" and c["securable_type"] == "CATALOG" for c in cats)
        one = uc.uc_get_catalog("workspace")
        assert one["name"] == "workspace" and one["comment"] == "Workspace"

    def test_missing_is_404(self, seeded):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            uc.uc_get_catalog("nope")
        assert e.value.status_code == 404


class TestSchemas:
    def test_list_and_full_name(self, seeded):
        schemas = _run(uc.uc_list_schemas(catalog_name="workspace"))["schemas"]
        assert [s["full_name"] for s in schemas] == ["workspace.missimi"]
        assert schemas[0]["catalog_name"] == "workspace" and schemas[0]["securable_type"] == "SCHEMA"

    def test_get_by_full_name(self, seeded):
        s = _run(uc.uc_get_schema("workspace.missimi"))
        assert s["name"] == "missimi"

    def test_bad_and_missing(self, seeded):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as bad:
            _run(uc.uc_get_schema("noseparator"))
        assert bad.value.status_code == 400
        with pytest.raises(HTTPException) as miss:
            _run(uc.uc_get_schema("workspace.ghost"))
        assert miss.value.status_code == 404


class TestTables:
    def test_list(self, seeded):
        tables = _run(uc.uc_list_tables(catalog_name="workspace", schema_name="missimi"))["tables"]
        assert {t["name"] for t in tables} == {"orders", "products"}
        assert tables[0]["full_name"].startswith("workspace.missimi.")
        assert tables[0]["securable_type"] == "TABLE"

    def test_get_by_full_name(self, seeded):
        t = _run(uc.uc_get_table("workspace.missimi.orders"))
        assert t["name"] == "orders" and t["row_count"] == 100

    def test_bad_and_missing(self, seeded):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as bad:
            _run(uc.uc_get_table("a.b"))           # not three-part
        assert bad.value.status_code == 400
        with pytest.raises(HTTPException) as miss:
            _run(uc.uc_get_table("workspace.missimi.ghost"))
        assert miss.value.status_code == 404
