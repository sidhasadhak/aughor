"""Recipe-binding gate — stop injecting profile recipes whose columns don't exist in
the connection's schema (the dominant Phase-8 token sink: the generator follows a
generic recipe like SUM(revenue - cogs) and invents line_total / customer_id / the
ecommerce.* schema, all of which the feasibility gate then drops)."""
from aughor.explorer.agent import _recipe_binds, _norm_ident

# The REAL missimi schema (a subset, normalised as the gate sees it).
REAL_COLS = {_norm_ident(c) for c in [
    "unit_price", "unit_cost", "order_value", "customer_unique_id", "marketing_channel",
    "review_score", "category", "attributed_revenue", "spend",
]}
REAL_TBLS = {_norm_ident(t) for t in ["orders", "order_items", "order_payments", "marketing"]}


def binds(formula):
    return _recipe_binds(formula, REAL_COLS, REAL_TBLS)


class TestRecipeBinds:
    def test_generic_revenue_cogs_recipe_does_not_bind(self):
        # the missimi "Gross Margin %" recipe — revenue/cogs are not real columns here
        assert binds("SUM(revenue - cogs) / NULLIF(SUM(revenue), 0)") is False

    def test_generic_customer_id_recipe_does_not_bind(self):
        # real column is customer_unique_id, not customer_id
        assert binds("COUNT(DISTINCT customer_id WITH order_count > 1) / COUNT(DISTINCT customer_id)") is False

    def test_explicit_wrong_schema_table_does_not_bind(self):
        assert binds("SELECT SUM(line_total) FROM ecommerce.orders") is False

    def test_units_sold_recipe_does_not_bind(self):
        assert binds("SUM(units_sold) / NULLIF(AVG(units_on_hand), 0)") is False

    def test_bound_recipe_with_real_columns_survives(self):
        # uses real columns → must be kept
        assert binds("SUM(unit_price - unit_cost) / NULLIF(SUM(unit_price), 0)") is True

    def test_roas_recipe_with_real_columns_survives(self):
        assert binds("SUM(attributed_revenue) / NULLIF(SUM(spend), 0)") is True

    def test_pure_function_formula_is_kept(self):
        # no judgeable column identifiers → fail-open (keep)
        assert binds("COUNT(*) / 100.0") is True

    def test_sql_keywords_not_counted_as_columns(self):
        # only real-column 'order_value' present amongst keywords → binds
        assert binds("SUM(order_value) FILTER (WHERE order_value > 0)") is True
