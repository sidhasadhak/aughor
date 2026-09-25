"""Briefings by period (IDEAS.md 3, PENDING.md item 7, ROADMAP §3.27).

What these hold, each measured against the gap it closes:

* the window is computed, complete and settled — and the monthly rule it shares with the
  scheduled-run note no longer skips the month that just ended;
* each headline metric is MEASURED for the window: its trend query cut to the period gives
  the numbers a hand-written query gives, a rate is recomputed (never averaged), and a query
  that cannot be cut says why instead of vanishing;
* the brief is built from the period's evidence only, the narrator is told which version it
  writes, and yesterday's daily brief is never served as today's;
* off by default, and byte-identical when off — the standing brief, the alert summary and every
  stored subscription;
* a scheduled period briefing re-measures its numbers at the send and holds a line whose
  number moved since the brief was written.
"""
from __future__ import annotations

import contextlib
from datetime import date, datetime, timezone

import duckdb
import pytest

import aughor.llm.provider as prov
from aughor.automations.temporal import complete_period, observation_note
from aughor.business_profile.models import BusinessProfile, NorthStarMetric
from aughor.knowledge import briefing as briefing_mod
from aughor.knowledge import period_brief
from aughor.knowledge.briefing import BriefingCitation, BriefingNarrative, _SYSTEM
from aughor.sql.trend_window import period_split

TODAY = date(2026, 9, 23)          # a Wednesday; with the one-day lag the anchor is Tue 22 Sep
FLAG_ENV = "AUGHOR_BRIEFING_BY_PERIOD"

REVENUE_TREND = ("SELECT date_trunc('month', created_at) AS month, SUM(amount) AS revenue "
                 "FROM orders WHERE status = 'done' GROUP BY 1 ORDER BY 1 LIMIT 12")
AOV_TREND = ("SELECT date_trunc('week', o.created_at) AS week, SUM(o.amount) / COUNT(*) AS aov "
             "FROM orders o WHERE o.status = 'done' GROUP BY week ORDER BY week")
TOP_STATUSES = "SELECT status, SUM(amount) FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 5"


# ── fixtures ────────────────────────────────────────────────────────────────────────────────

def _orders(con) -> None:
    """One 'done' order a day, worth a thousand times its day of the month, 2025-01-01 →
    2026-09-22 — so any window's revenue is a sum a reader can do by hand (14..20 Sep =
    119,000). Thousands, because law 1 grounds magnitudes of 1,000 and up; small counts are
    exempt by the platform's standing policy (`explorer/grounding.py`)."""
    con.execute("DROP TABLE IF EXISTS orders")
    con.execute("""CREATE TABLE orders AS
        SELECT d::TIMESTAMP + INTERVAL 9 HOUR AS created_at,
               CAST(day(d) AS DOUBLE) * 1000 AS amount, 'done' AS status
        FROM range(DATE '2025-01-01', DATE '2026-09-23', INTERVAL 1 DAY) t(d)""")


@pytest.fixture
def con():
    c = duckdb.connect()
    _orders(c)
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


def _metric(name, chart_sql, unit="USD"):
    return NorthStarMetric(name=name, definition=name, maps_to="orders", why_it_matters="-",
                           unit_or_range=unit, chart_sql=chart_sql)


def _profile(*metrics):
    return BusinessProfile(industry="Retail", business_model="transactional-retail",
                           summary="A shop.", north_star_metrics=list(metrics), key_questions=[],
                           confidence=0.9, evidence="test fixture",
                           currency_code="USD")


class FakeNarrator:
    def __init__(self, narrative="Revenue rose to $119 this week [1]."):
        self.narrative = narrative
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls.append((system, user))
        return BriefingNarrative(narrative=self.narrative, headline_theme="Theme",
                                 citations=[BriefingCitation(ref="1", insight_id="x",
                                                             domain="Key Metrics", finding="f")])


@pytest.fixture
def narrator(monkeypatch, tmp_path):
    fake = FakeNarrator()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fake)
    # each test its own brief cache
    from aughor.util.json_store import KeyedJsonStore
    store = KeyedJsonStore(tmp_path / "briefing_cache.json")
    monkeypatch.setattr(briefing_mod, "_store", lambda: store)
    return fake


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "1")


# ── the window ──────────────────────────────────────────────────────────────────────────────

def test_each_period_is_the_last_complete_one_before_the_settled_anchor():
    day = complete_period("day", TODAY)
    assert (day.start, day.end) == (date(2026, 9, 22), date(2026, 9, 23))
    # a day against the same weekday a week earlier, not against Monday
    assert (day.previous_start, day.previous_end) == (date(2026, 9, 15), date(2026, 9, 16))
    week = complete_period("week", TODAY)
    assert (week.start, week.last_day) == (date(2026, 9, 14), date(2026, 9, 20))
    assert (week.previous_start, week.previous_end) == (date(2026, 9, 7), date(2026, 9, 14))
    month = complete_period("month", TODAY)
    assert (month.start, month.end, month.previous_start) == (
        date(2026, 8, 1), date(2026, 9, 1), date(2026, 7, 1))
    year = complete_period("year", TODAY)
    assert (year.start, year.end, year.previous_start) == (
        date(2025, 1, 1), date(2026, 1, 1), date(2024, 1, 1))


def test_a_week_ending_on_the_anchor_is_complete_and_a_learned_lag_moves_every_window():
    # Mon 21 Sep with lag 1 → anchor Sun 20 Sep: that week is complete
    assert complete_period("week", date(2026, 9, 21)).start == date(2026, 9, 14)
    # an 8-day lag (theLook's) anchors on 15 Sep, so the complete week is 7..13 Sep
    lagged = complete_period("week", TODAY, lag_days=8)
    assert (lagged.start, lagged.lag_days) == (date(2026, 9, 7), 8)


def test_the_fiscal_year_is_the_year_when_org_settings_say_so():
    fy = complete_period("year", TODAY, fiscal_start_month=4)
    assert (fy.start, fy.end) == (date(2025, 4, 1), date(2026, 4, 1))
    assert "fiscal year 2025-04-01 to 2026-03-31" in period_brief.phrases(fy)[0]


def test_a_monthly_run_on_the_first_observes_the_month_that_just_ended():
    """The rule this replaced told a monthly automation firing on 1 October to observe
    August (measured 2026-09-23). September is complete on 1 October."""
    note = observation_note(datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc), "0 8 1 * *", 1)
    assert "COMPLETE month: 2026-09" in note
    weekly = observation_note(datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc), "0 8 * * 1", 1)
    assert "COMPLETE week: 2026-09-14 to 2026-09-20" in weekly


# ── measuring a period ──────────────────────────────────────────────────────────────────────

def _split(sql):
    w = complete_period("week", TODAY)
    return period_split(sql, start=w.start, end=w.end, previous_start=w.previous_start,
                        previous_end=w.previous_end)


def test_a_monthly_trend_cut_to_a_week_gives_the_hand_written_week(con):
    sql, why = _split(REVENUE_TREND)
    assert why == "" and sql
    got = {r[0]: r[1] for r in con.execute(sql).fetchall()}
    assert got == {"current": 119000.0, "previous": 70000.0}  # (14+..+20, 7+..+13) × 1000


def test_a_rate_is_recomputed_over_the_window_not_averaged_across_buckets(con):
    sql, _ = _split(AOV_TREND)
    got = {r[0]: r[1] for r in con.execute(sql).fetchall()}
    assert got == {"current": 17000.0, "previous": 10000.0}


def test_the_trend_inside_the_recent_window_wrapper_is_the_one_cut(con):
    """The profile store wraps every LIMITed chart in `recent_window`; the first real run
    refused GMV because the wrapper has no GROUP BY (2026-09-23)."""
    from aughor.sql.trend_window import recent_window
    wrapped = recent_window(REVENUE_TREND)
    assert "_recent" in wrapped
    sql, why = _split(wrapped)
    assert why == "" and {r[0]: r[1] for r in con.execute(sql).fetchall()} == {
        "current": 119000.0, "previous": 70000.0}


def test_a_comparison_the_data_only_partly_covers_states_no_change(con):
    """Data from 2025-01-01 only: the year 2025 against 2024 would read as a vast rise that
    is really the data's first day. The comparison's coverage is said instead."""
    year = complete_period("year", TODAY)
    with _runner(con)() as (run_sql, dialect):
        con.execute("DELETE FROM orders WHERE created_at < TIMESTAMP '2025-03-01'")
        con.execute("INSERT INTO orders VALUES (TIMESTAMP '2024-11-05 09:00', 5000.0, 'done')")
        measured, _ = period_brief.measure_period([_metric("Revenue", REVENUE_TREND)], run_sql, year, dialect)
    m = measured[0]
    assert m["rel"] is None and m["previous_partial"] == "2024-11-05 to 2024-11-05"
    assert m["current_partial"] == "2025-03-01 to 2025-12-31"
    line = period_brief.metric_line(m, period_brief.window_block(year, "default"), "USD")
    assert "the data covers only 2025-03-01 to 2025-12-31 of the year 2025, so no change is stated" in line


@pytest.mark.parametrize("sql, reason", [
    (TOP_STATUSES, "not a date"),
    # theLook's sell-through chart, 2026-09-25: an alias is not a date
    ("SELECT status AS bucket, SUM(amount) FROM orders GROUP BY status", "not a date"),
    ("SELECT date_trunc('day', created_at) d, SUM(SUM(amount)) OVER (ORDER BY 1) FROM orders "
     "GROUP BY 1", "window function"),
    ("WITH m AS (SELECT date_trunc('month', created_at) AS month, amount FROM orders) "
     "SELECT month, SUM(amount) FROM m GROUP BY 1", "sub-query"),
    ("SELECT date_trunc('week', created_at) w, status, SUM(amount) FROM orders GROUP BY 1, 2",
     "time alone"),
    ("", "no trend query"),
])
def test_a_query_that_cannot_be_cut_says_why(sql, reason):
    out, why = _split(sql)
    assert out is None and reason in why


def test_measure_period_puts_every_metric_in_exactly_one_list(con):
    w = complete_period("week", TODAY)
    metrics = [_metric("Revenue", REVENUE_TREND), _metric("Top statuses", TOP_STATUSES),
               _metric("Empty", "")]
    with _runner(con)() as (run_sql, dialect):
        measured, unmeasured = period_brief.measure_period(metrics, run_sql, w, dialect)
    assert [(m["name"], m["current"], m["previous"]) for m in measured] == [("Revenue", 119000.0, 70000.0)]
    assert {u["name"] for u in unmeasured} == {"Top statuses", "Empty"}


def test_a_period_with_no_rows_is_unmeasured_not_zero(con):
    con.execute("DELETE FROM orders WHERE created_at >= TIMESTAMP '2026-09-14'")
    w = complete_period("week", TODAY)
    with _runner(con)() as (run_sql, dialect):
        measured, unmeasured = period_brief.measure_period([_metric("Revenue", REVENUE_TREND)],
                                                           run_sql, w, dialect)
    assert measured == [] and unmeasured[0]["reason"] == "its data has no rows in this period"


def test_a_period_move_is_phrased_the_way_the_triage_reads_a_change():
    from aughor.knowledge.triage import extract_change
    block = period_brief.window_block(complete_period("week", TODAY), "default")
    line = period_brief.metric_line({"name": "Revenue", "unit": "USD", "current": 119.0,
                                     "previous": 70.0, "rel": 49 / 70}, block, "USD")
    assert line.startswith("Revenue moved from $70") and "(+70%)" in line
    assert "the week 2026-09-14 to 2026-09-20" in line
    change = extract_change(line)
    assert change and round(change.rel, 2) == round(49 / 119, 2)
    steady = period_brief.metric_line({"name": "Revenue", "unit": "USD", "current": 100.5,
                                       "previous": 100.0, "rel": 0.005}, block, "USD")
    assert "held steady" in steady


# ── the brief ───────────────────────────────────────────────────────────────────────────────

def _stored(recorded_at: str, text: str, fid: str) -> dict:
    return {"id": fid, "finding": text, "generated_at": recorded_at, "confidence": 0.8,
            "novelty": 3, "sql": ""}


def test_the_weekly_brief_is_built_from_the_weeks_evidence_and_told_its_version(con, narrator):
    domain_data = {"Sales": [
        _stored("2026-06-02T10:00:00Z", "Premium share has grown from 20% to 31% since 2024.", "old"),
        _stored("2026-09-16T10:00:00Z", "Refunds on the Lisbon warehouse rose from 3% to 9%.", "new"),
    ]}
    brief = period_brief.build_period_briefing(
        "c1", "week", scope_key="c1", domain_data=domain_data,
        profile=_profile(_metric("Revenue", REVENUE_TREND), _metric("Top statuses", TOP_STATUSES)),
        runner=_runner(con), today=TODAY)
    system, user = narrator.calls[-1]
    assert "weekly executive briefing" in system and system != _SYSTEM
    assert "This is the WEEKLY briefing. It covers the week 2026-09-14 to 2026-09-20" in user
    assert "Refunds on the Lisbon warehouse" in user            # recorded inside the week
    assert "Premium share" not in user                         # a standing finding is not news
    assert "Revenue moved from $70,000 to $119,000 (+70%)" in user     # measured for the week
    assert "Not measured for this week: Top statuses" in user
    block = brief["period"]
    assert (block["start"], block["last_day"], block["label"]) == ("2026-09-14", "2026-09-20", "Weekly")
    assert [m["name"] for m in block["measured"]] == ["Revenue"]
    assert block["unmeasured"][0]["reason"] == "its first column is not a date"


def test_a_brief_is_served_from_cache_only_while_its_window_is_the_same_one(con, narrator):
    args = dict(scope_key="c1", domain_data={}, profile=_profile(_metric("Revenue", REVENUE_TREND)),
                runner=_runner(con))
    first = period_brief.build_period_briefing("c1", "day", today=TODAY, **args)
    again = period_brief.build_period_briefing("c1", "day", today=TODAY, **args)
    assert len(narrator.calls) == 1 and again["period"] == first["period"]
    # the next day is a new window: rebuilt, never served from yesterday's entry — and since
    # the fixture has no orders on 23 Sep, it says so instead of writing about nothing
    nextday = period_brief.build_period_briefing("c1", "day", today=date(2026, 9, 24), **args)
    assert nextday["period"]["start"] == "2026-09-23" and nextday["narrative"] == ""
    assert nextday["period"]["unmeasured"] == [
        {"name": "Revenue", "reason": "its data has no rows in this period"}]
    assert len(narrator.calls) == 1                     # no narrator call for an empty period
    # the standing brief lives under its own key and is untouched by either
    assert briefing_mod._store().get("c1") is None


def test_deleting_a_connection_or_schema_drops_its_period_briefs_too(narrator):
    """A period brief is keyed `<scope>#<period>`; the delete cascade matched only `<conn>` and
    `<conn>:<schema>`, so a deleted connection's weekly brief would have survived it."""
    store = briefing_mod._store()
    for key in ("c1", "c1#week", "c1:s1", "c1:s1#day", "c1:s2#month", "c2#week"):
        store.put(key, {"narrative": key})
    assert briefing_mod.invalidate("c1", "s1") == 4          # s1's two, and the aggregate's two
    assert {k for k in store.load()} == {"c1:s2#month", "c2#week"}
    assert briefing_mod.invalidate("c1") == 1
    assert {k for k in store.load()} == {"c2#week"}


@pytest.mark.parametrize("source, moving, said", [
    ("learned", [], "the platform measured a 8-day settling lag"),
    # theLook 2026-09-25: a table still moving at the horizon is named, and nothing is final
    ("beyond_horizon", ["order_items"], "order_items was still changing 7 days after a day ended"),
])
def test_a_lag_longer_than_a_day_is_said_in_the_prompt(con, narrator, monkeypatch, source, moving, said):
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "connection_lag", lambda conn_id: {
        "days": 8, "source": source, "still_moving": moving, "horizon": 7})
    brief = period_brief.build_period_briefing(
        "c1", "week", scope_key="c1", domain_data={},
        profile=_profile(_metric("Revenue", REVENUE_TREND)), runner=_runner(con), today=TODAY)
    assert brief["period"]["lag_source"] == source and brief["period"]["start"] == "2026-09-07"
    assert brief["period"]["still_moving"] == moving
    assert said in narrator.calls[-1][1]


# ── on by default (the user's call, 2026-09-24), byte-identical when switched off ──────────

def test_on_by_default_and_off_the_refusal_says_why(monkeypatch):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert period_brief.enabled() is True
    monkeypatch.setenv(FLAG_ENV, "0")
    assert period_brief.enabled() is False
    assert "needs the 'briefing.by_period' flag" in period_brief.refusal("week")
    assert "period must be one of" in period_brief.refusal("fortnight")


def test_the_route_refuses_a_period_brief_while_off(monkeypatch):
    from fastapi import HTTPException

    from aughor.routers import exploration
    monkeypatch.setenv(FLAG_ENV, "0")
    with pytest.raises(HTTPException) as off:
        exploration._period_briefing("c1", "week", schema=None, requested_schema=None,
                                     refresh=False, workspace_id=None, by_domain={})
    assert off.value.status_code == 404 and "briefing.by_period" in off.value.detail
    monkeypatch.setenv(FLAG_ENV, "1")
    with pytest.raises(HTTPException) as bad:
        exploration._period_briefing("c1", "fortnight", schema=None, requested_schema=None,
                                     refresh=False, workspace_id=None, by_domain={})
    assert bad.value.status_code == 422


def test_the_standing_brief_prompt_and_cache_key_are_unchanged(narrator):
    briefing_mod.get_briefing("c1", {"Sales": [_stored("2026-06-02T10:00:00Z",
                                                       "Premium share grew from 20% to 31%.", "a")]},
                              patterns=[])
    system, user = narrator.calls[-1]
    assert system == _SYSTEM and "[Briefing period" not in user
    stored = briefing_mod._store().get("c1")
    assert stored and "period" not in stored


def test_an_alert_summary_subscription_is_stored_exactly_as_before():
    from aughor.briefing.models import BriefSubscription
    row = BriefSubscription(conn_id="c1", name="n", trigger_id="t").to_dict()
    assert "content" not in row
    assert BriefSubscription(conn_id="c1", name="n", trigger_id="t",
                             content="briefing").to_dict()["content"] == "briefing"


def test_subscription_periods_and_contents(monkeypatch):
    from fastapi import HTTPException

    from aughor.routers.briefs import _validate_period
    monkeypatch.setenv(FLAG_ENV, "0")
    _validate_period("day")
    _validate_period("week")
    for period, content in (("month", "alert_summary"), ("week", "briefing")):
        with pytest.raises(HTTPException) as off:
            _validate_period(period, content)
        assert off.value.status_code == 422
    with pytest.raises(HTTPException) as off:
        _validate_period("month")
    assert off.value.detail == "period must be 'week' or 'day'"        # unchanged while off
    monkeypatch.setenv(FLAG_ENV, "1")
    _validate_period("month", "briefing")
    _validate_period("year", "briefing")
    with pytest.raises(HTTPException) as refused:
        _validate_period("month", "alert_summary")
    assert "there is no monthly alert summary" in refused.value.detail


def test_the_daily_alert_summary_is_headed_daily():
    from aughor.briefing.delivery import brief_summary
    from aughor.briefing.models import BriefSubscription
    from aughor.monitors.alert_summary import AlertSummary
    summary = AlertSummary(conn_id="c1", period="day", generated_at="2026-09-23T08:00:00Z",
                          sections=[], alert_count=0, critical_count=0)
    assert summary.to_markdown().startswith("# Aughor Intelligence Digest — Daily")
    sub = BriefSubscription(conn_id="c1", name="n", trigger_id="t", period="day")
    assert brief_summary(sub, summary).startswith("Daily Intelligence Brief")


# ── the send ────────────────────────────────────────────────────────────────────────────────

def test_a_scheduled_period_brief_remeasures_at_the_send(con, narrator, flag_on, monkeypatch):
    """Built from the week's numbers; then late rows land before the send. The headline line
    still states the old number, so law 1 — re-run at departure — holds it."""
    from aughor.briefing import delivery
    from aughor.briefing.models import BriefSubscription
    from aughor.knowledge import period_brief as pb

    narrator.narrative = ("Order volume rose from 70,000 to 119,000 in the week [1].\n\n"
                          "Revenue reached $4,000 [1].")
    profile = _profile(_metric("Order volume", REVENUE_TREND, unit="orders"))
    monkeypatch.setattr(pb, "connection_inputs", lambda conn_id: ({}, profile))
    real_build = pb.build_period_briefing
    monkeypatch.setattr(pb, "build_period_briefing",
                        lambda *a, **k: real_build(*a, **{**k, "today": TODAY}))
    sub = BriefSubscription(id="s1", conn_id="c1", name="weekly", trigger_id="t",
                            period="week", content="briefing")

    sent = delivery.build_period_departure(sub, runner=_runner(con))
    # the grounded paragraph leaves; the one naming a KPI no approved metric defines, with a
    # number the period never measured, is cut at the gate — and the brief says a line was
    assert len(sent["held_lines"]) == 1 and "Revenue reached" in sent["held_lines"][0]
    assert "Order volume rose from 70,000 to 119,000 in the week [1]." in sent["markdown"]
    assert "## Headline metrics" in sent["markdown"]
    assert "Order volume moved from 70,000 to 119,000 (+70%)" in sent["markdown"]
    assert sent["summary"].startswith("Weekly Briefing — the week 2026-09-14 to 2026-09-20")

    con.execute("INSERT INTO orders VALUES (TIMESTAMP '2026-09-18 12:00', 500000.0, 'done')")
    late = delivery.build_period_departure(sub, runner=_runner(con))    # the brief is cached
    assert any("Order volume moved from 70,000 to 119,000" in h and "not in" in h
               for h in late["held_lines"]), late["held_lines"]
    assert "## Headline metrics" not in late["markdown"]
    assert "Order volume rose from 70,000 to 119,000" not in late["markdown"]   # stale narrative too
    assert "3 lines of this briefing did not leave the platform" in late["markdown"]


def test_a_briefing_subscription_is_not_sent_while_off(monkeypatch):
    from aughor.briefing import delivery
    from aughor.briefing.models import BriefSubscription
    monkeypatch.setenv(FLAG_ENV, "0")
    result: dict = {}
    delivery._deliver_period(BriefSubscription(conn_id="c1", name="n", trigger_id="t",
                                               period="week", content="briefing"), object(), result)
    assert result["error"].startswith("not sent — briefings by period are off")


def test_a_briefing_subscription_can_be_paused_after_the_flag_is_turned_off(monkeypatch):
    """Branch review, 2026-09-24: pause re-sends period and content, and a period/content the
    install no longer offers was refused — so a saved briefing subscription could not be paused."""
    from aughor.briefing.models import BriefSubscription
    from aughor.briefing.store import save_subscription
    from aughor.routers.briefs import _SubscriptionBody, update_briefing_subscription
    import aughor.notifications.store as triggers
    monkeypatch.setattr(triggers, "get_trigger", lambda tid: object())
    sub = save_subscription(BriefSubscription(conn_id="c1", name="m", trigger_id="t", period="month",
                                              content="briefing"))
    monkeypatch.setenv(FLAG_ENV, "0")
    paused = update_briefing_subscription(sub.id, _SubscriptionBody(
        conn_id="c1", name="m", trigger_id="t", period="month", content="briefing", enabled=False))
    assert paused["enabled"] is False and paused["content"] == "briefing"


def test_an_empty_fiscal_month_reads_as_the_calendar_year():
    assert complete_period("year", TODAY, fiscal_start_month=None).start == date(2025, 1, 1)
    assert complete_period("year", TODAY, fiscal_start_month=0).start == date(2025, 1, 1)
