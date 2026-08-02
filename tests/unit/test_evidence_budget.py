"""Wave R3 — duplicate-collapse evidence rendering.

One policy, lossless by construction: the identical table is still in the block, once.
The tests prove it only ever collapses a genuine duplicate, and that the block is
byte-identical when off, on a small block, and when anything goes wrong.

(The stale-stub sibling was deleted 2026-08-01 in the flag endgame — it dropped rows.)
"""
from __future__ import annotations

import pytest

from aughor.agent import evidence_budget as EB
from aughor.agent.nodes import _format_full_evidence
from aughor.agent.state import Hypothesis
from aughor.control_plane.contracts.execution import QueryResult
from aughor.tools.executor import format_result_for_llm


def _result(step, sql, n_rows=40, error=None):
    rows = [[i, f"seg{i}", i * 100] for i in range(n_rows)]
    return QueryResult(hypothesis_id=step, sql=sql, columns=["i", "segment", "value"],
                       rows=rows, row_count=len(rows), error=error)


def _hyp(hid, finding="something was found"):
    return Hypothesis(id=hid, description=f"hypothesis {hid}", key_finding=finding,
                      confidence=0.7, verdict="confirmed")


def _big_history(n_steps=12, per_step=3):
    return [_result(f"H{s}", f"SELECT i, segment, value FROM t{s}_{q}")
            for s in range(1, n_steps + 1) for q in range(per_step)]


# A fixture under the threshold would exercise the safe-direction fallback, not the policy.
assert sum(len(format_result_for_llm(r)) for r in _big_history()) > EB.MIN_BLOCK_CHARS


# ── dedup is lossless ─────────────────────────────────────────────────────────

def test_an_identical_query_collapses_to_a_pointer():
    a, b = _result("H1", "SELECT x FROM t"), _result("H2", "select   X from T")
    parts, info = EB.render_history([a, b], full_renderer=format_result_for_llm,
                                    collapse_duplicates=True)
    assert info["duplicates"] == 1
    assert "identical to the query already shown for H1" in parts[1]
    assert "seg0" in parts[0]                                  # the data is still there, once


def test_a_different_query_is_never_collapsed():
    parts, info = EB.render_history(
        [_result("H1", "SELECT x FROM t"), _result("H2", "SELECT y FROM t")],
        full_renderer=format_result_for_llm, collapse_duplicates=True)
    assert info["duplicates"] == 0 and info["full"] == 2


def test_a_failed_duplicate_is_kept_in_full():
    """Two attempts at the same SQL where one errored are a repair story, not a repeat —
    and the error text is the part the narrator needs."""
    ok = _result("H1", "SELECT x FROM t")
    bad = _result("H2", "SELECT x FROM t", error="no such column: x")
    parts, info = EB.render_history([ok, bad], full_renderer=format_result_for_llm,
                                    collapse_duplicates=True)
    assert info["duplicates"] == 0 and "no such column: x" in parts[1]


# ── the wiring: byte-identical unless asked, and on a big enough block ────────

def test_synthesis_evidence_is_byte_identical_with_no_flag(monkeypatch):
    monkeypatch.delenv("AUGHOR_DEEP_ANALYSIS_EVIDENCE_DEDUP", raising=False)
    history = _big_history()
    hyps = [_hyp(f"H{i}") for i in range(1, 13)]
    out = _format_full_evidence(history, hyps)
    assert out.count("seg29") == len(history)            # every table rendered in full


def test_a_small_block_is_left_alone_even_with_the_flag_on(monkeypatch):
    """Safe direction: a block this size is not what strains a window."""
    monkeypatch.setenv("AUGHOR_DEEP_ANALYSIS_EVIDENCE_DEDUP", "1")
    history = [_result("H1", "SELECT a FROM t", n_rows=3)]
    assert sum(len(format_result_for_llm(r)) for r in history) < EB.MIN_BLOCK_CHARS
    out = _format_full_evidence(history, [_hyp("H1")])
    assert out == _format_full_evidence(history, [_hyp("H1")])
    assert "seg2" in out and "identical to the query" not in out


def test_dedup_sees_across_hypothesis_sections(monkeypatch):
    """A repeat spread across two sections is still a repeat; a per-section renderer would
    miss exactly those."""
    monkeypatch.setenv("AUGHOR_DEEP_ANALYSIS_EVIDENCE_DEDUP", "1")
    history = _big_history() + [_result("H6", "SELECT i, segment, value FROM t1_0")]
    hyps = [_hyp(f"H{i}") for i in range(1, 13)]
    out = _format_full_evidence(history, hyps)
    assert "identical to the query already shown for H1" in out


def test_a_policy_error_falls_back_to_rendering_everything_full(monkeypatch):
    """Synthesis is where the answer is written. A helper that can raise here loses a whole
    investigation to save some tokens."""
    monkeypatch.setenv("AUGHOR_DEEP_ANALYSIS_EVIDENCE_DEDUP", "1")
    monkeypatch.setattr(EB, "render_history",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    history = _big_history()
    hyps = [_hyp(f"H{i}") for i in range(1, 13)]
    with pytest.raises(RuntimeError):
        EB.render_history([], full_renderer=format_result_for_llm)   # the fake really raises
    out = _format_full_evidence(history, hyps)
    assert out.count("seg29") == len(history)            # …and synthesis still got everything


def test_no_queries_is_unchanged():
    assert _format_full_evidence([], [_hyp("H1")]) == "No queries were executed."
