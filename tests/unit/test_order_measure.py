"""A ranked finding's evidence must return what it is ranked by (aughor.sql.order_measure).

The first case is the stored theLook finding verbatim: it ranked categories by profit and
returned only the names, so its Briefing chart had no measure and Table was the only
visualization on offer.
"""
import sqlglot

from aughor.sql.order_measure import project_order_keys

THELOOK_PINNED = """WITH category_profit AS (
    SELECT
        p.category,
        SUM(oi.sale_price - i.cost) AS total_profit
    FROM order_items oi
    JOIN products p ON oi.product_id = p.id
    JOIN inventory_items i ON oi.inventory_item_id = i.id
    GROUP BY 1
)
SELECT category
FROM category_profit
ORDER BY total_profit DESC"""


def _returned(sql: str, dialect: str = "duckdb") -> list[str]:
    return [p.alias_or_name for p in sqlglot.parse_one(sql, read=dialect).expressions]


def test_the_measure_a_ranking_is_ordered_by_is_returned():
    out = project_order_keys(THELOOK_PINNED, "bigquery")
    assert out is not None
    assert _returned(out, "bigquery") == ["category", "total_profit"]
    # Same rows in the same order: the ORDER BY is untouched.
    assert sqlglot.parse_one(out, read="bigquery").args["order"].sql("bigquery") == "ORDER BY total_profit DESC"


def test_an_ordering_expression_is_returned_under_a_name():
    out = project_order_keys("SELECT region FROM sales GROUP BY region ORDER BY SUM(amount) DESC")
    assert _returned(out) == ["region", "sort_value"]


def test_a_key_already_returned_is_left_alone():
    assert project_order_keys("SELECT region, SUM(amount) AS total FROM s GROUP BY 1 ORDER BY total DESC") is None
    assert project_order_keys("SELECT region, SUM(amount) FROM s GROUP BY 1 ORDER BY 2 DESC") is None
    assert project_order_keys("SELECT region, SUM(amount) FROM s GROUP BY 1 ORDER BY SUM(amount) DESC") is None


def test_shapes_where_adding_a_column_is_not_provably_safe_are_refused():
    # DISTINCT: the added column would change which rows are distinct.
    assert project_order_keys("SELECT DISTINCT region FROM s ORDER BY amount") is None
    # A star hides the output names.
    assert project_order_keys("SELECT * FROM s ORDER BY amount") is None
    # A set operation has no single SELECT list to extend.
    assert project_order_keys("SELECT a FROM s UNION ALL SELECT a FROM t ORDER BY a") is None
    assert project_order_keys("not sql at all") is None
