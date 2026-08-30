"""VA-9c — an agent may propose named actions, and proposing is not doing.

Measured before building: every tool an agent could call was a READ (`run_sql`,
`answer_question`, `deep_analysis`, `list_tables`, `describe_table`, plus the platform
roster, documented as "the read roster for one connection" and never filtered per agent).
`stage_proposal` was reachable only from an HTTP route. So VA-9's own receipt — grant one
agent `post_message`, ask it to act, the write pauses at approval — was not merely
unbuilt, it was unreachable.

The properties locked here:

* **A grant is permission to PROPOSE, never to EXECUTE.** A granted action still lands in
  the resolve-once inbox and waits for a human. Collapsing the two turns "may suggest a
  refund" into "may issue refunds".
* **No grants ⇒ no write tool at all**, rather than a tool that always refuses. The model
  picks from what it can see, and a visible tool is one it will spend a turn trying.
* **Named actions, never a whole roster.** An ungranted action is refused by name, with
  the roster, so the model does not guess again.
* **An unreadable agent means READ-ONLY**, never open.
* **Grants are governing configuration** — an agent that gained the power to propose a
  refund is not the agent an eval chip was earned by.
"""
from __future__ import annotations

import pytest

from aughor.agent.action_tools import action_tools, granted_actions, propose_one
from aughor.custom_agents.models import UserAgent


def _agent(**kw) -> UserAgent:
    base = dict(id="ag-1", name="Analyst", connection_id="conn-a")
    base.update(kw)
    return UserAgent(**base)


# ── the tool exists only when something was granted ──────────────────────────────

def test_an_agent_with_no_grants_gets_NO_write_tool():
    """Not a refusing tool: the model routes over what it can see, and a tool it can see
    is one it will try — each attempt costing a turn arguing with a gate."""
    assert action_tools("conn-a", agent=_agent()) == []
    assert action_tools("conn-a", agent=None) == []


def test_a_granted_agent_gets_exactly_one_write_tool_naming_its_roster():
    tools = action_tools("conn-a", agent=_agent(tool_grants=["refund_orders", "post_note"]))
    assert [t.name for t in tools] == ["propose_action"]
    desc = tools[0].description
    assert "refund_orders" in desc and "post_note" in desc
    # The description IS the routing policy — it has to say that nothing happens.
    assert "NOTHING happens" in desc or "nothing has been executed" in desc.lower()
    assert "accept" in desc.lower(), "the human step must be stated, not implied"


def test_granted_actions_ignores_junk():
    assert granted_actions(_agent(tool_grants=["a", "", "b"])) == ["a", "b"]
    assert granted_actions(None) == []


# ── proposing is not doing ───────────────────────────────────────────────────────

def test_an_ungranted_action_is_refused_BY_NAME_with_the_roster():
    out = propose_one("conn-a", grants=["post_note"], action_id="refund_orders")
    assert out["ok"] is False and out["status"] == "not_granted"
    assert "refund_orders" in out["message"] and "post_note" in out["message"], \
        "naming the roster stops the model guessing again, and each guess is a turn"


def test_an_ungranted_action_never_reaches_the_inbox(monkeypatch, graph_of, action):
    """`graph_of` is load-bearing. Without a resolvable graph the path stops at
    "no_actions" BEFORE staging, so `staged == []` would hold even with the grant gate
    removed — the assertion would pass for the wrong reason. Mutation-testing caught it:
    disabling the gate left this test green."""
    graph_of(action(id="refund_orders"))
    staged = []
    monkeypatch.setattr("aughor.actions.inbox.stage_proposal",
                        lambda p: staged.append(p) or p)
    # VALID params, deliberately: with a missing required param the proposal fails
    # validation and stages nothing anyway, so the assertion would again hold for a
    # reason that has nothing to do with grants. Everything except the grant must be
    # in order, or this proves nothing.
    propose_one("conn-a", grants=["post_note"], action_id="refund_orders",
                params={"order_id": "8821"})
    assert staged == [], "a refusal must not stage anything"


def test_a_granted_action_is_STAGED_and_awaits_approval(monkeypatch, graph_of, action):
    graph_of(action(id="post_note"))
    out = propose_one("conn-a", grants=["post_note"], action_id="post_note",
                      params={"order_id": "8821"}, reasoning="the user asked")

    assert out["ok"] is True
    assert out["status"] == "awaiting_approval", "not 'done' — a human has not accepted"
    assert out["proposal_id"]
    assert "awaiting" in out["message"].lower()
    assert "never that it is done" in out["message"], \
        "the model must be told what to SAY, or it will report the act as complete"


def test_the_staged_proposal_is_the_real_inbox_row(monkeypatch, graph_of, action):
    """Drives the REAL inbox, so this fails if the seam is unplugged rather than only if
    the return shape is wrong."""
    from aughor.actions.inbox import get_proposal
    graph_of(action(id="post_note"))
    out = propose_one("conn-a", grants=["post_note"], action_id="post_note",
                      params={"order_id": "1"}, proposer="agent:ag-1")

    p = get_proposal(out["proposal_id"])
    assert p is not None
    assert p.status == "pending", "staged, not executed"
    assert p.action_id == "post_note" and p.proposer == "agent:ag-1"
    assert p.expires_at, "RC-3's acceptance window applies to an agent's proposal too"


def test_a_criterion_failure_returns_the_AUTHORED_message(graph_of, action):
    """The action author wrote that sentence for exactly this moment; paraphrasing it
    would replace a domain rule with a generic refusal."""
    from aughor.ontology.models import SubmissionCriterion
    graph_of(action(id="post_note", submission_criteria=[
        SubmissionCriterion(expr="order_id == '8821'", message="Only order 8821 may post.")]))
    out = propose_one("conn-a", grants=["post_note"], action_id="post_note",
                      params={"order_id": "9999"})
    assert out["ok"] is False
    assert out["message"] == "Only order 8821 may post."


def test_a_connection_with_no_declared_actions_says_so(monkeypatch):
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda cid, schema=None: None)
    out = propose_one("conn-a", grants=["post_note"], action_id="post_note")
    assert out["ok"] is False and out["status"] == "no_actions"


# ── grants are governing configuration ───────────────────────────────────────────

def test_adding_a_grant_changes_the_config_rev():
    """An eval chip earned before a grant was added was earned by a different agent."""
    before = _agent().config_rev
    after = _agent(tool_grants=["refund_orders"]).config_rev
    assert before != after


def test_reordering_grants_does_NOT_change_the_config_rev():
    a = _agent(tool_grants=["a", "b"]).config_rev
    b = _agent(tool_grants=["b", "a"]).config_rev
    assert a == b, "the same permissions in a different order is the same agent"


def test_tool_grants_is_a_governing_field():
    from aughor.custom_agents.models import GOVERNING_FIELDS
    assert "tool_grants" in GOVERNING_FIELDS


# ── fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def action():
    from aughor.ontology.models import ActionParameter, KineticAction

    def _make(**kw):
        base = dict(id="post_note", kind="side_effect",
                    params=[ActionParameter(name="order_id", data_type="VARCHAR",
                                            required=True)],
                    submission_criteria=[], side_effects=[], risk="high")
        base.update(kw)
        return KineticAction(**base)
    return _make


@pytest.fixture
def graph_of(monkeypatch):
    def _install(act):
        class _G:
            kinetic_actions = {act.id: act}
        monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                            lambda cid, schema=None: _G())
    return _install
