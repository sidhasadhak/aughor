"""Wave K4b — the deep investigation auto-invokes the action proposer after synthesis.

`_attach_kinetic_proposals` stages proposals onto the answer report (flag `kinetic.agent_actions`,
default off) — never executing, never disturbing the report. Hermetic: the proposer and the ontology
loader are faked; no model, no store.
"""
from __future__ import annotations

from aughor.agent import investigate as I
from aughor.kinetic.propose import Proposal
from aughor.ontology.models import KineticAction, OntologyGraph, SubmissionCriterion


def _ar(**kw) -> dict:
    base = dict(headline="Returns spiked", executive_summary="Order X9001 was double-charged EUR 480.")
    base.update(kw)
    return base


def _graph_with_action() -> OntologyGraph:
    g = OntologyGraph(connection_id="c", schema_fingerprint="fp")
    g.kinetic_actions["refund"] = KineticAction(
        id="refund", kind="side_effect", submission_criteria=[SubmissionCriterion(expr="1==1", message="m")])
    return g


def test_attaches_staged_proposals_when_flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.agent_actions")
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda *a, **k: _graph_with_action())
    seen = {}

    def _fake_propose(graph, context, scope=""):
        seen["context"] = context
        seen["scope"] = scope
        return [Proposal("refund", "proposed", {"amount_eur": 480.0}, "clear duplicate charge")]

    monkeypatch.setattr("aughor.kinetic.propose.propose_actions", _fake_propose)

    ar = _ar()
    I._attach_kinetic_proposals(ar, "conn-1")

    assert ar["proposals"][0]["action_id"] == "refund" and ar["proposals"][0]["ok"] is True
    assert ar["proposals"][0]["params"] == {"amount_eur": 480.0}
    assert ar["proposals"][0]["reasoning"] == "clear duplicate charge"
    # the answer (headline + exec summary) is the grounding context; the scope is the connection
    assert "double-charged" in seen["context"] and seen["scope"] == "conn-1"


def test_noop_when_flag_off(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    ar = _ar()
    I._attach_kinetic_proposals(ar, "c")
    assert "proposals" not in ar


def test_noop_when_connection_declares_no_actions(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.agent_actions")
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda *a, **k: OntologyGraph(connection_id="c", schema_fingerprint="fp"))
    ar = _ar()
    I._attach_kinetic_proposals(ar, "c")
    assert "proposals" not in ar          # nothing to propose ⇒ no field, no LLM call


def test_fails_open_on_a_loader_error(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "kinetic.agent_actions")

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", boom)
    ar = _ar()
    I._attach_kinetic_proposals(ar, "c")   # must not raise
    assert "proposals" not in ar
