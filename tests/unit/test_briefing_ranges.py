"""Arc BR-2/BR-3 (ROADMAP §3.48) — the Briefing of any range, measured from approved metrics.

The resolver is pinned on the user's own example (17–26 August, asked on 26 September, with
theLook's 13-day lag) and on §3.27's windows, which the named presets must reproduce exactly.
The build runs end to end on a DuckDB shop with the narrator stubbed: approved metrics are
measured (their dates set by rule), a north star with no approved definition is named, and
two custom ranges never share a cache entry.
"""
from __future__ import annotations

import contextlib
from datetime import date

import duckdb
import pytest

import aughor.knowledge.briefing as briefing_mod
import aughor.llm.provider as prov
from aughor.automations.temporal import complete_period
from aughor.briefing import ranges
from aughor.business_profile.models import BusinessProfile, NorthStarMetric
from aughor.knowledge.briefing import BriefingNarrative

SEP26 = date(2026, 9, 26)


# ── the resolver ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("preset, period", sorted(ranges.PRESET_PERIOD.items()))
def test_a_named_preset_is_exactly_the_period_section_3_27_reads(preset, period):
    spec, why = ranges.resolve_range(preset, today=SEP26, lag_days=13)
    w = complete_period(period, SEP26, 13)
    assert why == "" and (spec.start, spec.end, spec.previous_start, spec.previous_end) == (
        w.start, w.end, w.previous_start, w.previous_end)
    assert spec.period == period


def test_the_users_range_is_compared_with_the_days_just_before():
    """17–26 August 2026 (Monday to Wednesday), asked on 26 September. Back to back (the user,
    2026-10-08): the whole-week shift matched the weekday mix but left the days between unread."""
    spec, why = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26,
                                     lag_days=13)
    assert why == "" and spec.days == 10 and spec.key == "range:custom:2026-08-17..2026-08-26"
    assert (spec.previous_start, spec.previous_end) == (date(2026, 8, 7), date(2026, 8, 17))
    assert (spec.last_year_start, spec.last_year_end) == (date(2025, 8, 18), date(2025, 8, 28))
    assert spec.last_year_start.weekday() == spec.start.weekday()      # a year earlier keeps its weekdays
    words = ranges.phrases(spec)
    assert words["covers"] == "2026-08-17 to 2026-08-26 (10 days)"
    assert words["compared_with"] == "the 10 days before, 2026-08-07 to 2026-08-16"
    # a cohort's comparisons are read at the same age: 31 days after each window's last day
    w = {x.label: x for x in spec.windows()}
    assert {(x.as_of - x.last_day).days for x in w.values()} == {31}


def test_month_to_date_ends_at_the_last_settled_day_and_compares_like_for_like():
    spec, _ = ranges.resolve_range("month_to_date", today=SEP26, lag_days=13)
    assert (spec.start, spec.last_day) == (date(2026, 9, 1), date(2026, 9, 13))
    assert (spec.previous_start, spec.previous_end) == (date(2026, 8, 1), date(2026, 8, 14))
    assert (spec.last_year_start, spec.last_year_end) == (date(2025, 9, 1), date(2025, 9, 14))


@pytest.mark.parametrize("kw, why", [
    ({"start": date(2026, 9, 27), "end": date(2026, 9, 30)}, "in the future"),
    ({"start": date(2026, 8, 26), "end": date(2026, 8, 17)}, "ends before it starts"),
    ({"start": date(2020, 1, 1), "end": date(2026, 9, 1)}, "read it as years"),
    ({"preset": "fortnight"}, "a range is one of"),
])
def test_a_range_that_cannot_be_read_says_why(kw, why):
    preset = kw.pop("preset", None)
    spec, reason = ranges.resolve_range(preset, today=SEP26, **kw)
    assert spec is None and why in reason


# ── the build ───────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def con():
    c = duckdb.connect()
    # one 'done' order a day worth 1,000 × its day of the month, and one cancelled order a day
    c.execute("""CREATE TABLE orders AS
        SELECT d::TIMESTAMP + INTERVAL 9 HOUR AS created_at,
               CAST(day(d) AS DOUBLE) * 1000 AS amount, 'done' AS status
        FROM range(DATE '2025-01-01', DATE '2026-09-26', INTERVAL 1 DAY) t(d)
        UNION ALL
        SELECT d::TIMESTAMP + INTERVAL 10 HOUR, 99999.0, 'cancelled'
        FROM range(DATE '2025-01-01', DATE '2026-09-26', INTERVAL 1 DAY) t(d)""")
    yield c
    c.close()


def _runner(con):
    @contextlib.contextmanager
    def open_():
        def run_sql(sql):
            try:
                cur = con.execute(sql)
                return [d[0] for d in cur.description], cur.fetchall(), None
            except Exception as exc:  # noqa: BLE001
                return [], [], str(exc)
        yield run_sql, "duckdb"
    return open_


class FakeNarrator:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls.append((system, user))
        return BriefingNarrative(narrative="Revenue moved.", headline_theme="Theme", citations=[])


@pytest.fixture
def narrator(monkeypatch, tmp_path):
    fake = FakeNarrator()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fake)
    from aughor.util.json_store import KeyedJsonStore
    store = KeyedJsonStore(tmp_path / "briefing_cache.json")
    monkeypatch.setattr(briefing_mod, "_store", lambda: store)
    return fake


@pytest.fixture
def approved(monkeypatch, tmp_path):
    """c1's catalogue: an approved revenue (cancelled orders excluded), a draft that must not be
    measured; the profiler knows orders.created_at. Its own catalogue file — the suite's is
    session-wide, and rows written here would leak into every later test's read."""
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    from aughor.semantic.metrics import MetricDefinition, save_metric
    save_metric(MetricDefinition(name="revenue", connection="c1", label="Revenue", sql="SUM(amount)",
                                 tables=["orders"], filters=["status <> 'cancelled'"], unit="USD",
                                 status="approved", approved_by="test"))
    save_metric(MetricDefinition(name="aov", connection="c1", label="AOV", sql="AVG(amount)",
                                 tables=["orders"], status="draft"))
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: {
        "tables": {"orders": {"primary_timestamp": "created_at"}},
        "columns": {f"orders.{c}": {"table": "orders", "column": c, "dtype": d}
                    for c, d in (("created_at", "TIMESTAMP"), ("amount", "DOUBLE"), ("status", "VARCHAR"))}})


def _profile():
    ns = NorthStarMetric(name="Gross margin", definition="-", maps_to="orders", why_it_matters="-",
                         unit_or_range="%", chart_sql="")
    return BusinessProfile(industry="Retail", business_model="transactional-retail", summary="A shop.",
                           north_star_metrics=[ns], key_questions=[], confidence=0.9,
                           evidence="test fixture", currency_code="USD")


def test_a_range_briefing_measures_the_approved_metrics_and_names_the_rest(con, narrator, approved):
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    brief = ranges.build_range_briefing("c1", spec, scope_key="c1", domain_data={}, profile=_profile(),
                                        runner=_runner(con))
    block = brief["period"]
    [rev] = block["measured"]
    assert (rev["name"], rev["current"], rev["previous"]) == ("Revenue", 215000.0, 115000.0)  # 17..26, 7..16 ×1,000
    assert rev["status"] == "final" and rev["time_kind"] == "flow"
    assert rev["time_source"].startswith("set automatically: created_at is the main date of orders")
    assert {u["name"]: u["reason"] for u in block["unmeasured"]} == {
        "Gross margin": "no approved definition; approve one in the Semantic Layer to measure it"}
    system, user = narrator.calls[-1]
    assert "2026-08-17 to 2026-08-26 (10 days)" in user and "CUSTOM RANGE" in user
    assert briefing_mod._store().get("c1#range:custom:2026-08-17..2026-08-26")


def test_two_custom_ranges_never_share_a_cache_entry(con, narrator, approved):
    for s, e in ((date(2026, 8, 17), date(2026, 8, 26)), (date(2026, 7, 1), date(2026, 7, 10))):
        spec, _ = ranges.resolve_range(start=s, end=e, today=SEP26, lag_days=13)
        ranges.build_range_briefing("c1", spec, scope_key="c1", domain_data={}, profile=_profile(),
                                    runner=_runner(con))
    keys = set(briefing_mod._store().load() or {})
    assert {"c1#range:custom:2026-08-17..2026-08-26", "c1#range:custom:2026-07-01..2026-07-10"} <= keys


def test_the_route_refuses_a_range_while_the_flag_is_off_and_a_bad_one_with_why(monkeypatch):
    from fastapi import HTTPException

    from aughor.routers import exploration
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "0")
    assert exploration._range_spec_or_refuse("c1", "week", None, None, None, None) is None  # §3.27 answers
    with pytest.raises(HTTPException) as off:
        exploration._range_spec_or_refuse("c1", None, "last_week", None, None, None)
    assert off.value.status_code == 404 and "briefing.ranges" in off.value.detail
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    with pytest.raises(HTTPException) as bad:
        exploration._range_spec_or_refuse("c1", None, None, "2026-08-26", "2026-08-17", None)
    assert bad.value.status_code == 422 and "ends before it starts" in bad.value.detail
    spec = exploration._range_spec_or_refuse("c1", "week", None, None, None, None)
    assert spec.preset == "last_week"


def test_dates_set_by_an_older_rule_are_rederived_and_a_persons_are_left_alone(approved, monkeypatch):
    """2026-09-26: the first live run saved every theLook metric as a flow on its table's main
    date; the fixed rule must be able to replace what it set — and never what a person set."""
    from aughor.semantic import metric_time as mt
    from aughor.semantic.metrics import MetricDefinition, get_metric, save_metric
    save_metric(MetricDefinition(name="shipped", connection="c1", label="Shipped", sql="COUNT(*)",
                                 tables=["orders"], filters=["shipped_at IS NOT NULL"],
                                 status="approved", approved_by="test", time_kind="flow",
                                 time_column="created_at", time_source="set automatically: an older rule"))
    save_metric(MetricDefinition(name="confirmed", connection="c1", label="Confirmed", sql="SUM(amount)",
                                 tables=["orders"], status="approved", approved_by="test",
                                 time_kind="flow", time_column="shipped_at", time_confirmed_by="Ana"))
    import aughor.tools.profile_cache as pc
    base = pc.latest_profile_entry("c1")
    base["columns"]["orders.shipped_at"] = {"table": "orders", "column": "shipped_at", "dtype": "TIMESTAMP"}
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: base)
    said = mt.ensure_dates("c1")
    assert get_metric("shipped", connection_id="c1").time_column == "shipped_at"
    assert said["confirmed"] == "confirmed by Ana"
    assert get_metric("confirmed", connection_id="c1").time_column == "shipped_at"


def test_a_share_moves_in_points_not_percent_of_a_percent():
    """theLook 2026-09-25: the narrator called 15.1% → 14.3% "a 6% improvement"."""
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    block = ranges.range_block(spec)
    m = {"name": "Return rate", "unit": "ratio 0..1", "current": 0.142857, "previous": 0.151255,
         "last_year": 0.161491, "rel": -0.0555, "rel_last_year": -0.115, "status": "final",
         "time_kind": "cohort"}
    line = ranges.metric_line(m, block, "USD")
    assert line.startswith("Return rate moved from 15.1% to 14.3% (-0.8 pts)")
    assert "16.1% a year earlier, 2025-08-18 to 2025-08-27 (-1.9 pts)" in line


# ── the Cockpit's default view and what a figure opens to (ROADMAP §6 item 43) ────────────────

def test_the_measures_alone_are_the_briefings_own_figures_with_no_narrator(con, narrator, approved):
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    block = ranges.measured_block("c1", spec, profile=_profile(), runner=_runner(con))
    brief = ranges.build_range_briefing("c1", spec, scope_key="c1", domain_data={}, profile=_profile(),
                                        runner=_runner(con))
    calls_for_the_briefing = len(narrator.calls)
    [alone], [built] = block["measured"], brief["period"]["measured"]
    same = ("name", "current", "previous", "last_year", "rel", "status", "unit",
            "current_text", "previous_text", "last_year_text")
    assert {k: alone[k] for k in same} == {k: built[k] for k in same}
    assert alone["current_text"] and block["covers"] == brief["period"]["covers"]
    assert {u["name"] for u in block["unmeasured"]} == {"Gross margin"}
    ranges.measured_block("c1", spec, profile=_profile(), runner=_runner(con))
    assert len(narrator.calls) == calls_for_the_briefing == 1          # measuring alone never writes


def test_measures_that_cannot_open_the_connection_say_so():
    @contextlib.contextmanager
    def closed():
        raise ConnectionError("the warehouse is away")
        yield  # pragma: no cover

    spec, _ = ranges.resolve_range("last_week", today=SEP26, lag_days=13)
    block = ranges.measured_block("c1", spec, runner=closed)
    assert block["measured"] == [] and "could not be opened (ConnectionError)" in block["unmeasured"][0]["reason"]


@pytest.mark.parametrize("kw, n, expected", [
    # a day is read against the same weekday: seven days back each time
    ({"preset": "yesterday"}, 3, [(date(2026, 8, 30), date(2026, 8, 31)), (date(2026, 9, 6), date(2026, 9, 7)),
                                  (date(2026, 9, 13), date(2026, 9, 14))]),
    # whole calendar months, whatever their length
    ({"preset": "last_month"}, 3, [(date(2026, 6, 1), date(2026, 7, 1)), (date(2026, 7, 1), date(2026, 8, 1)),
                                   (date(2026, 8, 1), date(2026, 9, 1))]),
    # a month to date reads the same days of each earlier month
    ({"preset": "month_to_date"}, 3, [(date(2026, 7, 1), date(2026, 7, 14)), (date(2026, 8, 1), date(2026, 8, 14)),
                                      (date(2026, 9, 1), date(2026, 9, 14))]),
    ({"preset": "last_year"}, 2, [(date(2024, 1, 1), date(2025, 1, 1)), (date(2025, 1, 1), date(2026, 1, 1))]),
    # a custom range steps back by its own length, back to back, as its comparison does
    ({"start": date(2026, 8, 17), "end": date(2026, 8, 26)}, 3,
     [(date(2026, 7, 28), date(2026, 8, 7)), (date(2026, 8, 7), date(2026, 8, 17)),
      (date(2026, 8, 17), date(2026, 8, 27))]),
])
def test_earlier_ranges_step_back_the_way_the_ranges_own_comparison_does(kw, n, expected):
    preset = kw.pop("preset", None)
    spec, why = ranges.resolve_range(preset, today=SEP26, lag_days=13, **kw)
    assert why == ""
    got = ranges.earlier_ranges(spec, n)
    assert got == expected
    assert got[-1] == (spec.start, spec.end) and got[-2] == (spec.previous_start, spec.previous_end)


def test_a_metric_opens_to_its_trend_oldest_first_with_how_it_is_defined(con, approved):
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    seen = ranges.metric_trend("c1", spec, "revenue", profile=_profile(), runner=_runner(con))
    assert seen["found"] and seen["why"] == "" and seen["name"] == "Revenue"
    assert seen["definition"] == "SUM(amount)" and seen["filters"] == ["status <> 'cancelled'"]
    assert seen["time_source"].startswith("set automatically")
    series = seen["series"]
    assert len(series) == ranges.TREND_RANGES and [p["current"] for p in series] == [False] * 7 + [True]
    assert [p["start"] for p in series] == sorted(p["start"] for p in series)
    # the last two points are the Briefing's own "this range" and "comparison"
    assert (series[-1]["value"], series[-2]["value"]) == (215000.0, 115000.0)
    assert series[-1]["label"] == "2026-08-17 to 2026-08-26" and series[-1]["value_text"]
    assert all(p["value_text"] for p in series if p["value"] is not None)


def test_a_metric_that_cannot_be_read_says_why_and_carries_no_series(con, approved):
    spec, _ = ranges.resolve_range("last_week", today=SEP26, lag_days=13)
    draft = ranges.metric_trend("c1", spec, "aov", runner=_runner(con))            # a draft is not measured
    assert draft == {"metric": "aov", "found": False, "series": [],
                     "why": "no approved metric by that name is on this connection"}

    @contextlib.contextmanager
    def broken():
        def run_sql(sql):
            return [], [], "Binder Error: no such column"
        yield run_sql, "duckdb"

    failed = ranges.metric_trend("c1", spec, "revenue", runner=broken)
    assert failed["found"] and failed["series"] == [] and failed["why"].startswith("its query failed: Binder Error")


def test_the_measures_route_hands_back_a_young_briefings_figures_and_measures_otherwise(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from aughor.routers import exploration
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    monkeypatch.setattr(exploration, "_load_business_profile", lambda cid, schema: None)
    monkeypatch.setattr(ranges, "resolve_for", lambda cid, preset, **kw: ranges.resolve_range(
        preset, today=SEP26, lag_days=13, start=kw.get("start"), end=kw.get("end")))
    spec, _ = ranges.resolve_range("last_week", today=SEP26, lag_days=13)
    measured_now = {**ranges.range_block(spec), "measured": [{"name": "Revenue", "current": 2.0}]}
    monkeypatch.setattr(ranges, "measured_block", lambda *a, **kw: measured_now)
    kept = {**ranges.range_block(spec), "measured": [{"name": "Revenue", "current": 1.0}]}
    entry = {"period": kept, "narrative": "…"}
    monkeypatch.setattr(briefing_mod, "peek_entry", lambda key: entry if key == f"c1#{spec.key}" else None)

    entry["generated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    young = exploration.measure_range_metrics("c1", preset="last_week")
    assert young["from_briefing"] is True and young["period"]["measured"][0]["current"] == 1.0

    entry["generated_at"] = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
    old = exploration.measure_range_metrics("c1", preset="last_week")
    assert old["from_briefing"] is False and old["period"]["measured"][0]["current"] == 2.0

    other_scope = exploration.measure_range_metrics("c1", schema="shop", preset="last_week")
    assert other_scope["from_briefing"] is False and other_scope["scope_key"] == "c1:shop"


# ── what each measured item is expected to read next (ROADMAP §6 item 42c) ───────────────────

def test_the_range_after_this_one_keeps_its_kind_and_its_step_back():
    day, _ = ranges.resolve_range("yesterday", today=SEP26, lag_days=13)
    nxt = ranges.later_spec(day)
    assert (nxt.start, nxt.end) == (date(2026, 9, 14), date(2026, 9, 15))
    assert nxt.start - nxt.previous_start == day.start - day.previous_start          # still the same weekday back
    month, _ = ranges.resolve_range("last_month", today=SEP26, lag_days=13)
    assert (ranges.later_spec(month).start, ranges.later_spec(month).end) == (date(2026, 9, 1), date(2026, 10, 1))
    custom, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    assert (ranges.later_spec(custom).start, ranges.later_spec(custom).end) == (date(2026, 8, 27), date(2026, 9, 6))
    for preset in ("month_to_date", "year_to_date"):
        to_date, _ = ranges.resolve_range(preset, today=SEP26, lag_days=13)
        assert ranges.later_spec(to_date) is None


def _share_metric():
    from aughor.semantic.metrics import MetricDefinition, save_metric
    save_metric(MetricDefinition(name="done_share", connection="c1", label="Done share", unit="%",
                                 sql="100.0 * SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) / COUNT(*)",
                                 tables=["orders"], status="approved", approved_by="test"))


def test_each_metric_is_expected_once_from_its_own_past_and_read_back_without_measuring(con, approved):
    from aughor.briefing import expected
    from aughor.record import claims as C
    _share_metric()
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    seen = expected.expected_next("c1", spec, profile=_profile(), runner=_runner(con), today=SEP26)
    assert seen["target"] == {"start": "2026-08-27", "last_day": "2026-09-05", "label": "2026-08-27 to 2026-09-05",
                              "settles_on": "2026-09-18"}                 # its last day and the lag, not a month on
    by = {i["metric"]: i for i in seen["items"]}
    assert set(by) == {"revenue", "done_share"}                           # the draft metric is not predicted
    rev = by["revenue"]["expected"]
    assert rev["low"] < rev["mid"] < rev["high"] and rev["n"] == 6 and rev["state"] == "open"
    assert " to " in rev["text"] and "6 earlier ranges" in rev["must_say"][0]
    claim = C.get(rev["claim_id"])
    assert claim.kind == "prediction" and claim.extra["settles_on"] == "2026-09-18" and claim.next_check == "2026-09-18"
    assert claim.extra["briefing"] == {"metric": "revenue", "start": "2026-08-27", "end": "2026-09-06",
                                       "as_of": "2026-09-18", "preset": "custom"}
    # a share that never moved is one figure, not a band, and its unit is kept beside the claim
    share = C.get(by["done_share"]["expected"]["claim_id"])
    assert by["done_share"]["expected"]["low"] == by["done_share"]["expected"]["high"] == 50.0
    assert share.statement.unit == "" and share.extra["metric_unit"] == "%"

    @contextlib.contextmanager
    def never():
        raise AssertionError("a prediction already on record is read back, never measured again")
        yield  # pragma: no cover

    again = expected.expected_next("c1", spec, profile=_profile(), runner=never, today=SEP26)
    assert {i["metric"]: i["expected"]["claim_id"] for i in again["items"]} == {
        "revenue": rev["claim_id"], "done_share": by["done_share"]["expected"]["claim_id"]}
    mine = [c for c in C.list_claims(kind="prediction", conn_id="c1", limit=200) if c.statement.range_end == "2026-09-05"]
    assert len(mine) == 2                                                 # booked once each, not once per read


def test_a_metric_that_cannot_be_read_is_not_predicted_and_says_why_and_a_range_to_date_is_never(con, approved):
    from aughor.briefing import expected
    from aughor.record import claims as C

    @contextlib.contextmanager
    def broken():
        def run_sql(sql):
            return [], [], "Binder Error: no such column"
        yield run_sql, "duckdb"

    spec, _ = ranges.resolve_range("last_week", today=SEP26, lag_days=13)
    before = len(C.list_claims(kind="prediction", conn_id="c1", limit=500))
    seen = expected.expected_next("c1", spec, runner=broken, today=SEP26)
    [item] = seen["items"]
    assert item["expected"] is None and item["why"].startswith("its query failed: Binder Error")
    assert len(C.list_claims(kind="prediction", conn_id="c1", limit=500)) == before        # nothing booked

    to_date, _ = ranges.resolve_range("month_to_date", today=SEP26, lag_days=13)
    nothing = expected.expected_next("c1", to_date, runner=_runner(con), today=SEP26)
    assert nothing["target"] is None and nothing["items"] == [] and "to date is not predicted" in nothing["why"]


def test_a_briefings_prediction_is_scored_by_measuring_its_range_once_it_has_settled(con, approved):
    from datetime import datetime, timezone

    from aughor.briefing import expected
    from aughor.record import claims as C
    _share_metric()
    # its own range, so nothing another test booked is in the way: 10..19 August, then 20..29
    spec, _ = ranges.resolve_range(start=date(2026, 8, 10), end=date(2026, 8, 19), today=SEP26, lag_days=13)
    seen = expected.expected_next("c1", spec, profile=_profile(), runner=_runner(con), today=SEP26)
    assert seen["target"]["settles_on"] == "2026-09-11"
    ids = {i["metric"]: i["expected"]["claim_id"] for i in seen["items"]}
    runner_for = lambda conn: _runner(con)()                                              # noqa: E731
    mine = lambda out: [c for c in out if c in {C.latest(C.get(i).key).id for i in ids.values()}]   # noqa: E731

    expected.score_due(runner_for=runner_for, now=datetime(2026, 9, 10, tzinfo=timezone.utc))
    assert C.latest(C.get(ids["revenue"]).key).state == "open"                            # not settled yet

    scored = expected.score_due(runner_for=runner_for, now=datetime(2026, 9, 11, 6, tzinfo=timezone.utc))
    assert len(mine(scored)) == 2
    revenue = C.latest(C.get(ids["revenue"]).key)
    assert revenue.state == "scored" and revenue.extra["actual"] == 245000.0              # 20..29, 1,000 a day of the month
    assert revenue.extra["scored_against"] in ("inside", "above", "below")
    assert revenue.extra["score_note"] == "measured for 2026-08-20 to 2026-08-29"
    share = C.latest(C.get(ids["done_share"]).key)
    assert share.extra["actual"] == 50.0 and share.extra["scored_against"] == "inside"     # never "cannot_tell"
    again = expected.score_due(runner_for=runner_for, now=datetime(2026, 9, 12, tzinfo=timezone.utc))
    assert mine(again) == []                                                              # scored once


def test_a_count_over_a_window_with_no_rows_is_not_a_reading(con, approved):
    """Found on the scratch install, 2026-10-05: COUNT answers 0 for the months before the data began,
    and three such zeros put "0 to 961" on a metric that had read 800 every month it existed."""
    from aughor.briefing import expected
    from aughor.semantic.metrics import MetricDefinition, save_metric
    save_metric(MetricDefinition(name="orders_placed", connection="c1", label="Orders placed", sql="COUNT(*)",
                                 tables=["orders"], status="approved", approved_by="test"))
    # the data begins 2025-01-01: of the eight weeks ending 14 January 2025, six hold no row at all
    spec, _ = ranges.resolve_range(start=date(2025, 1, 8), end=date(2025, 1, 14), today=SEP26, lag_days=13)
    seen = ranges.metric_trend("c1", spec, "orders_placed", runner=_runner(con))
    assert [p["value"] for p in seen["series"]] == [None] * 6 + [14.0, 14.0]
    assert [p["value_text"] for p in seen["series"]][:6] == [None] * 6
    band = {i["metric"]: i for i in expected.expected_next("c1", spec, runner=_runner(con), today=SEP26)["items"]}
    assert band["orders_placed"]["expected"] is None
    assert band["orders_placed"]["why"].startswith("only 2 earlier ranges held a reading")


# ── the Cockpit's periods: current and last, read to where the data ends (2026-10-08) ───────

OCT8 = date(2026, 10, 8)                     # a Thursday
LOADING = {"through": OCT8, "held_by": ["orders"], "tables": {"orders": OCT8}}


def _edge(preset, today=OCT8, edge=LOADING, **kw):
    spec, why = ranges.resolve_range(preset, today=today, edge=edge, **kw)
    assert spec is not None, why
    return spec


def test_a_current_day_is_the_newest_complete_day_and_today_still_loading_is_left_out():
    """The user: most warehouses hold yesterday at best, and a current day read off the calendar is
    empty. A day still loading is part of a day, and a part against a whole is no comparison."""
    day = _edge("current_day")
    assert (day.start, day.last_day, day.previous_start) == (date(2026, 10, 7), date(2026, 10, 7), date(2026, 9, 30))
    assert day.edge_note.startswith("Today (2026-10-08) is still loading, so it is left out")
    behind = _edge("current_day", edge={"through": date(2026, 10, 7)})
    assert behind.last_day == date(2026, 10, 7)
    assert behind.edge_note == "Data runs to 2026-10-07: today (2026-10-08) has no rows yet."


def test_a_period_so_far_is_compared_with_the_same_days_of_the_one_before():
    week = _edge("current_week")
    assert (week.start, week.last_day) == (date(2026, 10, 5), date(2026, 10, 7)) and week.under_way
    assert (week.previous_start, week.previous_end) == (date(2026, 9, 28), date(2026, 10, 1))
    assert ranges.phrases(week)["compared_with"] == "the same days of the week before, 2026-09-28 to 2026-09-30"
    month = _edge("current_month")
    assert (month.start, month.last_day, month.previous_start, month.previous_end) == (
        date(2026, 10, 1), date(2026, 10, 7), date(2026, 9, 1), date(2026, 9, 8))
    assert ranges.phrases(month)["covers"] == "October 2026 so far, 2026-10-01 to 2026-10-07"
    year = _edge("current_year")
    assert (year.start, year.previous_start, year.last_year_start) == (date(2026, 1, 1), date(2025, 1, 1), None)
    # its trend reads the same days of each month before; there is no "next" of a period so far
    assert ranges.earlier_ranges(month, 3) == [(date(2026, 8, 1), date(2026, 8, 8)),
                                               (date(2026, 9, 1), date(2026, 9, 8)),
                                               (date(2026, 10, 1), date(2026, 10, 8))]
    assert ranges.later_spec(month) is None
    from aughor.cockpit.host import TO_DATE, status_of
    assert status_of(month) == TO_DATE


def test_a_last_period_is_the_calendar_one_before_the_one_under_way():
    week, month, year = _edge("previous_week"), _edge("previous_month"), _edge("previous_year")
    assert (week.start, week.last_day, week.previous_start) == (date(2026, 9, 28), date(2026, 10, 4), date(2026, 9, 21))
    assert (month.start, month.end, month.previous_start) == (date(2026, 9, 1), date(2026, 10, 1), date(2026, 8, 1))
    assert ranges.phrases(month)["covers"] == "September 2026" and not month.under_way
    assert month.edge_note == ""                         # a whole month the data's edge left alone
    behind = _edge("previous_week", edge={"through": date(2026, 10, 2)})
    assert behind.last_day == date(2026, 10, 2) and behind.edge_note.startswith("Data runs to 2026-10-02")
    assert (year.start, year.end) == (date(2025, 1, 1), date(2026, 1, 1))
    nxt = ranges.later_spec(month)
    assert (nxt.start, nxt.end) == (date(2026, 10, 1), date(2026, 11, 1))


def test_a_current_period_with_no_data_yet_reads_the_newest_that_has_and_says_so():
    monday = date(2026, 10, 12)
    week = _edge("current_week", today=monday, edge={"through": date(2026, 10, 11)})
    assert (week.start, week.last_day, week.under_way) == (date(2026, 10, 5), date(2026, 10, 11), False)
    assert week.edge_note.startswith("The week of 2026-10-12 has no complete day yet, so this is the newest that has.")


def test_the_table_that_holds_the_data_back_is_named():
    held = {"through": date(2026, 10, 5), "held_by": ["returns"],
            "tables": {"returns": date(2026, 10, 5), "orders": date(2026, 10, 7)}}
    week = _edge("current_week", edge=held)
    assert (week.start, week.last_day) == (date(2026, 10, 5), date(2026, 10, 5))
    assert "returns has no rows after 2026-10-05; orders runs later." in week.edge_note


def test_a_custom_range_past_the_data_is_cut_and_says_so_and_without_an_edge_reads_as_asked():
    cut = _edge("custom", start=date(2026, 10, 1), end=OCT8)
    assert (cut.last_day, cut.previous_start) == (date(2026, 10, 7), date(2026, 9, 24))
    assert cut.edge_note.startswith("Asked to 2026-10-08, read to 2026-10-07.")
    asked, _ = ranges.resolve_range("custom", start=date(2026, 10, 1), end=OCT8, today=OCT8)
    assert (asked.last_day, asked.previous_start, asked.edge_note) == (OCT8, date(2026, 9, 23), "")


def test_a_metric_whose_data_stopped_reads_the_same_kind_of_period_at_its_end():
    moved = ranges.anchored_spec(_edge("current_month"), date(2024, 6, 15))
    assert (moved.start, moved.last_day, moved.preset, moved.as_of) == (
        date(2024, 6, 1), date(2024, 6, 15), "current_month", OCT8)


def _dated(name, table, kind="flow"):
    from types import SimpleNamespace as N
    return N(name=name, label=name, time_kind=kind, time_column=f"{table}.created_at", until_column="x",
             sql="COUNT(*)", tables=[table])


def test_where_the_data_ends_is_the_earliest_live_table_read_once_each(monkeypatch):
    ranges._EDGE_CACHE.clear()
    c = duckdb.connect()
    for table, last in (("orders", "2026-10-07"), ("returns", "2026-10-05"), ("legacy", "2024-03-01"),
                        ("stock", "2026-10-01")):
        c.execute(f"CREATE TABLE {table} AS SELECT TIMESTAMP '{last} 09:00' AS created_at")
    metrics = [_dated("revenue", "orders"), _dated("aov", "orders"), _dated("returns", "returns"),
               _dated("old", "legacy"), _dated("inventory", "stock", kind="stock")]
    monkeypatch.setattr(ranges, "governed_metrics", lambda conn_id, schema=None: metrics)
    seen: list[str] = []
    base = _runner(c)

    @contextlib.contextmanager
    def counting():
        with base() as (run_sql, d):
            yield (lambda sql: (seen.append(sql), run_sql(sql))[1]), d
    edge = ranges.data_edge("c1", today=OCT8, runner=counting)
    # the table that stopped in 2024 is not holding today back, and a level does not count
    assert edge == {"through": date(2026, 10, 5), "held_by": ["returns"], "why": "",
                    "tables": {"orders": date(2026, 10, 7), "returns": date(2026, 10, 5)}}
    assert len(seen) == 3                                       # orders once, though two metrics read it
    # read again inside ten minutes, it is not read again
    assert ranges.data_edge("c1", today=OCT8, runner=counting) == edge and len(seen) == 3
    c.close()


def test_where_the_data_ends_says_why_when_it_cannot_be_read(monkeypatch):
    ranges._EDGE_CACHE.clear()
    monkeypatch.setattr(ranges, "governed_metrics", lambda conn_id, schema=None: [])
    assert ranges.data_edge("c1", today=OCT8)["why"] == "no approved metric names a date"

    @contextlib.contextmanager
    def closed():
        raise ConnectionError("down")
        yield  # pragma: no cover
    monkeypatch.setattr(ranges, "governed_metrics", lambda conn_id, schema=None: [_dated("revenue", "orders")])
    unread = ranges.data_edge("c1", today=OCT8, runner=closed)
    assert unread["through"] is None and "could not be opened" in unread["why"]
    # unread, a current day reads yesterday and says it did not know
    day = _edge("current_day", edge=unread)
    assert day.last_day == date(2026, 10, 7) and day.edge_note.startswith("Whether data has arrived after 2026-10-07 was not read")


def test_only_the_current_and_last_periods_and_recent_custom_ranges_read_the_edge(monkeypatch):
    asked: list[str] = []
    monkeypatch.setattr(ranges, "data_edge", lambda conn_id, schema=None, today=None: asked.append(conn_id) or LOADING)
    ranges.resolve_for("c1", "last_month", today=OCT8)
    ranges.resolve_for("c1", "custom", start=date(2025, 1, 1), end=date(2025, 1, 31), today=OCT8)
    assert asked == []
    spec, _ = ranges.resolve_for("c1", "current_day", today=OCT8)
    assert asked == ["c1"] and spec.last_day == date(2026, 10, 7)


def test_a_flows_earlier_ranges_are_not_said_to_be_read_at_one_age(con, approved):
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    seen = ranges.metric_trend("c1", spec, "revenue", profile=_profile(), runner=_runner(con))
    assert seen["same_age"] is False and seen["lag_days"] == 13
    # the source settles 13 days back (by 13 September), so every range up to 26 August has settled
    assert [p["settling"] for p in seen["series"]] == [False] * 7 + [False]
    young, _ = ranges.resolve_range(start=date(2026, 9, 14), end=date(2026, 9, 24), today=SEP26, lag_days=13)
    assert [p["settling"] for p in ranges.metric_trend("c1", young, "revenue", runner=_runner(con))["series"]][-2:] == [False, True]


def test_a_north_star_whose_definition_was_deprecated_is_not_asked_for_again(con, approved):
    """theLook's profile names Item Return Rate, deprecated as a second name for Return rate: "approve
    one" would ask for the duplicate back (2026-10-08)."""
    from aughor.business_profile.models import NorthStarMetric
    from aughor.semantic.metrics import get_metric, save_metric
    aov = get_metric("aov", connection_id="c1")
    save_metric(aov.model_copy(update={"status": "deprecated"}))
    stars = [NorthStarMetric(name=n, definition="-", maps_to="orders", why_it_matters="-", unit_or_range="$",
                             chart_sql="") for n in ("AOV", "Gross margin")]
    spec, _ = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26, lag_days=13)
    with _runner(con)() as (run_sql, dialect):
        got = ranges.measure_range("c1", spec, run_sql=run_sql, dialect=dialect, north_stars=stars)
    why = {u["name"]: u["reason"] for u in got["unmeasured"]}
    assert why["AOV"] == "its definition was deprecated, so it is not measured under this name"
    assert why["Gross margin"].startswith("no approved definition")
