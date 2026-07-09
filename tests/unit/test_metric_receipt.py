"""Metric-definition receipt (T4-1, 2026-07-09).

Deep-Analysis audit finding: every deep run silently resolved an ambiguous metric — "refund rate" as
value-weighted refund$/revenue$ (18.8%) vs count-based orders-with-refund/orders (20.2%); "revenue"
off invoices vs line items — with the definition buried in the intake spec and no disclosure of the
reading chosen. `_metric_definition_receipt` surfaces the formula + interpretation on the report.
See aughor/agent/investigate.py.
"""
from aughor.agent.investigate import _metric_definition_receipt


def test_ratio_receipt_names_the_value_weighted_reading():
    r = _metric_definition_receipt({
        "metric_label": "refund rate",
        "metric_sql": "SUM(analytics.refunds.refund_amount_usd) / NULLIF(SUM(analytics.order_items.line_revenue_usd), 0) * 100",
        "metric_table": "analytics.refunds",
        "data_coverage_label": "2023-01-01 → 2025-01-09",
    })
    assert r.startswith("refund rate —")
    assert "value-weighted ratio" in r
    assert "not a count-based rate" in r
    assert "2023-01-01 → 2025-01-09" in r


def test_average_metric_flagged_non_additive():
    r = _metric_definition_receipt({"metric_label": "avg order value", "metric_sql": "AVG(order_total)"})
    assert "per-record average" in r
    assert "non-additive" in r


def test_additive_metric_just_states_formula():
    r = _metric_definition_receipt({"metric_label": "total revenue", "metric_sql": "SUM(line_revenue_usd)",
                                    "metric_table": "order_items"})
    assert r.startswith("total revenue —")
    assert "value-weighted ratio" not in r and "per-record average" not in r
    assert "on order_items" in r


def test_empty_when_no_metric():
    assert _metric_definition_receipt({}) == ""
    assert _metric_definition_receipt({"metric_label": "", "metric_sql": ""}) == ""


def test_never_raises_on_bad_input():
    assert _metric_definition_receipt({"metric_sql": None, "metric_label": None}) == ""
