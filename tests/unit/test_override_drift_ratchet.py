"""A graduation cannot be decided in a configuration no fresh clone has.

Flag drift is a recurring leak, not a one-off: the 2026-07-22 audit cleared 19 runtime
overrides that contradicted a code default, and the 2026-07-27 re-audit found 23 more. They
are written by the Settings UI during ordinary use and never expire, so the pattern has been
"discover it by hand, clear it by hand, watch it come back".

The reason it matters more during a graduation than in normal dev is that **a graduation
decides what a FRESH CLONE does**. Measuring a candidate on a box where unrelated flags are
forced on is the audit's own sentence — "CI validated a configuration nobody ran" — arriving
through the measurement plane instead of through CI.

**Why this is a runtime gate and not a repo ratchet.** The overrides live in the local ledger
(`Ledger.kv_*`, i.e. `data/system.db`), which a fresh CI checkout does not have. A test
asserting "this machine has no overrides" would therefore pass vacuously in CI and catch
nothing — it would be a ratchet in name only. So the check runs where the claim is made: the
gate refuses, and the receipt records the configuration either way.

These tests construct drift synthetically, so they assert the LOGIC in CI rather than
depending on whatever happens to be in a developer's ledger.
"""
from __future__ import annotations

from aughor.evals.promotion import evaluate_graduation

FLAGS = {"graph.readback", "closed_loop", "semops.champion_validate"}


def _clean_summary(total: int = 9) -> dict:
    return {"total": total, "stable_pass": total, "flaky": 0, "errors": 0,
            "pass_rate": 1.0, "run_id": "run-1", "suite_id": "suite-1"}


def _drift(**flags: bool) -> dict:
    """{flag: forced_value} → the shape `override_drift()` returns."""
    return {name: {"override": value, "without_override": not value}
            for name, value in flags.items()}


def test_a_clean_run_on_a_clean_box_graduates():
    d = evaluate_graduation("graph.readback", _clean_summary(),
                            registered_flags=FLAGS, override_drift={})
    assert d.can_graduate is True
    assert d.reasons == []
    assert d.override_drift == {}


def test_a_contradicting_override_blocks_an_otherwise_perfect_run():
    """The run is 9/9 with no baseline to beat — the decision is refused purely because
    the environment it was measured in is not one anybody else runs."""
    d = evaluate_graduation("graph.readback", _clean_summary(),
                            registered_flags=FLAGS,
                            override_drift=_drift(closed_loop=True))

    assert d.can_graduate is False
    assert any("contradict a fresh clone" in r for r in d.reasons)
    # The refusal NAMES the drifted flag and which way it differs, so the fix is obvious
    # without a second investigation.
    assert any("closed_loop is on here but off on a fresh clone" in r for r in d.reasons)


def test_drift_in_an_unrelated_flag_still_blocks():
    """Deliberately not scoped to the flag under decision. The overrides that move a
    measurement are the ones nobody was thinking about — scoping the check to the
    candidate would miss exactly those."""
    d = evaluate_graduation("graph.readback", _clean_summary(),
                            registered_flags=FLAGS,
                            override_drift=_drift(**{"semops.champion_validate": True}))
    assert d.can_graduate is False
    assert any("semops.champion_validate" in r for r in d.reasons)


def test_the_drift_is_recorded_on_the_receipt_not_only_in_the_refusal():
    """A receipt has to state the configuration it was measured in, so a later reader can
    re-judge it. Carried on passing decisions too."""
    drift = _drift(closed_loop=True)
    d = evaluate_graduation("graph.readback", _clean_summary(),
                            registered_flags=FLAGS, override_drift=drift)
    assert d.override_drift == drift
    assert d.to_dict()["override_drift"] == drift

    clean = evaluate_graduation("graph.readback", _clean_summary(),
                                registered_flags=FLAGS, override_drift={})
    assert "override_drift" in clean.to_dict()


def test_drift_is_reported_even_when_there_is_no_run():
    """The no-run early return must not drop the configuration — otherwise the one
    decision most likely to be retried says nothing about why it should not be."""
    d = evaluate_graduation("graph.readback", None, registered_flags=FLAGS,
                            override_drift=_drift(closed_loop=True))
    assert d.can_graduate is False
    assert d.override_drift == _drift(closed_loop=True)


def test_many_drifted_flags_are_summarised_not_dumped():
    d = evaluate_graduation(
        "graph.readback", _clean_summary(), registered_flags=FLAGS,
        override_drift={f"flag.{i}": {"override": True, "without_override": False}
                        for i in range(9)})
    reason = next(r for r in d.reasons if "contradict a fresh clone" in r)
    assert "9 runtime override(s)" in reason
    assert "(+3 more)" in reason


# ── the audit function itself ────────────────────────────────────────────────────

def test_override_drift_ignores_an_override_that_restates_the_default(
        monkeypatch, synthetic_default_on):
    """Measured 2026-07-31: 15 of 16 overrides on the reference box merely restated the
    code default. An audit that counts overrides reports 16 problems where there is 1."""
    import aughor.kernel.flags as flags

    monkeypatch.setattr(flags, "_override",
                        lambda name: True if name == synthetic_default_on else None)
    # The flag is default-ON, so an override forcing it ON changes nothing.
    assert flags.override_drift() == {}


def test_override_drift_catches_a_flag_forced_against_its_default(
        monkeypatch, synthetic_default_on):
    import aughor.kernel.flags as flags

    monkeypatch.setattr(flags, "_override",
                        lambda name: False if name == synthetic_default_on else None)
    drift = flags.override_drift()
    assert drift == {synthetic_default_on: {"override": False, "without_override": True}}


def test_override_drift_compares_against_resolution_not_flag_default(monkeypatch):
    """The distinction that got three flags wrong when predicted by hand.

    Comparing an override against ``FLAG_DEFAULT.get(name, False)`` calls a pinned-OFF
    flag "not drift" whenever something ELSE would have turned it on — so clearing the
    override silently changes the value the audit just declared safe.

    Auto-mode used to be that something else; Wave 3 dissolved it, so the case is built
    here from an env var instead. That is the more durable vehicle anyway: the property
    under test is the COMPARISON BASIS, not any one tier, and writing it against a tier
    is what made this test die with the tier.
    """
    import aughor.kernel.flags as flags

    victim = "semops.champion_validate"          # a plain default-OFF flag
    assert flags.FLAG_DEFAULT.get(victim, False) is False, "picked a flag with a real default"

    # The env turns it ON; the override pins it OFF. FLAG_DEFAULT says False and the
    # override says False, so a naive comparison sees agreement — while clearing the
    # override would flip this process to True.
    monkeypatch.setenv(flags.FLAG_ENV[victim], "1")
    monkeypatch.setattr(flags, "_override",
                        lambda name: False if name == victim else None)

    drift = flags.override_drift()
    assert victim in drift, "a pinned-off flag the env would enable IS drift"
    assert drift[victim] == {"override": False, "without_override": True}


