"""Decompose-under-abstention router gate (fix 5, 2026-07-09).

Deep-Analysis audit finding (inv3): "why did revenue decline in 2024 vs 2023?" hit the Tier-0
"no single-point anomaly → stop" gate and answered "within normal variance" while listing every
dimension it never queried as a data gap. A "why did X change?" question presupposes a real move
and asks its CAUSE — when the aggregate moved materially it must still run ONE dimensional pass.
A genuinely-flat series (inv4's false "did refunds spike?" premise) must still stop cleanly.
See route_after_baseline in aughor/agent/investigate.py.
"""
from aughor.agent.investigate import route_after_baseline


def _state(question, *, sig=None, sigma=None, rel=None, phases=None):
    return {
        "question": question,
        "_baseline_significant": sig,
        "_baseline_sigma": sigma,
        "_baseline_rel_change": rel,
        "investigation_phases": phases or [],
    }


def test_why_decline_with_material_move_decomposes():
    """inv3: sub-threshold single-point anomaly (code_sig False) but a real −6.4% aggregate move →
    must proceed to dimensional decomposition, not Tier-0 synthesis."""
    s = _state("Why did revenue decline in 2024 compared to 2023?", sig=False, sigma=0.9, rel=-0.064)
    assert route_after_baseline(s) == "ada_decompose"


def test_flat_false_premise_still_stops():
    """inv4: 'why did refunds spike?' but the series is flat (immaterial move) → clean Tier-0 stop
    preserved; we do not spend phases confirming a non-event."""
    s = _state("Why did refunds spike in Q3 2024?", sig=False, sigma=0.3, rel=-0.007)
    assert route_after_baseline(s) == "ada_synthesize"


def test_non_change_question_unaffected():
    """A non-temporal-change question with no anomaly keeps the original Tier-0 skip."""
    s = _state("What is the current revenue level?", sig=False, sigma=0.4, rel=-0.20)
    assert route_after_baseline(s) == "ada_synthesize"


def test_significant_move_is_not_early_stopped():
    """When the level-shift test already marked the move significant (fix 3), the gate proceeds
    regardless of the fix-5 branch."""
    s = _state("Why did revenue decline in 2024?", sig=True, sigma=2.83, rel=-0.064)
    assert route_after_baseline(s) != "ada_synthesize"


def test_explicit_dimension_still_wins_first():
    """The pre-existing 'user asked for a dimension' override is untouched and fires first."""
    s = _state("Which channel drove the revenue decline?", sig=False, sigma=0.2, rel=-0.001)
    assert route_after_baseline(s) == "ada_decompose"


def test_missing_rel_change_falls_back_to_sigma_gate():
    """When the level-shift probe couldn't run (rel_change None), behaviour is the pre-fix gate."""
    s = _state("Why did revenue decline in 2024?", sig=False, sigma=0.5, rel=None)
    assert route_after_baseline(s) == "ada_synthesize"
