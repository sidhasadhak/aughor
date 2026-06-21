"""Metric-resolution fixes surfaced by a data-driven sweep: beautycommerce revenue/AOV
were undercounting ~50% because the LLM intermittently dropped the quantity multiplier.

Root causes, both in the global-metric machinery:
  1. _metric_matches_schema checked tables + dimensions but NOT the formula's columns,
     so a metric like revenue=SUM(total_amount) injected into a connection that has no
     total_amount (the observed AVG(total_amount) leak into beautycommerce).
  2. _apply_ontology_overlay dropped a curated catalog metric whenever the ontology had
     an unverified same-NAME metric — even one with a DIFFERENT (failed-template) formula
     — silently stripping the correct catalog revenue/AOV from the LLM prompt.
"""
from types import SimpleNamespace

from aughor.semantic.metrics import (
    MetricDefinition, _formula_columns, _metric_matches_schema, _apply_ontology_overlay,
)


def _m(name, sql, tables=(), dims=()):
    return MetricDefinition(name=name, label=name, sql=sql, tables=list(tables), dimensions=list(dims))


class TestFormulaColumns:
    def test_simple_sum(self):
        assert _formula_columns("SUM(total_amount)") == {"total_amount"}

    def test_product(self):
        assert _formula_columns("SUM(final_price_usd * quantity)") == {"final_price_usd", "quantity"}

    def test_ratio_with_distinct(self):
        cols = _formula_columns("SUM(final_price_usd * quantity) / NULLIF(COUNT(DISTINCT order_id), 0)")
        assert cols == {"final_price_usd", "quantity", "order_id"}

    def test_functions_are_not_columns(self):
        assert _formula_columns("SUM(x)") == {"x"}  # SUM is a function, not a column

    def test_malformed_returns_empty(self):
        assert _formula_columns("this is not sql ((") == set()


class TestMetricMatchesSchema:
    def test_formula_column_absent_drops(self):
        # the leak: revenue=SUM(total_amount) must NOT match a schema lacking total_amount
        m = _m("revenue", "SUM(total_amount)", tables=["orders"])
        assert _metric_matches_schema(m, {"orders"}, {"o_totalprice", "o_orderkey"}) is False

    def test_formula_columns_present_keeps(self):
        m = _m("revenue", "SUM(final_price_usd * quantity)", tables=["order_items"])
        assert _metric_matches_schema(m, {"order_items"}, {"final_price_usd", "quantity", "product_id"}) is True

    def test_table_absent_still_drops(self):
        m = _m("revenue", "SUM(x)", tables=["nonesuch"])
        assert _metric_matches_schema(m, {"orders"}, {"x"}) is False

    def test_dimension_absent_still_drops(self):
        m = _m("revenue", "SUM(x)", tables=["orders"], dims=["region"])
        assert _metric_matches_schema(m, {"orders"}, {"x"}) is False

    def test_malformed_formula_adds_no_constraint(self):
        # conservative: an unparseable formula yields no columns, so we don't over-drop
        m = _m("revenue", "weird((", tables=["orders"])
        assert _metric_matches_schema(m, {"orders"}, set()) is True


class TestOntologyOverlayKeepsCuratedCatalog:
    def _patch_ontology(self, monkeypatch, metrics):
        graph = SimpleNamespace(validated=True, metrics=metrics)
        monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda cid: graph)

    def test_unverified_DIFFERENT_formula_keeps_catalog(self, monkeypatch):
        # beautycommerce: catalog revenue=SUM(final_price_usd*quantity); ontology revenue=
        # SUM(total_amount) unverified (failed template) → curated catalog must SURVIVE.
        cat = [_m("revenue", "SUM(final_price_usd * quantity)", tables=["order_items"])]
        om = SimpleNamespace(id="revenue", display_name="revenue", verified=False, formula_sql="SUM(total_amount)")
        self._patch_ontology(monkeypatch, {"revenue": om})
        out = _apply_ontology_overlay(cat, "c1")
        assert len(out) == 1 and out[0].sql == "SUM(final_price_usd * quantity)"

    def test_unverified_SAME_formula_drops(self, monkeypatch):
        # preserve the original protection: validator tested THIS exact formula → drop it
        cat = [_m("revenue", "SUM(a)*SUM(b)", tables=["t"])]
        om = SimpleNamespace(id="revenue", display_name="revenue", verified=False, formula_sql="SUM(a)*SUM(b)")
        self._patch_ontology(monkeypatch, {"revenue": om})
        assert _apply_ontology_overlay(cat, "c1") == []

    def test_verified_corrects_the_formula(self, monkeypatch):
        cat = [_m("revenue", "SUM(wrong)", tables=["t"])]
        om = SimpleNamespace(id="revenue", display_name="revenue", verified=True, formula_sql="SUM(right)")
        self._patch_ontology(monkeypatch, {"revenue": om})
        out = _apply_ontology_overlay(cat, "c1")
        assert len(out) == 1 and out[0].sql == "SUM(right)"


# ── build_metrics_block re-filters AFTER the ontology overlay (2026-06-21) ──────
# The overlay can INJECT a verified ontology metric with no catalog counterpart, and that
# injection wasn't schema-checked — so a stale ontology formula (revenue=SUM(total_amount)
# on a connection whose orders has order_value) leaked a missing-column formula into the
# prompt. build_metrics_block now re-applies the schema filter after the overlay.
def test_build_metrics_block_filters_overlay_injected_metric(monkeypatch):
    from aughor.semantic import metrics as M
    # schema has order_value, NOT total_amount (two-space col format the parser expects)
    schema = "TABLE: orders\n  order_id  BIGINT\n  order_value  DOUBLE\n"
    _tables, _cols = M._schema_tables_and_columns(schema)
    assert "orders" in _tables and "order_value" in _cols and "total_amount" not in _cols
    bad = _m("revenue", "SUM(total_amount)", tables=("orders",))  # stale formula, missing column
    # overlay injects the stale metric (as if from a verified-but-stale ontology)
    monkeypatch.setattr(M, "_apply_ontology_overlay", lambda ms, cid: list(ms) + [bad])
    monkeypatch.setattr(M, "list_metrics", lambda *a, **k: [])    # empty catalog
    out = M.build_metrics_block(schema_text=schema, connection_id="c")
    assert "total_amount" not in out   # the injected missing-column metric is filtered out


def test_build_metrics_block_keeps_overlay_metric_with_valid_columns(monkeypatch):
    from aughor.semantic import metrics as M
    schema = "TABLE: orders\n  order_id  BIGINT\n  order_value  DOUBLE\n"
    good = _m("revenue", "SUM(order_value)", tables=("orders",))  # valid column
    monkeypatch.setattr(M, "_apply_ontology_overlay", lambda ms, cid: list(ms) + [good])
    monkeypatch.setattr(M, "list_metrics", lambda *a, **k: [])
    out = M.build_metrics_block(schema_text=schema, connection_id="c")
    assert "order_value" in out   # a valid overlay-injected metric survives
