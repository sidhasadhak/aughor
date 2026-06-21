"""Named-metric ↔ SQL coherence guard: the explorer trust gate must reject a finding that
ASSERTS a spend-based metric (ROAS/CAC) over a query with no spend/cost term — the AOV-labelled-
as-ROAS bug ('Email CRM ROAS 6.23' over SUM(order_value)/COUNT(orders)) that poisoned the briefing
and the drill-down. High-precision: real ROAS, passing mentions, and correctly-labelled AOV pass."""
from __future__ import annotations

from aughor.explorer.agent import _mislabeled_named_metric, verify_insight

_AOV_SQL = ("SELECT o.marketing_channel, SUM(o.order_value) / NULLIF(COUNT(DISTINCT o.order_id), 0) "
            "AS aov FROM missimi.orders o GROUP BY o.marketing_channel ORDER BY aov DESC")
_REAL_ROAS_SQL = "SELECT channel, SUM(revenue) / NULLIF(SUM(ad_spend), 0) AS roas FROM perf GROUP BY channel"


def test_aov_labelled_as_roas_is_flagged():
    why = _mislabeled_named_metric("Email CRM has the highest ROAS at 6.23, outperforming display (4.75)", _AOV_SQL)
    assert why and "no ad-spend/cost term" in why


def test_real_roas_with_a_spend_term_passes():
    assert _mislabeled_named_metric("Email CRM ROAS at 6.2 leads", _REAL_ROAS_SQL) is None


def test_correctly_labelled_aov_passes():
    assert _mislabeled_named_metric("Email CRM has the highest AOV at 6.23", _AOV_SQL) is None


def test_passing_mention_without_an_asserted_value_passes():
    assert _mislabeled_named_metric("High AOV channels also convert; ROAS would be worth checking", _AOV_SQL) is None
    assert _mislabeled_named_metric("Email CRM leads on ROAS across channels", _AOV_SQL) is None


def test_cac_over_a_no_spend_query_is_flagged():
    why = _mislabeled_named_metric(
        "CAC is lowest for email at 12.50",
        "SELECT channel, SUM(revenue) / COUNT(DISTINCT customer_id) AS x FROM orders GROUP BY channel")
    assert why and "CAC" in why


def test_non_ratio_query_is_ignored():
    assert _mislabeled_named_metric("ROAS was 6.23", "SELECT channel, SUM(revenue) FROM perf GROUP BY channel") is None


def test_gate_rejects_the_mislabelled_finding():
    # the AOV-as-ROAS finding must not pass the pre-emission trust gate (numbers are grounded in
    # rows, so the ONLY reason to reject is the metric-name mislabel).
    rows = [["email_crm", 6.23], ["display", 4.75]]
    ok, reason = verify_insight(rows, "Email CRM has the highest ROAS at 6.23, then display at 4.75", _AOV_SQL)
    assert ok is False and "ad-spend/cost" in reason
    # the same finding, correctly labelled AOV, passes the gate
    ok2, _ = verify_insight(rows, "Email CRM has the highest AOV at 6.23, then display at 4.75", _AOV_SQL)
    assert ok2 is True
