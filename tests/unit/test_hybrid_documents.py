"""Arc FA, FA-1 — the documents are still searched when the embedder is down (ROADMAP §3.60); unconditional since
2026-10-28, on when its setup — the vector store up — exists (ROADMAP §3.65).

Measured 2026-10-26: document search was vector-only, so a stopped local embedder — the usual cause `knowledge/health.py`
explains — made the documents unsearchable, said honestly since ED-0 but searched not at all, while the store holding
every passage's text still answered. Now the passages the caller may read are ranked by their words (BM25 over the
scoped corpus), each hit says it was matched by words, and the door, the chat tool and the prompt say so; the search is
unavailable only when the store cannot be read either, and then it says which store did not answer and where it is set.

Drives the real indexer, as ED-0's tests do; the embedder and the store fail on request.
"""
from __future__ import annotations

import json

import pytest

import aughor.knowledge.indexer as idx

WORDS = "matched by words only — the embedder is unavailable"
OTHER_SCHEMA_DOC = idx.doctree_doc_id("c2", "main")


@pytest.fixture()
def plane(monkeypatch, tmp_path):
    """Four registered documents — two uploads, another organisation's upload and another connection's schema docs —
    and in the store their passages plus one of a document since deleted."""
    registry = tmp_path / "documents.json"
    monkeypatch.setenv("AUGHOR_DOCUMENTS_REGISTRY", str(registry))
    monkeypatch.setattr("aughor.db.registry.get_connection_org", lambda _c: None)
    monkeypatch.setattr("aughor.security.authz.tenant_scope", lambda: "org-a")
    monkeypatch.setattr("aughor.custom_agents.context.agent_doc_ids", lambda: None)
    rows = [{"doc_id": d, "filename": f"{d}.md", "title": d, "chunk_count": 1, "uploaded_at": "2026-10-24T00:00:00Z",
             **({"org_id": org} if org is not None else {})}
            for d, org in (("refunds", "org-a"), ("travel", "org-a"), ("theirs", "org-b"), (OTHER_SCHEMA_DOC, "org-a"))]
    registry.write_text(json.dumps(rows))
    passages = {
        "refunds": "A refund is issued within 14 days of a return reaching the warehouse.",
        "travel": "Travel is booked through the portal and approved by a manager.",
        "theirs": "Their refund rules: refund within 30 days, refund in store credit.",
        OTHER_SCHEMA_DOC: "refund_amount — the refund issued on a return, in the order's currency.",
        "deleted": "The old refund policy: refund within 7 days.",
    }
    calls = {"scroll": 0}

    def _set(*, embed_ok=True, store_ok=True):
        def _embed(_q):
            if not embed_ok:
                raise ConnectionError("connection refused")
            return [0.0] * 8

        def _search(_coll, _vector, top_k=10, query_filter=None):
            if not store_ok:
                raise ConnectionError("qdrant did not answer")
            return [{"payload": {"doc_id": "refunds", "text": passages["refunds"], "title": "refunds"}, "score": 0.9}]

        def _scroll(_coll, limit=10_000, *, strict=False):
            calls["scroll"] += 1
            if not store_ok:
                raise ConnectionError("qdrant did not answer")
            return [{"id": str(i), "payload": {"doc_id": d, "text": t, "title": d, "filename": f"{d}.md", "chunk_index": 0}}
                    for i, (d, t) in enumerate(passages.items())]

        monkeypatch.setattr("aughor.semantic.embedder.embed_one", _embed)
        monkeypatch.setattr("aughor.semantic.vector_store.search", _search)
        monkeypatch.setattr("aughor.semantic.vector_store.scroll_points", _scroll)
        return calls
    return _set


def test_the_embedder_down_the_scoped_passages_are_ranked_by_their_words_and_say_so(plane):
    plane(embed_ok=False)
    hits = idx.search_documents("how long does a refund take", connection_id="c1")
    # another organisation's upload, another connection's schema docs and a deleted document are never ranked;
    # a passage sharing no word with the question is no match
    assert [h["doc_id"] for h in hits] == ["refunds"]
    (hit,) = hits
    assert (hit["matched_by"], hit["said"]) == ("words", WORDS) and hit["score"] > 0
    assert hit["text"].startswith("A refund is issued") and hit["filename"] == "refunds.md"


def test_a_search_by_meaning_says_so(plane):
    plane()
    (hit,) = idx.search_documents("refund", connection_id="c1")
    assert hit["matched_by"] == "meaning" and "said" not in hit


def test_with_the_store_down_too_it_is_unavailable_and_names_both_and_where_the_store_is_set(plane, monkeypatch):
    plane(embed_ok=False, store_ok=False)
    monkeypatch.delenv("AUGHOR_QDRANT_URL", raising=False)
    monkeypatch.setattr("aughor.semantic.vector_store.backend", lambda: "qdrant")     # the embedded default
    with pytest.raises(idx.DocumentSearchUnavailable) as exc:
        idx.search_documents("refund", connection_id="c1")
    assert "the embedder failed (ConnectionError: connection refused)" in str(exc.value)
    assert "the document store could not be read (ConnectionError: qdrant did not answer)" in str(exc.value)
    assert str(exc.value).endswith("; the store is the embedded index at AUGHOR_QDRANT_PATH (default: the state "
                                   "directory's qdrant), which one process holds at a time")


def test_a_meaning_search_whose_store_is_down_says_where_the_store_is_set(plane, monkeypatch):
    plane(store_ok=False)
    monkeypatch.setenv("AUGHOR_QDRANT_URL", "http://qdrant.internal:6333")
    with pytest.raises(idx.DocumentSearchUnavailable) as exc:
        idx.search_documents("refund", connection_id="c1")
    assert str(exc.value) == ("the document store could not be read (ConnectionError: qdrant did not answer); the store "
                              "is the Qdrant server at AUGHOR_QDRANT_URL")


@pytest.mark.parametrize("env, backend, said", [
    ({"AUGHOR_DB_URL": "postgresql://h/db"}, "pgvector", "pgvector, in the database at AUGHOR_DB_URL"),
    ({}, "", "not installed here — add qdrant-client, or set AUGHOR_QDRANT_URL or a Postgres AUGHOR_DB_URL"),
])
def test_where_the_store_is_set_is_named_for_each_backend(monkeypatch, env, backend, said):
    monkeypatch.delenv("AUGHOR_QDRANT_URL", raising=False)
    monkeypatch.delenv("AUGHOR_DB_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr("aughor.semantic.vector_store.backend", lambda: backend)
    assert idx.store_where() == said


def test_the_chat_tool_says_why_the_documents_could_not_be_searched(plane):
    from aughor.agent import platform_tools as pt
    plane(embed_ok=False, store_ok=False)
    out = pt.search_documents("c1", {"query": "how long does a refund take"})
    assert out["count"] == 0 and out["why"].startswith("the document index could not be searched: the embedder failed")
    assert "the store is " in out["why"]


def test_a_search_that_read_the_most_passages_it_reads_says_so(plane, monkeypatch):
    plane(embed_ok=False)
    monkeypatch.setattr(idx, "WORDS_POOL", 5)
    (hit,) = idx.search_documents("refund take", connection_id="c1")
    assert hit["passages_read"] == 5 and hit["said"] == f"{WORDS} (the first 5 passages were read)"


def test_the_chat_tool_says_the_passages_were_matched_by_words(plane):
    from aughor.agent import platform_tools as pt
    plane(embed_ok=False)
    out = pt.search_documents("c1", {"query": "how long does a refund take"})
    assert out["count"] == 1 and out["matched_by"] == "words"
    assert out["note"].startswith(f"These passages were {WORDS}")


def test_the_prompt_is_told_the_passages_were_matched_by_words(plane):
    plane(embed_ok=False)
    section = idx.build_external_context_section("how long does a refund take", connection_id="c1")
    assert section.startswith(f"UPLOADED DOCUMENTS: {WORDS}.")
    assert "A refund is issued within 14 days" in section


def test_with_the_store_down_too_the_prompt_says_the_documents_could_not_be_searched(plane):
    plane(embed_ok=False, store_ok=False)
    assert idx.build_external_context_section("refund", connection_id="c1") == idx.DOCUMENTS_UNAVAILABLE_SECTION


def test_the_http_door_hands_back_each_hit_with_what_it_says(plane):
    from aughor.routers.knowledge import search_documents_endpoint
    plane(embed_ok=False)
    hits = search_documents_endpoint({"query": "how long does a refund take"}, request=None)
    assert hits and all(h["matched_by"] == "words" and h["said"] == WORDS for h in hits)
