"""The catalog said "0 rows" for every table, and the real number was two lines away.

`/catalog/tree` reported `row_count` 0 for all 79 tables across five connections. The
DuckDB path selected a LITERAL zero out of `information_schema.tables`, and the query
that reads the true value — `estimated_size` from `duckdb_tables()` — sat directly
below it behind `if not rows:`. `information_schema` always returns rows, so the
correct path was unreachable dead code. Ground truth at the time: `superstore.orders`
`COUNT(*)` = 9,994, `estimated_size` = 9994. The number was fetched and thrown away.

The uploads path had the same shape for a different reason: it hardcoded 0 because it
deliberately never opens the connection (that open cost 9.56s of a 9.87s tree). Not
opening is right; rendering the placeholder as a measurement is not.

Both are the same rule — **unknown is never zero**. Zero is a measurement, reserved
for tables that are actually empty. Anything we did not count reads "—".

One trap runs underneath all of it: the connector layer stringifies every cell and
renders SQL NULL as the literal string "NULL", so these values arrive as text, never
as `None`. A fix that only changed the SQL would have shipped the string "NULL" on a
wire whose declared type is `number | null`.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.routers import catalog as catalog_router


# ── the connector's own value shapes ────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("9994", 9994),          # what a real estimate looks like on the wire
    (9994, 9994),            # ... and if a driver ever hands back a real int
    ("NULL", None),          # the connector's rendering of SQL NULL — NOT a number
    ("null", None),
    ("", None),
    (None, None),
    ("0", 0),                # a genuinely empty table keeps its measured zero
    ("9994.0", 9994),        # DECIMAL-typed estimates
    ("not-a-number", None),
])
def test_as_count_keeps_unknown_unknown(raw, expected):
    assert catalog_router._as_count(raw) == expected


# ── harness ─────────────────────────────────────────────────────────────────────

class _DB:
    """A DuckDB-shaped connection whose two catalog queries are set per test."""

    dialect = "duckdb"

    def __init__(self, *, info_rows, size_rows, sizes_raise=False):
        self._info_rows = info_rows
        self._size_rows = size_rows
        self._sizes_raise = sizes_raise
        self.queries: list[str] = []

    def execute(self, _tag, sql):
        self.queries.append(sql)

        class _R:
            rows: list = []

        if "current_database" in sql:
            _R.rows = [("memory",)]
        elif "duckdb_tables()" in sql:
            if self._sizes_raise:
                raise RuntimeError("duckdb_tables() unavailable on this engine")
            _R.rows = self._size_rows
        else:
            _R.rows = self._info_rows
        return _R()

    def close(self):
        pass


@pytest.fixture
def one_duckdb_connection(monkeypatch):
    """A single DuckDB catalog, with the metastore reconcile neutered."""
    import aughor.metastore as ms

    monkeypatch.setattr(ms, "set_catalog_schemas", lambda *a, **k: 0)
    monkeypatch.setattr(ms, "accessible_catalog_ids", lambda ws: None)
    monkeypatch.setattr(catalog_router, "get_meta", lambda cid: {})
    monkeypatch.setattr(
        "aughor.db.registry.list_connections",
        lambda *a, **k: [{"id": "c1", "name": "C1", "conn_type": "duckdb", "builtin": False}],
    )

    def _install(db):
        monkeypatch.setattr(catalog_router, "open_connection_for", lambda cid: db)
        return asyncio.run(catalog_router.get_catalog_tree())

    return _install


def _tables(tree, conn=0, schema=0):
    return tree["sections"][0]["entries"][conn]["schemas"][schema]["tables"]


# ── the regression itself ───────────────────────────────────────────────────────

def test_duckdb_reports_the_real_estimate_not_a_literal_zero(one_duckdb_connection):
    """The bug: 9,994 rows was read by the engine and replaced with 0 on the way out."""
    tree = one_duckdb_connection(_DB(
        # information_schema carries the names and a NULL third column, stringified.
        info_rows=[("main", "orders", "NULL"), ("main", "regional_managers", "NULL")],
        size_rows=[("main", "orders", "9994"), ("main", "regional_managers", "4")],
    ))

    counts = {t["name"]: t["row_count"] for t in _tables(tree)}
    assert counts == {"orders": 9994, "regional_managers": 4}, (
        f"the estimate never reached the response: {counts}")
    assert all(isinstance(v, int) for v in counts.values()), (
        "row_count must be a number — web/lib/api.ts declares `number | null`")


def test_a_table_with_no_estimate_reads_unknown_not_zero(one_duckdb_connection):
    """information_schema lists it, duckdb_tables() has no size for it."""
    tree = one_duckdb_connection(_DB(
        info_rows=[("main", "orders", "NULL"), ("main", "a_view_like_thing", "NULL")],
        size_rows=[("main", "orders", "9994")],
    ))

    counts = {t["name"]: t["row_count"] for t in _tables(tree)}
    assert counts["a_view_like_thing"] is None, (
        "an unmeasured table claimed to be empty — unknown is never zero")
    assert counts["orders"] == 9994


def test_a_measured_empty_table_keeps_its_zero(one_duckdb_connection):
    """The fix must not make real emptiness unreadable."""
    tree = one_duckdb_connection(_DB(
        info_rows=[("main", "staging_scratch", "NULL")],
        size_rows=[("main", "staging_scratch", "0")],
    ))

    assert _tables(tree)[0]["row_count"] == 0, "a genuinely empty table lost its measurement"


def test_losing_the_estimates_never_costs_the_listing(one_duckdb_connection):
    """Degrade, don't disappear — the counts are an enrichment, not the query."""
    db = _DB(
        info_rows=[("main", "orders", "NULL"), ("main", "returns", "NULL")],
        size_rows=[],
        sizes_raise=True,
    )
    tree = one_duckdb_connection(db)

    tables = _tables(tree)
    assert [t["name"] for t in tables] == ["orders", "returns"], (
        "an engine without duckdb_tables() lost its table names")
    assert all(t["row_count"] is None for t in tables)


def test_the_estimate_query_is_scoped_to_the_current_database(one_duckdb_connection):
    """MotherDuck's duckdb_tables() leaks every attached DB — the scope is the guard
    that keeps a same-named table in another database from supplying the count."""
    db = _DB(info_rows=[("main", "orders", "NULL")], size_rows=[("main", "orders", "9994")])
    one_duckdb_connection(db)

    sized = [q for q in db.queries if "duckdb_tables()" in q]
    assert sized, "the estimate query never ran"
    assert "database_name = 'memory'" in sized[0], (
        f"duckdb_tables() was not scoped to the current database: {sized[0]}")


def test_the_names_query_no_longer_selects_a_literal_zero(one_duckdb_connection):
    """A rot guard on the exact line that caused this: `SELECT ..., 0`."""
    db = _DB(info_rows=[("main", "orders", "NULL")], size_rows=[("main", "orders", "9994")])
    one_duckdb_connection(db)

    names_q = [q for q in db.queries if "information_schema.tables" in q.lower()]
    assert names_q, "the names query never ran"
    assert "table_name, 0" not in names_q[0], (
        "the literal zero is back in the names query — it shadows the real estimate")


# ── the uploads path ────────────────────────────────────────────────────────────

def test_uploads_report_unknown_without_paying_to_open_the_connection(monkeypatch):
    """The 9.56s open stays avoided; the placeholder stops posing as a measurement."""
    import aughor.metastore as ms

    monkeypatch.setattr(ms, "set_catalog_schemas", lambda *a, **k: 0)
    monkeypatch.setattr(ms, "accessible_catalog_ids", lambda ws: None)
    monkeypatch.setattr(catalog_router, "get_meta", lambda cid: {})
    monkeypatch.setattr(
        "aughor.db.registry.list_connections",
        lambda *a, **k: [{"id": "ws", "name": "Workspace",
                          "conn_type": "local_upload", "builtin": True}],
    )
    monkeypatch.setattr(
        "aughor.connectors.file.local_upload.uploaded_tables",
        lambda cid, meta: {"default": ["orders", "returns"]},
    )

    def _must_not_open(conn_id):
        raise AssertionError(
            "the uploads listing opened the connection — that open is the 9.56s "
            "this path exists to avoid")

    monkeypatch.setattr(catalog_router, "open_connection_for", _must_not_open)

    tree = asyncio.run(catalog_router.get_catalog_tree())

    tables = _tables(tree)
    assert [t["name"] for t in tables] == ["orders", "returns"]
    assert all(t["row_count"] is None for t in tables), (
        "uploads still claim 0 rows — not measured is not empty")
