"""A failed document search is not an empty one (ROADMAP §3.58, ED-0).

`search_documents` ended `except Exception: return []`, so an embedder that was down, a vector
store that did not answer and a genuine no-match all reached every caller as the same empty
list. Its first check had the same fault one level down: `collection_count` answers 0 for a
store that is down as well as for an empty one, so a stopped Qdrant answered `[]` before the
search was tried.

The chat tool already said *could not be searched* on an exception, and its test proved it by
replacing the indexer with one that raised. The real indexer never raised, so the tool's
branch had never seen the failure it was written for. These tests drive the real indexer.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import aughor.knowledge.indexer as idx


@pytest.fixture()
def plane(monkeypatch, tmp_path):
    """One registered document; the embedder and the store fail on request."""
    registry = tmp_path / "documents.json"
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(registry))
    monkeypatch.setattr("aughor.db.registry.get_connection_org", lambda _c: None)
    monkeypatch.setattr("aughor.security.authz.tenant_scope", lambda: None)
    monkeypatch.setattr("aughor.custom_agents.context.agent_doc_ids", lambda: None)
    # What the old first check read: a store that is down answers 0, as an empty one does.
    monkeypatch.setattr("aughor.semantic.vector_store.collection_count", lambda _c: 0)
    calls = {"embed": 0}

    def _set(*, registered=True, embed_ok=True, store_ok=True):
        rows = ([{"doc_id": "d1", "filename": "d1.md", "title": "d1", "chunk_count": 1,
                  "uploaded_at": "2026-10-24T00:00:00Z"}] if registered else [])
        registry.write_text(json.dumps(rows))

        def _embed(_q):
            calls["embed"] += 1
            if not embed_ok:
                raise ConnectionError("connection refused")
            return [0.0] * 8

        def _search(_coll, _vector, top_k=10, query_filter=None):
            if not store_ok:
                raise ConnectionError("qdrant did not answer")
            return [{"payload": {"doc_id": "d1", "text": "a passage", "title": "d1"},
                     "score": 0.9}]

        monkeypatch.setattr("aughor.semantic.embedder.embed_one", _embed)
        monkeypatch.setattr("aughor.semantic.vector_store.search", _search)
        return calls
    return _set


def test_an_unreachable_embedder_is_unavailable_not_empty(plane):
    plane(embed_ok=False)
    with pytest.raises(idx.DocumentSearchUnavailable, match="ConnectionError"):
        idx.search_documents("refund policy")


def test_a_store_that_is_down_is_unavailable_not_empty(plane):
    """The store answers 0 to `collection_count` here, as a stopped Qdrant does; the old first
    check returned `[]` on it without trying the search."""
    plane(store_ok=False)
    with pytest.raises(idx.DocumentSearchUnavailable, match="qdrant did not answer"):
        idx.search_documents("refund policy")


def test_nothing_indexed_is_still_empty_and_spends_no_embedding(plane):
    calls = plane(registered=False, embed_ok=False)
    assert idx.search_documents("refund policy") == []
    assert calls["embed"] == 0


def test_a_healthy_search_still_answers(plane):
    plane()
    assert [h["doc_id"] for h in idx.search_documents("refund policy")] == ["d1"]


def test_the_chat_tool_says_so_over_the_real_indexer(plane):
    from aughor.agent import platform_tools as pt

    plane(embed_ok=False)
    out = pt.search_documents("c1", {"query": "refund policy"})
    assert out["count"] == 0 and "could not be searched" in out["why"]


def test_a_prompt_is_told_the_documents_could_not_be_searched(plane):
    plane(store_ok=False)
    assert idx.build_external_context_section("refund policy") == idx.DOCUMENTS_UNAVAILABLE_SECTION


def test_a_prompt_reads_nothing_when_nothing_is_indexed(plane):
    plane(registered=False)
    assert idx.build_external_context_section("refund policy") == ""


def test_the_http_door_answers_503_not_an_empty_list(plane):
    from aughor.routers.knowledge import search_documents_endpoint

    plane(embed_ok=False)
    with pytest.raises(HTTPException) as exc:
        search_documents_endpoint({"query": "refund policy"}, request=None)
    assert exc.value.status_code == 503
    assert "unavailable" in exc.value.detail
