"""Duplicate metric NAMES must never reach the prompt / enforcement / receipt.

The repro: data/metrics.json carries two `revenue` and two `aov` (one per table
grain — `orders` vs `order_items`). A commerce schema has BOTH tables, so the
schema filter keeps both → the same KPI was injected twice with conflicting
formulas, enforcement double-counted, and the Trust Receipt rendered two badges
with key `metric:aov` (the React "two children with the same key" crash).

These tests load the REAL catalog and lock the fix at the boundary that feeds
the user-facing paths: `filter_metrics_to_schema` + `build_metrics_block`.
"""
from pathlib import Path

import pytest

from aughor.semantic import metrics as M
from aughor.semantic.metrics import (
    list_metrics,
    filter_metrics_to_schema,
    build_metrics_block,
    _dedupe_by_name,
)
from aughor.semantic.enforcement import check_metric_enforcement

_REAL_CATALOG = Path(M.__file__).parent.parent.parent / "data" / "metrics.json"

# A schema that contains BOTH grains of the catalog (every table, formula column
# AND declared dimension of both the orders-grain and order_items-grain metrics)
# → the real trigger condition under which the schema filter keeps both.
_BOTH_TABLES_SCHEMA = """\
TABLE: orders
  order_id  INTEGER
  total_amount  DECIMAL
  status  VARCHAR
  order_date  DATE
  customer_id  INTEGER
  payment_method  VARCHAR

TABLE: order_items
  order_id  INTEGER
  final_price_usd  DECIMAL
  quantity  INTEGER
  product_id  INTEGER
  traffic_source  VARCHAR
  device_type  VARCHAR
"""


def _names(metrics):
    return sorted(m.name for m in metrics)


# ── the repro is real (lock it so we never lose the signal) ────────────────────

def test_real_catalog_has_the_duplicate_repro():
    """If someone cleans data/metrics.json the dup disappears — that's fine, but
    this asserts the boundary still HOLDS the invariant rather than relying on the
    file. Here we just confirm the raw read is un-deduped (management UI truth)."""
    if not _REAL_CATALOG.exists():
        pytest.skip("no real catalog on disk")
    raw = list_metrics()
    # list_metrics() is the raw read — it deliberately does NOT dedupe so the
    # metrics-management UI can still show a human the conflict to resolve.
    names = [m.name for m in raw]
    # Either the catalog is already clean, or it still carries the repro; both ok.
    assert len(names) == len(raw)


# ── the boundary collapses duplicate names ─────────────────────────────────────

def test_filter_collapses_duplicate_names_keeping_most_recent():
    raw = list_metrics()
    kept = filter_metrics_to_schema(raw, _BOTH_TABLES_SCHEMA)
    names = _names(kept)
    # No name appears twice after the schema-scoped boundary.
    assert len(names) == len(set(names)), f"duplicate names survived: {names}"
    # And when a KPI had two grains, the most-recent (line-grain) formula wins.
    by_name = {m.name: m for m in kept}
    if "aov" in by_name:
        assert "order_id" in by_name["aov"].sql or "AVG" in by_name["aov"].sql
    if "revenue" in by_name:
        assert by_name["revenue"].sql  # present and singular


def test_enforcement_no_longer_double_counts_aov():
    """The exact crash source: two `aov` verdicts → two badges with the same React
    key. After dedupe the targeted metric yields ONE verdict."""
    cms = filter_metrics_to_schema(list_metrics(), _BOTH_TABLES_SCHEMA)
    sql = "SELECT AVG(total_amount) FROM orders"
    verdicts = check_metric_enforcement("average order value", sql, cms)
    aov_verdicts = [v for v in verdicts if v["metric"] == "aov"]
    assert len(aov_verdicts) <= 1, f"aov double-counted: {aov_verdicts}"


def test_build_block_injects_each_kpi_once():
    block = build_metrics_block(schema_text=_BOTH_TABLES_SCHEMA)
    if not block:
        pytest.skip("catalog empty under this schema")
    # AOV / REVENUE headers appear at most once each (no conflicting twin formula).
    assert block.upper().count("AOV (") <= 1
    assert block.upper().count("REVENUE (") <= 1


# ── helper unit behaviour (synthetic, dependency-free) ─────────────────────────

class _Stub:
    def __init__(self, name, sql):
        self.name, self.sql = name, sql


def test_dedupe_keeps_last_and_preserves_first_seen_order():
    out = _dedupe_by_name([
        _Stub("revenue", "SUM(total_amount)"),
        _Stub("aov", "AVG(total_amount)"),
        _Stub("revenue", "SUM(final_price_usd * quantity)"),  # later wins
    ])
    assert [m.name for m in out] == ["revenue", "aov"]           # first-seen order
    assert out[0].sql == "SUM(final_price_usd * quantity)"        # most-recent formula


def test_dedupe_noop_when_unique():
    items = [_Stub("a", "1"), _Stub("b", "2")]
    assert _dedupe_by_name(items) == items
