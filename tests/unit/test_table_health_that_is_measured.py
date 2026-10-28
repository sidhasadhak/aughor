"""Arc ED, ED-3 (ROADMAP §3.58) — table health that is measured.

The quality plane had three readers and no producer: an answer's caveats, the MCP table-health tool and the Briefing's
count of failing tables all read `quality/results.py`, and nothing ever wrote a verdict there, so every table read "not
checked". An automation step now measures a table's expectations, read-only, through the connection's own door, and
records each verdict in the one store.

Held on the seeded samples warehouse through the real DuckDB connection and the real compiler, and the readers read
what it wrote. The falsifier is ROADMAP §3.58's: a table read as failing because a query could not run → stop.
"""
from __future__ import annotations

import uuid

import pytest

from aughor.automations.models import Automation, Condition, Effect
from aughor.quality import expectations as X
from aughor.quality.results import count_failing, latest_for_tables
from aughor.quality.rules import RuleError
from tests.unit.test_object_actions import db  # noqa: F401 — the samples warehouse, by name


def _conn() -> str:
    return f"ed3-{uuid.uuid4().hex[:8]}"          # each test its own connection id in the one store


def _x(**kw) -> dict:
    return {"table": "orders", **kw}


# ── what a step may carry ───────────────────────────────────────────────────────

def test_a_step_carries_names_and_values_never_sql():
    assert len(X.parse([_x(name="ids", kind="not_null", column="order_id")])) == 1
    for bad, why in ((_x(name="a", kind="not_null", column="order_id", filter="status <> 'x'"), "filter"),
                     (_x(name="a", kind="not_null", column="order_id; DROP TABLE x"), "plain name"),
                     ({"name": "a", "table": "orders o, users u", "kind": "unique", "column": "id"}, "plain name"),
                     (_x(name="a", kind="foreign_key", column="customer_id",
                         args={"references": "customers", "references_column": "id) OR (1=1"}), "plain name")):
        with pytest.raises(RuleError, match=why):
            X.parse([bad])
    with pytest.raises(RuleError, match="at least one"):
        X.parse([])
    with pytest.raises(RuleError, match="two expectations"):
        X.parse([_x(name="a", kind="not_null", column="x"), _x(name="a", kind="unique", column="x")])


def test_a_malformed_step_is_refused_when_it_is_saved_not_at_run_time():
    with pytest.raises(ValueError, match="expectations"):
        Effect(kind="expectations", config={"expectations": [_x(name="a", kind="range", column="total_amount")]})
    assert Effect(kind="expectations", config={"expectations": [_x(name="a", kind="not_null", column="order_id")]})


# ── the measurement, on the samples warehouse ───────────────────────────────────

def test_each_verdict_is_measured_and_recorded_where_the_readers_read(db):  # noqa: F811
    conn = _conn()
    statuses = [r[0] for r in db.execute("s", "SELECT DISTINCT status FROM orders").rows]
    rules = X.parse([
        _x(name="order ids", kind="not_null", column="order_id"),
        _x(name="order ids repeat", kind="unique", column="order_id"),
        _x(name="customers exist", kind="foreign_key", column="customer_id",
           args={"references": "customers", "references_column": "customer_id"}),
        _x(name="shipped only", kind="in_list", column="status", args={"values": ["shipped"]}, criticality="error"),
        _x(name="recent orders", kind="freshness", column="order_date", args={"max_age_hours": 1}),
    ])
    run = X.measure(db, rules, connection_id=conn)
    verdicts = {r.rule_name: r for r in run.results}
    assert not run.unmeasured and set(verdicts) == {"order ids", "order ids repeat", "customers exist",
                                                     "shipped only", "recent orders"}
    assert verdicts["order ids"].passed and verdicts["order ids repeat"].passed
    assert verdicts["customers exist"].passed
    other = int(db.execute("n", "SELECT COUNT(*) FROM orders WHERE status NOT IN ('shipped')").rows[0][0])
    assert len(statuses) > 1 and not verdicts["shipped only"].passed
    assert verdicts["shipped only"].violations == other and f"{other:,} rows' status" in verdicts["shipped only"].detail
    assert not verdicts["recent orders"].passed and "older than 1 hours" in verdicts["recent orders"].detail
    # the readers read it: the latest per expectation, the failing count, an answer's caveats
    latest = {r.rule_name: r for r in latest_for_tables(conn, ["ecommerce.orders"])}
    assert set(latest) == set(verdicts)
    assert count_failing(conn) >= 1
    from aughor.quality.caveats import caveats_for_answer
    said = " ".join(caveats_for_answer(conn, ["orders"]))
    assert "shipped only" in said or "status" in said, said


def test_freshness_asks_about_the_newest_row_not_every_old_one(db):  # noqa: F811
    """It counted every row older than the limit, so a table with any history failed forever."""
    conn = _conn()
    newest, oldest = (int(v) for v in db.execute("age", "SELECT date_diff('hour', CAST(MAX(order_date) AS TIMESTAMP), "
                                                        "now()), date_diff('hour', CAST(MIN(order_date) AS TIMESTAMP), "
                                                        "now()) FROM orders").rows[0])
    assert oldest > newest + 2, "the samples need orders on more than one day for this to tell the two apart"
    hours = newest + 1                       # younger than the newest order, older than the oldest
    run = X.measure(db, X.parse([_x(name="recent enough", kind="freshness", column="order_date",
                                    args={"max_age_hours": hours})]), connection_id=conn)
    assert run.results[0].passed and run.results[0].violations == 0, run.results[0].detail
    assert "within" in run.results[0].detail


def test_a_query_that_cannot_run_is_said_and_never_counted_as_failing(db):  # noqa: F811
    conn = _conn()
    run = X.measure(db, X.parse([_x(name="ghost column", kind="not_null", column="no_such_column")]),
                    connection_id=conn)
    assert run.results == [] and run.unmeasured and run.unmeasured[0][0] == "ghost column"
    assert latest_for_tables(conn, ["orders"]) == [] and count_failing(conn) == 0
    assert "could not be measured" in run.words()


def test_a_drift_is_read_against_the_last_reading(db):  # noqa: F811
    conn = _conn()
    rule = X.parse([_x(name="row count", kind="row_count_drift", args={"max_change_pct": 10})])
    first = X.measure(db, rule, connection_id=conn).results[0]
    assert first.passed and "baseline" in first.detail
    second = X.measure(db, rule, connection_id=conn).results[0]
    assert second.passed and "0% change" in second.detail
    from aughor.quality.results import Result, record
    record(Result(connection_id=conn, table_name="orders", producer="check", rule_name="row count",
                  rule_fingerprint=rule[0].fingerprint, observed=second.observed * 3, passed=True))
    third = X.measure(db, rule, connection_id=conn).results[0]
    assert not third.passed and "the limit is 10%" in third.detail


# ── the step ────────────────────────────────────────────────────────────────────

def _automation(conn: str, effects) -> Automation:
    return Automation(id=f"ed3-{uuid.uuid4().hex[:6]}", conn_id=conn, name="orders health",
                      conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})], effects=effects)


def test_the_step_measures_and_publishes_what_it_found(db, monkeypatch):  # noqa: F811
    from tests.unit.test_object_actions import _Borrowed
    from aughor.automations.engine import _dispatch_expectations
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn: _Borrowed(db))
    conn = _conn()
    effect = Effect(kind="expectations", config={"expectations": [
        _x(name="order ids", kind="not_null", column="order_id"),
        _x(name="ghost", kind="not_null", column="no_such_column")]})
    out = _dispatch_expectations(effect, _automation(conn, [effect]))
    assert out.status == "executed", out.message
    assert out.data["met"] == 1 and out.data["not_met"] == 0 and out.data["unmeasured"][0]["name"] == "ghost"
    assert "orders: 1 of 1 expectation met" in out.message and "1 could not be measured" in out.message


def test_a_step_where_nothing_could_be_measured_fails_rather_than_reads_healthy(db, monkeypatch):  # noqa: F811
    from tests.unit.test_object_actions import _Borrowed
    from aughor.automations.engine import _dispatch_expectations
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn: _Borrowed(db))
    effect = Effect(kind="expectations", config={"expectations": [_x(name="ghost", kind="not_null", column="nope")]})
    out = _dispatch_expectations(effect, _automation(_conn(), [effect]))
    assert out.status == "failed" and "no expectation was measured" in out.message
