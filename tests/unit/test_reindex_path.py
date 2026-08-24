"""Re-embedding the corpus, and the two things it cannot do.

Needed the moment the embedding backend became a switch: a different model is a different
vector space, and a different WIDTH means the collection itself must be rebuilt, because
Qdrant fixes width at creation and `ensure_collection` no-ops on an existing one. Measured
live: `models/gemini-embedding-2` returns 3072 against a stored 768.

Two properties carry this file:

* **Nothing is destroyed before its replacement exists.** Read → embed EVERYTHING → drop →
  recreate → write. Embedding is the step that talks to a remote service and the step that
  fails; doing it first means a failure costs a run, not a corpus.
* **It recovers what the STORE holds and nothing more.** `index_file` unlinks the upload, so
  a chunk absent from the store has no source anywhere. A document claiming 59 chunks with 5
  present comes back with 5 — and the registry stops claiming 59.
"""
from __future__ import annotations

import pytest

from aughor.knowledge import reindex


@pytest.fixture()
def corpus(monkeypatch):
    """A store and a registry that can be made to disagree, and an embedder that can fail."""
    state = {"payloads": [], "dropped": 0, "ensured": None, "upserted": [], "registered": []}

    def _install(payloads, registry, *, embed_fails=False, dim=768):
        state["payloads"] = list(payloads)
        monkeypatch.setattr("aughor.semantic.vector_store.scroll_payloads",
                            lambda _c, limit=0: list(state["payloads"]))
        monkeypatch.setattr("aughor.semantic.vector_store.collection_dim", lambda _c: 768)
        monkeypatch.setattr("aughor.semantic.vector_store.drop_collection",
                            lambda _c: state.__setitem__("dropped", state["dropped"] + 1))
        monkeypatch.setattr("aughor.semantic.vector_store.ensure_collection",
                            lambda _c, dim=None: state.__setitem__("ensured", dim))
        # Capture only the documents this test set up. Something in the wider suite
        # re-indexes a doc tree from a thread that outlives the request that started it —
        # observed arriving as `doc::doctree::fixture::default::0`, into THIS collection,
        # in the middle of an unrelated test. A capture that took every point made that
        # write look like the code under test: first a KeyError on a payload shaped for
        # something else, then a stranger's point sitting at `upserted[0]`.
        from aughor.knowledge.indexer import DOCS_COLLECTION

        owned = ({str(p.get("doc_id") or "") for p in payloads}
                 | {str(d.get("doc_id") or "") for d in registry})

        def _upsert(coll, points):
            if coll != DOCS_COLLECTION:
                return
            state["upserted"].extend(
                p for p in points
                if str((p.get("payload") or {}).get("doc_id") or "") in owned)
        monkeypatch.setattr("aughor.semantic.vector_store.upsert", _upsert)
        monkeypatch.setattr("aughor.knowledge.indexer.list_documents", lambda: list(registry))
        # Mirrors the real contract: False when the count is ALREADY right, so nothing is
        # rewritten and nothing is counted as a correction. A stub that always returned True
        # made "left alone" indistinguishable from "corrected".
        known = {d["doc_id"]: int(d.get("chunk_count") or 0) for d in registry}

        def _correct(doc_id, n):
            state["registered"].append((doc_id, n))
            return known.get(doc_id) != n
        monkeypatch.setattr("aughor.knowledge.indexer.correct_chunk_count", _correct)
        monkeypatch.setattr("aughor.semantic.embedder.embedding_dim", lambda: dim)

        def _embed(texts):
            if embed_fails:
                raise ConnectionError("embedder is down")
            return [[0.0] * dim for _ in texts]
        monkeypatch.setattr("aughor.semantic.embedder.embed", _embed)
        monkeypatch.setattr("aughor.semantic.embedder.embed_backend", lambda: "gemini")
        monkeypatch.setattr("aughor.semantic.embedder.embed_model", lambda: "some-model")
        return state
    return _install


def _chunk(doc_id, index=0, text="body"):
    return {"doc_id": doc_id, "chunk_index": index, "text": text, "title": "T",
            "filename": "f.pdf", "uploaded_at": "2026-01-01T00:00:00Z"}


def _doc(doc_id, chunk_count):
    return {"doc_id": doc_id, "chunk_count": chunk_count, "filename": "f.pdf",
            "title": "T", "uploaded_at": "2026-01-01T00:00:00Z"}


# ── the plan does nothing ────────────────────────────────────────────────────────

def test_the_plan_touches_nothing(corpus):
    """The endpoint's default. Everything below it destroys something."""
    state = corpus([_chunk("a"), _chunk("ghost")], [_doc("a", 1)])

    out = reindex.plan()

    assert out["chunks_in_store"] == 2 and out["orphan_chunks"] == 1
    assert state["dropped"] == 0 and state["upserted"] == []


def test_the_plan_names_what_cannot_be_recovered(corpus):
    """The honest number. A document claiming 59 chunks with 5 present has 54 with no source
    anywhere — the upload was unlinked after indexing. Reporting only "will re-embed 5"
    invites the reader to think the other 54 come back."""
    corpus([_chunk("big", i) for i in range(5)], [_doc("big", 59)])

    out = reindex.plan()

    assert out["unrecoverable_chunks"] == 54
    assert out["registry_corrections"]["big"] == {"from": 59, "to": 5}


# ── the ordering that makes it safe ──────────────────────────────────────────────

def test_a_failed_embed_leaves_the_corpus_untouched(corpus):
    """The property the whole ordering exists for. Embedding talks to a remote service; if
    the drop came first, an outage would cost the corpus rather than the run."""
    state = corpus([_chunk("a"), _chunk("b")], [_doc("a", 1), _doc("b", 1)],
                   embed_fails=True)

    with pytest.raises(ConnectionError):
        reindex.run()

    assert state["dropped"] == 0, "the collection was dropped before the new vectors existed"
    assert state["upserted"] == [] and state["registered"] == []


def test_a_successful_run_rebuilds_at_the_new_width(corpus):
    state = corpus([_chunk("a"), _chunk("b")], [_doc("a", 1), _doc("b", 1)], dim=3072)

    out = reindex.run()

    assert state["dropped"] == 1
    assert state["ensured"] == 3072, "recreated at the ACTIVE width, not the old one"
    assert out["rebuilt"] == 2 and len(state["upserted"]) == 2


def test_a_rebuilt_point_keeps_its_identity_and_payload(corpus):
    """A re-embed must land a chunk where a fresh index would: same point id, same payload,
    or search results shift for reasons nobody asked for."""
    state = corpus([_chunk("a", 7, text="the body")], [_doc("a", 1)])

    reindex.run()

    point = state["upserted"][0]
    assert point["id"] == "doc::a::7"
    assert point["payload"]["text"] == "the body"


# ── reconciliation ───────────────────────────────────────────────────────────────

def test_the_registry_stops_claiming_chunks_that_are_not_there(corpus):
    state = corpus([_chunk("big", i) for i in range(5)], [_doc("big", 59)])

    out = reindex.run()

    assert out["registry_corrected"] == 1
    assert state["registered"][0] == ("big", 5), "corrected to the real count"


def test_a_correct_registry_is_left_alone(corpus):
    state = corpus([_chunk("a")], [_doc("a", 1)])

    assert reindex.run()["registry_corrected"] == 0
    assert state["registered"] == [("a", 1)], "asked, and told nothing needed changing"


# ── orphans: opt-in, because deleting someone's chunks is not a default ──────────

def test_orphans_survive_by_default(corpus):
    """KB-0 reported and did not repair, deliberately. A re-index that silently deleted
    chunks would make that decision for the operator on their behalf."""
    state = corpus([_chunk("a"), _chunk("ghost")], [_doc("a", 1)])

    out = reindex.run()

    assert out["rebuilt"] == 2 and out["orphans_purged"] == 0
    assert any(p["payload"]["doc_id"] == "ghost" for p in state["upserted"])


def test_orphans_are_dropped_when_asked(corpus):
    state = corpus([_chunk("a"), _chunk("ghost"), _chunk("ghost", 1)], [_doc("a", 1)])

    out = reindex.run(purge_orphans=True)

    assert out["rebuilt"] == 1 and out["orphans_purged"] == 2
    assert not any(p["payload"]["doc_id"] == "ghost" for p in state["upserted"])


# ── refusals ─────────────────────────────────────────────────────────────────────

def test_a_truncated_scan_refuses_to_rebuild(corpus, monkeypatch):
    """A rebuild from a partial read would delete every chunk it did not see."""
    monkeypatch.setattr(reindex, "_SCAN_LIMIT", 2)
    state = corpus([_chunk("a", i) for i in range(2)], [_doc("a", 2)])

    with pytest.raises(RuntimeError, match="partial read"):
        reindex.run()

    assert state["dropped"] == 0


def test_an_empty_store_is_a_no_op_not_a_wipe(corpus):
    state = corpus([], [_doc("a", 1)])

    out = reindex.run()

    assert out["rebuilt"] == 0 and state["dropped"] == 0
