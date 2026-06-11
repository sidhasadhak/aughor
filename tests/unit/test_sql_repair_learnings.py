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


# ── T2b: Phase-8 Binder-error classes the retry loop used to DROP ─────────────
# Each error string below was reproduced verbatim against DuckDB 1.5.2 (not
# guessed) so the diagnosis regexes match what the engine actually emits.

# the GROUP BY completeness class — column in SELECT/ORDER BY not grouped/aggregated
_GROUPBY_ERR = ('Binder Error: column "order_date" must appear in the GROUP BY clause '
                'or must be part of an aggregate function.')


def test_diag_group_by_completeness_offers_group_or_aggregate():
    d = _make_diagnosis(_GROUPBY_ERR,
                        "SELECT region, SUM(total) FROM orders GROUP BY region ORDER BY order_date", {})
    assert "order_date" in d
    assert "GROUP BY" in d
    # offers BOTH legal repairs, not just one
    assert "ANY_VALUE" in d or "aggregate" in d.lower()
    # and explicitly forbids the wrong "fix" of deleting the column
    assert "exists" in d.lower()


def test_group_by_error_does_not_ban_the_column():
    # the column EXISTS — negative-knowledge harvest must NOT add it to dead refs,
    # or the generator would stop selecting a perfectly real column.
    assert _extract_dead_refs(_GROUPBY_ERR) == set()


# the EXTRACT(EPOCH FROM (date - date)) class — DuckDB lowers it to
# date_part('epoch', BIGINT); same error string as date_part('day', a - b).
_EPOCH_ERR = ("Binder Error: No function matches the given name and argument types "
              "'date_part(STRING_LITERAL, BIGINT)'. You might need to add explicit type casts.")


def test_diag_extract_epoch_on_date_diff_routes_to_date_diff():
    d = _make_diagnosis(_EPOCH_ERR,
                        "SELECT EXTRACT(EPOCH FROM (ship_date - order_date)) FROM orders", {})
    assert "date_diff" in d
    # covers the seconds/epoch intent, not just days
    assert "second" in d.lower()
    assert "EXTRACT" in d


def test_diag_cte_dropped_column_points_at_inner_select():
    # a column dropped by an intermediate CTE — must say "SELECT it out", not ban it
    err = 'Binder Error: Referenced column "order_date" not found in FROM clause!'
    sql = ("WITH agg AS (SELECT customer_id, SUM(total) AS rev FROM orders GROUP BY customer_id) "
           "SELECT customer_id, rev, order_date FROM agg")
    d = _make_diagnosis(err, sql, {})
    assert "order_date" in d and ("SELECT" in d or "subquery" in d.lower())
