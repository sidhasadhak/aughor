"""Narration-inversion guard (aughor.agent.verify.inverted_universal_claim).

The filed bug: a per-group/per-row value gets narrated as a UNIVERSAL per-entity
property. A distribution like (1 item → 3 orders), (2 items → 5 orders) is narrated
as "all orders have 3 items" — one row's number asserted of EVERY entity over data
that visibly varies. The numeric-grounding check can't catch it (3 is a real cell)
and _mislabeled_per_grain only covers AVG-of-line-items.

These pin the detector: it must FIRE on the inversion and stay SILENT on legitimate
prose. The false-positive guard is the whole point — a clumsy version would suppress
valid uniform-result claims or any sentence with 'all'."""
from aughor.agent.verify import inverted_universal_claim


# A distribution that VARIES: order_count differs across item-bucket rows.
# Columns: [items_per_order, order_count]
VARYING = [[1, 3], [2, 5], [3, 2], [4, 1]]


class TestFiresOnInversion:
    def test_the_filed_bug_all_orders_have_3_items(self):
        # "3 orders have 1 item" inverted into "all orders have 3 items". 3 is the
        # order_count of one bucket, not a universal items-per-order.
        r = inverted_universal_claim("All orders have 3 items.", VARYING)
        assert r and "over-generalises" in r

    def test_every_customer_has_2_orders_singular_entity(self):
        # singular entity word, still a universal claim; 2 is one of several values.
        rows = [["north", 2], ["south", 9], ["east", 5]]
        assert inverted_universal_claim("Every customer has 2 orders on average.", rows)

    def test_each_basket_contains_5(self):
        rows = [["a", 5], ["b", 1], ["c", 8]]
        assert inverted_universal_claim("Each basket contains 5 line items.", rows)


class TestSilentOnLegitimateProse:
    def test_uniform_result_is_not_flagged(self):
        # The data genuinely IS uniform — every row's value is 3 — so "all ... 3" is true.
        uniform = [["jan", 3], ["feb", 3], ["mar", 3]]
        assert inverted_universal_claim("All months have 3 launches.", uniform) is None

    def test_non_universal_language_not_flagged(self):
        # "most" / specific subsets are honest descriptions of a distribution.
        assert inverted_universal_claim("Most orders have 3 items; a few have more.", VARYING) is None

    def test_number_absent_from_data_left_to_numeric_verifier(self):
        # 99 is in no column — that's a hallucinated magnitude, the numeric verifier's job.
        assert inverted_universal_claim("All orders have 99 items.", VARYING) is None

    def test_count_of_entities_not_a_per_entity_claim(self):
        # "all 12 months are represented" — number before entity, no possession verb.
        assert inverted_universal_claim("All 12 months are represented in the data.", VARYING) is None

    def test_single_row_result_not_flagged(self):
        # one row can't be a contradicting distribution.
        assert inverted_universal_claim("All orders have 3 items.", [[3, 3]]) is None

    def test_no_universal_quantifier_not_flagged(self):
        assert inverted_universal_claim("Orders average 3 items each in the top bucket.", VARYING) is None


class TestRobustness:
    def test_empty_and_none_inputs_never_raise(self):
        assert inverted_universal_claim("", VARYING) is None
        assert inverted_universal_claim("All orders have 3 items.", []) is None
        assert inverted_universal_claim("All orders have 3 items.", None) is None
        assert inverted_universal_claim(None, VARYING) is None

    def test_non_numeric_rows_do_not_crash(self):
        rows = [["alpha", "beta"], ["gamma", "delta"]]
        assert inverted_universal_claim("All teams have 3 wins.", rows) is None

    def test_decimal_value_match(self):
        rows = [["a", 2.49], ["b", 7.1], ["c", 3.0]]
        assert inverted_universal_claim("All SKUs average 2.49 returns.", rows)


# ── ADA report verifier (cross-surface wiring → DataQualityNote caveat) ────────

def _report(headline="", verdict="", claims=(), actions=()):
    from aughor.agent.state import AnalysisReport, Finding
    return AnalysisReport(
        headline=headline, verdict=verdict,
        key_findings=[Finding(claim=c, evidence="", confidence=0.9) for c in claims],
        what_is_not_the_cause=[], risks=[], recommended_actions=list(actions),
    )


def _qr(columns, rows, error=None):
    from aughor.agent.state import QueryResult
    return QueryResult(hypothesis_id="h1", sql="SELECT 1", columns=columns,
                       rows=rows, row_count=len(rows), error=error)


class TestADAReportVerifier:
    def test_inverted_finding_flagged(self):
        from aughor.agent.verify import verify_universal_claims
        rep = _report(headline="AOV is flat.",
                      claims=["All orders have 3 items, so basket size is uniform."])
        qr = _qr(["items", "order_count"], VARYING)
        reasons = verify_universal_claims(rep, [qr])
        assert reasons and "over-generalises" in reasons[0]

    def test_clean_report_not_flagged(self):
        from aughor.agent.verify import verify_universal_claims
        rep = _report(headline="Revenue grew 12% in Q4.",
                      claims=["The top region drove most of the gain."])
        qr = _qr(["items", "order_count"], VARYING)
        assert verify_universal_claims(rep, [qr]) == []

    def test_uniform_data_not_flagged(self):
        from aughor.agent.verify import verify_universal_claims
        rep = _report(headline="All months have 3 launches.")
        qr = _qr(["month", "launches"], [["jan", 3], ["feb", 3], ["mar", 3]])
        assert verify_universal_claims(rep, [qr]) == []

    def test_errored_query_is_skipped(self):
        from aughor.agent.verify import verify_universal_claims
        rep = _report(headline="All orders have 3 items.")
        qr = _qr(["items", "order_count"], VARYING, error="boom")
        assert verify_universal_claims(rep, [qr]) == []

    def test_empty_report_text_no_crash(self):
        from aughor.agent.verify import verify_universal_claims
        rep = _report()
        assert verify_universal_claims(rep, [_qr(["a"], [[1], [2]])]) == []
