"""A claim's page cites the links from its types into other connections (ROADMAP §6 item 42e).

Read-only: the organisation's declarations and the Record, never a statement on either connection.
The graph here has the trap Wave G5 paid for built in — two connections that each hold a table
called `orders` — so a tie made on a bare name would show.
"""
from __future__ import annotations

from aughor.ontology.models import Backing, OntologyEntity, OntologyGraph, OntologyRelationship
from aughor.ontology.sources import stamp_traversals
from aughor.record import claims as C
from aughor.record import cross_links as X


def _type(type_id: str, table: str, conn: str) -> OntologyEntity:
    return OntologyEntity(id=type_id, display_name=type_id, source_tables=[table], identity_key="id", grain_verified=True,
                          backing=Backing(kind="table", table=table, primary_key="id", connection_id=conn))


def _link(a: str, b: str, a_table: str, b_table: str, name: str = "") -> OntologyRelationship:
    return OntologyRelationship(id=f"{a}_RELATES_TO_{b}", from_entity=a, to_entity=b, cardinality="N:1",
                                join_sql=f"{a_table}.ref = {b_table}.id", from_table=a_table, from_col="ref",
                                to_table=b_table, to_col="id", **({"name": name} if name else {}))


def _graph() -> OntologyGraph:
    graph = OntologyGraph(
        connection_id="org=default", schema_fingerprint="",
        entities={"Order": _type("Order", "shop.orders", "shop"), "Line": _type("Line", "shop.order_items", "shop"),
                  "Account": _type("Account", "accounts", "crm"), "Renewal": _type("Renewal", "crm.orders", "crm")},
        relationships={r.id: r for r in (
            _link("Order", "Account", "shop.orders", "accounts", name="order_placed_by_account"),
            _link("Line", "Order", "shop.order_items", "shop.orders"))})
    stamp_traversals(graph)
    return graph


def _claim(conn: str, text: str, *, sql: str = "", entities=(), state: str = "", cid: str = "") -> C.Claim:
    c = C.Claim(kind="finding", tier="measured", about=C.About(kind="connection", key=conn),
                statement=C.Statement(text=text), status="Final", as_of="2026-10-05",
                warrants=[C.Warrant(kind="run", ref="r1", detail=sql)] if sql else [],
                author="agent:explorer", author_kind="agent", extra={"entities": list(entities)}, state=state)
    c.id = cid or text[:12]
    return c


def test_two_tables_are_the_same_only_where_every_segment_both_spell_agrees():
    assert X.same_table("shop.orders", "orders") and X.same_table('"shop"."orders"', "SHOP.ORDERS")
    assert not X.same_table("shop.orders", "crm.orders")
    assert not X.same_table("orders", "order_items") and not X.same_table("", "orders")


def test_a_claim_is_tied_to_a_type_by_its_runs_tables_or_its_named_entities_on_its_own_connection():
    graph = _graph()
    by_table = _claim("shop", "Orders fell 4%", sql="SELECT COUNT(*) FROM shop.orders WHERE status = 'done'")
    by_name = _claim("shop", "Orders fell 4%", entities=["order"])
    assert X.types_of(by_table, graph) == {"Order"} == X.types_of(by_name, graph)
    # the same bare table name on ANOTHER connection is another table, and another type
    assert X.types_of(_claim("crm", "Renewals rose", sql="SELECT COUNT(*) FROM orders"), graph) == {"Renewal"}
    assert X.types_of(_claim("shop", "Stock is flat", sql="SELECT 1 FROM shop.inventory"), graph) == set()
    organisation_wide = _claim("shop", "x", entities=["Order"])
    organisation_wide.about = C.About(kind="organisation", key="default")
    assert X.types_of(organisation_wide, graph) == set()


def test_a_claim_cites_the_link_across_and_the_far_sides_claims_about_the_far_type():
    graph = _graph()
    far = [_claim("crm", "Enterprise accounts renew at 91%", entities=["Account"], cid="far-1"),
           _claim("crm", "Renewals rose 3%", sql="SELECT COUNT(*) FROM crm.orders", cid="far-2"),      # about Renewal
           _claim("crm", "Accounts churned 12%", entities=["Account"], state="withdrawn", cid="far-3")]
    read: list[str] = []

    def claims_on(conn):
        read.append(conn)
        return far

    claim = _claim("shop", "Orders fell 4%", sql="SELECT COUNT(*) FROM shop.orders")
    [link] = X.cross_links(claim, [("default", graph)], claims_on=claims_on)
    assert (link["near_type"], link["far_type"], link["far_connection"]) == ("Order", "Account", "crm")
    assert link["name"] == "order placed by account" and link["withheld"] is False and link["domain"] == "default"
    assert [c["id"] for c in link["far_claims"]] == ["far-1"] and link["far_claims_total"] == 1
    assert read == ["crm"]                                    # the Record is read; no connection is

    # read from the far side, the same link points back
    [back] = X.cross_links(far[0], [("default", graph)], claims_on=lambda conn: [claim])
    assert (back["near_type"], back["far_type"], back["far_connection"]) == ("Account", "Order", "shop")
    assert [c["text"] for c in back["far_claims"]] == ["Orders fell 4%"]


def test_a_link_inside_one_connection_and_a_claim_tied_to_no_type_cite_nothing():
    graph = _graph()
    lines = _claim("shop", "Lines per order rose", sql="SELECT COUNT(*) FROM shop.order_items")
    assert X.types_of(lines, graph) == {"Line"}
    assert X.cross_links(lines, [("default", graph)], claims_on=lambda conn: []) == []       # Line→Order is a join
    untied = _claim("shop", "Stock is flat", sql="SELECT 1 FROM shop.inventory")
    assert X.cross_links(untied, [("default", graph)], claims_on=lambda conn: []) == []


def test_a_far_connection_the_reader_may_not_see_is_said_and_nothing_of_it_is_listed():
    graph = _graph()
    asked: list[str] = []

    def claims_on(conn):
        asked.append(conn)
        return [_claim("crm", "Enterprise accounts renew at 91%", entities=["Account"])]

    claim = _claim("shop", "Orders fell 4%", entities=["Order"])
    [link] = X.cross_links(claim, [("default", graph)], visible=lambda conn: conn != "crm", claims_on=claims_on)
    assert link["withheld"] is True and link["near_type"] == "Order"
    assert link["far_type"] == "" and link["far_connection"] == "" and link["far_claims"] == []
    assert asked == []                                        # not even read


def test_the_door_opens_the_ontology_and_this_module_never_does(monkeypatch):
    """Only the doors that take ?domain= read an organisation's ontology (`test_organisation_ontology_boundary`).
    The door hands the graphs in; a claim that is not there, or not the reader's to see, is a 404."""
    import inspect

    from fastapi import HTTPException

    from aughor.routers import ontology as door
    assert "aughor.ontology.domains" not in inspect.getsource(X)
    monkeypatch.setattr("aughor.ontology.domains.domain_names", lambda org=None: ["retail"])
    opened: list[str] = []

    def graph_of(scope):
        opened.append(scope.name)
        return _graph()

    monkeypatch.setattr("aughor.ontology.domains.domain_graph", graph_of)
    claim = _claim("shop", "Orders fell 4%", entities=["Order"], cid="near-1")
    monkeypatch.setattr("aughor.record.claims.get", lambda cid: claim if cid == "near-1" else None)
    monkeypatch.setattr(X, "_claims_on", lambda conn: [_claim("crm", "Enterprise accounts renew at 91%", entities=["Account"], cid="far-1")])
    monkeypatch.setattr("aughor.security.authz.org_visible_conn_ids", lambda: None)

    out = door.list_claim_links("near-1", domain=None)
    assert opened == ["default", "retail"]                                # every domain the organisation declared in
    assert {(l["domain"], l["far_type"], l["far_connection"]) for l in out["links"]} == {
        ("default", "Account", "crm"), ("retail", "Account", "crm")}
    opened.clear()
    assert len(door.list_claim_links("near-1", domain="retail")["links"]) == 1 and opened == ["retail"]

    for hidden in (lambda: {"crm"}, None):
        if hidden is not None:
            monkeypatch.setattr("aughor.security.authz.org_visible_conn_ids", hidden)
        try:
            door.list_claim_links("near-1" if hidden else "nobody", domain=None)
            raise AssertionError("expected a 404")
        except HTTPException as refused:
            assert refused.status_code == 404
