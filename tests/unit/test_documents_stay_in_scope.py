"""PENDING item 16 — documents stay inside their connection and organisation.

Measured 2026-09-24 by reading: `search_documents` filtered nothing. With no agent active, a
question on one connection was handed another connection's generated schema docs as "external
context" — tables that connection does not have; with sign-in on, another organisation's
uploads; and a deleted document's leftover vectors (deleting them is best-effort) were still
served. The registry row is now the authority on both: whose a document is, and whether it
still exists.

Hermetic: the vector store, the embedder, the connection registry and the sign-in scope are
stubbed at their module seams; the registry rides a temp `AUGHOR_DOCUMENTS_REGISTRY`.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import aughor.knowledge.indexer as idx

CONNECTION_ORGS = {"connA": "orgA", "connB": "orgB", "samples": None}


@pytest.fixture()
def corpus(monkeypatch, tmp_path):
    registry = tmp_path / "documents.json"
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(registry))
    points: list[dict] = []

    def _search(coll, vector, top_k=10, query_filter=None):
        ranked = [{"payload": p, "score": round(0.99 - i * 0.01, 2)} for i, p in enumerate(points)]
        return ranked[:top_k]

    monkeypatch.setattr("aughor.semantic.vector_store.search", _search)
    monkeypatch.setattr("aughor.semantic.vector_store.collection_count", lambda coll: len(points))
    monkeypatch.setattr("aughor.semantic.embedder.embed_one", lambda q: [0.0] * 8)
    monkeypatch.setattr("aughor.db.registry.get_connection_org", CONNECTION_ORGS.get)
    monkeypatch.setattr("aughor.security.authz.tenant_scope", lambda: None)   # sign-in off

    def add(doc_id: str, *, org: object = "unset", registered: bool = True) -> None:
        points.append({"doc_id": doc_id, "text": f"passage of {doc_id}", "filename": doc_id,
                       "title": doc_id, "chunk_index": 0})
        if not registered:
            return
        rows = json.loads(registry.read_text()) if registry.exists() else []
        row = {"doc_id": doc_id, "filename": doc_id, "title": doc_id, "chunk_count": 1,
               "uploaded_at": "2026-09-24T00:00:00Z"}
        if org != "unset":                 # "unset" = a row indexed before owners were stamped
            row["org_id"] = org
        rows.append(row)
        registry.write_text(json.dumps(rows))

    return add


def _ids(hits: list[dict]) -> list[str]:
    return [h["doc_id"] for h in hits]


def test_a_question_never_reads_another_connections_schema_docs(corpus):
    corpus("doctree::connB::main", org="orgB")          # ranked first, and wrong for connA
    corpus("doctree::connA::main", org="orgA")
    corpus("u1", org="orgA")

    assert _ids(idx.search_documents("revenue", connection_id="connA")) == [
        "doctree::connA::main", "u1"]
    # the Documents screen's own search names no connection, and keeps its whole corpus
    assert _ids(idx.search_documents("revenue")) == [
        "doctree::connB::main", "doctree::connA::main", "u1"]


def test_a_deleted_documents_leftover_vectors_are_not_served(corpus):
    corpus("gone", registered=False)          # its registry row was deleted; its vectors were not
    corpus("u1", org="default")

    assert _ids(idx.search_documents("revenue")) == ["u1"]


def test_with_sign_in_on_only_the_callers_organisation_is_read(corpus, monkeypatch):
    monkeypatch.setattr("aughor.security.authz.tenant_scope", lambda: "orgA")
    corpus("u2", org="orgB")
    corpus("u1", org="orgA")
    corpus("doctree::samples::main", org="")         # a shared builtin's docs: every org reads them
    corpus("old-upload")                             # indexed before owners: the default org's
    corpus("doctree::connB::main")                   # an unstamped schema doc: its connection's org

    assert _ids(idx.search_documents("revenue")) == ["u1", "doctree::samples::main"]

    monkeypatch.setattr("aughor.security.authz.tenant_scope", lambda: "default")
    assert _ids(idx.search_documents("revenue")) == ["doctree::samples::main", "old-upload"]


def test_the_filters_do_not_shrink_the_answer_below_top_k(corpus):
    for i in range(10):
        corpus(f"doctree::connB::s{i}", org="orgB")
    for i in range(3):
        corpus(f"doctree::connA::s{i}", org="orgA")

    assert _ids(idx.search_documents("revenue", top_k=2, connection_id="connA")) == [
        "doctree::connA::s0", "doctree::connA::s1"]


def test_indexing_stamps_the_owner_and_a_reindex_keeps_it(monkeypatch, tmp_path):
    from aughor.org.context import reset_org_id, set_org_id
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(tmp_path / "documents.json"))
    monkeypatch.setattr("aughor.db.registry.get_connection_org", CONNECTION_ORGS.get)

    token = set_org_id("orgA")
    try:
        idx._register("u9", "q3.pdf", "Q3", 4, "2026-09-24T00:00:00Z")
    finally:
        reset_org_id(token)
    token = set_org_id("orgB")                 # a connector re-sync running under another org
    try:
        idx._register("u9", "q3.pdf", "Q3", 5, "2026-09-24T01:00:00Z")
        idx._register("doctree::connA::main", "schema-docs/connA/main", "docs", 3,
                      "2026-09-24T00:00:00Z")
        idx._register("doctree::samples::main", "schema-docs/samples/main", "docs", 3,
                      "2026-09-24T00:00:00Z")
    finally:
        reset_org_id(token)

    assert idx.get_document("u9")["org_id"] == "orgA"
    assert idx.get_document("u9")["chunk_count"] == 5
    assert idx.get_document("doctree::connA::main")["org_id"] == "orgA"       # its connection's
    assert idx.get_document("doctree::connA::main")["connection_id"] == "connA"
    assert idx.get_document("doctree::samples::main")["org_id"] == ""         # every org's
    assert idx.document_org("u9") == "orgA"
    assert idx.document_org("doctree::samples::main") is None
    assert idx.document_org("never-registered") is None


def test_the_by_id_doors_refuse_another_organisations_document(corpus):
    from aughor.security.authz import authorize_resource
    corpus("u2", org="orgB")
    corpus("doctree::samples::main", org="")
    a_user_in_org_a = SimpleNamespace(org_id="orgA")

    assert authorize_resource("document", "u2", a_user_in_org_a) is False
    assert authorize_resource("document", "doctree::samples::main", a_user_in_org_a) is True
    assert authorize_resource("document", "missing", a_user_in_org_a) is True  # the door's 404
    assert authorize_resource("document", "u2", None) is True                  # sign-in off


def test_the_list_door_shows_only_the_callers_documents(corpus, monkeypatch):
    from aughor.routers.knowledge import list_documents_endpoint
    corpus("u1", org="orgA")
    corpus("u2", org="orgB")
    corpus("doctree::samples::main", org="")

    assert sorted(d["doc_id"] for d in list_documents_endpoint()) == [
        "doctree::samples::main", "u1", "u2"]                     # sign-in off: unchanged
    monkeypatch.setattr("aughor.security.authz.tenant_scope", lambda: "orgA")
    assert sorted(d["doc_id"] for d in list_documents_endpoint()) == [
        "doctree::samples::main", "u1"]


def test_every_question_path_names_its_connection(monkeypatch):
    """The four callers that put documents in front of a model all pass their connection."""
    seen: list = []
    monkeypatch.setattr(idx, "search_documents",
                        lambda q, top_k=4, **kw: seen.append(kw.get("connection_id")) or [])
    monkeypatch.setattr("aughor.custom_agents.context.agent_doc_ids", lambda: None)

    idx.build_external_context_section("q", connection_id="connA")
    from aughor.agent.grounding import external_docs
    external_docs("q", connection_id="connA")
    from aughor.agent import platform_tools
    platform_tools.search_documents("connA", {"query": "q"})

    assert seen == ["connA", "connA", "connA"]


def test_doctree_connection_reads_the_id_backwards():
    assert idx.doctree_connection(idx.doctree_doc_id("connA", "main")) == "connA"
    assert idx.doctree_connection(idx.doctree_doc_id("connA")) == "connA"
    assert idx.doctree_connection("u1") is None
