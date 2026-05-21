"""Qdrant-backed cache for schema-aware starter suggestions.

Each suggestion is stored as a separate embedded point so that future semantic
search ("find the suggestion closest to what the user is typing") works without
any additional infrastructure.

Collection: schema_suggestions
  One point per suggestion per (connection_id, schema_fingerprint) pair.
  payload = {connection_id, fingerprint, text, mode, created_at}
  vector  = nomic-embed-text embedding of `text`

Cache key: (connection_id, fingerprint)
  fingerprint = MD5 of the schema summary string
  → auto-invalidates when the schema changes

Graceful degradation: any Qdrant or embedding failure is caught and re-raised so
the caller can fall back to a direct LLM call without caching.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

SUGGESTIONS_COLLECTION = "schema_suggestions"
_SUGGESTIONS_PER_SCHEMA = 6


# ── Fingerprint ───────────────────────────────────────────────────────────────

def schema_fingerprint(schema_summary: str) -> str:
    """Stable fingerprint of the schema — derived from sorted table+column names only.

    Strips row counts and descriptions (which can vary) so the fingerprint only
    changes when the structure changes (new table, renamed column, etc.).
    """
    import re
    # Extract "TABLE: name" and "  column_name  TYPE" lines only
    structural_lines: list[str] = []
    for line in schema_summary.splitlines():
        m = re.match(r"^\s*(TABLE:\s+\w+)", line)
        if m:
            structural_lines.append(m.group(1))
            continue
        # Column lines: leading whitespace + identifier + type, no dashes/comments
        m2 = re.match(r"^\s+(\w+)\s+([A-Z]+)", line)
        if m2 and not line.strip().startswith("--"):
            structural_lines.append(f"  {m2.group(1)} {m2.group(2)}")
    stable = "\n".join(sorted(structural_lines))
    return hashlib.md5(stable.encode()).hexdigest()[:16]


# ── Cache read ────────────────────────────────────────────────────────────────

def get_cached(connection_id: str, fingerprint: str) -> list[dict] | None:
    """
    Return cached suggestions for this (connection_id, fingerprint) pair, or
    None if not found.

    Returns list of {text: str, mode: str} dicts, ready for the API response.
    Raises on Qdrant connectivity errors so the caller can decide to degrade.
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    from hermes.semantic.vector_store import _client, collection_count

    if collection_count(SUGGESTIONS_COLLECTION) == 0:
        return None

    client = _client()
    results, _ = client.scroll(
        collection_name=SUGGESTIONS_COLLECTION,
        scroll_filter=Filter(must=[
            FieldCondition(key="connection_id", match=MatchValue(value=connection_id)),
            FieldCondition(key="fingerprint",   match=MatchValue(value=fingerprint)),
        ]),
        limit=_SUGGESTIONS_PER_SCHEMA + 2,
        with_payload=True,
        with_vectors=False,
    )

    if len(results) < _SUGGESTIONS_PER_SCHEMA:
        return None  # incomplete cache entry — treat as miss

    return [
        {"text": r.payload["text"], "mode": r.payload["mode"]}
        for r in results
        if r.payload
    ]


# ── Cache write ───────────────────────────────────────────────────────────────

def store(
    connection_id: str,
    fingerprint: str,
    suggestions: list[dict],   # [{text, mode}, ...]
) -> None:
    """
    Embed each suggestion and upsert into Qdrant.
    Old points for the same (connection_id, fingerprint) are overwritten via
    deterministic IDs. Points from a previous schema version are left in place
    (different fingerprint → different IDs) and will naturally become orphans;
    a periodic cleanup can remove them if needed.
    """
    from hermes.semantic.embedder import embed
    from hermes.semantic.vector_store import ensure_collection, upsert

    ensure_collection(SUGGESTIONS_COLLECTION)

    texts = [s["text"] for s in suggestions]
    vectors = embed(texts)

    now = datetime.now(timezone.utc).isoformat()
    points = [
        {
            # Deterministic ID: connection + fingerprint + position
            "id": f"{connection_id}:{fingerprint}:{i}",
            "vector": vector,
            "payload": {
                "connection_id": connection_id,
                "fingerprint":   fingerprint,
                "text":          suggestions[i]["text"],
                "mode":          suggestions[i]["mode"],
                "created_at":    now,
            },
        }
        for i, vector in enumerate(vectors)
    ]
    upsert(SUGGESTIONS_COLLECTION, points)


# ── Semantic search (future use) ──────────────────────────────────────────────

def search_similar(
    query: str,
    connection_id: str,
    top_k: int = 3,
) -> list[dict]:
    """
    Find the suggestions most semantically similar to `query` for the given
    connection. Useful for real-time autocomplete: as the user types, surface
    the closest pre-generated suggestion.

    Returns [] on any error (graceful degradation).
    """
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        from hermes.semantic.embedder import embed_one
        from hermes.semantic.vector_store import search

        vector = embed_one(query)
        hits = search(
            SUGGESTIONS_COLLECTION,
            vector,
            top_k=top_k,
            query_filter=Filter(must=[
                FieldCondition(key="connection_id", match=MatchValue(value=connection_id)),
            ]),
        )
        return [
            {"text": h["payload"]["text"], "mode": h["payload"]["mode"], "score": h["score"]}
            for h in hits
        ]
    except Exception:
        return []
