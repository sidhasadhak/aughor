"""Platform-generic SQL-repair learnings (not connection/schema specific):
 T1 — negative-knowledge harvest from engine errors (aughor/explorer/agent._extract_dead_refs)
 T2 — repair diagnosis branches for missing-table / unexposed-column / ambiguous / non-inner-join
      (aughor/sql/writer._make_diagnosis)
Driven entirely by DuckDB + Postgres error text, so the learning transfers across connections."""
from aughor.explorer.agent import _extract_dead_refs
from aughor.sql.writer import _make_diagnosis


# ── T1: dead-reference harvest ────────────────────────────────────────────────

def test_dead_refs_duckdb_missing_column():
    assert "region" in _extract_dead_refs('Table "sc" does not have a column named "region"')


def test_dead_refs_duckdb_missing_table():
    assert "oi" in _extract_dead_refs('Binder Error: Referenced table "oi" not found!')


def test_dead_refs_duckdb_unexposed_column():
    assert "order_tier" in _extract_dead_refs(
        'Referenced column "order_tier" not found in FROM clause!')


def test_dead_refs_postgres_column_and_relation():
    assert "region" in _extract_dead_refs('column "region" does not exist')
    assert "orders" in _extract_dead_refs('relation "orders" does not exist')


def test_dead_refs_ignores_ambiguous_column():
    # an ambiguous column EXISTS — it must NOT be banned, only qualified
    assert _extract_dead_refs('Ambiguous reference to column name "item_count"') == set()


def test_dead_refs_empty_and_noise():
    assert _extract_dead_refs("") == set()
    assert _extract_dead_refs("connection reset by peer") == set()


def test_dead_refs_accumulate_union():
    acc = set()
    acc |= _extract_dead_refs('Table "a" does not have a column named "campaign_id"')
    acc |= _extract_dead_refs('Referenced table "ml" not found')
    assert acc == {"campaign_id", "ml"}


# ── T2: repair diagnosis branches ─────────────────────────────────────────────

def test_diag_referenced_table_not_found_suggests_join_or_drop():
    sql = "SELECT oi.qty FROM orders o"
    d = _make_diagnosis('Referenced table "oi" not found!', sql, {})
    assert "oi" in d
    assert "JOIN" in d and "remove" in d.lower()
    assert "orders" in d  # lists the tables actually in the query


def test_diag_unexposed_column_points_at_subquery():
    d = _make_diagnosis('Referenced column "order_tier" not found in FROM clause!',
                        "SELECT order_tier FROM (SELECT 1) s", {})
    assert "order_tier" in d and "subquery" in d.lower()


def test_diag_ambiguous_column_says_qualify():
    d = _make_diagnosis('Binder Error: Ambiguous reference to column name "item_count"',
                        "SELECT item_count FROM o JOIN oi ON o.id=oi.oid", {})
    assert "item_count" in d and "qualif" in d.lower()


def test_diag_postgres_ambiguous_column():
    d = _make_diagnosis('column reference "id" is ambiguous', "SELECT id FROM a JOIN b USING(x)", {})
    assert "qualif" in d.lower()


def test_diag_non_inner_join_on_subquery_suggests_cte():
    d = _make_diagnosis('Not implemented Error: Cannot perform non-inner join on subquery!',
                        "SELECT * FROM a LEFT JOIN (SELECT ...) s ON a.id=s.id", {})
    assert "CTE" in d or "WITH" in d
    assert "INNER" in d


def test_diag_still_handles_plain_missing_column():
    # regression — the pre-existing branch must still win for the common case
    d = _make_diagnosis('Table "im" does not have a column named "id"',
                        "SELECT im.id FROM inventory_movements im", {"inventory_movements": ["movement_id"]})
    assert "does not exist" in d and "movement_id" in d
