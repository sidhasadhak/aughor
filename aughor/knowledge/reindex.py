"""Re-embed the corpus with the active model, and reconcile the registry with the store.

Needed the moment the embedding backend became a switch: a different model is a different
vector space, and a different WIDTH means the collection itself has to be rebuilt, because
Qdrant fixes the width at creation and `ensure_collection` no-ops on an existing one.
Measured live: a hosted embedding model returned 3072 against a stored 768. The id is
not written here — the package names no hosted model, and the guard that enforces that
covers prose too, because prose is where a convenient default starts.

🔑 **For an UPLOAD, the source of truth is the STORE.** `index_file` writes an upload to a
temp file and unlinks it, so the only surviving copy of its text is the `text` payload on
each chunk, and **re-indexing recovers what the store still holds and nothing more.**

🔑 **For a SCHEMA DOC it is not.** `build_and_persist` leaves a doc tree on disk, one YAML
per node, and that artifact outlives whatever happened to the collection — measured here as
a store holding 5 chunks for a document whose artifact held 59. Counting those 54 as
unrecoverable was a claim about uploads applied to something that is not one, and it read
as "gone forever" while the source sat in `data/ontology_docs`. `plan()` now separates the
two, and `doctree_restore()` puts the recoverable half back.

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

    # What a persisted doc tree could put back. Fail-safe in the honest direction: if the
    # artifacts cannot be read, claim no recovery rather than a recovery nobody can perform.
    try:
        restorable, _ = _tree_chunk_counts()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "doc-tree artifacts unreadable; reporting no recoverable chunks",
                 counter="doctree.plan_scan")
        restorable = {}

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
        # Said out loud, because it is the one thing a re-index cannot do — but only for
        # the documents where it is TRUE. A schema doc keeps its source in the doc-tree
        # artifact, so counting it here read as "gone forever" while it sat on disk. What
        # an artifact can supply is reported separately, and `doctree_restore` supplies it.
        "unrecoverable_chunks": sum(max(0, n - by_doc.get(doc, 0) - restorable.get(doc, 0))
                                    for doc, n in registry.items()),
        "restorable_from_doctrees": sum(
            max(0, n - by_doc.get(doc, 0)) for doc, n in restorable.items()),
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


# ── restoring from the doc-tree artifact ──────────────────────────────────────────────
#
# `unrecoverable_chunks` above is true for UPLOADS and false for schema docs, and the
# difference is worth stating because the two look identical in the store. `index_file`
# unlinks its upload, so a chunk absent from the store has no source. A schema doc's
# source is a persisted artifact: `build_and_persist` writes one YAML per node under the
# doc-tree root and the tree survives whatever happened to the collection. Measured on the
# machine this was written on: the store held 5 chunks for a connection whose artifact held
# 59 table docs, every one of them embeddable.
#
# Restoring is deliberately its OWN call rather than a flag on `run()`. `run()` re-embeds
# what the store holds and rebuilds the collection around it; this ADDS chunks the store
# never had, touching only the documents it names. Folding them together would give one
# endpoint two safety stories.


def _live_connection_ids() -> set[str]:
    from aughor.db.registry import list_connections
    return {str(c.get("id") or "") for c in list_connections()}


def _tree_chunk_counts(connection_id: Optional[str] = None) -> tuple[dict, list[dict]]:
    """`(doc_id → chunks the artifact would produce, skipped trees with a reason)`.

    Scoped to connections that still exist. An artifact outliving its connection is not
    hypothetical — a purge removes a deleted connection's documents, and a restore that
    ignored the registry would put them straight back, which is the same defect wearing a
    repair's clothes.
    """
    from aughor.knowledge.indexer import doctree_chunks, doctree_doc_id
    from aughor.ontology.doctree import list_persisted_trees, load_doc_tree

    live = _live_connection_ids()
    counts: dict[str, int] = {}
    skipped: list[dict] = []
    for conn, schema in list_persisted_trees():
        if connection_id and conn != connection_id:
            continue
        if conn not in live:
            skipped.append({"doc_id": doctree_doc_id(conn, schema), "connection_id": conn,
                            "reason": "no such connection — restoring it would resurrect a "
                                      "document a purge removed"})
            continue
        tree = load_doc_tree(conn, schema)
        if tree is None:
            skipped.append({"doc_id": doctree_doc_id(conn, schema), "connection_id": conn,
                            "reason": "the artifact is present but unreadable"})
            continue
        counts[doctree_doc_id(conn, schema)] = len(
            doctree_chunks(tree, connection_id=conn, schema=schema))
    return counts, skipped


def _store_counts_by_doc() -> dict[str, int]:
    from aughor.semantic import vector_store
    by_doc: dict[str, int] = {}
    for payload in vector_store.scroll_payloads(DOCS_COLLECTION, limit=_SCAN_LIMIT):
        doc = str(payload.get("doc_id") or "")
        by_doc[doc] = by_doc.get(doc, 0) + 1
    return by_doc


def doctree_plan(*, connection_id: Optional[str] = None) -> dict:
    """What restoring the persisted doc trees would add, without embedding anything.

    Reports per document rather than a total alone: a restore that adds 54 chunks to one
    document and 0 to nine others is a different decision from one that touches all ten.
    """
    counts, skipped = _tree_chunk_counts(connection_id)
    in_store = _store_counts_by_doc()
    documents = [{"doc_id": doc, "in_store": in_store.get(doc, 0), "in_artifact": n,
                  "adds": max(0, n - in_store.get(doc, 0))}
                 for doc, n in sorted(counts.items())]
    return {
        "documents": documents,
        "restorable_chunks": sum(d["adds"] for d in documents),
        "skipped": skipped,
    }


def doctree_restore(*, connection_id: Optional[str] = None) -> dict:
    """Re-embed every persisted doc tree back into the store, replacing what it holds.

    Each document is independent — `index_doc_tree` deletes and rewrites one doc_id — so a
    failure part-way leaves the documents already done correct and the rest untouched. The
    ones that failed are named in the result rather than folded into a count, because a
    restore that silently half-ran is the state this whole path exists to end.
    """
    from aughor.knowledge.indexer import doctree_doc_id, index_doc_tree
    from aughor.ontology.doctree import list_persisted_trees, load_doc_tree

    before = doctree_plan(connection_id=connection_id)
    planned = {d["doc_id"] for d in before["documents"]}

    restored: list[dict] = []
    failed: list[dict] = []
    for conn, schema in list_persisted_trees():
        doc_id = doctree_doc_id(conn, schema)
        if doc_id not in planned:
            continue
        tree = load_doc_tree(conn, schema)
        if tree is None:
            continue
        try:
            restored.append(index_doc_tree(tree, connection_id=conn, schema=schema))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"doc-tree restore failed for {doc_id}", counter="doctree.restore")
            failed.append({"doc_id": doc_id, "error": f"{type(exc).__name__}: {exc}"})

    return {**before, "restored": restored, "failed": failed,
            "chunks_written": sum(r.get("chunk_count", 0) for r in restored),
            "ok": not failed}
