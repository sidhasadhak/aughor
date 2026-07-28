"""Wave N3 — the deterministic graduation suite for `graph.consolidate`.

Hermetic: every scenario is arithmetic over synthetic finding dicts, so these run without a
warehouse, an LLM, or anything in ``data/``. That is the point — the flag's receipt must not
depend on what happened to be on disk the day it was recorded.
"""
from __future__ import annotations

import pytest

from aughor.evals.consolidation import FLAG, SCENARIOS, consolidation_target
from aughor.evals.evaluator import EvalCase


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_holds(name):
    """Each invariant, named individually so a failure says which one broke."""
    comparison = SCENARIOS[name]()
    assert comparison.equivalent, (
        f"{name}: expected {comparison.expected!r}, observed {comparison.observed!r}")


def test_every_scenario_declares_an_oracle():
    """A comparison whose expectation has no stated source is a hand-written literal
    pretending to be evidence."""
    for name, fn in SCENARIOS.items():
        assert fn().oracle, f"{name} declares no oracle"


def test_the_suite_covers_the_invariants_that_matter():
    """Pinned by name: these are the properties the flag's default rests on, and a
    silent deletion of one would leave the graduation resting on less than it claims."""
    assert {"lossless", "never_picks_a_winner", "budget_respected",
            "unverifiable_evicted_first", "stale_is_kept_not_deleted",
            "flag_off_projection_identical"} <= set(SCENARIOS)


def test_unknown_scenario_is_an_error_not_an_empty_pass():
    """A suite that silently skipped a case it could not resolve would report a pass rate
    over fewer cases than it claims to cover."""
    obs = consolidation_target()(EvalCase(id="x", question="?", expected={"scenario": "nope"}))
    assert obs.error and "nope" in obs.error


def test_the_flag_under_test_is_registered():
    from aughor.kernel.flags import FLAG_ENV

    assert FLAG in FLAG_ENV
