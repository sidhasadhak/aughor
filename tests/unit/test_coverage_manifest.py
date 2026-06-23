"""L2 coverage manifest — the data-derived question space (replaces the fixed angle ceiling).

The point these tests pin: the manifest SCALES WITH THE DATA (more measures/dimensions/time
→ more cells), is profile-led with a profiled-measure fallback so the business profile's blind
spots can't silently shrink it, and prunes immaterial cuts.
"""
from __future__ import annotations

from aughor.explorer.coverage_manifest import build_manifest, summarize
from aughor.tools.profiler import ColumnProfile, TableProfile


def _measure(table, col):
    return ColumnProfile(table, col, "DOUBLE", "measure", unit="USD", value_range=(0, 1000))


def _dim(table, col, n):
    return ColumnProfile(table, col, "VARCHAR", "dimension", distinct_count=n, is_low_cardinality=(n <= 50))


def _id(table, col):
    return ColumnProfile(table, col, "BIGINT", "id", is_fk=True, distinct_count=99999)


def _cp(*cols):
    return {f"{c.table}.{c.column}": c for c in cols}


class TestMateriality:
    def test_measure_gets_headline_plus_each_material_dimension(self):
        cp = _cp(_measure("orders", "amount"), _dim("orders", "region", 5), _dim("orders", "channel", 3))
        cells = build_manifest({}, cp)
        dims = {c.cut for c in cells if c.axis == "dimension"}
        assert dims == {"region", "channel"}
        assert any(c.axis == "headline" for c in cells)

    def test_prunes_ids_fks_and_high_cardinality_dimensions(self):
        cp = _cp(
            _measure("orders", "amount"),
            _id("orders", "order_id"),                  # id/fk → not a dimension, not a measure
            _dim("orders", "customer_name", 9000),      # high-cardinality near-key → pruned
            _dim("orders", "status", 4),                # material
        )
        cells = build_manifest({}, cp)
        assert {c.cut for c in cells if c.axis == "dimension"} == {"status"}

    def test_geo_coordinates_are_not_treated_as_measures(self):
        # "total longitude" is grounded but meaningless — exclude coordinates (on-target fix).
        cp = _cp(
            ColumnProfile("geo", "lng", "DOUBLE", "measure", value_range=(-180, 180)),
            ColumnProfile("geo", "longitude", "DOUBLE", "measure", value_range=(-180, 180)),
            ColumnProfile("geo", "customer_lat", "DOUBLE", "measure", value_range=(-90, 90)),
            _measure("geo", "revenue"),                 # a real measure on the same table
        )
        metrics = {c.metric for c in build_manifest({}, cp) if c.source == "profiled_measure"}
        assert metrics == {"revenue"}                   # coordinates dropped, revenue kept

    def test_coordinate_match_does_not_false_exclude_real_columns(self):
        # precise matching: 'latency_ms' / 'belong_count' are NOT coordinates
        cp = _cp(ColumnProfile("t", "latency_ms", "DOUBLE", "measure", unit="ms", value_range=(0, 999)))
        assert {c.metric for c in build_manifest({}, cp)} == {"latency_ms"}

    def test_a_measure_without_unit_or_range_is_skipped(self):
        bare = ColumnProfile("t", "raw_num", "DOUBLE", "measure")   # no unit/range → not baseline-worthy
        cells = build_manifest({}, _cp(bare, _dim("t", "kind", 3)))
        assert cells == []


class TestTimeAxes:
    def _with_periods(self, n):
        tp = {"orders": TableProfile("orders", primary_timestamp="ordered_at", n_periods=n)}
        return build_manifest(tp, _cp(_measure("orders", "amount")))

    def test_no_time_without_enough_periods(self):
        assert {c.axis for c in self._with_periods(2)} == {"headline"}

    def test_trend_unlocks_then_seasonality_then_yoy(self):
        assert "trend" in {c.axis for c in self._with_periods(6)}
        axes12 = {c.axis for c in self._with_periods(12)}
        assert {"trend", "seasonality"} <= axes12 and "yoy" not in axes12
        assert "yoy" in {c.axis for c in self._with_periods(36)}


class TestProfileLedWithFallback:
    def test_north_star_kpi_mapped_to_table_is_profile_sourced(self):
        cp = _cp(_measure("orders", "amount"), _dim("orders", "region", 5))
        ns = [{"name": "Average Order Value", "maps_to": "orders.amount / orders.id"}]
        cells = build_manifest({}, cp, north_star=ns)
        assert any(c.source == "profile" and c.metric == "Average Order Value" for c in cells)

    def test_fallback_adds_a_measure_the_profile_never_named(self):
        # profile names 'amount' but NOT 'shipping_cost' — the fallback must surface it (blind spot)
        cp = _cp(_measure("orders", "amount"), _measure("orders", "shipping_cost"), _dim("orders", "region", 5))
        ns = [{"name": "AOV", "maps_to": "orders.amount"}]
        cells = build_manifest({}, cp, north_star=ns)
        fb = {c.metric for c in cells if c.source == "profiled_measure"}
        assert "shipping_cost" in fb           # blind spot caught
        assert "amount" not in fb              # already covered by the KPI → not duplicated

    def test_unmapped_kpi_still_counts_as_one_baseline(self):
        ns = [{"name": "NPS", "maps_to": "some_survey_we_dont_have"}]
        cells = build_manifest({}, {}, north_star=ns)
        assert cells == [c for c in cells if c.table == "(business)" and c.metric == "NPS"]
        assert len(cells) == 1


class TestScalesWithData:
    def test_more_data_means_more_cells(self):
        small = build_manifest({}, _cp(_measure("t", "m"), _dim("t", "d1", 4)))
        big_cp = _cp(_measure("t", "m1"), _measure("t", "m2"),
                     _dim("t", "d1", 4), _dim("t", "d2", 6), _dim("t", "d3", 8))
        big_tp = {"t": TableProfile("t", primary_timestamp="ts", n_periods=36)}
        big = build_manifest(big_tp, big_cp)
        assert len(big) > 3 * len(small)        # richer data → materially larger question space
        s = summarize(big)
        assert s["total_cells"] == len(big) and s["distinct_metrics"] == 2
