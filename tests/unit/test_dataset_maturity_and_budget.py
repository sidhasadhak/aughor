"""Maturity, the watch job and the monthly budget — the exploration principles' §3, §4 and §7 (2026-10-08).

The user, 2026-10-07: a maturity reading per schema and table — "three check marks … or percentage
highlighted by vertical bars and a number"; a mature dataset is WATCHED, time its only new factor; and
an exploration budget per organisation AND per connection per month, the tighter holding, said when spent.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from aughor.explorer import budget as B
from aughor.explorer import maturity as M
from aughor.explorer import program as P
from aughor.explorer import watch as W

BUSINESS = frozenset({"business"})


def _metric(name, *, grain="day", dated=True, tables=("orders",)):
    return SimpleNamespace(name=name, label=name, time_grain=grain, time_kind="flow" if dated else "",
                           time_column="created_at" if dated else "", until_column="", outcome_column="",
                           sql=f"SELECT SUM(x) FROM {tables[0]}", tables=list(tables))


# ── maturity ─────────────────────────────────────────────────────────────────

def test_structure_reads_how_far_the_structure_job_got():
    assert M.structure_bar({"structure_learned": {"at": "x"}})["share"] == 1.0
    assert M.structure_bar({"phase": "lifecycle_mapping"})["share"] == 0.5
    assert M.structure_bar({"phase": "pending"}) == {"share": 0.0, "note": "not explored yet"}


def test_questions_is_the_question_list_asked_and_says_why_it_does_not_apply():
    state = {"manifest_status": {"cells": 10, "by_table": {"orders": 6, "items": 4}},
             "manifest_covered": {"cells": [["rev", "orders", "headline", None]] * 3
                                  + [["n", "(kpi)", "headline", None]]}}
    bar = M.questions_bar(state, P.load("none"), layer="business", explored_layers=BUSINESS)
    assert bar == {"share": 0.3, "note": "3 of 10 questions asked"}, "a KPI cell is not a question-list cell"
    by_table = M.questions_bar(state, {}, layer="business", explored_layers=BUSINESS, table="orders")
    assert by_table["share"] == 0.5
    staged = M.questions_bar(state, {}, layer="raw", explored_layers=BUSINESS)
    assert staged == {"share": None, "note": "not explored — raw"}, "a staging dataset is not 0%"


def test_two_runs_that_found_almost_nothing_new_are_mature():
    runs = [{"job": "questions", "outcome": "complete", "new_findings": n} for n in (9, 1, 0)]
    bar = M.questions_bar({"manifest_status": {"cells": 10}}, {"runs": runs}, layer="business",
                          explored_layers=BUSINESS)
    assert bar["share"] == 1.0 and "almost nothing new" in bar["note"]


def test_time_is_dates_and_the_newest_settled_period_read():
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    metrics = [_metric("revenue"), _metric("orders", dated=False)]
    assert M.time_bar(metrics, {"watch": {}}, now=now)["share"] == 0.25
    fresh = {"watch": {"day": {"read_at": (now - timedelta(hours=5)).isoformat()}}}
    assert M.time_bar(metrics, fresh, now=now)["share"] == 0.75
    assert M.time_bar([], {}, now=now) == {"share": None, "note": "no approved metrics to watch"}


def test_the_number_beside_the_bars_reads_only_what_applies():
    m = M.maturity({"structure_learned": {"at": "x"}}, {}, [], layer="raw", explored_layers=BUSINESS)
    assert m["questions"]["share"] is None and m["time"]["share"] is None
    assert m["percent"] == 100 and m["stage"] == "learning"


# ── the program store ─────────────────────────────────────────────────────────

def test_a_reopen_holds_its_first_reason_until_a_run_takes_it():
    key = f"wh-{uuid.uuid4().hex[:6]}__marts"
    P.reopen(key, "AOV was approved")
    P.reopen(key, "revenue moved -12%")
    assert P.load(key)["reopened"]["reason"] == "AOV was approved"
    assert P.take_reopen(key)["reason"] == "AOV was approved"
    assert P.load(key)["reopened"] is None
    P.record_run(key, job="questions", outcome="complete", new_findings=3)
    assert P.last_run(P.load(key), "questions")["new_findings"] == 3


# ── the watch job ─────────────────────────────────────────────────────────────

def _spec(last: date):
    return SimpleNamespace(start=last - timedelta(days=0), end=last + timedelta(days=1), last_day=last)


def test_a_grain_is_read_once_per_settled_period_and_a_real_move_reopens(monkeypatch):
    conn = f"wh-{uuid.uuid4().hex[:6]}"
    metrics = [_metric("revenue"), _metric("aov")]
    monkeypatch.setattr("aughor.briefing.ranges.governed_metrics", lambda c, s=None: metrics)
    monkeypatch.setattr("aughor.briefing.ranges.resolve_for",
                        lambda c, preset, **kw: (_spec(date(2026, 10, 7)), ""))
    reads: list = []

    def measure(spec):
        reads.append(spec.last_day)
        return {"measured": [
            {"name": "revenue", "metric": "revenue", "rel": -0.12, "status": "final", "anchored": None},
            {"name": "aov", "metric": "aov", "rel": 0.02, "status": "final", "anchored": None}],
            "unmeasured": []}

    got = W.read_due(conn, "marts", reopen_questions=True, measure=measure)
    assert [g["grain"] for g in got] == ["day"] and got[0]["moved"] == [
        {"name": "revenue", "metric": "revenue", "rel": -0.12}]
    prog = P.load(f"{conn}__marts")
    assert prog["watch"]["day"]["through"] == "2026-10-07"
    assert "revenue moved -12%" in prog["reopened"]["reason"]
    assert W.read_due(conn, "marts", reopen_questions=True, measure=measure) == [], "read once per period"
    assert len(reads) == 1


def test_a_provisional_or_ended_figure_is_not_a_move():
    names = {"a", "b", "c"}
    assert W.moved_figures([{"metric": "a", "rel": 0.5, "status": "provisional"},
                            {"metric": "b", "rel": 0.5, "status": "final", "anchored": {"x": 1}},
                            {"metric": "c", "rel": 0.05, "status": "final"}], names) == []


def test_the_newest_settled_quarter_is_the_one_its_last_settled_month_closes():
    def resolve(conn, preset, *, start=None, end=None, today=None):
        if preset == "last_month":
            return SimpleNamespace(last_day=date(2026, 8, 31)), ""
        return SimpleNamespace(start=start, last_day=end), ""
    q = W._quarter_spec("c", resolve, date(2026, 9, 15))
    assert (q.start, q.last_day) == (date(2026, 4, 1), date(2026, 6, 30))


# ── the budget ────────────────────────────────────────────────────────────────

def _job(tokens):
    return {"metrics": {"total_tokens": tokens}}


def test_spend_is_the_tokens_the_jobs_recorded_this_month():
    assert B.spent(jobs=[_job(1200), _job(800), {"metrics": None}]) == 2000
    assert B.month_start(datetime(2026, 10, 8, 13, tzinfo=timezone.utc)) == "2026-10-01T00:00:00+00:00"


def test_the_tighter_budget_holds_and_says_so(monkeypatch):
    monkeypatch.setattr(B, "limits", lambda c: (1_000_000, 50_000))
    monkeypatch.setattr(B, "spent", lambda c=None, **k: 400_000 if c is None else 60_000)
    s = B.standing("wh")
    assert s["held_by"] == "connection" and s["spent_out"] and s["remaining"] == -10_000
    assert "connection's monthly exploration budget of 50,000 tokens is spent" in s["sentence"]
    assert "a person's Start still runs" in s["sentence"]
    monkeypatch.setattr(B, "limits", lambda c: (None, None))
    open_ = B.standing("wh")
    assert open_["held_by"] is None and not open_["spent_out"] and "no monthly exploration budget" in open_["sentence"]


def test_a_budget_is_set_in_the_organisations_settings_and_the_connections(monkeypatch):
    from aughor.orgsettings.models import OrgSettings
    assert OrgSettings().exploration_monthly_tokens == 0, "none unless a person sets one"
    monkeypatch.setattr("aughor.orgsettings.load_org_settings", lambda: OrgSettings(exploration_monthly_tokens=900))
    monkeypatch.setattr("aughor.db.registry.get_connection_settings", lambda c: {"exploration_monthly_tokens": 0})
    assert B.limits("wh") == (900, None), "0 clears a connection's budget"
