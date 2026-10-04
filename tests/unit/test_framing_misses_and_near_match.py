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
THELOOK = OntologyGraph.model_validate(json.loads((REPO / "evals/ablation_thelook_business_ontology.json").read_text()))


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


# ── the ask, not the code-written context in front of it (2026-10-04) ────────────────────

def _grounded(ask: str, previous: str = "Revenue fell.\n\nOrders were completed on time.") -> str:
    """A scheduled run's question as the engine composes it, by the composer's own parts."""
    from datetime import datetime, timezone

    from aughor.automations import temporal
    note = temporal.observation_note(datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc), "0 9 * * *", 8)
    prev = (f"{temporal.PREVIOUS_REPORT_HEADER}\nThe previous run of this automation reported:\n"
            f"\"{previous}\"\nIf your current measurements DISAGREE, say so instead of "
            f"{temporal._PREVIOUS_REPORT_END}")
    return f"{note}\n\n{prev}\n\n{ask}"


def test_the_ask_is_recovered_from_a_scheduled_runs_question():
    """Round trip through the composer's own blocks — and the previous report is quoted text
    that holds a blank line, which is why that block ends on its last sentence."""
    from aughor.automations.temporal import ask_of
    ask = "What changed in theLook in the last day?\n\nSay which day."
    assert ask_of(_grounded(ask)) == ask
    assert ask_of(ask) == ask, "a question with no block in front of it is returned as it is"
    assert ask_of("") == ""


def test_the_scheduled_context_is_not_read_as_the_question():
    """Measured on theLook: all twelve recorded scheduled runs drew `completed_orders` from
    "the most recent complete day" and the previous report's "order volume". The ask named
    neither."""
    from aughor.automations.temporal import ask_of
    grounded = _grounded("What changed in theLook in the last day?")
    assert [c["name"] for c in near_candidates(grounded, THELOOK)] == ["completed_orders"], \
        "the context alone draws the term — the fault this guards"
    assert near_candidates(ask_of(grounded), THELOOK) == []


def test_resolve_frame_frames_the_ask(monkeypatch):
    """The exact matcher reads the same words. A report quoted in the context that names a
    declared term must not frame the run that follows it."""
    import aughor.agent.framing as agent_framing
    monkeypatch.setattr(agent_framing, "served_graph", lambda conn, schema=None: LUX)
    monkeypatch.setattr(agent_framing, "person_synonyms", lambda conn: [])
    quoted = "High-risk payments rose to 40 on the day."
    assert frame_question(quoted, LUX).defines, "the quoted report alone would frame"
    frame = agent_framing.resolve_frame(_grounded("What changed in the last day?", previous=quoted),
                                        "conn-ask-of", "lux", choose=False, trace_id="t-ask-of")
    assert not frame.defines


def test_a_miss_shows_its_question_however_long_the_run_was():
    """The reader took a run's newest twenty events and looked for the question there; it is on
    the first. Every one of theLook's 45 misses had more than twenty events, so each read "not
    kept" the day after it ran."""
    from aughor.obs import session_log
    asked = "How many transactions look fraudulent?"
    session_log.emit(session_log.USER_REQUEST, name="ask", trace_id="t-long-run",
                     payload={"question": asked})
    for i in range(30):
        session_log.emit(session_log.LLM_CALL, name="m", trace_id="t-long-run", payload={"i": i})
    frame = frame_question(asked, LUX)
    assert record(frame, LUX, "conn-long", "lux", trace_id="t-long-run") is True
    got = misses("conn-long", graph=LUX)["recent"][0]
    assert got["question"] == asked and got["scheduled"] is False
    assert [m["name"] for m in got["might_mean"]] == ["high_risk_payments"], \
        "what a person might add a synonym for — offered, never framed"


def test_a_scheduled_runs_miss_shows_the_ask_and_says_it_was_scheduled():
    from aughor.obs import session_log
    session_log.emit(session_log.USER_REQUEST, name="ask", trace_id="t-sched-run",
                     payload={"question": _grounded("What changed in the last day?")})
    frame = frame_question("What changed in the last day?", THELOOK)
    assert record(frame, THELOOK, "conn-sched", "thelook", trace_id="t-sched-run") is True
    got = misses("conn-sched", graph=THELOOK)["recent"][0]
    assert got["question"] == "What changed in the last day?" and got["scheduled"] is True
    assert got["might_mean"] == [], "nothing declared on theLook is meant by it"
