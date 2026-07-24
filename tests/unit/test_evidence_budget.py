"""Wave R3 — fresh-full / stale-stub evidence rendering.

Two policies with different risk, tested to different standards:

* **dedup is lossless** — the identical table is still in the block, once. Its tests prove
  it only ever collapses a genuine duplicate.
* **stubbing drops rows**, so its tests are mostly about what it must NOT drop: the row
  count (a head mistaken for the whole table is a wrong claim about coverage), the stats,
  the SQL, and anything belonging to a hypothesis that was never scored.

Both must be byte-identical when off, and on a small block, and when anything goes wrong.
"""
from __future__ import annotations

import pytest

from aughor.agent import evidence_budget as EB
from aughor.agent.nodes import _format_full_evidence
from aughor.agent.state import Hypothesis
from aughor.platform.contracts.execution import QueryResult
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


# ── the stub keeps what may be cited ──────────────────────────────────────────

def test_the_stub_keeps_sql_columns_stats_and_a_head():
    r = _result("H1", "SELECT i, segment, value FROM sales", n_rows=40)
    out = EB.stub(r)
    assert "SELECT i, segment, value FROM sales" in out       # provenance
    assert "segment" in out                                   # column names
    assert "seg0" in out and "seg3" in out                    # a real head
    assert "seg29" not in out                                 # the tail is gone


def test_the_stub_states_the_true_row_count_and_what_it_omitted():
    """A head mistaken for the whole table is not a saved token, it is a wrong claim about
    coverage — 'the top 4 segments' when there were 40."""
    out = EB.stub(_result("H1", "SELECT * FROM t", n_rows=40))
    assert "Rows returned: 40" in out
    assert "36 more rows" in out


def test_the_stub_keeps_every_statistical_finding():
    """The stats lines ARE the grounded interpretations — dropping them would drop the
    numbers the narrator is most likely to cite."""
    from aughor.agent.state import StatResult

    r = _result("H1", "SELECT * FROM t")
    r = QueryResult(**{**r.model_dump(),
                       "stats": [StatResult(type="outlier", interpretation="EU is 3.2σ above",
                                            is_significant=True, sigma=3.2)]})
    out = EB.stub(r)
    assert "STATISTICAL ANALYSIS" in out and "EU is 3.2σ above" in out and "3.2σ" in out


def test_a_stub_is_smaller_than_the_full_render():
    r = _result("H1", "SELECT * FROM t", n_rows=40)
    assert len(EB.stub(r)) < len(format_result_for_llm(r))


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


# ── stubbing only touches what was actually interpreted ───────────────────────

def test_only_a_scored_hypothesis_goes_stale():
    """An unscored result has nothing else in the prompt carrying its meaning."""
    parts, info = EB.render_history(
        [_result("H1", "SELECT a FROM t"), _result("H2", "SELECT b FROM t")],
        full_renderer=format_result_for_llm, scored_steps={"H1"}, stub_scored=True)
    assert info["stubbed"] == 1 and info["full"] == 1
    assert "seg29" not in parts[0] and "seg29" in parts[1]


def test_an_unattributed_result_is_always_rendered_full():
    parts, info = EB.render_history(
        [_result("", "SELECT a FROM t")], full_renderer=format_result_for_llm,
        scored_steps={"H1"}, stub_scored=True)
    assert info["stubbed"] == 0 and "seg29" in parts[0]


def test_an_errored_result_is_never_stubbed():
    parts, info = EB.render_history(
        [_result("H1", "SELECT a FROM t", error="boom")],
        full_renderer=format_result_for_llm, scored_steps={"H1"}, stub_scored=True)
    assert info["stubbed"] == 0 and "boom" in parts[0]


# ── the wiring: byte-identical unless asked, and on a big enough block ────────

def test_synthesis_evidence_is_byte_identical_with_no_flags(monkeypatch):
    for var in ("AUGHOR_ADA_EVIDENCE_DEDUP", "AUGHOR_ADA_EVIDENCE_STUBS"):
        monkeypatch.delenv(var, raising=False)
    history = _big_history()
    hyps = [_hyp(f"H{i}") for i in range(1, 13)]
    out = _format_full_evidence(history, hyps)
    assert out.count("seg29") == len(history)            # every table rendered in full


def test_a_small_block_is_left_alone_even_with_the_flags_on(monkeypatch):
    """Safe direction: a block this size is not what strains a window."""
    monkeypatch.setenv("AUGHOR_ADA_EVIDENCE_STUBS", "1")
    history = [_result("H1", "SELECT a FROM t", n_rows=3)]
    assert sum(len(format_result_for_llm(r)) for r in history) < EB.MIN_BLOCK_CHARS
    out = _format_full_evidence(history, [_hyp("H1")])
    assert out == _format_full_evidence(history, [_hyp("H1")])
    assert "seg2" in out and "already interpreted" not in out


def test_stubbing_shrinks_a_big_block_and_keeps_every_section(monkeypatch):
    monkeypatch.setenv("AUGHOR_ADA_EVIDENCE_STUBS", "1")
    history = _big_history()
    hyps = [_hyp(f"H{i}") for i in range(1, 13)]
    before = _format_full_evidence(history, [Hypothesis(id=h.id, description=h.description)
                                             for h in hyps])
    after = _format_full_evidence(history, hyps)
    assert len(after) < len(before)
    for h in hyps:
        assert f"=== {h.id} EVIDENCE" in after           # no section disappears
    assert "Rows returned: 40" in after                  # coverage still stated


def test_an_unscored_hypothesis_keeps_its_full_evidence_in_a_big_block(monkeypatch):
    """The mixed case: one hypothesis scored, one not. Only the scored one goes stale."""
    monkeypatch.setenv("AUGHOR_ADA_EVIDENCE_STUBS", "1")
    history = _big_history()
    hyps = [_hyp("H1")] + [Hypothesis(id=f"H{i}", description="d") for i in range(2, 13)]
    after = _format_full_evidence(history, hyps)
    h1 = after.split("=== H1 EVIDENCE")[1].split("=== H2 EVIDENCE")[0]
    h2 = after.split("=== H2 EVIDENCE")[1].split("=== H3 EVIDENCE")[0]
    assert "seg29" not in h1 and "seg29" in h2


def test_dedup_sees_across_hypothesis_sections(monkeypatch):
    """A repeat spread across two sections is still a repeat; a per-section renderer would
    miss exactly those."""
    monkeypatch.setenv("AUGHOR_ADA_EVIDENCE_DEDUP", "1")
    history = _big_history() + [_result("H6", "SELECT i, segment, value FROM t1_0")]
    hyps = [_hyp(f"H{i}") for i in range(1, 13)]
    out = _format_full_evidence(history, hyps)
    assert "identical to the query already shown for H1" in out


def test_a_policy_error_falls_back_to_rendering_everything_full(monkeypatch):
    """Synthesis is where the answer is written. A helper that can raise here loses a whole
    investigation to save some tokens."""
    monkeypatch.setenv("AUGHOR_ADA_EVIDENCE_STUBS", "1")
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
