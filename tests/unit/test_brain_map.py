"""PENDING.md item 9 — the company-brain map (ROADMAP §3.30).

Every box is a store that exists, with a live count and its door; a store that cannot be read
says so instead of reading zero; every arrow is a measurement; CB-1's fact dates and history —
built with no screen — reach one through the facts box.
"""
from __future__ import annotations

import pytest

from aughor.hub import brain_map as bm
from aughor.ontology.context_graph import (
    ContextGraph, FactRevision, GraphEdge, GraphNode, Provenance, RetiredNode,
)

CONN = "brain-t"


def _node(nid, kind, *, observed_at="", basis="", history=()):
    return GraphNode(id=nid, kind=kind, label=nid.split(":", 1)[1],
                     provenance=Provenance(source="exploration", observed_at=observed_at, observed_basis=basis),
                     first_seen="2026-09-01T00:00:00Z", last_changed="2026-09-20T00:00:00Z" if history else "",
                     history=list(history))


@pytest.fixture
def graph(monkeypatch):
    revision = FactRevision(replaced_at="2026-09-20T00:00:00Z", reason="changed", label="revenue",
                            summary="SUM(num_of_item)", facts={"expression": "SUM(num_of_item)"})
    g = ContextGraph(org_id="", connection_id=CONN, schema_name="shop")
    for n in (_node("table:orders", "table", observed_at="2026-09-19", basis="source"),
              _node("metric:revenue", "metric", observed_at="2026-09-20", basis="build", history=[revision]),
              _node("finding:f1", "finding"), _node("brief:b1", "brief")):
        g.nodes[n.id] = n
    g.edges["e1"] = GraphEdge(id="e1", kind="derived_from", from_id="brief:b1", to_id="finding:f1",
                              provenance=Provenance(source="exploration"))
    g.retired["table:old_orders"] = RetiredNode(node=_node("table:old_orders", "table"),
                                                retired_at="2026-09-21T00:00:00Z")
    monkeypatch.setattr(bm, "_graphs", lambda org, conn: [g])
    return g


def _box(result, box_id):
    return next(b for b in result["boxes"] if b["id"] == box_id)


def test_a_connection_with_nothing_built_says_so_box_by_box(monkeypatch):
    monkeypatch.setattr(bm, "_graphs", lambda org, conn: [])
    result = bm.brain_map(CONN)
    assert [b["id"] for b in result["boxes"]] == ["facts", "metrics", "visibility", "findings", "outcomes",
                                                  "claims", "departures", "priorities", "owners"]
    assert {b["vault"] for b in result["boxes"]} == {"company", "engagement", "working_memory"}
    facts = _box(result, "facts")
    assert facts["count"] is None and facts["line"] == "no context graph is built for this connection yet"
    assert _box(result, "findings")["count"] == 0
    assert all(b["door"].startswith("GET /") for b in result["boxes"])


def test_an_unreadable_store_is_said_never_a_zero(monkeypatch):
    monkeypatch.setattr(bm, "_graphs", lambda org, conn: [])
    import aughor.semantic.metrics as metrics

    def boom(**kw):
        raise RuntimeError("catalogue locked")
    monkeypatch.setattr(metrics, "list_metrics", boom)
    box = _box(bm.brain_map(CONN), "metrics")
    assert box["count"] is None and box["line"] == "could not be read (RuntimeError)"


def test_facts_are_counted_dated_and_their_history_is_on_the_screen(graph):
    result = bm.brain_map(CONN)
    facts = _box(result, "facts")
    assert facts["count"] == 4
    d = facts["detail"]
    assert (d["dated"], d["dated_from_source"], d["with_history"], d["revisions"], d["retired"]) == (2, 1, 1, 1, 1)
    recent = d["recent"][0]
    assert recent["id"] == "metric:revenue" and recent["history"][0]["summary"] == "SUM(num_of_item)"
    assert facts["line"] == "2 of 4 dated · 1 changed since first seen · 1 retired, kept"


def test_every_edge_is_a_measured_count(graph, monkeypatch):
    import aughor.explorer.store as store
    monkeypatch.setattr(store, "get_findings", lambda key: [
        {"id": "f1", "domain": "Sales", "generated_at": "2026-09-20T10:00:00Z", "finding": "x"}])
    result = bm.brain_map(CONN)
    edges = {(e["from"], e["to"], e["label"]): e["count"] for e in result["edges"]}
    assert edges[("findings", "facts", "findings landed in the graph as facts")] == 1
    assert edges[("facts", "findings", "Briefing citations of findings")] == 1
    assert _box(result, "findings")["line"] == "1 across 1 domains · newest 2026-09-20"
