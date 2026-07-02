"""Unit tests for the flag-gated parallel wave executor in explore mode.

The parallel path (`explore.parallel_subq`) fans out READY sub-questions concurrently over
ContextThreadPoolExecutor and reduces through the existing operator.add state. These tests pin the
five guardrails from docs/PARALLEL_MULTIAGENT_GROUNDWORK.md §5: budget-abort, determinism/ordering,
failure isolation, correct dependency waves, and the flag gate (byte-identical when off).
"""
from __future__ import annotations

import os
import time

import pytest

import aughor.agent.explore as ex
from aughor.agent.state import (
    QueryResult,
    ReasoningOutput,
    SubQuestion,
    SubQuestionAnswer,
)
from aughor.kernel.metering import BudgetExceeded


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeConn:
    """A do-nothing connection whose make_reader() returns a fresh clone (mirrors the real
    per-thread-reader contract) so the wave code can call it exactly as it would a real conn."""

    dialect = "duckdb"

    def __init__(self):
        self.reader_count = 0

    def make_reader(self):
        self.reader_count += 1
        return _FakeConn()


def _sq(id, purpose="drill_down", depends_on=None):
    return SubQuestion(
        id=id, purpose=purpose, depends_on=depends_on or [],
        question=f"question {id}", expected_output=f"expected {id}",
    )


def _install_fast_cores(monkeypatch, *, sleep=0.0, fail_ids=(), budget_ids=(), refinements=None,
                        promotions=None):
    """Stub the three per-sub-question cores so the wave logic is exercised without an LLM/DB.
    - sleep: per-branch work time (to prove concurrency by wall-clock)
    - fail_ids: raise a plain Exception (→ isolated as inconclusive)
    - budget_ids: raise BudgetExceeded (→ must abort the whole wave)
    - refinements: {subq_id: refinement text}
    - promotions: {subq_id: SubQuestion to promote}
    """
    refinements = refinements or {}
    promotions = promotions or {}

    def fake_scan(subq, schema, conn):
        return ""

    def fake_execute(state, subq, prior_answers, conn, portrait=None):
        if sleep:
            time.sleep(sleep)
        if subq.id in budget_ids:
            raise BudgetExceeded("token budget (test)")
        if subq.id in fail_ids:
            raise RuntimeError(f"boom {subq.id}")
        r = QueryResult(hypothesis_id=subq.id, sql=f"SELECT 1 -- {subq.id}",
                        columns=["c"], rows=[[1]], row_count=1, error=None)
        return [r], [], ["join_value_domain"]

    def fake_reason(state, subq, subq_results, prior_answers):
        obj = ReasoningOutput(
            answer=f"answer {subq.id}", insight=f"insight {subq.id}",
            refinement=refinements.get(subq.id),
            new_sub_question=promotions.get(subq.id),
        )
        ans = SubQuestionAnswer(
            subq_id=subq.id, question=subq.question, purpose=subq.purpose,
            sql=f"SELECT 1 -- {subq.id}", columns=["c"], rows=[[1]], row_count=1, error=None,
            answer=obj.answer, insight=obj.insight, refinement=obj.refinement,
        )
        return ans, obj

    monkeypatch.setattr(ex, "_scan_one_subq", fake_scan)
    monkeypatch.setattr(ex, "_execute_one_subq", fake_execute)
    monkeypatch.setattr(ex, "_reason_one_subq", fake_reason)


# ── _ready_subqs (dependency waves) ────────────────────────────────────────────

def test_ready_subqs_respects_depends_on():
    sqs = [_sq("Q1", "landscape"), _sq("Q2", depends_on=["Q1"]), _sq("Q3", depends_on=["Q1"])]
    # Nothing done → only Q1 (no deps) is ready.
    assert [s.id for s in ex._ready_subqs(sqs, set())] == ["Q1"]
    # Q1 done → Q2 and Q3 (both depend only on Q1) become ready together.
    assert [s.id for s in ex._ready_subqs(sqs, {"Q1"})] == ["Q2", "Q3"]


def test_ready_subqs_skips_done_and_dangling():
    sqs = [_sq("Q1", "landscape"), _sq("Q2", depends_on=["Q1"]), _sq("Q3", depends_on=["QX"])]
    done_q1 = SubQuestion(**{**sqs[0].model_dump(), "done": True})
    sqs2 = [done_q1, sqs[1], sqs[2]]
    ready = ex._ready_subqs(sqs2, {"Q1"})
    # Q1 done (skipped), Q2 ready, Q3 depends on a non-existent QX (never ready).
    assert [s.id for s in ready] == ["Q2"]


# ── _apply_wave_results (chain mutation) ───────────────────────────────────────

def _branch(subq_id, refinement=None, promotion=None):
    obj = ReasoningOutput(answer=f"a{subq_id}", insight=f"i{subq_id}",
                          refinement=refinement, new_sub_question=promotion)
    ans = SubQuestionAnswer(subq_id=subq_id, question="q", purpose="drill_down", sql="",
                            columns=[], rows=[], row_count=0, error=None,
                            answer=obj.answer, insight=obj.insight, refinement=refinement)
    return ex._BranchOut(subq_id, ans, obj, [], [], [])


def test_apply_wave_marks_done_and_injects_refinement_into_dependents():
    sqs = [_sq("Q1", "landscape"), _sq("Q2", depends_on=["Q1"]), _sq("Q3", depends_on=["Q1"])]
    # Q1 completes with a refinement; Q2/Q3 depend on Q1 and are still pending.
    updated = ex._apply_wave_results(sqs, [_branch("Q1", refinement="use net revenue")])
    by = {s.id: s for s in updated}
    assert by["Q1"].done is True
    # The refinement is injected into BOTH dependents (not just "the next one").
    assert "use net revenue" in by["Q2"].expected_output
    assert "use net revenue" in by["Q3"].expected_output
    assert by["Q2"].done is False


def test_apply_wave_promotes_new_subquestion_with_unique_id():
    sqs = [_sq("Q1", "landscape")]
    dup = SubQuestion(id="Q1", purpose="drill_down", question="promoted", expected_output="x")
    updated = ex._apply_wave_results(sqs, [_branch("Q1", promotion=dup)])
    ids = [s.id for s in updated]
    # The promoted sub-question collided on "Q1"; it must be re-minted to a unique id.
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert any(s.question == "promoted" for s in updated)


# ── plan_and_execute_wave (the node) ───────────────────────────────────────────

def _state(sqs, **over):
    st = {
        "sub_questions": sqs, "subq_answers": [], "query_history": [], "pitfalls": [],
        "verification_checks": [], "iteration": 0, "schema_context": "TABLE: t",
        "question": "q", "connection_id": "c", "scope_schema": "", "data_catalog": "",
        "subq_data_portrait": {}, "analysis_ledger": "", "events_context": "",
    }
    st.update(over)
    return st


def test_wave_runs_ready_set_and_returns_each_answer_once(monkeypatch):
    _install_fast_cores(monkeypatch)
    sqs = [_sq("Q1", "landscape"), _sq("Q2", depends_on=["Q1"]), _sq("Q3", depends_on=["Q1"])]
    out = ex.plan_and_execute_wave(_state(sqs), _FakeConn())
    # First wave: only Q1 is ready.
    assert [a.subq_id for a in out["subq_answers"]] == ["Q1"]
    assert out["iteration"] == 1
    # query_history / verification_checks accumulate via operator.add (returned as this wave's slice).
    assert len(out["query_history"]) == 1
    assert "join_value_domain" in out["verification_checks"]


def test_wave_is_concurrent(monkeypatch):
    _install_fast_cores(monkeypatch, sleep=0.3)
    # Three independent sub-questions, all ready at once → should run in ~1×, not ~3×.
    sqs = [_sq("Q1", "landscape", depends_on=[]),
           _sq("Q2", "landscape", depends_on=[]),
           _sq("Q3", "landscape", depends_on=[])]
    t0 = time.time()
    out = ex.plan_and_execute_wave(_state(sqs), _FakeConn())
    dt = time.time() - t0
    assert len(out["subq_answers"]) == 3
    assert dt < 0.9, f"expected concurrent (~0.3s), got {dt:.2f}s — branches serialized"


def test_wave_deterministic_order_by_planned_index(monkeypatch):
    # Later-planned sub-questions finish FIRST (inverse sleep), but the merged answers must be
    # ordered by planned position, never completion order.
    order_sleep = {"Q1": 0.30, "Q2": 0.15, "Q3": 0.01}

    def fake_scan(subq, schema, conn):
        return ""

    def fake_execute(state, subq, prior_answers, conn, portrait=None):
        time.sleep(order_sleep[subq.id])
        r = QueryResult(hypothesis_id=subq.id, sql="s", columns=["c"], rows=[[1]], row_count=1, error=None)
        return [r], [], []

    def fake_reason(state, subq, subq_results, prior_answers):
        obj = ReasoningOutput(answer="a", insight="i", refinement=None)
        ans = SubQuestionAnswer(subq_id=subq.id, question="q", purpose="landscape", sql="",
                                columns=[], rows=[], row_count=0, error=None,
                                answer="a", insight="i", refinement=None)
        return ans, obj

    monkeypatch.setattr(ex, "_scan_one_subq", fake_scan)
    monkeypatch.setattr(ex, "_execute_one_subq", fake_execute)
    monkeypatch.setattr(ex, "_reason_one_subq", fake_reason)

    sqs = [_sq("Q1", "landscape"), _sq("Q2", "landscape"), _sq("Q3", "landscape")]
    out = ex.plan_and_execute_wave(_state(sqs), _FakeConn())
    assert [a.subq_id for a in out["subq_answers"]] == ["Q1", "Q2", "Q3"]


def test_wave_isolates_a_failing_branch(monkeypatch):
    _install_fast_cores(monkeypatch, fail_ids={"Q2"})
    sqs = [_sq("Q1", "landscape"), _sq("Q2", "landscape"), _sq("Q3", "landscape")]
    out = ex.plan_and_execute_wave(_state(sqs), _FakeConn())
    answers = {a.subq_id: a for a in out["subq_answers"]}
    # All three still produce an answer; the failing one is recorded as an errored/inconclusive answer.
    assert set(answers) == {"Q1", "Q2", "Q3"}
    assert answers["Q2"].error is not None
    assert answers["Q1"].error is None and answers["Q3"].error is None


def test_wave_budget_exceeded_aborts(monkeypatch):
    _install_fast_cores(monkeypatch, budget_ids={"Q2"})
    sqs = [_sq("Q1", "landscape"), _sq("Q2", "landscape"), _sq("Q3", "landscape")]
    with pytest.raises(BudgetExceeded):
        ex.plan_and_execute_wave(_state(sqs), _FakeConn())


def test_wave_single_ready_runs_inline(monkeypatch):
    # width==1 path: a single ready sub-question runs on the shared conn (no clone).
    _install_fast_cores(monkeypatch)
    conn = _FakeConn()
    sqs = [_sq("Q1", "landscape")]
    out = ex.plan_and_execute_wave(_state(sqs), conn)
    assert [a.subq_id for a in out["subq_answers"]] == ["Q1"]
    assert conn.reader_count == 0  # inline path never cloned a reader


def test_wave_empty_ready_returns_noop(monkeypatch):
    _install_fast_cores(monkeypatch)
    done = SubQuestion(**{**_sq("Q1").model_dump(), "done": True})
    out = ex.plan_and_execute_wave(_state([done], subq_answers=[]), _FakeConn())
    assert out == {}


# ── route_after_wave ───────────────────────────────────────────────────────────

def test_route_after_wave_loops_then_synthesizes():
    sqs = [SubQuestion(**{**_sq("Q1", "landscape").model_dump(), "done": True}),
           _sq("Q2", depends_on=["Q1"])]
    # Q2 is ready (Q1 done) and under the cap → loop for another wave.
    assert ex.route_after_wave(_state(sqs, iteration=1)) == "plan_and_execute_wave"
    # All done → synthesize.
    all_done = [SubQuestion(**{**s.model_dump(), "done": True}) for s in sqs]
    assert ex.route_after_wave(_state(all_done, iteration=2)) == "synthesize_exploration"


def test_route_after_wave_iteration_cap():
    sqs = [SubQuestion(**{**_sq("Q1", "landscape").model_dump(), "done": True}),
           _sq("Q2", depends_on=["Q1"])]
    over = _state(sqs, iteration=ex.MAX_SUBQ + 1)
    assert ex.route_after_wave(over) == "synthesize_exploration"


# ── The flag gate ──────────────────────────────────────────────────────────────

def _explore_nodes(flag: str | None):
    import duckdb
    from aughor.db.connection import DuckDBConnection
    from aughor.agent.graph import build_graph_generic
    if flag:
        os.environ["AUGHOR_EXPLORE_PARALLEL"] = flag
    else:
        os.environ.pop("AUGHOR_EXPLORE_PARALLEL", None)
    try:
        db = DuckDBConnection.__new__(DuckDBConnection)
        db._conn = duckdb.connect(":memory:")
        db._path = None
        db._connection_id = "t"
        g = build_graph_generic(db)
        return set(g.get_graph().nodes.keys())
    finally:
        os.environ.pop("AUGHOR_EXPLORE_PARALLEL", None)


def test_flag_off_uses_sequential_nodes():
    nodes = _explore_nodes(None)
    assert "plan_and_execute_subq" in nodes
    assert "reason_over_result" in nodes
    assert "plan_and_execute_wave" not in nodes


def test_flag_on_uses_wave_node():
    nodes = _explore_nodes("1")
    assert "plan_and_execute_wave" in nodes
    assert "plan_and_execute_subq" not in nodes
    assert "reason_over_result" not in nodes
