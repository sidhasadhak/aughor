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

WHY THERE IS A PROCESS-LOCAL LAYER IN FRONT OF A PERSISTENT ONE
---------------------------------------------------------------
`vector_store.available()` reports INSTALLATION, not liveness — its own docstring
says it "says nothing about the server being up". So when the backend is configured
but down (a local Qdrant that is not running is the common case), `get_cached`
raises and `store` fails. Both call sites in `routers/system.py` wrap those in
`except Exception: pass`, which is correct for availability and catastrophic for
latency: the cache silently stops caching, and **every** `/suggestions` request pays
the full LLM call. Measured on this machine with Qdrant down: 42.8s of a 43.7s
request was the model, and nothing was ever cached to make the next one cheaper.

The layer below is a fine persistent cache and stays the source of truth across
restarts. This one only ensures a dead backend costs the FIRST request rather than
every request. It is deliberately small and dumb: no TTL, because the fingerprint
already invalidates on schema change, and a hard bound so a long-lived process
cannot grow without limit.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SUGGESTIONS_COLLECTION = "schema_suggestions"
_SUGGESTIONS_PER_SCHEMA = 6

#: Bounded so a process serving many connections cannot grow without limit. Entries
#: are keyed by (connection_id, fingerprint) and each holds 6 short strings.
_LOCAL_MAX = 64
_local_lock = threading.Lock()
_local: OrderedDict[tuple[str, str], list[dict]] = OrderedDict()


def _local_get(key: tuple[str, str]) -> list[dict] | None:
    with _local_lock:
        hit = _local.get(key)
        if hit is not None:
            _local.move_to_end(key)          # LRU: keep the live schemas resident
            return list(hit)
    return None


def _local_put(key: tuple[str, str], suggestions: list[dict]) -> None:
    with _local_lock:
        _local[key] = list(suggestions)
        _local.move_to_end(key)
        while len(_local) > _LOCAL_MAX:
            _local.popitem(last=False)


def local_clear() -> int:
    """Drop the process-local layer. For tests and for any caller that must force a
    re-read of the persistent cache. Returns how many entries were dropped."""
    with _local_lock:
        n = len(_local)
        _local.clear()
    return n


def local_count() -> int:
    """How many entries the process-local layer holds — for tests and diagnostics."""
    with _local_lock:
        return len(_local)


# ── Thundering-herd guard ────────────────────────────────────────────────────
#
# The work this cache holds costs one LLM call, measured at 42.8s. Nothing stopped
# two requests for the SAME (connection, schema) making that call at the same time —
# two tabs, or a reload — and neither can hit the other's cache entry, because
# neither has finished. On a free tier capped at 20 requests/minute that is not just
# slow, it is quota that buys the identical answer twice.

#: A follower waits this long before computing anyway. A wedged leader must not
#: strand every other caller; the duplicate call is the lesser failure, and it is
#: what happened on every request before this existed.
INFLIGHT_WAIT_S = 90.0

_inflight_lock = threading.Lock()
_inflight: dict[tuple[str, str], threading.Event] = {}


def inflight_count() -> int:
    """Computations currently held by a leader — for tests and diagnostics."""
    with _inflight_lock:
        return len(_inflight)


def compute_once(connection_id: str, fingerprint: str, compute) -> list[dict]:
    """Run `compute` at most once at a time per (connection, schema).

    Unlike `db/single_flight.py` — where the follower re-runs because it needs state
    on its OWN connection object — a follower here wants the value itself, so it
    takes the leader's result out of the process-local layer. It only recomputes if
    the leader failed or timed out, which is the pre-existing behaviour rather than
    a new failure mode.
    """
    key = (connection_id, fingerprint)
    with _inflight_lock:
        event = _inflight.get(key)
        is_leader = event is None
        if is_leader:
            event = threading.Event()
            _inflight[key] = event

    if not is_leader:
        logger.info("suggestions: %s is already being computed — waiting", key)
        if not event.wait(timeout=INFLIGHT_WAIT_S):
            logger.warning("suggestions: waited %.0fs for %s and it never finished — "
                           "computing anyway", INFLIGHT_WAIT_S, key)
        hit = _local_get(key)
        if hit is not None:
            return hit
        return compute()

    try:
        result = compute()
        # Published BEFORE the event is set, so a waking follower cannot miss it.
        _local_put(key, result)
        return result
    finally:
        with _inflight_lock:
            _inflight.pop(key, None)
        event.set()


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
    Raises on Qdrant connectivity errors so the caller can decide to degrade — but NOT
    when the client is simply absent (the `[semantic]` extra), which is an empty cache.

    The process-local layer is consulted first and answers WITHOUT raising, so a
    backend that is configured but down degrades to "cold once" instead of "cold
    every time". See the module docstring.
    """
    local = _local_get((connection_id, fingerprint))
    if local is not None:
        return local

    from aughor.semantic.vector_store import available
    if not available():
        return None
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    from aughor.semantic.vector_store import _client, collection_count

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

    found = [
        {"text": r.payload["text"], "mode": r.payload["mode"]}
        for r in results
        if r.payload
    ]
    _local_put((connection_id, fingerprint), found)   # next read skips the network
    return found


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

    The process-local layer is written FIRST and unconditionally. Everything below
    it — embedding, collection setup, upsert — can raise when the backend is down,
    and the caller wraps this whole call in `except Exception: pass`. Writing local
    first is what makes a failed persist cost one LLM call instead of one per
    request, which is the entire point of the layer.
    """
    _local_put((connection_id, fingerprint), suggestions)

    from aughor.semantic.embedder import embed
    from aughor.semantic.vector_store import ensure_collection, upsert

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
        from aughor.semantic.embedder import embed_one
        from aughor.semantic.vector_store import search

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
