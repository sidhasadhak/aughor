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


# ── E1-quoted-identifier: `WHERE 'id' = 165428` ───────────────────────────────────
#
# Reported from the SQL editor on a live BigQuery run (2026-09-02): the badge read
# "Guards clean" and the warehouse then refused the job with "No matching signature for
# operator =". The badge was honest about what it checks — fan-out, value-domain, grain,
# trust, never syntax — and still read as a clean bill of health on a query that could not
# run, because `E1-text-numeric-compare` requires a Column on one side and quoting `id`
# turned it into a three-character string. Nothing in the battery looked at the case where
# the column reference was never a column.
#
# The severity is not the BigQuery error. A strict engine refusing is the SAFE outcome; a
# coercing one runs the query, the predicate is a constant that is always false, and the
# analyst reads zero rows as a fact about the world.

_BUG = "SELECT * FROM order_items WHERE 'id' = 165428"


def _quoted(sql: str, col_types=None):
    return [f for f in run_trust_checks(sql, col_types=col_types, dialect="bigquery")
            if f.pattern == "E1-quoted-identifier"]


def test_the_reported_query_is_caught():
    hits = _quoted(_BUG)
    assert len(hits) == 1
    assert hits[0].subject == "id"


def test_it_fires_whichever_side_the_quoted_word_is_on():
    assert _quoted("SELECT * FROM t WHERE 165428 = 'id'")


def test_it_fires_on_range_comparisons_too_not_only_equality():
    assert _quoted("SELECT * FROM t WHERE 'created_at' > 20240101")


def test_the_caveat_names_the_ZERO_ROW_outcome_not_only_the_engine_error():
    """The engine error is the safe half. A caveat that mentioned only "BigQuery rejects
    this" would leave a reader on DuckDB believing the guard did not apply to them."""
    msg = _quoted(_BUG)[0].message
    assert "zero rows" in msg


def test_column_types_SHARPEN_the_suggestion_but_are_not_required():
    """The module's rule is that the text/numeric checks skip rather than guess. This one
    has nothing to guess about — two literals compared is a bug whatever the schema says —
    so types only improve the wording, and their absence must not silence it."""
    with_types = _quoted(_BUG, {"order_items.id": "INT64"})[0].message
    without = _quoted(_BUG)[0].message
    assert "Did you mean the column `id`" in with_types
    assert "If `id` is a column, remove the quotes" in without


# ── precision: the idioms it must never flag ──────────────────────────────────────

def test_the_1_equals_1_placeholder_is_not_flagged():
    """Idiomatic in generated SQL. Numeric vs numeric is not a type mismatch."""
    assert not _quoted("SELECT * FROM t WHERE 1 = 1")


def test_an_ordinary_string_filter_is_not_flagged():
    assert not _quoted("SELECT * FROM t WHERE status = 'shipped'")
    assert not _quoted("SELECT * FROM t WHERE zip = '02134'")


def test_string_compared_to_string_is_left_alone():
    """Ambiguous — could be a deliberate constant. Precision over reach."""
    assert not _quoted("SELECT * FROM t WHERE 'a' = 'b'")


def test_an_explicit_cast_is_not_flagged():
    assert not _quoted("SELECT * FROM t WHERE CAST(id AS STRING) = '5'")


def test_a_quoted_word_outside_a_comparison_is_not_flagged():
    assert not _quoted("SELECT 'id' AS label FROM t")
    assert not _quoted("SELECT * FROM t WHERE status IN ('a','b')")
