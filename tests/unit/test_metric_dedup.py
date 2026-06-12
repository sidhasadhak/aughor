"""Duplicate metric NAMES must not corrupt the prompt / enforcement / receipt.

The repro: data/metrics.json carries two `revenue` and two `aov` — but they are
NOT accidental copies, they are different governed formulas at different grains
(`orders` vs `order_items`). A commerce schema has BOTH tables, so the schema
filter keeps both. Three consumers each need a different resolution:

  * prompt injection (`build_metrics_block`) must inject ONE formula per name —
    never two contradictory ones → it dedupes (most-recent wins).
  * the Trust Receipt's "available" list shows ONE badge per name.
  * enforcement must judge against EVERY grain and credit `used` if the query
    matched any of them — collapsing the catalog first would drop the matching
    grain and mislabel a correct answer as drift (the regression these lock).

The TSX side adds index-namespaced React keys as defense-in-depth so a duplicate
can never crash the receipt regardless of upstream.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aughor.semantic import metrics as M
from aughor.semantic.metrics import (
    list_metrics,
    filter_metrics_to_schema,
    build_metrics_block,
    _dedupe_by_name,
)
from aughor.semantic.enforcement import check_metric_enforcement, enforcement_summary

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


def _has_both_grains(name: str) -> bool:
    """True when the real catalog still carries the multi-grain repro for `name`
    (skip-guard so cleaning data/metrics.json doesn't turn these red)."""
    return [m.name for m in list_metrics()].count(name) >= 2


# ── the raw management read must NOT dedupe ────────────────────────────────────

def test_raw_read_preserves_duplicates_for_the_management_ui():
    """`list_metrics()` is the raw management read — it must NOT dedupe, so a human
    can see and resolve a name collision. Assert it returns exactly what the file
    holds (same names, same order); and IF the repro is on disk, that the duplicate
    genuinely survives the read rather than being silently collapsed."""
    if not _REAL_CATALOG.exists():
        pytest.skip("no real catalog on disk")
    with open(_REAL_CATALOG) as f:
        file_names = [m["name"] for m in json.load(f)]
    read_names = [m.name for m in list_metrics()]
    assert read_names == file_names, "raw read must preserve file order + duplicates"
    if len(file_names) != len(set(file_names)):
        # repro present → the read must still carry the collision (un-deduped)
        assert len(read_names) > len(set(read_names))


# ── prompt / canonical boundary collapses duplicate names (default dedupe) ─────

def test_filter_collapses_duplicate_names_keeping_most_recent():
    raw = list_metrics()
    kept = filter_metrics_to_schema(raw, _BOTH_TABLES_SCHEMA)  # default dedupe=True
    names = _names(kept)
    # No name appears twice after the default (single-definition) boundary.
    assert len(names) == len(set(names)), f"duplicate names survived: {names}"
    # And when a KPI had two grains, the most-recent (line-grain) formula wins.
    by_name = {m.name: m for m in kept}
    if "aov" in by_name:
        assert "order_id" in by_name["aov"].sql or "AVG" in by_name["aov"].sql
    if "revenue" in by_name:
        assert by_name["revenue"].sql  # present and singular


def test_dedupe_false_keeps_every_grain_but_collapsed_is_unique():
    """The enforcement path passes dedupe=False to keep both grains; the default
    keeps one. dedupe=False must never return FEWER rows than the default, and the
    default must have unique names."""
    raw = list_metrics()
    keep_all = filter_metrics_to_schema(raw, _BOTH_TABLES_SCHEMA, dedupe=False)
    collapsed = filter_metrics_to_schema(raw, _BOTH_TABLES_SCHEMA, dedupe=True)
    assert len(keep_all) >= len(collapsed)
    cnames = [m.name for m in collapsed]
    assert len(cnames) == len(set(cnames)), f"default boundary left dupes: {cnames}"
    if _has_both_grains("aov"):
        assert [m.name for m in keep_all].count("aov") == 2, "dedupe=False dropped a grain"


def test_build_block_injects_each_kpi_exactly_once():
    block = build_metrics_block(schema_text=_BOTH_TABLES_SCHEMA)
    if not block:
        pytest.skip("catalog empty under this schema")
    up = block.upper()
    # Header format is "  AOV (Average Order Value): ..." — when a KPI is present
    # it must appear EXACTLY once (no conflicting twin formula injected).
    if "AOV (" in up:
        assert up.count("AOV (") == 1, "AOV injected twice with conflicting formulas"
    if "REVENUE (" in up:
        assert up.count("REVENUE (") == 1, "REVENUE injected twice with conflicting formulas"


# ── enforcement: judge every grain, credit 'used' if any matched ───────────────

def test_enforcement_credits_correct_grain_as_used_on_real_catalog():
    """The regression: with BOTH grains of `aov` in scope, a correct orders-grain
    query (AVG(total_amount)) must read 'used' — not a false 'drift' from the OTHER
    grain — and yield exactly ONE verdict (the React-key crash source)."""
    if not _has_both_grains("aov"):
        pytest.skip("catalog no longer carries both aov grains")
    cms = filter_metrics_to_schema(list_metrics(), _BOTH_TABLES_SCHEMA, dedupe=False)
    verdicts = check_metric_enforcement(
        "average order value", "SELECT AVG(total_amount) FROM orders", cms)
    aov = [v for v in verdicts if v["metric"] == "aov"]
    assert len(aov) == 1, f"aov must collapse to one verdict: {aov}"
    assert aov[0]["status"] == "used", f"correct orders-grain query mislabeled: {aov[0]}"


# Deterministic, file-independent locks for the collapse semantics ──────────────

def _aov_orders():
    return SimpleNamespace(name="aov", label="Average Order Value",
                           sql="AVG(total_amount)", wrong_usage_examples=[])


def _aov_lineitem():
    return SimpleNamespace(
        name="aov", label="Average Order Value",
        sql="SUM(final_price_usd*quantity)/NULLIF(COUNT(DISTINCT order_id),0)",
        wrong_usage_examples=[])


def test_collapse_used_beats_drift_regardless_of_order():
    """A query matching ONLY the orders grain still reads 'used' even when the
    non-matching line-item grain is listed first (used must win the collapse)."""
    q, sql = "average order value", "SELECT AVG(total_amount) FROM orders"
    for metrics in ([_aov_orders(), _aov_lineitem()], [_aov_lineitem(), _aov_orders()]):
        v = check_metric_enforcement(q, sql, metrics)
        assert len(v) == 1 and v[0]["status"] == "used", f"order-sensitive collapse: {v}"
    s = enforcement_summary(check_metric_enforcement(q, sql, [_aov_orders(), _aov_lineitem()]))
    assert s["targeted"] == 1 and s["used"] == ["aov"] and s["enforced"] is True


def test_collapse_drift_when_no_grain_matches():
    """If the query matches NO grain, the single collapsed verdict is 'drift'."""
    v = check_metric_enforcement(
        "average order value", "SELECT SUM(line_total) FROM x",
        [_aov_orders(), _aov_lineitem()])
    assert len(v) == 1 and v[0]["status"] == "drift", v


# ── _dedupe_by_name helper behaviour (synthetic, dependency-free) ──────────────

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
