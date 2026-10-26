"""
Document indexer — embeds DocumentChunks into the `aughor_documents` Qdrant collection.
Also holds the document metadata registry (data/documents.json).
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

from aughor.knowledge.documents import DocumentChunk, chunk_file

DOCS_COLLECTION = "aughor_documents"
_REGISTRY_PATH = Path(__file__).parent.parent.parent / "data" / "documents.json"


# ── Registry (metadata store) ─────────────────────────────────────────────────

def _registry_path() -> Path:
    """Registry file; ``AUGHOR_DOCUMENTS_REGISTRY`` overrides (test hermeticity —
    the suite must never mutate the live data/documents.json)."""
    from aughor.db.home import rehome          # IN-4: the data home, once migrated
    return Path(os.environ.get("AUGHOR_DOCUMENTS_REGISTRY") or rehome(_REGISTRY_PATH))


def _load_registry() -> list[dict]:
    path = _registry_path()
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_registry(docs: list[dict]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(docs, f, indent=2)


def list_documents() -> list[dict]:
    return _load_registry()


def get_document(doc_id: str) -> Optional[dict]:
    return next((d for d in _load_registry() if d["doc_id"] == doc_id), None)


def _register(doc_id: str, filename: str, title: str, chunk_count: int, uploaded_at: str,
              settings: Optional[dict] = None) -> None:
    docs = _load_registry()
    previous = next((d for d in docs if d["doc_id"] == doc_id), None)
    # Remove any existing entry for this doc_id
    docs = [d for d in docs if d["doc_id"] != doc_id]
    docs.append({
        "doc_id": doc_id,
        "filename": filename,
        "title": title,
        "chunk_count": chunk_count,
        "uploaded_at": uploaded_at,
        # KB-1 — WHAT CUT IT. Without this a re-index is a guess: the defaults may have
        # moved, or the document may have been indexed with settings a person chose once
        # and cannot now recall. Absent on every document indexed before this existed,
        # which `ChunkSettings.from_dict(None)` reads as "the defaults", because it was.
        **({"chunk_settings": settings} if settings else {}),
        # Whose it is. A re-index (a connector re-sync, a restore) never changes the owner a
        # document was first stamped with — only the connection's own org decides a doc tree.
        **_ownership(doc_id, previous),
    })
    _save_registry(docs)


def _ownership(doc_id: str, previous: Optional[dict] = None) -> dict:
    """The registry fields that say whose a document is, stamped when it is indexed.

    PENDING item 16: the store had no owner on any row, so retrieval handed a question on one
    connection another connection's schema docs, and with sign-in on another organisation's
    uploads. A generated schema doc belongs to its connection and, through it, to that
    connection's organisation — ``""`` for a shared builtin, which every organisation reads.
    Anything else belongs to the organisation that indexed it, and keeps it."""
    conn = doctree_connection(doc_id)
    if conn is not None:
        return {"connection_id": conn, "org_id": _connection_org(conn)}
    if previous and "org_id" in previous:
        return {"org_id": previous["org_id"]}
    from aughor.org.context import current_org_id
    return {"org_id": current_org_id()}


def _connection_org(connection_id: str) -> str:
    """The organisation that owns a connection, ``""`` for a shared builtin. An unreadable
    registry raises: guessing an owner would decide who may read the document."""
    from aughor.db.registry import get_connection_org
    return get_connection_org(connection_id) or ""


def entry_org(entry: dict) -> Optional[str]:
    """The organisation a registry row belongs to, or ``None`` when every organisation may
    read it (a shared builtin connection's schema docs).

    A row indexed before owners were stamped carries none: a schema doc resolves through its
    connection as a new one would, and an upload belongs to the default organisation — the
    only one that existed when it was made."""
    if "org_id" in entry:
        return entry["org_id"] or None
    conn = doctree_connection(entry.get("doc_id", ""))
    if conn is not None:
        return _connection_org(conn) or None
    from aughor.org.context import DEFAULT_ORG_ID
    return DEFAULT_ORG_ID


def document_org(doc_id: str) -> Optional[str]:
    """The organisation that owns a registered document (``entry_org``), or ``None`` for an
    unregistered id — the ownership guard then lets the door answer its own 404."""
    entry = get_document(doc_id)
    return entry_org(entry) if entry else None


def in_scope(entry: dict, *, connection_id: Optional[str] = None,
             org_id: Optional[str] = None) -> bool:
    """May a question on ``connection_id``, asked inside ``org_id``, read this document?

    Another connection's schema docs describe tables this connection does not have, so they
    are never in scope for it. ``org_id`` is ``None`` with sign-in off (one tenant owns every
    row); otherwise a document is readable by its own organisation, or by everyone when it
    belongs to none."""
    doc_id = entry.get("doc_id", "")
    if connection_id and doctree_connection(doc_id) not in (None, connection_id):
        return False
    if org_id is not None and entry_org(entry) not in (None, org_id):
        return False
    return True


def correct_chunk_count(doc_id: str, chunk_count: int) -> bool:
    """Set a document's recorded chunk count to what the store actually holds.

    Narrow on purpose. Re-indexing needs to stop the registry claiming chunks that are not
    there, and it needs nothing else from the registry writer — so this exposes that one
    correction rather than `_register`, which takes six arguments and can invent a document.
    Returns False for an id the registry does not list.
    """
    docs = _load_registry()
    for entry in docs:
        if entry["doc_id"] == doc_id:
            if int(entry.get("chunk_count") or 0) == chunk_count:
                return False                      # already right; do not rewrite the file
            entry["chunk_count"] = chunk_count
            _save_registry(docs)
            return True
    return False


def _deregister(doc_id: str) -> bool:
    docs = _load_registry()
    filtered = [d for d in docs if d["doc_id"] != doc_id]
    if len(filtered) == len(docs):
        return False
    _save_registry(filtered)
    return True


# ── Qdrant helpers ────────────────────────────────────────────────────────────

class EmbeddingDimensionMismatch(RuntimeError):
    """The configured embedder does not fit the collection that already exists."""


class DocumentSearchUnavailable(RuntimeError):
    """The documents could not be searched: the embedder, the store or the registry failed.

    Raised where `search_documents` used to answer `[]`. An empty list says "nothing matched",
    and that is the one thing a failed search does not know (withheld is said, never implied).
    """


def _ensure_collection() -> None:
    """Create the collection at the ACTIVE embedder's width, or refuse if one exists at a
    different one.

    `ensure_collection` no-ops on an existing collection whatever its width, so without this
    a changed embedding model fails at upsert with a driver error and — far worse — at
    search, where the failure is swallowed into an empty result. Switching model always
    requires re-embedding anyway (a different model is a different vector space, even at an
    identical width); this makes the moment it becomes necessary loud instead of silent.
    """
    from aughor.semantic.embedder import embedding_dim
    from aughor.semantic.vector_store import collection_dim, ensure_collection

    dim = embedding_dim()
    existing = collection_dim(DOCS_COLLECTION)
    if existing is not None and existing != dim:
        from aughor.semantic.embedder import embed_backend, embed_model
        raise EmbeddingDimensionMismatch(
            f"the document index holds {existing}-dimension vectors and "
            f"{embed_backend()}/{embed_model()} produces {dim}. Nothing was written. The "
            f"corpus must be re-embedded with one model: delete the '{DOCS_COLLECTION}' "
            f"collection and re-index, or switch the embedder back.")
    ensure_collection(DOCS_COLLECTION, dim=dim)


def _delete_doc_chunks(doc_id: str) -> None:
    """Delete all vector points belonging to a document.

    Through the seam (`delete_by_filter`), not a bespoke QdrantClient: the old
    hand-built client read AUGHOR_QDRANT_URL itself, so on a pgvector or embedded
    deployment it deleted from a server that held nothing while the real index kept
    the chunks it claimed to drop."""
    try:
        from aughor.semantic.vector_store import delete_by_filter, match_filter
        delete_by_filter(DOCS_COLLECTION, match_filter("doc_id", doc_id))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "vector chunk deletion is best-effort; registry deregister still proceeds and stale vectors are harmless", counter="indexer.delete_chunks")


# ── Public API ────────────────────────────────────────────────────────────────

def index_text(
    text: str,
    title: str,
    source: str = "",
    doc_id: Optional[str] = None,
    source_url: str = "",
    settings=None,
) -> dict:
    """
    Chunk plain text, embed, and upsert into Qdrant — no file I/O required.
    Returns the registry entry dict.

    Used by Confluence/Notion/API knowledge connectors.
    """
    import datetime
    from aughor.knowledge.documents import chunk_text as _chunk_text

    doc_id = doc_id or uuid.uuid4().hex
    uploaded_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    filename = source or "api_sync"

    chunks = _chunk_text(
        text=text,
        doc_id=doc_id,
        title=title,
        filename=filename,
        uploaded_at=uploaded_at,
        source_url=source_url,
        settings=settings,
    )
    if not chunks:
        # The floor that cut it rides along, so a caller can say why without importing it.
        from aughor.knowledge.documents import DEFAULT_CHUNK_SETTINGS
        return {"doc_id": doc_id, "chunk_count": 0,
                "min_chars": (settings or DEFAULT_CHUNK_SETTINGS).min_chars}

    _ensure_collection()
    _upsert_chunks(chunks)
    _register(doc_id, filename, title, len(chunks), uploaded_at,
              settings=settings.as_dict() if settings else None)
    return {
        "doc_id": doc_id,
        "title": title,
        "source": source,
        "source_url": source_url,
        "chunk_count": len(chunks),
        "uploaded_at": uploaded_at,
    }


def index_file(path: Path, title: Optional[str] = None, settings=None) -> dict:
    """
    Parse, chunk, embed, and upsert a document file.
    Returns the registry entry dict.
    """
    import datetime
    doc_id = uuid.uuid4().hex
    uploaded_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    title = title or path.stem.replace("_", " ").replace("-", " ").title()

    chunks = chunk_file(path, doc_id=doc_id, title=title, uploaded_at=uploaded_at,
                        settings=settings)
    if not chunks:
        raise ValueError(f"No text could be extracted from {path.name}")

    _ensure_collection()
    _upsert_chunks(chunks)
    _register(doc_id, path.name, title, len(chunks), uploaded_at,
              settings=settings.as_dict() if settings else None)

    return {
        "doc_id": doc_id,
        "filename": path.name,
        "title": title,
        "chunk_count": len(chunks),
        "uploaded_at": uploaded_at,
    }


def delete_chunks(doc_id: str) -> None:
    """Drop one document's vectors, leaving the registry alone.

    The public half of `_delete_doc_chunks`, for the orphan purge: an orphan has no
    registry row to deregister, so `delete_document` would do half its job and report
    False for it. Named rather than reached into — a cross-module private import is a
    coupling the ratchet in `test_kernel_contracts` exists to keep from spreading.
    """
    _delete_doc_chunks(doc_id)


def delete_document(doc_id: str) -> bool:
    """Delete a document from both the registry and Qdrant."""
    _delete_doc_chunks(doc_id)
    return _deregister(doc_id)


#: Prefix of every doc_id the ontology GENERATES. One definition, used by the id
#: builder below and by `is_generated` — the surface that hides these from a person's
#: own uploads must not carry its own copy of the rule.
DOCTREE_PREFIX = "doctree::"


def doctree_doc_id(connection_id: str, schema: str = "") -> str:
    """The deterministic doc_id for one (connection, schema) doc tree."""
    return f"{DOCTREE_PREFIX}{connection_id}::{schema or 'default'}"


def doctree_connection(doc_id: str) -> Optional[str]:
    """The connection a generated doc tree documents — ``doctree_doc_id`` read backwards — or
    ``None`` for a document a person or a connector put there."""
    if not is_generated(doc_id):
        return None
    return doc_id[len(DOCTREE_PREFIX):].rsplit("::", 1)[0]


def purge_connection_doctrees(connection_id: str) -> int:
    """Delete every generated schema document of one connection — registry row AND vectors.
    A deleted connection's `Schema documentation — <id>/<schema>` stayed registered and
    searchable (measured 2026-10-04: both connections deleted in September). Returns count."""
    gone = 0
    for entry in list_documents():
        doc_id = str(entry.get("doc_id") or "")
        if doctree_connection(doc_id) == connection_id:
            gone += 1 if delete_document(doc_id) else 0
    return gone


def is_generated(doc_id: str) -> bool:
    """Was this document COMPILED by the platform rather than uploaded by a person?

    Schema documentation is embedded into the same collection as uploads, which is
    right for retrieval — an agent asking about a table wants the schema doc — and
    wrong for the Documents surface, where it made a corpus of one real file look like
    sixteen. Measured on a live install: 15 of 16 rows were `doctree::` and 102 of 148
    chunks, so a person's own document was outnumbered ten to one by artifacts they
    never created and cannot act on.
    """
    return (doc_id or "").startswith(DOCTREE_PREFIX)


def doctree_chunks(tree, *, connection_id: str, schema: str = "") -> list[DocumentChunk]:
    """The chunks a doc tree embeds to — one per TABLE node, in the order it indexes them.

    Factored out of :func:`index_doc_tree` so a caller can ask what indexing WOULD produce
    without producing it. A second copy of this rule would drift from the copy that writes,
    and the number it reports is the one a person decides a restore on.
    """
    import datetime

    schema_label = schema or "default"
    doc_id = doctree_doc_id(connection_id, schema_label)
    uploaded_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    filename = f"schema-docs/{connection_id}/{schema_label}"

    chunks: list[DocumentChunk] = []
    for i, node in enumerate(tree.tables()):
        # best_summary (R8b): the LLM-polished prose when current, else deterministic.
        parts = [node.best_summary() if hasattr(node, "best_summary") else node.summary]
        parts += [tree.nodes[c].summary for c in node.children if c in tree.nodes]
        if node.questions:
            parts.append("Questions this table can answer: " + " · ".join(node.questions))
        text = "\n".join(p for p in parts if p)[:6_000]
        if len(text.strip()) < 50:
            continue
        chunks.append(DocumentChunk(
            doc_id=doc_id, chunk_index=i, text=text,
            filename=filename, title=node.title, uploaded_at=uploaded_at,
            fqn=node.fqn, kind="schema_doc",
        ))
    return chunks


def index_doc_tree(tree, *, connection_id: str, schema: str = "") -> dict:
    """R8a — embed the ontology doc tree into the knowledge store with FQN provenance.

    The R8 doc tree compiles understanding into YAML; this is its retrieval
    consumer: one chunk per TABLE node (the table summary + its column summaries
    + the analyst questions — the embed-worthy prose), stamped ``fqn`` /
    ``kind="schema_doc"`` so a retrieved chunk cites the exact ontology node it
    came from. The doc_id is deterministic per (connection, schema), so a rebuild
    REPLACES the previous embedding instead of accumulating stale chunks.

    Raises on a dead embedder/Qdrant like ``index_text`` — the autodoc hook
    wraps it best-effort (no infra → the YAML artifact alone, exactly as before).
    """
    schema_label = schema or "default"
    doc_id = doctree_doc_id(connection_id, schema_label)
    chunks = doctree_chunks(tree, connection_id=connection_id, schema=schema)
    if not chunks:
        return {"doc_id": doc_id, "chunk_count": 0}

    _ensure_collection()
    # Replace, don't accumulate: a shrunk schema must not leave orphan chunks.
    _delete_doc_chunks(doc_id)
    _upsert_chunks(chunks)
    _register(doc_id, chunks[0].filename,
              f"Schema documentation — {connection_id}/{schema_label}",
              len(chunks), chunks[0].uploaded_at)
    return {"doc_id": doc_id, "chunk_count": len(chunks)}


def search_documents(query: str, top_k: int = 4, *,
                     connection_id: Optional[str] = None) -> list[dict]:
    """
    Semantic search over indexed documents.
    Returns list of {text, filename, title, doc_id, score} sorted by relevance.

    Only what the question may read (PENDING item 16): a document still in the registry — a
    deleted one's vectors can outlive it, since deleting them is best-effort, and the registry
    row is what deleting it removed — never another connection's schema docs when
    ``connection_id`` is given, and with sign-in on only the caller's organisation's documents.
    Over-fetches so the filters cannot shrink the answer below ``top_k``.

    Raises `DocumentSearchUnavailable` when the search itself fails; `[]` means the indexed
    documents were searched and nothing matched, or that none are indexed.

    Arc FA, FA-1 (flag ``knowledge.hybrid_documents``): when the question cannot be embedded and
    the store answers, the same scoped passages are ranked by their words instead
    (`_search_by_words`), each hit marked ``matched_by: "words"`` with the sentence a reader is told
    (``said``) — and a hit the embedder matched is marked ``"meaning"``. Off, hits carry neither
    key and a failed embed raises, as before.
    """
    try:
        hybrid = _hybrid_documents()
        from aughor.security.authz import tenant_scope
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.vector_store import search
        registry = {d["doc_id"]: d for d in _load_registry()}
        if not registry:
            # Nothing indexed. Asked of the registry, not `collection_count`, which answers 0
            # for a store that is down as well as for an empty one.
            return []
        try:
            vector = embed_one(query)
        except Exception as embed_exc:
            if not hybrid:
                raise
            return _search_by_words(query, top_k, registry, connection_id=connection_id,
                                    org_id=tenant_scope(), cause=embed_exc)
        hits = search(DOCS_COLLECTION, vector, top_k=max(top_k * 4, 16))
        org_id = tenant_scope()
        results = []
        for h in hits:
            p = h["payload"]
            entry = registry.get(p.get("doc_id", ""))
            if entry is None or not in_scope(entry, connection_id=connection_id, org_id=org_id):
                continue
            if len(results) >= top_k:
                break
            results.append({**_hit(p, h["score"]), **({"matched_by": "meaning"} if hybrid else {})})
        return results
    except DocumentSearchUnavailable:
        raise
    except Exception as exc:
        raise DocumentSearchUnavailable(f"{type(exc).__name__}: {_first_line(exc)}") from exc


def _first_line(exc: BaseException) -> str:
    return (str(exc).splitlines() or [""])[0][:200]


def _hit(payload: dict, score: float) -> dict:
    """One passage as a search hands it back."""
    return {
        "text": payload.get("text", ""),
        "filename": payload.get("filename", ""),
        "title": payload.get("title", ""),
        "doc_id": payload.get("doc_id", ""),
        "chunk_index": payload.get("chunk_index", 0),
        "fqn": payload.get("fqn", ""),           # R8a — ontology-node provenance
        "source_url": payload.get("source_url", ""),
        "score": score,
    }


#: Arc FA, FA-1 — what every caller tells a reader of passages matched by their words alone: they share the question's
#: words, which is not the same as answering it.
MATCHED_BY_WORDS = "matched by words only — the embedder is unavailable"
#: The most passages a search by words reads; one that reads this many says so (`passages_read` on each hit).
WORDS_POOL = 20_000


def _hybrid_documents() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled("knowledge.hybrid_documents")


def matched_by_words(hits: list[dict]) -> str:
    """The sentence a caller says of a search the words answered, or "" when the embedder matched its hits."""
    return next((str(h.get("said") or MATCHED_BY_WORDS) for h in hits or [] if h.get("matched_by") == "words"), "")


def _search_by_words(query: str, top_k: int, registry: dict, *, connection_id: Optional[str],
                     org_id: Optional[str], cause: BaseException) -> list[dict]:
    """Arc FA, FA-1 — the indexed passages ranked by the words they share with the question (BM25 over the scoped
    corpus), when the embedder failed. Scoped exactly as the vector path is — a passage counts only while its document
    is in the registry and in scope (`in_scope`) — and a passage that shares no word is not a match. Raises
    `DocumentSearchUnavailable` naming both failures when the store cannot be read either."""
    from aughor.semantic.lexical import bm25_scores
    from aughor.semantic.vector_store import scroll_points
    try:
        points = scroll_points(DOCS_COLLECTION, limit=WORDS_POOL, strict=True)
    except Exception as exc:
        raise DocumentSearchUnavailable(
            f"the embedder failed ({type(cause).__name__}: {_first_line(cause)}) and the document store could not be "
            f"read ({type(exc).__name__}: {_first_line(exc)})") from exc
    pool = []
    for point in points:
        p = point.get("payload") or {}
        entry = registry.get(p.get("doc_id", ""))
        if entry is not None and in_scope(entry, connection_id=connection_id, org_id=org_id):
            pool.append(p)
    scores = bm25_scores(query, [f"{p.get('title', '')} {p.get('text', '')}" for p in pool])
    ranked = sorted((i for i in range(len(pool)) if scores[i] > 0), key=lambda i: -scores[i])[:top_k]
    read = {"passages_read": len(points)} if len(points) >= WORDS_POOL else {}
    said = MATCHED_BY_WORDS + (f" (the first {len(points):,} passages were read)" if read else "")
    return [{**_hit(pool[i], round(scores[i], 4)), "matched_by": "words", "said": said, **read} for i in ranked]


#: What a prompt reads when the documents could not be searched, in place of nothing: an
#: absent section would let the model conclude the documents are silent on the question.
DOCUMENTS_UNAVAILABLE_SECTION = (
    "UPLOADED DOCUMENTS: could not be searched for this question (the document index did not "
    "answer). Do not treat the documents as silent on this subject.")


def build_external_context_section(query: str, top_k: int = 4,
                                   canvas_id: Optional[str] = None,
                                   connection_id: Optional[str] = None) -> str:
    """
    Retrieve relevant document snippets and format them for prompt injection.
    Returns empty string when no documents are indexed or none match, and
    `DOCUMENTS_UNAVAILABLE_SECTION` when the search failed.
    ``connection_id`` keeps another connection's schema docs out (`search_documents`).

    Two scopes act here, and they are deliberately not the same shape.

    An AGENT's documents RESTRICT. When a user-defined agent is active, retrieval is
    scoped to its bound documents: search wider, keep only its doc_ids. An agent with
    no bound documents sees none — fail-closed, because its context is what its
    creator gave it.

    A CANVAS's documents PIN. A canvas is a place a person works, so a document bound
    there is context for everything done in it; binding one ADDS to what is in reach
    rather than taking the rest of the corpus away. Pinned documents are searched
    SEPARATELY against the same query and placed first, which is what makes "pinned"
    survive contact with a large corpus: a workspace document that a global search
    would rank twentieth still arrives, but only its passages that bear on the
    question do, so a 200-chunk report cannot flood the prompt.

    Where both apply the agent still fences: a canvas cannot widen an agent past what
    it was given, because that is the direction that turns a restriction into a
    suggestion.
    """
    from aughor.custom_agents.context import agent_doc_ids
    allowed = agent_doc_ids()
    if allowed is not None and not allowed:
        return ""

    pinned_ids = canvas_doc_ids(canvas_id)
    if allowed is not None:
        pinned_ids = [d for d in pinned_ids if d in allowed]

    pinned_hits: list[dict] = []
    try:
        if pinned_ids:
            wide = search_documents(query, top_k=max(top_k * 8, 32), connection_id=connection_id)
            pinned_hits = [h for h in wide if h.get("doc_id") in set(pinned_ids)][:top_k]

        hits = search_documents(query, top_k=top_k if allowed is None else max(top_k * 4, 16),
                                connection_id=connection_id)
    except DocumentSearchUnavailable as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the documents could not be searched; the prompt says so",
                 counter="knowledge.docs_unavailable")
        return DOCUMENTS_UNAVAILABLE_SECTION
    if allowed is not None:
        hits = [h for h in hits if h.get("doc_id") in allowed]
    seen = {(h.get("doc_id"), h.get("chunk_index")) for h in pinned_hits}
    hits = [h for h in hits
            if (h.get("doc_id"), h.get("chunk_index")) not in seen][:top_k]

    if not pinned_hits and not hits:
        return ""

    lines: list[str] = []
    words = matched_by_words(pinned_hits + hits)
    if words:
        # FA-1 — a passage the words matched shares the question's words, not necessarily its meaning: said first
        lines.append(f"UPLOADED DOCUMENTS: {words}. Each passage below shares words with the question; read it "
                     "before relying on it.")
    if pinned_hits:
        lines.append("WORKSPACE DOCUMENTS (pinned to this canvas — treat as "
                     "authoritative context for this work):")
        lines.extend(_context_lines(pinned_hits))
    if hits:
        if pinned_hits:
            lines.append("")
        lines.append("AGENT DOCUMENTS (this agent's bound context — use where relevant):"
                     if allowed is not None else
                     "EXTERNAL CONTEXT (from uploaded documents — use where relevant):")
        lines.extend(_context_lines(hits))
    return "\n".join(lines)


def _context_lines(hits: list[dict]) -> list[str]:
    """One retrieved chunk per stanza, each carrying where it came from."""
    lines: list[str] = []
    for h in hits:
        # R8a — a compiled schema doc cites its ontology node (the FQN) so the
        # model can name exactly where a fact came from; uploads keep the filename.
        provenance = h.get("fqn") or h.get("filename", "")
        lines.append(f"\n── {h['title']} ({provenance}) ──")
        lines.append(h["text"])
    return lines


def canvas_doc_ids(canvas_id: Optional[str]) -> list[str]:
    """The documents pinned to a canvas ([] for none, an unknown id, or no canvas).

    Fail-open on purpose: a canvas that cannot be read must not take down the answer
    path. Losing a pinned document degrades the context; raising would lose the reply.
    """
    if not canvas_id:
        return []
    try:
        from aughor.canvas.store import get_canvas
        canvas = get_canvas(canvas_id)
        return list(canvas.doc_ids) if canvas else []
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "reading a canvas's pinned documents is best-effort; the answer "
                      "proceeds on the unpinned corpus", counter="canvas.doc_ids")
        return []


# ── Internal ──────────────────────────────────────────────────────────────────

def _upsert_chunks(chunks: list[DocumentChunk]) -> None:
    from aughor.semantic.embedder import embed
    from aughor.semantic.vector_store import upsert

    BATCH = 32
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i: i + BATCH]
        texts = [c.embed_text() for c in batch]
        vectors = embed(texts)
        points = [
            {
                "id": c.point_id(),
                "vector": v,
                "payload": c.payload(),
            }
            for c, v in zip(batch, vectors)
        ]
        upsert(DOCS_COLLECTION, points)
