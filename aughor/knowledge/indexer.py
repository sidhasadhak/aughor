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
    env = os.environ.get("AUGHOR_DOCUMENTS_REGISTRY")
    return Path(env) if env else _REGISTRY_PATH


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
    })
    _save_registry(docs)


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
        return {"doc_id": doc_id, "chunk_count": 0}

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


def delete_document(doc_id: str) -> bool:
    """Delete a document from both the registry and Qdrant."""
    _delete_doc_chunks(doc_id)
    return _deregister(doc_id)


def doctree_doc_id(connection_id: str, schema: str = "") -> str:
    """The deterministic doc_id for one (connection, schema) doc tree."""
    return f"doctree::{connection_id}::{schema or 'default'}"


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


def search_documents(query: str, top_k: int = 4) -> list[dict]:
    """
    Semantic search over indexed documents.
    Returns list of {text, filename, title, doc_id, score} sorted by relevance.
    """
    try:
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.vector_store import collection_count, search
        if collection_count(DOCS_COLLECTION) == 0:
            return []
        vector = embed_one(query)
        hits = search(DOCS_COLLECTION, vector, top_k=top_k)
        results = []
        for h in hits:
            p = h["payload"]
            results.append({
                "text": p.get("text", ""),
                "filename": p.get("filename", ""),
                "title": p.get("title", ""),
                "doc_id": p.get("doc_id", ""),
                "chunk_index": p.get("chunk_index", 0),
                "fqn": p.get("fqn", ""),           # R8a — ontology-node provenance
                "source_url": p.get("source_url", ""),
                "score": h["score"],
            })
        return results
    except Exception:
        return []


def build_external_context_section(query: str, top_k: int = 4) -> str:
    """
    Retrieve relevant document snippets and format them for prompt injection.
    Returns empty string when no documents are indexed or Qdrant is unavailable.

    When a user-defined agent is active (flag `agents.user_defined`), retrieval
    is scoped to THAT agent's bound documents: search wider, keep only its
    doc_ids. An agent with no bound documents sees none (fail-closed — its
    context is what its creator gave it). No agent → unchanged global behavior.
    """
    from aughor.custom_agents.context import agent_doc_ids
    allowed = agent_doc_ids()
    if allowed is not None and not allowed:
        return ""
    hits = search_documents(query, top_k=top_k if allowed is None else max(top_k * 4, 16))
    if allowed is not None:
        hits = [h for h in hits if h.get("doc_id") in allowed][:top_k]
    if not hits:
        return ""
    header = ("AGENT DOCUMENTS (this agent's bound context — use where relevant):"
              if allowed is not None else
              "EXTERNAL CONTEXT (from uploaded documents — use where relevant):")
    lines = [header]
    for h in hits:
        # R8a — a compiled schema doc cites its ontology node (the FQN) so the
        # model can name exactly where a fact came from; uploads keep the filename.
        provenance = h.get("fqn") or h.get("filename", "")
        lines.append(f"\n── {h['title']} ({provenance}) ──")
        lines.append(h["text"])
    return "\n".join(lines)


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
