"""J3 binds J9: a flag cannot graduate on a delta the harness refuses to attribute.

Found by running Wave L2's first real grid. `fidelity.compare` refused a +0.023 change
against a 0.182 noise band, while `evaluate_graduation` — looking at the same two
numbers — independently returned `can_graduate=True`. Two halves of one discipline,
disagreeing, because only one of them had ever looked at the floor.

Clearing the bar is not the same as beating it. The difference is the noise floor.
"""
from __future__ import annotations

from aughor.evals import fidelity as FI
from aughor.evals.promotion import evaluate_graduation

FLAGS = {"graph.readback"}


def _summary(pass_rate: float, total: int = 22) -> dict:
    return {"total": total, "stable_pass": round(pass_rate * total), "flaky": 0,
            "errors": 0, "pass_rate": pass_rate}


def _runs(*rates: float) -> list[dict]:
    return [{"pass_rate": r, "total": 22} for r in rates]


def test_a_noisy_baseline_blocks_graduation():
    """The real L2 numbers: off scored 0.864 and 0.682 on identical configuration, so
    the baseline disagrees with itself by more than any effect this suite could
    resolve."""
    delta = FI.compare(_runs(0.8636, 0.6818), _runs(0.7727, 0.8182), axis="pass_rate")
    assert delta.attributable is False

    d = evaluate_graduation("graph.readback", _summary(0.7954),
                            registered_flags=FLAGS, baseline_pass_rate=0.7727,
                            delta=delta)
    assert d.can_graduate is False
    assert any("not attributable" in r for r in d.reasons)
    # the refusal quotes the floor's own reasoning rather than inventing its own
    assert any("0.182" in r or "band" in r for r in d.reasons)


def test_a_quiet_baseline_lets_a_real_delta_through():
    """The gate must not become unpassable — a floor-verified delta still graduates."""
    delta = FI.compare(_runs(0.70, 0.71), _runs(0.90, 0.91), axis="pass_rate")
    assert delta.attributable is True

    d = evaluate_graduation("graph.readback", _summary(0.905),
                            registered_flags=FLAGS, baseline_pass_rate=0.705,
                            delta=delta)
    assert d.can_graduate is True, d.reasons


def test_an_ab_without_floor_evidence_is_refused_not_assumed():
    """A baseline implies an A/B ran, and an A/B without its floor is exactly the shape
    that produced this bug. Silence is not evidence."""
    d = evaluate_graduation("graph.readback", _summary(0.80),
                            registered_flags=FLAGS, baseline_pass_rate=0.77)
    assert d.can_graduate is False
    assert any("no floor evidence" in r for r in d.reasons)


def test_a_plain_threshold_run_still_needs_no_floor():
    """No baseline ⇒ no A/B ⇒ nothing to floor-verify; the min_pass_rate bar stands
    alone, so an existing single-run graduation is not broken by this."""
    d = evaluate_graduation("graph.readback", _summary(1.0),
                            registered_flags=FLAGS, min_pass_rate=1.0)
    assert d.can_graduate is True, d.reasons
