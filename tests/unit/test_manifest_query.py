"""Deterministic manifest-cell → baseline SQL (Tier-1 #4 keystone).

The accuracy-critical assertion is the aggregate choice: an additive measure (currency/count)
SUMs; a rate (fraction/percent, or values in [0,1]) AVGs — summing a rate is meaningless. The
generator only proposes; the Phase-8 guards dispose, so these stay grounded.
"""
from __future__ import annotations

from aughor.explorer.coverage_manifest import ManifestCell
from aughor.explorer.manifest_query import cell_question, cell_to_sql
from aughor.tools.profiler import ColumnProfile, TableProfile


def _additive():
    return ColumnProfile("orders", "amount", "DOUBLE", "measure", unit="USD", value_range=(0, 5000))


def _rate():
    return ColumnProfile("orders", "margin_pct", "DOUBLE", "measure",
                         value_interpretation="fraction 0-1", value_range=(0.0, 1.0))


def _cell(axis, cut=None, metric="amount"):
    return ManifestCell(metric=metric, table="orders", axis=axis, cut=cut, source="profiled_measure")


class TestAggregateSemantics:
    def test_additive_measure_sums(self):
        sql = cell_to_sql(_cell("headline"), TableProfile("orders"), _additive())
        assert sql == "SELECT SUM(amount) AS value FROM orders"

    def test_rate_measure_averages_not_sums(self):
        sql = cell_to_sql(_cell("headline", metric="margin_pct"), TableProfile("orders"), _rate())
        assert "AVG(margin_pct)" in sql and "SUM(" not in sql

    def test_rate_detected_by_value_range_alone(self):
        # no unit hint, but values in [0,1] → treat as a rate
        p = ColumnProfile("t", "conv", "DOUBLE", "measure", value_range=(0.01, 0.4))
        assert "AVG(conv)" in cell_to_sql(_cell("headline", metric="conv"), TableProfile("t"), p)


class TestAxes:
    def test_dimension_breakdown_groups_and_top_n(self):
        sql = cell_to_sql(_cell("dimension", cut="region"), TableProfile("orders"), _additive())
        assert "GROUP BY region" in sql and "ORDER BY value DESC" in sql and "LIMIT 20" in sql

    def test_trend_needs_a_timestamp(self):
        assert cell_to_sql(_cell("trend"), TableProfile("orders"), _additive()) is None  # no ts
        tp = TableProfile("orders", primary_timestamp="ordered_at", time_grain="month")
        sql = cell_to_sql(_cell("trend"), tp, _additive())
        assert "date_trunc('month', ordered_at)" in sql and "ordered_at IS NOT NULL" in sql

    def test_seasonality_and_yoy_use_extract(self):
        tp = TableProfile("orders", primary_timestamp="ts")
        assert "EXTRACT(month FROM ts)" in cell_to_sql(_cell("seasonality"), tp, _additive())
        assert "EXTRACT(year FROM ts)" in cell_to_sql(_cell("yoy"), tp, _additive())

    def test_unmapped_business_kpi_returns_none(self):
        # named KPI with no fact table → reuse its own value_sql/chart_sql, not synthesised
        c = ManifestCell(metric="NPS", table="(business)", axis="headline", cut=None, source="profile")
        assert cell_to_sql(c, None, None) is None

    def test_kpi_cell_with_prevalidated_sql_is_used_verbatim(self):
        # a KPI cell carrying its value_sql is used as-is (already correct), not synthesised
        c = ManifestCell(metric="GMV", table="(kpi)", axis="headline", cut=None, source="profile",
                         sql="SELECT SUM(total_amount) AS value FROM orders WHERE status='paid'")
        assert cell_to_sql(c, None, None) == "SELECT SUM(total_amount) AS value FROM orders WHERE status='paid'"


def test_cell_question_labels_each_axis():
    assert "total amount" in cell_question(_cell("headline")).lower()
    assert "by region" in cell_question(_cell("dimension", cut="region")).lower()
    assert "trend" in cell_question(_cell("trend")).lower()
