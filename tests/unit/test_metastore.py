"""Phase 2 — the metastore (Catalog + Grant + Schema).

Catalogs are derived from the connection registry. Grants are an independent
access-control layer: the live data-path gate `accessible_catalog_ids()` =
a workspace's connection membership (read live) ∪ its explicit catalog grants. These
tests pin store CRUD + idempotent migration, the catalog sync, and — the headline —
that the gate equals the legacy `workspace_connection_ids()` with no explicit grants
and widens with one.
"""
from __future__ import annotations

import sqlite3

import pytest

from aughor.org import using_org
from aughor.metastore import (
    USAGE,
    accessible_catalog_ids,
    add_grant,
    catalog_securable,
    ensure_catalogs_for_connections,
    explicit_catalog_ids,
    get_catalog,
    grants_for_workspace,
    list_catalogs,
    list_grants,
    revoke_grant,
    upsert_catalog,
    workspace_principal,
)


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    """Hermetic metastore + workspace stores."""
    import aughor.metastore.store as ms_store
    import aughor.workspace.store as ws_store
    monkeypatch.setattr(ms_store, "_DB_PATH", tmp_path / "metastore.db")
    monkeypatch.setattr(ws_store, "_DB_PATH", tmp_path / "workspaces.db")
    return ws_store


# ── store CRUD + migration ────────────────────────────────────────────────────

class TestCatalogStore:
    def test_upsert_get_list_delete(self, stores):
        upsert_catalog("c1", name="One", conn_id="c1")
        assert get_catalog("c1").name == "One"
        upsert_catalog("c1", name="One v2", conn_id="c1")   # idempotent update, not insert
        assert get_catalog("c1").name == "One v2"
        assert len(list_catalogs()) == 1
        from aughor.metastore import delete_catalog
        assert delete_catalog("c1") is True
        assert get_catalog("c1") is None

    def test_org_scoped(self, stores):
        upsert_catalog("c1", name="default-cat")
        with using_org("acme"):
            upsert_catalog("c1", name="acme-cat")
            assert get_catalog("c1").org_id == "acme"
        # same id, different orgs → distinct rows
        assert get_catalog("c1").name == "default-cat"
        with using_org("acme"):
            assert get_catalog("c1").name == "acme-cat"


class TestGrantStore:
    def test_add_is_idempotent_revoke_removes(self, stores):
        p, s = workspace_principal("w1"), catalog_securable("c1")
        add_grant(p, s)
        add_grant(p, s)  # idempotent on (org,principal,securable,privilege)
        assert len(list_grants(principal=p)) == 1
        assert revoke_grant(p, s) is True
        assert list_grants(principal=p) == []

    def test_grants_for_workspace(self, stores):
        add_grant(workspace_principal("w1"), catalog_securable("c1"))
        add_grant(workspace_principal("w1"), catalog_securable("c2"))
        add_grant(workspace_principal("w2"), catalog_securable("c3"))
        assert {g.securable for g in grants_for_workspace("w1")} == {"catalog:c1", "catalog:c2"}


class TestMigrationIdempotent:
    def test_schema_created_and_reopen_clean(self, stores, tmp_path):
        upsert_catalog("c1", name="One")            # creates the DB + tables
        db = tmp_path / "metastore.db"
        cols = lambda t: {r[1] for r in sqlite3.connect(str(db)).execute(f"PRAGMA table_info({t})").fetchall()}
        assert "org_id" in cols("catalogs") and "privilege" in cols("grants")
        # second access re-runs _ensure_schema without error
        assert len(list_catalogs()) == 1


# ── bootstrap reconcile ───────────────────────────────────────────────────────

class TestCatalogSync:
    def test_catalogs_mirror_connections(self, stores, monkeypatch):
        import aughor.db.registry as registry
        monkeypatch.setattr(registry, "list_connections", lambda: [
            {"id": "a1", "name": "Alpha"}, {"id": "b2", "name": "Bravo"},
        ])
        assert ensure_catalogs_for_connections() == 2
        assert {c.id for c in list_catalogs()} == {"a1", "b2"}
        assert get_catalog("a1").name == "Alpha"


# ── the headline: the gate equals the legacy membership gate (no explicit grants) ──

class TestGateParity:
    def test_gate_matches_workspace_membership(self, stores):
        ws_store = stores
        from aughor.workspace.store import workspace_connection_ids
        ws_store.create_workspace(name="Default", workspace_id="default",
                                  connection_ids=["c1", "c2", "c3"], is_default=True)
        ws_store.create_workspace(name="Sales", workspace_id="ws_sales", connection_ids=["c2"])
        ws_store.create_workspace(name="Empty", workspace_id="ws_empty", connection_ids=[])
        # No explicit grants → the gate is exactly the legacy membership gate.
        for ws in ws_store.list_workspaces():
            assert accessible_catalog_ids(ws.id) == workspace_connection_ids(ws.id), ws.id
        assert accessible_catalog_ids(None) is workspace_connection_ids(None) is None
        assert accessible_catalog_ids("unknown") == workspace_connection_ids("unknown") == set()

    def test_non_usage_and_non_explicit_grants_ignored(self, stores):
        stores.create_workspace(name="W", workspace_id="w1", connection_ids=[])
        add_grant(workspace_principal("w1"), catalog_securable("c9"), privilege="ADMIN")
        add_grant(workspace_principal("w1"), catalog_securable("c8"), source="membership")
        # ADMIN ≠ USAGE and source≠explicit → neither widens the gate
        assert explicit_catalog_ids("w1") == set()
        assert accessible_catalog_ids("w1") == set()


class TestSchemaStore:
    def test_upsert_list_and_reconcile(self, stores):
        from aughor.metastore import list_schemas, set_catalog_schemas, upsert_schema
        upsert_schema("c1", "main")
        upsert_schema("c1", "main")   # idempotent
        assert {s.name for s in list_schemas("c1")} == {"main"}
        # reconcile to a new set → one add, one delete
        changed = set_catalog_schemas("c1", ["main", "finance"])
        assert changed == 1 and {s.name for s in list_schemas("c1")} == {"main", "finance"}
        changed = set_catalog_schemas("c1", ["finance"])
        assert changed == 1 and {s.name for s in list_schemas("c1")} == {"finance"}
        assert set_catalog_schemas("c1", ["finance"]) == 0   # idempotent

    def test_full_name_and_securable_roundtrip(self, stores):
        from aughor.metastore import schema_securable, securable_schema, upsert_schema
        s = upsert_schema("cat1", "sales")
        assert s.full_name == "cat1.sales"
        sec = schema_securable("cat1", "sales")
        assert sec == "schema:cat1.sales"
        assert securable_schema(sec) == ("cat1", "sales")
        assert securable_schema("catalog:cat1") is None   # not a schema securable


class TestLiveGate:
    """The gate is `membership ∪ explicit grants`, a pure live read — no reconcile."""

    def test_membership_is_read_live(self, stores):
        ws_store = stores
        from aughor.workspace.store import workspace_connection_ids
        ws_store.create_workspace(name="W", workspace_id="w1", connection_ids=["c1", "c2"])
        assert accessible_catalog_ids("w1") == {"c1", "c2"} == workspace_connection_ids("w1")
        ws_store.update_workspace("w1", connection_ids=["c2", "c3"])
        assert accessible_catalog_ids("w1") == {"c2", "c3"} == workspace_connection_ids("w1")

    def test_explicit_grant_widens_and_revoke_narrows(self, stores):
        ws_store = stores
        ws_store.create_workspace(name="W", workspace_id="w1", connection_ids=["c1"])
        # Grant access to a catalog NOT in membership → the gate widens.
        add_grant(workspace_principal("w1"), catalog_securable("shared"), source="explicit")
        assert accessible_catalog_ids("w1") == {"c1", "shared"}
        # Durable across a membership edit (membership is just one input).
        ws_store.update_workspace("w1", connection_ids=["c1", "c2"])
        assert accessible_catalog_ids("w1") == {"c1", "c2", "shared"}
        # Revoke the explicit grant → back to membership only.
        revoke_grant(workspace_principal("w1"), catalog_securable("shared"))
        assert accessible_catalog_ids("w1") == {"c1", "c2"}

    def test_none_and_fail_closed_semantics(self, stores):
        stores.create_workspace(name="W", workspace_id="w1", connection_ids=["c1"])
        assert accessible_catalog_ids(None) is None          # unscoped
        assert accessible_catalog_ids("nope") == set()       # unknown → fail-closed
        assert accessible_catalog_ids("w1") == {"c1"}


class TestGrantApi:
    """The independent access-control endpoints (grant/revoke/list explicit grants)."""

    def test_grant_revoke_list_roundtrip(self, stores):
        from aughor.routers.metastore import (
            GrantRequest, grant_workspace_catalog, list_workspace_grants, revoke_workspace_catalog,
        )
        stores.create_workspace(name="W", workspace_id="w1", connection_ids=["c1"])
        upsert_catalog("shared", name="Shared", conn_id="shared")
        assert list_workspace_grants("w1")["catalogs"] == []
        assert grant_workspace_catalog("w1", GrantRequest(catalog_id="shared"))["catalogs"] == ["shared"]
        assert list_workspace_grants("w1")["catalogs"] == ["shared"]
        assert accessible_catalog_ids("w1") == {"c1", "shared"}   # the gate widened via the API
        assert revoke_workspace_catalog("w1", "shared")["catalogs"] == []
        assert accessible_catalog_ids("w1") == {"c1"}

    def test_grant_unknown_catalog_404(self, stores):
        from fastapi import HTTPException
        from aughor.routers.metastore import GrantRequest, grant_workspace_catalog
        with pytest.raises(HTTPException) as e:
            grant_workspace_catalog("w1", GrantRequest(catalog_id="ghost"))
        assert e.value.status_code == 404


class TestOrgStamping:
    def test_explicit_grant_stamped_with_org(self, stores):
        with using_org("acme"):
            stores.create_workspace(name="A", workspace_id="wa", connection_ids=["c1"])
            add_grant(workspace_principal("wa"), catalog_securable("extra"), source="explicit")
            g = grants_for_workspace("wa", org_id="acme")
            assert len(g) == 1 and g[0].org_id == "acme" and g[0].source == "explicit"
            assert accessible_catalog_ids("wa") == {"c1", "extra"}
