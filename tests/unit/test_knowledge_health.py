"""An empty knowledge base had four causes and one appearance.

`search_documents` ends `except Exception: return []`, and four conditions arrive there
indistinguishably: nothing matched · nothing is indexed · the store is unavailable · **the
embedder is unreachable**. The last is the common one on this platform and the least
guessable: embeddings come from a LOCAL Ollama (`localhost:11434`, `nomic-embed-text`),
which runs on a laptop and does not exist on Vercel. The same code indexes 92 chunks here
and nothing there, reporting the same empty list.

They call for opposite responses — rephrase, upload, configure a backend, start a server —
and an empty list recommends the first for all four.

The drift check is here for the same reason one level down: the registry and the store are
two records of one corpus with nothing reconciling them, and measured on a real install they
disagreed in BOTH directions at once.
"""
from __future__ import annotations

import pytest

from aughor.knowledge import health
from aughor.semantic import embedder


@pytest.fixture()
def plane(monkeypatch):
    """Compose a knowledge plane out of its three failure points."""
    def _set(*, embed_ok=True, store_ok=True, chunks=10, docs=2, points=None):
        if embed_ok:
            monkeypatch.setattr("aughor.semantic.embedder.embed_one", lambda _t: [0.0] * 768)
        else:
            def _boom(_t):
                raise ConnectionError("connection refused")
            monkeypatch.setattr("aughor.semantic.embedder.embed_one", _boom)
        monkeypatch.setattr("aughor.semantic.vector_store.backend", lambda: "qdrant")
        monkeypatch.setattr("aughor.semantic.vector_store.available", lambda: store_ok)
        monkeypatch.setattr("aughor.semantic.vector_store.collection_count",
                            lambda _c: chunks)
        # The width the store holds, matching this fixture's fake embedder. Without it
        # `embedder_status` reads a REAL Qdrant for the live collection's width and
        # compares it against the 768 above — so the fixture was hermetic only while the
        # real collection happened to be 768 too, and the day the corpus was re-embedded
        # at another width these tests failed on a laptop and stayed green in CI, which
        # runs no Qdrant at all. A test that passes for want of a server is not passing.
        monkeypatch.setattr("aughor.semantic.vector_store.collection_dim", lambda _c: 768)
        monkeypatch.setattr("aughor.semantic.vector_store.scroll_payloads",
                            lambda _c, limit=0: list(points or []))
        monkeypatch.setattr("aughor.knowledge.indexer.list_documents",
                            lambda: [{"doc_id": f"d{i}", "chunk_count": 1}
                                     for i in range(docs)])
    return _set


# ── the four causes, told apart ──────────────────────────────────────────────────

def test_a_healthy_plane_is_ready_and_explains_nothing(plane):
    """When the plane is fine, an empty result really does mean no match — and saying
    anything else would be noise on every clean search."""
    plane(points=[{"doc_id": "d0"}, {"doc_id": "d1"}])

    assert health.knowledge_status()["ready"] is True
    assert health.why_empty() == ""


def test_an_unreachable_embedder_is_named_as_such(plane):
    """The one a person cannot guess. Nothing about an empty list suggests 'start Ollama'."""
    plane(embed_ok=False)

    status = health.knowledge_status()

    assert status["ready"] is False
    assert status["reason"] == "the embedder is unreachable"
    assert "connection refused" in status["embedder"]["error"]
    # WHERE it tried, whatever that is — not a literal host. Asserting `localhost:11434`
    # made this pass only while `OLLAMA_BASE_URL` was unset, which is true on a laptop and
    # false anywhere the endpoint is configured. The property is that the report names the
    # endpoint it used, so a person can see it is the wrong one.
    assert status["embedder"]["endpoint"] == embedder.endpoint()[0]
    assert status["embedder"]["endpoint"], "an unnamed endpoint explains nothing"
    assert "UNAVAILABLE" in health.why_empty()


def test_a_width_mismatch_is_not_reported_as_an_outage(plane, monkeypatch):
    """Found by the first live run of the Gemini switch: the embedder answered perfectly —
    3072 dimensions — against an index holding 768, and this reported "the embedder is
    unreachable". That sends a person to check a service that is fine, and away from the
    re-embed that is actually needed."""
    plane()
    monkeypatch.setattr("aughor.semantic.vector_store.collection_dim", lambda _c: 768)
    monkeypatch.setattr("aughor.semantic.embedder.embed_one", lambda _t: [0.0] * 3072)

    status = health.knowledge_status()

    assert status["ready"] is False
    assert status["reason"] == "the embedder does not fit the index"
    assert status["embedder"]["stored_dim"] == 768 and status["embedder"]["dim"] == 3072
    assert "re-embedded" in status["embedder"]["why"]


def test_an_unavailable_store_is_distinct_from_an_unreachable_embedder(plane):
    plane(store_ok=False)

    assert health.knowledge_status()["reason"] == "the vector store is unavailable"


def test_an_empty_corpus_is_distinct_from_both(plane):
    plane(chunks=0, docs=0)

    status = health.knowledge_status()

    assert status["reason"] == "no documents are indexed"
    assert status["ready"] is False


def test_a_working_embedder_over_an_empty_corpus_is_not_ready(plane):
    """`ready` means a search can run AND has something to search. Healthy-and-useless
    reported as ready teaches its reader to distrust the word."""
    plane(chunks=0, docs=0)

    assert health.embedder_status()["ok"] is True
    assert health.knowledge_status()["ready"] is False


# ── registry ↔ store drift ───────────────────────────────────────────────────────

def test_chunks_in_the_store_that_no_document_lists_are_orphans(plane):
    """Searchable, undeletable, unbindable. `delete_document` works off the registry, and
    per-agent scoping filters `doc_id in allowed` — which a document nobody can list can
    never be. So an orphan answers questions while escaping every control."""
    plane(docs=1, points=[{"doc_id": "d0"}, {"doc_id": "ghost"}, {"doc_id": "ghost"}])

    drift = health.consistency_status()

    assert drift["ok"] is False
    assert drift["orphan_documents"] == 1 and drift["orphan_chunks"] == 2
    assert drift["orphans"] == ["ghost"]


def test_a_document_shorter_in_the_store_than_it_claims_is_reported(plane, monkeypatch):
    """The corpus looks complete and answers as if the missing part were irrelevant."""
    plane(docs=0, points=[])
    monkeypatch.setattr("aughor.knowledge.indexer.list_documents",
                        lambda: [{"doc_id": "big", "chunk_count": 59}])

    drift = health.consistency_status()

    assert drift["mismatched_documents"]["big"] == {"registry": 59, "store": 0}


def test_the_number_worth_quoting_is_what_is_listed_AND_present(plane):
    """Neither total is the truth on its own: the registry's sum is a claim, and the store's
    count includes chunks no one can list. What a person can search and control is the
    overlap."""
    plane(docs=2, points=[{"doc_id": "d0"}, {"doc_id": "ghost"}, {"doc_id": "ghost"}])

    assert health.consistency_status()["listed_chunks_present"] == 1


def test_a_scan_that_hit_its_bound_says_so(plane, monkeypatch):
    """A drift verdict computed over part of a corpus is a guess. Better to report the
    truncation than a clean bill of health for chunks nobody looked at."""
    monkeypatch.setattr(health, "_DRIFT_SCAN_LIMIT", 3)
    plane(docs=1, points=[{"doc_id": "d0"}] * 10)

    assert health.consistency_status()["truncated"] is True


# ── it reports, and never repairs ────────────────────────────────────────────────

def test_nothing_here_mutates_the_corpus(plane):
    """Deleting orphans and re-indexing a short document are both destructive acts on
    someone's corpus. The value of this module is that a person can SEE the choice."""
    import ast
    import inspect

    # CALLS, not mentions. This module's own docstrings name `delete_document` and
    # `index_file` while explaining that it does not call them, and a substring check reads
    # that as the offence — the same way the connector guard's `"self._conn" in source`
    # was satisfied by `self._connection_id`.
    tree = ast.parse(inspect.getsource(health))
    called = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
              for n in ast.walk(tree) if isinstance(n, ast.Call)}

    forbidden = {"delete_document", "index_file", "index_text", "reindex",
                 "_upsert_chunks", "upsert"}
    assert not (called & forbidden), (
        f"health checking must not mutate the corpus, but calls {sorted(called & forbidden)}")
    assert "list_documents" in called, (
        "the AST walk found no known call at all — the guard has gone blind")
