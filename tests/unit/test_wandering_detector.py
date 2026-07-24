"""Wave R3 — the wandering detector.

Two contracts, and the second is the one that keeps this safe to ship:

* **Catch the three shapes.** A repeat, a no-progress streak, and churn are three different
  failures and each is invisible to the counter that catches the others.
* **Never suppress real evidence.** A detector that vetoes a genuinely new query is worse
  than the redundancy it saves — it deletes a finding. Every "must NOT fire" test below is
  load-bearing, especially the repair path, where re-running a failed query is how the fix
  works.
"""
from __future__ import annotations

import pytest

from aughor.agent import wandering as W
from aughor.platform.contracts.execution import QueryResult


def _result(step, sql, rows=None, cols=("a",), error=None, caveats=()):
    rows = [[1]] if rows is None else rows
    return QueryResult(hypothesis_id=step, sql=sql, columns=list(cols), rows=rows,
                       row_count=len(rows), error=error, caveats=list(caveats))


# ── fingerprints ──────────────────────────────────────────────────────────────

def test_formatting_differences_are_the_same_query():
    """The planner re-emits the same intent with different indentation and case
    constantly. A raw string compare would miss most real repeats."""
    a = W.args_fingerprint("SELECT a, b FROM t WHERE x = 1")
    b = W.args_fingerprint("select   a,\n  b\nfrom t\nwhere x = 1;")
    assert a == b


def test_a_different_query_is_a_different_fingerprint():
    assert W.args_fingerprint("SELECT a FROM t") != W.args_fingerprint("SELECT b FROM t")
    assert W.args_fingerprint("SELECT a FROM t WHERE x=1") != W.args_fingerprint("SELECT a FROM t WHERE x=2")


def test_unparseable_sql_falls_back_conservatively():
    """The fallback collapses whitespace and case ONLY. A fingerprint that is too eager
    would veto a genuinely new query."""
    a = W.args_fingerprint("this is not sql at all {{")
    b = W.args_fingerprint("THIS IS   NOT SQL AT ALL {{")
    assert a == b
    assert a != W.args_fingerprint("this is not sql either {{")


def test_empty_sql_has_no_fingerprint():
    assert W.args_fingerprint("") == "" and W.args_fingerprint(None) == ""


def test_the_same_numbers_under_different_headings_are_a_different_answer():
    """A chain that renamed its output did make progress."""
    assert W.result_fingerprint(["revenue"], [[10]]) != W.result_fingerprint(["margin"], [[10]])
    assert W.result_fingerprint(["a"], [[1], [2]]) == W.result_fingerprint(["a"], [[1], [2]])


# ── signal 1: repeat (the pre-dispatch veto) ──────────────────────────────────

def test_a_repeat_is_caught_before_dispatch():
    history = [_result("Q1", "SELECT region, SUM(rev) FROM sales GROUP BY region")]
    v = W.check_before_dispatch("select REGION, sum(REV) from SALES group by REGION", history)
    assert v.wandering and v.kind == "repeat" and v.prior_step == "Q1"
    assert "Q1" in v.detail


def test_a_new_query_is_never_vetoed():
    history = [_result("Q1", "SELECT region FROM sales")]
    assert not W.check_before_dispatch("SELECT product FROM sales", history).wandering


def test_re_running_a_FAILED_query_is_never_vetoed():
    """The load-bearing exclusion. Re-running a query that errored is how a repair WORKS —
    vetoing it would break the repair path outright, turning a recoverable SQL error into
    a permanently unanswered sub-question."""
    history = [_result("Q1", "SELECT bad FROM t", error="no such column: bad")]
    assert not W.check_before_dispatch("SELECT bad FROM t", history).wandering


def test_a_veto_is_not_itself_evidence_of_a_repeat():
    """A veto echoes the prior result verbatim. Counting it would let one veto cascade into
    terminating a healthy run."""
    prior = _result("Q1", "SELECT a FROM t")
    echo = W.veto_result("Q2", "SELECT a FROM t", prior,
                         W.Verdict("repeat", "already run for Q1.", "Q1"))
    assert W.is_veto(echo) and not W.is_veto(prior)
    assert W._usable([prior, echo]) == [prior]


def test_the_veto_result_carries_the_prior_data_not_an_empty_stand_in():
    """A zero-row stand-in would trip every 'suspicious empty result' heuristic we have and
    read downstream as a finding of ABSENCE — a wrong answer, not a saved request."""
    prior = _result("Q1", "SELECT r, v FROM t", rows=[["eu", 10], ["us", 20]], cols=("r", "v"))
    echo = W.veto_result("Q2", "SELECT r, v FROM t", prior,
                         W.Verdict("repeat", "already run for Q1.", "Q1"))
    assert echo.rows == [["eu", 10], ["us", 20]] and echo.row_count == 2
    assert echo.columns == ["r", "v"] and echo.error is None
    assert echo.hypothesis_id == "Q2"                       # attributed to the step that asked
    assert any(c.startswith(W.VETO_MARKER) for c in echo.caveats)


# ── signal 2: no progress (what a repeat counter cannot see) ──────────────────

def test_distinct_queries_with_identical_results_are_no_progress():
    same = [[1]]
    history = [_result(f"Q{i}", f"SELECT c{i} FROM t", rows=same) for i in range(1, 4)]
    v = W.check_progress(history)
    assert v.kind == "no_progress" and "identical" in v.detail


def test_two_agreeing_queries_are_a_coincidence_not_a_pattern():
    """A landscape query and its ORDER BY variant legitimately agree. Two is not evidence."""
    same = [[1]]
    history = [_result(f"Q{i}", f"SELECT c{i} FROM t", rows=same) for i in range(1, 3)]
    assert not W.check_progress(history).wandering


def test_identical_sql_is_reported_as_a_repeat_not_as_no_progress():
    """Same SQL is a different and cheaper story — the pre-dispatch veto owns it."""
    history = [_result(f"Q{i}", "SELECT c FROM t", rows=[[1]]) for i in range(1, 4)]
    assert W.check_progress(history).kind != "no_progress"


def test_progress_breaks_the_streak():
    history = [_result("Q1", "SELECT a FROM t", rows=[[1]]),
               _result("Q2", "SELECT b FROM t", rows=[[1]]),
               _result("Q3", "SELECT c FROM t", rows=[[2]])]
    assert not W.check_progress(history).wandering


# ── signal 3: churn (what a streak counter cannot see) ────────────────────────

def test_many_distinct_queries_collapsing_onto_two_answers_is_churn():
    """The opposite failure: maximum variety, no convergence. No two CONSECUTIVE steps
    match, so a streak counter never fires — this is why churn needs its own signal."""
    history = []
    for i in range(1, 9):
        history.append(_result(f"Q{i}", f"SELECT c{i} FROM t", rows=[[i % 2]]))
    v = W.check_progress(history)
    assert v.kind == "churn" and "distinct" in v.detail


def test_a_run_that_is_actually_covering_ground_is_not_churn():
    history = [_result(f"Q{i}", f"SELECT c{i} FROM t", rows=[[i]]) for i in range(1, 9)]
    assert not W.check_progress(history).wandering


def test_churn_needs_enough_queries_to_mean_anything():
    history = [_result(f"Q{i}", f"SELECT c{i} FROM t", rows=[[1]]) for i in range(1, 3)]
    assert not W.check_progress(history).wandering


# ── termination ───────────────────────────────────────────────────────────────

def test_repeated_vetoes_end_the_wave():
    prior = _result("Q1", "SELECT a FROM t")
    v = W.Verdict("repeat", "already run for Q1.", "Q1")
    history = [prior] + [W.veto_result(f"Q{i}", "SELECT a FROM t", prior, v) for i in range(2, 5)]
    assert W.veto_count(history) == 3
    assert W.should_terminate(history).wandering


def test_a_healthy_run_is_never_terminated():
    history = [_result(f"Q{i}", f"SELECT c{i} FROM t", rows=[[i]]) for i in range(1, 6)]
    assert not W.should_terminate(history).wandering


def test_an_empty_run_is_never_terminated():
    assert not W.should_terminate([]).wandering
    assert not W.check_progress([]).wandering


# ── the wiring ────────────────────────────────────────────────────────────────

def test_the_veto_is_off_by_default(monkeypatch):
    """Off by default — an operator opts into a brake that can skip a query."""
    from aughor.agent import explore

    monkeypatch.delenv("AUGHOR_EXPLORE_WANDERING_DETECTOR", raising=False)
    assert explore._wandering_enabled() is False
    state = {"query_history": [_result("Q1", "SELECT a FROM t")]}
    subq = type("S", (), {"id": "Q2"})()
    assert explore._wandering_veto(state, subq, "SELECT a FROM t") is None


def test_the_veto_fires_when_enabled(monkeypatch):
    from aughor.agent import explore

    monkeypatch.setenv("AUGHOR_EXPLORE_WANDERING_DETECTOR", "1")
    state = {"query_history": [_result("Q1", "SELECT a FROM t", rows=[[7]])]}
    subq = type("S", (), {"id": "Q2"})()
    out = explore._wandering_veto(state, subq, "select A from T")
    assert out is not None and out.rows == [[7]] and out.hypothesis_id == "Q2"


def test_a_detector_error_lets_the_query_run(monkeypatch):
    """Fail-open in the strongest sense. A detector that can suppress real evidence on its
    own bug is worse than the redundancy it saves."""
    from aughor.agent import explore

    monkeypatch.setenv("AUGHOR_EXPLORE_WANDERING_DETECTOR", "1")
    monkeypatch.setattr(W, "check_before_dispatch",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    state = {"query_history": [_result("Q1", "SELECT a FROM t")]}
    subq = type("S", (), {"id": "Q2"})()
    assert explore._wandering_veto(state, subq, "SELECT a FROM t") is None


def test_a_fully_vetoed_step_skips_its_interpret_call():
    """The request the veto actually saves — the DB scan is the cheap half."""
    from aughor.agent.explore import _all_vetoed

    prior = _result("Q1", "SELECT a FROM t")
    v = W.Verdict("repeat", "This query is identical to the one already run for Q1. x", "Q1")
    echo = W.veto_result("Q2", "SELECT a FROM t", prior, v)
    assert _all_vetoed([echo]) == "Q1"


def test_a_step_with_any_fresh_evidence_still_gets_interpreted():
    """All, not any. A step that ran one fresh query and one repeat has new evidence, and
    skipping its narration would lose that."""
    from aughor.agent.explore import _all_vetoed

    prior = _result("Q1", "SELECT a FROM t")
    v = W.Verdict("repeat", "already run for Q1.", "Q1")
    echo = W.veto_result("Q2", "SELECT a FROM t", prior, v)
    fresh = _result("Q2", "SELECT b FROM t")
    assert _all_vetoed([echo, fresh]) == ""


def test_the_stop_is_off_by_default_and_fail_safe(monkeypatch):
    from aughor.agent import explore

    monkeypatch.delenv("AUGHOR_EXPLORE_WANDERING_DETECTOR", raising=False)
    prior = _result("Q1", "SELECT a FROM t")
    v = W.Verdict("repeat", "already run for Q1.", "Q1")
    history = [prior] + [W.veto_result(f"Q{i}", "SELECT a FROM t", prior, v) for i in range(2, 6)]
    assert explore._wandering_stop({"query_history": history}) is False

    monkeypatch.setenv("AUGHOR_EXPLORE_WANDERING_DETECTOR", "1")
    assert explore._wandering_stop({"query_history": history}) is True


@pytest.mark.parametrize("route_fn", ["route_after_wave", "route_after_reason"])
def test_both_routers_honour_the_brake(route_fn, monkeypatch):
    """The sequential path and the parallel wave path each have their own loop; a brake
    wired to only one leaves the other running to the cap."""
    from aughor.agent import explore

    monkeypatch.setenv("AUGHOR_EXPLORE_WANDERING_DETECTOR", "1")
    prior = _result("Q1", "SELECT a FROM t")
    v = W.Verdict("repeat", "already run for Q1.", "Q1")
    history = [prior] + [W.veto_result(f"Q{i}", "SELECT a FROM t", prior, v) for i in range(2, 6)]

    class _SQ:
        def __init__(self, i):
            self.id, self.done, self.depends_on, self.purpose = f"S{i}", False, [], "landscape"

    state = {"query_history": history, "sub_questions": [_SQ(1), _SQ(2)],
             "iteration": 1, "current_subq_idx": 0}
    assert getattr(explore, route_fn)(state) == "synthesize_exploration"
