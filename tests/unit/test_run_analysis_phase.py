"""Structural guards for the ADA run_analysis_phase refactor (C2).

These would have caught the decorator-misplacement regression where a stray
@node_span landed on `class _PhaseRun`, turning it into a (state)-taking wrapper so
every phase's `return _PhaseRun(ok=True, ...)` raised "missing 'state'" at runtime —
something imports and unit tests passed right over."""
import inspect

from aughor.agent import investigate as I


def test_phaserun_is_a_class_not_a_wrapped_node():
    assert isinstance(I._PhaseRun, type), "_PhaseRun must be a plain class, not a decorated node"
    r = I._PhaseRun(ok=True, results=[1, 2], results_text="x")
    assert r.ok is True and r.results == [1, 2] and r.interpretation is None
    e = I._PhaseRun(ok=False, error_phase={"phase_id": "x"})
    assert e.ok is False and e.error_phase == {"phase_id": "x"}


def test_run_analysis_phase_signature():
    assert inspect.isfunction(I.run_analysis_phase)
    params = inspect.signature(I.run_analysis_phase).parameters
    for p in ("phase_id", "title", "emoji", "plan_system", "plan_user",
              "interpret_system", "interpret_user_fn", "cap"):
        assert p in params, f"run_analysis_phase missing param {p}"


def test_all_ada_phase_nodes_present_and_callable():
    for fn in ("ada_intake", "ada_baseline", "ada_decompose",
               "ada_dimensional", "ada_behavioral", "ada_cross_section"):
        assert callable(getattr(I, fn)), f"{fn} missing/not callable"
