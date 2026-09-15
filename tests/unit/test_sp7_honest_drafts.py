"""SP-7 (§3.11, the second movement) — honest drafts: a draft may only say what is true here.

The census that opened the movement read the user's own staged drafts from the live inbox:
an agent pinned to schema ``public`` on a connection pinned to ``thelook``, and a chain
posting to a ``#general`` nobody named. Each law below closes one of those, and each is
proven at every door it guards — stage, accept and the create routes — because a rule held
at one door and not the next is the two-site drift this codebase keeps paying for.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import aughor.agent.spotlight_act as act
from aughor.actions.inbox import StagedProposal, accept_proposal, get_proposal, stage_proposal
from aughor.custom_agents.store import schema_scope_problem, validate_agent_draft

CONN = "sp7-look"


@pytest.fixture
def pinned(monkeypatch):
    """A registered connection that pins schema ``thelook`` — theLook's own shape."""
    monkeypatch.setattr("aughor.db.registry.list_connections",
                        lambda *a, **k: [{"id": CONN}])
    monkeypatch.setattr("aughor.db.registry.get_meta",
                        lambda conn_id: {"schema_name": "thelook"} if conn_id == CONN else {})


# ── the schema rule, as problem sentences ─────────────────────────────────────────────

def test_a_pinned_connection_refuses_any_other_schema(pinned):
    problems = validate_agent_draft(name="Anomaly Scout", instructions="x",
                                    connection_id=CONN, schema_scope="public")
    assert problems == ["schema 'public' is not on this connection — it reads schema "
                        "'thelook' only"]


def test_the_pinned_schema_itself_and_no_schema_both_pass(pinned):
    assert validate_agent_draft(connection_id=CONN, schema_scope="thelook") == []
    assert validate_agent_draft(connection_id=CONN, schema_scope="") == []


def test_a_measured_catalogue_refuses_a_name_it_does_not_hold():
    msg = schema_scope_problem("public", "any", known_schemas=["swiss_air", "missimi"])
    assert msg == ("schema 'public' is not on this connection — its schemas are: "
                   "missimi, swiss_air")
    assert schema_scope_problem("missimi", "any", known_schemas=["swiss_air", "missimi"]) == ""


def test_an_unread_schema_list_is_not_an_absence(monkeypatch):
    """Neither a pin nor a catalogue: nothing is known, so nothing is refused — and an empty
    catalogue is how a failed read arrives, so it is not a measurement either."""
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn_id: {})
    assert schema_scope_problem("anything", "unpinned") == ""
    assert schema_scope_problem("anything", "any", known_schemas=[]) == ""


def test_a_settings_read_that_fails_is_not_an_absence(monkeypatch):
    def boom(conn_id):
        raise RuntimeError("registry locked")
    monkeypatch.setattr("aughor.db.registry.get_meta", boom)
    assert schema_scope_problem("public", "whatever") == ""


# ── the doors: stage, accept, create ──────────────────────────────────────────────────

def test_spotlight_refuses_the_wrong_schema_before_anything_is_staged(pinned, monkeypatch):
    staged: list = []
    monkeypatch.setattr("aughor.actions.inbox.stage_proposal",
                        lambda p: staged.append(p) or p)
    draft = {"name": "Anomaly Scout", "instructions": "Hunt statistical departures."}

    out = act.draft_agent(CONN, {**draft, "schema_scope": "public"})
    assert out["staged"] is False
    assert any("'thelook' only" in p for p in out["problems"])
    assert staged == []

    # The control: the same draft on the schema the connection has DOES reach the stager,
    # so the refusal above is the rule's and not a patch point that never fires.
    out = act.draft_agent(CONN, {**draft, "schema_scope": "thelook"})
    assert out["staged"] is True and len(staged) == 1


def test_accept_refuses_a_staged_draft_whose_schema_is_not_there(pinned):
    """The user's pending draft, as it sits in the live inbox: staged before SP-7 existed."""
    from aughor.custom_agents.store import list_agents
    from aughor.org.context import current_org_id

    before = {a.id for a in list_agents()}
    p = stage_proposal(StagedProposal(
        kind="agent_draft", org_id=current_org_id() or "", connection_id=CONN,
        action_id="agent:Anomaly Scout",
        params={"name": "Anomaly Scout", "instructions": "Hunt statistical departures.",
                "schema_scope": "public", "doc_ids": []},
        reasoning="drafted from conversation", proposer="spotlight", source="agent"))

    result, _ = accept_proposal(p.id, actor="tester")
    assert result.ok is False
    assert "'thelook' only" in result.message
    assert {a.id for a in list_agents()} == before
    assert get_proposal(p.id).status == "failed"


def test_the_create_route_refuses_it(pinned):
    from aughor.routers.agents import UserAgentCreate, create_user_agent
    with pytest.raises(HTTPException) as err:
        create_user_agent(UserAgentCreate(name="Anomaly Scout", instructions="x",
                                          connection_id=CONN, schema_scope="public"))
    assert err.value.status_code == 422 and "'thelook' only" in err.value.detail


def test_the_template_route_refuses_it_before_looking_for_the_pack(pinned):
    from aughor.routers.agents import UserAgentFromTemplate, create_user_agent_from_template
    with pytest.raises(HTTPException) as err:
        create_user_agent_from_template(UserAgentFromTemplate(
            pack_id="no-such-pack", connection_id=CONN, schema_scope="public"))
    assert err.value.status_code == 422 and "'thelook' only" in err.value.detail


# ── open choices, and a first run that waits for its schedule ─────────────────────────

from types import SimpleNamespace  # noqa: E402

from aughor.automations.models import fill_required_holes  # noqa: E402
from aughor.automations.propose import ProposedChain, _first_run, propose_chain  # noqa: E402

AUTO_CONN = "sp7-auto"


class _Provider:
    """The model, scripted — nothing in this file spends a token."""

    def __init__(self, draft):
        self.draft = draft

    def complete(self, *, system, user, response_model, temperature=0.0):
        return self.draft


def _anomaly_chain(channel="#general", bot_id="sb_look") -> ProposedChain:
    """The user's own draft, in the shape the live inbox holds it (proposal ce470b60)."""
    return ProposedChain(
        name="Morning Anomaly Scout",
        description="Every morning at 9am, look for anomalies and post the top findings.",
        conditions=[{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
        effects=[
            {"kind": "investigate", "alias": "scout",
             "config": {"question": "Scan for anomalies in daily orders and revenue."}},
            {"kind": "slack_post", "alias": "post",
             "config": {"bot_id": bot_id, "channel": channel,
                        "message": {"$from": "scout.summary"}}},
        ])


@pytest.fixture
def two_bots(monkeypatch):
    monkeypatch.setattr("aughor.slackbots.store.list_bots", lambda *a, **k: [
        SimpleNamespace(id="sb_look", name="TheLook Analyst", enabled=True),
        SimpleNamespace(id="sb_aughor", name="Aughor", enabled=True)])


@pytest.fixture(autouse=True)
def _no_saved_chains():
    """The automations store is session-scoped: whatever an accept saves here is removed."""
    from aughor.automations.store import delete_automation, list_automations
    for a in list_automations(conn_id=AUTO_CONN):
        delete_automation(a.id)
    yield
    for a in list_automations(conn_id=AUTO_CONN):
        delete_automation(a.id)


def _stage_chain(channel: str, bot_id: str = "sb_aughor", trigger=None):
    from aughor.org.context import current_org_id
    return stage_proposal(StagedProposal(
        kind="automation_draft", org_id=current_org_id() or "", connection_id=AUTO_CONN,
        action_id="automation:Morning Anomaly Scout",
        params={"conn_id": AUTO_CONN, "name": "Morning Anomaly Scout",
                "conditions": [trigger or {"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
                "effects": [
                    {"kind": "investigate", "alias": "scout",
                     "config": {"question": "Scan for anomalies."}},
                    {"kind": "slack_post", "alias": "post",
                     "config": {"bot_id": bot_id, "channel": channel,
                                "message": {"$from": "scout.summary"}}}]},
        reasoning="drafted from conversation", proposer="spotlight", source="agent"))


def test_holes_are_named_and_only_the_copy_is_filled():
    effects = [{"kind": "slack_post", "config": {"bot_id": "sb_1", "channel": ""}}]
    filled, holes = fill_required_holes(effects)
    assert holes == ["Action 1 needs channel"]
    assert filled[0]["config"]["channel"] == "…"
    assert effects[0]["config"]["channel"] == ""      # what a person sees keeps the hole


def test_a_channel_and_sender_the_request_did_not_name_stay_open(two_bots):
    out = propose_chain("create an agent that delivers anomalies to slack every morning at 9am",
                        conn_id=AUTO_CONN, provider=_Provider(_anomaly_chain()))
    assert out.verdict == "proposed"
    post = out.draft["effects"][1]["config"]
    assert post["channel"] == "" and post["bot_id"] == ""
    assert out.to_fill == [
        "Action 2 needs a Slack channel — the request names no Slack channel",
        "Action 2 needs a Slack bot to send it — more than one Slack bot could send it "
        "and the request names none"]


def test_what_the_request_names_is_kept(two_bots):
    out = propose_chain("post anomalies to #anomalies as Aughor every morning at 9am",
                        conn_id=AUTO_CONN,
                        provider=_Provider(_anomaly_chain("#anomalies", "sb_aughor")))
    post = out.draft["effects"][1]["config"]
    assert (post["channel"], post["bot_id"]) == ("#anomalies", "sb_aughor")
    assert out.to_fill == []


def test_a_channel_named_only_inside_another_word_is_not_named(two_bots):
    out = propose_chain("generally, send anomalies to slack as Aughor", conn_id=AUTO_CONN,
                        provider=_Provider(_anomaly_chain("#general", "sb_aughor")))
    assert out.draft["effects"][1]["config"]["channel"] == ""


def test_the_one_bot_there_is_needs_no_choosing(monkeypatch):
    monkeypatch.setattr("aughor.slackbots.store.list_bots", lambda *a, **k: [
        SimpleNamespace(id="sb_only", name="Aughor", enabled=True)])
    out = propose_chain("post anomalies to #ops every morning", conn_id=AUTO_CONN,
                        provider=_Provider(_anomaly_chain("#ops", "")))
    assert out.draft["effects"][1]["config"]["bot_id"] == "sb_only"
    assert out.to_fill == []


def test_any_other_missing_key_still_refuses(two_bots):
    """Only the choices SP-7 opens become holes — a step the model left without its question
    is the model's failure, and refuses exactly as it did before."""
    chain = _anomaly_chain("#anomalies", "sb_aughor")
    chain.effects[0].config["question"] = ""
    out = propose_chain("post anomalies to #anomalies as Aughor", conn_id=AUTO_CONN,
                        provider=_Provider(chain))
    assert out.verdict == "refused" and "question" in out.reason


def test_the_first_run_is_read_by_the_schedulers_own_clock():
    from datetime import datetime, timezone
    evening = datetime(2026, 9, 14, 22, 37, tzinfo=timezone.utc)
    assert _first_run([{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
                      evening) == "2026-09-15T09:00:00Z"
    assert _first_run([{"kind": "webhook", "config": {}}], evening) == ""


def test_spotlight_says_what_is_open_and_when_it_would_first_run(two_bots, monkeypatch):
    real = propose_chain
    monkeypatch.setattr("aughor.automations.propose.propose_chain",
                        lambda outcome, conn_id: real(outcome, conn_id=conn_id,
                                                      provider=_Provider(_anomaly_chain())))
    out = act.draft_automation(AUTO_CONN, {"outcome": "anomalies to slack every morning at 9am"})
    assert out["staged"] is True
    assert "cannot be accepted until these are chosen" in out["summary"]
    assert out["first_run"].endswith("T09:00:00Z") and " UTC." in out["summary"]
    assert "OPEN CHOICES" in get_proposal(out["proposal_id"]).reasoning


def test_accept_refuses_an_open_choice_and_the_proposal_stays_pending():
    from aughor.automations.store import list_automations
    p = _stage_chain(channel="")
    result, _ = accept_proposal(p.id, actor="tester")
    assert result.ok is False and result.status == "invalid_params"
    assert "Action 2 needs channel" in result.message
    assert get_proposal(p.id).status == "pending"
    assert list_automations(conn_id=AUTO_CONN) == []


def test_an_accepted_schedule_waits_for_its_first_scheduled_time():
    from datetime import datetime, timezone

    from aughor.automations.store import get_automation
    p = _stage_chain(channel="#anomalies")
    result, _ = accept_proposal(p.id, actor="tester")
    assert result.ok is True, result.message
    saved = get_automation(result.detail["automation_id"])
    assert saved.enabled is True
    assert saved.paused_until == result.detail["first_run"]
    assert saved.paused_until.endswith("T09:00:00Z")
    wait = (datetime.fromisoformat(saved.paused_until.replace("Z", "+00:00"))
            - datetime.now(timezone.utc)).total_seconds()
    assert 0 < wait <= 24 * 3600


def test_a_chain_with_another_trigger_is_not_muted():
    """A webhook would be silenced by the same mute, so only an all-schedule chain waits."""
    from aughor.automations.store import get_automation
    p = _stage_chain(channel="#anomalies", trigger={"kind": "webhook", "config": {}})
    result, _ = accept_proposal(p.id, actor="tester")
    assert result.ok is True, result.message
    assert get_automation(result.detail["automation_id"]).paused_until is None
    assert result.detail["first_run"] == ""
