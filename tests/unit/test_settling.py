"""Idea 4 · learn when each table's numbers stop changing.

The learner is fed theLook's measured shape (2026-09-05: a day's count is a function of its
AGE — a ramp that flattens a week out) and must name the lag; fed too little, or a day
still moving at the edge of what was read, it must refuse with the reason. The sampler is
driven with a fake warehouse; the store round-trips through an isolated data home.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable

import pytest

from aughor.settling import learn, sampler, settling_answer, store
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



def _sampled(mornings: int, window: int = 14) -> list[Observation]:
    """A source whose days are final the next morning, read once a morning from S over the last ``window`` days —
    the sampler's own shape. Each day's count is fixed."""
    s = D0 + timedelta(days=window)
    return [Observation(day=m - timedelta(days=a), measured_on=m, value=40.0)
            for m in (s + timedelta(days=i) for i in range(mornings)) for a in range(1, window + 1)]


def test_a_day_first_read_old_and_steady_since_does_not_set_the_lag():
    """LuxExperience 2026-10-14: four mornings in, the oldest days of the first window had been read at ages 12–14
    only, steady throughout, and the lag was learned as 12. Its days are final the next morning."""
    assert settle_lag(_sampled(4)).lag_days == 2          # three days shown final from age ≤ 2
    assert settle_lag(_sampled(5)).lag_days == 1
    assert "1 day after it ends" in settle_lag(_sampled(5)).reason

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
                   "horizon": 12, "rewrites": []}
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
    assert len(asked) == 3   # orders' horizon and its old days; broken failed before its old days were asked
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
    asked: dict[str, list[str]] = {"orders": [], "users": []}

    def run_sql(sql):
        asked["orders" if '"orders"' in sql else "users"].append(sql)
        return ["day", "n"], [], None

    sampler.sample_connection("c1", run_sql, today=today)
    wide = (today - timedelta(days=2 * sampler.HORIZON_DAYS)).isoformat()
    short = (today - timedelta(days=sampler.HORIZON_DAYS)).isoformat()
    assert f"DATE '{wide}'" in asked["orders"][0] and f"DATE '{short}'" in asked["users"][0]
    read_today = [o for o in store.observations("c1", "orders") if o.measured_on == today]
    assert len(read_today) == 2 * sampler.HORIZON_DAYS
    # and every table not yet shown to settle reads the days six months back, filed apart from the horizon's
    old = (today - timedelta(days=sampler.OLD_DAYS[1])).isoformat()
    assert len(asked["orders"]) == 2 and f"DATE '{old}'" in asked["orders"][1]
    assert len(asked["users"]) == 2 and f"DATE '{old}'" in asked["users"][1]
    assert {o.day.isoformat() for o in store.old_readings("c1", "orders")} >= {old}
    assert store.verdicts("c1")["orders"].horizon_days < sampler.OLD_DAYS[0]


def test_a_failed_read_of_the_old_days_is_reported_and_the_days_reading_stands(home, monkeypatch):
    _fake_profiles(monkeypatch, {"orders": {"primary_timestamp": "created_at", "row_count": 100}})
    for i in range(4):
        day = D0 + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations("c1", "orders", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): 100.0 * age})
    today = date(2026, 9, 23)
    old = (today - timedelta(days=sampler.OLD_DAYS[1])).isoformat()

    def run_sql(sql):
        if f"DATE '{old}'" in sql:
            return [], [], "the warehouse said no"
        return ["day", "n"], [], None

    out = sampler.sample_connection("c1", run_sql, today=today)
    assert out["sampled"] == ["orders"] and out["errors"] == {"orders, its old days": "the warehouse said no"}
    assert [o for o in store.observations("c1", "orders") if o.measured_on == today]
    assert store.old_readings("c1", "orders") == []


# ── a source that rewrites its history ───────────────────────────

OLD_DAY = date(2026, 3, 1)


def _old_readings(*readings: list[float]) -> list[Observation]:
    """Each argument is one reading, a day apart, of the same days six months old."""
    return [Observation(day=OLD_DAY + timedelta(days=n), measured_on=date(2026, 9, 1) + timedelta(days=i), value=v)
            for i, values in enumerate(readings) for n, v in enumerate(values)]


def test_old_days_moving_at_two_readings_is_a_source_that_rewrites_its_history():
    """theLook's shape, measured 2026-11-04: a typical six-month-old day moved 8% in one refresh, up as often as down."""
    a, b, c = [200.0] * 7, [216.0, 184.0] * 3 + [216.0], [190.0, 210.0] * 3 + [190.0]
    assert learn.rewrites_history(_old_readings(a, b, c)) is True
    assert learn.rewrites_history(_old_readings(a, b)) is False           # one is a backfill
    assert learn.rewrites_history(_old_readings(a, b, b, b)) is False     # and it then stayed put
    assert learn.rewrites_history(_old_readings(a, a, a, a)) is False


def test_it_takes_half_the_old_days_moving_past_the_tolerance():
    flat, half, less = [200.0] * 8, [216.0] * 4 + [200.0] * 4, [216.0] * 3 + [200.0] * 5
    assert learn.rewrites_history(_old_readings(flat, half, flat)) is True
    assert learn.rewrites_history(_old_readings(flat, less, flat)) is False
    within = [201.0] * 8                                                  # within 1%: a deleted row or two
    assert learn.rewrites_history(_old_readings(flat, within, flat)) is False


def test_days_with_no_rows_and_too_few_days_say_nothing():
    assert learn.rewrites_history(_old_readings([0.0] * 7, [0.0] * 7, [0.0] * 7)) is False
    assert learn.rewrites_history(_old_readings([200.0] * 2, [216.0] * 2, [200.0] * 2)) is False
    # empty days are not days that held still: three days with rows, all moving, and five with none
    a, b = [200.0] * 3 + [0.0] * 5, [216.0] * 3 + [0.0] * 5
    assert learn.rewrites_history(_old_readings(a, b, a)) is True


def test_the_two_kinds_of_reading_are_kept_apart_and_neither_drops_the_other(home):
    store.record_observations("c1", "orders", "created_at", date(2026, 9, 2), {"2026-09-01": 100.0})
    store.record_old_readings("c1", "orders", date(2026, 9, 2), {"2026-03-01": 200.0})
    store.record_observations("c1", "orders", "created_at", date(2026, 9, 3), {"2026-09-01": 90.0})
    store.record_old_readings("c1", "orders", date(2026, 9, 3), {"2026-03-01": 210.0})
    assert [o.value for o in store.observations("c1", "orders")] == [100.0, 90.0]
    assert [o.value for o in store.old_readings("c1", "orders")] == [200.0, 210.0]
    assert store.verdicts("c1")["orders"].horizon_days == 2


def test_a_table_whose_old_days_keep_moving_rewrites_its_history_whatever_its_recent_days_show(home):
    """Between one redraw and the next a source's recent days hold still, and read as settled. Its old days say otherwise."""
    for i in range(4):
        day = D0 + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations("c1", "orders", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): RAMP[age]})
            store.record_observations("c1", "order_items", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): 100.0 * age})
            store.record_observations("c1", "users", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): RAMP[age]})
    old_days = [(OLD_DAY + timedelta(days=n)).isoformat() for n in range(7)]
    for t, values in (("order_items", (200.0, 216.0, 190.0)), ("users", (200.0, 216.0, 190.0)), ("orders", (200.0, 200.0, 200.0))):
        for i, v in enumerate(values):
            store.record_old_readings("c1", t, date(2026, 9, 20 + i), dict.fromkeys(old_days, v))
    assert store.verdicts("c1")["users"].lag_days is not None           # its recent days read as settled
    lag = store.connection_lag("c1")
    assert lag["rewrites"] == ["order_items", "users"] and "users" in lag["still_moving"] and lag["source"] == "beyond_horizon"
    said = {r["table"]: r["verdict"]["reason"] for r in store.summary("c1")["tables"]}
    assert said["order_items"].startswith("its old days keep being rewritten") and store.summary("c1")["rewrites"] == lag["rewrites"]
    assert "rewritten" not in said["orders"]


def test_a_backfill_long_past_is_not_a_habit_and_a_pause_in_a_habit_is_not_its_end():
    def reading(day, value):
        return [Observation(day=OLD_DAY + timedelta(days=n), measured_on=day, value=value) for n in range(7)]
    start = date(2026, 6, 1)
    moved = reading(start, 200.0) + reading(start + timedelta(days=1), 216.0) + reading(start + timedelta(days=2), 190.0)
    assert learn.rewrites_history(moved) is True
    # no refresh for three weeks reads nothing new: still the source that did this
    paused = moved + [o for d in range(3, 24) for o in reading(start + timedelta(days=d), 190.0)]
    assert learn.rewrites_history(paused) is True
    # then, over a month with nothing moved, it was a backfill
    long_past = moved + [o for d in range(3, 40) for o in reading(start + timedelta(days=d), 190.0)]
    assert learn.rewrites_history(long_past) is False


def test_a_table_no_longer_read_stops_speaking_for_its_connection_once_its_readings_would_have_aged_out(home):
    for i in range(4):
        day = D0 + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations("c1", "gone", "created_at", day + timedelta(days=age), {day.isoformat(): 100.0 * age})
    assert store.connection_lag("c1")["still_moving"] == ["gone"]
    later = D0 + timedelta(days=store.KEEP_DAYS + 30)
    for i in range(4):
        day = later + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations("c1", "read", "created_at", day + timedelta(days=age), {day.isoformat(): RAMP[age]})
    lag = store.connection_lag("c1")
    assert lag["still_moving"] == [] and lag["source"] == "learned" and lag["days"] == 7


def test_the_horizon_said_is_the_moving_tables_own_not_a_longer_ones(home):
    for i in range(4):
        day = D0 + timedelta(days=i)
        for age in range(1, 21):       # read to 20, and it settled
            store.record_observations("c1", "long", "created_at", day + timedelta(days=age),
                                      {day.isoformat(): RAMP.get(age, RAMP[12])})
        for age in range(1, 13):       # read to 12, and it has not
            store.record_observations("c1", "short", "created_at", day + timedelta(days=age), {day.isoformat(): 100.0 * age})
    assert store.connection_lag("c1")["horizon"] == 12


def test_the_daily_reading_runs_once_per_utc_day(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(sampler, "_last_sample_day", "")
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda: [{"id": "c1"}, {"id": "c-quiet"}])
    monkeypatch.setattr(sampler, "time_tables",
                        lambda cid: [("orders", "ts", 1)] if cid == "c1" else [])
    monkeypatch.setattr("aughor.db.measure.run_sql_for", lambda cid, **kw: (lambda sql: (["d", "n"], [], None)))
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
    assert note and "may still change" in note and "8 days after a day ends, learned from observation" in note
    assert "newest day to read, 2026-09-15" in note

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

    monkeypatch.setattr("aughor.settling.store.connection_lag",
                        lambda cid: {"days": 7, "source": "learned", "still_moving": [], "horizon": 14, "rewrites": []}
                        if cid == "c-lag" else {"days": None, "source": None, "still_moving": [], "horizon": 0, "rewrites": []})
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
                            "lag_source": None, "still_moving": [], "rewrites": []}

    _fake_profiles(monkeypatch, {"orders": {"primary_timestamp": "created_at", "row_count": 100}})
    monkeypatch.setattr("aughor.db.measure.run_sql_for",
                        lambda cid, **kw: (lambda sql: (["day", "n"], [("2026-09-22", 1745)], None)))
    taken = client.post("/settling/c1/sample")
    assert taken.status_code == 200 and taken.json()["sampled"] == ["orders"]
    after = client.get("/settling/c1").json()
    assert after["tables"][0]["table"] == "orders"
    assert after["tables"][0]["observations"] == sampler.HORIZON_DAYS
    assert after["tables"][0]["verdict"]["lag_days"] is None
    assert after["tables"][0]["verdict"]["reason"].startswith("insufficient evidence")


# ── a source connected tomorrow ──────────────────────────────────────────────────────────

def _warehouse(clock: dict, value_on: Callable):
    """Every day of the horizon and six months back reads ``value_on(today)``: a table redrawn whole moves them together."""
    def run_sql(sql):
        today = clock["today"]
        old_from = (today - timedelta(days=sampler.OLD_DAYS[1])).isoformat()
        ages = range(*sampler.OLD_DAYS) if f"DATE '{old_from}'" in sql else range(1, 2 * sampler.HORIZON_DAYS + 1)
        return ["day", "n"], [((today - timedelta(days=n)).isoformat(), value_on(today)) for n in ages], None
    return run_sql


@pytest.mark.parametrize("cycle", [1, 3, 7, 12])
def test_a_new_source_redrawn_at_each_refresh_is_recognised_at_its_second_refresh(home, monkeypatch, cycle):
    _fake_profiles(monkeypatch, {"redrawn": {"primary_timestamp": "created_at", "row_count": 100}})
    start = date(2026, 9, 21)
    clock = {"today": start}
    # a new draw every `cycle` days, each differing from the last by far more than the tolerance
    run_sql = _warehouse(clock, lambda today: 200.0 + 20.0 * ((today - start).days // cycle % 2))
    kinds = []
    for offset in range(2 * cycle + 1):
        clock["today"] = start + timedelta(days=offset)
        assert sampler.sample_connection("c1", run_sql, today=clock["today"])["sampled"] == ["redrawn"]
        kinds.append(settling_answer("c1").kind)
    assert kinds[cycle] != "rewrites"                     # one refresh seen could be a backfill
    assert kinds[2 * cycle] == "rewrites"                 # a second means the source does this
    for offset in range(2 * cycle + 1, 3 * cycle + 1):    # and between refreshes, when its recent days hold still, it still does
        clock["today"] = start + timedelta(days=offset)
        sampler.sample_connection("c1", run_sql, today=clock["today"])
        assert settling_answer("c1").kind == "rewrites"


def test_a_new_source_whose_days_hold_is_not_called_one_that_rewrites(home, monkeypatch):
    _fake_profiles(monkeypatch, {"steady": {"primary_timestamp": "created_at", "row_count": 100}})
    clock = {"today": date(2026, 9, 21)}
    run_sql = _warehouse(clock, lambda today: 200.0)
    for offset in range(5):
        clock["today"] = date(2026, 9, 21) + timedelta(days=offset)
        assert sampler.sample_connection("c1", run_sql, today=clock["today"])["sampled"] == ["steady"]
    assert store.connection_lag("c1")["rewrites"] == [] and settling_answer("c1").kind == "settles"


def _settled_verdict(conn: str, table: str):
    for i in range(4):
        day = D0 + timedelta(days=i)
        for age in range(1, 13):
            store.record_observations(conn, table, "created_at", day + timedelta(days=age), {day.isoformat(): RAMP[age]})


def test_a_table_is_read_six_months_back_until_its_old_days_have_held_for_a_month_and_not_after(home, monkeypatch):
    _fake_profiles(monkeypatch, {"orders": {"primary_timestamp": "created_at", "row_count": 100}})
    _settled_verdict("c1", "orders")
    asked: list[str] = []

    def run_sql(sql):
        asked.append(sql)
        return ["day", "n"], [], None

    today = date(2026, 9, 23)
    sampler.sample_connection("c1", run_sql, today=today)
    assert len(asked) == 2                                # settled on its recent days, which shows nothing yet
    old_days = [(OLD_DAY + timedelta(days=n)).isoformat() for n in range(7)]
    held = today + timedelta(days=learn.STILL_A_HABIT_DAYS)
    for d in (today, held):
        store.record_old_readings("c1", "orders", d, dict.fromkeys(old_days, 200.0))
    asked.clear()
    sampler.sample_connection("c1", run_sql, today=held)
    assert len(asked) == 1
    # a month that held, then a table still moving on its recent days: it is read again
    for i in range(4):
        day = held - timedelta(days=20 - i)
        for age in range(1, 13):
            store.record_observations("c1", "orders", "created_at", day + timedelta(days=age), {day.isoformat(): 100.0 * age})
    asked.clear()
    sampler.sample_connection("c1", run_sql, today=held + timedelta(days=1))
    assert len(asked) == 2


def test_old_days_have_not_held_until_a_month_of_readings_moved_none_of_them():
    def reading(day, value):
        return [Observation(day=OLD_DAY + timedelta(days=n), measured_on=day, value=value) for n in range(7)]
    start = date(2026, 6, 1)
    assert learn.old_days_held([]) is False
    assert learn.old_days_held(reading(start, 200.0) + reading(start + timedelta(days=5), 200.0)) is False
    month = start + timedelta(days=learn.STILL_A_HABIT_DAYS)
    assert learn.old_days_held(reading(start, 200.0) + reading(month, 200.0)) is True
    assert learn.old_days_held(reading(start, 200.0) + reading(start + timedelta(days=1), 216.0) + reading(month, 216.0)) is False


def test_a_table_a_metric_reads_is_read_first_past_the_cap_and_by_the_metrics_own_date(home, monkeypatch):
    many = {f"t{i:02d}": {"primary_timestamp": "ts", "row_count": 1000 + i} for i in range(sampler.MAX_TABLES_PER_CONNECTION + 2)}
    many["small"] = {"primary_timestamp": "ts", "row_count": 1}
    many["undated"] = {"row_count": 2}             # the profiler found no main date on it; the metric names one
    _fake_profiles(monkeypatch, many)
    monkeypatch.setattr(sampler, "_metric_dates", lambda cid: {"small": "ts", "undated": "sold_at"})
    got = sampler.time_tables("c1")
    assert {t for t, _, _ in got[:2]} == {"small", "undated"} and dict((t, c) for t, c, _ in got)["undated"] == "sold_at"
    assert len(got) == sampler.MAX_TABLES_PER_CONNECTION
    assert got[2][0] == f"t{sampler.MAX_TABLES_PER_CONNECTION + 1:02d}"          # then the largest, as before

    every = {f"m{i:02d}": "ts" for i in range(sampler.MAX_TABLES_PER_CONNECTION + 2)}
    _fake_profiles(monkeypatch, {t: {"primary_timestamp": "ts", "row_count": 1} for t in every})
    monkeypatch.setattr(sampler, "_metric_dates", lambda cid: every)
    assert len(sampler.time_tables("c1")) == len(every)                           # a table a metric reads is never left unread


def test_only_this_connections_approved_metrics_count(home, monkeypatch):
    mine = SimpleNamespace(status="approved", connection="c1", time_column="sales.sold_at", tables=["sales", "items"], sql="")
    draft = SimpleNamespace(status="draft", connection="c1", time_column="drafted.at", tables=["drafted"], sql="")
    other = SimpleNamespace(status="approved", connection="c2", time_column="theirs.at", tables=["theirs"], sql="")
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: [mine, draft, other])
    assert sampler._metric_dates("c1") == {"sales": "sold_at", "items": ""}
    # a table two metrics read keeps the date one of them gives it, whichever comes first
    dated = SimpleNamespace(status="approved", connection="c1", time_column="items.made_at", tables=["items"], sql="")
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: [mine, dated])
    assert sampler._metric_dates("c1")["items"] == "made_at"


def test_a_table_a_metric_only_joins_is_read_past_the_cap_by_the_profiles_date(home, monkeypatch):
    many = {f"t{i:02d}": {"primary_timestamp": "ts", "row_count": 1000 + i} for i in range(sampler.MAX_TABLES_PER_CONNECTION + 2)}
    many["joined"] = {"primary_timestamp": "made_at", "row_count": 1}
    _fake_profiles(monkeypatch, many)
    monkeypatch.setattr(sampler, "_metric_dates", lambda cid: {"joined": ""})
    got = sampler.time_tables("c1")
    assert got[0] == ("joined", "made_at", 1) and len(got) == sampler.MAX_TABLES_PER_CONNECTION
