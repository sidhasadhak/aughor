"""Phase-8 temporal-feasibility gate (#1) + repair intent-preservation trigger (#2).
Both platform-generic. See aughor/explorer/agent.py (_is_temporal_angle, _query_columns)."""
from aughor.explorer.agent import (
    _is_temporal_angle, _query_columns, _has_temporal_sql, _has_vacuous_temporal,
)


# ── #1: temporal-angle classification ─────────────────────────────────────────

def test_temporal_angles_flagged():
    for a in ["trends", "seasonality", "retention", "customer_lifecycle", "cohort_analysis",
              "churn", "aging", "lead_times", "growth", "recency", "tenure", "over_time"]:
        assert _is_temporal_angle(a), f"{a} should be temporal"


def test_nontemporal_angles_not_flagged():
    for a in ["volume", "value", "receivables", "margins", "basket_composition", "channel_mix",
              "distribution", "ranking", "anomalies", "supplier_performance", "refund_rate",
              "conversion", "inventory_health"]:
        assert not _is_temporal_angle(a), f"{a} should NOT be temporal"


# ── #2: column-substitution detection (the faithfulness trigger) ──────────────

def test_query_columns_extracts_real_columns():
    cols = _query_columns(
        "SELECT i.invoice_date, i.net_revenue FROM invoices i WHERE i.invoice_date >= '2025-01-01'")
    assert "invoice_date" in cols and "net_revenue" in cols


def test_substitution_detected_on_the_invoice_case():
    # the exact failure: invoice AGE (date) repaired to a payment-DELAY column
    orig = ("SELECT DATE_DIFF('DAY', i.invoice_date, CURRENT_DATE) AS age, SUM(i.net_revenue) r "
            "FROM invoices i WHERE i.invoice_date >= '2025-05-17'")
    fixed = ("SELECT i.invoice_delay_days AS age, SUM(i.revenue_net) r "
             "FROM analytics.invoices i WHERE i.invoice_delay_days <= 365")
    removed = _query_columns(orig) - _query_columns(fixed)
    added = _query_columns(fixed) - _query_columns(orig)
    assert "invoice_date" in removed and "net_revenue" in removed   # → triggers faithfulness check
    assert "invoice_delay_days" in added and "revenue_net" in added


def test_join_add_is_not_a_substitution():
    # T2 missing-table repair ADDS a join — removes no columns → no faithfulness check
    orig = "SELECT o.order_id, oi.quantity FROM orders o"
    fixed = "SELECT o.order_id, oi.quantity FROM orders o JOIN order_items oi ON o.order_id=oi.order_id"
    assert (_query_columns(orig) - _query_columns(fixed)) == set()


def test_qualification_is_not_a_substitution():
    # T2 ambiguous repair QUALIFIES order_id → o.order_id; bare name unchanged → no check
    orig = "SELECT order_id FROM orders o JOIN order_items oi ON o.order_id=oi.order_id"
    fixed = "SELECT o.order_id FROM orders o JOIN order_items oi ON o.order_id=oi.order_id"
    assert (_query_columns(orig) - _query_columns(fixed)) == set()


def test_pure_typo_rename_is_a_substitution():
    orig = "SELECT SUM(net_revenue) FROM invoices"
    fixed = "SELECT SUM(revenue_net) FROM invoices"
    assert (_query_columns(orig) - _query_columns(fixed)) == {"net_revenue"}


# ── #2: de-temporalisation detector (the deterministic drift signal) ──────────

def _detemporalised(orig, fixed):
    """The exact decision the explorer makes: substituted columns AND the original computed
    over time but the repair no longer does."""
    removed = _query_columns(orig) - _query_columns(fixed)
    return bool(removed) and _has_temporal_sql(orig) and not _has_temporal_sql(fixed)


def test_has_temporal_sql_positive():
    for s in ["SELECT DATE_DIFF('DAY', a, CURRENT_DATE) FROM t",
              "SELECT x FROM t WHERE d >= '2025-05-17'",
              "SELECT date_trunc('month', ts) FROM t",
              "SELECT x FROM t WHERE ts > NOW() - INTERVAL 30 DAY"]:
        assert _has_temporal_sql(s), s


def test_has_temporal_sql_negative():
    for s in ["SELECT invoice_delay_days, revenue_net FROM invoices WHERE invoice_delay_days <= 365",
              "SELECT category, SUM(amount) FROM sales GROUP BY category",
              "SELECT status, COUNT(*) FROM invoices GROUP BY status"]:
        assert not _has_temporal_sql(s), s


def test_detemporalisation_drops_the_invoice_repair():
    orig = ("SELECT DATE_DIFF('DAY', i.invoice_date, CURRENT_DATE) AS age, SUM(i.net_revenue) "
            "FROM invoices i WHERE i.invoice_date >= '2025-05-17'")
    fixed = ("SELECT i.invoice_delay_days AS age, SUM(i.revenue_net) "
             "FROM analytics.invoices i WHERE i.invoice_delay_days <= 365")
    assert _detemporalised(orig, fixed) is True   # → DROP


def test_no_false_drop_when_repair_keeps_time():
    # a date-column typo fix (order_dt -> order_ts) keeps temporal logic → NOT a drop
    orig = "SELECT order_dt FROM orders WHERE order_dt >= '2025-01-01'"
    fixed = "SELECT order_ts FROM orders WHERE order_ts >= '2025-01-01'"
    assert _detemporalised(orig, fixed) is False


def test_no_false_drop_on_nontemporal_rename():
    # net_revenue -> revenue_net, neither side temporal → not a de-temporalisation
    assert _detemporalised("SELECT SUM(net_revenue) FROM invoices",
                           "SELECT SUM(revenue_net) FROM invoices") is False


def test_no_false_drop_on_join_add():
    assert _detemporalised("SELECT o.order_id, oi.quantity FROM orders o",
                           "SELECT o.order_id, oi.quantity FROM orders o "
                           "JOIN order_items oi ON o.order_id=oi.order_id") is False


# ── vacuous temporal: DATE_DIFF of identical dates (a constant-0 "age") ────────

def test_vacuous_datediff_current_date_self():
    # the observed second drift: a repair fakes age as DATE_DIFF(CURRENT_DATE, CURRENT_DATE) = 0
    assert _has_vacuous_temporal(
        "SELECT DATE_DIFF('DAY', CURRENT_DATE, CURRENT_DATE) AS age, SUM(revenue_net) FROM invoices") is True


def test_vacuous_datediff_same_column():
    assert _has_vacuous_temporal("SELECT DATEDIFF(i.d, i.d) FROM t i") is True


def test_genuine_datediff_is_not_vacuous():
    assert _has_vacuous_temporal(
        "SELECT DATE_DIFF('DAY', i.invoice_date, CURRENT_DATE) FROM invoices i") is False


def test_no_datediff_is_not_vacuous():
    assert _has_vacuous_temporal("SELECT category, SUM(amount) FROM sales GROUP BY category") is False


def test_vacuous_caught_even_when_temporal_sql_survives():
    # _has_temporal_sql is True (DATE_DIFF/CURRENT_DATE present) so de-temporalisation misses it;
    # the vacuous check is what catches this repair.
    fixed = "SELECT DATE_DIFF('DAY', CURRENT_DATE, CURRENT_DATE) AS age, SUM(i.revenue_net) FROM invoices i GROUP BY 1"
    assert _has_temporal_sql(fixed) is True
    assert _has_vacuous_temporal(fixed) is True
