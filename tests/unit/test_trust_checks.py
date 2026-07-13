"""Tests for CIDR-E1 result-trust checks (aughor/sql/trust_checks.py).

Contract: deterministic, execution-free caveats for the function-semantics footguns that silently
return wrong rows — timestamp-vs-date-literal boundary, lexicographic ordering of numeric text,
text-vs-numeric comparison. Emit labelled findings; never raise; never guess when types are absent.
"""
from __future__ import annotations

from aughor.sql.trust_checks import run_trust_checks


def _patterns(sql, **kw):
    return {f.pattern for f in run_trust_checks(sql, **kw)}


# ── E1 date-boundary ───────────────────────────────────────────────────────────

def test_date_boundary_lte_on_timestamp_by_name_heuristic():
    sql = "SELECT * FROM events WHERE created_at <= '2024-01-31'"
    assert "E1-date-boundary" in _patterns(sql)        # _at name → treated as timestamp


def test_date_boundary_between_on_timestamp_by_type():
    sql = "SELECT * FROM e WHERE e.occurred BETWEEN '2024-01-01' AND '2024-01-31'"
    ct = {"e.occurred": "TIMESTAMP"}
    assert "E1-date-boundary" in _patterns(sql, col_types=ct)


def test_no_date_boundary_for_real_date_column():
    # a DATE column compared to a date literal is correct — must NOT flag
    sql = "SELECT * FROM o WHERE o.order_date <= '2024-01-31'"
    assert "E1-date-boundary" not in _patterns(sql, col_types={"o.order_date": "DATE"})


def test_no_date_boundary_for_date_named_column_heuristic():
    sql = "SELECT * FROM o WHERE order_date <= '2024-01-31'"     # _date → DATE-like, no flag
    assert _patterns(sql) == set()


# ── E1 lexicographic order ─────────────────────────────────────────────────────

def test_lexicographic_max_over_numeric_text():
    sql = "SELECT MAX(rf) FROM labs"
    assert "E1-lexicographic-order" in _patterns(sql, col_types={"labs.rf": "VARCHAR"})


def test_lexicographic_order_by_numeric_text():
    sql = "SELECT id FROM t ORDER BY amount DESC"
    assert "E1-lexicographic-order" in _patterns(sql, col_types={"t.amount": "TEXT"})


def test_no_lexicographic_flag_for_plain_text_name():
    # text column with a non-numeric name (e.g. a real name) should not be flagged
    sql = "SELECT id FROM t ORDER BY name"
    assert "E1-lexicographic-order" not in _patterns(sql, col_types={"t.name": "VARCHAR"})


def test_no_lexicographic_flag_without_types():
    sql = "SELECT MAX(rf) FROM labs"
    assert "E1-lexicographic-order" not in _patterns(sql)        # never guess without types


# ── E1 text-numeric comparison ─────────────────────────────────────────────────

def test_text_numeric_comparison_flagged():
    sql = "SELECT id FROM exam WHERE rf < 20"
    assert "E1-text-numeric-compare" in _patterns(sql, col_types={"exam.rf": "VARCHAR"})


def test_text_numeric_comparison_needs_types():
    sql = "SELECT id FROM exam WHERE rf < 20"
    assert "E1-text-numeric-compare" not in _patterns(sql)


def test_clean_query_has_no_findings():
    sql = "SELECT id FROM orders WHERE status = 'shipped' ORDER BY id"
    assert run_trust_checks(sql, col_types={"orders.status": "VARCHAR", "orders.id": "INTEGER"}) == []


def test_unparseable_returns_empty_not_raise():
    assert run_trust_checks("@@@ not sql @@@") == []


# ── connection_column_types (WP-1f live col-types; hardened after code review) ──

def _mem_conn(conn_id, ddl):
    import duckdb
    from pathlib import Path
    from aughor.db.connection import DuckDBConnection
    c = DuckDBConnection.__new__(DuckDBConnection)
    c._path = Path(":memory:"); c._conn = duckdb.connect(":memory:")
    c._connection_id = conn_id; c._schema_name = None
    c._conn.execute(ddl)
    return c


def test_connection_column_types_not_truncated_over_500_columns():
    """A wide schema (>500 columns) must resolve ALL types — the introspection goes through
    execute_bounded, not the 500-row answer cap that would drop most columns and revert the
    E1 checks to the name heuristic (the WP-1f false positive)."""
    from aughor.sql import trust_checks
    trust_checks._COLTYPE_CACHE.clear()
    cols = ", ".join(f"c{i} INTEGER" for i in range(600))
    ct = trust_checks.connection_column_types("wide", _mem_conn("wide", f"CREATE TABLE t ({cols})"))
    # 600 table.col keys + 600 bare-col keys; the point is >500 survived (no truncation).
    assert sum(1 for k in ct if k.startswith("t.")) == 600


def test_connection_column_types_does_not_cache_transient_failure():
    """A failed introspection returns {} but is NOT cached — a later call retries instead of
    pinning the connection to the name heuristic for the whole process."""
    from aughor.sql import trust_checks
    trust_checks._COLTYPE_CACHE.clear()

    class _FailDB:
        _path = "/x/fail.db"
        def execute_bounded(self, *a, **k):
            raise RuntimeError("warehouse unreachable")

    assert trust_checks.connection_column_types("flaky", _FailDB()) == {}
    assert "flaky" not in trust_checks._COLTYPE_CACHE          # not pinned
    # Recovery: a subsequent successful scan on the same id now populates.
    ct = trust_checks.connection_column_types("flaky", _mem_conn("flaky", "CREATE TABLE t (a DATE)"))
    assert ct.get("t.a") == "DATE"


def test_connection_column_types_caches_id_less_by_path():
    """An id-less connection (empty _connection_id, e.g. the fixture) still caches — keyed by
    its path — instead of re-scanning information_schema on every answer."""
    from aughor.sql import trust_checks
    trust_checks._COLTYPE_CACHE.clear()
    conn = _mem_conn("", "CREATE TABLE t (a INT)")
    conn._path = "data/some_fixture.duckdb"                    # a stable path stands in as the key
    trust_checks.connection_column_types("", conn)
    assert "data/some_fixture.duckdb" in trust_checks._COLTYPE_CACHE
