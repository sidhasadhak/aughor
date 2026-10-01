"""A duration between two timestamps that run backwards on a real share of rows is named.

Measured 2026-10-01 on theLook: in multi-item orders, 19,360 of 33,272 `order_items` rows are
recorded as shipped before they were created. The Agent's fulfilment answer of 2026-09-29 took
its durations from those columns and published 3.12 days; the orders took 3.98. The SQL was
correct and nothing said the rows were not.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import sqlglot

from aughor.db.connection import DuckDBConnection
from aughor.sql import time_order_guard as T
from aughor.sql.executor import execute_guarded

SHIP = "SELECT AVG(date_diff('hour', created_at, shipped_at)) AS hours FROM items"


def _conn(inverted: int, total: int = 10):
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE items (id INT, created_at TIMESTAMP, shipped_at TIMESTAMP)")
    for i in range(total):
        ship = "2026-01-01 08:00" if i < inverted else "2026-01-03 08:00"
        conn._conn.execute(f"INSERT INTO items VALUES ({i}, TIMESTAMP '2026-01-02 08:00', TIMESTAMP '{ship}')")
    return conn


def test_a_duration_that_runs_backwards_is_named_with_its_share():
    r = execute_guarded(_conn(inverted=3), SHIP, query_id="q")
    assert not r.error
    assert ("time-order guard: shipped_at is earlier than created_at on 30.0% of the rows measured "
            "(3 of 10)") in " ".join(r.caveats)
    assert "guarded:time-order" in r.doors


def test_an_ordered_duration_says_nothing_and_a_statement_without_one_is_not_probed():
    r = execute_guarded(_conn(inverted=0), SHIP, query_id="q")
    assert not any("time-order" in c for c in r.caveats)
    assert "guarded:time-order" in r.doors
    r = execute_guarded(_conn(inverted=3), "SELECT COUNT(*) AS n FROM items", query_id="q")
    assert not any("time-order" in d for d in r.doors)


def test_the_threshold_is_one_percent_of_the_rows_measured():
    below = T.time_order_check(_conn(inverted=0, total=200), SHIP, "duckdb")
    at = T.time_order_check(_conn(inverted=2, total=200), SHIP, "duckdb")
    assert below.findings == []
    assert [(f.inverted, f.measured) for f in at.findings] == [(2, 200)]


FULFIL = ("SELECT dc.name, AVG(DATE_DIFF(CAST(oi.shipped_at AS DATE), CAST(oi.created_at AS DATE), DAY)) AS d "
          "FROM order_items oi JOIN inventory_items ii ON oi.inventory_item_id = ii.id "
          "JOIN distribution_centers dc ON ii.product_distribution_center_id = dc.id "
          "WHERE oi.shipped_at IS NOT NULL GROUP BY 1 ORDER BY d DESC")


def test_the_probe_counts_the_statements_own_rows_without_its_grouping():
    """The 2026-09-29 fulfilment statement, as it ran on BigQuery."""
    tree = sqlglot.parse_one(FULFIL, read="bigquery")
    [(scope, pairs)] = T.duration_pairs(tree)
    assert [(e.sql(), s.sql()) for e, s in pairs] == [("oi.shipped_at", "oi.created_at")]
    probe = T.probe_sql(tree, scope, pairs, "bigquery")
    assert "oi.shipped_at < oi.created_at" in probe and "JOIN distribution_centers" in probe
    assert "WHERE NOT oi.shipped_at IS NULL" in probe or "WHERE oi.shipped_at IS NOT NULL" in probe
    assert "GROUP BY" not in probe and "ORDER BY" not in probe


def test_a_duration_inside_a_cte_is_probed_with_the_ctes():
    sql = ("WITH d AS (SELECT order_id, TIMESTAMP_DIFF(shipped_at, created_at, HOUR) AS h FROM orders), "
           "m AS (SELECT order_id FROM d) SELECT AVG(h) FROM d JOIN m USING (order_id)")
    tree = sqlglot.parse_one(sql, read="bigquery")
    [(scope, pairs)] = T.duration_pairs(tree)
    probe = T.probe_sql(tree, scope, pairs, "bigquery")
    assert probe.startswith("WITH d AS") and "shipped_at < created_at" in probe


def test_a_probe_that_fails_is_unchecked_not_clean():
    conn = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(error="Access Denied", rows=[]))
    run = T.time_order_check(conn, SHIP, "duckdb")
    assert run.findings == [] and run.door == "unchecked:time-order"
    assert "Access Denied" in run.caveats()[0]


# ── The analyst's evidence carries the result's size and what its guards said ─────────

def test_the_analyst_records_the_results_size_and_its_caveats():
    from aughor.agent.analyst import AnalystTurn, _record_evidence
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": "q", "investigation_phases": []})
    result = {"columns": ["cohort", "n"], "rows": [["2025-01", 3]] * 20, "row_count": 720,
              "truncated": True, "caveats": ["time-order guard: shipped_at is earlier than created_at …"]}
    _record_evidence(turn, {"sql": "SELECT 1"}, result)
    f = turn.state["investigation_phases"][-1]["findings"][0]
    assert f["row_count"] == 720 and len(f["rows"]) == 20
    assert f["trust_caveat"].startswith("time-order guard:")


# ── The warning points to the record the rows belong to, before dropping any ─────────

def _with_parent(parent: bool):
    conn = _conn(inverted=3)
    # Column types are cached per connection id, and every fixture here is "test": its own id,
    # so the lookup sees THIS fixture's tables.
    import uuid
    conn._connection_id = f"time-order-{uuid.uuid4().hex[:8]}"
    if parent:
        conn._conn.execute("CREATE TABLE orders (id INT, created_at TIMESTAMP, shipped_at TIMESTAMP)")
    return conn


def test_the_warning_names_the_table_that_carries_the_same_two_timestamps():
    r = execute_guarded(_with_parent(True), SHIP, query_id="q")
    text = " ".join(r.caveats)
    assert ("Measure from the record each items row belongs to first — orders also carries "
            "shipped_at and created_at; leaving the backwards rows out keeps only the ones whose "
            "timestamps happen to agree.") in text


def test_without_such_a_table_it_still_says_parent_first():
    r = execute_guarded(_with_parent(False), SHIP, query_id="q")
    assert ("Measure from the timestamps of the record each items row belongs to, if it carries "
            "its own; leaving the backwards rows out") in " ".join(r.caveats)


# ── A query re-run to correct a flagged one replaces it on the page ───────────────────

def _record(turn, columns, caveats):
    from aughor.agent.analyst import _record_evidence
    _record_evidence(turn, {"sql": "SELECT 1"}, {"columns": columns, "rows": [["a", 1]],
                                                 "row_count": 1, "caveats": caveats})
    turn.phase_tools_run.append("run_sql")


def test_a_corrected_rerun_hides_the_flagged_result_and_nothing_else():
    from aughor.agent.analyst import AnalystTurn
    from aughor.agent.investigate import _evidence_confidence_ceiling
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": "q", "investigation_phases": []})
    _record(turn, ["centre", "days"], ["time-order guard: shipped_at is earlier than created_at …"])
    _record(turn, ["month", "days"], [])                       # a different cut: stays
    _record(turn, ["centre", "days"], [])                       # the corrected re-run
    first, other, fixed = turn.state["investigation_phases"]
    assert first["_hidden"] and first["superseded_by"] == fixed["phase_id"]
    assert not other.get("_hidden") and not fixed.get("_hidden")
    # the replaced result's warning no longer caps the answer shown without it
    assert _evidence_confidence_ceiling(turn.state["investigation_phases"])[0] == "HIGH"


def test_a_rerun_that_is_flagged_too_replaces_nothing():
    from aughor.agent.analyst import AnalystTurn
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": "q", "investigation_phases": []})
    _record(turn, ["centre", "days"], ["time-order guard: …"])
    _record(turn, ["centre", "days"], ["time-order guard: …"])
    assert not any(p.get("_hidden") for p in turn.state["investigation_phases"])


# ── A statement that filters the backwards rows out is told how many it left (2026-10-01) ─

LEFT_OUT = SHIP.replace("FROM items", "FROM items WHERE shipped_at >= created_at")


def test_a_filter_that_drops_the_backwards_rows_is_named_with_what_it_left_out():
    """Told to measure from `orders`, the Agent re-ran its fulfilment query with exactly this
    filter. Counted over the filtered rows the guard found nothing, and the re-run replaced the
    flagged result at HIGH confidence — ship times 1 to 4.4 hours short per centre."""
    r = execute_guarded(_conn(inverted=3), LEFT_OUT, query_id="q")
    assert not r.error
    assert ("time-order guard: the statement leaves out the rows where shipped_at is earlier than "
            "created_at — 30.0% of the rows it would measure (3 of 10) — so its result covers only "
            "the rows whose timestamps happen to agree.") in " ".join(r.caveats)


def test_every_spelling_of_the_filter_is_read_and_a_filter_on_something_else_is_not():
    for where in ("created_at <= shipped_at", "shipped_at > created_at", "NOT (shipped_at < created_at)",
                  "date_diff('hour', created_at, shipped_at) >= 0",
                  "0 < date_diff('hour', created_at, shipped_at)", "id >= 0 AND (shipped_at >= created_at)"):
        run = T.time_order_check(_conn(inverted=3), SHIP.replace("FROM items", f"FROM items WHERE {where}"), "duckdb")
        assert [(f.inverted, f.measured, f.left_out) for f in run.findings] == [(3, 10, True)], where
    run = T.time_order_check(_conn(inverted=3), SHIP.replace("FROM items", "FROM items WHERE id >= 0"), "duckdb")
    assert [(f.inverted, f.measured, f.left_out) for f in run.findings] == [(3, 10, False)]


Q4_RERUN = ("SELECT dc.name AS distribution_center, "
            "AVG(TIMESTAMP_DIFF(oi.shipped_at, oi.created_at, HOUR)) AS avg_hours_to_ship, "
            "AVG(TIMESTAMP_DIFF(oi.delivered_at, oi.shipped_at, HOUR)) AS avg_hours_to_deliver, "
            "COUNT(oi.id) AS order_count FROM `order_items` AS oi "
            "JOIN `inventory_items` AS ii ON oi.inventory_item_id = ii.id "
            "JOIN `distribution_centers` AS dc ON ii.product_distribution_center_id = dc.id "
            "WHERE oi.created_at >= '2026-08-01' AND oi.created_at < '2026-09-03' "
            "AND oi.shipped_at >= oi.created_at AND oi.delivered_at >= oi.shipped_at "
            "GROUP BY 1 ORDER BY avg_hours_to_ship + avg_hours_to_deliver DESC")


def test_the_probe_lifts_only_the_filters_that_order_a_pair():
    """The 2026-10-01 re-run, as it ran on BigQuery: its window stays, its two order filters go."""
    tree = sqlglot.parse_one(Q4_RERUN, read="bigquery")
    [(scope, pairs)] = T.duration_pairs(tree)
    assert T.left_out_pairs(scope, pairs) == {0, 1}
    probe = T.probe_sql(tree, scope, pairs, "bigquery")
    assert "oi.shipped_at >= oi.created_at" not in probe and "oi.delivered_at >= oi.shipped_at" not in probe
    assert "oi.created_at >= '2026-08-01'" in probe and "oi.created_at < '2026-09-03'" in probe


def _three_stamps():
    """Ten rows: 0–2 shipped before they were created, 3–4 delivered before they shipped."""
    conn = _conn(inverted=0)
    conn._conn.execute("CREATE TABLE parcels (id INT, created_at TIMESTAMP, shipped_at TIMESTAMP, "
                       "delivered_at TIMESTAMP)")
    for i in range(10):
        ship = "2026-01-01 08:00" if i < 3 else "2026-01-03 08:00"
        deliver = "2026-01-02 08:00" if i in (3, 4) else "2026-01-05 08:00"
        conn._conn.execute(f"INSERT INTO parcels VALUES ({i}, TIMESTAMP '2026-01-02 08:00', "
                           f"TIMESTAMP '{ship}', TIMESTAMP '{deliver}')")
    return conn


def test_a_pair_nothing_filtered_is_still_counted_over_the_statements_own_rows():
    sql = ("SELECT AVG(date_diff('hour', created_at, shipped_at)) AS ship, "
           "AVG(date_diff('hour', shipped_at, delivered_at)) AS deliver "
           "FROM parcels WHERE shipped_at >= created_at")
    run = T.time_order_check(_three_stamps(), sql, "duckdb")
    assert [(f.end, f.inverted, f.measured, f.left_out) for f in run.findings] == [
        ("shipped_at", 3, 10, True),       # what the filter left out, of the rows it would measure
        ("delivered_at", 2, 7, False)]     # backwards among the 7 rows the statement kept


def test_a_rerun_that_leaves_the_rows_out_does_not_replace_the_flagged_one():
    from aughor.agent.analyst import AnalystTurn
    turn = AnalystTurn(connection_id="c", conn=None, state={"question": "q", "investigation_phases": []})
    conn = _conn(inverted=3)
    for sql in (SHIP, LEFT_OUT):
        _record(turn, ["hours"], execute_guarded(conn, sql, query_id="q").caveats)
    assert not any(p.get("_hidden") for p in turn.state["investigation_phases"])
