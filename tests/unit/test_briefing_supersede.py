"""Arc BR-5 (ROADMAP §3.48) — one Briefing, not three.

theLook's only daily delivery was an automation — a deep analysis posted to Slack by a bot —
dark since 2026-09-19. A Day Briefing subscription now posts to the same channel through the
same bot and the same departure gate, and pauses (never deletes) the automation it replaces
once it has delivered seven mornings (the user's call, §6 item 34(e)). The send re-measures
every figure it states, a segment's change included.
"""
from __future__ import annotations

import pytest

from aughor.briefing import delivery
from aughor.briefing.models import SUPERSEDE_AFTER, BriefSubscription
from aughor.govern.departure import DepartureVerdict


def test_a_row_that_never_uses_the_new_fields_is_stored_exactly_as_before():
    row = BriefSubscription(conn_id="c1", name="n", trigger_id="t").to_dict()
    assert not {"bot_id", "channel", "schema_name", "supersedes", "delivered"} & set(row)
    bot = BriefSubscription(conn_id="c1", name="n", bot_id="sb_1", channel="#ops", content="briefing",
                            supersedes="a1", delivered=3).to_dict()
    assert (bot["bot_id"], bot["channel"], bot["supersedes"], bot["delivered"]) == ("sb_1", "#ops", "a1", 3)


@pytest.fixture
def sent(monkeypatch):
    """A Day subscription whose build and gate are stubbed; the bot's post is recorded."""
    posts: list[tuple[str, str]] = []
    monkeypatch.setattr(delivery, "build_period_departure", lambda sub, runner=None: {
        "brief": {}, "held_lines": [], "summary": "Daily Briefing — 2026-09-10",
        "markdown": "Revenue moved from $14,438 to $19,365 (+34%)."})
    monkeypatch.setattr("aughor.govern.departure.gate_departure", lambda **kw: DepartureVerdict(
        state="departed", record_id="dep1", receipt={"measured_by": "the day briefing's queries"}))

    class _Bot:
        name, enabled, bot_token = "TheLook Analyst", True, "not-a-real-token"

    monkeypatch.setattr("aughor.slackbots.store.get_bot_decrypted", lambda bot_id: _Bot())
    monkeypatch.setattr("aughor.slackbots.post.post_as_bot",
                        lambda token, channel, text, thread_ts=None: (posts.append((channel, text)) or True, {"ts": "1"}))
    monkeypatch.setattr("aughor.knowledge.period_brief.refusal", lambda period: None)
    return posts


def _automation():
    from aughor.automations.models import Automation, Condition, Effect
    from aughor.automations.store import get_automation, upsert_automation
    a = upsert_automation(Automation(
        conn_id="c1", name="The Look - Daily Briefing",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="slack_post", config={"bot_id": "sb_1", "channel": "#aughor_canvas",
                                                   "message": "hello"})]))
    return get_automation(a.id)


def test_a_bot_subscription_posts_after_the_gate_and_pauses_what_it_replaces_on_the_seventh(sent, monkeypatch):
    from aughor.automations.store import get_automation
    from aughor.briefing.store import save_subscription
    replaced = _automation()
    sub = save_subscription(BriefSubscription(conn_id="c1", name="The Look — Day", period="day",
                                              content="briefing", bot_id="sb_1", channel="#aughor_canvas",
                                              supersedes=replaced.id))
    for morning in range(1, SUPERSEDE_AFTER + 2):
        result = delivery.deliver_subscription(sub)
        assert result["status"] == "ok" and sub.delivered == morning
        paused = str(get_automation(replaced.id).paused_until or "")
        if morning < SUPERSEDE_AFTER:
            assert paused == "" and not result["superseded"]
        elif morning == SUPERSEDE_AFTER:
            assert paused.startswith("9999") and result["superseded"] == replaced.id
        else:
            assert paused.startswith("9999") and result["superseded"] == ""   # never re-paused
    channel, text = sent[0]
    assert channel == "#aughor_canvas" and text.startswith("Revenue moved from $14,438 to $19,365")
    assert get_automation(replaced.id) is not None                            # paused, not deleted


def test_a_held_send_is_not_a_delivered_morning(sent, monkeypatch):
    from aughor.briefing.store import save_subscription
    monkeypatch.setattr("aughor.govern.departure.gate_departure",
                        lambda **kw: DepartureVerdict(state="held", reasons=["re-measured: 1,648 not in the analysis"]))
    sub = save_subscription(BriefSubscription(conn_id="c1", name="Day", period="day", content="briefing",
                                              bot_id="sb_1", channel="#ops"))
    result = delivery.deliver_subscription(sub)
    assert result["status"] == "held" and sub.delivered == 0 and sent == []


def test_the_send_remeasures_each_segment_and_the_change_it_states():
    """theLook's automation was held four mornings for figures its analysis never measured; a
    range send states segment figures and their changes, so both are re-run at the send."""
    import contextlib

    from aughor.briefing import ranges

    rows = {"q_head": (["_w", "_v", "_first", "_last", "_n"], [("current", 19365.0, None, None, 9),
                                                                ("previous", 14438.0, None, None, 7)]),
            "q_seg": (["_w", "_g", "_v", "_first", "_last", "_n"], [("current", "Complete", 6721.0, None, None, 65),
                                                                     ("previous", "Complete", 3916.0, None, None, 70)])}

    @contextlib.contextmanager
    def runner():
        yield (lambda sql: (*rows[sql], None)), "duckdb"

    brief = {"period": {"label": "Daily", "last_day": "2026-09-10",
                        "measured": [{"sql": "q_head"}], "moves": [{"sql": "q_seg"}]}}
    m = ranges.fresh_measurement("c1", brief, runner=runner)
    assert {19365.0, 14438.0, 6721.0, 3916.0} <= set(m.values)
    assert 2805.0 in m.values and 4927.0 in m.values                        # the changes it states


def test_the_router_refuses_a_bot_without_a_channel_and_another_connections_automation(monkeypatch):
    from fastapi import HTTPException

    from aughor.routers.briefs import _SubscriptionBody, _validate_destination
    monkeypatch.setattr("aughor.slackbots.store.get_bot", lambda bot_id: object())
    with pytest.raises(HTTPException) as no_channel:
        _validate_destination(_SubscriptionBody(conn_id="c1", name="n", bot_id="sb_1"))
    assert no_channel.value.status_code == 422
    other = _automation()
    with pytest.raises(HTTPException) as foreign:
        _validate_destination(_SubscriptionBody(conn_id="c2", name="n", bot_id="sb_1", channel="#x",
                                                supersedes=other.id))
    assert foreign.value.status_code == 422 and "not one of this connection's" in foreign.value.detail
