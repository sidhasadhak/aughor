"""Lifecycle SQL guard — a prompt is not a guard (aughor/sql/lifecycle_guard.py).

The live planner ignored the probed lifecycle directive in BOTH prompt positions
(plan_user, then plan_system) while obeying the grouping rule beside it — invs
0db3a6db / 8f9ca261 shipped utilization SQL with no status filter, and the claim
moved between readings run to run. The guard injects the KEEP filter into the
planned SQL deterministically, per scope, after planning.

Hermetic: pure sqlglot pass + an in-memory DuckDB where the readings genuinely
differ, so a wrong repair produces a wrong NUMBER, not just a wrong string.
"""
from __future__ import annotations

import duckdb

from aughor.agent.loss_signals import lifecycle_rules
from aughor.sql.lifecycle_guard import enforce_lifecycle_filters, lifecycle_transform

_RULES = [
    {"table": "tickets", "column": "segment_status", "keep": ["flown"],
     "exclude": ["cancelled", "no_show"]},
    {"table": "flights", "column": "status", "keep": ["scheduled"],
     "exclude": ["cancelled"]},
]

# The EXACT shape the live planner produced with the pin ignored (inv 8f9ca261).
_LIVE_SQL = """
WITH capacity AS (SELECT flight_id, haul, total_seats FROM flights),
     sold AS (SELECT flight_id, COUNT(t.ticket_id) AS tickets_sold FROM tickets t GROUP BY flight_id)
SELECT c.haul AS group_name,
       100.0 * SUM(COALESCE(s.tickets_sold, 0)) / NULLIF(SUM(c.total_seats), 0) AS metric_total,
       SUM(c.total_seats) AS n
FROM capacity c LEFT JOIN sold s ON c.flight_id = s.flight_id
GROUP BY c.haul ORDER BY metric_total ASC
"""


def _fixture():
    """2 flights (one cancelled) + tickets where the readings differ:
    reading A (all/all): sold=3 of capacity=20 = 15%;
    reading E (flown/operated): sold=1 of capacity=10 = 10%."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE flights(flight_id INT, haul VARCHAR, total_seats INT, status VARCHAR)")
    c.execute("INSERT INTO flights VALUES (1,'long',10,'scheduled'), (2,'long',10,'cancelled')")
    c.execute("CREATE TABLE tickets(ticket_id INT, flight_id INT, segment_status VARCHAR)")
    c.execute("INSERT INTO tickets VALUES (1,1,'flown'), (2,1,'cancelled'), (3,2,'cancelled')")
    return c


def test_repairs_the_exact_live_sql_and_the_number_changes():
    fixed, applied = enforce_lifecycle_filters(_LIVE_SQL, _RULES)
    assert sorted(applied) == ["flights.status", "tickets.segment_status"]
    c = _fixture()
    naive = c.execute(_LIVE_SQL).fetchall()[0]
    pinned = c.execute(fixed).fetchall()[0]
    assert float(naive[1]) == 15.0            # reading A — what shipped
    assert float(pinned[1]) == 10.0           # reading E — flown / operated capacity
    assert float(pinned[2]) == 10.0           # cancelled flight's seats out of the denominator


def test_a_planner_that_obeyed_is_left_alone():
    obeyed = """
    SELECT f.haul, 100.0 * COUNT(t.ticket_id) / NULLIF(SUM(f.total_seats), 0) AS metric_total
    FROM flights f LEFT JOIN tickets t
      ON t.flight_id = f.flight_id AND t.segment_status = 'flown'
    WHERE f.status <> 'cancelled'
    GROUP BY f.haul
    """
    fixed, applied = enforce_lifecycle_filters(obeyed, _RULES)
    assert applied == [] and fixed == obeyed


def test_aliased_tables_get_alias_qualified_filters():
    sql = "SELECT t.cabin, COUNT(*) FROM tickets t GROUP BY t.cabin"
    fixed, applied = enforce_lifecycle_filters(sql, _RULES)
    assert applied == ["tickets.segment_status"]
    assert "t.segment_status IN ('flown')" in fixed


def test_unruled_tables_and_broken_sql_pass_through():
    sql = "SELECT * FROM bookings WHERE channel = 'web'"
    assert enforce_lifecycle_filters(sql, _RULES) == (sql, [])
    broken = "SELEC nonsense FROM ((("
    assert enforce_lifecycle_filters(broken, _RULES) == (broken, [])
    assert enforce_lifecycle_filters(_LIVE_SQL, []) == (_LIVE_SQL, [])


def test_each_scope_is_filtered_at_its_own_grain():
    """Two CTEs reading the same ruled table each get their own filter — the rule composes
    per scope, exactly like the directive's 'apply each filter on ITS OWN table' clause."""
    sql = """
    WITH a AS (SELECT flight_id FROM tickets),
         b AS (SELECT COUNT(*) AS n FROM tickets)
    SELECT * FROM a, b
    """
    fixed, applied = enforce_lifecycle_filters(sql, _RULES)
    assert applied == ["tickets.segment_status", "tickets.segment_status"]
    assert fixed.count("segment_status IN ('flown')") == 2


def test_rules_come_from_the_same_classification_as_the_directive():
    rules = lifecycle_rules({
        "tickets.segment_status": ["cancelled", "flown", "no_show"],
        "flights.status": ["cancelled", "scheduled"],
        "sales_customers.state": ["CA", "NY", "TX"],          # pins nothing
    })
    assert {(r["table"], r["column"]) for r in rules} == {
        ("tickets", "segment_status"), ("flights", "status")}
    tick = next(r for r in rules if r["table"] == "tickets")
    assert tick["keep"] == ["flown"] and sorted(tick["exclude"]) == ["cancelled", "no_show"]


def test_transform_reports_applications_and_none_without_rules():
    hits: list = []
    t = lifecycle_transform(_RULES, on_apply=hits.append)
    out = t(_LIVE_SQL)
    assert "segment_status IN ('flown')" in out
    assert hits and sorted(hits[0]) == ["flights.status", "tickets.segment_status"]
    assert lifecycle_transform([], on_apply=hits.append) is None


def test_lens_wiring_reaches_run_analysis_phase_with_the_guard(monkeypatch):
    """Reachability — the whole chain through the REAL `_run_loss_lens_phases`, LLM stubbed.
    This exact path shipped a NameError in an instrumentation line: every unit test passed
    while the live lens died at its fail-open tolerate() and reports quietly lost their loss
    phases. Drive the function, not just its parts."""
    import aughor.agent.investigate as inv

    captured: dict = {}

    class _Res:
        def __init__(self, rows):
            self.rows, self.columns, self.error = rows, ["v"], None

    class _Conn:
        dialect = "duckdb"
        def execute_bounded(self, tag, sql, max_rows):
            if "segment_status" in sql:
                return _Res([["cancelled"], ["flown"], ["no_show"]])
            if '"status"' in sql:
                return _Res([["cancelled"], ["scheduled"]])
            return _Res([])

    def _fake_phase(conn, **kw):
        captured[kw["phase_id"]] = kw
        return type("R", (), {"ok": False, "error_phase": None})()

    monkeypatch.setenv("AUGHOR_INTAKE_LOSS_SIGNALS", "1")
    monkeypatch.setattr(inv, "run_analysis_phase", _fake_phase)
    state = {
        "question": "Where are we losing money?",
        "connection_id": "workspace",
        "schema_context": "TABLE: flights\n  status  VARCHAR\n",
        "_ada_intake": {
            "loss_signals": {"contra_revenue": ["refund_chf"], "capacity": ["total_seats"],
                             "lifecycle": ["tickets.segment_status", "flights.status"]},
            "metric_label": "net fare revenue", "metric_sql": "SUM(b.total_fare_chf)",
            "filtered_schema": "TABLE: flights\n  status  VARCHAR\n",
        },
    }
    inv._run_loss_lens_phases(state, _Conn())
    assert "loss_utilization" in captured and "loss_leakage" in captured
    # The guard rides ONLY on the lens that declares lifecycle_filter.
    t = captured["loss_utilization"]["sql_transform"]
    assert t is not None
    assert captured["loss_leakage"]["sql_transform"] is None
    # And it actually repairs: the transform is live, not a stub.
    assert "segment_status IN ('flown')" in t("SELECT COUNT(*) FROM tickets")
