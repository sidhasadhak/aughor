"""A1 — the decision corpus's provenance, its return path, and the yield read.

Hermetic: no LLM, no warehouse, no network. `evals/decision_yield_eval.py`'s pure helpers
are imported the way `tests/unit/test_ablation_framed_arm.py` imports the ablation
harness's, so the eval keeps a CI gate without `evals/` joining the suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aughor.learning import decisions  # noqa: E402
from evals.decision_yield_eval import arm_a, summarize  # noqa: E402


def _wipe() -> None:
    conn = decisions._connect()
    try:
        conn.execute("DELETE FROM decision_record")
        conn.commit()
    finally:
        conn.close()


def test_a_decision_carries_the_world_it_was_made_in():
    """Without conn_id a row cannot be attributed, which is what made the live 40 useless."""
    _wipe()
    rid = decisions.record_decision("framing.definition", "what is our return rate?",
                                    ["completed_orders: ...", "controllable_returns: ..."],
                                    chosen="completed_orders", confidence=0.62,
                                    conn_id="914df862", trace_id="tr-1", inv_id="inv-1")
    assert rid
    [row] = decisions.list_decisions(site="framing.definition")
    assert row["conn_id"] == "914df862"
    assert row["trace_id"] == "tr-1"
    assert row["confidence"] == pytest.approx(0.62)


def test_a_human_verdict_closes_every_decision_that_run_made():
    """mark_outcomes_for_run is the negative half: before it, every row read 'ok'."""
    _wipe()
    for site in ("ask.route", "converse.tool"):
        decisions.record_decision(site, "q", ["a", "b"], chosen="a",
                                  conn_id="914df862", inv_id="inv-7", outcome="ok")
    decisions.record_decision("converse.tool", "q", ["a", "b"], chosen="b",
                              conn_id="914df862", inv_id="inv-other", outcome="ok")

    closed = decisions.mark_outcomes_for_run(inv_id="inv-7", outcome="rejected")
    assert closed == 2

    by_inv = {(r["inv_id"], r["outcome"]) for r in decisions.list_decisions(limit=10)}
    assert ("inv-7", "rejected") in by_inv
    assert ("inv-other", "ok") in by_inv, "another run's decisions must not be touched"


def test_marking_a_run_never_raises_and_refuses_an_empty_key():
    """It sits behind a verdict write; a missing key is a no-op, not an exception."""
    _wipe()
    assert decisions.mark_outcomes_for_run(inv_id="", trace_id="", outcome="rejected") == 0
    assert decisions.mark_outcomes_for_run(inv_id="inv-1", outcome="") == 0


def test_one_outcome_value_is_not_a_label():
    """The heart of A1: 40 rows all reading 'ok' is a constant, not a corpus."""
    _wipe()
    for _ in range(4):
        decisions.record_decision("converse.tool", "q", ["a", "b"], chosen="a",
                                  conn_id="c1", outcome="ok")
    assert decisions.corpus_yield()["converse.tool"]["discriminating"] is False

    decisions.record_decision("converse.tool", "q", ["a", "b"], chosen="b",
                              conn_id="c1", outcome="error")
    assert decisions.corpus_yield()["converse.tool"]["discriminating"] is True


def test_yield_counts_attribution_and_probability_separately():
    _wipe()
    decisions.record_decision("ask.route", "q", ["direct", "investigate"],
                              chosen="direct", conn_id="c1", confidence=0.9)
    decisions.record_decision("ask.route", "q", ["direct", "investigate"],
                              chosen="investigate", source="rule", confidence=0.0)
    got = decisions.corpus_yield()["ask.route"]
    assert got["total"] == 2
    assert got["attributable"] == 1
    assert got["with_probability"] == 1
    assert got["trainable"] == 2


def test_a_one_option_menu_is_not_trainable():
    """Same floor as list_for_export — the two reads must not drift."""
    _wipe()
    decisions.record_decision("converse.tool", "q", ["only"], chosen="only", conn_id="c1")
    assert decisions.corpus_yield()["converse.tool"]["trainable"] == 0


def test_arm_a_is_derived_per_site_not_blanket_zeroes():
    """The pre-A1 code was not equally blind at every site, and pretending it was would
    overstate A1. ask.route ALWAYS passed the model's confidence, so the probability column
    is not what A1 bought there — attribution and the outcome are."""
    measured = {
        "converse.tool": {"total": 40, "attributable": 40, "with_probability": 0,
                          "trainable": 40, "outcomes": {"ok": 39, "rejected": 1},
                          "discriminating": True},
        "ask.route": {"total": 8, "attributable": 8, "with_probability": 8,
                      "trainable": 8, "outcomes": {"rejected": 1}, "discriminating": False},
    }
    a = arm_a(measured)
    assert a["converse.tool"]["with_probability"] == 0
    assert a["converse.tool"]["outcomes"] == {"ok": 40}
    assert a["ask.route"]["with_probability"] == 8, "ask.route always had a probability"
    assert a["ask.route"]["outcomes"] == {}, "nothing ever closed a route decision"
    for site in a.values():
        assert site["attributable"] == 0
        assert site["discriminating"] is False
    assert a["converse.tool"]["total"] == 40 and a["converse.tool"]["trainable"] == 40, \
        "A1 records more, it does not decide more"


def test_an_unknown_site_is_assumed_arm_a_capable():
    """The conservative direction: a site missing from the capability table must make A1
    look like it bought LESS, never more."""
    measured = {"new.site": {"total": 5, "attributable": 5, "with_probability": 5,
                             "trainable": 5, "outcomes": {"ok": 5}, "discriminating": False}}
    assert arm_a(measured)["new.site"]["with_probability"] == 5


def test_a_conversational_turn_gets_its_investigation_stitched_on_afterwards():
    """A converse turn has no investigation id while it runs — save_chat_turn mints one
    FROM the answer. Measured 2026-09-20 before this existed: four rows from two real
    LuxExperience turns carried conn_id and an empty inv_id, which is attribution with no
    return path."""
    _wipe()
    for tool in ("list_tables", "run_sql"):
        decisions.record_decision("converse.tool", "q", ["list_tables", "run_sql", "answer_question"],
                                  chosen=tool, conn_id="914df862", trace_id="tr-chat", outcome="ok")
    decisions.record_decision("converse.tool", "other", ["a", "b"], chosen="a",
                              conn_id="914df862", trace_id="tr-other", outcome="ok")

    assert decisions.attach_run("tr-chat", "inv-chat") == 2
    closed = decisions.mark_outcomes_for_run(inv_id="inv-chat", outcome="rejected")
    assert closed == 2, "a verdict can now reach a conversational turn's picks"

    others = [r for r in decisions.list_decisions(limit=10) if r["trace_id"] == "tr-other"]
    assert [r["inv_id"] for r in others] == [""], "another turn must not be stitched"


def test_attach_run_never_reassigns_an_investigation_it_did_not_open():
    _wipe()
    decisions.record_decision("converse.tool", "q", ["a", "b"], chosen="a",
                              conn_id="c1", trace_id="tr", inv_id="inv-first")
    assert decisions.attach_run("tr", "inv-second") == 0
    assert decisions.list_decisions(limit=5)[0]["inv_id"] == "inv-first"
    assert decisions.attach_run("", "inv-x") == 0
    assert decisions.attach_run("tr", "") == 0


def test_the_falsifier_fires_when_instrumentation_bought_nothing():
    flat = {"converse.tool": {"total": 40, "attributable": 0, "with_probability": 0,
                              "trainable": 40, "outcomes": {"ok": 40}, "discriminating": False}}
    assert summarize(arm_a(flat), flat)["falsifier"]["a1_bought_nothing"] is True

    better = {"converse.tool": {"total": 40, "attributable": 40, "with_probability": 0,
                                "trainable": 40, "outcomes": {"ok": 39, "rejected": 1},
                                "discriminating": True}}
    assert summarize(arm_a(better), better)["falsifier"]["a1_bought_nothing"] is False


def test_an_empty_store_is_inconclusive_not_a_pass():
    """A zero read as a pass is how a guard passes for the wrong reason."""
    s = summarize(arm_a({}), {})
    assert s["inconclusive"] is True
    assert s["falsifier"]["a1_bought_nothing"] is False
    assert set(s["sites_silent"]) == {"ask.route", "framing.definition", "converse.tool"}


def test_the_definition_chooser_is_asked_for_confidence_only_behind_its_flag():
    """The off-arm must ship the identical response model it ships today, or the A/B
    measures the diff around the field instead of the field."""
    from aughor.agent.framing import DefinitionChoice, DefinitionChoiceWithConfidence
    assert set(DefinitionChoice.model_fields) == {"definition"}
    assert set(DefinitionChoiceWithConfidence.model_fields) == {"definition", "confidence"}


def test_the_confidence_flag_declares_an_exit():
    """A flag with no disposition fails CI by design; assert ours is the group that owns
    a prompt change, and that its entry names the corpus block rather than hiding it."""
    from aughor.kernel.flags import EXPERIMENT, flag_disposition
    assert flag_disposition("framing.choice_confidence") == "experiment"
    assert "GRID BLOCKED ON CORPUS" in EXPERIMENT["framing.choice_confidence"]
