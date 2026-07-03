"""The shared SQL-analysis facade (aughor/sql/analyze.py) and its first retargets.

`analyze(sql)` is the single AST-based semantic-fact extractor that string-munging
consumers (ontology validator, investigations._extract_tables, …) now share. The
product-of-aggregates detector is the headline: it replaces a regex that silently
missed any nested-paren argument.
"""
import re

from aughor.sql.analyze import analyze


# ── product_of_aggregates — the $3T anti-pattern, on the AST ───────────────────

class TestProductOfAggregates:
    def test_classic_bug_flagged(self):
        assert analyze("SUM(final_price) * SUM(quantity)").product_of_aggregates

    def test_nested_paren_arg_flagged(self):
        # the case the old `AGG(...)\s*\*\s*AGG(` regex silently MISSED
        assert analyze("SUM(COALESCE(price, 0)) * SUM(quantity)").product_of_aggregates

    def test_mixed_aggregates_flagged(self):
        assert analyze("AVG(x) * SUM(y)").product_of_aggregates

    def test_per_row_product_is_safe(self):
        # SUM(a * b) — the CORRECT form, multiply inside the aggregate
        assert not analyze("SUM(final_price * quantity)").product_of_aggregates

    def test_scaling_by_constant_is_safe(self):
        assert not analyze("2 * SUM(x)").product_of_aggregates

    def test_aggregate_times_column_is_safe(self):
        # only ONE operand is an aggregate — not a product of two aggregates
        assert not analyze("SUM(x) * qty").product_of_aggregates

    def test_single_aggregate_is_safe(self):
        assert not analyze("SUM(revenue)").product_of_aggregates

    def test_beats_the_regex_on_the_nested_case(self):
        # lock the improvement: the facade catches what the legacy regex could not
        legacy = re.compile(r"\b(?:SUM|COUNT|AVG|MIN|MAX)\s*\([^)]*\)\s*\*\s*(?:SUM|COUNT|AVG|MIN|MAX)\s*\(",
                            re.IGNORECASE)
        sql = "SUM(COALESCE(price, 0)) * SUM(quantity)"
        assert analyze(sql).product_of_aggregates is True
        assert legacy.search(sql) is None      # the bug the AST version fixes


# ── facts extraction ──────────────────────────────────────────────────────────

class TestFacts:
    def test_tables_columns_aggregates_groupby(self):
        f = analyze("SELECT c.region, SUM(o.amount) AS rev FROM orders o "
                    "JOIN customers c ON o.cid = c.id GROUP BY c.region")
        assert f.ok
        assert f.tables == {"orders", "customers"}
        assert "region" in f.columns and "amount" in f.columns
        assert f.group_by == {"c.region"}
        assert f.has_aggregate
        assert ("sum", "o.amount") in [(a.func, a.arg_sql) for a in f.aggregates]

    def test_ctes_excluded_from_tables(self):
        f = analyze("WITH t AS (SELECT * FROM orders) SELECT * FROM t "
                    "JOIN customers c ON 1=1")
        assert "t" in f.ctes
        assert f.tables == {"orders", "customers"}   # the CTE 't' is NOT a base table

    def test_distinct_and_windowed_aggregates(self):
        f = analyze("SELECT COUNT(DISTINCT id), AVG(x) OVER (PARTITION BY g) FROM t")
        by_func = {a.func: a for a in f.aggregates}
        assert by_func["count"].is_distinct is True
        assert by_func["avg"].is_windowed is True

    def test_count_star(self):
        f = analyze("SELECT COUNT(*) FROM t")
        assert f.aggregates[0].func == "count"
        assert f.aggregates[0].arg_sql == "*"


# ── never raises ──────────────────────────────────────────────────────────────

class TestGraceful:
    def test_malformed_returns_not_ok(self):
        f = analyze("this is not sql at all )(")
        assert f.ok is False
        assert f.tables == set() and f.aggregates == []
        assert f.product_of_aggregates is False

    def test_empty_and_none(self):
        assert analyze("").ok is False
        assert analyze(None).ok is False
