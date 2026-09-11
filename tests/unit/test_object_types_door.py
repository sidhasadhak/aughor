"""ON-3b — the entity-type map's doors, driven over HTTP: the map, one type, the paths between two types, a display
property declared and measured, and a link named by its verb.

The graph is the measured samples ontology seeded into a hermetic ontology store and overrides tree; the warehouse
is the bundled samples SQL in a temp DuckDB file; every measured number is compared with a hand-written count. No
model is called anywhere on these paths.
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
CONN = "object-types-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def warehouse(tmp_path, monkeypatch):
    """A cached graph for CONN/ecommerce, an empty overrides tree, and a warehouse every opener resolves to."""
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


def test_the_map_the_type_and_the_path_doors_read_the_served_graph(warehouse, client):
    m = client.get("/object-types", params=PARAMS)
    assert m.status_code == 200, m.text
    assert {t["object_type"] for t in m.json()["object_types"]} == {"customer", "order", "order_item", "product", "review"}
    assert len(m.json()["links"]) == 5
    item = client.get("/object-types/order_item", params=PARAMS).json()
    assert item["path"] == "object_type" and item["schema_name"] == "ecommerce"
    assert any(not link["traversable"] and "N:N" in link["why_not"] for link in item["links"])
    refused = client.get("/object-types/invoice", params=PARAMS).json()
    assert refused["path"] == "refused" and "order" in refused["available"]
    paths = client.get("/object-paths", params={**PARAMS, "source": "customer", "target": "product"}).json()
    assert paths["path"] == "paths" and paths["found"] == 2
    assert paths["paths"][0]["traversable"] and not paths["paths"][1]["traversable"]
    assert client.get("/object-types", params={"connection_id": "nothing-built-t"}).status_code == 404


def test_a_display_property_is_declared_merged_measured_and_titles_the_object_page(warehouse, client):
    described = client.put("/ontology/entities/Customer", params=PARAMS, json={"description": "people who buy"})
    assert described.status_code == 200, described.text
    declared = client.put("/ontology/entities/Customer", params=PARAMS, json={"display_property": "CITY"})
    assert declared.status_code == 200, declared.text
    # merged into the entity's override — the description survives — and spelled as the type spells it
    assert declared.json()["override"]["fields"] == {"description": "people who buy", "display_property": "city"}
    unknown = client.put("/ontology/entities/Customer", params=PARAMS, json={"display_property": "nickname"})
    assert unknown.status_code == 400 and "full_name" in unknown.json()["detail"]
    assert client.put("/ontology/entities/Invoice", params=PARAMS,
                      json={"display_property": "city"}).status_code == 404

    before = client.get("/object-types/customer", params=PARAMS).json()["display_property"]
    assert (before["property"], before["source"], before["verified"]) == ("city", "human", None)
    measured = client.post("/ontology/measure", params=PARAMS)
    assert measured.status_code == 200, measured.text
    assert "Customer" in measured.json()["display_properties"]["overrides_measured"]
    after = client.get("/object-types/customer", params=PARAMS).json()
    [counts] = _reference(warehouse, "SELECT COUNT(*) AS n, COUNT(city) AS v, COUNT(DISTINCT city) AS d FROM customers")
    rows, non_null, distinct = (int(v) for v in counts)                      # the connection hands cells back as text
    shown = after["display_property"]
    assert (shown["rows"], shown["non_null"], shown["distinct"]) == (rows, non_null, distinct)
    assert after["key"]["rows"] == rows and after["key"]["verified"] is True       # the same door measured the key

    page = client.get("/objects/customer/C00042", params=PARAMS).json()
    [[city]] = _reference(warehouse, "SELECT city FROM customers WHERE customer_id = 'C00042'")
    assert page["title"] == city and (page["display"]["property"], page["display"]["source"]) == ("city", "human")


def test_a_link_is_named_by_its_verb_and_the_name_is_accepted_where_links_are_named(warehouse, client):
    named = client.put("/ontology/links/Customer_RELATES_TO_Order", params=PARAMS, json={"name": "customer_buys"})
    assert named.status_code == 200, named.text
    customer = client.get("/object-types/customer", params=PARAMS).json()
    link = next(link for link in customer["links"] if link["relationship"] == "Customer_RELATES_TO_Order")
    assert (link["name"], link["business_name"], link["business_name_source"]) == (
        "customer_to_order", "customer_buys", "human")
    compiled = client.post("/objects/query", params={**PARAMS, "execute": "false"},
                           json={"object_type": "customer", "measures": [{"agg": "count", "path": "customer_buys"}]})
    assert compiled.json()["path"] == "compiled", compiled.text
    taken = client.put("/ontology/links/Customer_RELATES_TO_Order", params=PARAMS,
                       json={"name": "customer_writes_review"})
    assert taken.status_code == 400 and "already has a link" in taken.json()["detail"]
    assert client.put("/ontology/links/Nope", params=PARAMS, json={"name": "x_y"}).status_code == 404
    reverted = client.delete("/ontology/overrides/link/Customer_RELATES_TO_Order", params=PARAMS)
    assert reverted.status_code == 200 and reverted.json()["removed"] is True
    link = next(link for link in client.get("/object-types/customer", params=PARAMS).json()["links"]
                if link["relationship"] == "Customer_RELATES_TO_Order")
    assert (link["business_name"], link["business_name_source"]) == ("customer_places_order", "proposed")
