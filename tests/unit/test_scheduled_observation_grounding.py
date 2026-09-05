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
