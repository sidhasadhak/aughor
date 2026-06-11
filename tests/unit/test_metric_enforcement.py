"""B-7 — metric enforcement detection: did the AI use the governed formula?

The point of UNIFY was a single registered metric; the point of B-7 is proving
the AI actually USES it. These pin the detector: a governed-formula answer reads
'used', a re-derivation on the same concept reads 'drift', and an unrelated
question is n/a (nothing to enforce) — high precision so a correct-but-different
query is never mislabelled.
"""
from types import SimpleNamespace

from aughor.semantic.enforcement import (
    check_metric_enforcement, enforcement_summary,
)


def _revenue():
    return SimpleNamespace(
        name="revenue", label="Revenue", sql="SUM(total_amount)",
        wrong_usage_examples=["SUM(order_items.line_total) — line-item grain, diverges 4.3x"],
    )


def _aov():
    return SimpleNamespace(
        name="aov", label="Average Order Value", sql="AVG(total_amount)",
        wrong_usage_examples=["AVG(line_total) sold as AOV"],
    )


class TestUsed:
    def test_governed_formula_reads_used(self):
        v = check_metric_enforcement(
            "what is the total revenue?",
            "SELECT ROUND(SUM(total_amount), 2) FROM ecommerce.orders WHERE status <> 'cancelled'",
            [_revenue()],
        )
        assert len(v) == 1 and v[0]["status"] == "used"
        assert enforcement_summary(v)["enforced"] is True

    def test_whitespace_and_case_insensitive(self):
        v = check_metric_enforcement(
            "revenue please", "select sum( TOTAL_AMOUNT ) from orders", [_revenue()])
        assert v[0]["status"] == "used"

    def test_label_phrase_match_targets_metric(self):
        v = check_metric_enforcement(
            "show the average order value", "SELECT AVG(total_amount) FROM orders", [_aov()])
        assert v and v[0]["metric"] == "aov" and v[0]["status"] == "used"


class TestDrift:
    def test_rederivation_on_same_concept_reads_drift(self):
        v = check_metric_enforcement(
            "what is total revenue?",
            "SELECT SUM(line_total) FROM ecommerce.order_items",
            [_revenue()],
        )
        assert len(v) == 1 and v[0]["status"] == "drift"
        # names a non-governed reference (line_total or its table order_items)
        assert "line_total" in v[0]["detail"] or "order_items" in v[0]["detail"]
        assert enforcement_summary(v)["enforced"] is False

    def test_drift_without_known_wrong_col_still_flags(self):
        v = check_metric_enforcement(
            "total revenue", "SELECT SUM(price) FROM sales", [_revenue()])
        assert v[0]["status"] == "drift"


class TestNotApplicable:
    def test_unrelated_question_is_na(self):
        v = check_metric_enforcement(
            "how many customers are there?",
            "SELECT COUNT(*) FROM customers", [_revenue(), _aov()])
        assert v == []
        assert enforcement_summary(v) is None

    def test_no_metrics_registered_is_na(self):
        assert check_metric_enforcement("total revenue", "SELECT SUM(x) FROM y", []) == []

    def test_empty_sql_is_na_not_drift(self):
        # The ADA false-drift bug: enforcing against no SQL flagged every targeted
        # metric as 'drift' for the wrong reason. No SQL → no verdict.
        assert check_metric_enforcement("why did average order value change?", "", [_aov()]) == []
        assert check_metric_enforcement("total revenue", "   ", [_revenue()]) == []


class TestSummary:
    def test_mixed_used_and_drift_not_enforced(self):
        verdicts = [
            {"metric": "revenue", "status": "used", "formula": "", "detail": ""},
            {"metric": "aov", "status": "drift", "formula": "", "detail": ""},
        ]
        s = enforcement_summary(verdicts)
        assert s["targeted"] == 2 and s["used"] == ["revenue"] and s["drift"] == ["aov"]
        assert s["enforced"] is False
