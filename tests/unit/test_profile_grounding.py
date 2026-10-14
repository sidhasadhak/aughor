"""Deterministic grounding guards on the inferred BusinessProfile:
  F7 — strip business_model clauses the schema can't support (hallucinated 'subscription')
  F5 — guarantee a cross-domain AND key-question (the margin-leak class)
  F4 — anchor a metric's sane band on the MEASURED magnitude, not a world-knowledge guess
"""
from aughor.business_profile import infer as I
from aughor.business_profile.models import BusinessProfile, NorthStarMetric


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


    def test_a_denied_claim_is_kept(self):
        # theLook, 2026-10-14: both words were stripped from a sentence that denied them → "…retail, not and not a ."
        p = _profile(business_model="single-purchase retail, not subscription and not a marketplace.")
        I._strip_unsupported_model(p, "TABLE: orders\n order_id\n user_id")
        assert p.business_model == "single-purchase retail, not subscription and not a marketplace."

    def test_a_stored_sentence_left_empty_reads_whole(self):
        stored = ("Transactional DTC e-commerce: one-off purchases where users place many orders over time "
                  "(orders.user_id / order_items.user_id), fulfilled from physical distribution_centers, with no plan, "
                  "renewal, billing-cycle or seller/listing table anywhere in the schema — so it is single-purchase "
                  "retail, not and not a .")                      # theLook's live profile, as stored
        assert I.tidy_business_model(stored) == stored.replace(", not and not a .", ".")
        assert I.tidy_business_model("one-off retail, not a marketplace.") == "one-off retail, not a marketplace."

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
        def execute(self, *a, **_kw): return TestCalibrateRanges._Res(self._rows)

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
