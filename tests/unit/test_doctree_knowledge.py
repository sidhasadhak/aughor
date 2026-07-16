"""R8a — the doc tree's retrieval consumer: embed compiled schema docs into the
knowledge store with FQN provenance.

One chunk per TABLE node (summary + column summaries + analyst questions),
stamped fqn/kind="schema_doc"; a deterministic doc_id REPLACES on rebuild; the
external-context formatter cites the ontology node instead of a filename.

Hermetic: embedder + vector store are monkeypatched at their module seams (the
established per-test pattern — no Ollama/Qdrant); the registry rides the
conftest AUGHOR_DOCUMENTS_REGISTRY temp override, re-pointed per test.
"""
from __future__ import annotations

import pytest

import aughor.knowledge.indexer as idx


@pytest.fixture()
def fakes(monkeypatch, tmp_path):
    """Capture upserts/deletes; stub the embedder; isolate the registry."""
    state = {"upserts": [], "deleted": [], "ensured": 0}
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(tmp_path / "documents.json"))
    monkeypatch.setattr("aughor.semantic.embedder.embed",
                        lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr("aughor.semantic.vector_store.upsert",
                        lambda coll, points: state["upserts"].extend(points))
    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection",
                        lambda coll: state.__setitem__("ensured", state["ensured"] + 1))
    monkeypatch.setattr(idx, "_delete_doc_chunks",
                        lambda doc_id: state["deleted"].append(doc_id))
    return state


def _tree():
    from aughor.ontology.doctree import build_doc_tree
    from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph
    ent = OntologyEntity(
        id="sales", display_name="Sales", source_tables=["sales"],
        identity_key="id", grain_verified=True,
        properties={
            "brand": EntityProperty(name="brand", data_type="VARCHAR",
                                    semantic_type="dimension"),
            "amount": EntityProperty(name="amount", data_type="DOUBLE",
                                     semantic_type="measure"),
        },
    )
    graph = OntologyGraph(connection_id="connZ", schema_name="s", schema_fingerprint="f",
                          entities={"sales": ent})
    return build_doc_tree(graph, table_stats={"sales": {"row_count": 42}})


def test_index_doc_tree_embeds_table_chunks_with_fqn(fakes):
    out = idx.index_doc_tree(_tree(), connection_id="connZ", schema="s")
    assert out["chunk_count"] == 1
    assert out["doc_id"] == "doctree::connZ::s"

    payloads = [p["payload"] for p in fakes["upserts"]]
    assert len(payloads) == 1
    p = payloads[0]
    assert p["fqn"] == "s.sales"                       # ontology-node provenance
    assert p["kind"] == "schema_doc"
    assert "brand" in p["text"] and "amount" in p["text"]   # column summaries folded in
    assert "Questions this table can answer" in p["text"]

    # Registered (visible/deletable like any document), under the deterministic id.
    reg = idx.get_document("doctree::connZ::s")
    assert reg and reg["chunk_count"] == 1


def test_index_doc_tree_replaces_on_rebuild(fakes):
    idx.index_doc_tree(_tree(), connection_id="connZ", schema="s")
    idx.index_doc_tree(_tree(), connection_id="connZ", schema="s")
    assert fakes["deleted"] == ["doctree::connZ::s"] * 2   # replace, never accumulate
    assert len([d for d in idx.list_documents()
                if d["doc_id"] == "doctree::connZ::s"]) == 1


def test_formatter_cites_fqn_for_schema_docs(monkeypatch):
    hits = [
        {"title": "Sales", "filename": "schema-docs/connZ/s", "fqn": "s.sales",
         "text": "Sales table doc", "doc_id": "doctree::connZ::s", "chunk_index": 0},
        {"title": "Q3 report", "filename": "q3.pdf", "fqn": "",
         "text": "Uploaded doc", "doc_id": "u1", "chunk_index": 0},
    ]
    monkeypatch.setattr(idx, "search_documents", lambda q, top_k=4: hits)
    monkeypatch.setattr("aughor.user_agents.context.agent_doc_ids", lambda: None)
    section = idx.build_external_context_section("anything")
    assert "── Sales (s.sales) ──" in section           # compiled docs cite the node
    assert "── Q3 report (q3.pdf) ──" in section        # uploads keep the filename


def test_index_text_source_url_reaches_the_payload(fakes):
    """The previously-inert source_url param now lands in every chunk payload."""
    idx.index_text("A" * 200, "Wiki page", source="confluence",
                   source_url="https://wiki/x")
    assert fakes["upserts"], "chunks must be upserted"
    assert all(p["payload"]["source_url"] == "https://wiki/x" for p in fakes["upserts"])


def test_index_doc_tree_is_raise_transparent(monkeypatch, tmp_path):
    """Dead infra must RAISE (like index_text) — the autodoc hook's tolerate()
    wrapper is the resilience layer, and it can only work if failures surface."""
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(tmp_path / "documents.json"))

    def _down(coll):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection", _down)
    with pytest.raises(RuntimeError):
        idx.index_doc_tree(_tree(), connection_id="c", schema="s")


def test_empty_tree_indexes_nothing(fakes):
    from aughor.ontology.doctree import build_doc_tree
    from aughor.ontology.models import OntologyGraph
    empty = build_doc_tree(OntologyGraph(connection_id="c", schema_name="s",
                                         schema_fingerprint="f"))
    out = idx.index_doc_tree(empty, connection_id="c", schema="s")
    assert out["chunk_count"] == 0
    assert fakes["upserts"] == [] and fakes["deleted"] == []
