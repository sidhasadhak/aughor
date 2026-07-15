"""R7 — deterministic unique-output-column aliasing, wired into preflight_repair.

LLM SQL that emits colliding output names (`SELECT a.id, b.id`, a reused `AS total`)
yields a result with duplicate column names; every name-keyed consumer downstream
silently keeps one. The compile pass renames the later duplicates; preflight adopts
it dry-run-gated. Pure AST, fail-open.
"""
from __future__ import annotations

from aughor.sql.aliases import uniquify_output_columns as U
from aughor.sql import safety


# ── the pure AST pass ─────────────────────────────────────────────────────────

def test_duplicate_column_names_get_suffixed():
    assert U("SELECT a.id, b.id FROM a JOIN b USING(k)") == \
        "SELECT a.id, b.id AS id_1 FROM a JOIN b USING (k)"


def test_reused_alias_gets_suffixed():
    out = U("SELECT SUM(x) AS total, SUM(y) AS total FROM t")
    assert "SUM(x) AS total" in out and "SUM(y) AS total_1" in out


def test_three_way_collision_increments():
    out = U("SELECT a.id, b.id, c.id FROM a, b, c")
    assert "b.id AS id_1" in out and "c.id AS id_2" in out


def test_pre_existing_suffix_is_reserved():
    # id, id, and an explicit id_1 → the 2nd id must skip the taken id_1 → id_2.
    out = U("SELECT a.id, b.id, c.x AS id_1 FROM a, b, c")
    assert "b.id AS id_2" in out
    assert out.count(" AS id_1") == 1   # the original id_1 is untouched


def test_no_duplicates_returns_none():
    assert U("SELECT a.x, b.y FROM a JOIN b USING(k)") is None


def test_select_star_is_skipped():
    assert U("SELECT * FROM t") is None


def test_qualified_star_is_skipped():
    assert U("SELECT t.*, 1 AS n FROM t") is None


def test_count_star_is_not_treated_as_a_star():
    # COUNT(*) carries a normal output name; a dup of it still uniquifies.
    assert U("SELECT COUNT(*) AS c, COUNT(*) AS c FROM t") == \
        "SELECT COUNT(*) AS c, COUNT(*) AS c_1 FROM t"


def test_set_operation_is_skipped():
    assert U("SELECT id FROM a UNION SELECT id FROM b") is None


def test_parse_failure_returns_none():
    assert U("this is not sql {{{") is None


def test_only_outer_select_columns_count():
    # The subquery's internal duplicate names are not user-visible → the single outer
    # column has no collision → nothing to do.
    assert U("SELECT s.id FROM (SELECT a.id, b.id FROM a JOIN b USING(k)) s") is None


# ── wired into preflight_repair (dry-run-gated adoption + receipt) ─────────────

class _FakeConn:
    dialect = "duckdb"

    def dry_run(self, sql):
        return (True, None)   # every candidate binds → adoption is gated only on the rewrite


def test_preflight_adopts_uniquified_sql_and_records_receipt():
    out, receipt = safety.preflight_repair(
        _FakeConn(), "SELECT a.id, b.id FROM a JOIN b USING(k)", schema=None)
    assert receipt["aliases_uniquified"] is True
    assert "id_1" in out


def test_preflight_leaves_clean_sql_unchanged():
    sql = "SELECT a.x, b.y FROM a JOIN b USING(k)"
    out, receipt = safety.preflight_repair(_FakeConn(), sql, schema=None)
    assert receipt["aliases_uniquified"] is False
    assert "id_1" not in out


def test_preflight_uniquifies_on_a_real_connection():
    """End-to-end on a real DuckDB connection: the aliased SQL genuinely binds
    (real dry_run) and executes with two DISTINCT output column names."""
    from pathlib import Path
    import duckdb
    from aughor.db.connection import DuckDBConnection

    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "t"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE a (id INT, k INT)")
    conn._conn.execute("CREATE TABLE b (id INT, k INT)")

    out, receipt = safety.preflight_repair(
        conn, "SELECT a.id, b.id FROM a JOIN b USING(k)", schema=None)
    assert receipt["aliases_uniquified"] is True
    assert receipt["dry_run_ok"] is True                       # the rewrite really binds
    names = [d[0] for d in conn._conn.execute(out).description]
    assert names == ["id", "id_1"]                             # distinct, name-addressable

