"""Flag strategy batch A — the deterministic graduation suite for nine flags.

Hermetic: no LLM, no warehouse; monitor scenarios run against an in-memory stub DB
and nothing writes outside throwaway objects. Each scenario name carries the flag it
backs (``<flag with dots as _>__<claim>``), so a failure names the graduation it
undermines.
"""
from __future__ import annotations

import pytest

from aughor.evals.evaluator import EvalCase
from aughor.evals.flag_batch_a_receipt import (
    FLAGS, SCENARIO_PREFIX, SCENARIOS, receipt_target,
)


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


def test_every_graduated_flag_has_at_least_one_scenario():
    """The batch's contract: a flag with no scenario in the suite is graduating on
    somebody else's evidence. SCENARIO_PREFIX is the declared flag→cases map."""
    covered = {n.split("__")[0] for n in SCENARIOS}
    assert set(SCENARIO_PREFIX) == set(FLAGS)
    for flag in FLAGS:
        assert SCENARIO_PREFIX[flag] in covered, f"{flag} has no scenario backing it"


def test_unknown_scenario_is_an_error_not_an_empty_pass():
    """A suite that silently skipped a case it could not resolve would report a pass
    rate over fewer cases than it claims to cover."""
    obs = receipt_target()(EvalCase(id="x", question="?", expected={"scenario": "nope"}))
    assert obs.error and "nope" in obs.error


def test_every_flag_this_suite_backed_stayed_deleted():
    """Hardwired by flag endgame Wave 2 (2026-08-06). The registry must stay empty
    of every one of them — a re-registration would be the drift the endgame ended."""
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV

    for flag in FLAGS:
        assert flag not in FLAG_ENV, flag
        assert flag not in FLAG_DEFAULT, flag
