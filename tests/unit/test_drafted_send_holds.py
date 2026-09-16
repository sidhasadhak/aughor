"""SP-7 widened to outbound sends (2026-09-16): a Slack post a MODEL drafted into a chain
waits for a person on its first run, and "always allow" makes later runs unattended.

The custody gap a live 9am tick surfaced: the drafted-write hold covered warehouse writes
only, so a drafted anomaly chain would have posted to Slack with nobody having said so.
Locked here, through the REAL engine dispatch and the REAL inbox accept (only the Slack
transport and the bot store are stubbed):

* a drafted post (`require_approval`) parks the run and stages an `outbound_send` proposal;
* accepting it POSTS once and the resumed chain reads the real thread ts downstream;
* accept with "always allow" mints a standing send-grant, and the NEXT run posts unattended;
* a hand-built post (no `require_approval`) never parks — untouched, like a hand-built write;
* the drafted-hold helper marks slack_post.
"""
from __future__ import annotations

import pytest

from aughor.automations.engine import resume_run, run_automation
from aughor.automations.models import Automation, Condition, Effect
from aughor.automations.store import get_run, upsert_automation


@pytest.fixture(autouse=True)
def _slack_stub(monkeypatch):
    posts: list = []

    class _Bot:
        name, enabled, bot_token = "Aughor", True, "xoxb-x"

    def _post(token, channel, message, thread_ts=None):
        posts.append({"channel": channel, "message": message, "thread_ts": thread_ts})
        return True, {"ts": f"ts{len(posts)}", "channel": channel}

    monkeypatch.setattr("aughor.slackbots.store.get_bot_decrypted", lambda bid: _Bot())
    monkeypatch.setattr("aughor.slackbots.post.post_as_bot", _post)
    return posts


def _chain(*, drafted: bool, message="anomalies today") -> Automation:
    cfg = {"bot_id": "sb_1", "channel": "#ops", "message": message}
    if drafted:
        cfg["require_approval"] = True
    return upsert_automation(Automation(
        name="anomaly delivery", conn_id="conn-send",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
        effects=[Effect(kind="slack_post", alias="tell", config=cfg)], max_retries=0))


def _run(a):
    # manual=True forces the trigger — these tests are about the SEND hold, not schedule
    # due-ness, and a daily cron is not due twice in one test second.
    return run_automation(a, persist=True, manual=True, probe=lambda *x, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0)


def test_the_hold_helper_marks_a_drafted_slack_post():
    from aughor.automations.dataflow import DECLARED_WRITE_KIND
    from aughor.automations.propose import _hold_drafted_writes
    from types import SimpleNamespace
    drafted = SimpleNamespace(effects=[
        SimpleNamespace(kind="slack_post", config={}),
        SimpleNamespace(kind="investigate", config={}),
        SimpleNamespace(kind=DECLARED_WRITE_KIND, config={})])
    held = _hold_drafted_writes(drafted)
    assert held == [1, 3]
    assert drafted.effects[0].config["require_approval"] is True
    assert "require_approval" not in drafted.effects[1].config


def test_a_hand_built_post_never_parks(_slack_stub):
    run = _run(_chain(drafted=False))
    assert run.outcome != "paused"
    assert len(_slack_stub) == 1                      # it just posted, no human asked


def test_a_drafted_post_parks_and_accept_sends_once(_slack_stub):
    from aughor.actions.inbox import accept_proposal, proposals_for_run

    a = _chain(drafted=True)
    run = _run(a)
    assert run.outcome == "paused"
    assert _slack_stub == []                          # nothing posted while it waits
    pending = [p for p in proposals_for_run(run.id) if p.pending]
    assert len(pending) == 1 and pending[0].kind == "outbound_send"
    assert pending[0].params["channel"] == "#ops"

    result, grant = accept_proposal(pending[0].id, actor="person:amit")
    assert result.ok and len(_slack_stub) == 1       # the accept performed the send
    assert grant == ""                               # no "always allow" → no standing grant
    resume_run(run.id, sleeper=lambda _s: None, rng=lambda: 0.0)
    assert get_run(run.id).outcome != "paused"       # chain finished

    # A SECOND run with no grant parks again — "every run until always allow".
    run2 = _run(a)
    assert run2.outcome == "paused" and len(_slack_stub) == 1


def test_always_allow_mints_a_send_grant_and_the_next_run_is_unattended(_slack_stub):
    from aughor.actions.inbox import accept_proposal, proposals_for_run

    a = _chain(drafted=True)
    run = _run(a)
    pending = [p for p in proposals_for_run(run.id) if p.pending][0]
    result, grant = accept_proposal(pending.id, actor="person:amit", mint_grant=True)
    assert result.ok and grant                       # a standing send-grant was minted
    resume_run(run.id, sleeper=lambda _s: None, rng=lambda: 0.0)

    # The next run finds the grant and posts unattended — no park, no new proposal.
    posts_before = len(_slack_stub)
    run2 = _run(a)
    assert run2.outcome != "paused"
    assert len(_slack_stub) == posts_before + 1
    assert not [p for p in proposals_for_run(run2.id) if p.pending]


def test_the_grant_is_bound_to_the_channel_not_blanket(_slack_stub):
    """always-allow for #ops does not authorize a post to #general — the target is exact."""
    from aughor.actions import grants
    from aughor.actions.inbox import accept_proposal, proposals_for_run

    a = _chain(drafted=True)
    run = _run(a)
    pending = [p for p in proposals_for_run(run.id) if p.pending][0]
    accept_proposal(pending.id, actor="person:amit", mint_grant=True)
    assert grants.matching_send_grant(a.id, "#ops", connection_id="conn-send") is not None
    assert grants.matching_send_grant(a.id, "#general", connection_id="conn-send") is None
