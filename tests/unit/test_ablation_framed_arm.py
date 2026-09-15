"""ON-10 — the ablation harness's `framed` arm: the frame block a question gets, the arm that must not spend where
there is nothing declared to frame, and the falsifier the movement is held to. Hermetic: the served Olist graph, no
live connection, no model."""
from __future__ import annotations

import json
from pathlib import Path

from aughor.ontology.models import OntologyGraph
from evals.ablation_eval import _arms_after_frame_check, _summarize, framed_context

REPO = Path(__file__).resolve().parents[2]
OLIST = OntologyGraph.model_validate(json.loads((REPO / "evals" / "ablation_olist_business_ontology.json").read_text()))


def test_a_question_that_reaches_nothing_declared_gets_no_frame_and_no_call():
    block, frame, calls = framed_context("How many sellers are there in each state?", OLIST)
    assert block == "" and frame["defines"] is False and calls == 0


def test_a_declared_definition_gets_its_block_and_an_ambiguous_one_one_choice():
    block, frame, calls = framed_context("What percentage of order lines broke the dispatch promise?", OLIST)
    assert block.startswith("QUESTION FRAME") and "dispatch_breach_rate, compiled by the object door" in block
    assert calls == 0 and frame["outcomes"][frame["chosen"]]["name"] == "dispatch_breach_rate"
    chosen = []

    def choose(f, g):
        chosen.append([o.name for o in f.candidates()])
        from aughor.ontology.framing import frame_question
        return frame_question(f.question, g, choice="delivery_breach_rate", chosen_by="model")

    block, frame, calls = framed_context("What was late last month?", OLIST, choose=choose)
    assert calls == 1 and chosen == [["dispatch_breach_rate", "delivery_breach_rate"]]
    assert frame["chosen_by"] == "model" and "delivery_breach_rate, compiled" in block


def test_the_arm_is_dropped_where_nothing_is_declared():
    bare = OLIST.model_copy(update={"processes": {}, "rules": {}})
    assert _arms_after_frame_check(("raw", "guarded", "framed"), bare) == (("raw", "guarded"), ("framed",))
    assert _arms_after_frame_check(("raw", "framed"), OLIST) == (("raw", "framed"), ())
    assert _arms_after_frame_check(("raw", "framed"), None) == (("raw",), ("framed",))
    assert _arms_after_frame_check(("raw", "framed", "framed_guarded"), bare) == (("raw",), ("framed", "framed_guarded"))


def _row(rid, definition, raw, guarded, framed, via="", framed_guarded=None):
    row = {"id": rid, "definition": definition, "raw": {"class": raw}, "guarded": {"class": guarded, "guards_fired": []},
           "framed": {"class": framed}}
    if via:
        row["framed"]["via"] = via
    if framed_guarded is not None:
        row["framed_guarded"] = {"class": framed_guarded, "guards_fired": []}
    return row


def test_the_falsifier_holds_only_when_framed_beats_raw_on_the_declared_definitions():
    arms = ("raw", "guarded", "framed")
    rows = [_row("d1", "declared", "silent-wrong", "silent-wrong", "correct"),
            _row("d2", "declared", "correct", "correct", "correct"),
            _row("d3", "declared", "silent-wrong", "caught", "silent-wrong"),
            _row("c1", "schema", "correct", "correct", "correct", via="raw (the question reached nothing declared)")]
    s = _summarize(rows, arms)
    assert s["by_definition"]["declared"] == {"n": 3, "raw_correct": 1, "framed_correct": 2, "guarded_safe": 2}
    assert s["falsifier"]["framed_beats_raw_on_declared"] is True and s["falsifier"]["controls_lost"] == []
    assert s["framed_gains"] == ["d1"] and s["framed_losses"] == [] and s["framed_no_frame"] == ["c1"]
    tie = [_row("d1", "declared", "correct", "correct", "correct"), _row("c1", "schema", "correct", "correct", "error")]
    s = _summarize(tie, arms)
    assert s["falsifier"]["framed_beats_raw_on_declared"] is False and s["falsifier"]["controls_lost"] == ["c1"]
    assert _summarize([_row("c1", "schema", "correct", "correct", "correct")], arms)["falsifier"] is None


def test_the_guarded_framed_arm_is_held_to_the_safety_guarding_already_keeps():
    arms = ("raw", "guarded", "framed", "framed_guarded")
    rows = [_row("d1", "declared", "silent-wrong", "caught", "silent-wrong", framed_guarded="caught"),
            _row("d2", "declared", "silent-wrong", "silent-wrong", "correct", framed_guarded="correct"),
            _row("c1", "schema", "correct", "correct", "correct", framed_guarded="correct")]
    s = _summarize(rows, arms)
    assert (s["framed_guarded_safe_rate"], s["framed_guarded_silent_wrong"]) == (1.0, 0)
    assert s["by_definition"]["declared"]["framed_guarded_safe"] == 2
    assert s["falsifier"]["framed_guarded_keeps_guarded_safety"] is True
    worse = [_row("d1", "declared", "silent-wrong", "caught", "silent-wrong", framed_guarded="silent-wrong")]
    assert _summarize(worse, arms)["falsifier"]["framed_guarded_keeps_guarded_safety"] is False
