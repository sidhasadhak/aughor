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
