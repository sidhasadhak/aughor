"""Deterministic grounding guards on the inferred BusinessProfile:
  F7 — strip business_model clauses the schema can't support (hallucinated 'subscription')
  F5 — guarantee a cross-domain AND key-question (the margin-leak class)
  F4 — anchor a metric's sane band on the MEASURED magnitude, not a world-knowledge guess
"""
from aughor.profile import infer as I
from aughor.profile.models import BusinessProfile, NorthStarMetric


def _profile(**kw):
    base = dict(industry="x", business_model="retail", summary="s",
                north_star_metrics=[], key_questions=[], confidence=0.9, evidence="e")
    base.update(kw)
    return BusinessProfile(**base)


def _metric(name, **kw):
    base = dict(name=name, definition="d", maps_to="t", why_it_matters="w", unit_or_range="")
    base.update(kw)
    return NorthStarMetric(**base)


class TestStripUnsupportedModel:
    def test_subscription_stripped_when_no_evidence(self):
        p = _profile(business_model="DTC subscription & one-time purchase retail")
        I._strip_unsupported_model(p, "TABLE: analytics.orders\n order_id\n total_amount\n order_status")
        assert "subscription" not in p.business_model.lower()
        assert "one-time purchase retail" in p.business_model

    def test_subscription_kept_when_evidence_present(self):
        p = _profile(business_model="B2B subscription SaaS")
        I._strip_unsupported_model(p, "TABLE: subscriptions\n plan_id\n mrr\n renewal")
        assert "subscription" in p.business_model.lower()

    def test_marketplace_stripped_without_seller_table(self):
        p = _profile(business_model="marketplace retail")
        I._strip_unsupported_model(p, "TABLE: orders\n order_id\n customer_id")
        assert "marketplace" not in p.business_model.lower()


class TestEnsureCompositeQuestion:
    def test_seeds_composite_when_margin_and_return_metrics(self):
        p = _profile(north_star_metrics=[_metric("Gross Margin Rate"), _metric("Refund Rate")],
                     key_questions=["What is AOV?"])
        I._ensure_composite_question(p)
        assert any("BOTH" in q for q in p.key_questions)

    def test_no_seed_when_composite_already_present(self):
        p = _profile(north_star_metrics=[_metric("Gross Margin Rate"), _metric("Refund Rate")],
                     key_questions=["Which SKUs are both high-margin and high-return?"])
        before = len(p.key_questions)
        I._ensure_composite_question(p)
        assert len(p.key_questions) == before

    def test_no_seed_without_both_metric_families(self):
        p = _profile(north_star_metrics=[_metric("AOV"), _metric("GMV")], key_questions=["q"])
        I._ensure_composite_question(p)
        assert not any("BOTH" in q for q in p.key_questions)


class TestCalibrateRanges:
    class _Res:
        error = None
        def __init__(self, rows): self.rows = rows

    class _Conn:
        def __init__(self, rows): self._rows = rows
        def execute(self, *a): return TestCalibrateRanges._Res(self._rows)

    def test_appends_measured_magnitude(self):
        m = _metric("AOV", unit_or_range="USD (human scale: 20-150)", value_sql="SELECT AVG(x) FROM t")
        p = _profile(north_star_metrics=[m])
        I._calibrate_ranges(p, self._Conn([["536.84"]]))
        assert "measured" in m.unit_or_range and "536.84" in m.unit_or_range

    def test_skips_when_no_value_sql(self):
        m = _metric("AOV", unit_or_range="USD", value_sql="")
        p = _profile(north_star_metrics=[m])
        I._calibrate_ranges(p, self._Conn([["1"]]))
        assert m.unit_or_range == "USD"
