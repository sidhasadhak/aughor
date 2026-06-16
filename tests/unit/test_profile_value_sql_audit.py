"""Unit tests for the build-time value_sql audit (aughor/profile/validate.py).

Proves the audit drops the two real-path value_sql bugs — a chasm-fan-out ROAS
(structural) and a conversion rate that reads 100% because its denominator was
pre-filtered to converted carts (live boundary) — while keeping correct metrics.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.profile.validate import audit_value_sql, audit_profile, _range_kind

# A chasm: attribution and invoices are each on the many-side of `order`.
TC = {
    "attribution": ["attribution_id", "order_id", "weight"],
    "invoices":    ["invoice_id", "order_id", "revenue_gross"],
    "orders":      ["order_id", "cart_id"],
    "carts":       ["cart_id", "abandoned"],
    "marketing_ledger": ["ledger_id", "spend_usd"],
}


class _Res:
    def __init__(self, val):
        self.rows = [] if val is None else [[str(val)]]
        self.error = None
        self.columns = ["v"]


class FakeConn:
    """A connection that binds anything and returns a fixed scalar — lets the audit
    exercise its static guards + range/boundary check without a live warehouse."""
    dialect = "duckdb"

    def __init__(self, scalar=0.5):
        self._scalar = scalar

    def dry_run(self, _sql):
        return (True, "")

    def execute(self, _hid, _sql):
        return _Res(self._scalar)


class TestRangeKind:
    def test_bounded_ratio(self):
        assert _range_kind("ratio 0-1") == ("ratio01", 1.0)

    def test_percent(self):
        assert _range_kind("percent 0-100") == ("pct100", 100.0)

    def test_unbounded_ratio_is_open(self):
        assert _range_kind("ratio 0-∞")[0] == "open"
        assert _range_kind("ratio 0-inf")[0] == "open"

    def test_currency_is_open(self):
        assert _range_kind("USD") == ("open", None)


class TestStaticGuards:
    def test_chasm_sum_roas_dropped(self):
        # the real Attribution-Weighted ROAS bug: attribution⋈invoices both fan out order_id
        sql = ("SELECT SUM(a.weight * i.revenue_gross) / NULLIF((SELECT SUM(spend_usd) "
               "FROM marketing_ledger), 0) AS roas FROM attribution a "
               "JOIN invoices i ON a.order_id = i.order_id")
        ok, reason = audit_value_sql(sql, TC, FakeConn(2.0), "ratio 0-∞")
        assert not ok and "grain bug" in reason

    def test_clean_scalar_kept(self):
        sql = "SELECT SUM(spend_usd) AS spend FROM marketing_ledger"
        ok, _ = audit_value_sql(sql, TC, FakeConn(12345.0), "USD")
        assert ok


class TestRangeBoundary:
    SQL = ("SELECT COUNT(DISTINCT o.order_id) * 1.0 / NULLIF(COUNT(DISTINCT c.cart_id), 0) "
           "AS conv FROM carts c LEFT JOIN orders o ON c.cart_id = o.cart_id WHERE c.abandoned = 0")

    def test_conversion_100pct_dropped(self):
        # the abandoned=0 denominator bug → reads 1.0; degenerate boundary
        ok, reason = audit_value_sql(self.SQL, TC, FakeConn(1.0), "ratio 0-1")
        assert not ok and "boundary" in reason

    def test_correct_conversion_kept(self):
        ok, _ = audit_value_sql(self.SQL, TC, FakeConn(0.18), "ratio 0-1")
        assert ok

    def test_above_bound_dropped(self):
        ok, reason = audit_value_sql(self.SQL, TC, FakeConn(1.36), "ratio 0-1")
        assert not ok and "out of range" in reason

    def test_zero_dropped(self):
        ok, reason = audit_value_sql(self.SQL, TC, FakeConn(0.0), "ratio 0-1")
        assert not ok

    def test_high_but_not_boundary_kept(self):
        # 99.7% is a plausible payment-success rate — must NOT be dropped
        ok, _ = audit_value_sql("SELECT 0.997 AS r", TC, FakeConn(0.997), "ratio 0-1")
        assert ok

    def test_open_ended_zero_dropped(self):
        # no card should read $0 / 0.0 for an open-ended metric
        ok, reason = audit_value_sql("SELECT 0 AS r", TC, FakeConn(0.0), "USD")
        assert not ok


class TestAuditProfile:
    def test_blanks_in_place_and_reports(self):
        good = SimpleNamespace(name="Spend", unit_or_range="USD",
                               value_sql="SELECT SUM(spend_usd) FROM marketing_ledger")
        bad = SimpleNamespace(name="Conversion", unit_or_range="ratio 0-1",
                              value_sql=TestRangeBoundary.SQL)
        profile = SimpleNamespace(north_star_metrics=[good, bad])
        failures = audit_profile(profile, FakeConn(1.0), "marketing_ledger(spend_usd)\ncarts(cart_id)")
        # FakeConn returns 1.0 for both → Spend(USD)=1.0 is fine (not boundary), kept;
        # Conversion(ratio 0-1)=1.0 → boundary → blanked.
        assert "Conversion" in failures
        assert bad.value_sql == ""
        assert good.value_sql  # untouched
