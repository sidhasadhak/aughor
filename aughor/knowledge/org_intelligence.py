"""
Org Intelligence Layer — M16e.

Canvas insights promoted via "Promote to Org →" are embedded into the
`org_intelligence` Qdrant collection. build_org_intelligence_section() is
injected into ADA_SYNTHESIZE_PROMPT so every future investigation benefits from
accumulated org-wide patterns.
"""
from __future__ import annotations

import datetime
import hashlib
import os
from typing import Optional

ORG_INTEL_COLLECTION = "org_intelligence"
_QDRANT_URL = os.getenv("AUGHOR_QDRANT_URL", "http://localhost:6333")


# ── Qdrant helpers ─────────────────────────────────────────────────────────────

def _ensure_collection() -> None:
    from aughor.semantic.vector_store import ensure_collection
    ensure_collection(ORG_INTEL_COLLECTION)


def _point_id(canvas_id: str, insight_id: str) -> int:
    """Deterministic numeric point ID so re-promoting the same insight is idempotent."""
    key = f"{canvas_id}:{insight_id}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)


# ── Public write API ───────────────────────────────────────────────────────────

def promote_to_org(
    insight_id: str,
    text: str,
    domain: str,
    novelty: int,
    canvas_id: str,
    angle: str = "",
    promoted_by: str = "user",
) -> dict:
    """
    Embed insight text and upsert into the org_intelligence Qdrant collection.
    Idempotent: re-promoting the same (canvas_id, insight_id) overwrites the point.
    Returns the stored insight dict.
    """
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import upsert

    promoted_at = datetime.datetime.utcnow().isoformat() + "Z"
    point_id = _point_id(canvas_id, insight_id)

    _ensure_collection()
    vector = embed_one(text)
    payload = {
        "insight_id": insight_id,
        "canvas_id": canvas_id,
        "text": text,
        "domain": domain,
        "angle": angle,
        "novelty": novelty,
        "promoted_by": promoted_by,
        "promoted_at": promoted_at,
    }
    upsert(ORG_INTEL_COLLECTION, [{"id": str(point_id), "vector": vector, "payload": payload}])
    return {"id": str(point_id), **payload}


# ── Public read API ────────────────────────────────────────────────────────────

def search_org_intelligence(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search over promoted org insights. Returns [] when Qdrant is unavailable."""
    try:
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.vector_store import collection_count, search

        if collection_count(ORG_INTEL_COLLECTION) == 0:
            return []
        vector = embed_one(query)
        hits = search(ORG_INTEL_COLLECTION, vector, top_k=top_k)
        return [{"id": str(h["payload"].get("insight_id", "")), "score": h["score"], **h["payload"]} for h in hits]
    except Exception:
        return []


def build_org_intelligence_section(question: str, top_k: int = 5) -> str:
    """
    Retrieve relevant org-wide insights and format them for ADA prompt injection.
    Returns empty string when the collection is empty or Qdrant is unavailable.
    """
    hits = search_org_intelligence(question, top_k=top_k)
    if not hits:
        return ""
    lines = ["ORG-WIDE INTELLIGENCE (verified patterns promoted from past canvas investigations):"]
    for h in hits:
        domain_tag = f"[{h['domain']}] " if h.get("domain") else ""
        novelty_tag = f"  (novelty {h['novelty']})" if h.get("novelty") else ""
        lines.append(f"• {domain_tag}{h['text']}{novelty_tag}")
    return "\n".join(lines) + "\n"


def list_org_intelligence() -> list[dict]:
    """Scroll the entire org_intelligence collection and return all insights."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=_QDRANT_URL)
        results: list[dict] = []
        offset = None
        while True:
            batch, next_offset = client.scroll(
                collection_name=ORG_INTEL_COLLECTION,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in batch:
                results.append({"id": str(p.id), **p.payload})
            if next_offset is None:
                break
            offset = next_offset
        return sorted(results, key=lambda x: x.get("promoted_at", ""), reverse=True)
    except Exception:
        return []


def delete_org_insight(point_id: str) -> bool:
    """Delete a promoted insight from the org collection by its numeric point id."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointIdsList

        client = QdrantClient(url=_QDRANT_URL)
        client.delete(
            collection_name=ORG_INTEL_COLLECTION,
            points_selector=PointIdsList(points=[int(point_id)]),
        )
        return True
    except Exception:
        return False
