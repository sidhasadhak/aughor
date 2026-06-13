"""Structural query signatures — deterministic near-duplicate finding detection.

Pinned to the REAL Phase-8 redundancy: a bakehouse Customer domain emitted four findings
that were all "customer count by continent/country" in cosmetic disguises. The signature
must collapse the cosmetic variants and keep the genuinely-distinct cuts (different grain,
different measure, different tables).
"""
from aughor.sql.shape import query_signature, is_structural_duplicate

# The four findings the live run actually produced (verbatim shapes).
F1 = ("SELECT continent, country, COUNT(DISTINCT customerID) AS customer_count "
      "FROM bakehouse.sales_customers GROUP BY continent, country ORDER BY continent, customer_count")
F2 = ("SELECT continent, country, COUNT(*) AS customer_count, "
      "ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total "
      "FROM bakehouse.sales_customers GROUP BY continent, country")
F3 = ("SELECT continent, COUNT(DISTINCT customerID) AS customer_count, "
      "ROUND(COUNT(DISTINCT customerID) * 100.0 / SUM(COUNT(DISTINCT customerID)) OVER (), 1) AS pct "
      "FROM bakehouse.sales_customers GROUP BY continent")
F4 = ("SELECT continent, country, COUNT(DISTINCT customerID) AS customer_count, "
      "ROUND(COUNT(DISTINCT customerID) * 100.0 / SUM(COUNT(DISTINCT customerID)) "
      "OVER (PARTITION BY continent), 1) AS pct_within "
      "FROM bakehouse.sales_customers GROUP BY continent, country")
# A genuinely different finding — same cut, DIFFERENT measure (revenue, not headcount).
REVENUE = ("SELECT sc.continent, SUM(st.totalPrice) AS revenue FROM bakehouse.sales_customers sc "
           "JOIN bakehouse.sales_transactions st ON sc.customerID = st.customerID GROUP BY sc.continent")


class TestSignature:
    def test_cosmetic_variants_collapse(self):
        # F1, F2, F4 are the same cut (sales_customers, by continent+country, headcount) —
        # COUNT(*) vs COUNT(DISTINCT pk) and a pct-of-total window wrapper are cosmetic.
        assert query_signature(F1) == query_signature(F2) == query_signature(F4)

    def test_window_aggregate_is_ignored(self):
        # the pct-of-total SUM(COUNT(...)) OVER () must NOT add a 'sum' measure
        _t, _g, measures = query_signature(F2)
        assert measures == frozenset({"count"})

    def test_different_grain_is_distinct(self):
        # F3 groups by continent only — a coarser cut, legitimately its own finding
        assert query_signature(F3) != query_signature(F1)

    def test_different_measure_is_distinct(self):
        # same cut by continent, but revenue ≠ headcount → must be kept
        assert query_signature(REVENUE) != query_signature(F3)
        _t, _g, measures = query_signature(REVENUE)
        assert any(m.startswith("sum:") for m in measures)

    def test_signature_components(self):
        tables, keys, measures = query_signature(F1)
        assert tables == frozenset({"bakehouse.sales_customers"})
        assert keys == frozenset({"continent", "country"})
        assert measures == frozenset({"count"})

    def test_casing_insensitive_keys(self):
        a = query_signature("SELECT customer_id, COUNT(*) FROM t GROUP BY customer_id")
        b = query_signature("SELECT customerID, COUNT(*) FROM t GROUP BY customerID")
        assert a == b


class TestIsDuplicate:
    def test_catches_the_redundant_findings(self):
        # walking the four in order: F2 and F4 are dups of F1; F3 is fresh
        seen = [F1]
        assert is_structural_duplicate(F2, seen) is True
        seen.append(F3)                                # F3 is fresh, gets kept
        assert is_structural_duplicate(F3, [F1]) is False
        assert is_structural_duplicate(F4, seen) is True

    def test_distinct_findings_not_flagged(self):
        assert is_structural_duplicate(REVENUE, [F1, F2, F3]) is False

    def test_parse_failure_is_not_a_duplicate(self):
        assert is_structural_duplicate("this <<< not sql", [F1]) is False
        assert is_structural_duplicate(F1, []) is False
        assert query_signature("") is None
