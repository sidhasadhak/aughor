"""Re-validation / quarantine pass over STORED findings (revalidate.py).

Generation-time guards only protect new findings; this pass re-checks stored ones.
Quarantines (flags, never deletes) fabricated/no-data findings; repairs (clamps) a
real finding whose only problem is a runaway novelty score. Apply is opt-in.
"""
import copy

from aughor.explorer.revalidate import validate_insight, revalidate_state


FABRICATED = {
    "id": "Commerce__customer_acquisition__9", "novelty": 77568,
    "finding": "The 'Unknown' acquisition channel, the only channel represented…",
    "sql": "SELECT 'Unknown' AS signup_source, SUM(x) FROM t GROUP BY signup_source",
}
RUNAWAY_NOVELTY = {  # real finding, only the score is wrong
    "id": "Operations__supplier__9", "novelty": 74, "confidence": 0.95,
    "finding": "Suppliers with higher delay rates supply higher-movement SKUs",
    "sql": "SELECT supplier_id, AVG(delay) FROM po GROUP BY supplier_id",
}
NO_DATA = {
    "id": "Customer__x__1", "novelty": 3,
    "finding": "The query returned no data: 0 customers were found",
    "sql": "SELECT region, COUNT(*) FROM c GROUP BY region",
}
GOOD = {
    "id": "Commerce__value__2", "novelty": 4, "confidence": 0.8,
    "finding": "Revenue grew 12% QoQ driven by the EU cohort",
    "sql": "SELECT region, SUM(revenue) FROM orders GROUP BY region",
}


def test_validate_classifies_each_case():
    assert validate_insight(FABRICATED) == ("quarantine", "fabricated dimension (constant grouping key)")
    assert validate_insight(NO_DATA) == ("quarantine", "no-data interpretation")
    assert validate_insight(RUNAWAY_NOVELTY)[0] == "repair"
    assert validate_insight(GOOD) is None


def test_already_quarantined_is_skipped():
    assert validate_insight({**FABRICATED, "invalid": True}) is None


def test_dry_run_does_not_mutate():
    state = {"insights": [copy.deepcopy(FABRICATED), copy.deepcopy(RUNAWAY_NOVELTY), copy.deepcopy(GOOD)]}
    before = copy.deepcopy(state)
    report = revalidate_state(state, apply=False)
    assert state == before                       # untouched
    assert len(report["quarantined"]) == 1
    assert len(report["repaired"]) == 1


def test_apply_quarantines_and_repairs():
    state = {"insights": [copy.deepcopy(FABRICATED), copy.deepcopy(RUNAWAY_NOVELTY), copy.deepcopy(GOOD)]}
    revalidate_state(state, apply=True)
    fab, sup, good = state["insights"]
    # fabricated → flagged invalid (kept, not deleted)
    assert fab["invalid"] is True and fab["invalid_reason"].startswith("fabricated")
    assert fab in state["insights"]
    # runaway novelty → clamped in place, NOT quarantined
    assert sup["novelty"] == 5 and sup["confidence"] == 0.9
    assert "invalid" not in sup
    # good finding → untouched
    assert good == GOOD


def test_apply_is_idempotent():
    state = {"insights": [copy.deepcopy(FABRICATED), copy.deepcopy(RUNAWAY_NOVELTY)]}
    revalidate_state(state, apply=True)
    second = revalidate_state(state, apply=True)
    # already quarantined / already clamped → nothing left to do
    assert second["quarantined"] == [] and second["repaired"] == []
