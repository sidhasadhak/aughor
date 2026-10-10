"""Arc OC-7 — security on the contract: who sees which objects and which properties, said wherever it bites.

Held on the seeded samples warehouse through the real compiler and the real object page. Order declares two row
policies — the fulfilment group sees shipped and delivered orders, support sees cancelled and refunded ones — and
total_amount is visible to finance only. Ana (fulfilment) and Ben (support, finance) list the same orders and see
different rows, and Ana sees the amount masked, each told why; Carl, in no group, sees none and is told which groups
would; an agent acting for Ben reads only what both may. The falsifier: with enforcement off every one of those
assertions fails — the last test turns it off and checks the reader sees everything again.
"""
from __future__ import annotations

import pytest

from aughor.ontology.models import RowPolicy, Sensitivity
from aughor.ontology.security import reset_acting_agent, set_acting_agent
from aughor.semantic.object_instances import ObjectWithheld, get_object
from aughor.semantic.object_query import (MaskedProperty, ObjectListing, ObjectQuery, compile_object_listing,
                                          compile_object_query)
from tests.unit.test_object_actions import CONN, ORDER, db, graph  # noqa: F401 — fixtures by name

SHIPPED = {"shipped", "delivered"}
RETURNED = {"cancelled", "refunded"}


@pytest.fixture
def secured(graph, monkeypatch):  # noqa: F811
    from aughor.rbac.groups import add_member, upsert_group
    monkeypatch.setenv("AUGHOR_ONTOLOGY_SECURITY", "1")
    for group, members in (("fulfilment", ["user:ana"]), ("support", ["user:ben"]),
                           ("finance", ["user:ben"])):
        upsert_group("default", group, group.capitalize())
        for m in members:
            add_member("default", group, m)
    order = graph.entities["Order"]
    order.row_policies = [
        RowPolicy(group="fulfilment", conditions=[{"path": "status", "op": "in", "values": sorted(SHIPPED)}]),
        RowPolicy(group="support", conditions=[{"path": "status", "op": "in", "values": sorted(RETURNED)}])]
    order.sensitive = {"total_amount": Sensitivity(level="confidential", visible_to=["finance"])}
    return graph


def _as(monkeypatch, who: str) -> None:
    monkeypatch.setenv("AUGHOR_LOCAL_USER", who)


def _listing(graph, db, columns=("status", "total_amount")):  # noqa: F811
    compiled = compile_object_listing(ObjectListing(entity="Order", columns=list(columns), limit=200), graph,
                                      dialect="duckdb")
    # the display path renders SQL NULL as the text "NULL" and numbers as text
    rows = [[None if v in (None, "NULL") else v for v in r] for r in db.execute("t", compiled.sql).rows]
    total = int(db.execute("t", compiled.count_sql).rows[0][0])
    return compiled, rows, total


def test_two_people_list_the_same_orders_and_see_different_rows_and_a_masked_amount_each_told_why(secured, db, monkeypatch):  # noqa: F811
    _as(monkeypatch, "ana")
    compiled, rows, ana_total = _listing(secured, db)
    assert rows and {r[1] for r in rows} <= SHIPPED and all(r[2] is None for r in rows)
    assert any("only the Order objects user:ana may see are shown — fulfilment: status in" in c for c in compiled.caveats)
    assert any("Order.total_amount is confidential — masked for user:ana; finance may read it" in c
               for c in compiled.caveats)
    assert [c.get("masked") for c in compiled.columns] == [None, True]
    _as(monkeypatch, "ben")
    compiled, rows, ben_total = _listing(secured, db)
    assert rows and {r[1] for r in rows} <= RETURNED and all(r[2] is not None for r in rows)
    assert ben_total != ana_total and not any("masked" in c for c in compiled.caveats)


def test_a_reader_in_no_group_sees_no_object_and_is_told_which_groups_would(secured, db, monkeypatch):  # noqa: F811
    _as(monkeypatch, "carl")
    compiled, rows, total = _listing(secured, db, columns=("status",))
    assert (rows, total) == ([], 0)
    assert any("user:carl is in none of its groups (fulfilment, support)" in c for c in compiled.caveats)


def test_a_masked_property_cannot_shape_an_answer_it_would_show(secured, monkeypatch):
    _as(monkeypatch, "ana")
    q = ObjectQuery(object_type="order", measures=[{"agg": "sum", "path": "total_amount"}])
    with pytest.raises(MaskedProperty, match="masked for user:ana"):
        compile_object_query(q, secured)
    with pytest.raises(MaskedProperty):
        compile_object_query(ObjectQuery(object_type="order", measures=[{"agg": "count"}],
                                         filters=[{"path": "total_amount", "op": ">", "value": 100}]), secured)
    _as(monkeypatch, "ben")
    assert "SUM" in compile_object_query(q, secured).sql.upper()


def test_the_object_page_masks_the_amount_and_says_an_order_outside_your_rows_is_withheld(secured, db, monkeypatch):  # noqa: F811
    _as(monkeypatch, "ana")
    page = get_object(secured, db, "order", ORDER)                           # O000123 is delivered: Ana's
    amount = next(p for p in page.properties if p["name"] == "total_amount")
    assert amount["value"] is None and "masked for user:ana" in amount["withheld"]
    _as(monkeypatch, "ben")
    with pytest.raises(ObjectWithheld, match=f"Order {ORDER} is withheld from you — .*support: status in"):
        get_object(secured, db, "order", ORDER)


def test_an_agent_acting_for_a_person_reads_only_what_both_may(secured, db, monkeypatch):  # noqa: F811
    from aughor.rbac.groups import add_member
    add_member("default", "fulfilment", "agent:bot")                          # the agent: fulfilment, no finance
    _as(monkeypatch, "ben")                                                  # the person: support and finance
    token = set_acting_agent("agent:bot")
    try:
        compiled, rows, total = _listing(secured, db)
        assert (rows, total) == ([], 0)                                       # support ∩ fulfilment: no order
        assert any("both the person's and the agent's" in c or "agent:bot" in c for c in compiled.caveats)
        with pytest.raises(MaskedProperty, match="masked for agent:bot"):
            compile_object_query(ObjectQuery(object_type="order", measures=[{"agg": "sum", "path": "total_amount"}]),
                                 secured)
    finally:
        reset_acting_agent(token)


def test_the_acting_agent_header_narrows_a_listing_over_http(secured, client, monkeypatch):  # noqa: F811
    """The header reaches the door through its router dependency — the same read as above, over the wire."""
    from aughor.rbac.groups import add_member
    add_member("default", "fulfilment", "agent:bot")
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: secured)
    _as(monkeypatch, "ben")
    body = {"entity": "Order", "columns": ["status"], "limit": 200}
    params = {"connection_id": CONN, "schema_name": "ecommerce"}
    alone = client.post("/objects/list", params=params, json=body)
    assert alone.status_code == 200 and alone.json()["total"] > 0, alone.text
    acting = client.post("/objects/list", params=params, json=body, headers={"X-Aughor-Acting-Agent": "agent:bot"})
    assert acting.status_code == 200 and acting.json()["total"] == 0, acting.text
    assert any("agent:bot" in c for c in acting.json()["caveats"])


def test_the_declare_doors_take_own_properties_and_never_mask_the_key(graph, client, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology._get_ontology_graph", lambda conn, schema=None: graph)
    params = {"connection_id": CONN, "schema_name": "ecommerce"}
    linked = client.put("/ontology/entities/Order/row-policies", params=params,
                        json={"policies": [{"group": "eu", "conditions": [{"path": "customer.country", "op": "=", "value": "DE"}]}]})
    assert linked.status_code == 400 and "own properties" in linked.json()["detail"]
    kept = client.put("/ontology/entities/Order/row-policies", params=params,
                      json={"policies": [{"group": "eu", "conditions": [{"path": "status", "op": "=", "value": "shipped"}]}]})
    assert kept.status_code == 200, kept.text
    key = client.put("/ontology/entities/Order/sensitive/order_id", params=params, json={"visible_to": ["finance"]})
    assert key.status_code == 400 and "never masked" in key.json()["detail"]
    ok = client.put("/ontology/entities/Order/sensitive/total_amount", params=params,
                    json={"level": "pii", "visible_to": ["finance"]})
    assert ok.status_code == 200 and ok.json()["sensitive"]["visible_to"] == ["finance"]
    from aughor.ontology.overrides import apply_overrides
    served, _ = apply_overrides(graph, CONN, "ecommerce")
    assert served.entities["Order"].row_policies[0].group == "eu"
    assert served.entities["Order"].sensitive["total_amount"].level == "pii"
    assert client.delete("/ontology/entities/Order/sensitive/total_amount", params=params).status_code == 200


def test_off_every_reader_sees_every_order_and_every_amount_as_before(secured, db, monkeypatch):  # noqa: F811
    """The falsifier: the assertions above must fail with enforcement off — here, off, nothing is filtered or masked
    and the SQL is exactly what an entity with no policy compiles."""
    monkeypatch.delenv("AUGHOR_ONTOLOGY_SECURITY", raising=False)
    _as(monkeypatch, "carl")
    compiled, rows, total = _listing(secured, db)
    statuses = {r[1] for r in rows}
    assert statuses & SHIPPED and statuses & RETURNED and all(r[2] is not None for r in rows)
    bare = secured.model_copy(deep=True)
    bare.entities["Order"].row_policies, bare.entities["Order"].sensitive = [], {}
    plain = compile_object_listing(ObjectListing(entity="Order", columns=["status", "total_amount"], limit=200), bare,
                                   dialect="duckdb")
    assert compiled.sql == plain.sql and compiled.caveats == plain.caveats
    assert get_object(secured, db, "order", ORDER).properties                 # no withheld, no mask
