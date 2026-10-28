"""Briefings by period (IDEAS.md 3, PENDING.md item 7, ROADMAP §3.27).

A day, week, month or year Briefing is the range Briefing of that period's preset
(`test_briefing_ranges.py`); what these hold is what it shares with the period Briefing it replaced:

* the window is computed, complete and settled — and the monthly rule it shares with the
  scheduled-run note no longer skips the month that just ended;
* a trend query cut to the period gives the numbers a hand-written query gives, a rate is
  recomputed (never averaged), and a query that cannot be cut says why instead of vanishing;
* the narrator is told which version it writes, and a lag longer than a day is said;
* the standing brief, the alert summary and every stored subscription read as before, and a
  subscription may send the Briefing of any period.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

import aughor.llm.provider as prov
from aughor.automations.temporal import complete_period, observation_note
from aughor.knowledge import briefing as briefing_mod
from aughor.knowledge import period_brief
from aughor.knowledge.briefing import BriefingCitation, BriefingNarrative, _SYSTEM

TODAY = date(2026, 9, 23)          # a Wednesday; with the one-day lag the anchor is Tue 22 Sep

# ── fixtures ────────────────────────────────────────────────────────────────────────────────

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

def test_a_period_move_is_phrased_the_way_the_triage_reads_a_change():
    from aughor.knowledge.triage import extract_change
    covers, against = period_brief.phrases(complete_period("week", TODAY))
    block = {"covers": covers, "compared_with": against}
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
            "novelty": 3, "sql": "SELECT 1"}


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
def test_a_lag_longer_than_a_day_is_said_in_the_prompt(source, moving, said):
    week = complete_period("week", TODAY, lag_days=8)
    covers, against = period_brief.phrases(week)
    block = {**week.to_dict(), "label": "Weekly", "covers": covers, "compared_with": against,
             "lag_source": source, "still_moving": moving}
    note = period_brief.period_note(block, TODAY)
    assert block["start"] == "2026-09-07" and "This is the WEEKLY briefing" in note
    assert said in note


# ── the standing brief, the alert summary and the subscriptions ────────────────────────────

def test_a_period_that_does_not_exist_is_refused_with_why():
    assert period_brief.refusal("week") is None and period_brief.refusal("year") is None
    assert "period must be one of" in period_brief.refusal("fortnight")


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


def test_subscription_periods_and_contents():
    from fastapi import HTTPException

    from aughor.routers.briefs import _validate_period
    _validate_period("day")
    _validate_period("week")
    for period in ("day", "week", "month", "year"):
        _validate_period(period, "briefing")
    with pytest.raises(HTTPException) as refused:
        _validate_period("month", "alert_summary")
    assert refused.value.status_code == 422 and "there is no monthly alert summary" in refused.value.detail
    with pytest.raises(HTTPException) as unknown:
        _validate_period("fortnight", "briefing")
    assert unknown.value.status_code == 422 and "period must be one of" in unknown.value.detail
    with pytest.raises(HTTPException) as content:
        _validate_period("month", "newsletter")
    assert content.value.status_code == 422


def test_the_daily_alert_summary_is_headed_daily():
    from aughor.briefing.delivery import brief_summary
    from aughor.briefing.models import BriefSubscription
    from aughor.monitors.alert_summary import AlertSummary
    summary = AlertSummary(conn_id="c1", period="day", generated_at="2026-09-23T08:00:00Z",
                          sections=[], alert_count=0, critical_count=0)
    assert summary.to_markdown().startswith("# Aughor Intelligence Digest — Daily")
    sub = BriefSubscription(conn_id="c1", name="n", trigger_id="t", period="day")
    assert brief_summary(sub, summary).startswith("Daily Intelligence Brief")


def test_a_briefing_subscription_can_be_paused(monkeypatch):
    """Branch review, 2026-09-24: pause re-sends period and content, which are validated only when
    they change — so a saved briefing subscription can always be paused."""
    from aughor.briefing.models import BriefSubscription
    from aughor.briefing.store import save_subscription
    from aughor.routers.briefs import _SubscriptionBody, update_briefing_subscription
    import aughor.notifications.store as triggers
    monkeypatch.setattr(triggers, "get_trigger", lambda tid: object())
    sub = save_subscription(BriefSubscription(conn_id="c1", name="m", trigger_id="t", period="month",
                                              content="briefing"))
    paused = update_briefing_subscription(sub.id, _SubscriptionBody(
        conn_id="c1", name="m", trigger_id="t", period="month", content="briefing", enabled=False))
    assert paused["enabled"] is False and paused["content"] == "briefing"


def test_an_empty_fiscal_month_reads_as_the_calendar_year():
    assert complete_period("year", TODAY, fiscal_start_month=None).start == date(2025, 1, 1)
    assert complete_period("year", TODAY, fiscal_start_month=0).start == date(2025, 1, 1)
