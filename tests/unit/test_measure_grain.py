"""Measure-grain detection — the additivity semantic layer.

The pure classifier (classify_from_buckets) decides per-unit vs per-line from AVG-by-
quantity buckets, the signal verified live on beautycommerce (final_price_usd flat 1/1/1
→ per_unit; gross_margin_usd 1/2/3 → per_line). These pin the decision logic exhaustively
and the conservative 'unknown' fallback (it must never mislabel a noisy measure)."""
from aughor.semantic.measure_grain import (
    classify_from_buckets, measure_grain_misuse, render_grains_block,
)

# beautycommerce grains (detected live): final_price_usd per-unit, gross_margin_usd per-line.
GRAINS = {"final_price_usd": "per_unit", "unit_price_usd": "per_unit",
          "cogs_usd": "per_unit", "gross_margin_usd": "per_line"}
QCOLS = {"quantity"}


def _b(*pairs, n=1000):
    """buckets helper: _b((1,40.0),(2,40.1)) → [(1,40.0,n),(2,40.1,n)]"""
    return [(q, avg, n) for q, avg in pairs]


class TestPerUnit:
    def test_flat_is_per_unit(self):
        # final_price_usd shape: AVG flat across quantity
        assert classify_from_buckets(_b((1, 39.1), (2, 39.08), (3, 39.1))) == "per_unit"

    def test_flat_with_noise_within_tol(self):
        assert classify_from_buckets(_b((1, 40.0), (2, 43.0), (3, 38.0))) == "per_unit"

    def test_negative_flat_per_unit(self):
        assert classify_from_buckets(_b((1, -5.0), (2, -5.1), (3, -4.9))) == "per_unit"


class TestPerLine:
    def test_scales_is_per_line(self):
        # gross_margin_usd shape: AVG ≈ k × base
        assert classify_from_buckets(_b((1, 26.91), (2, 53.79), (3, 80.72))) == "per_line"

    def test_scales_with_noise_within_tol(self):
        assert classify_from_buckets(_b((1, 27.0), (2, 52.0), (3, 83.0))) == "per_line"

    def test_negative_per_line_scales(self):
        # margin can be negative; ratio preserves sign so scaling is still detected
        assert classify_from_buckets(_b((1, -10.0), (2, -20.0), (3, -30.0))) == "per_line"


class TestUnknownIsConservative:
    def test_ambiguous_slope_is_unknown(self):
        # ratio 1.5 — neither flat (≈1) nor linear (≈2) → don't guess
        assert classify_from_buckets(_b((1, 40.0), (2, 60.0))) == "unknown"

    def test_single_bucket_is_unknown(self):
        assert classify_from_buckets(_b((1, 40.0))) == "unknown"

    def test_zero_baseline_is_unknown(self):
        assert classify_from_buckets(_b((1, 0.0), (2, 0.0), (3, 0.0))) == "unknown"

    def test_too_few_rows_is_unknown(self):
        assert classify_from_buckets([(1, 40.0, 50), (2, 80.0, 50)]) == "unknown"

    def test_missing_q1_baseline_is_unknown(self):
        assert classify_from_buckets([(2, 80.0, 1000), (3, 120.0, 1000)]) == "unknown"

    def test_empty_is_unknown(self):
        assert classify_from_buckets([]) == "unknown"

    def test_partial_scale_then_flat_is_unknown(self):
        # q=2 looks per-line (≈2) but q=3 looks flat (≈1) — inconsistent → unknown
        assert classify_from_buckets(_b((1, 30.0), (2, 60.0), (3, 31.0))) == "unknown"


class TestGrainMisuseGuard:
    def test_the_gross_margin_double_count_bug(self):
        # the exact Q3 investigation bug: per-line margin × quantity
        r = measure_grain_misuse(
            "SELECT product_id, SUM(gross_margin_usd * quantity) AS m FROM order_items GROUP BY 1",
            GRAINS, QCOLS)
        assert r and "DOUBLE-count" in r

    def test_the_revenue_undercount_bug(self):
        # per-unit price summed without × quantity (the $252M-vs-$503M bug)
        r = measure_grain_misuse("SELECT SUM(final_price_usd) FROM order_items", GRAINS, QCOLS)
        assert r and "under-counts" in r

    def test_correct_revenue_is_silent(self):
        assert measure_grain_misuse(
            "SELECT SUM(final_price_usd * quantity) FROM order_items", GRAINS, QCOLS) is None

    def test_correct_margin_is_silent(self):
        # per-line margin summed directly = correct
        assert measure_grain_misuse(
            "SELECT SUM(gross_margin_usd) FROM order_items", GRAINS, QCOLS) is None

    def test_per_unit_times_non_quantity_is_silent(self):
        # final_price_usd * discount_pct — the other operand is not a quantity → don't flag
        assert measure_grain_misuse(
            "SELECT SUM(final_price_usd * discount_pct) FROM order_items", GRAINS, QCOLS) is None

    def test_unknown_grain_is_silent(self):
        # a measure we couldn't classify must not be flagged
        assert measure_grain_misuse("SELECT SUM(mystery_col) FROM t", GRAINS, QCOLS) is None

    def test_count_and_avg_not_flagged(self):
        assert measure_grain_misuse("SELECT COUNT(*), AVG(final_price_usd) FROM t", GRAINS, QCOLS) is None

    def test_malformed_sql_never_raises(self):
        assert measure_grain_misuse("not sql ((", GRAINS, QCOLS) is None


class TestGrainsBlock:
    def test_renders_both_grains_with_quantity_name(self):
        b = render_grains_block({"final_price_usd": "per_unit", "gross_margin_usd": "per_line"}, {"quantity"})
        assert "PER-UNIT" in b and "final_price_usd" in b and "* quantity" in b
        assert "PER-LINE" in b and "gross_margin_usd" in b
        # the actionable rules both appear
        assert "under-counts" in b and "double-counts" in b

    def test_uses_the_detected_quantity_column_name(self):
        b = render_grains_block({"unit_price": "per_unit"}, {"qty"})
        assert "* qty" in b

    def test_empty_grains_is_empty_string(self):
        assert render_grains_block({}, {"quantity"}) == ""
        assert render_grains_block({"x": "unknown"}, {"quantity"}) == ""

    def test_only_per_unit(self):
        b = render_grains_block({"final_price_usd": "per_unit"}, {"quantity"})
        assert "PER-UNIT" in b and "PER-LINE" not in b


class TestOntologyPersistence:
    def _fake_graph(self, props):
        from types import SimpleNamespace
        ent = SimpleNamespace(properties={n: SimpleNamespace(name=n, measure_grain=g) for n, g in props})
        return SimpleNamespace(entities={"e": ent})

    def test_grains_from_ontology_reads_stamped(self, monkeypatch):
        from aughor.semantic import measure_grain as M
        graph = self._fake_graph([("final_price_usd", "per_unit"), ("gross_margin_usd", "per_line"), ("quantity", "")])
        monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda cid: graph)
        g, q = M.grains_from_ontology("c1")
        assert g == {"final_price_usd": "per_unit", "gross_margin_usd": "per_line"}
        assert "quantity" in q

    def test_grains_from_ontology_empty_when_no_ontology(self, monkeypatch):
        monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda cid: None)
        from aughor.semantic.measure_grain import grains_from_ontology
        assert grains_from_ontology("c1") == ({}, set())

    def test_connection_grains_seeds_from_ontology_without_probing(self, monkeypatch):
        # the persistence payoff: when grains are stamped on the ontology, no DB probe runs.
        from aughor.semantic import measure_grain as M
        M._GRAIN_CACHE.pop("c1_seed", None)
        graph = self._fake_graph([("final_price_usd", "per_unit"), ("quantity", "")])
        monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda cid: graph)

        class _NoProbeDB:
            def execute(self, *a, **k):
                raise AssertionError("probed the DB despite grains being on the ontology")

        g, q = M.connection_measure_grains("c1_seed", _NoProbeDB(), {"t": ["final_price_usd", "quantity"]})
        assert g == {"final_price_usd": "per_unit"} and "quantity" in q
