"""Grounded probe compiler — structured intent → grain-safe SQL, no invented columns.

The compiler is the structural guarantee: a probe whose columns are validated against
the real schema compiles to SQL that references only those columns; one the compiler
can't express returns None (caller falls back to free-form). These tests pin the
single-table and star-join cases + the validation gate.
"""
import sqlglot
from aughor.explorer.probe import (
    Probe, ProbeFilter, ProbeHaving, validate_probe, probe_to_sql,
)


class _Prof:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# missimi-like schema
TABLES_COLS = {
    "missimi.order_items": ["order_item_id", "sku_id", "unit_price", "unit_cost",
                            "gross_margin_rate", "category", "order_id"],
    "missimi.orders": ["order_id", "order_value", "marketing_channel", "customer_unique_id"],
}
COL_PROFILES = {
    "missimi.order_items": {
        "unit_price": _Prof(semantic_type="measure", value_range=(1, 200)),
        "unit_cost": _Prof(semantic_type="measure", value_range=(1, 150)),
        "gross_margin_rate": _Prof(semantic_type="measure", unit="percent", value_range=(0, 1)),
        "category": _Prof(semantic_type="dimension", is_low_cardinality=True),
        "sku_id": _Prof(semantic_type="key"),
    },
    "missimi.orders": {
        "order_value": _Prof(semantic_type="measure", value_range=(5, 500)),
        "marketing_channel": _Prof(semantic_type="dimension", is_low_cardinality=True),
    },
}
JOINS = [{"from_table": "missimi.order_items", "from_col": "order_id",
          "to_table": "missimi.orders", "to_col": "order_id", "cardinality": "N:1"}]


def _compile(probe):
    return probe_to_sql(probe, tables_cols=TABLES_COLS, col_profiles=COL_PROFILES,
                        joins=JOINS, dialect="duckdb")


def _parses(sql):
    return sqlglot.parse_one(sql, read="duckdb") is not None


class TestValidation:
    def test_invalid_measure_flagged(self):
        p = Probe(measures=["line_total"], dimensions=["category"])
        bad = validate_probe(p, ["unit_price", "unit_cost"], ["category"], [])
        assert "line_total" in bad

    def test_valid_probe_passes(self):
        p = Probe(measures=["unit_price"], dimensions=["category"])
        assert validate_probe(p, ["unit_price"], ["category"], []) == []

    def test_normalisation_insensitive(self):
        p = Probe(measures=["UnitPrice"], dimensions=["Category"])
        assert validate_probe(p, ["unit_price"], ["category"], []) == []


class TestSingleTable:
    def test_headline_measure(self):
        sql = _compile(Probe(measures=["unit_price"]))
        assert sql and _parses(sql)
        assert "SUM(unit_price)" in sql.replace(" ", "").replace("SUM(unit_price)", "SUM(unit_price)") or "SUM(unit_price)" in sql

    def test_measure_by_dimension(self):
        sql = _compile(Probe(measures=["unit_price"], dimensions=["category"]))
        assert sql and _parses(sql)
        assert "GROUP BY" in sql and "category" in sql and "LIMIT" in sql

    def test_rate_column_uses_avg_not_sum(self):
        sql = _compile(Probe(measures=["gross_margin_rate"], dimensions=["category"]))
        assert sql and "AVG(gross_margin_rate)" in sql
        assert "SUM(gross_margin_rate)" not in sql

    def test_composite_having_threshold(self):
        # "categories whose avg gross margin > 0.6" — the composite class
        p = Probe(measures=["gross_margin_rate"], dimensions=["category"],
                  having=ProbeHaving(measure="gross_margin_rate", op=">", value=0.6))
        sql = _compile(p)
        assert sql and _parses(sql)
        assert "HAVING" in sql and "0.6" in sql

    def test_filter_emitted_and_quoted(self):
        p = Probe(measures=["unit_price"], dimensions=["category"],
                  filters=[ProbeFilter(column="category", op="=", value="fragrance")])
        sql = _compile(p)
        assert sql and _parses(sql)
        assert "WHERE" in sql and "'fragrance'" in sql

    def test_no_invented_column_can_appear(self):
        # even if a bad column sneaks to the compiler, it can't resolve a table → None
        assert _compile(Probe(measures=["line_total"], dimensions=["category"])) is None


class TestStarJoin:
    def test_fact_measure_by_joined_dimension(self):
        # measure on order_items, dimension on orders → grain-safe star join
        sql = _compile(Probe(measures=["unit_price"], dimensions=["marketing_channel"]))
        assert sql and _parses(sql)
        assert "JOIN" in sql and "marketing_channel" in sql
        assert "order_id" in sql  # the verified join key

    def test_measures_spanning_two_tables_falls_back(self):
        # unit_price (order_items) + order_value (orders) as measures → fan-out risk → None
        assert _compile(Probe(measures=["unit_price", "order_value"], dimensions=["category"])) is None

    def test_unjoined_tables_fall_back(self):
        sql = probe_to_sql(Probe(measures=["unit_price"], dimensions=["marketing_channel"]),
                           tables_cols=TABLES_COLS, col_profiles=COL_PROFILES, joins=[], dialect="duckdb")
        assert sql is None  # no verified join available → fall back to free-form
