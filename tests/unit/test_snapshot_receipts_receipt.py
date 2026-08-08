"""Flag strategy batch D — the deterministic graduation suite for `snapshot_receipts`.

Hermetic: throwaway DuckDB files, no LLM, no warehouse.
"""
from __future__ import annotations

import pytest

from aughor.evals.evaluator import EvalCase
from aughor.evals.snapshot_receipts_receipt import FLAG, SCENARIOS, receipt_target


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_holds(name):
    comparison = SCENARIOS[name]()
    assert comparison.equivalent, (
        f"{name}: expected {comparison.expected!r}, observed {comparison.observed!r}")


def test_every_scenario_declares_an_oracle():
    for name, fn in SCENARIOS.items():
        assert fn().oracle, f"{name} declares no oracle"


def test_the_suite_covers_the_claim_the_graduation_rests_on():
    assert {"off_stamps_nothing_on_stamps_a_valid_token",
            "the_token_pins_the_data_and_moves_when_it_moves",
            "a_broken_probe_never_blocks_the_emit",
            "the_probe_clears_the_e1_cost_bar",
            "one_pinning_mechanism_not_two"} <= set(SCENARIOS)


def test_unknown_scenario_is_an_error_not_an_empty_pass():
    obs = receipt_target()(EvalCase(id="x", question="?", expected={"scenario": "nope"}))
    assert obs.error and "nope" in obs.error


def test_the_flag_stayed_deleted():
    """Hardwired by flag endgame Wave 2 (2026-08-06); the registry must stay empty of it."""
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV

    assert FLAG not in FLAG_ENV
    assert FLAG not in FLAG_DEFAULT
