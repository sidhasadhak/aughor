"""ON-3 — `get_object` on the SP-5 roster: one object by type and key, through the same reader the
object page serves, answering (never raising) when there is nothing to open."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology.models import OntologyGraph

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
CONN = "objects-tool-t"


@pytest.fixture
def bound(tmp_path, monkeypatch):
    import aughor.db.connection as C
    import aughor.routers.ontology as R

    path = tmp_path / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    graph = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    monkeypatch.setattr(R, "served_ontology_graph", lambda connection_id, schema_name: graph)
    monkeypatch.setattr(C, "open_connection_for_with_schema", lambda *_a, **_k: open_connection(
        "duckdb", str(path), schema_name="ecommerce", connection_id=CONN))
    return path


def test_get_object_is_declared_once_on_the_roster_every_transport_derives_from():
    from aughor.agent.spotlight_roster import spotlight_roster
    assert [t.name for t in spotlight_roster("c1")].count("get_object") == 1


def test_get_object_opens_an_order_with_its_links_and_a_page_of_the_linked_objects(bound):
    from aughor.agent.object_tools import get_object_tool
    out = get_object_tool(CONN, {"object_type": "order", "key": "O000123", "link": "order_to_order_item"})
    assert out["found"] is True and (out["object_type"], out["pk"]) == ("order", "O000123")
    assert "O000123" in out["summary"] and "via order_to_order_item" in out["summary"]
    assert out["linked"]["link"] == "order_to_order_item" and out["linked"]["rows"]
    assert all(set(p) <= {"name", "value", "unit"} for p in out["properties"])


def test_get_object_answers_rather_than_raises(bound):
    from aughor.agent.object_tools import get_object_tool
    assert "error" in get_object_tool(CONN, {})
    missing = get_object_tool(CONN, {"object_type": "order", "key": "O999999"})
    assert missing["found"] is False and missing["summary"].startswith("Not found")
    unknown = get_object_tool(CONN, {"object_type": "invoice", "key": "1"})
    assert unknown["found"] is False and "order" in unknown["available"]
    refused = get_object_tool(CONN, {"object_type": "order_item", "key": "7", "link": "order_item_to_review"})
    assert refused["found"] is True and "N:N" in refused["linked"]["refused"]
