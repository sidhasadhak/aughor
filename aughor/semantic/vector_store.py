"""Thin Qdrant wrapper — collection management, upsert, search."""
from __future__ import annotations

import hashlib
import os

QDRANT_URL = os.getenv("AUGHOR_QDRANT_URL", "http://localhost:6333")
VECTOR_DIM = 768  # nomic-embed-text


def _client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL)


def ensure_collection(name: str, dim: int = VECTOR_DIM) -> None:
    from qdrant_client.models import Distance, VectorParams
    client = _client()
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )


def upsert(collection: str, points: list[dict]) -> None:
    """points: list of {id: str, vector: list[float], payload: dict}"""
    from qdrant_client.models import PointStruct
    client = _client()
    structs = [
        PointStruct(
            id=_hash_id(p["id"]),
            vector=p["vector"],
            payload=p["payload"],
        )
        for p in points
    ]
    client.upsert(collection_name=collection, points=structs)


def search(collection: str, vector: list[float], top_k: int = 10, query_filter=None) -> list[dict]:
    """Returns [{score, payload}] sorted by descending relevance."""
    client = _client()
    response = client.query_points(
        collection_name=collection,
        query=vector,
        limit=top_k,
        query_filter=query_filter,
    )
    return [{"score": p.score, "payload": p.payload} for p in response.points]


def collection_count(collection: str) -> int:
    """Return number of points in a collection, or 0 if not found."""
    try:
        client = _client()
        info = client.get_collection(collection)
        return info.points_count or 0
    except Exception:
        return 0


def delete_by_filter(collection: str, query_filter) -> int:
    """Delete points matching a Qdrant filter. Returns number of points deleted."""
    try:
        client = _client()
        # Qdrant delete API returns operation info; we count before/after
        before = collection_count(collection)
        client.delete(collection_name=collection, points_selector=query_filter)
        after = collection_count(collection)
        return max(0, before - after)
    except Exception:
        return 0


def scroll_payloads(collection: str, limit: int = 10_000) -> list[dict]:
    """Return all point payloads in a collection. Empty list on any error."""
    try:
        client = _client()
        records, _ = client.scroll(
            collection_name=collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [r.payload for r in records if r.payload]
    except Exception:
        return []


def _hash_id(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:16], 16) % (2 ** 63)
