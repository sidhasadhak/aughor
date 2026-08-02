"""Flag strategy batch B — the deterministic graduation suite for the data-gated
and invocation-gated queue (plus the REC-U10 byte-equality that flipped
`semantic.contract_live`).

Hermetic: no LLM, no warehouse, no writes; synthetic probe connections throughout.
Scenario names carry the flag they back (``SCENARIO_PREFIX`` is the declared map).
"""
from __future__ import annotations

import pytest

from aughor.evals.evaluator import EvalCase
from aughor.evals.flag_batch_b_receipt import (
    FLAGS, SCENARIO_PREFIX, SCENARIOS, receipt_target,
)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_holds(name):
    """Each invariant, named individually so a failure says which one broke."""
    comparison = SCENARIOS[name]()
    assert comparison.equivalent, (
        f"{name}: expected {comparison.expected!r}, observed {comparison.observed!r}")


def test_every_scenario_declares_an_oracle():
    for name, fn in SCENARIOS.items():
        assert fn().oracle, f"{name} declares no oracle"


def test_every_graduated_flag_has_at_least_one_scenario():
    """A flag with no scenario in the suite is graduating on somebody else's evidence."""
    covered = {n.split("__")[0] for n in SCENARIOS}
    assert set(SCENARIO_PREFIX) == set(FLAGS)
    for flag in FLAGS:
        assert SCENARIO_PREFIX[flag] in covered, f"{flag} has no scenario backing it"


def test_unknown_scenario_is_an_error_not_an_empty_pass():
    obs = receipt_target()(EvalCase(id="x", question="?", expected={"scenario": "nope"}))
    assert obs.error and "nope" in obs.error


def test_batch_b_behaviour_is_unconditional_or_still_default_on():
    """Most of batch B was HARDWIRED 2026-08-02 — those flags are gone and the
    behaviour is permanent. The few that still hold a flag must stay default-on."""
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV

    for flag in FLAGS:
        if flag in FLAG_ENV:
            assert FLAG_DEFAULT.get(flag) is True, flag
        else:
            assert flag not in FLAG_DEFAULT, f"{flag} is hardwired; it must not linger"


def test_the_conversion_landed_as_auto_not_default_on():
    """ask.conversation_context converted to a self-gating guard — its trigger decides
    per turn under Auto-mode; it must NOT be in FLAG_DEFAULT (that would bypass the
    trigger discipline the conversion exists for)."""
    from aughor.kernel.flags import AUTO_ELIGIBLE, CAPABILITY_TRIGGER, FLAG_DEFAULT

    assert "ask.conversation_context" in AUTO_ELIGIBLE
    assert "ask.conversation_context" in CAPABILITY_TRIGGER
    assert "ask.conversation_context" not in FLAG_DEFAULT


def test_federation_planner_stays_an_experiment():
    """The batch's premise-check finding, pinned: the planner auto-federates fresh
    /ask turns, so it must not silently re-enter a graduation queue as
    'invocation-gated'."""
    from aughor.kernel.flags import EXPERIMENT, FLAG_DEFAULT

    assert "federation.planner" in EXPERIMENT
    assert "federation.planner" not in FLAG_DEFAULT
