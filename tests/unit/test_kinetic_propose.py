"""Wave K4 — the agent proposes a declared action.

The proposer is deterministic around one LLM call (faked here): the model returns structured
proposals, and each is dry-run validated (typed params + submission criteria) and STAGED — never
executed. Locks: a valid proposal stages with coerced params; a criterion violation returns the
AUTHORED message verbatim (for the model to revise); bad params / unknown actions are caught; the
model may abstain; and no declared actions ⇒ no LLM call. Hermetic: no network, no execution.
"""
from __future__ import annotations

from aughor.kinetic.propose import (
    ProposedAction,
    ProposerOutput,
    build_kinetic_actions_section,
    evaluate_proposal,
    propose_actions,
    validate_proposals,
)
from aughor.ontology.models import (
    ActionParameter,
    KineticAction,
    OntologyGraph,
    SubmissionCriterion,
)

MSG = "Refunds over €10,000 need finance sign-off — route to approvals instead."


def _graph() -> OntologyGraph:
    g = OntologyGraph(connection_id="c", schema_name="s", schema_fingerprint="fp")
    g.kinetic_actions["refund_order"] = KineticAction(
        id="refund_order", kind="side_effect", risk="high",
        description="Refund an order.",
        params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True),
                ActionParameter(name="amount_eur", data_type="NUMERIC", required=True)],
        submission_criteria=[SubmissionCriterion(expr="amount_eur <= 10000", message=MSG)])
    return g


class _FakeProvider:
    def __init__(self, proposals):
        self._proposals = proposals
        self.calls = 0

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls += 1
        self.system = system
        return ProposerOutput(proposals=self._proposals)


# ── the prompt section ───────────────────────────────────────────────────────────

def test_section_lists_actions_params_and_criteria():
    s = build_kinetic_actions_section(_graph())
    assert "refund_order" in s
    assert "order_id" in s and "amount_eur" in s and "required" in s
    assert "amount_eur <= 10000" in s          # the model sees the constraint


def test_section_empty_without_actions():
    assert build_kinetic_actions_section(OntologyGraph(
        connection_id="c", schema_fingerprint="fp")) == ""


# ── dry-run validation (no execution) ─────────────────────────────────────────────

def test_evaluate_valid_proposal():
    action = _graph().kinetic_actions["refund_order"]
    status, msg, coerced = evaluate_proposal(action, {"order_id": "A1", "amount_eur": "500"})
    assert status == "proposed" and msg == "" and coerced == {"order_id": "A1", "amount_eur": 500.0}


def test_evaluate_criterion_violation_returns_authored_message():
    action = _graph().kinetic_actions["refund_order"]
    status, msg, _ = evaluate_proposal(action, {"order_id": "A1", "amount_eur": "25000"})
    assert status == "criterion_failed" and msg == MSG


def test_evaluate_invalid_params():
    action = _graph().kinetic_actions["refund_order"]
    status, msg, _ = evaluate_proposal(action, {"order_id": "A1"})   # missing amount_eur
    assert status == "invalid_params" and "amount_eur" in msg


# ── proposer → staged proposals ────────────────────────────────────────────────────

def test_valid_proposal_is_staged_with_coerced_params():
    fake = _FakeProvider([ProposedAction(action_id="refund_order",
                                         params={"order_id": "A1", "amount_eur": "500"},
                                         reasoning="clear duplicate charge")])
    out = propose_actions(_graph(), "order A1 was double-charged", scope="c", provider=fake)
    assert len(out) == 1 and out[0].ok and out[0].status == "proposed"
    assert out[0].params == {"order_id": "A1", "amount_eur": 500.0}   # coerced, ready to accept
    assert out[0].reasoning == "clear duplicate charge"
    assert fake.calls == 1


def test_criterion_violating_proposal_carries_the_authored_message():
    fake = _FakeProvider([ProposedAction(action_id="refund_order",
                                         params={"order_id": "A1", "amount_eur": "50000"})])
    out = propose_actions(_graph(), "big refund", scope="c", provider=fake)
    assert out[0].status == "criterion_failed" and out[0].message == MSG and not out[0].ok


def test_unknown_action_is_flagged():
    fake = _FakeProvider([ProposedAction(action_id="delete_everything", params={})])
    out = propose_actions(_graph(), "ctx", scope="c", provider=fake)
    assert out[0].status == "unknown_action" and not out[0].ok


def test_model_may_abstain():
    fake = _FakeProvider([])
    out = propose_actions(_graph(), "nothing actionable here", scope="c", provider=fake)
    assert out == [] and fake.calls == 1


def test_no_declared_actions_makes_no_llm_call():
    fake = _FakeProvider([ProposedAction(action_id="x")])
    out = propose_actions(OntologyGraph(connection_id="c", schema_fingerprint="fp"),
                          "ctx", scope="c", provider=fake)
    assert out == [] and fake.calls == 0          # abstain WITHOUT paying for a model call


def test_proposer_error_fails_open():
    class _Boom:
        def complete(self, **k):
            raise RuntimeError("model down")
    out = propose_actions(_graph(), "ctx", scope="c", provider=_Boom())
    assert out == []                               # advisory — never blocks the answer


def test_section_is_in_the_proposer_system_prompt():
    fake = _FakeProvider([])
    propose_actions(_graph(), "ctx", scope="c", provider=fake)
    assert "DECLARED ACTIONS" in fake.system and "refund_order" in fake.system


def test_validate_mixes_valid_and_invalid():
    raw = [ProposedAction(action_id="refund_order", params={"order_id": "A", "amount_eur": "9"}),
           ProposedAction(action_id="refund_order", params={"order_id": "B", "amount_eur": "99999"}),
           ProposedAction(action_id="nope", params={})]
    out = validate_proposals(_graph(), raw, scope="c")
    assert [p.status for p in out] == ["proposed", "criterion_failed", "unknown_action"]


# ── the HTTP surface ─────────────────────────────────────────────────────────────

def test_router_propose_404_when_flag_off(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    from fastapi import HTTPException

    from aughor.routers import kinetic as K
    import pytest
    with pytest.raises(HTTPException) as e:
        K.propose_actions_route(K.ProposeRequest(context="x"), connection_id="c", schema_name=None)
    assert e.value.status_code == 404


def test_router_propose_returns_staged_proposals(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.agent_actions")
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda *a, **k: _graph())
    fake = _FakeProvider([ProposedAction(action_id="refund_order",
                                         params={"order_id": "A1", "amount_eur": "500"})])
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role=None: fake)
    from aughor.routers import kinetic as K
    out = K.propose_actions_route(K.ProposeRequest(context="A1 double charged"),
                                  connection_id="c", schema_name=None)
    assert out["proposals"][0]["status"] == "proposed" and out["proposals"][0]["ok"] is True
