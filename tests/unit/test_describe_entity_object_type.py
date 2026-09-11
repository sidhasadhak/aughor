"""ON-3c — the agent reads the type: `describe_entity` returns the ON-1 object type, one body on every transport.

The roster's `describe_entity` and the MCP server's are two callers of `knowledge_tools.describe_entity`; this
file pins that the body IS the entity-type slice (`aughor.semantic.object_types`), that the conversation and
MCP return the identical dict for the same call, that G5's clearance trim still guards it, and that the
knowledge graph's table node answers only where no ontology describes the type — labelled as such.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import aughor.mcp.knowledge_tools as KT
from aughor.agent import platform_tools as pt
from aughor.ontology.models import OntologyGraph
from aughor.semantic.object_types import describe_object_type

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


@pytest.fixture
def graph(monkeypatch):
    served = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    monkeypatch.setattr(KT, "_served_ontology", lambda *a, **k: served)
    monkeypatch.setattr(KT, "_accepted_edits", lambda *a, **k: [])
    monkeypatch.setattr(KT, "_load_graph", lambda *a, **k: None)
    return served


def test_describe_entity_returns_the_object_type_not_the_table_node(graph):
    out = KT.describe_entity("samples", "orders")                         # asked by its table, answered by its type
    assert (out["available"], out["kind"], out["notice"]) == (True, "object_type", "")
    expected = describe_object_type(graph, "order")
    assert out["summary"] == expected.pop("summary")
    assert out["object_type"] == expected
    sources = {p["name"]: p["source"] for p in out["object_type"]["properties"]}
    assert sources["total_amount"] == {"binding": "orders", "table": "orders", "column": "total_amount"}
    assert any(link["name"] == "order_to_order_item" and link["cardinality"] == "1:N" and link["traversable"]
               for link in out["object_type"]["links"])
    assert KT.describe_entity("samples", "ecommerce.orders")["object_type"]["object_type"] == "order"


def test_the_same_call_over_mcp_returns_the_identical_body(graph):
    from aughor.mcp import server

    conversation = pt.describe_entity("samples", {"entity": "order_item"})
    mcp = asyncio.run(server.describe_entity(connection="samples", entity="order_item"))
    assert conversation == mcp and conversation["kind"] == "object_type"
    assert any(not link["traversable"] and "N:N" in link["why_not"] for link in mcp["object_type"]["links"])


def test_a_withheld_type_is_withheld_and_the_notice_never_names_it(graph, monkeypatch):
    from aughor.govern import tags as T
    from aughor.govern.tags import ClearanceDecision, Requirement

    req = Requirement(key="tier", value="restricted", clearance="clearance.restricted")
    monkeypatch.setattr(T, "check", lambda securable, held, bypass=False: (
        ClearanceDecision(securable=securable, allowed=False, requirements=[req], missing=[req])
        if "customers" in securable else ClearanceDecision(securable=securable, allowed=True)))
    out = KT.describe_entity("samples", "customer")
    assert out["available"] is False and "withheld" in out["reason"] and out["notice"]
    assert "customers" not in out["notice"] and "object_type" not in out
    assert KT.describe_entity("samples", "order")["available"] is True


def test_an_unknown_type_says_so_and_names_the_types_that_exist(graph):
    out = KT.describe_entity("samples", "invoice")
    assert out["available"] is False and "no object type 'invoice'" in out["reason"]
    assert set(out["object_types"]) == {"customer", "order", "order_item", "product", "review"}


def test_with_no_ontology_the_knowledge_graph_table_node_answers_labelled_as_such(monkeypatch):
    node = SimpleNamespace(id="table:orders", kind="table", label="orders", summary="",
                           data={"source_tables": ["orders"]})
    monkeypatch.setattr(KT, "_served_ontology", lambda *a, **k: None)
    monkeypatch.setattr(KT, "_load_graph", lambda *a, **k: SimpleNamespace(nodes={node.id: node}, edges=[]))
    out = KT.describe_entity("c1", "orders")
    assert (out["available"], out["kind"], out["entity"]["label"]) == (True, "table", "orders")


def test_the_routing_policy_names_the_sources_and_the_sibling_tools():
    spec = next(s for s in pt.platform_tools("c1") if s.name == "describe_entity")
    for claim in ("SOURCE", "measured cardinality", "get_object", "search_graph", "describe_table"):
        assert claim in spec.description, claim
