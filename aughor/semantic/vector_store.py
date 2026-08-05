"""The semantic-index seam — Qdrant or pgvector behind one interface.

Two backends, selected by deployment shape rather than code changes:

* **Qdrant** — the self-hosted/local default (``AUGHOR_QDRANT_URL``, default
  ``localhost:6333``). Explicitly setting that env var pins this backend.
* **pgvector** — chosen automatically when ``AUGHOR_DB_URL`` names a Postgres and no
  Qdrant URL was pinned. The index rides IN the platform's one managed database:
  no second service, ~0 MB of bundle (psycopg2 is already in the serving set), and
  semantic rows live inside the same purge/transaction boundary as the state they
  index — a finding deleted relationally can no longer survive as a stray vector,
  which is the drift class the Qdrant purge hooks existed to chase.

The availability contract is unchanged from the trim's design and applies to both:
an ABSENT capability (package not installed / no database configured) degrades —
reads answer like an empty index, writes no-op — while a CONFIGURED backend that is
down RAISES, because an outage is worth surfacing and a deployment choice is not.

Filters: callers use :func:`match_filter` (a neutral exact-match on one payload
key — the only shape the codebase has ever needed). The Qdrant backend also accepts
raw ``qdrant_client`` Filter objects for compatibility.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

QDRANT_URL_ENV = "AUGHOR_QDRANT_URL"
VECTOR_DIM = 768  # nomic-embed-text

_PG_SCHEMA = "store_semantic"


class SemanticIndexUnavailable(RuntimeError):
    """Raised when the vector store is used without a usable backend."""


def match_filter(key: str, value) -> dict:
    """A backend-neutral exact-match filter on one payload key — the only filter
    shape any caller builds. Backends translate it; callers stop importing
    qdrant_client models (which a pgvector deployment does not install)."""
    return {"key": key, "value": value}


def backend() -> str:
    """Which backend this process uses: 'qdrant', 'pgvector', or '' (none).

    An explicit AUGHOR_QDRANT_URL pins Qdrant — self-hosted deployments keep exactly
    today's behaviour. Otherwise a Postgres AUGHOR_DB_URL means pgvector: the index
    belongs in the database the deployment already has. With neither, Qdrant's
    localhost default applies when the client package is present (the historical
    local-dev shape), else there is no index."""
    if os.getenv(QDRANT_URL_ENV):
        return "qdrant"
    url = os.getenv("AUGHOR_DB_URL", "")
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return "pgvector"
    return "qdrant" if _qdrant_importable() else ""


def _qdrant_importable() -> bool:
    try:
        import qdrant_client  # noqa: F401
        return True
    except ImportError:
        return False


def available() -> bool:
    """Whether a semantic backend is USABLE as a matter of installation/config.
    Says nothing about the server being up — a configured backend that is down
    raises from the operation itself, exactly as before."""
    b = backend()
    if b == "qdrant":
        return _qdrant_importable()
    if b == "pgvector":
        try:
            import psycopg2  # noqa: F401
            return True
        except ImportError:
            return False
    return False


# ── Qdrant backend plumbing (unchanged) ──────────────────────────────────────

def _client():
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise SemanticIndexUnavailable(
            "semantic search needs the 'semantic' extra (qdrant-client). Install it with:"
            "  uv pip install -e '.[semantic]'  — or call vector_store.available() first "
            "and degrade, which is what every function in this module does."
        ) from exc
    return QdrantClient(url=os.getenv(QDRANT_URL_ENV, "http://localhost:6333"))


def _qdrant_filter(query_filter):
    """A neutral match_filter dict → a Qdrant Filter; anything else passes through."""
    if isinstance(query_filter, dict) and {"key", "value"} <= set(query_filter):
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        return Filter(must=[FieldCondition(
            key=query_filter["key"], match=MatchValue(value=query_filter["value"]))])
    return query_filter


# ── pgvector backend plumbing ────────────────────────────────────────────────

def _pg():
    """A connection pinned to the semantic schema, table ensured. Connection
    failures RAISE (configured backend down = outage). Native Postgres SQL on
    purpose — vector ops have no sqlite meaning, so this does not ride the
    dialect-translation seam the relational stores use."""
    import psycopg2
    conn = psycopg2.connect(os.environ["AUGHOR_DB_URL"])
    cur = conn.cursor()
    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{_PG_SCHEMA}"')
    # public stays on the path: CREATE EXTENSION installs the `vector` TYPE into
    # public (its default), and a path without public cannot resolve it.
    cur.execute(f'SET search_path TO "{_PG_SCHEMA}", public')
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS vectors (
          collection TEXT NOT NULL,
          id         BIGINT NOT NULL,
          vector     vector({VECTOR_DIM}),
          payload    JSONB NOT NULL DEFAULT '{{}}',
          PRIMARY KEY (collection, id)
        )""")
    cur.execute("CREATE INDEX IF NOT EXISTS vectors_hnsw ON vectors "
                "USING hnsw (vector vector_cosine_ops)")
    cur.close()
    conn.commit()
    return conn


def _pg_where(query_filter) -> tuple[str, list]:
    if query_filter is None:
        return "", []
    if isinstance(query_filter, dict) and {"key", "value"} <= set(query_filter):
        return " AND payload->>%s = %s", [query_filter["key"], str(query_filter["value"])]
    raise ValueError(
        "the pgvector backend accepts vector_store.match_filter(...) filters only; "
        f"got {type(query_filter).__name__}")


# ── public API ───────────────────────────────────────────────────────────────

def ensure_collection(name: str, dim: int = VECTOR_DIM) -> None:
    if not available():
        logger.debug("semantic index unavailable; skipping ensure_collection(%s)", name)
        return
    if backend() == "pgvector":
        _pg().close()          # schema/table/extension ensure IS the work
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
        logger.debug("semantic index unavailable; dropping %d point(s) for %s",
                     len(points or []), collection)
        return
    if backend() == "pgvector":
        conn = _pg()
        try:
            cur = conn.cursor()
            cur.executemany(
                "INSERT INTO vectors (collection, id, vector, payload) "
                "VALUES (%s, %s, %s::vector, %s::jsonb) "
                "ON CONFLICT (collection, id) DO UPDATE "
                "SET vector = EXCLUDED.vector, payload = EXCLUDED.payload",
                [(collection, _hash_id(p["id"]), str(list(p["vector"])),
                  json.dumps(p["payload"], default=str)) for p in points])
            cur.close()
            conn.commit()
        finally:
            conn.close()
        return
    from qdrant_client.models import PointStruct
    client = _client()
    structs = [
        PointStruct(id=_hash_id(p["id"]), vector=p["vector"], payload=p["payload"])
        for p in points
    ]
    client.upsert(collection_name=collection, points=structs)


def search(collection: str, vector: list[float], top_k: int = 10, query_filter=None) -> list[dict]:
    """Returns [{score, payload}] sorted by descending relevance. An absent backend
    answers like an empty index — that is what such a deployment HAS."""
    if not available():
        return []
    if backend() == "pgvector":
        where, params = _pg_where(query_filter)
        conn = _pg()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 - (vector <=> %s::vector) AS score, payload FROM vectors "
                "WHERE collection = %s" + where +
                " ORDER BY vector <=> %s::vector LIMIT %s",
                [str(list(vector)), collection, *params, str(list(vector)), top_k])
            rows = cur.fetchall()
            cur.close()
            return [{"score": float(s), "payload": p} for s, p in rows]
        finally:
            conn.close()
    client = _client()
    response = client.query_points(
        collection_name=collection, query=vector, limit=top_k,
        query_filter=_qdrant_filter(query_filter),
    )
    return [{"score": p.score, "payload": p.payload} for p in response.points]


def collection_count(collection: str) -> int:
    """Number of points in a collection, or 0 if not found / no backend."""
    try:
        if backend() == "pgvector":
            conn = _pg()
            try:
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM vectors WHERE collection = %s", (collection,))
                n = cur.fetchone()[0]
                cur.close()
                return int(n)
            finally:
                conn.close()
        info = _client().get_collection(collection)
        return info.points_count or 0
    except Exception:
        return 0


def delete_by_filter(collection: str, query_filter) -> int:
    """Delete points matching a filter. Returns number deleted; 0 on any error."""
    try:
        if backend() == "pgvector":
            where, params = _pg_where(query_filter)
            conn = _pg()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM vectors WHERE collection = %s" + where,
                            [collection, *params])
                n = cur.rowcount
                cur.close()
                conn.commit()
                return int(n)
            finally:
                conn.close()
        client = _client()
        before = collection_count(collection)
        client.delete(collection_name=collection,
                      points_selector=_qdrant_filter(query_filter))
        after = collection_count(collection)
        return max(0, before - after)
    except Exception:
        return 0


def scroll_payloads(collection: str, limit: int = 10_000) -> list[dict]:
    """All point payloads in a collection. Empty list on any error."""
    try:
        if backend() == "pgvector":
            conn = _pg()
            try:
                cur = conn.cursor()
                cur.execute("SELECT payload FROM vectors WHERE collection = %s LIMIT %s",
                            (collection, limit))
                rows = [r[0] for r in cur.fetchall() if r[0]]
                cur.close()
                return rows
            finally:
                conn.close()
        records, _ = _client().scroll(
            collection_name=collection, limit=limit,
            with_payload=True, with_vectors=False,
        )
        return [r.payload for r in records if r.payload]
    except Exception:
        return []


def _hash_id(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:16], 16) % (2 ** 63)
