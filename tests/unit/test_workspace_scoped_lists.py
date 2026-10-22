"""A workspace is what its pages show, not just what its header counts (the Olist run, 2026-10-22).

Three doors measured that day: the Catalog tree listed every connection in the org inside a
one-connection workspace, Now's briefing list folded every connection's Briefing, and a connection
made for uploads was explored while still empty. Each is pinned here against the resolver the
router gates already share, `aughor.metastore.accessible_catalog_ids` — one authority, not a second.
"""
from __future__ import annotations

import asyncio

import pytest


def _rows(fold: dict) -> list[dict]:
    """The fold's per-connection rows, whatever the list is called."""
    lists = [v for v in fold.values() if isinstance(v, list)]
    assert lists, fold
    return lists[0]


@pytest.fixture
def two_connections(monkeypatch):
    """The org holds c1 and c2; the reader's workspace holds c1 only."""
    import aughor.metastore as ms
    from aughor.routers import catalog as catalog_router
    conns = [
        {"id": "c1", "name": "C1", "conn_type": "duckdb", "builtin": False},
        {"id": "c2", "name": "C2", "conn_type": "duckdb", "builtin": False},
    ]
    monkeypatch.setattr("aughor.db.registry.list_connections", lambda *a, **k: list(conns))
    monkeypatch.setattr(ms, "accessible_catalog_ids", lambda ws: {"c1"})
    monkeypatch.setattr(ms, "set_catalog_schemas", lambda *a, **k: 0)
    monkeypatch.setattr(catalog_router, "get_meta", lambda cid: {})
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda cid: (_ for _ in ()).throw(RuntimeError("no warehouse in this test")))
    return conns


def test_the_catalog_tree_lists_only_the_workspaces_connections(two_connections):
    from aughor.routers import catalog as catalog_router
    tree = asyncio.run(catalog_router.get_catalog_tree(workspace_id="w1"))
    listed = [e["conn_id"] for s in tree["sections"] for e in s["entries"]]
    assert listed == ["c1"], listed


def test_the_organisation_briefing_folds_only_the_workspaces_connections(two_connections, monkeypatch):
    from aughor.briefing import organisation
    # No Briefing is read in this test — the fold's rows are what is under test, not their contents.
    monkeypatch.setattr(organisation, "latest_kept", lambda cid: None)
    names = sorted(r["connection_id"] for r in _rows(organisation.organisation_briefing()))
    assert names == ["c1"], names


def test_the_organisation_briefing_is_unscoped_without_a_workspace(two_connections, monkeypatch):
    import aughor.metastore as ms
    from aughor.briefing import organisation
    monkeypatch.setattr(ms, "accessible_catalog_ids", lambda ws: None)
    monkeypatch.setattr(organisation, "latest_kept", lambda cid: None)
    names = sorted(r["connection_id"] for r in _rows(organisation.organisation_briefing()))
    assert names == ["c1", "c2"], names


def test_a_new_uploads_connection_is_not_explored_while_empty(monkeypatch):
    """`POST /connections` with conn_type local_upload: born empty, so the explorer waits for the first upload."""
    from aughor.routers import connections as conn_router

    class _Db:
        def test(self): return True, "ok"
        def close(self): pass

    monkeypatch.setattr(conn_router, "open_connection", lambda *a, **k: _Db())
    monkeypatch.setattr(conn_router, "add_connection", lambda **k: "u1")
    monkeypatch.setattr("aughor.util.idempotency.lookup", lambda *a, **k: None)
    monkeypatch.setattr("aughor.util.idempotency.remember", lambda *a, **k: None)
    started: list[str] = []
    monkeypatch.setattr(conn_router, "_kickoff_exploration", lambda cid, **k: started.append(cid) or True)

    req = conn_router.AddConnectionRequest(name="Olist uploads", conn_type="local_upload", dsn="local://",
                                           workspace_id="w1")
    out = asyncio.run(conn_router.create_connection(req, idempotency_key=None))
    assert out["id"] == "u1" and out["exploring"] is False
    assert started == [], "an empty uploads space was sent to the explorer"

    other = conn_router.AddConnectionRequest(name="Postgres", conn_type="postgres", dsn="postgresql://x")
    asyncio.run(conn_router.create_connection(other, idempotency_key=None))
    assert started == ["u1"], "a warehouse connection must still be explored on creation"
