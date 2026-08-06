"""Flag strategy batch 1 — the deterministic graduation suite for `specialist_packs`.

Hermetic: scenarios construct packs in memory (or under a temp dir), write deploy
bindings only under synthetic receipt-probe connection ids and purge them per
case, and only ever READ the repo's shipped ``packs/`` directory. The flag's
receipt must not depend on what happened to be deployed the day it was recorded.
"""
from __future__ import annotations

import pytest

from aughor.evals.evaluator import EvalCase
from aughor.evals.specialist_packs_receipt import FLAG, SCENARIOS, receipt_target


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


def test_the_suite_covers_the_invariants_the_flip_rests_on():
    """Pinned by name: these are the properties the flag's default rests on, and a
    silent deletion of one would leave the graduation resting on less than it claims."""
    assert {"an_installed_active_pack_alone_steers_nothing",
            "a_fresh_clone_has_nothing_to_steer_with",
            "a_draft_pack_never_steers_even_when_deployed",
            "steering_is_scoped_to_the_deployed_connection",
            "agent_pack_preference_never_bypasses_the_deploy_gate",
                        "a_broken_pack_on_disk_never_takes_down_intake",
            "the_enabled_field_is_the_only_fresh_clone_delta"} <= set(SCENARIOS)


def test_unknown_scenario_is_an_error_not_an_empty_pass():
    """A suite that silently skipped a case it could not resolve would report a pass
    rate over fewer cases than it claims to cover."""
    obs = receipt_target()(EvalCase(id="x", question="?", expected={"scenario": "nope"}))
    assert obs.error and "nope" in obs.error


def test_the_flag_stayed_deleted():
    """Hardwired by flag endgame Wave 2 (2026-08-06). The registry must stay empty
    of it — a re-registration would be the drift the endgame exists to prevent."""
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV

    assert FLAG not in FLAG_ENV
    assert FLAG not in FLAG_DEFAULT
