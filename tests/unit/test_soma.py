"""SOMA candidate-disagreement (3b) — execution-grounded structural-ambiguity detection.

Contract: ask ONLY when candidate readings, when executed, produce materially different results;
the distinct readings' labels become grounded option chips. The suspect filter gates the probe.
"""
from __future__ import annotations

from aughor.agent.soma import (
    CandidateReading, assess_structural_ambiguity, is_structural_suspect,
)


# ── the cheap suspect filter ──────────────────────────────────────────────────

def test_superlative_without_binding_is_suspect():
    assert is_structural_suspect("top products") is True
    assert is_structural_suspect("who are our biggest customers") is True


def test_ambiguous_metric_is_suspect():
    assert is_structural_suspect("what is the average order value") is True


def test_bound_or_plain_question_is_not_suspect():
    assert is_structural_suspect("top 10 customers by revenue") is False     # measure bound
    assert is_structural_suspect("total revenue last month") is False        # plain lookup
    assert is_structural_suspect("") is False


# ── the execution-grounded probe ──────────────────────────────────────────────

def _exec(table):
    def ex(sql):
        return (True, table.get(sql, []), "")
    return ex


def test_divergent_candidates_are_ambiguous_with_grounded_options():
    # two readings of "top product" that return DIFFERENT entities → ambiguous
    cands = [
        CandidateReading("by units sold", "SELECT product ORDER BY units"),
        CandidateReading("by revenue", "SELECT product ORDER BY revenue"),
    ]
    ex = _exec({
        "SELECT product ORDER BY units":   [["gadget"]],
        "SELECT product ORDER BY revenue": [["jewelry"]],
    })
    v = assess_structural_ambiguity("top product", cands, ex)
    assert v.ambiguous and v.n_groups == 2
    assert set(v.options) == {"by units sold", "by revenue"}


def test_agreeing_candidates_are_not_ambiguous():
    # both readings return the SAME result → no real ambiguity, don't ask
    cands = [
        CandidateReading("reading A", "SELECT a"),
        CandidateReading("reading B", "SELECT b"),
    ]
    # same rows in a different ROW order — the signature is row-order-insensitive → one group
    ex = _exec({"SELECT a": [["x", 1], ["y", 2]], "SELECT b": [["y", 2], ["x", 1]]})
    v = assess_structural_ambiguity("q", cands, ex)
    assert v.ambiguous is False and v.n_groups == 1


def test_errored_candidates_are_dropped():
    def ex(sql):
        if "good" in sql:
            return (True, [["ok"]], "")
        return (False, [], "boom")
    cands = [CandidateReading("a", "good"), CandidateReading("b", "bad")]
    # only one candidate survives → not ambiguous
    assert assess_structural_ambiguity("q", cands, ex).ambiguous is False


def test_to_event_shape():
    cands = [CandidateReading("u", "su"), CandidateReading("r", "sr")]
    ex = _exec({"su": [["a"]], "sr": [["b"]]})
    ev = assess_structural_ambiguity("q", cands, ex).to_event()
    assert ev["source"] == "structural" and set(ev["options"]) == {"u", "r"}
    assert set(ev) >= {"question", "options", "source", "reason"}
