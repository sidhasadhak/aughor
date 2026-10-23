"""Arc AP-8b — a set read whole by a condition: its linked objects, and sets combined (ROADMAP §3.57; the study's §9.2,
screen 12 of `design-mockups/cockpit-builder.html`).

A dashboard's set could narrow its own objects, and nothing more: a condition through a to-many link held ONE condition,
so "the customers of the waiting orders" — orders overdue AND in the window AND in the country, all on the SAME order —
could not be said, nor "either", "both" or "but not" of two sets. Now a condition names whole sets (`in_set`,
`not_in_set`): each set is one EXISTS over its entity holding its segment and every one of its conditions, tied to the
condition's object by its key or, for a set of another entity, by that set's `via` link. Every answer here is checked
against SQL written by hand over the seeded samples warehouse; a reader's row policies hold inside a set as outside.
"""
from __future__ import annotations

import pytest

from aughor.semantic.object_query import (ObjectListing, ObjectQueryRefused, compile_object_listing, object_links)
from tests.unit.test_object_actions import db  # noqa: F401 — fixtures by name
from tests.unit.test_object_query import _compile, _graph, _rows, warehouse  # noqa: F401 — the fixture, by name
from tests.unit.test_ontology_security import graph, secured  # noqa: F401 — fixtures by name

ACTIVE = "o.status NOT IN ('delivered', 'cancelled')"


def _count(con, compiled) -> int:
    return int(_rows(con, compiled.sql)[0][0])


def _ref(con, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def _link(source: str, target: str) -> str:
    """The name of the link from `source` that reaches `target` in the samples ontology."""
    g = _graph()
    return next(h.name for h in object_links(g, g.entities[source]) if h.target.id == target)


ACTIVE_BIG = {"entity": "order", "segment": "active_orders", "filters": [{"path": "total_amount", "op": ">=", "value": 150}]}


# ── a set's linked objects ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_customers_of_a_set_of_orders_are_those_with_one_order_meeting_every_condition_of_the_set(warehouse):  # noqa: F811
    via = _link("Order", "Customer")
    theirs = _compile({"object_type": "customer", "measures": [{"agg": "count"}],
                       "filters": [{"path": "", "op": "in_set", "sets": [{**ACTIVE_BIG, "via": via}]}]})
    one_order = _ref(warehouse, "SELECT COUNT(*) FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE "
                                f"o.customer_id = c.customer_id AND {ACTIVE} AND o.total_amount >= 150)")
    assert _count(warehouse, theirs) == one_order > 0
    # two conditions written apart are two orders — the very thing a set's single EXISTS is for: an order between 300
    # and 310 is one order, never "an order over 300 and another under 310"
    band = {"entity": "order", "via": via, "filters": [{"path": "total_amount", "op": ">=", "value": 300},
                                                       {"path": "total_amount", "op": "<", "value": 310}]}
    one = _count(warehouse, _compile({"object_type": "customer", "measures": [{"agg": "count"}],
                                      "filters": [{"path": "", "op": "in_set", "sets": [band]}]}))
    assert one == _ref(warehouse, "SELECT COUNT(*) FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE "
                                  "o.customer_id = c.customer_id AND o.total_amount >= 300 AND o.total_amount < 310)")
    apart = _ref(warehouse, "SELECT COUNT(*) FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = "
                            "c.customer_id AND o.total_amount >= 300) AND EXISTS (SELECT 1 FROM orders o WHERE "
                            "o.customer_id = c.customer_id AND o.total_amount < 310)")
    assert apart > one > 0
    assert any(link["treatment"] == "semi-join over a set" for link in theirs.links)
    assert any(line.startswith("set of Order (active_orders), 1 condition, reached through") for line in theirs.plan)


def test_the_lines_of_a_set_of_orders_are_reached_the_other_way_down_the_link(warehouse):  # noqa: F811
    via = _link("Order", "OrderItem")
    lines = _compile({"object_type": "OrderItem", "measures": [{"agg": "count"}],
                      "filters": [{"path": "", "op": "in_set", "sets": [{**ACTIVE_BIG, "via": via}]}]})
    assert _count(warehouse, lines) == _ref(warehouse, "SELECT COUNT(*) FROM order_items i WHERE EXISTS (SELECT 1 FROM "
                                                       f"orders o WHERE o.order_id = i.order_id AND {ACTIVE} AND "
                                                       "o.total_amount >= 150)")


# ── sets combined ──────────────────────────────────────────────────────────────────────────────────────────────────

BIG = {"entity": "order", "filters": [{"path": "total_amount", "op": ">=", "value": 200}]}
ACTIVE_SET = {"entity": "order", "segment": "active_orders"}


@pytest.mark.parametrize("filters,where", [
    ([{"path": "", "op": "in_set", "sets": [ACTIVE_SET, BIG]}], f"{ACTIVE} OR o.total_amount >= 200"),           # either
    ([{"path": "", "op": "in_set", "sets": [ACTIVE_SET]}, {"path": "", "op": "in_set", "sets": [BIG]}],
     f"{ACTIVE} AND o.total_amount >= 200"),                                                                       # both
    ([{"path": "", "op": "in_set", "sets": [ACTIVE_SET]}, {"path": "", "op": "not_in_set", "sets": [BIG]}],
     f"{ACTIVE} AND NOT o.total_amount >= 200"),                                                                   # but not
    ([{"path": "", "op": "not_in_set", "sets": [ACTIVE_SET, BIG]}], f"NOT ({ACTIVE} OR o.total_amount >= 200)"),   # neither
])
def test_either_both_and_but_not_hold_exactly_the_objects_the_two_sets_say(warehouse, filters, where):  # noqa: F811
    compiled = _compile({"object_type": "order", "measures": [{"agg": "count"}], "filters": filters})
    assert _count(warehouse, compiled) == _ref(warehouse, f"SELECT COUNT(*) FROM orders o WHERE {where}")


def test_a_set_read_inside_a_set_is_read_whole_too(warehouse):  # noqa: F811
    """The customers with an order active but not big: a set that combines two sets, reached through a link."""
    via = _link("Order", "Customer")
    nested = {"entity": "order", "segment": "active_orders", "via": via,
              "filters": [{"path": "", "op": "not_in_set", "sets": [BIG]}]}
    compiled = _compile({"object_type": "customer", "measures": [{"agg": "count"}],
                         "filters": [{"path": "", "op": "in_set", "sets": [nested]}]})
    assert _count(warehouse, compiled) == _ref(warehouse, "SELECT COUNT(*) FROM customers c WHERE EXISTS (SELECT 1 FROM "
                                                          f"orders o WHERE o.customer_id = c.customer_id AND {ACTIVE} AND "
                                                          "NOT o.total_amount >= 200)")


def test_a_listing_of_a_set_counts_what_it_lists_and_says_its_own_segment_never_a_set_s(warehouse):  # noqa: F811
    compiled = compile_object_listing(ObjectListing(entity="order", segment="delivered_orders", limit=200, filters=[
        {"path": "", "op": "not_in_set", "sets": [ACTIVE_SET, BIG]}]), _graph(), dialect="duckdb")
    total = int(warehouse.execute(compiled.count_sql).fetchone()[0])
    assert total == _ref(warehouse, "SELECT COUNT(*) FROM orders o WHERE o.status = 'delivered' AND NOT "
                                    f"({ACTIVE} OR o.total_amount >= 200)")
    assert len(warehouse.execute(compiled.sql).fetchall()) == min(total, 200) > 0
    own = compile_object_listing(ObjectListing(entity="order", segment="delivered_orders", limit=200), _graph(), dialect="duckdb")
    assert compiled.segment_said == own.segment_said != ""


def test_a_set_reached_through_a_link_is_tied_by_the_link_s_own_two_columns_each_on_its_own_side():
    """The samples' links join columns of the same name, so their counts cannot tell the tie's two ends apart; theLook's
    order → user link is `user_id` to `id`. A link whose ends differ: the set's own column on the set's side."""
    g = _graph()
    rel = next(r for r in g.relationships.values() if {r.from_entity, r.to_entity} == {"Customer", "Order"})
    if rel.from_entity == "Order":
        rel.from_col = "buyer_id"
    else:
        rel.to_col = "buyer_id"
    via = next(h.name for h in object_links(g, g.entities["Order"]) if h.target.id == "Customer")
    sql = _compile({"object_type": "customer", "measures": [{"agg": "count"}],
                    "filters": [{"path": "", "op": "in_set", "sets": [{"entity": "order", "via": via}]}]}, g).sql
    assert '.buyer_id = t0.customer_id' in sql.replace('"', ""), sql


# ── what is refused, in words ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filters,says", [
    ([{"path": "status", "op": "in_set", "sets": [BIG]}], "a set is read of the object itself"),
    ([{"path": "", "op": "in_set"}], "names no set"),
    ([{"path": "", "op": "in_set", "sets": [BIG] * 5}], "at most 4"),
    ([{"path": "", "op": "in_set", "sets": [{"entity": "customer"}]}], "a set of Customer is read by a Order only through a link"),
    ([{"path": "", "op": "in_set", "sets": [{"entity": "product", "via": "nowhere"}]}], "no link 'nowhere' from Product"),
    ([{"path": "status", "op": "=", "value": "x", "sets": [BIG]}], "sets are read by in_set and not_in_set"),
])
def test_a_set_the_door_cannot_read_as_written_is_refused_in_words(filters, says):
    with pytest.raises(ObjectQueryRefused) as e:
        _compile({"object_type": "order", "measures": [{"agg": "count"}], "filters": filters})
    assert says in str(e.value), str(e.value)


def test_a_link_that_reaches_another_entity_is_refused_and_so_is_reading_sets_without_end():
    to_lines = _link("Order", "OrderItem")
    with pytest.raises(ObjectQueryRefused) as e:
        _compile({"object_type": "customer", "measures": [{"agg": "count"}],
                  "filters": [{"path": "", "op": "in_set", "sets": [{"entity": "order", "via": to_lines}]}]})
    assert "reaches OrderItem" in str(e.value) and "not Customer" in str(e.value)
    deep: dict = {"entity": "order"}
    for _ in range(5):
        deep = {"entity": "order", "filters": [{"path": "", "op": "in_set", "sets": [deep]}]}
    with pytest.raises(ObjectQueryRefused) as e:
        _compile({"object_type": "order", "measures": [{"agg": "count"}], "filters": deep["filters"]})
    assert "more than 4 levels down" in str(e.value)


# ── a reader's row policies hold inside a set ─────────────────────────────────────────────────────────────────────

def test_a_set_never_tells_a_reader_of_objects_a_row_policy_keeps_from_them(secured, db, monkeypatch):  # noqa: F811
    """Ana sees shipped and delivered orders only: the customers who placed a cancelled order are none, for her — a set
    is no window onto the orders she may not see — and she is told why. Ben, in support, sees them, as many as there are."""
    from aughor.semantic.object_query import compile_object_query
    from tests.unit.test_ontology_security import _as
    via = _link("Order", "Customer")
    query = {"object_type": "customer", "measures": [{"agg": "count"}],
             "filters": [{"path": "", "op": "in_set", "sets": [{"entity": "order", "via": via,
                                                                "filters": [{"path": "status", "value": "cancelled"}]}]}]}

    def count() -> tuple[int, list[str]]:
        compiled = compile_object_query(query, secured, dialect="duckdb")
        return int(float(db.execute("t", compiled.sql).rows[0][0])), compiled.caveats
    _as(monkeypatch, "ana")
    n, caveats = count()
    assert n == 0 and any("Order" in c or "order" in c for c in caveats), caveats
    _as(monkeypatch, "ben")
    n, _ = count()
    every = int(db.execute("t", "SELECT COUNT(DISTINCT customer_id) FROM orders WHERE status = 'cancelled'").rows[0][0])
    assert n == every > 0
    monkeypatch.delenv("AUGHOR_ONTOLOGY_SECURITY")
    _as(monkeypatch, "ana")
    assert count()[0] == every                                              # off: as before, every reader the same
