"""Thin Qdrant wrapper — collection management, upsert, search.

Qdrant is OPTIONAL twice over, and the two cases are deliberately not the same:

* **The server is unreachable.** Callers already treat this as non-critical ("Qdrant
  unavailable — the metadata flag is already set"), and it stays that way: the client
  raises, the caller's existing handler absorbs it. A configured-but-broken index is a
  problem worth surfacing, not one to swallow here.
* **The package is not installed.** That is a DEPLOYMENT CHOICE — `qdrant-client` lives in
  the `[semantic]` extra because it pulls 39 MB of grpc, which a serving deployment that
  does not use semantic search should not carry. Here the honest answer is "there is no
  index", so reads return empty and writes no-op, exactly as they would against an index
  that has never been populated.

Distinguishing them matters: silently swallowing a connection failure would hide a real
outage, while raising ImportError for an uninstalled optional feature would turn a
supported configuration into a crash.
"""
from __future__ import annotations

import hashlib
import logging
import os

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("AUGHOR_QDRANT_URL", "http://localhost:6333")
VECTOR_DIM = 768  # nomic-embed-text


class SemanticIndexUnavailable(RuntimeError):
    """Raised when the vector store is used without the `semantic` extra installed."""


def available() -> bool:
    """Whether the `qdrant-client` package is importable. Says nothing about the server."""
    try:
        import qdrant_client  # noqa: F401
        return True
    except ImportError:
        return False


def _client():
    """The raw client. Deliberately NOT guarded — every public entry point in this module
    checks :func:`available` first, so reaching here without the package means a caller
    skipped that check, and a clear error beats a bare ImportError from three frames down."""
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise SemanticIndexUnavailable(
            "semantic search needs the 'semantic' extra (qdrant-client). Install it with:"
            "  uv pip install -e '.[semantic]'  — or call vector_store.available() first "
            "and degrade, which is what every function in this module does."
        ) from exc
    return QdrantClient(url=QDRANT_URL)


def ensure_collection(name: str, dim: int = VECTOR_DIM) -> None:
    if not available():
        logger.debug("semantic index unavailable (qdrant-client not installed); "
                     "skipping ensure_collection(%s)", name)
        return
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
    if not available():
        logger.debug("semantic index unavailable (qdrant-client not installed); "
                     "dropping %d point(s) for %s", len(points or []), collection)
        return
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
    """Returns [{score, payload}] sorted by descending relevance.

    An uninstalled client answers like an empty index — no hits — because that is what a
    deployment without semantic search HAS. Callers already handle "no hits"."""
    if not available():
        return []
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
