"""Wave C2 — grep-the-graph-first read-back (hermetic).

The vector path is monkeypatched out so these are deterministic and infra-free; the
lexical floor and the read-back assembly are what's under test. A separate live test
exercises the real Qdrant+Ollama vector path.
"""
from __future__ import annotations

import pytest

from aughor.ontology import context_graph_search as search_mod
from aughor.ontology.context_graph import ContextGraph, GraphEdge, GraphNode, Provenance
from aughor.ontology.context_graph_search import (
    lexical_search,
    merge_graphs,
    one_hop,
    search_graph,
)


@pytest.fixture(autouse=True)
def _no_vector(monkeypatch):
    """Force the lexical floor — no Ollama/Qdrant call in the unit suite."""
    monkeypatch.setattr(search_mod, "_vector_search", lambda *a, **k: [])


def _graph() -> ContextGraph:
    cg = ContextGraph(org_id="o", connection_id="c", schema_name="main")
    cg.add_node(GraphNode(id="table:Order", kind="table", label="Order",
                          provenance=Provenance(source="ontology.entity"),
                          data={"source_tables": ["orders"], "columns": ["order_id", "revenue"]}))
    cg.add_node(GraphNode(id="table:Customer", kind="table", label="Customer",
                          provenance=Provenance(source="ontology.entity"),
                          data={"source_tables": ["customers"]}))
    cg.add_edge(GraphEdge(id="e1", kind="joins_on", from_id="table:Order", to_id="table:Customer",
                          provenance=Provenance(source="join_guard", measured=0.97,
                                                note="value_overlap=0.970 join_confidence=verified")))
    cg.add_node(GraphNode(id="finding:f1", kind="finding", label="orders never terminal",
                          summary="32% of orders never reach a terminal state",
                          provenance=Provenance(source="dossier"), data={"tables": ["orders"]}))
    cg.add_edge(GraphEdge(id="e2", kind="grounded_in", from_id="finding:f1", to_id="table:Order",
                          provenance=Provenance(source="dossier")))
    return cg


# ── search ────────────────────────────────────────────────────────────────────

def test_lexical_search_ranks_relevant_nodes():
    cg = _graph()
    hits = lexical_search(cg, "which orders never reach a terminal state", top_k=5)
    ids = [n.id for n, _ in hits]
    assert "finding:f1" in ids  # the finding's text overlaps strongly
    assert "table:Order" in ids


def test_unrelated_question_matches_nothing():
    cg = _graph()
    assert lexical_search(cg, "employee salary headcount by department", top_k=5) == []


def test_one_hop_pulls_findings_onto_a_matched_table():
    cg = _graph()
    nodes, edges = one_hop(cg, ["table:Order"])
    nids = {n.id for n in nodes}
    assert "finding:f1" in nids  # reached via the grounded_in edge — the read-back's reach
    assert any(e.kind == "grounded_in" for e in edges)


def test_merge_graphs_unions_schemas():
    a = _graph()
    b = ContextGraph(org_id="o", connection_id="c", schema_name="raw")
    b.add_node(GraphNode(id="table:Event", kind="table", label="Event",
                         provenance=Provenance(source="ontology.entity")))
    merged = merge_graphs([a, b])
    assert "table:Order" in merged.nodes and "table:Event" in merged.nodes


def test_search_graph_returns_ranked_without_vector():
    cg = _graph()
    hits = search_graph(cg, "orders terminal state", top_k=4)
    assert hits and hits[0][0].kind in ("finding", "table")


# ── read-back assembly ──────────────────────────────────────────────────────

def test_readback_empty_when_flag_off():
    """Byte-identical: default off ⇒ empty string, no citations."""
    from aughor.ontology.context_graph_readback import build_graph_prior
    p = build_graph_prior("which orders never reach a terminal state", "c", org_id="o")
    assert p.section == "" and p.cited_node_ids == []


def _save(cg, monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    store.save_graph(cg)


def test_readback_surfaces_the_unread_finding(monkeypatch, tmp_path):
    """The point of Wave C: a finding that was write-only now reaches the plan, cited."""
    _save(_graph(), monkeypatch, tmp_path)
    monkeypatch.setenv("AUGHOR_GRAPH_READBACK", "1")
    from aughor.ontology.context_graph_readback import build_graph_prior, last_cited_nodes

    p = build_graph_prior("which orders never reach a terminal state", "c", org_id="o")
    assert p.fired
    assert "32% of orders never reach a terminal state" in p.section  # the finding text
    assert "[finding:f1]" in p.section                                # cited by node id
    # P2: the join states its warrant class AND the number behind it — a measured join
    # and a name match must not read as the same claim.
    assert "97% of key values overlap" in p.section
    assert "[measured:" in p.section
    assert "finding:f1" in p.cited_node_ids
    assert "finding:f1" in last_cited_nodes()                         # contextvar for the receipt


def test_readback_empty_when_no_graph_built(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    monkeypatch.setenv("AUGHOR_GRAPH_READBACK", "1")
    from aughor.ontology.context_graph_readback import build_graph_prior
    assert build_graph_prior("anything", "no-such-conn", org_id="o").section == ""


# ── the wiring: independent of closed_loop, at the one inject site ────────────

def test_build_corrections_section_appends_graph_block(monkeypatch, tmp_path):
    """The graph block reaches both live paths via build_corrections_section, and is
    gated INDEPENDENTLY of closed_loop (fires with closed_loop OFF)."""
    _save(_graph(), monkeypatch, tmp_path)
    monkeypatch.setenv("AUGHOR_GRAPH_READBACK", "1")
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "0")  # explicitly off
    from aughor.feedback.priors import build_corrections_section
    section = build_corrections_section("which orders never reach a terminal state", "c", org_id="o")
    assert "CONNECTION GRAPH" in section
    assert "32% of orders never reach a terminal state" in section


def test_build_corrections_section_byte_identical_when_both_off(monkeypatch, tmp_path):
    _save(_graph(), monkeypatch, tmp_path)
    monkeypatch.setenv("AUGHOR_GRAPH_READBACK", "0")
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "0")
    from aughor.feedback.priors import build_corrections_section
    assert build_corrections_section("which orders never reach a terminal state", "c", org_id="o") == ""
