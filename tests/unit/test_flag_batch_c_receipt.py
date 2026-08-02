"""Flag strategy batch C — the deterministic graduation suite for the Knowledge-Graph
and connection-birth bundles, plus the last two migration flips.

Hermetic: no LLM, no warehouse, no writes; synthetic probe connections throughout.
"""
from __future__ import annotations

import pytest

from aughor.evals.evaluator import EvalCase
from aughor.evals.flag_batch_c_receipt import (
    FLAGS, SCENARIO_PREFIX, SCENARIOS, receipt_target,
)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_holds(name):
    comparison = SCENARIOS[name]()
    assert comparison.equivalent, (
        f"{name}: expected {comparison.expected!r}, observed {comparison.observed!r}")


def test_every_scenario_declares_an_oracle():
    for name, fn in SCENARIOS.items():
        assert fn().oracle, f"{name} declares no oracle"


def test_every_graduated_flag_has_at_least_one_scenario():
    covered = {n.split("__")[0] for n in SCENARIOS}
    assert set(SCENARIO_PREFIX) == set(FLAGS)
    for flag in FLAGS:
        assert SCENARIO_PREFIX[flag] in covered, f"{flag} has no scenario backing it"


def test_unknown_scenario_is_an_error_not_an_empty_pass():
    obs = receipt_target()(EvalCase(id="x", question="?", expected={"scenario": "nope"}))
    assert obs.error and "nope" in obs.error


def test_batch_c_behaviour_is_unconditional_or_still_default_on():
    """Batch C's graph and birth bundles were HARDWIRED 2026-08-02 — their flags are
    gone and the behaviour is permanent. The two migration flips still hold flags
    (they owe a legacy-path deletion first), and those must stay default-on."""
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV

    for flag in FLAGS:
        if flag in FLAG_ENV:
            assert FLAG_DEFAULT.get(flag) is True, flag
        else:
            assert flag not in FLAG_DEFAULT, f"{flag} is deleted; it must not linger"


def test_the_queue_and_migrations_are_empty():
    """The strategy's terminal state: every flag is graduated, auto, an opt-in, an
    experiment, or in the performance profile. A new queued/migration flag must
    declare itself with its exit, which these dicts (and the partition test) enforce."""
    from aughor.kernel.flags import GRADUATION_QUEUE, MIGRATION

    assert GRADUATION_QUEUE == {}
    assert MIGRATION == {}
