"""A card's definition is read off its SQL, so a label a model chose cannot say one thing while its query does another."""
from __future__ import annotations

import pytest

from aughor.dashboards.definitions import definition_of


@pytest.mark.parametrize("sql,said", [
    ("SELECT SUM(sale_price) AS kept FROM t WHERE status = 'Complete'", "Sum of Sale price where Status is Complete"),
    ("SELECT SUM(sale_price) FROM t WHERE status <> 'Cancelled'", "Sum of Sale price where Status is not Cancelled"),
    ("SELECT SUM(sale_price) FROM t WHERE status IN ('Processing', 'Shipped')", "Sum of Sale price where Status is Processing or Shipped"),
    ("SELECT COUNT(*) FROM t WHERE amount > 10", "Count of rows where Amount is above 10"),
    ("SELECT COUNT(DISTINCT order_id) FROM t", "Count of different Order id"),
    ("SELECT AVG(price) FROM t WHERE region = 'north' AND price >= 5", "Average of Price where Region is north and Price is at least 5"),
    ("SELECT SUM(CASE WHEN status = 'Returned' THEN sale_price END) / SUM(CASE WHEN status IN ('Complete', 'Returned') THEN sale_price END) FROM t",
     "Sum of Sale price where Status is Returned ÷ Sum of Sale price where Status is Complete or Returned"),
    ("SELECT SUM(CASE WHEN status = 'Returned' THEN sale_price END) / NULLIF(SUM(sale_price), 0) FROM t",
     "Sum of Sale price where Status is Returned ÷ Sum of Sale price"),
    ("SELECT COALESCE(SUM(amount), 0) FROM t", "Sum of Amount"),
])
def test_a_figure_says_what_its_statement_says(sql, said):
    assert definition_of(sql) == said


def test_a_chart_names_each_series_and_what_it_is_by():
    assert definition_of(
        "SELECT DATE_TRUNC('week', ordered_on) AS week, SUM(CASE WHEN status = 'Complete' THEN sale_price END) AS kept, "
        "SUM(CASE WHEN status = 'Returned' THEN sale_price END) AS came_back FROM t GROUP BY 1 ORDER BY 1"
    ) == ("Kept: Sum of Sale price where Status is Complete. Came back: Sum of Sale price where Status is Returned. "
          "By Week of Ordered on.")


def test_the_shapes_a_real_model_wrote():
    """Each read off a real draft, 2026-11-03: an ELSE 0, a date cast, a share of a count, a floor on a group."""
    assert definition_of(
        "SELECT CAST(date_trunc('week', ordered_on) AS DATE) AS week, SUM(CASE WHEN status = 'Complete' THEN sale_price ELSE 0 END) AS kept "
        "FROM t GROUP BY 1 ORDER BY 1") == "Kept: Sum of Sale price where Status is Complete. By Week of Ordered on."
    assert definition_of(
        "SELECT category, SUM(CASE WHEN status = 'Returned' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS return_rate FROM t "
        "WHERE status <> 'Cancelled' GROUP BY category HAVING COUNT(*) >= 30 ORDER BY return_rate DESC LIMIT 10"
    ) == ("Return rate: Count of rows where Status is Returned ÷ Count of rows where Status is not Cancelled. By Category. "
          "Only where Count of rows is at least 30. The top 10.")


def test_a_where_the_case_already_implies_is_not_said_twice():
    sql = "SELECT SUM(CASE WHEN status = 'Complete' THEN x END) AS kept FROM t WHERE status <> 'Cancelled'"
    assert definition_of(sql) == "Sum of X where Status is Complete"
    sql = "SELECT SUM(CASE WHEN status NOT IN ('Complete', 'Cancelled') THEN x END) AS o FROM t WHERE status <> 'Cancelled'"
    assert definition_of(sql) == "Sum of X where Status is none of Complete, Cancelled"
    sql = "SELECT SUM(CASE WHEN region = 'north' THEN x END) AS n FROM t WHERE status <> 'Cancelled'"
    assert definition_of(sql) == "Sum of X where Region is north and Status is not Cancelled"
    # a CASE that does not rule the WHERE out keeps it: the words must stay true
    sql = "SELECT SUM(CASE WHEN status IN ('Complete', 'Cancelled') THEN x END) AS n FROM t WHERE status <> 'Cancelled'"
    assert definition_of(sql) == "Sum of X where Status is Complete or Cancelled and Status is not Cancelled"


def test_a_figure_is_defined_by_the_value_it_shows_not_the_one_beside_it():
    sql = "SELECT SUM(x) AS kept, SUM(x) / SUM(y) AS share FROM t"
    assert definition_of(sql, only="kept") == "Sum of X"
    assert definition_of(sql) == "Kept: Sum of X. Share: Sum of X ÷ Sum of Y."


def test_a_cap_is_said():
    assert definition_of("SELECT category, SUM(x) AS total FROM t GROUP BY category ORDER BY total DESC LIMIT 8").endswith("By Category. The top 8.")


def test_a_reader_value_is_said_as_theirs():
    words = definition_of("SELECT SUM(amount) * (1 - {{return_rate}}) AS kept FROM t", values={"return_rate": "your return rate"})
    assert words == "Sum of Amount × (1 − your return rate)"


def test_the_rows_are_said_as_rows():
    assert definition_of("SELECT * FROM t") == "The rows, as they stand."
    assert definition_of("SELECT * FROM t WHERE region = 'north'") == "The rows where Region is north."


@pytest.mark.parametrize("sql", [
    "SELECT a.x FROM t a JOIN u ON a.id = u.id",
    "WITH c AS (SELECT 1 AS x) SELECT x FROM c",
    "SELECT id, ROW_NUMBER() OVER (ORDER BY id) FROM t",
    "SELECT SUM(x) FROM t WHERE y IN (SELECT y FROM u)",
    "SELECT SUM(CASE WHEN a = 1 THEN x WHEN a = 2 THEN y END) FROM t",
    "SELECT SUM(CASE WHEN a = 1 THEN x ELSE y END) FROM t",
    "SELECT SUM(CASE WHEN a = 1 THEN x ELSE 5 END) FROM t",
    "SELECT y, SUM(x) AS s FROM t GROUP BY y HAVING SUM(x) > 3 AND COUNT(*) > 2",
    "not sql at all (",
])
def test_what_words_cannot_hold_is_not_guessed(sql):
    """A guess in plain words is worse than none: the card then says to read its query."""
    assert definition_of(sql) is None
