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


def test_the_queue_is_named_and_migrations_are_empty():
    """The strategy's steady state: every flag is graduated, auto, an opt-in, an
    experiment, or in the performance profile — and a queued/migration flag must
    declare itself with its exit AND be named here, so joining the queue is a
    reviewed decision, not a side effect (this assertion going red on an unnamed
    entry is the mechanism, and is exactly how FL-1b's entry arrived — and how
    its removal left, 2026-08-28, when `ask.resume_stream` graduated on its
    delivered receipts: browser-soak reattach + interrupt-cancels-the-job. The
    receipt record lives on the GRADUATION_QUEUE tombstone in kernel/flags.py)."""
    from aughor.kernel.flags import GRADUATION_QUEUE, MIGRATION

    # Arc CT-4 (ROADMAP §3.50), 2026-09-28: `cockpit.composed` — a Cockpit tab in the Data Canvas.
    # It adds no model call, so it has no grid to pass: it is queued on a receipt of USE, and
    # its entry in kernel/flags.py says which, and what would delete it instead.
    # Arc AO-2b (ROADMAP §3.52), 2026-10-03: `slack.managed_supervisor` — the API runs the
    # Slack supervisor. No model call either; it graduates on the arc's own measure (Create
    # agent → a Slack answer, one person, no terminal, under five minutes, on two machines)
    # and its entry names the falsifier that reopens the in-process spike instead.
    # Arc OC-0 (ROADMAP §3.56), 2026-10-09: `ontology.census` — the daily census in the journal. No model
    # call and no warehouse query; it graduates on being READ by a later wave's receipt, and its entry names
    # the falsifier that deletes it instead.
    # Arc OC-1, the same day: `ontology.history` — every declaration's versions, and a withdrawal refused where
    # something depends on it. Its entry names the receipt and the falsifier.
    # …and `ontology.release` (Arc OC-2): a change waits in a draft until a person publishes it.
    # Arc OC-4, the same day: `ontology.cockpit_pieces` — cockpit pieces bound to the ontology. No model call; it
    # graduates on its live receipt, and its entry names the falsifier that deletes it instead.
    # Arc OC-6, 2026-10-10: `actions.outbox` — a declared action's calls through an outbox, retried by cause and an
    # unknown one checked before it is sent again. No model call; it graduates on its live receipt (a forced timeout
    # reconciled by the action's check), and its entry names the falsifier that sends it back.
    # Arc OC-7 and OC-8, the same day: `ontology.security` (row policies and masked properties; its receipt is on a
    # scratch install until sign-in) and `ontology.builder_doors` (the contract, listed and proposed on from outside).
    # Neither calls a model; each entry names its receipt and the falsifier.
    assert set(GRADUATION_QUEUE) == {"cockpit.composed", "slack.managed_supervisor", "ontology.census",
                                     "ontology.history", "ontology.release", "ontology.cockpit_pieces",
                                     "actions.outbox", "ontology.security", "ontology.builder_doors"}
    assert all("receipt" in why and "Falsifier" in why for why in GRADUATION_QUEUE.values())
    assert MIGRATION == {}
