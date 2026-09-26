"""Idea 4 · learn when each table's numbers stop changing.

The learner is fed theLook's measured shape (2026-09-05: a day's count is a function of its
AGE — a ramp that flattens a week out) and must name the lag; fed too little, or a day
still moving at the edge of what was read, it must refuse with the reason. The sampler is
driven with a fake warehouse; the store round-trips through an isolated data home.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from aughor.settling import learn, sampler, store
from aughor.settling.learn import Observation, settle_lag

D0 = date(2026, 9, 1)

#: theLook's ramp, by age: young days read high and settle by day 7.
RAMP = {1: 1745.0, 2: 991.0, 3: 791.0, 4: 594.0, 5: 450.0, 6: 335.0, 7: 329.0, 8: 329.0,
        9: 328.0, 10: 329.0, 11: 329.0, 12: 329.0}


def _days(n_days: int, ages: range, curve=RAMP) -> list[Observation]:
    out = []
    for i in range(n_days):
        day = D0 + timedelta(days=i)
        for age in ages:
            out.append(Observation(day=day, measured_on=day + timedelta(days=age),
                                   value=curve[age]))
    return out


# ── the learner ──────────────────────────────────────────────────────────────────

def test_thelook_ramp_settles_seven_days_out():
    v = settle_lag(_days(4, range(1, 13)))
    assert v.lag_days == 7
    assert v.evidence_days == 4 and v.horizon_days == 12
    assert "learned from 4 days" in v.reason and "7 days after it ends" in v.reason


def test_one_reading_per_day_is_not_evidence():
    # The first day of sampling: every day read once, at one age. Nothing can be learned.
    obs = [Observation(day=D0 + timedelta(days=i), measured_on=D0 + timedelta(days=14), value=100.0)
           for i in range(14)]
    v = settle_lag(obs)
    assert v.lag_days is None
    assert v.reason.startswith("insufficient evidence: 0 days read at 3+ ages (needs 3)")


def test_two_qualifying_days_are_not_enough_either():
    v = settle_lag(_days(2, range(1, 13)))
    assert v.lag_days is None and v.evidence_days == 2
    assert "2 days read at 3+ ages (needs 3)" in v.reason


def test_a_day_still_moving_at_the_horizon_withholds_the_verdict():
    # Read only at ages 1–4, where the ramp is still falling: no age has settled.
    v = settle_lag(_days(3, range(1, 5)))
    assert v.lag_days is None
    assert v.reason.startswith("still moving at age 4 on 3 of 3 days")


def test_a_source_that_never_restates_settles_in_one_day():
    flat = {a: 500.0 for a in range(1, 8)}
    v = settle_lag(_days(3, range(1, 8), curve=flat))
    assert v.lag_days == 1 and "1 day after it ends" in v.reason


def test_the_verdict_is_the_slowest_day_not_the_typical_one():
    quick = {1: 400.0, 2: 330.0, 3: 329.0, 4: 329.0, 5: 329.0, 6: 329.0, 7: 329.0, 8: 329.0}
    obs = _days(3, range(1, 9), curve=quick) + _days(1, range(1, 9))[0:0]
    # one slow day, the ramp, appended as a fourth day
    slow_day = D0 + timedelta(days=10)
    obs += [Observation(day=slow_day, measured_on=slow_day + timedelta(days=a), value=RAMP[a])
            for a in range(1, 9)]
    assert settle_lag(obs).lag_days == 7


def test_a_one_row_restatement_on_a_tiny_day_still_counts_as_movement():
    # 3 rows → 4 rows is one late row, and reading the day as final at age 1 would have been
    # wrong by a third. The absolute floor (50 × 1% = half a row) tolerates nothing an integer
    # count can do, which is the point: for counts, any change is a restatement.
    tiny = {1: 3.0, 2: 4.0, 3: 4.0, 4: 4.0}
    assert settle_lag(_days(3, range(1, 5), curve=tiny)).lag_days == 2


def test_age_zero_and_future_dated_rows_are_ignored():
    obs = _days(3, range(1, 13)) + [
        Observation(day=D0, measured_on=D0, value=5.0),                          # the day itself
        Observation(day=D0 + timedelta(days=3), measured_on=D0, value=9.0),      # future-dated
    ]
    assert settle_lag(obs).lag_days == 7


# ── the store ────────────────────────────────────────────────────────────────────

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_path", lambda: tmp_path / "settling.json")
    return tmp_path


def test_readings_accumulate_per_day_and_a_reread_of_the_same_day_replaces_it(home):
    store.record_observations("c1", "orders", "created_at", D0 + timedelta(days=1),
                              {"2026-09-01": 1745.0, "2026-08-31": 991.0})
    store.record_observations("c1", "orders", "created_at", D0 + timedelta(days=2),
                              {"2026-09-01": 991.0, "2026-08-31": 791.0})
    # the same reading day again — replaced, not doubled
    n = store.record_observations("c1", "orders", "created_at", D0 + timedelta(days=2),
                                  {"2026-09-01": 990.0, "2026-08-31": 791.0})
    assert n == 4
    obs = store.observations("c1", "orders")
    assert sorted((o.day.isoformat(), o.age, o.value) for o in obs) == [
        ("2026-08-31", 2, 991.0), ("2026-08-31", 3, 791.0),
        ("2026-09-01", 1, 1745.0), ("2026-09-01", 2, 990.0)]
    assert store.tables("c1") == ["orders"] and store.tables("c2") == []


def test_readings_older_than_the_keep_window_are_dropped(home):
    store.record_observations("c1", "t", "ts", D0, {"2026-08-31": 1.0})
    store.record_observations("c1", "t", "ts", D0 + timedelta(days=store.KEEP_DAYS + 1),
                              {"2026-11-30": 2.0})
    assert [o.value for o in store.observations("c1", "t")] == [2.0]


def test_the_connection_lag_is_the_slowest_table_and_none_until_learned(home):
    # orders settles in 7 days, events in 2: the connection waits for orders.
    for i in range(4):
        day = D0 + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations("c1", "orders", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): RAMP[age]})
            store.record_observations("c1", "events", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): 60.0 if age == 1 else 50.0})
    assert store.verdicts("c1")["orders"].lag_days == 7
    assert store.verdicts("c1")["events"].lag_days == 2
    assert store.learned_lag_days("c1") == 7
    assert store.learned_lag_days("c-none") is None and store.learned_lag_days("") is None
    s = store.summary("c1")
    assert s["learned_lag_days"] == 7
    assert {r["table"]: r["verdict"]["lag_days"] for r in s["tables"]} == {"orders": 7, "events": 2}
    assert s["tables"][0]["days_observed"] == 4


def test_a_table_still_moving_at_the_horizon_raises_the_lag_it_is_not_left_out(home):
    """theLook 2026-09-25: orders settled at 13, order_items still moved at 14 — and the
    connection read "13, learned". A table that has not stopped makes the lag a floor."""
    for i in range(4):
        day = D0 + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations("c1", "orders", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): RAMP[age]})
            store.record_observations("c1", "order_items", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): 100.0 * age})   # never stops
    assert store.verdicts("c1")["order_items"].still_moving
    lag = store.connection_lag("c1")
    assert lag == {"days": 13, "source": "beyond_horizon", "still_moving": ["order_items"],
                   "horizon": 12}
    assert store.learned_lag_days("c1") == 13
    assert store.summary("c1")["lag_source"] == "beyond_horizon"


# ── the sampler ──────────────────────────────────────────────────────────────────

def _fake_profiles(monkeypatch, tables: dict[str, dict]):
    monkeypatch.setattr("aughor.tools.profile_cache._load",
                        lambda: {"c1:old": {"tables": {}}, "c1:abc": {"tables": tables}})


def test_the_sql_names_literal_days_never_the_warehouse_clock():
    sql = sampler.count_by_day_sql("orders", "created_at", date(2026, 9, 9), date(2026, 9, 23))
    assert sql == ('SELECT CAST("created_at" AS DATE) AS day, COUNT(*) AS n FROM "orders" '
                   'WHERE CAST("created_at" AS DATE) >= DATE \'2026-09-09\' '
                   'AND CAST("created_at" AS DATE) < DATE \'2026-09-23\' GROUP BY 1 ORDER BY 1')
    assert "CURRENT_DATE" not in sql
    # Found by the first live tick: an unquoted "Order Date" is two tokens. Identifiers are
    # quoted in DuckDB's dialect, which `native_sql` translates for the backtick engines.
    spaced = sampler.count_by_day_sql("thelook.superstore", "Order Date", date(2026, 9, 9), date(2026, 9, 10))
    assert spaced.startswith('SELECT CAST("Order Date" AS DATE) AS day, COUNT(*) AS n FROM "thelook"."superstore" ')


def test_time_tables_come_from_the_latest_profile_largest_first_and_capped(monkeypatch):
    tables = {f"t{i}": {"primary_timestamp": "ts", "row_count": i * 10} for i in range(12)}
    tables["lookup"] = {"primary_timestamp": "", "row_count": 999999}
    _fake_profiles(monkeypatch, tables)
    got = sampler.time_tables("c1")
    assert len(got) == sampler.MAX_TABLES_PER_CONNECTION
    assert got[0] == ("t11", "ts", 110) and "lookup" not in {t for t, _, _ in got}
    assert sampler.time_tables("c-unprofiled") == []


def test_a_reading_files_every_day_of_the_horizon_and_skips_a_failing_table(home, monkeypatch):
    _fake_profiles(monkeypatch, {"orders": {"primary_timestamp": "created_at", "row_count": 100},
                                 "broken": {"primary_timestamp": "ts", "row_count": 50}})
    today = date(2026, 9, 23)
    asked: list[str] = []

    def run_sql(sql):
        asked.append(sql)
        if 'FROM "broken"' in sql:
            return [], [], "permission denied"
        return (["day", "n"], [("2026-09-22", 1745), (date(2026, 9, 21), 991),
                               ("2026-09-30", 7),            # future-dated: outside the horizon
                               ("2026-09-01", 3)], None)     # older than the horizon

    result = sampler.sample_connection("c1", run_sql, today=today)
    assert result["sampled"] == ["orders"] and result["errors"] == {"broken": "permission denied"}
    assert len(asked) == 2
    obs = {o.day.isoformat(): o.value for o in store.observations("c1", "orders")}
    assert obs["2026-09-22"] == 1745.0 and obs["2026-09-21"] == 991.0
    assert obs["2026-09-09"] == 0.0 and "2026-09-30" not in obs and "2026-09-01" not in obs
    assert len(obs) == sampler.HORIZON_DAYS
    assert all(o.measured_on == today for o in store.observations("c1", "orders"))


def test_a_table_still_moving_is_read_twice_as_far_back(home, monkeypatch):
    _fake_profiles(monkeypatch, {"orders": {"primary_timestamp": "created_at", "row_count": 100},
                                 "users": {"primary_timestamp": "created_at", "row_count": 50}})
    for i in range(4):   # orders never stops moving; users has no readings yet
        day = D0 + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations("c1", "orders", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): 100.0 * age})
    today = date(2026, 9, 23)
    asked: dict[str, str] = {}

    def run_sql(sql):
        asked["orders" if '"orders"' in sql else "users"] = sql
        return ["day", "n"], [], None

    sampler.sample_connection("c1", run_sql, today=today)
    wide = (today - timedelta(days=2 * sampler.HORIZON_DAYS)).isoformat()
    short = (today - timedelta(days=sampler.HORIZON_DAYS)).isoformat()
    assert f"DATE '{wide}'" in asked["orders"] and f"DATE '{short}'" in asked["users"]
    read_today = [o for o in store.observations("c1", "orders") if o.measured_on == today]
    assert len(read_today) == 2 * sampler.HORIZON_DAYS


def test_the_daily_reading_runs_once_per_utc_day(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(sampler, "_last_sample_day", "")
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda: [{"id": "c1"}, {"id": "c-quiet"}])
    monkeypatch.setattr(sampler, "time_tables",
                        lambda cid: [("orders", "ts", 1)] if cid == "c1" else [])
    monkeypatch.setattr("aughor.db.measure.run_sql_for", lambda cid: (lambda sql: (["d", "n"], [], None)))
    monkeypatch.setattr(sampler, "sample_connection",
                        lambda cid, run_sql, today=None: calls.append(cid) or
                        {"sampled": ["orders"], "errors": {}})
    now = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    assert sampler.run_settling_samples_daily(now=now) == 1
    assert sampler.run_settling_samples_daily(now=now) == 0          # same day: already read
    assert sampler.run_settling_samples_daily(now=now, force=True) == 1
    assert sampler.run_settling_samples_daily(now=now + timedelta(days=1)) == 1
    assert calls == ["c1", "c1", "c1"]


def test_learn_constants_are_the_ones_the_verdict_reports():
    v = settle_lag([])
    assert v.tolerance == learn.DEFAULT_TOLERANCE and v.lag_days is None


# ── the consumers: a learned lag reaches the briefing, the deep run, the monitor, the chat ──

def test_a_persons_lag_wins_the_learned_lag_beats_the_default_and_is_clamped():
    from aughor.automations.temporal import DEFAULT_LAG_DAYS, MAX_LAG_DAYS, resolve_lag
    assert resolve_lag({"observation_lag_days": 8}, learned_lag=3) == 8
    assert resolve_lag({}, learned_lag=6) == 6
    assert resolve_lag({}, learned_lag=None) == DEFAULT_LAG_DAYS
    assert resolve_lag({}, learned_lag=90) == MAX_LAG_DAYS
    assert resolve_lag(None, learned_lag=0) == DEFAULT_LAG_DAYS


def test_the_scheduled_grounding_observes_at_the_learned_lag_when_the_step_sets_none():
    from types import SimpleNamespace

    from aughor.automations.temporal import scheduled_grounding
    auto = SimpleNamespace(id="a1", conditions=[SimpleNamespace(kind="schedule", config={"cron": "0 9 * * *"})])
    now = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    learned = scheduled_grounding(auto, {"question": "q"}, now=now, learned_lag=6)
    assert "observation lag of 6 days" in learned and "6 days behind today" in learned
    explicit = scheduled_grounding(auto, {"observation_lag_days": 8}, now=now, learned_lag=6)
    assert "observation lag of 8 days" in explicit and "6 days" not in explicit
    plain = scheduled_grounding(auto, {}, now=now, learned_lag=None)
    assert "observation lag" not in plain


def test_the_deep_run_window_ends_at_the_last_settled_day_not_merely_yesterday():
    from types import SimpleNamespace

    from aughor.agent.investigate import _clamp_intake_to_coverage

    def intake():
        return SimpleNamespace(
            observation_start="2026-09-10", observation_end="2026-09-23",
            observation_label="Last two weeks", comparison_start="2026-08-27",
            comparison_end="2026-09-09", comparison_label="Prior two weeks",
            cross_sectional=False, intake_notes="")

    it = intake()
    note = _clamp_intake_to_coverage(it, "2025-01-01", "2026-09-23", question="what changed?",
                                     today="2026-09-23", settle_days=8)
    assert it.observation_end == "2026-09-15"
    assert note and "still restating" in note and "8 days after a day ends" in note
    assert "last settled day 2026-09-15" in note

    # A window that ends on a settled day is left alone even though the data reaches today.
    it2 = intake()
    it2.observation_end = "2026-09-14"
    note2 = _clamp_intake_to_coverage(it2, "2025-01-01", "2026-09-23", question="what changed?",
                                      today="2026-09-23", settle_days=8)
    assert it2.observation_end == "2026-09-14" and not (note2 and "restating" in note2)

    # With the default of one day the existing sentence is byte-for-byte what it was.
    it3 = intake()
    note3 = _clamp_intake_to_coverage(it3, "2025-01-01", "2026-09-23", question="what changed?",
                                      today="2026-09-23")
    assert it3.observation_end == "2026-09-22" and "day still in progress" in note3


def test_the_anomaly_monitor_scores_the_newest_settled_day(monkeypatch):
    from aughor.monitors import runner

    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: 7 if cid == "c1" else None)
    today = date(2026, 9, 23)
    pts = [(date(2026, 9, 23) - timedelta(days=i), float(100 - i)) for i in range(12)][::-1]
    kept = runner._drop_unsettled(pts, "c1", today=today)
    assert [d.isoformat() for d, _ in kept][-1] == "2026-09-16"
    assert len(kept) == 5
    assert runner._drop_unsettled(pts, "c-other", today=today) == pts
    undated = [(None, 1.0), (None, 2.0)]
    assert runner._drop_unsettled(undated, "c1", today=today) == undated


def test_the_conversation_is_told_which_days_are_still_settling(monkeypatch):
    from aughor.agent.converse_tools import converse_system_prompt

    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: 7 if cid == "c-lag" else None)
    told = converse_system_prompt("c-lag")
    assert "go on changing for 7 days after it ends (learned from observation)" in told
    assert "Treat totals for the last 7 days as provisional" in told
    assert "still settling" not in converse_system_prompt("c-quiet")
    assert "provisional" not in converse_system_prompt("c-quiet")


def test_the_settling_door_serves_the_store_and_takes_a_reading(home, monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app

    client = TestClient(app)
    empty = client.get("/settling/c1")
    assert empty.status_code == 200
    assert empty.json() == {"connection_id": "c1", "tables": [], "learned_lag_days": None,
                            "lag_source": None, "still_moving": []}

    _fake_profiles(monkeypatch, {"orders": {"primary_timestamp": "created_at", "row_count": 100}})
    monkeypatch.setattr("aughor.db.measure.run_sql_for",
                        lambda cid: (lambda sql: (["day", "n"], [("2026-09-22", 1745)], None)))
    taken = client.post("/settling/c1/sample")
    assert taken.status_code == 200 and taken.json()["sampled"] == ["orders"]
    after = client.get("/settling/c1").json()
    assert after["tables"][0]["table"] == "orders"
    assert after["tables"][0]["observations"] == sampler.HORIZON_DAYS
    assert after["tables"][0]["verdict"]["lag_days"] is None
    assert after["tables"][0]["verdict"]["reason"].startswith("insufficient evidence")
