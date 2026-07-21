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


class TestStalePlausibilityRejectsAreRetired:
    """The explorer's EMISSION gate (verify.py) rejects a methodologically-void finding, but
    anything written BEFORE that gate landed sits in the store untouched — and every brief
    re-triaged it into a red "held back by the trust gate" strip. On the real luxexperience
    store all 14 such signals were generated 2026-06-30, weeks after nothing was producing
    them any more. Retiring the reject once beats re-deriving it on every read.

    The two checks differ in what they need: the rate check is pure SQL, so it works offline;
    the aggregate↔type check needs declared column types and fail-opens without them."""

    AVG_OF_RATE = {
        "id": "Operations__fulfillment__3", "novelty": 3, "confidence": 0.7,
        "finding": "Asia concentrates the highest total duty exposure across all platforms.",
        "sql": "SELECT region, AVG(duty_rate) FROM shipments GROUP BY region",
    }
    SUM_OF_VARCHAR = {
        "id": "Customer__tier__1", "novelty": 3, "confidence": 0.7,
        "finding": "Signups total 2,493,788 across the base, led by the enterprise tier.",
        "sql": "SELECT tier, SUM(signup_fy) AS m_signupfy FROM customers GROUP BY tier",
    }

    def test_avg_of_a_stored_rate_is_retired_without_column_types(self):
        action, reason = validate_insight(self.AVG_OF_RATE)
        assert action == "quarantine"
        assert "duty_rate" in reason and "already-computed rate" in reason

    def test_sum_over_varchar_needs_types_and_fails_open_without_them(self):
        assert validate_insight(self.SUM_OF_VARCHAR) is None      # no types → check no-ops
        action, reason = validate_insight(self.SUM_OF_VARCHAR, {"signup_fy": "VARCHAR"})
        assert action == "quarantine"
        assert "signup_fy" in reason

    def test_a_confound_is_demoted_not_retired(self):
        """'confound' severity stays a soft demotion at synthesis — an inverse relationship
        can be a real finding, so it must NOT be quarantined out of the store."""
        confounded = {
            "id": "Ops__lead_time__2", "novelty": 3, "confidence": 0.7,
            "finding": "Stockouts decrease as supplier lead time increases across all warehouses.",
            "sql": "SELECT w, AVG(stockouts) FROM inv GROUP BY w",
        }
        from aughor.knowledge.triage import plausibility
        assert plausibility(confounded["finding"], confounded["sql"]).severity == "confound"
        assert validate_insight(confounded) is None

    def test_a_sound_finding_is_untouched(self):
        assert validate_insight(GOOD, {"revenue": "DECIMAL(18,2)"}) is None

    def test_apply_flags_in_place_and_the_store_read_path_hides_it(self):
        state = {"insights": [copy.deepcopy(self.AVG_OF_RATE), copy.deepcopy(GOOD)]}
        report = revalidate_state(state, apply=True)
        assert len(report["quarantined"]) == 1
        assert state["insights"][0]["invalid"] is True
        assert "duty_rate" in state["insights"][0]["invalid_reason"]
        assert "invalid" not in state["insights"][1]        # the sound finding is untouched
        # quarantine HIDES, never deletes — the row survives for inspection and is reversible
        visible = [i for i in state["insights"] if not i.get("invalid")]
        assert [i["id"] for i in visible] == [GOOD["id"]]

    def test_column_types_thread_through_revalidate_state(self):
        state = {"insights": [copy.deepcopy(self.SUM_OF_VARCHAR)]}
        assert revalidate_state(state, apply=True)["quarantined"] == []      # no types → kept
        assert "invalid" not in state["insights"][0]
        rep = revalidate_state(state, apply=True, col_types={"signup_fy": "VARCHAR"})
        assert len(rep["quarantined"]) == 1
        assert state["insights"][0]["invalid"] is True
