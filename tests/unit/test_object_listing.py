"""Arc OC-4 — a page of objects through the object door's own compiler (ROADMAP §3.56).

Before: the door answered aggregates only. `POST /objects/query` grouped and counted, and the one listing that existed
(`list_linked`) read a single object's links with no total and no edit merged. A cockpit's objects table needs one row
per object, the columns a person chose, a sort that holds still across pages, and the total the set holds. Every
claim here is held to a hand-written query over the seeded samples warehouse: the page, the sort with the key breaking
ties, the total under a segment and filters, an accepted edit listed like a column, and — behind
`ontology.cockpit_pieces` — each promise's overdue segment, whose total is exactly the measurement's `open_overdue`.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.ontology import overrides as OV
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_listing
from tests.unit.test_object_bindings import seed
from tests.unit.test_object_processes import _DEADLINES, FULFILMENT, declare, fresh_graph

_FLAG = "ontology.cockpit_pieces"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("listing") / "samples.duckdb"
    seed(path)
    con = duckdb.connect(str(path))
    con.execute(_DEADLINES)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="listing-t")
    yield conn
    conn.close()


@pytest.fixture
def graph():
    return fresh_graph()


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


def _flag(monkeypatch, on: bool) -> None:
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: on and name == _FLAG)


def run(db, sql: str) -> list[tuple]:
    result = db.execute("reference", sql)
    assert not result.error, (result.error, sql)
    return [tuple(None if v is None or v == "NULL" else str(v) for v in row) for row in result.rows]   # cells are text


def total(db, compiled) -> int:
    return int(run(db, compiled.count_sql)[0][0])


def listing(graph, edits=None, **body):
    return compile_object_listing({"object_type": "order", **body}, graph, overlay=edits)


# ── a page ──────────────────────────────────────────────────────────────────────────────────

def test_a_page_is_the_key_then_the_columns_asked_for_in_key_order(db, graph):
    page = listing(graph, columns=["status", "order_date"], limit=5, offset=10)
    assert page.key == "order_id" and [c["name"] for c in page.columns] == ["status", "order_date"]
    assert run(db, page.sql) == run(db, "SELECT order_id, status, order_date FROM ecommerce.orders "
                                        "ORDER BY order_id LIMIT 5 OFFSET 10")
    assert total(db, page) == int(run(db, "SELECT COUNT(*) FROM ecommerce.orders")[0][0])


def test_a_sort_holds_still_across_pages_because_the_key_breaks_ties(db, graph):
    pages = [run(db, listing(graph, columns=["status"], order_by="status", descending=True, limit=7,
                             offset=n).sql) for n in (0, 7, 14)]
    want = run(db, "SELECT order_id, status FROM ecommerce.orders ORDER BY status DESC NULLS LAST, order_id LIMIT 21")
    assert [r for p in pages for r in p] == want


def test_a_column_through_a_to_one_link_is_read_from_the_linked_object(db, graph):
    page = listing(graph, columns=["customer.customer_id", "status"], limit=4)
    assert run(db, page.sql) == run(db, "SELECT o.order_id, c.customer_id, o.status FROM ecommerce.orders o "
                                        "LEFT JOIN ecommerce.customers c ON c.customer_id = o.customer_id "
                                        "ORDER BY o.order_id LIMIT 4")


def test_the_total_is_the_object_set_under_the_filters_not_the_page(db, graph):
    page = listing(graph, columns=["status"], filters=[{"path": "status", "op": "=", "value": "delivered"}], limit=3)
    assert len(run(db, page.sql)) == 3
    assert total(db, page) == int(run(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE status = 'delivered'")[0][0])


def test_no_columns_asked_lists_the_types_first_properties(db, graph):
    page = listing(graph, limit=2)
    assert page.columns and len(page.columns) <= 6 and page.key not in [c["name"] for c in page.columns]
    assert len(run(db, page.sql)) == 2


# ── an accepted edit is a column ────────────────────────────────────────────────────────────

def _edit(key: str, value: str = "true"):
    return NS(kind="property", object_type="order", column="flagged_for_review", row_key=key, body=value,
              note="check with carrier", actor="ana", source="user", origin="action:flag_for_review",
              created_at="2026-10-09T12:00:00", provenance=lambda: "ana via action:flag_for_review")


def test_an_accepted_edit_is_listed_like_a_column_and_says_so(db, graph):
    first, second = (r[0] for r in run(db, "SELECT order_id FROM ecommerce.orders ORDER BY order_id LIMIT 2"))
    page = listing(graph, [_edit(second)], columns=["status", "flagged_for_review"], limit=2)
    assert page.columns[-1] == {"name": "flagged_for_review", "path": "flagged_for_review",
                                "label": "flagged_for_review", "type": "BOOLEAN", "edited": True}
    got = {r[0]: r[2] for r in run(db, page.sql)}
    assert got[first] is None and got[second].lower() == "true"
    assert page.overlay and page.overlay[0]["pk"] == second
    flagged = listing(graph, [_edit(second)], filters=[{"path": "flagged_for_review", "op": "=", "value": True}])
    assert total(db, flagged) == 1


# ── refused, with why ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body, says", [
    ({"columns": ["no_such_thing"]}, "no property 'no_such_thing'"),
    ({"columns": ["status"], "order_by": "order_date"}, "is not a listed column"),
    ({"columns": ["order_to_order_item.quantity"]}, "a to-many link"),
    ({"limit": 500}, "the listing is malformed"),
])
def test_a_listing_the_door_cannot_vouch_for_is_refused_with_why(graph, body, says):
    with pytest.raises(ObjectQueryRefused) as exc:
        listing(graph, **body)
    assert says in exc.value.reason


# ── the overdue segment: a process board's count, listed ────────────────────────────────────

def test_the_overdue_segment_lists_exactly_what_the_promise_counted(db, graph, monkeypatch):
    _, process = declare(graph, db, FULFILMENT)
    delivery = process.stages[2].promise
    assert delivery.open_overdue and delivery.open_overdue > 0
    _flag(monkeypatch, True)
    page = listing(graph, segment="overdue_delivery", columns=["shipped_at", "delivered_at"], limit=10)
    assert total(db, page) == delivery.open_overdue
    assert any("overdue_delivery (derived from the delivery promise of process order_fulfilment" in line
               for line in page.plan)
    assert all(r[2] is None and r[1] is not None for r in run(db, page.sql))      # shipped, not delivered


def test_off_the_overdue_segment_is_a_name_the_door_does_not_know(db, graph, monkeypatch):
    declare(graph, db, FULFILMENT)
    _flag(monkeypatch, False)
    with pytest.raises(ObjectQueryRefused) as exc:
        listing(graph, segment="overdue_delivery")
    assert "has no segment 'overdue_delivery'" in exc.value.reason
    assert "late_delivery" in exc.value.available                    # what the door always derived, unchanged


def test_an_unmeasured_promise_has_no_overdue_list_and_says_why(graph, monkeypatch):
    from aughor.ontology.processes import process_from_fields
    graph.processes["order_fulfilment"] = process_from_fields("order_fulfilment", {
        "entity": "Order", "stages": FULFILMENT["stages"]})
    _flag(monkeypatch, True)
    with pytest.raises(ObjectQueryRefused) as exc:
        listing(graph, segment="overdue_delivery")
    assert "has not been measured" in exc.value.reason


# ── the door ────────────────────────────────────────────────────────────────────────────────

def test_the_door_lists_a_page_with_its_total_and_the_plan_over_http(tmp_path, monkeypatch, client):
    import json

    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.ontology.models import OntologyGraph
    from aughor.util.json_store import KeyedJsonStore
    from tests.unit.test_object_bindings import GRAPH

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology("listing-door-t", "ecommerce", "fp", OntologyGraph.model_validate(json.loads(GRAPH.read_text())))
    path = tmp_path / "samples.duckdb"
    seed(path)
    monkeypatch.setattr(C, "open_connection_for_with_schema", lambda *_a, **_k: open_connection(
        "duckdb", str(path), schema_name="ecommerce", connection_id="listing-door-t"))
    params = {"connection_id": "listing-door-t", "schema_name": "ecommerce"}
    body = {"object_type": "order", "columns": ["status"], "filters": [{"path": "status", "value": "delivered"}],
            "order_by": "order_id", "descending": True, "limit": 3, "offset": 1}
    r = client.post("/objects/list", params=params, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["path"] == "listed" and out["key"] == "order_id" and out["names"] == ["order_id", "status"]
    con = duckdb.connect(str(path), read_only=True)
    want = con.execute("SELECT order_id, status FROM ecommerce.orders WHERE status = 'delivered' "
                       "ORDER BY order_id DESC LIMIT 3 OFFSET 1").fetchall()
    (n,) = con.execute("SELECT COUNT(*) FROM ecommerce.orders WHERE status = 'delivered'").fetchone()
    con.close()
    assert [tuple(row) for row in out["rows"]] == [tuple(row) for row in want] and out["total"] == n
    assert out["plan"][0].startswith("list(order)") and out["error"] in ("", None)
    refused = client.post("/objects/list", params=params, json={"object_type": "order", "columns": ["nope"]}).json()
    assert refused["path"] == "refused" and "no property 'nope'" in refused["refused"]
