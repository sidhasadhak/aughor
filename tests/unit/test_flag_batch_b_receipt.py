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


def test_the_conversion_ended_in_an_unconditional_trigger():
    """Batch B converted ask.conversation_context from a toggle into a self-gating guard,
    on the finding that both call sites were already gated by `is_followup(question)`.
    Wave 3 finished the move: the flag is gone and the detector alone decides.

    The receipt's claim is what is pinned here — that the TRIGGER survived the flag. Its
    description stays in CAPABILITY_TRIGGER because the Activation Receipt still reports
    why the capability fired, which has nothing to do with whether a flag gated it."""
    from aughor.kernel.flags import AUTO_ELIGIBLE, CAPABILITY_TRIGGER, FLAG_DEFAULT, FLAG_ENV

    assert "ask.conversation_context" not in FLAG_ENV
    assert "ask.conversation_context" not in FLAG_DEFAULT
    assert AUTO_ELIGIBLE == frozenset()
    assert CAPABILITY_TRIGGER.get("ask.conversation_context"), \
        "the trigger description outlives the flag — the receipt still names why it fired"


def test_federation_planner_is_kept_and_no_longer_routes_chat_on_its_own(client):
    """The batch's premise-check finding stood until 2026-10-28: the planner auto-federated fresh /ask turns,
    unmeasured. The user kept the planner ("We may need cross querying across connections in the future") and the
    flag went (ROADMAP §3.65): the planner is part of the platform, served through its own doors with nothing set,
    and /ask no longer sends a turn to it."""
    import aughor.routers.investigations as inv
    from aughor.kernel import flags as F

    for registry in (F.FLAG_ENV, F.FLAG_META, F.ALWAYS_ON, F.EXPERIMENT, F.FLAG_DEFAULT, F.GRADUATION_QUEUE):
        assert "federation.planner" not in registry
    # each door serves: it reaches its own validation (one connection is refused by name), never a 404
    for door in ("/query/federated-answer", "/query/auto-federated-answer"):
        r = client.post(door, json={"question": "x", "conn_ids": ["only-one"]})
        assert r.status_code == 400 and "at least two" in r.text, (door, r.status_code, r.text)
    assert not hasattr(inv, "_federation_eligible") and not hasattr(inv, "_stream_federated")
