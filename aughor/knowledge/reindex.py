"""Re-embed the corpus with the active model, and reconcile the registry with the store.

Needed the moment the embedding backend became a switch: a different model is a different
vector space, and a different WIDTH means the collection itself has to be rebuilt, because
Qdrant fixes the width at creation and `ensure_collection` no-ops on an existing one.
Measured live: a hosted embedding model returned 3072 against a stored 768. The id is
not written here — the package names no hosted model, and the guard that enforces that
covers prose too, because prose is where a convenient default starts.

🔑 **The source of truth is the STORE, not the original files.** `index_file` writes an
upload to a temp file and unlinks it, so the only surviving copy of a document's text is the
`text` payload on each of its chunks. That has a consequence worth stating plainly rather
than discovering: **re-indexing recovers what the store still holds and nothing more.** A
document the registry says has 59 chunks where 5 are present comes back with 5 — the other
54 have no source anywhere. What re-indexing CAN do for that document is stop the registry
claiming otherwise.

**Nothing is destroyed until its replacement exists.** Read every payload, embed every text,
and only then drop and rebuild. The embedding step is the one that talks to a remote service
and the one that can fail; doing it first means a failure costs a run rather than a corpus.
"""
from __future__ import annotations

from typing import Optional

from aughor.knowledge.indexer import DOCS_COLLECTION

#: Payloads read in one pass. Above this the plan reports `truncated` and refuses to run,
#: because a rebuild from a partial read would silently delete whatever it did not see.
_SCAN_LIMIT = 50_000

#: Vectors embedded per request, matching the indexer's own batching.
_BATCH = 32


def plan(*, purge_orphans: bool = False) -> dict:
    """What a re-index would do, without doing any of it.

    Cheap and side-effect free: it reads payloads and the registry, and does not embed. The
    default for the endpoint, because everything below this is destructive.
    """
    from aughor.knowledge.indexer import list_documents
    from aughor.semantic import vector_store

    try:
        registry = {d["doc_id"]: int(d.get("chunk_count") or 0) for d in list_documents()}
    except Exception as exc:
        return {"ok": False, "error": f"registry unreadable: {type(exc).__name__}"}

    payloads = vector_store.scroll_payloads(DOCS_COLLECTION, limit=_SCAN_LIMIT)
    truncated = len(payloads) >= _SCAN_LIMIT

    by_doc: dict[str, int] = {}
    for payload in payloads:
        by_doc[str(payload.get("doc_id") or "")] = by_doc.get(
            str(payload.get("doc_id") or ""), 0) + 1
    orphans = {doc: n for doc, n in by_doc.items() if doc not in registry}
    keep = len(payloads) - (sum(orphans.values()) if purge_orphans else 0)

    from aughor.semantic.embedder import embed_backend, embed_model
    return {
        "ok": not truncated,
        "truncated": truncated,
        "chunks_in_store": len(payloads),
        "chunks_to_re_embed": keep,
        "orphan_documents": sorted(orphans),
        "orphan_chunks": sum(orphans.values()),
        "purge_orphans": purge_orphans,
        # What the registry will be corrected TO, per document that currently disagrees.
        "registry_corrections": {doc: {"from": n, "to": by_doc.get(doc, 0)}
                                 for doc, n in registry.items() if by_doc.get(doc, 0) != n},
        # Said out loud, because it is the one thing a re-index cannot do.
        "unrecoverable_chunks": sum(max(0, n - by_doc.get(doc, 0))
                                    for doc, n in registry.items()),
        "backend": embed_backend(),
        "model": embed_model(),
        "current_width": vector_store.collection_dim(DOCS_COLLECTION),
    }


def run(*, purge_orphans: bool = False, progress: Optional[callable] = None) -> dict:
    """Re-embed and rebuild. Destructive; call `plan()` first.

    Order is the safety property: read → embed EVERYTHING → drop → recreate → write. A
    failure anywhere before the drop leaves the corpus exactly as it was.
    """
    from aughor.knowledge.indexer import correct_chunk_count, list_documents
    from aughor.semantic import vector_store
    from aughor.semantic.embedder import embed, embedding_dim

    before = plan(purge_orphans=purge_orphans)
    if before.get("truncated"):
        raise RuntimeError(
            f"the corpus exceeds this pass's scan limit ({_SCAN_LIMIT}); rebuilding from a "
            f"partial read would delete every chunk it did not see")
    if not before.get("chunks_in_store"):
        return {**before, "rebuilt": 0, "note": "nothing in the store to re-embed"}

    payloads = vector_store.scroll_payloads(DOCS_COLLECTION, limit=_SCAN_LIMIT)
    registry = {d["doc_id"] for d in list_documents()}
    if purge_orphans:
        payloads = [p for p in payloads if str(p.get("doc_id") or "") in registry]

    # ── embed FIRST. This is the step that can fail, and it must fail before the drop ──
    points: list[dict] = []
    for i in range(0, len(payloads), _BATCH):
        batch = payloads[i: i + _BATCH]
        # The same text the indexer embeds: title and body, so a re-embed lands a document
        # in the same place a fresh index would.
        vectors = embed([f"{p.get('title', '')}\n\n{p.get('text', '')}" for p in batch])
        points.extend({"id": f"doc::{p.get('doc_id')}::{p.get('chunk_index', 0)}",
                       "vector": v, "payload": p}
                      for p, v in zip(batch, vectors))
        if progress:
            progress(len(points), len(payloads))

    # ── only now is anything destroyed ────────────────────────────────────────────────
    vector_store.drop_collection(DOCS_COLLECTION)
    vector_store.ensure_collection(DOCS_COLLECTION, dim=embedding_dim())
    for i in range(0, len(points), _BATCH):
        vector_store.upsert(DOCS_COLLECTION, points[i: i + _BATCH])

    # ── the registry stops claiming chunks that are not there ─────────────────────────
    written: dict[str, int] = {}
    for point in points:
        doc = str(point["payload"].get("doc_id") or "")
        written[doc] = written.get(doc, 0) + 1
    corrected = sum(correct_chunk_count(entry["doc_id"], written.get(entry["doc_id"], 0))
                    for entry in list_documents())

    return {**before, "rebuilt": len(points), "width": embedding_dim(),
            "registry_corrected": corrected,
            "orphans_purged": before["orphan_chunks"] if purge_orphans else 0}
