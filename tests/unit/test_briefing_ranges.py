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


def test_the_users_range_is_compared_with_the_same_weekdays():
    """17–26 August 2026 (Monday to Wednesday), asked on 26 September."""
    spec, why = ranges.resolve_range(start=date(2026, 8, 17), end=date(2026, 8, 26), today=SEP26,
                                     lag_days=13)
    assert why == "" and spec.days == 10 and spec.key == "range:custom:2026-08-17..2026-08-26"
    assert (spec.previous_start, spec.previous_end) == (date(2026, 8, 3), date(2026, 8, 13))
    assert (spec.last_year_start, spec.last_year_end) == (date(2025, 8, 18), date(2025, 8, 28))
    assert spec.previous_start.weekday() == spec.start.weekday() == spec.last_year_start.weekday()
    words = ranges.phrases(spec)
    assert words["covers"] == "2026-08-17 to 2026-08-26 (10 days)"
    assert words["compared_with"] == "the same 10 days 2 weeks earlier, 2026-08-03 to 2026-08-12"
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
    assert (rev["name"], rev["current"], rev["previous"]) == ("Revenue", 215000.0, 75000.0)  # 17..26, 3..12 ×1,000
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
