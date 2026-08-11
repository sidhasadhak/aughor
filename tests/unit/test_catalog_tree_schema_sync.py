"""A failed introspection must not delete the catalog's schemas.

`/catalog/tree` reconciles the metastore to whatever introspection returns, and
`_quick_schemas` returned `[]` on ANY exception. So a connection that could not be
opened reported "no schemas", and the reconcile — which deletes what is absent —
removed every schema row that catalog had. A GET destroying metadata because a
database blinked.

It self-repaired on the next successful request, which is why it never surfaced as
an error: the damage showed up as WRITE CHURN. Measured in production,
`store_metastore` had 1701 writes against single digits for every other store.

"I could not look" and "there is nothing there" are different answers, and the bug
was giving them the same value.
"""
from __future__ import annotations

import pytest

from aughor.routers import catalog as catalog_router


class _Recorder:
    """Stands in for the metastore reconcile, recording what it was asked to set."""

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, catalog_id, names, org_id=None):
        self.calls.append((catalog_id, list(names)))
        return len(names)


@pytest.fixture
def wiring(monkeypatch):
    """One connection, introspection stubbed per test."""
    import aughor.metastore as ms

    rec = _Recorder()
    monkeypatch.setattr(ms, "set_catalog_schemas", rec)
    monkeypatch.setattr(catalog_router, "get_meta", lambda cid: {})
    monkeypatch.setattr(
        "aughor.db.registry.list_connections",
        lambda *a, **k: [{"id": "c1", "name": "C1", "conn_type": "duckdb", "builtin": False}],
    )
    monkeypatch.setattr(ms, "accessible_catalog_ids", lambda ws: None)
    return rec


def _tree(monkeypatch, *, schemas):
    """Run the tree build with `_quick_schemas` forced to a given outcome."""
    import asyncio

    async def _run():
        # The router builds _quick_schemas as a closure, so drive the endpoint and
        # replace the connection open it depends on.
        return await catalog_router.get_catalog_tree()

    if schemas is RuntimeError:
        def _boom(conn_id):
            raise RuntimeError("connection refused")
        monkeypatch.setattr(catalog_router, "open_connection_for", _boom)
    else:
        class _DB:
            dialect = "duckdb"

            def execute(self, _tag, sql):
                class R:
                    rows = ([("main", t, 0)] if "information_schema" in sql else [])
                if "current_database" in sql:
                    class R2:
                        rows = [("memory",)]
                    return R2()
                return R()

            def close(self):
                pass

        t = schemas
        monkeypatch.setattr(catalog_router, "open_connection_for", lambda cid: _DB())

    return asyncio.run(_run())


def test_a_failed_introspection_does_not_reconcile_anything(wiring, monkeypatch):
    """The bug: an unopenable connection reported [] and the reconcile deleted the
    catalog's every schema row."""
    _tree(monkeypatch, schemas=RuntimeError)

    assert wiring.calls == [], (
        f"introspection failed and the metastore was still reconciled to {wiring.calls}"
        " — that call deletes what is absent")


def test_a_successful_introspection_still_reconciles(wiring, monkeypatch):
    """The guard must not disable the sync it protects."""
    _tree(monkeypatch, schemas=["main"])

    assert len(wiring.calls) == 1, "a healthy introspection stopped syncing the metastore"
    assert wiring.calls[0][0] == "c1"


def test_a_failed_introspection_still_renders_the_catalog(wiring, monkeypatch):
    """Degrade, don't disappear — the connection stays listed with no schemas."""
    tree = _tree(monkeypatch, schemas=RuntimeError)

    entries = tree["sections"][0]["entries"]
    assert len(entries) == 1
    assert entries[0]["conn_id"] == "c1"
    assert entries[0]["schemas"] == []
