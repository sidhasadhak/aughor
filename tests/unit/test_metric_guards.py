"""Metric-semantics guards.

#6 _mislabeled_per_grain — a line-item AVG presented as a per-order/per-customer
metric (AVG(line_total) AS aov). True AOV = SUM(revenue)/COUNT(DISTINCT order); the
line-item average undercounts (the live $467-vs-$1108 mislabel).

#5 _semantic_metric_drift — a repair that swaps a metric column across business
meanings (revenue↔cost). An LLM faithfulness check rates these "faithful"; the
deterministic column-group swap is the reliable signal (cf. de-temporalisation).
"""
from aughor.explorer.agent import _mislabeled_per_grain, _semantic_metric_drift


# ── #6 per-grain mislabel ─────────────────────────────────────────────────────

def test_line_item_avg_labelled_aov_is_flagged():
    assert _mislabeled_per_grain("SELECT AVG(oi.line_total) AS aov FROM order_items oi") is True
    # mislabel can come from the narration, not just the alias
    assert _mislabeled_per_grain("SELECT AVG(line_total) FROM oi", "AOV of $467 for these customers") is True


def test_genuine_per_order_metrics_not_flagged():
    assert _mislabeled_per_grain("SELECT AVG(order_total) AS aov FROM orders") is False          # per-order column
    assert _mislabeled_per_grain("SELECT SUM(revenue)/COUNT(DISTINCT order_id) AS aov FROM o") is False  # real ratio


def test_honestly_labelled_line_average_not_flagged():
    assert _mislabeled_per_grain("SELECT AVG(line_total) AS avg_line_value FROM oi") is False
    assert _mislabeled_per_grain("SELECT AVG(rating) AS avg_rating FROM reviews") is False


# ── #5 semantic metric drift ──────────────────────────────────────────────────

def test_revenue_to_cost_swap_is_drift():
    assert _semantic_metric_drift(
        "SELECT cat, SUM(revenue) t FROM s GROUP BY cat",
        "SELECT cat, SUM(cost) t FROM s GROUP BY cat") is True


def test_price_to_quantity_swap_is_drift():
    assert _semantic_metric_drift("SELECT SUM(unit_price) FROM x", "SELECT SUM(quantity) FROM x") is True


def test_typo_fix_is_not_drift():
    # revenu → revenue: only the corrected name belongs to a metric group → no swap.
    assert _semantic_metric_drift("SELECT SUM(revenu) FROM x", "SELECT SUM(revenue) FROM x") is False


def test_dimension_swap_is_not_drift():
    assert _semantic_metric_drift(
        "SELECT old_dim, SUM(revenue) FROM x GROUP BY old_dim",
        "SELECT new_dim, SUM(revenue) FROM x GROUP BY new_dim") is False


def test_identical_sql_is_not_drift():
    assert _semantic_metric_drift("SELECT SUM(revenue) FROM x", "SELECT SUM(revenue) FROM x") is False
