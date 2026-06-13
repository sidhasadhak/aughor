"""B-7 — metric enforcement detection: did the AI use the governed formula?

The point of UNIFY was a single registered metric; the point of B-7 is proving
the AI actually USES it. These pin the detector: a governed-formula answer reads
'used', a re-derivation on the same concept reads 'drift', and an unrelated
question is n/a (nothing to enforce) — high precision so a correct-but-different
query is never mislabelled.
"""
from types import SimpleNamespace

from aughor.semantic.enforcement import (
    check_metric_enforcement, enforcement_summary, corrective_directive, drift_count,
    enforce_gate, propose_undefined_metrics,
)

_GOVERNED = "SELECT SUM(total_amount) FROM ecommerce.orders WHERE status <> 'cancelled'"
_DRIFTED  = "SELECT SUM(line_total) FROM ecommerce.order_items"


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


class TestGateDriftCount:
    def test_counts_only_drifts(self):
        verdicts = [
            {"metric": "revenue", "status": "used", "formula": "", "detail": ""},
            {"metric": "aov", "status": "drift", "formula": "", "detail": ""},
            {"metric": "margin", "status": "drift", "formula": "", "detail": ""},
        ]
        assert drift_count(verdicts) == 2

    def test_empty_is_zero(self):
        assert drift_count([]) == 0 and drift_count(None) == 0


class TestGateCorrectiveDirective:
    def test_drift_produces_directive_naming_the_formula(self):
        # a real drift verdict (re-derivation of revenue) → the corrective directive
        # must name the metric and quote its governed formula verbatim.
        v = check_metric_enforcement(
            "what is total revenue?", "SELECT SUM(line_total) FROM order_items", [_revenue()])
        d = corrective_directive(v)
        assert d                                  # non-empty
        assert "revenue" in d
        assert "SUM(total_amount)" in d           # governed formula, verbatim
        assert "do NOT re-derive" in d

    def test_no_directive_when_used(self):
        v = check_metric_enforcement(
            "total revenue", "SELECT SUM(total_amount) FROM orders", [_revenue()])
        assert v[0]["status"] == "used"
        assert corrective_directive(v) == ""

    def test_no_directive_when_nothing_targeted(self):
        assert corrective_directive([]) == ""

    def test_directive_covers_every_drifted_metric(self):
        verdicts = [
            {"metric": "revenue", "status": "drift", "formula": "SUM(total_amount)", "detail": "x"},
            {"metric": "aov", "status": "drift", "formula": "AVG(total_amount)", "detail": "y"},
        ]
        d = corrective_directive(verdicts)
        assert "revenue" in d and "aov" in d
        assert "SUM(total_amount)" in d and "AVG(total_amount)" in d


class TestEnforceGate:
    """The B-7 gate decision the agent's SQL-gen path runs (regenerate-on-drift,
    keep-only-if-better). `regenerate` is injected so the LLM stays out of the test."""

    def test_drift_then_compliant_rewrite_is_kept(self):
        calls = []
        def regen(directive):
            calls.append(directive)
            return _GOVERNED                       # the corrected SQL uses the formula
        out = enforce_gate("total revenue", _DRIFTED, [_revenue()], regen)
        assert out == _GOVERNED                    # rewrite kept
        assert calls and "SUM(total_amount)" in calls[0]   # directive named the formula

    def test_drift_then_still_drifting_keeps_original(self):
        # the rewrite is no better → fail-safe: keep the original, don't worsen it
        out = enforce_gate("total revenue", _DRIFTED, [_revenue()],
                           lambda d: "SELECT SUM(price) FROM sales")
        assert out == _DRIFTED

    def test_regenerate_returns_none_keeps_original(self):
        out = enforce_gate("total revenue", _DRIFTED, [_revenue()], lambda d: None)
        assert out == _DRIFTED

    def test_used_does_not_regenerate(self):
        called = {"n": 0}
        def regen(d):
            called["n"] += 1
            return _DRIFTED
        out = enforce_gate("total revenue", _GOVERNED, [_revenue()], regen)
        assert out == _GOVERNED and called["n"] == 0   # no drift → no regenerate

    def test_nothing_targeted_is_noop(self):
        called = {"n": 0}
        def regen(d):
            called["n"] += 1
            return _GOVERNED
        # unrelated question → no targeted metric → gate is a no-op, no regenerate
        out = enforce_gate("how many customers?", "SELECT COUNT(*) FROM customers",
                           [_revenue()], regen)
        assert out == "SELECT COUNT(*) FROM customers" and called["n"] == 0

    def test_no_metrics_is_noop(self):
        out = enforce_gate("total revenue", _DRIFTED, [], lambda d: _GOVERNED)
        assert out == _DRIFTED


class TestProposeToDefine:
    def test_ungoverned_kpi_is_proposed(self):
        # churn is a known KPI, not in the registry → propose defining it
        p = propose_undefined_metrics("what's our churn rate this quarter?", [_revenue()])
        assert [x["slug"] for x in p] == ["churn_rate"]
        assert p[0]["phrase"] == "churn rate"

    def test_governed_kpi_is_not_proposed(self):
        # revenue IS governed → no proposal even though the term appears
        assert propose_undefined_metrics("total revenue", [_revenue()]) == []

    def test_governed_by_label_not_proposed(self):
        # _aov's label is "Average Order Value" → the phrase is covered
        assert propose_undefined_metrics("average order value trend", [_aov()]) == []

    def test_no_kpi_term_no_proposal(self):
        assert propose_undefined_metrics("how many customers are there?", [_revenue(), _aov()]) == []

    def test_multiple_ungoverned_kpis(self):
        slugs = {x["slug"] for x in propose_undefined_metrics(
            "show gross margin and lifetime value", [_revenue()])}
        assert slugs == {"gross_margin", "ltv"}

    def test_dedupes_by_slug(self):
        # "churn rate" and "churn" both map to churn_rate → one proposal
        p = propose_undefined_metrics("churn and churn rate", [_revenue()])
        assert [x["slug"] for x in p] == ["churn_rate"]

    def test_empty_question_no_proposal(self):
        assert propose_undefined_metrics("", [_revenue()]) == []

    def test_governed_term_elsewhere_does_not_suppress_ungoverned(self):
        # regression the real receipt path caught: a governed metric named in the same
        # question ("revenue") must NOT suppress an unrelated ungoverned KPI.
        p = propose_undefined_metrics("repeat purchase rate and total revenue", [_revenue()])
        assert [x["slug"] for x in p] == ["repeat_purchase_rate"]


class TestSummary:
    def test_mixed_used_and_drift_not_enforced(self):
        verdicts = [
            {"metric": "revenue", "status": "used", "formula": "", "detail": ""},
            {"metric": "aov", "status": "drift", "formula": "", "detail": ""},
        ]
        s = enforcement_summary(verdicts)
        assert s["targeted"] == 2 and s["used"] == ["revenue"] and s["drift"] == ["aov"]
        assert s["enforced"] is False
