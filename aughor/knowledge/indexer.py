"""
Document indexer — embeds DocumentChunks into the `aughor_documents` Qdrant collection.
Also holds the document metadata registry (data/documents.json).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from aughor.knowledge.documents import DocumentChunk, chunk_file

DOCS_COLLECTION = "aughor_documents"
_REGISTRY_PATH = Path(__file__).parent.parent.parent / "data" / "documents.json"


# ── Registry (metadata store) ─────────────────────────────────────────────────

def _load_registry() -> list[dict]:
    if not _REGISTRY_PATH.exists():
        return []
    with open(_REGISTRY_PATH) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _save_registry(docs: list[dict]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_REGISTRY_PATH, "w") as f:
        json.dump(docs, f, indent=2)


def list_documents() -> list[dict]:
    return _load_registry()


def get_document(doc_id: str) -> Optional[dict]:
    return next((d for d in _load_registry() if d["doc_id"] == doc_id), None)


def _register(doc_id: str, filename: str, title: str, chunk_count: int, uploaded_at: str) -> None:
    docs = _load_registry()
    # Remove any existing entry for this doc_id
    docs = [d for d in docs if d["doc_id"] != doc_id]
    docs.append({
        "doc_id": doc_id,
        "filename": filename,
        "title": title,
        "chunk_count": chunk_count,
        "uploaded_at": uploaded_at,
    })
    _save_registry(docs)


def _deregister(doc_id: str) -> bool:
    docs = _load_registry()
    filtered = [d for d in docs if d["doc_id"] != doc_id]
    if len(filtered) == len(docs):
        return False
    _save_registry(filtered)
    return True


# ── Qdrant helpers ────────────────────────────────────────────────────────────

def _ensure_collection() -> None:
    from aughor.semantic.vector_store import ensure_collection
    ensure_collection(DOCS_COLLECTION)


def _delete_doc_chunks(doc_id: str) -> None:
    """Delete all Qdrant points belonging to a document."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        import os
        client = QdrantClient(url=os.getenv("AUGHOR_QDRANT_URL", "http://localhost:6333"))
        client.delete(
            collection_name=DOCS_COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def index_file(path: Path, title: Optional[str] = None) -> dict:
    """
    Parse, chunk, embed, and upsert a document file.
    Returns the registry entry dict.
    """
    import datetime
    doc_id = uuid.uuid4().hex
    uploaded_at = datetime.datetime.utcnow().isoformat() + "Z"
    title = title or path.stem.replace("_", " ").replace("-", " ").title()

    chunks = chunk_file(path, doc_id=doc_id, title=title, uploaded_at=uploaded_at)
    if not chunks:
        raise ValueError(f"No text could be extracted from {path.name}")

    _ensure_collection()
    _upsert_chunks(chunks)
    _register(doc_id, path.name, title, len(chunks), uploaded_at)

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
                "score": h["score"],
            })
        return results
    except Exception:
        return []


def build_external_context_section(query: str, top_k: int = 4) -> str:
    """
    Retrieve relevant document snippets and format them for prompt injection.
    Returns empty string when no documents are indexed or Qdrant is unavailable.
    """
    hits = search_documents(query, top_k=top_k)
    if not hits:
        return ""
    lines = ["EXTERNAL CONTEXT (from uploaded documents — use where relevant):"]
    for h in hits:
        lines.append(f"\n── {h['title']} ({h['filename']}) ──")
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
