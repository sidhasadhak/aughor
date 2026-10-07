"""A scheduled investigation knows what time it is — the theLook-incident model fix.

Measured 2026-09-05: the first automation anyone pointed at a daily cadence chose the
in-progress day as its observation period, and narrated a history-restating source's
rewrites as business change, every morning. The correction lives in the MODEL, not in
that automation: a schedule-fired ``investigate`` now carries a code-written
observation note (complete periods only; ``observation_lag_days`` moves the anchor)
and its own previous report (so restatement is named, not narrated).

Pinned here: the note's arithmetic per cadence, the lag clamp, the previous-report
read-back from the run history the engine already keeps, and the two engine
guarantees — a scheduled dispatch is grounded, and a NON-scheduled automation's
question stays byte-identical.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aughor.automations import temporal
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome

NOW = datetime(2026, 9, 6, 9, 0, tzinfo=timezone.utc)


# ── the observation note ─────────────────────────────────────────────────────────────


def test_cadence_is_read_from_the_cron_shape():
    assert temporal.cadence_of("0 9 * * *") == "daily"
    assert temporal.cadence_of("0 9 * * 1") == "weekly"
    assert temporal.cadence_of("0 9 1 * *") == "monthly"
    assert temporal.cadence_of("gibberish") == "daily"   # safest true statement


def test_daily_note_names_yesterday_and_forbids_today():
    note = temporal.observation_note(NOW, "0 9 * * *")
    assert "Observe 2026-09-05 (UTC), the most recent complete day." in note
    assert "today is 2026-09-06" in note and "partial by construction" in note


def test_lag_moves_the_anchor_and_says_why():
    note = temporal.observation_note(NOW, "0 9 * * *", lag_days=3)
    assert "Observe 2026-09-03 (UTC)" in note
    assert "observation lag of 3 days" in note
    assert "not yet reliable for this source" in note


def test_weekly_and_monthly_name_complete_periods():
    weekly = temporal.observation_note(NOW, "0 9 * * 1")
    # Sep 6 2026 is a Sunday; anchor Sep 5 (Sat) ⇒ last COMPLETE Mon–Sun week
    assert "2026-08-24 to 2026-08-30" in weekly
    monthly = temporal.observation_note(NOW, "0 9 1 * *")
    assert "COMPLETE month: 2026-08" in monthly


def test_lag_is_clamped_never_trusted():
    assert temporal.clamp_lag("not a number") == 1
    assert temporal.clamp_lag(0) == 1
    assert temporal.clamp_lag(99) == 30


# ── the previous report, read from the history the engine already keeps ──────────────


@pytest.fixture()
def runs_store(tmp_path, monkeypatch):
    import aughor.automations.store as store
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "automations.db")
    store._init_schema()
    return store


def _run(store, automation_id, outcome, summary=""):
    effects = []
    if summary:
        effects = [EffectOutcome(kind="investigate", target="q", status="executed",
                                 data={"summary": summary})]
    store.append_run(
        __import__("aughor.automations.models", fromlist=["AutomationRun"])
        .AutomationRun(automation_id=automation_id, outcome=outcome, effects=effects))


def test_previous_report_is_the_last_fired_investigate_summary(runs_store):
    _run(runs_store, "auto1", "fired", "Orders were 1,745 on September 4.")
    _run(runs_store, "auto1", "not_fired")
    _run(runs_store, "auto1", "not_fired")
    note = temporal.previous_report_note("auto1")
    assert "Orders were 1,745 on September 4." in note
    assert "restated its own history" in note


def test_previous_report_survives_a_real_day_of_not_fired_ticks(runs_store):
    """The population is the scheduler's, not a hand-picked pair.

    The two `not_fired` rows above are what this note was born with, and they are the
    reason it shipped broken: the ENGINE appends a row on every tick, so a daily cron
    lays down ~1,440 `not_fired` rows between one fired run and the next. Measured on
    the live theLook briefing 2026-09-08: 400 consecutive rows, all `not_fired`, and
    this note had therefore returned '' on every production run since it shipped —
    the agent was never once told its source restates history.

    300 rows is well past any window this could be tempted to take; the fix is that
    there IS no window over ticks, because the outcome filter runs in SQL.
    """
    _run(runs_store, "auto1", "fired", "Orders were 1,745 on September 4.")
    for _ in range(300):
        _run(runs_store, "auto1", "not_fired")

    note = temporal.previous_report_note("auto1")
    assert "Orders were 1,745 on September 4." in note, (
        "the previous report was buried under a day of scheduler ticks")


def test_lag_makes_the_report_disclose_its_own_age(runs_store):
    """A correctly-lagged report that does not say so reads as a broken one.

    The live briefing posted "On September 5th, 2026..." on September 8 with nothing
    explaining the gap, and its owner's first words were "today's date is wrong".
    """
    note = temporal.observation_note(NOW, "0 9 * * *", lag_days=3)
    assert "3 days behind today (2026-09-06 UTC)" in note
    assert "restates its most recent days" in note


def test_no_lag_means_no_disclosure_sentence(runs_store):
    # lag=1 is just "yesterday" — nothing to explain, and no extra prompt weight.
    assert "behind today" not in temporal.observation_note(NOW, "0 9 * * *")


def test_no_history_means_no_note(runs_store):
    assert temporal.previous_report_note("never-ran") == ""


# ── the engine guarantees ────────────────────────────────────────────────────────────


def _automation(conditions):
    return Automation(
        name="t", conn_id="c1", conditions=conditions,
        effects=[Effect(kind="investigate", config={"question": "what changed?"})])


def _capture_dispatch(monkeypatch):
    import aughor.runners as runners
    captured = {}

    def _fake(req, **kw):
        captured["question"] = req.question
        return SimpleNamespace(status="submitted", message="ok", headline="",
                               summary="", investigation_id="inv1")

    monkeypatch.setattr(runners, "run_investigation", _fake)
    return captured


def test_scheduled_dispatch_is_grounded_and_target_stays_raw(runs_store, monkeypatch):
    from aughor.automations.engine import _dispatch_investigate
    captured = _capture_dispatch(monkeypatch)
    auto = _automation([Condition(kind="schedule", config={"cron": "0 9 * * *"})])

    outcome = _dispatch_investigate(auto.effects[0], auto)
    q = captured["question"]
    assert q.startswith("[Scheduled-run context")
    assert "most recent complete day" in q
    assert q.rstrip().endswith("what changed?")
    # The run history shows the human's question, not the machinery's preamble.
    assert outcome.target == "what changed?"


def test_lag_setting_on_the_effect_config_is_honoured(runs_store, monkeypatch):
    from aughor.automations.engine import _dispatch_investigate
    captured = _capture_dispatch(monkeypatch)
    auto = _automation([Condition(kind="schedule", config={"cron": "0 9 * * *"})])
    auto.effects[0].config["observation_lag_days"] = 3

    _dispatch_investigate(auto.effects[0], auto)
    assert "observation lag of 3 days" in captured["question"]


def test_unscheduled_automations_keep_a_byte_identical_question(runs_store, monkeypatch):
    from aughor.automations.engine import _dispatch_investigate
    captured = _capture_dispatch(monkeypatch)
    auto = _automation([Condition(kind="metric", config={"monitor_id": "m1"})])

    _dispatch_investigate(auto.effects[0], auto)
    assert captured["question"] == "what changed?"


def test_previous_summary_reaches_the_scheduled_prompt(runs_store, monkeypatch):
    from aughor.automations.engine import _dispatch_investigate
    captured = _capture_dispatch(monkeypatch)
    auto = _automation([Condition(kind="schedule", config={"cron": "0 9 * * *"})])
    _run(runs_store, auto.id, "fired", "Yesterday the source said 1,769.")

    _dispatch_investigate(auto.effects[0], auto)
    q = captured["question"]
    assert "Yesterday the source said 1,769." in q
    assert "restated its own history" in q


# ── the previous report's DEFINITION, so a definition change is not called a restatement ──────
# Traced 2026-10-07: theLook's daily runs read Revenue under three definitions in five days; this
# block told each run that any disagreement IS the source restating, and the 4 October report
# blamed the source for the switch from items not Cancelled to items marked Complete.


def test_the_previous_basis_is_quoted_and_a_definition_change_is_not_a_restatement(runs_store, monkeypatch):
    from aughor.automations.models import AutomationRun
    import aughor.db.history as history

    runs_store.append_run(AutomationRun(automation_id="daily", outcome="fired", effects=[
        EffectOutcome(kind="investigate", target="q", status="executed",
                      data={"summary": "Revenue increased by 7.55% to $20,496.80 on September 25, 2026.",
                            "investigation_id": "f4255ab0"})]))
    report = {
        "metric_definition": "Revenue — computed as `SUM(sale_price)`; on order_items",
        "envelope": {"provenance": {"sql": [
            "SELECT DATE(created_at), SUM(sale_price) FROM order_items "
            "WHERE status <> 'Cancelled' AND created_at >= '2026-09-24' GROUP BY 1"]}},
    }
    monkeypatch.setattr(history, "get_investigation", lambda iid: {"report": report} if iid == "f4255ab0" else None)
    note = temporal.previous_report_note("daily")
    assert "That report's definition: Revenue — computed as `SUM(sale_price)`; on order_items" in note
    assert "Its figures were read WHERE status <> 'Cancelled' AND created_at >= '2026-09-24'" in note
    assert "the difference is the DEFINITION" in note and "do not call it a restatement" in note
    # The block still ends on its sentence, so the person's words are still recovered from it.
    asked = "What changed in theLook in the last day?"
    assert temporal.ask_of(note + "\n\n" + asked) == asked


def test_an_unreadable_previous_run_quotes_its_summary_alone(runs_store, monkeypatch):
    from aughor.automations.models import AutomationRun
    import aughor.db.history as history

    runs_store.append_run(AutomationRun(automation_id="daily2", outcome="fired", effects=[
        EffectOutcome(kind="investigate", target="q", status="executed",
                      data={"summary": "Orders fell.", "investigation_id": "gone"})]))
    monkeypatch.setattr(history, "get_investigation", lambda iid: None)
    note = temporal.previous_report_note("daily2")
    assert "Orders fell." in note and "That report's definition" not in note


# ── a hand-set lag shorter than the measured one is said, not silently kept ────────────────────
# theLook's daily run reads at 8 days by a person's setting; the settling read puts the source at
# 29 (still moving at the oldest age it read), and governed revenue for 24 September moved from
# $15,929.96 to $19,057.53 between 8 and 9 days old (2026-10-07).


def test_reading_younger_than_the_source_settles_is_said():
    note = temporal.unsettled_note(8, 29)
    assert "still changing days up to 29 days old" in note and "reads at 8" in note
    assert "never call a later change to the same day a business change" in note


def test_no_sentence_when_the_lag_is_the_learned_one_or_none_was_learned():
    assert temporal.unsettled_note(29, 29) == ""
    assert temporal.unsettled_note(8, None) == ""
    assert temporal.unsettled_note(12, 9) == ""


def test_the_sentence_rides_the_generated_block_and_leaves_the_persons_words(runs_store, monkeypatch):
    auto = _automation([Condition(kind="schedule", config={"cron": "0 9 * * *"})])
    block = temporal.scheduled_grounding(auto, {"observation_lag_days": 8}, learned_lag=29)
    assert "reads at 8 by its own setting" in block
    asked = "What changed in theLook in the last day?"
    assert temporal.ask_of(block + "\n\n" + asked) == asked
    # The person's lag still wins: the window is 8 days back, not 29.
    assert "observation lag of 8 days" in block
