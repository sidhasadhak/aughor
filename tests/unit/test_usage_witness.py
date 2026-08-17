"""AT-8 — roles mined from real SQL, and the witnesses they justify.

The miner already counted how OFTEN a column appears. A count says a column matters; it
cannot tell a dimension from a measure. These tests are about the distinction: `GROUP BY
state` and `SUM(total)` are different facts about different kinds of column, and both are
recoverable from history nobody had to annotate.
"""
from __future__ import annotations

from aughor.sql.query_log_miner import (
    ROLE_AVG,
    ROLE_FILTER_BINARY,
    ROLE_GROUP_BY,
    ROLE_JOIN,
    ROLE_SUM,
    mine_query_log,
)
from aughor.tools.concept import CONFIDENT, LAYER_USAGE, resolve_concept
from aughor.tools.usage import MIN_SUPPORT, roles_by_column, usage_witnesses, witnesses_for_table

SQL_GROUPED = "SELECT state, SUM(total) FROM orders GROUP BY state"
SQL_JOINED = "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
SQL_FLAG = "SELECT COUNT(*) FROM orders WHERE is_late = 1"


# ── the mining ────────────────────────────────────────────────────────────────

def test_group_by_and_sum_are_recorded_as_different_roles():
    facts = mine_query_log([SQL_GROUPED])
    assert facts.column_roles[("orders.state", ROLE_GROUP_BY)] == 1
    assert facts.column_roles[("orders.total", ROLE_SUM)] == 1
    # …and neither column picked up the other's role.
    assert facts.column_roles[("orders.state", ROLE_SUM)] == 0
    assert facts.column_roles[("orders.total", ROLE_GROUP_BY)] == 0


def test_both_sides_of_a_join_are_recorded():
    facts = mine_query_log([SQL_JOINED])
    assert facts.column_roles[("orders.customer_id", ROLE_JOIN)] == 1
    assert facts.column_roles[("customers.id", ROLE_JOIN)] == 1


def test_a_zero_one_equality_is_a_flag_role_and_a_price_is_not():
    facts = mine_query_log([SQL_FLAG, "SELECT * FROM orders WHERE price = 42"])
    assert facts.column_roles[("orders.is_late", ROLE_FILTER_BINARY)] == 1
    assert facts.column_roles[("orders.price", ROLE_FILTER_BINARY)] == 0


def test_avg_is_its_own_role():
    facts = mine_query_log(["SELECT AVG(discount_rate) FROM orders"])
    assert facts.column_roles[("orders.discount_rate", ROLE_AVG)] == 1


def test_unparseable_sql_costs_nothing():
    facts = mine_query_log(["this is not sql at all ((("])
    assert facts.column_roles == {} or sum(facts.column_roles.values()) == 0


def test_roles_do_not_disturb_what_the_miner_already_reported():
    """`column_roles` is additive. The counters four consumers already read must not move."""
    facts = mine_query_log([SQL_GROUPED, SQL_JOINED])
    assert facts.n_parsed == 2
    assert facts.column_usage[("orders.state")] >= 1
    assert any("orders.customer_id" in edge for edge in facts.join_edges)


# ── the projection ────────────────────────────────────────────────────────────

def test_a_habit_becomes_a_witness_and_one_query_does_not():
    once = usage_witnesses({ROLE_GROUP_BY: 1})
    assert once == [], "one exploratory query is not evidence of what a column is"
    habit = usage_witnesses({ROLE_GROUP_BY: MIN_SUPPORT})
    assert habit and habit[0].concept == "dimension.categorical"
    assert habit[0].layer == LAYER_USAGE


def test_usage_alone_can_never_type_a_column():
    """Even a column grouped ten thousand times: usage records the questions asked, not
    what the column is. The AT-4 cap does the enforcing; this asserts the intent."""
    w = usage_witnesses({ROLE_GROUP_BY: 10_000})
    assert w[0].confidence < CONFIDENT
    assert not resolve_concept(w).is_confident


def test_usage_supplies_the_SECOND_witness_a_name_pattern_cannot():
    """The point of the layer: a name says `state` is a dimension, and being grouped by
    500 times agrees from a different kind of evidence. Two layers → a concept."""
    from aughor.tools.concept import LAYER_NAME, Witness

    name = Witness(layer=LAYER_NAME, concept="dimension.categorical",
                   confidence=0.5, evidence="named like a place")
    verdict = resolve_concept([name] + usage_witnesses({ROLE_GROUP_BY: 500}))
    assert verdict.concept == "dimension.categorical"
    assert verdict.is_confident


def test_a_column_with_two_honest_roles_keeps_both():
    w = usage_witnesses({ROLE_JOIN: 40, ROLE_GROUP_BY: 12})
    assert {x.concept for x in w} == {"key.identifier", "dimension.categorical"}
    # the dominant habit is worth more than the occasional one
    assert w[0].concept == "key.identifier"


def test_evidence_names_the_role_and_the_count():
    w = usage_witnesses({ROLE_SUM: 7})
    assert "sum" in w[0].evidence and "7" in w[0].evidence


def test_roles_by_column_inverts_the_counter_and_survives_junk():
    got = roles_by_column({("orders.state", ROLE_GROUP_BY): 4, "not-a-pair": 9, ("", ""): 3})
    assert got == {"orders.state": {ROLE_GROUP_BY: 4}}
    assert roles_by_column({}) == {}
    assert roles_by_column(None) == {}


def test_lookup_is_case_insensitive_on_both_halves():
    """The log holds what the analyst typed; the profiler holds what the catalog says. A
    guard whose key stops matching goes blind rather than wrong."""
    facts = mine_query_log(["SELECT State, SUM(Total) FROM Orders GROUP BY State"])
    got = witnesses_for_table("orders", ["state", "total"], facts.column_roles)
    # one query is below MIN_SUPPORT, so the point here is that the KEY matched at all
    assert roles_by_column(facts.column_roles)
    got = witnesses_for_table(
        "orders", ["state"], {("Orders.State", ROLE_GROUP_BY): 9})
    assert "state" in got and got["state"][0].concept == "dimension.categorical"


def test_a_table_nobody_queried_witnesses_nothing():
    assert witnesses_for_table("orders", ["state"], {}) == {}
    assert witnesses_for_table("orders", [], {("orders.state", ROLE_GROUP_BY): 9}) == {}
