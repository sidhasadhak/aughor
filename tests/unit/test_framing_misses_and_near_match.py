"""PENDING.md item 12 (ROADMAP §3.32) — how often wording misses the declared terms, and what a
near-match would recover.

* A question on a scope that DECLARES definitions and reaches none of them is recorded — as a
  ledger event with the run's trace id, never the question's text; a question on a scope that
  declares nothing is not a miss, and neither is a framed one.
* The near-match finder is deterministic and changes nothing that answers: it proposes the
  declared definitions a missed question might mean, weighting rare words over type names, never
  matching two words that merely begin alike, never reading an instruction's verb as a term.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aughor.ontology.framing import frame_question
from aughor.ontology.framing_misses import KIND, misses, record
from aughor.ontology.models import OntologyGraph
from aughor.ontology.near_match import near_candidates

REPO = Path(__file__).resolve().parents[2]
LUX = OntologyGraph.model_validate(json.loads((REPO / "evals/ablation_luxexperience_business_ontology.json").read_text()))
OLIST = OntologyGraph.model_validate(json.loads((REPO / "evals/ablation_olist_business_ontology.json").read_text()))


def test_a_question_that_reaches_no_declared_term_is_recorded_without_its_text():
    frame = frame_question("How many transactions look fraudulent?", LUX)
    assert not frame.defines
    assert record(frame, LUX, "conn-miss", "lux", trace_id="t-miss-1") is True
    from aughor.kernel.ledger import Ledger
    event = Ledger.default().events(kind=KIND, conn_id="conn-miss", limit=1)[0]
    assert event["trace_id"] == "t-miss-1"
    assert "fraudulent" not in json.dumps(event["payload"])          # the text is not copied
    assert misses("conn-miss")["misses"] >= 1


def test_a_framed_question_or_a_scope_with_nothing_declared_is_not_a_miss():
    framed = frame_question("How many payments were high-risk for each payment method?", LUX)
    assert framed.defines and record(framed, LUX, "conn-miss-2", "lux") is False
    empty = OntologyGraph.model_validate({**json.loads(LUX.model_dump_json()), "rules": {}, "processes": {}})
    unframed = frame_question("How many transactions look fraudulent?", empty)
    assert record(unframed, empty, "conn-miss-2", "lux") is False


@pytest.mark.parametrize("graph, question, gold", [
    (LUX, "How many transactions look fraudulent?", "high_risk_payments"),
    (LUX, "How much revenue came from bags, shoes and jewellery last year?", "accessories_division"),
    (OLIST, "How much revenue came from Sao Paulo, Rio and Minas Gerais?", "southeast"),
])
def test_a_near_match_puts_the_meant_definition_among_the_candidates(graph, question, gold):
    assert gold in [c["name"] for c in near_candidates(question, graph)]


def test_near_matches_do_not_read_an_instruction_or_a_word_that_merely_begins_alike():
    assert near_candidates("Return the five brands with the most order lines.", LUX) == []      # a verb
    assert near_candidates("How many support tickets were opened in each channel?", LUX) == []  # channel ≠ change
    assert near_candidates("Order the product categories by number of order lines, largest first.", OLIST) == []


def test_resolve_frame_records_the_miss_on_the_way(monkeypatch):
    """The hook is where every fresh framing passes (`agent.framing.resolve_frame`)."""
    import aughor.agent.framing as agent_framing
    monkeypatch.setattr(agent_framing, "served_graph", lambda conn, schema=None: LUX)
    monkeypatch.setattr(agent_framing, "person_synonyms", lambda conn: [])
    before = misses("conn-resolve")["misses"]
    frame = agent_framing.resolve_frame("How many transactions look fraudulent?", "conn-resolve", "lux",
                                        choose=False, trace_id="t-resolve")
    assert not frame.defines and misses("conn-resolve")["misses"] == before + 1
    agent_framing.resolve_frame("How many payments were high-risk for each payment method?", "conn-resolve", "lux",
                                choose=False)
    assert misses("conn-resolve")["misses"] == before + 1                 # a framed question is not a miss



def test_one_run_that_frames_its_question_twice_is_one_miss():
    frame = frame_question("How many transactions look fraudulent?", LUX)
    before = misses("conn-twice")["misses"]
    assert record(frame, LUX, "conn-twice", "lux", inv_id="inv-1") is True
    assert record(frame, LUX, "conn-twice", "lux", inv_id="inv-1") is False
    assert misses("conn-twice")["misses"] == before + 1
