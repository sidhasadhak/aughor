"""Wave CR0 — the deterministic invariant suite the session log rests on.

Hermetic: scenarios drive the real door wrapper over synthetic frame streams
against throwaway ledgers, so these run without a warehouse, an LLM, or anything
in ``data/``. The flag's receipt must not depend on what happened to be on disk
the day it was recorded.
"""
from __future__ import annotations

import pytest

from aughor.evals.evaluator import EvalCase
from aughor.evals.session_log_receipt import SCENARIOS, receipt_target


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
    assert {"frames_are_delivered_untouched",
            "crashed_run_leaves_evidence", "store_failure_never_reaches_the_answer",
            "content_capture_stays_off", "retention_bounds_the_table",
            "write_latency_clears_e1_bar"} <= set(SCENARIOS)


def test_unknown_scenario_is_an_error_not_an_empty_pass():
    """A suite that silently skipped a case it could not resolve would report a pass
    rate over fewer cases than it claims to cover."""
    obs = receipt_target()(EvalCase(id="x", question="?", expected={"scenario": "nope"}))
    assert obs.error and "nope" in obs.error


def test_recording_is_unconditional():
    """The flag this suite once gated on was hardwired 2026-08-01. Pinning it here
    means a future edit re-introducing an off switch has to face this test."""
    from aughor.kernel.flags import FLAG_ENV
    from aughor.obs import session_log

    assert "obs.session_log" not in FLAG_ENV
    assert session_log.enabled() is True
