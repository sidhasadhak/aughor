"""SP-13 — the chain's own clock, DST included, with UTC never lied about.

The receipt sentence, pinned: a 09:00 Europe/Berlin chain fires at 07:00Z in summer
and 08:00Z in winter — read through the SAME trigger factory the scheduler uses, so
the first run a draft states cannot disagree with the one that happens. Berlin's
clocks fall back on Sunday 2026-10-25 at 03:00 CEST; the test walks straight across
that morning.
"""
from __future__ import annotations

from datetime import datetime, timezone

from aughor.automations.engine import next_fire_utc


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_a_9am_berlin_chain_fires_at_7z_in_summer_and_8z_in_winter():
    summer = next_fire_utc("0 9 * * *", _utc(2026, 7, 1, 0), "Europe/Berlin")
    winter = next_fire_utc("0 9 * * *", _utc(2026, 12, 1, 0), "Europe/Berlin")
    assert summer == _utc(2026, 7, 1, 7)      # CEST: 09:00 local = 07:00Z
    assert winter == _utc(2026, 12, 1, 8)     # CET:  09:00 local = 08:00Z


def test_the_clock_change_morning_itself():
    """Saturday's fire is at 07:00Z; Sunday the clocks fall back and the same cron
    fires at 08:00Z — one day apart, no arithmetic of ours in between."""
    from datetime import timedelta
    saturday = next_fire_utc("0 9 * * *", _utc(2026, 10, 24, 0), "Europe/Berlin")
    # +1s past the fire, the scheduler's own idiom — get_next_fire_time is inclusive.
    sunday = next_fire_utc("0 9 * * *", saturday + timedelta(seconds=1), "Europe/Berlin")
    assert saturday == _utc(2026, 10, 24, 7)
    assert sunday == _utc(2026, 10, 25, 8)


def test_the_result_is_always_utc_whatever_clock_evaluates():
    """Every consumer stamps ISO with a Z (`_first_run`, the store's first-run mute) —
    a Berlin-local datetime rendered with a Z would be the lie SP-13 exists to end."""
    t = next_fire_utc("0 9 * * *", _utc(2026, 7, 1, 0), "Europe/Berlin")
    assert t.utcoffset().total_seconds() == 0
    assert next_fire_utc("0 9 * * *", _utc(2026, 7, 1, 0)) == _utc(2026, 7, 1, 9)  # "" = UTC


def test_the_scheduler_reads_the_chains_own_clock():
    """`_schedule_fired` due-ness through the same factory: a Berlin 09:00 chain whose
    last run was yesterday is DUE at 07:05Z in July, and not yet at 06:55Z."""
    from aughor.automations.engine import _schedule_fired
    from aughor.automations.models import Automation, AutomationRun, Condition, Effect
    from aughor.automations.store import append_run, upsert_automation

    a = upsert_automation(Automation(
        conn_id="conn-tz", name="berlin nine", timezone="Europe/Berlin",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="notify", config={"trigger_id": "t1"})]))
    # the previous run at 06:00Z on July 1 — exactly one 09:00-Berlin (07:00Z)
    # boundary sits between the two probes below
    append_run(AutomationRun(automation_id=a.id, outcome="fired", reason="seed",
                             started_at="2026-07-01T06:00:00+00:00"))

    fired, why = _schedule_fired(a.conditions[0], a, _utc(2026, 7, 1, 6, 55))
    assert fired is False, why
    fired, why = _schedule_fired(a.conditions[0], a, _utc(2026, 7, 1, 7, 5))
    assert fired is True, why


def test_a_typoed_clock_refuses_at_construction():
    import pytest
    from aughor.automations.models import Automation, Condition, Effect
    with pytest.raises(ValueError, match="Europe/Berlin"):
        Automation(conn_id="c", name="x", timezone="Europe/Berlni",
                   conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                   effects=[Effect(kind="notify", config={"trigger_id": "t"})])


def test_the_first_run_mute_and_the_draft_speak_the_same_instant(monkeypatch, tmp_path):
    """The store mutes a fresh chain until its first SCHEDULED time — in the chain's
    own clock now — and the drafted first_run states the same instant."""
    from aughor.automations.store import _first_scheduled_time
    from aughor.automations.models import Automation, Condition, Effect

    a = Automation(conn_id="c", name="x", timezone="Europe/Berlin",
                   conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                   effects=[Effect(kind="notify", config={"trigger_id": "t"})])
    iso = _first_scheduled_time(a)
    from datetime import datetime as dt
    t = dt.fromisoformat(iso.replace("Z", "+00:00"))
    assert t.astimezone(timezone.utc).hour in (7, 8)   # 09:00 Berlin, whatever season


def test_edit_by_sentence_moves_the_clock(monkeypatch):
    """'switch it to Europe/Berlin' is a one-field diff through the same edit door."""
    import aughor.agent.spotlight_act as act
    from aughor.actions.inbox import accept_proposal
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import get_automation, upsert_automation

    a = upsert_automation(Automation(
        conn_id="conn-tz", name="utc nine",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="notify", config={"trigger_id": "t1"})]))
    out = act.edit_automation("conn-tz", {"automation": a.id,
                                          "changes": {"timezone": "Europe/Berlin"}})
    assert out["diff"] == [{"field": "timezone", "before": "", "after": "Europe/Berlin"}]
    result, _ = accept_proposal(out["proposal_id"], actor="tester")
    assert result.ok, result.message
    assert get_automation(a.id).timezone == "Europe/Berlin"

    # and a typo'd clock is refused by the door, never armed
    out = act.edit_automation("conn-tz", {"automation": a.id,
                                          "changes": {"timezone": "Mars/Olympus"}})
    result, _ = accept_proposal(out["proposal_id"], actor="tester")
    assert not result.ok and "Mars/Olympus" in result.message


def test_the_timezone_preference_key_validates_and_reaches_drafts(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_USER_PREFS_DB", str(tmp_path / "prefs.db"))
    import pytest
    from aughor.db.user_prefs import preferred_timezone, set_preference

    with pytest.raises(ValueError, match="IANA"):
        set_preference("timezone", "CEST")
    assert preferred_timezone() == ""
    set_preference("timezone", "Europe/Berlin")
    assert preferred_timezone() == "Europe/Berlin"
