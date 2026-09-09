"""Describe an agent, get a drafted one — the laws that draft has to obey.

Every test here runs with an INJECTED provider: this module's whole point is judgment
about a catalogue, and a suite that reached a live model to check it would measure the
weather. The repo has paid for that once already.
"""
from __future__ import annotations

import pytest

from aughor.custom_agents.propose import (MAX_DRAFTED_GOLDENS, ProposedAgent,
                                          ProposedGolden, propose_agent)

CATALOGUE = [
    {"name": "thelook", "tables": [{"name": n} for n in
                                   ("orders", "order_items", "users", "products")]},
    {"name": "billing", "tables": [{"name": "invoices"}]},
]
DOCS = [{"id": "doc_1", "title": "Refund policy"}, {"id": "doc_2", "title": "Glossary"}]
PACKS = [{"id": "pack_retail", "description": "retail metrics"}]


class _Provider:
    """Returns a fixed draft and records the system prompt it was handed."""

    def __init__(self, draft: ProposedAgent):
        self.draft, self.system, self.user = draft, "", ""

    def complete(self, *, system, user, response_model, temperature=0.0, **kw):
        self.system, self.user = system, user
        return self.draft


def _draft(**kw) -> ProposedAgent:
    base = dict(name="Orders Analyst", purpose="answers order questions",
                instructions="Answer with the order grain and say when a day is partial.",
                schema_scope="thelook", doc_ids=["doc_1"], pack_ids=["pack_retail"],
                goldens=[ProposedGolden(question="How many orders yesterday?", why="daily")],
                evidence="orders and order_items carry the grain")
    base.update(kw)
    return ProposedAgent(**base)


def _propose(draft: ProposedAgent, **kw):
    prov = _Provider(draft)
    kw.setdefault("catalogue", CATALOGUE)
    kw.setdefault("documents", DOCS)
    kw.setdefault("packs", PACKS)
    return propose_agent("agent for orders", conn_id="c1", provider=prov,
                         validator=lambda **_: [], **kw), prov


# ── it proposes; it never creates ────────────────────────────────────────────────────

def test_a_proposal_is_a_draft_and_nothing_is_saved():
    proposal, _ = _propose(_draft())
    assert proposal.verdict == "proposed"
    assert proposal.draft["name"] == "Orders Analyst"
    assert proposal.draft["connection_id"] == "c1"
    # The id an agent would have is conspicuously absent: nothing was created.
    assert "id" not in proposal.draft


def test_only_fields_that_reach_the_runtime_are_drafted():
    """GOVERNING_FIELDS + name + purpose. A knob that changes nothing teaches the page lies."""
    proposal, _ = _propose(_draft())
    assert set(proposal.draft) == {"name", "purpose", "instructions", "connection_id",
                                   "schema_scope", "doc_ids", "pack_ids"}


def test_an_empty_description_is_refused_without_calling_a_model():
    prov = _Provider(_draft())
    out = propose_agent("   ", conn_id="c1", catalogue=CATALOGUE, provider=prov)
    assert out.verdict == "refused" and not prov.system, "no model call for an empty ask"


# ── the model drafts questions; it may not certify answers ───────────────────────────

def test_goldens_come_back_as_uncertified_questions_with_no_model_written_sql():
    proposal, _ = _propose(_draft())
    assert proposal.goldens[0]["question"] == "How many orders yesterday?"
    assert proposal.goldens[0]["reference_sql"] == ""
    assert proposal.goldens[0]["certified"] is False
    # The schema itself must not offer the model a place to put SQL.
    assert "reference_sql" not in ProposedGolden.model_fields


def test_drafted_goldens_are_capped_so_the_synchronous_eval_stays_clickable():
    many = [ProposedGolden(question=f"q{i}") for i in range(MAX_DRAFTED_GOLDENS + 5)]
    proposal, _ = _propose(_draft(goldens=many))
    assert len(proposal.goldens) == MAX_DRAFTED_GOLDENS


# ── disclosures are written by CODE, not by the drafter ──────────────────────────────

def test_no_documents_is_disclosed_as_restrictive_not_neutral():
    proposal, _ = _propose(_draft(doc_ids=[]))
    assert any("RESTRICTIVE" in d and "FEWER" in d for d in proposal.disclosures), \
        "the empty-doc_ids trap must be stated, not buried"


def test_an_unscoped_agent_is_disclosed_with_the_table_count_it_really_covers():
    proposal, _ = _propose(_draft(schema_scope=""))
    assert any("every schema" in d and "5 tables" in d for d in proposal.disclosures)


def test_an_uncertified_suite_is_named_as_measuring_nothing():
    proposal, _ = _propose(_draft())
    assert any("CERTIFIED" in d for d in proposal.disclosures)
    bare, _ = _propose(_draft(goldens=[]))
    assert any("unmeasured" in d for d in bare.disclosures)


# ── the draft cannot point at things that do not exist ───────────────────────────────

def test_a_hallucinated_schema_widens_the_scope_and_says_so():
    """Free-text `schema_scope` 409s on every ask, silently. A drafted typo must not
    reintroduce that by another door."""
    proposal, _ = _propose(_draft(schema_scope="warehouse_v2"))
    assert proposal.draft["schema_scope"] == ""
    assert "warehouse_v2" in proposal.notes and "widened" in proposal.notes


def test_invented_document_and_pack_ids_are_dropped():
    proposal, _ = _propose(_draft(doc_ids=["doc_1", "doc_nope"],
                                  pack_ids=["pack_retail", "pack_ghost"]))
    assert proposal.draft["doc_ids"] == ["doc_1"]
    assert proposal.draft["pack_ids"] == ["pack_retail"]


def test_the_catalogue_documents_and_packs_all_reach_the_drafter():
    _, prov = _propose(_draft())
    assert "thelook (4 tables): orders" in prov.system
    assert "doc_1 — Refund policy" in prov.system
    assert "pack_retail" in prov.system


# ── refusals are answers, not failures ───────────────────────────────────────────────

def test_a_nameless_draft_is_a_refusal_carrying_the_drafters_reason():
    proposal, _ = _propose(_draft(name="", notes="no order data on this connection"))
    assert proposal.verdict == "refused"
    assert proposal.reason == "no order data on this connection"


def test_a_draft_the_save_would_reject_is_refused_rather_than_drawn():
    """A canvas showing an agent the Save button will 422 looks like nearly-finished work."""
    prov = _Provider(_draft())
    out = propose_agent("x", conn_id="c1", catalogue=CATALOGUE, documents=DOCS,
                        provider=prov,
                        validator=lambda **_: ["instructions are required"])
    assert out.verdict == "refused" and "instructions are required" in out.reason


def test_a_provider_that_raises_is_a_refusal_not_a_traceback():
    class _Boom:
        def complete(self, **kw): raise RuntimeError("no model configured")
    out = propose_agent("x", conn_id="c1", catalogue=CATALOGUE, provider=_Boom())
    assert out.verdict == "refused" and "no model configured" in out.reason


def test_an_empty_catalogue_tells_the_drafter_it_cannot_scope_anything():
    prov = _Provider(_draft(name=""))
    propose_agent("x", conn_id="c1", catalogue=[], provider=prov)
    assert "empty" in prov.system and "Refuse" in prov.system


# ── the route ────────────────────────────────────────────────────────────────────────

def test_the_propose_route_is_not_shadowed_by_the_agent_id_route(client):
    """FastAPI matches in DECLARATION order, so a static segment declared after a
    path-parameter route is never reached. This repo has paid for that once already."""
    r = client.post("/agents/custom/propose", json={"description": "x"})
    assert r.status_code == 200, r.text
    assert "verdict" in r.json(), "the propose route answered, not the {agent_id} route"


def test_the_route_refuses_without_a_connection_and_never_reaches_a_model(client,
                                                                         monkeypatch):
    """A refusal is an ANSWER to the question asked — 200 with a reason the flow renders
    as a step, not a 422 the form renders as the person's mistake."""
    import aughor.custom_agents.propose as mod
    monkeypatch.setattr(mod, "propose_agent",
                        lambda *a, **k: pytest.fail("must not draft without a connection"))
    body = client.post("/agents/custom/propose",
                       json={"description": "orders agent", "connection_id": " "}).json()
    assert body["verdict"] == "refused" and "connection" in body["reason"]
    assert body["draft"] == {} and body["goldens"] == []
