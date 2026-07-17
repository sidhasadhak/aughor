"""Report relevance + ranking — deliver only what moves the reader, most-material first.

The user's critique of the losing-money report: it was bloated with findings that change
no conclusion (a suppressed metric, a 100%-in-every-channel ranking, a self-declared
"inconclusive — no peer" finding) and buried its one decision (the utilization gap) last.
This pass drops the noise classes and re-orders so the opportunity-bearing phase leads.
"""
from __future__ import annotations

from aughor.agent.investigate import (
    _finding_earns_place,
    _is_zero_variance_ranking,
    _phase_materiality,
    _prune_and_rank_phases,
)


def _f(**kw):
    base = {"columns": [], "rows": [], "key_numbers": [], "interpretation": "",
            "is_significant": False}
    base.update(kw)
    return base


def test_suppressed_finding_is_dropped():
    assert not _finding_earns_place(_f(_suppressed=True, interpretation="could not be computed"))


def test_repaired_finding_always_earns_its_place():
    assert _finding_earns_place(_f(_grain_repaired=True, interpretation="Recomputed…"))


def test_zero_variance_ranking_is_dropped():
    """100% in every booking channel — no spread, no discrimination, no action."""
    uniform = _f(columns=["segment", "leading_reason_share", "n"],
                 rows=[["web", 100.0, 5], ["app", 100.0, 4], ["corporate", 100.0, 3]],
                 interpretation="Uniform. The leading reason shows no concentration.")
    assert _is_zero_variance_ranking(uniform)
    assert not _finding_earns_place(uniform)
    # a real spread survives
    spread = _f(columns=["segment", "leakage_rate", "n"],
                rows=[["first", 3.56, 20], ["economy", 2.22, 90]],
                interpretation="First leaks fastest.")
    assert not _is_zero_variance_ranking(spread)
    assert _finding_earns_place(spread)


def test_inconclusive_finding_is_dropped_unless_it_carries_an_opportunity():
    inconclusive = _f(interpretation="Inconclusive — no peer range is present in the data.",
                      key_numbers=[{"label": "Leading reason share", "value": "60.7%"}])
    assert not _finding_earns_place(inconclusive)
    # …but one that still carries a material opportunity number stands on its own
    with_opp = _f(interpretation="Inconclusive — no peer range is present.",
                  key_numbers=[{"label": "Opportunity: long → short", "value": "1,812"}])
    assert _finding_earns_place(with_opp)


def test_single_row_fact_is_not_a_zero_variance_ranking():
    """A single-row finding is a stated fact ('100% of refunds are voluntary'), not a
    ranking — it is left alone (its chart is already suppressed for <2 rows elsewhere)."""
    fact = _f(columns=["reason", "share"], rows=[["voluntary_cancellation", 100.0]],
              interpretation="100% of refunds are voluntary cancellations.")
    assert not _is_zero_variance_ranking(fact)
    assert _finding_earns_place(fact)


def test_the_opportunity_phase_leads_after_ranking():
    """The whole point: the utilization gap (the decision) led from LAST to FIRST."""
    phases = [
        {"phase_id": "cross_section", "phase_name": "Where", "summary": "s",
         "findings": [_f(_grain_repaired=True, columns=["seg", "rate", "n"],
                         rows=[["a", 3.4, 5], ["b", 2.6, 5]], interpretation="Recomputed.")]},
        {"phase_id": "cross_section_interaction", "phase_name": "Interaction", "summary": "Uniform.",
         "findings": [_f(columns=["seg", "share", "n"],
                         rows=[["web", 100.0, 5], ["app", 100.0, 4]],
                         interpretation="Uniform. No concentration.")]},
        {"phase_id": "reason_benchmark", "phase_name": "Benchmark", "summary": "s",
         "findings": [_f(interpretation="Inconclusive — no peer range is present.")]},
        {"phase_id": "loss_utilization", "phase_name": "Utilization", "summary": "s",
         "findings": [_f(columns=["haul", "util", "n"], rows=[["long", 74.5, 65], ["short", 77.2, 280]],
                         key_numbers=[{"label": "Opportunity: long → short benchmark", "value": "1,812"}],
                         interpretation="Long-haul is weakest.")]},
    ]
    ranked = _prune_and_rank_phases(phases)
    order = [p["phase_id"] for p in ranked if not p.get("_hidden")]
    # the two noise phases are hidden; the opportunity phase leads
    assert order[0] == "loss_utilization"
    assert "cross_section_interaction" not in order   # zero-variance → emptied → hidden
    assert "reason_benchmark" not in order            # inconclusive → emptied → hidden
    assert "cross_section" in order                   # the repaired real finding survives
    # hidden phases are RETAINED (count/reconciliation intact), just flagged
    assert len(ranked) == 4
    assert sum(1 for p in ranked if p.get("_hidden")) == 2


def test_phase_materiality_ranks_opportunity_highest():
    opp = {"findings": [_f(key_numbers=[{"label": "Opportunity: x", "value": "1"}])]}
    sig = {"findings": [_f(is_significant=True)]}
    plain = {"findings": [_f()]}
    assert _phase_materiality(opp) > _phase_materiality(sig) > _phase_materiality(plain)
