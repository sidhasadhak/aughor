"""Early-stop on convergence (2026-06-26).

When the metric reads statistically uniform across several dimensions, the remaining
segment drills only re-confirm the flat baseline — they cost LLM+SQL round-trips and
add no signal (#3 adaptivity, #13 redundancy). route_after_reason short-circuits to
synthesis once enough dimensions have converged AND the next step is just another drill.
See aughor/agent/explore.py.
"""
from aughor.agent.explore import _should_early_stop, route_after_reason, _UNIFORM_CONVERGENCE
from aughor.agent.state import QueryResult, SubQuestion, StatResult


def _uniform_qr(hid):
    return QueryResult(
        hypothesis_id=hid, sql="SELECT 1", columns=["a"], rows=[[1]], row_count=1,
        stats=[StatResult(type="uniformity", interpretation="UNIFORM / NO SIGNAL", is_significant=False)],
    )


def _sq(id, purpose):
    return SubQuestion(id=id, purpose=purpose, question=f"q {id}", expected_output="agg")


def _state(n_uniform, next_purpose, idx=3, n_planned=6):
    return {
        "query_history": [_uniform_qr(f"Q{i}") for i in range(n_uniform)],
        "sub_questions": [_sq(f"Q{i+1}", next_purpose if i == idx else "relationship")
                          for i in range(n_planned)],
        "current_subq_idx": idx,
        "iteration": idx,
    }


def test_stops_once_converged_and_next_is_a_drill():
    st = _state(n_uniform=_UNIFORM_CONVERGENCE, next_purpose="drill_down")
    assert _should_early_stop(st) is True
    assert route_after_reason(st) == "synthesize_exploration"


def test_does_not_stop_below_convergence_threshold():
    st = _state(n_uniform=_UNIFORM_CONVERGENCE - 1, next_purpose="drill_down")
    assert _should_early_stop(st) is False
    assert route_after_reason(st) == "plan_and_execute_subq"


def test_never_skips_a_synthesis_step():
    # Even fully converged, a wrap-up/synthesis sub-question must still run.
    st = _state(n_uniform=_UNIFORM_CONVERGENCE + 2, next_purpose="synthesis")
    assert _should_early_stop(st) is False


def test_no_uniformity_means_normal_routing():
    st = {
        "query_history": [],
        "sub_questions": [_sq("Q1", "landscape"), _sq("Q2", "drill_down")],
        "current_subq_idx": 1,
        "iteration": 1,
    }
    assert route_after_reason(st) == "plan_and_execute_subq"
