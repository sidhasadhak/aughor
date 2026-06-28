"""Tests for query-log mining (aughor/sql/query_log_miner.py).

Contract: mine a list of historical SQL strings into DETERMINISTIC facts — observed join paths,
filter value domains, named business formulas, column usage — ranked by frequency, with one-off
noise filterable via min_support. Unparseable queries are skipped, never raised on. The rendered
block is a schema-context comment the LLM can use the way value-verified join hints already are.
"""
from __future__ import annotations

from aughor.sql.query_log_miner import mine_query_log, QueryLogFacts


def test_mines_join_edges_with_alias_resolution_and_direction_normalized():
    sqls = [
        "SELECT o.id FROM orders o JOIN customers c ON o.customer_id = c.id",
        # same edge, reversed operand order + different aliases → must merge to one key
        "SELECT * FROM customers cu JOIN orders ord ON cu.id = ord.customer_id",
    ]
    facts = mine_query_log(sqls, dialect="duckdb")
    assert facts.join_edges["customers.id = orders.customer_id"] == 2
    assert len(facts.join_edges) == 1  # direction/alias normalized to a single edge


def test_self_column_equality_is_not_a_join_edge():
    facts = mine_query_log(["SELECT * FROM t WHERE t.a = t.b"], dialect="duckdb")
    assert facts.join_edges == {}  # same-table col=col is a filter, not a join path


def test_mines_filter_value_domains_eq_and_in():
    sqls = [
        "SELECT * FROM orders WHERE status = 'shipped'",
        "SELECT * FROM orders WHERE status = 'shipped'",
        "SELECT * FROM orders WHERE status IN ('cancelled', 'delivered')",
    ]
    facts = mine_query_log(sqls, dialect="duckdb")
    dom = facts.filter_values["orders.status"]
    assert dom["shipped"] == 2 and dom["cancelled"] == 1 and dom["delivered"] == 1


def test_mines_named_formulas_but_not_bare_columns():
    sqls = [
        "SELECT SUM(amount * qty) AS revenue FROM sales",
        "SELECT SUM(amount * qty) AS revenue FROM sales",
        "SELECT name AS who FROM sales",      # bare column alias → NOT a formula
    ]
    facts = mine_query_log(sqls, dialect="duckdb")
    assert facts.named_formulas[("revenue", "SUM(amount * qty)")] == 2
    assert all(name != "who" for (name, _expr) in facts.named_formulas)


def test_unparseable_and_empty_are_skipped_not_raised():
    # sqlglot is lenient, so "garbage" may parse to a trivial tree — the contract is no crash and
    # no spurious facts, and blank inputs contribute nothing.
    facts = mine_query_log(["", "   ", "@@@ not real sql @@@"], dialect="duckdb")
    assert facts.n_queries == 3
    assert facts.join_edges == {} and facts.filter_values == {} and facts.named_formulas == {}
    assert facts.render_for_schema_context() == ""


def test_render_includes_all_sections_and_query_count():
    sqls = [
        "SELECT SUM(o.amt) AS revenue FROM orders o JOIN customers c ON o.customer_id = c.id "
        "WHERE o.status = 'paid'",
    ]
    block = mine_query_log(sqls).render_for_schema_context()
    assert "LEARNED FROM QUERY HISTORY (1 queries analyzed)" in block
    assert "customers.id = orders.customer_id" in block   # edge operands rendered sorted
    assert "orders.status IN ('paid')" in block
    assert "revenue := SUM(o.amt)" in block


def test_min_support_filters_one_off_noise():
    sqls = [
        "SELECT * FROM a JOIN b ON a.k = b.k",            # seen 1×
        "SELECT * FROM a JOIN b ON a.k = b.k",            # seen 2×
        "SELECT * FROM a JOIN d ON a.q = d.q",            # seen 1× (noise)
    ]
    facts = mine_query_log(sqls)
    block = facts.render_for_schema_context(min_support=2)
    assert "a.k = b.k" in block
    assert "a.q = d.q" not in block  # below support threshold → dropped


def test_empty_facts_render_empty():
    assert QueryLogFacts().render_for_schema_context() == ""
