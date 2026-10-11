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

            def execute(self, _tag, sql, internal=False):
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


def test_the_tree_reads_its_catalogs_side_by_side_in_their_order(monkeypatch):
    """Read one after another, the first tree waited for the SUM of every warehouse's introspection — 17.1 s measured
    live on 2026-10-09, behind "Loading the catalog…" (the usability walk-through). Side by side it waits for the
    slowest; the order of the catalogs and the one-at-a-time metastore reconcile are unchanged."""
    import asyncio
    import threading
    import time

    import aughor.metastore as ms

    rec = _Recorder()
    monkeypatch.setattr(ms, "set_catalog_schemas", rec)
    monkeypatch.setattr(ms, "accessible_catalog_ids", lambda ws: None)
    ids = ["w", "bq1", "bq2", "sheets"]
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": i, "name": i.upper(), "conn_type": "duckdb"} for i in ids])
    threads: set[str] = set()

    def slow(conn_id, conn_type):
        threads.add(threading.current_thread().name)
        time.sleep(0.4)
        return [{"name": f"{conn_id}_schema", "tables": []}]

    monkeypatch.setattr(catalog_router, "quick_schemas", slow)
    t0 = time.monotonic()
    tree = asyncio.run(catalog_router.get_catalog_tree())
    took = time.monotonic() - t0
    entries = tree["sections"][0]["entries"]
    assert [e["conn_id"] for e in entries] == ids
    assert [e["schemas"][0]["name"] for e in entries] == [f"{i}_schema" for i in ids]
    assert rec.calls == [(i, [f"{i}_schema"]) for i in ids]
    assert took < 1.0, f"{took:.2f}s for four 0.4 s catalogs — read one after another"   # 1.6 s one at a time
    assert len(threads) == 4


# ── a project-wide BigQuery connection names no dataset ───────────────────────────────────────────────────────────

class _Project:
    """A BigQuery connection over a whole project: its datasets listed, each one's `__TABLES__` read."""
    dialect = "bigquery"
    _dataset = ""

    def __init__(self, datasets, unreadable=(), listable=True):
        self._datasets, self._unreadable, self._listable = datasets, set(unreadable), listable
        self.asked: list[str] = []

    def datasets(self, limit=50):
        if not self._listable:
            raise RuntimeError("403 bigquery.datasets.list denied")
        return list(self._datasets)

    def execute(self, _tag, sql, internal=False):
        ds = sql.split("`")[1].split(".")[0]
        self.asked.append(ds)

        class R:
            error = "Not found: dataset" if ds in self._unreadable else None
            rows = [] if ds in self._unreadable else [(ds, f"{ds}_t{i}", str(10 * i)) for i in (1, 2)]
        return R()

    def close(self):
        pass


def test_a_project_wide_bigquery_connection_lists_every_dataset_s_tables_and_skips_one_it_cannot_read(monkeypatch):
    monkeypatch.setattr(catalog_router, "get_meta", lambda cid: {})
    db = _Project(["sales", "ops", "gone"], unreadable=["gone"])
    monkeypatch.setattr(catalog_router, "open_connection_for", lambda cid: db)
    got = catalog_router.quick_schemas("bq", "bigquery")
    assert [(s["name"], [t["name"] for t in s["tables"]]) for s in got] == [
        ("sales", ["sales_t1", "sales_t2"]), ("ops", ["ops_t1", "ops_t2"])]
    assert db.asked == ["sales", "ops", "gone"]


def test_a_project_that_cannot_be_listed_or_read_is_could_not_look_never_nothing_there(monkeypatch):
    monkeypatch.setattr(catalog_router, "get_meta", lambda cid: {})
    monkeypatch.setattr(catalog_router, "open_connection_for", lambda cid: _Project(["a"], listable=False))
    assert catalog_router.quick_schemas("bq", "bigquery") is None
    monkeypatch.setattr(catalog_router, "open_connection_for", lambda cid: _Project(["a", "b"], unreadable=["a", "b"]))
    assert catalog_router.quick_schemas("bq", "bigquery") is None
    monkeypatch.setattr(catalog_router, "open_connection_for", lambda cid: _Project([]))
    assert catalog_router.quick_schemas("bq", "bigquery") == []              # a project with no dataset holds nothing
