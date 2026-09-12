"""ON-2 — the object plane's doors, driven: the catalog and the compiled query over HTTP, and the
`query_objects` tool the conversation is offered behind `ask.query_objects`.

The graph is the measured samples ontology seeded into a hermetic ontology store; the warehouse is
the bundled samples SQL seeded into a temp DuckDB file; every answer is compared with a
hand-written reference. No model is called anywhere on these paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.models import OntologyGraph

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
CONN = "objects-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """A cached graph for CONN/ecommerce, and a warehouse every opener resolves to."""
    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology(CONN, "ecommerce", "fp", OntologyGraph.model_validate(json.loads(GRAPH.read_text())))
    path = tmp_path / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()

    def _open(*_a, **_k):
        return open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)

    monkeypatch.setattr(C, "open_connection_for_with_schema", _open)
    return _open


def _reference(open_conn, sql: str) -> list:
    return [list(row) for row in open_conn().execute("reference", sql).rows]


# ── HTTP ────────────────────────────────────────────────────────────────────────────────

def test_the_catalog_door_lists_the_object_types_and_404s_a_connection_with_none(warehouse, client):
    r = client.get("/objects/catalog", params=PARAMS)
    assert r.status_code == 200, r.text
    types = {t["object_type"]: t for t in r.json()["object_types"]}
    assert set(types) == {"customer", "order", "order_item", "product", "review"}
    assert any(link["name"] == "order_to_order_item" and link["usable"] for link in types["order"]["links"])
    assert client.get("/objects/catalog", params={"connection_id": "nothing-built-t"}).status_code == 404


def test_the_query_door_answers_through_the_compiled_path_and_the_battery_stays_quiet(warehouse, client):
    body = {"object_type": "order", "by": ["payment_method"], "measures": [
        {"name": "revenue", "agg": "sum", "path": "total_amount", "decimals": 2},
        {"name": "lines", "agg": "count", "path": "order_item"}]}
    r = client.post("/objects/query", params=PARAMS, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["path"] == "compiled" and out["error"] is None
    assert out["dimensions"] == ["payment_method"] and out["measures"] == ["revenue", "lines"]
    assert [link["treatment"] for link in out["links"]] == ["pre-aggregated"]
    assert not any(g.get("guard", "").startswith("fanout") for g in out["guard_receipts"])
    want = _reference(warehouse, "SELECT o.payment_method, ROUND(SUM(o.total_amount), 2), "
                                 "(SELECT COUNT(*) FROM order_items i JOIN orders o2 ON o2.order_id = i.order_id "
                                 " WHERE o2.payment_method = o.payment_method) FROM orders o GROUP BY 1")
    got = sorted((row[0], round(float(row[1]), 2), int(row[2])) for row in out["rows"])
    assert got == sorted((row[0], round(float(row[1]), 2), int(row[2])) for row in want)


def test_a_refusal_is_an_answer_and_execute_false_returns_the_plan_without_rows(warehouse, client):
    refused = client.post("/objects/query", params=PARAMS, json={
        "object_type": "order_item", "measures": [{"agg": "sum", "path": "order.total_amount"}]})
    assert refused.status_code == 200 and refused.json()["path"] == "refused"
    assert "that is the fan-out" in refused.json()["refused"]
    plan = client.post("/objects/query", params={**PARAMS, "execute": "false"},
                       json={"object_type": "order", "measures": [{"metric": "revenue"}]}).json()
    assert plan["path"] == "compiled" and "rows" not in plan and plan["sql"].startswith("SELECT")


# ── the conversation's tool ─────────────────────────────────────────────────────────────

def test_query_objects_is_offered_first_only_behind_its_flag_and_only_where_an_ontology_exists(warehouse):
    from aughor.agent import converse_tools as ct
    from aughor.kernel.flags import flag_overrides

    assert "query_objects" not in [t.name for t in ct.converse_tools(CONN)]      # flag off: today's roster
    with flag_overrides({"ask.query_objects": True}):
        assert [t.name for t in ct.converse_tools(CONN)][0] == "query_objects"
        assert "query_objects" not in [t.name for t in ct.converse_tools("nothing-built-t")]


def test_the_tool_compiles_runs_discloses_and_refuses(warehouse, monkeypatch):
    from aughor.agent import converse_tools as ct

    monkeypatch.setattr(ct, "_connection", lambda cid: warehouse())
    out = ct.query_objects(CONN, {"object_type": "order", "segment": "delivered_orders",
                                  "measures": [{"agg": "count"}]})
    assert out["path"] == "compiled" and out["row_count"] == 1
    assert out["rows"][0][0] == _reference(warehouse, "SELECT COUNT(*) FROM orders WHERE status = 'delivered'")[0][0]
    entry = ct.query_objects(CONN, {"object_type": "order"})
    assert entry["path"] == "catalog" and "delivered_orders" in entry["object_type"]["segments"]
    refused = ct.query_objects(CONN, {"object_type": "order", "measures": [{"agg": "sum", "path": "status"}]})
    assert refused["path"] == "refused" and "run_sql" in refused["instruction"]


def test_a_streamed_compiled_answer_carries_a_receipt_that_names_the_compiled_path(warehouse, monkeypatch):
    from aughor.agent import converse_tools as ct
    import aughor.routers.investigations as inv

    monkeypatch.setattr(ct, "_connection", lambda cid: warehouse())
    written: dict = {}
    monkeypatch.setattr(inv, "write_answer_receipt", lambda **kw: written.update(kw) or {"receipt_id": "r-1"})
    frames: list = []
    ct.query_objects(CONN, {"object_type": "order", "by": ["customer.country"], "measures": [{"metric": "revenue"}]},
                     emit=lambda kind, payload: frames.append((kind, payload)), user_question="revenue by country")
    kinds = [kind for kind, _ in frames]
    assert kinds[:2] == ["sql", "compiled"] and "receipt_id" in kinds and kinds[-1] == "done"
    assert dict(frames)["compiled"] == {"intent_type": "object_query", "entity": "order",
                                        "measure": "revenue", "dimension": "country"}
    assert written["guard_edges"][0][:2] == ("validated_by", "guard:object_compiler")
    assert written["payload_extra"]["path"] == "compiled" and written["payload_extra"]["body"] == "converse.query_objects"


# ── ON-3: the object page's doors ───────────────────────────────────────────────────────

def test_an_object_page_reads_one_order_live_and_404s_a_missing_key(warehouse, client):
    r = client.get("/objects/order/O000123", params=PARAMS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["path"], body["key"], body["pk"]) == ("object", "order_id", "O000123")
    (customer_id,) = _reference(warehouse, "SELECT customer_id FROM orders WHERE order_id = 'O000123'")[0]
    links = {link["name"]: link for link in body["links"]}
    assert links["order_to_customer"]["pk"] == str(customer_id)
    assert links["order_to_order_item"]["count"] > 0
    assert client.get("/objects/order/O999999", params=PARAMS).status_code == 404
    refused = client.get("/objects/invoice/1", params=PARAMS).json()
    assert refused["path"] == "refused" and "order" in refused["available"]


def test_a_links_page_lists_the_linked_objects_in_key_order(warehouse, client):
    r = client.get("/objects/customer/C00042/links/customer_to_order", params={**PARAMS, "limit": 3})
    assert r.status_code == 200, r.text
    page = r.json()
    expected = [str(row[0]) for row in _reference(
        warehouse, "SELECT order_id FROM orders WHERE customer_id = 'C00042' ORDER BY order_id")]
    position = page["columns"].index("order_id")
    assert [str(row[position]) for row in page["rows"]] == expected[:3] and page["has_more"] is True
    refused = client.get("/objects/order_item/7/links/order_item_to_review", params=PARAMS).json()
    assert refused["path"] == "refused" and "N:N" in refused["refused"]


# ── the titles door (ON-3b) ─────────────────────────────────────────────────────────────────────

def test_the_titles_door_names_a_page_of_keys_and_refuses_an_unknown_type(warehouse, client):
    """What an answer table asks once for every key it linked, rather than once per key."""
    want = {str(r[0]): str(r[1]) for r in _reference(
        warehouse, "SELECT customer_id, full_name FROM customers ORDER BY customer_id LIMIT 4")}
    r = client.post("/objects/titles", params=PARAMS, json={"object_type": "customer", "keys": list(want)})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["path"] == "titles" and out["property"] == "full_name" and out["titles"] == want

    keyed = client.post("/objects/titles", params=PARAMS, json={"object_type": "order", "keys": ["O000123"]}).json()
    assert keyed["titles"] == {} and "named by its key" in keyed["note"]

    refused = client.post("/objects/titles", params=PARAMS, json={"object_type": "invoice", "keys": ["1"]}).json()
    assert refused["path"] == "refused" and "order" in refused["available"]

    empty = client.post("/objects/titles", params=PARAMS, json={"object_type": "customer", "keys": []}).json()
    assert empty["titles"] == {}      # no keys is not an error, and asks the warehouse nothing


def test_a_display_property_may_come_from_a_static_binding_but_never_from_a_timeseries_one(warehouse, client):
    """The declaration door's ON-1b widening, and the one it refuses with a sentence."""
    # A keyed SELECT, because a type's own backing table may not be re-bound — and one row per product is what
    # the door counts before it accepts it.
    bound = client.put("/ontology/entities/Product/bindings/naming", params=PARAMS,
                       json={"sql": "SELECT product_id, MAX(product_name) AS label FROM products GROUP BY 1",
                             "key": "product_id", "kind": "static"})
    assert bound.status_code == 200, bound.text
    named = client.put("/ontology/entities/Product", params=PARAMS, json={"display_property": "label"})
    assert named.status_code == 200, named.text

    series = client.put("/ontology/entities/Product/bindings/moving", params=PARAMS,
                        json={"table": "order_items", "key": "product_id", "kind": "timeseries",
                              "time_column": "order_id", "properties": {"moving_price": "unit_price"}})
    assert series.status_code == 200, series.text
    refused = client.put("/ontology/entities/Product", params=PARAMS, json={"display_property": "moving_price"})
    assert refused.status_code == 400
    assert "would change when the next reading lands" in refused.json()["detail"]

    missing = client.put("/ontology/entities/Product", params=PARAMS, json={"display_property": "nope"})
    assert missing.status_code == 400 and "has no property 'nope'" in missing.json()["detail"]
