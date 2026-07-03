"""Cross-finding synthesis — findings-graph + composition-operator eligibility.

The pure half of Phase 9: reduce findings to claims, find combinable pairs (sharing
a join key), and tag each pair with the composition operators it is structurally
eligible for. The LLM articulation + confirming-query verification live in the agent
and are not exercised here.
"""
from aughor.explorer.synthesis import (
    to_claim, candidate_pairs, render_pair_prompt, OPERATORS,
)


def _insight(id, finding, sql, dims, meas, tables, novelty=3, domain="Commerce"):
    return {
        "id": id, "domain": domain, "finding": finding, "sql": sql, "novelty": novelty,
        "signature": {"tables": tables, "dimensions": dims, "measures": meas},
    }


# Two findings on the same entity, opposing measures cut by the same dimension.
MARGIN_BY_SHADE = _insight(
    "f1", "Shade X has the highest gross margin at 78%",
    "SELECT shade, AVG(margin) FROM missimi.order_items GROUP BY shade",
    dims=["shade"], meas=["margin"], tables=["missimi.order_items"], novelty=2)
RETURNS_BY_SHADE = _insight(
    "f2", "Shade X has the worst return rate at 31%",
    "SELECT shade, SUM(returns)/COUNT(*) FROM missimi.order_items GROUP BY shade",
    dims=["shade"], meas=["returns"], tables=["missimi.order_items"], novelty=2)
# A headline total + the same measure broken out by a dimension → concentration/confound.
REV_HEADLINE = _insight(
    "f3", "Total GMV is $4.2M",
    "SELECT SUM(revenue) FROM missimi.orders", dims=[], meas=["revenue"],
    tables=["missimi.orders"])
REV_BY_REGION = _insight(
    "f4", "Revenue is concentrated in the top 3 regions",
    "SELECT region, SUM(revenue) FROM missimi.orders GROUP BY region",
    dims=["region"], meas=["revenue"], tables=["missimi.orders"])
# Unrelated finding — different table, no shared dimension.
SUPPLIER_LEAD = _insight(
    "f5", "Supplier lead time averages 12 days",
    "SELECT AVG(lead_days) FROM missimi.suppliers", dims=[], meas=["lead_days"],
    tables=["missimi.suppliers"], domain="Operations")


class TestClaim:
    def test_headline_and_temporal_flags(self):
        c = to_claim(REV_HEADLINE)
        assert c.is_headline
        d = to_claim(_insight("x", "f", "s", dims=["order_month"], meas=["revenue"],
                              tables=["missimi.orders"]))
        assert d.has_temporal_dim
        assert not to_claim(REV_BY_REGION).has_temporal_dim

    def test_to_claim_falls_back_to_top_level_fields(self):
        c = to_claim({"id": "z", "dimensions": ["region"], "measures": ["revenue"], "sql": "x"})
        assert "region" in c.dimensions and "revenue" in c.measures


class TestCandidatePairs:
    def test_unrelated_findings_are_not_combinable(self):
        pairs = candidate_pairs([REV_BY_REGION, SUPPLIER_LEAD])
        assert pairs == []                       # no shared table or dimension

    def test_tension_and_chain_for_opposing_measures_same_dimension(self):
        pairs = candidate_pairs([MARGIN_BY_SHADE, RETURNS_BY_SHADE])
        assert len(pairs) == 1
        ops = pairs[0].operators
        assert "tension" in ops and "chain" in ops
        assert pairs[0].shared_dimensions == ["shade"]

    def test_concentration_and_confound_for_headline_plus_split(self):
        pairs = candidate_pairs([REV_HEADLINE, REV_BY_REGION])
        assert len(pairs) == 1
        ops = pairs[0].operators
        assert "concentration" in ops and "confound" in ops

    def test_identical_signature_pairs_excluded(self):
        dup = _insight("f4b", "Revenue by region, worded differently",
                       "SELECT region, SUM(revenue) FROM missimi.orders GROUP BY region",
                       dims=["region"], meas=["revenue"], tables=["missimi.orders"])
        # f4 and f4b have identical (tables, dims, measures) → the dedup gate owns that,
        # synthesis must not treat them as a combinable pair.
        pairs = candidate_pairs([REV_BY_REGION, dup])
        assert pairs == []

    def test_ranked_by_score_and_capped(self):
        pairs = candidate_pairs(
            [MARGIN_BY_SHADE, RETURNS_BY_SHADE, REV_HEADLINE, REV_BY_REGION],
            max_pairs=2)
        assert len(pairs) <= 2
        scores = [p.score for p in pairs]
        assert scores == sorted(scores, reverse=True)

    def test_all_operator_names_are_known(self):
        pairs = candidate_pairs([MARGIN_BY_SHADE, RETURNS_BY_SHADE, REV_HEADLINE, REV_BY_REGION])
        for p in pairs:
            assert all(op in OPERATORS for op in p.operators)


def test_render_pair_prompt_includes_findings_and_operators():
    pairs = candidate_pairs([MARGIN_BY_SHADE, RETURNS_BY_SHADE])
    body = render_pair_prompt(pairs[0])
    assert "FINDING A" in body and "FINDING B" in body
    assert "shade" in body
    assert "CANDIDATE COMPOSITION TYPES" in body
