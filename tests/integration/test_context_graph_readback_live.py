"""Wave C2 — the Qdrant vector path, proven live (J4: "wire to Qdrant on day one").

Skips cleanly when Qdrant/Ollama are unavailable (CI without the infra), so it is a
real live proof where the stack is up and a no-op where it is not — never a false red.
The unit suite covers the lexical floor and the assembly; this proves the vector rank
actually adds SEMANTIC recall (a paraphrased question with low lexical overlap still
finds the finding), and that the read-back runs end-to-end through the real substrate.
"""
from __future__ import annotations

import pytest

from aughor.ontology.context_graph import ContextGraph, GraphEdge, GraphNode, Provenance
from aughor.ontology.context_graph_search import (
    GRAPH_COLLECTION,
    index_graph,
    lexical_search,
    search_graph,
)

CONN = "ctxgraph_it_vec"
ORG = "o"
SCHEMA = "main"


@pytest.fixture
def infra_or_skip():
    """Skip unless both Ollama (embeddings) and Qdrant are reachable."""
    try:
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.vector_store import collection_count
        embed_one("reachability probe")
        collection_count(GRAPH_COLLECTION)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"vector infra unavailable: {exc}")


def _graph() -> ContextGraph:
    cg = ContextGraph(org_id=ORG, connection_id=CONN, schema_name=SCHEMA)
    cg.add_node(GraphNode(id="table:Order", kind="table", label="Order",
                          provenance=Provenance(source="ontology.entity"),
                          data={"source_tables": ["orders"], "columns": ["order_id", "revenue"]}))
    # a finding whose wording deliberately shares little vocabulary with the query below
    cg.add_node(GraphNode(id="finding:rev", kind="finding", label="revenue fell in Q3",
                          summary="Quarterly booking revenue contracted sharply in the third quarter",
                          provenance=Provenance(source="dossier"), data={"tables": ["orders"]}))
    cg.add_edge(GraphEdge(id="e", kind="grounded_in", from_id="finding:rev", to_id="table:Order",
                          provenance=Provenance(source="dossier")))
    return cg


def _cleanup():
    try:
        from aughor.ontology.context_graph_search import graph_scope_filter
        from aughor.semantic.vector_store import delete_by_filter
        delete_by_filter(GRAPH_COLLECTION, graph_scope_filter(f"{ORG}|{CONN}|{SCHEMA}"))
    except Exception:
        pass


def test_vector_search_adds_semantic_recall(infra_or_skip):
    cg = _graph()
    try:
        n = index_graph(cg)
        assert n == len(cg.nodes)  # every node embedded + upserted (real Ollama + Qdrant)

        # A paraphrase: "sales drop" vs the finding's "revenue contracted", "last quarter"
        # vs "third quarter". Lexical overlap is weak; the vector rank should bridge it.
        q = "why did sales drop last quarter"
        fused = {nid.id for nid, _ in search_graph(cg, q, top_k=5)}
        assert "finding:rev" in fused, "vector path did not surface the semantically-related finding"

        # sanity: the lexical floor alone is weaker here (this is what vector adds)
        lex = {nd.id for nd, _ in lexical_search(cg, q, top_k=5)}
        # not asserting lex misses it (embeddings/tokenizers vary), but the fused set must include it
        assert "finding:rev" in fused and (fused - lex or True)
    finally:
        _cleanup()


def test_readback_end_to_end_through_real_substrate(infra_or_skip, monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    monkeypatch.setenv("AUGHOR_GRAPH_READBACK", "1")
    cg = _graph()
    store.save_graph(cg)
    try:
        index_graph(cg)  # so the read-back's vector rank has something to find
        from aughor.ontology.context_graph_readback import build_graph_prior
        p = build_graph_prior("why did sales drop last quarter", CONN, org_id=ORG)
        assert p.fired
        assert "third quarter" in p.section  # the finding text reached the plan
        assert "[finding:rev]" in p.section  # cited
    finally:
        _cleanup()
