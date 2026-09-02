"""The semantic-index seam — embedded Qdrant, a Qdrant server, or pgvector behind one interface.

Three backends, selected by deployment shape rather than code changes (S1, §3.6):

* **Embedded Qdrant** — the local default when nothing is pinned. ``qdrant-client``'s
  in-process on-disk mode (``QdrantClient(path=…)``) at ``AUGHOR_QDRANT_PATH``
  (default ``<state dir>/qdrant``): same API, no port, no daemon, no second install
  step — a fresh clone gets semantic search from ``uv sync`` alone. Local mode holds
  an EXCLUSIVE lock on its directory, so the API process is the single writer — the
  same one-writer rule ``data/system.db`` already lives by — and this module keeps
  exactly one client per path (serialized: request threads and kernel job threads
  both reach this seam).
* **Qdrant server** — explicitly setting ``AUGHOR_QDRANT_URL`` pins it; self-hosted
  deployments (and any machine with an existing server holding vectors) keep exactly
  today's behaviour.
* **pgvector** — chosen automatically when ``AUGHOR_DB_URL`` names a Postgres and no
  Qdrant URL was pinned. The index rides IN the platform's one managed database:
  no second service, ~0 MB of bundle (psycopg2 is already in the serving set), and
  semantic rows live inside the same purge/transaction boundary as the state they
  index — a finding deleted relationally can no longer survive as a stray vector,
  which is the drift class the Qdrant purge hooks existed to chase.

The availability contract is unchanged from the trim's design and applies to all:
an ABSENT capability (package not installed / no database configured) degrades —
reads answer like an empty index, writes no-op — while a CONFIGURED backend that is
down RAISES, because an outage is worth surfacing and a deployment choice is not.
For the embedded backend "down" means the directory's lock is held by another
process, and the error says which rule was broken rather than leaking portalocker's.

Filters: callers use :func:`match_filter` (a neutral exact-match on one payload
key — the only shape the codebase has ever needed). The Qdrant backends also accept
raw ``qdrant_client`` Filter objects for compatibility.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

QDRANT_URL_ENV = "AUGHOR_QDRANT_URL"
QDRANT_PATH_ENV = "AUGHOR_QDRANT_PATH"
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

    An explicit AUGHOR_QDRANT_URL pins the Qdrant server — self-hosted deployments
    (and a laptop with an existing server holding vectors) keep exactly that
    behaviour. Otherwise a Postgres AUGHOR_DB_URL means pgvector: the index belongs
    in the database the deployment already has. With neither, Qdrant runs EMBEDDED
    (`_client()` opens local mode at AUGHOR_QDRANT_PATH) when the client package is
    present, else there is no index. Both Qdrant shapes answer 'qdrant' here —
    every operation in this module is identical across them; only `_client()`
    differs — so callers switching on the name need never know which one runs."""
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


# ── Qdrant backend plumbing ──────────────────────────────────────────────────

def _embedded_path() -> str:
    """Where the embedded index lives: AUGHOR_QDRANT_PATH, else `<state dir>/qdrant`.

    Rides `state_dir()` rather than a literal `data/` so the whole-deployment moves
    (and the test suite's temp AUGHOR_STATE_DIR) carry the index with them — the
    property every store guard in test_store_hermeticity exists to keep."""
    p = os.getenv(QDRANT_PATH_ENV, "")
    if p:
        return p
    from aughor.db.paths import state_dir
    return str(state_dir() / "qdrant")


class _Serialized:
    """One lock around every method of the embedded client.

    Local mode mutates in-process state with no locking of its own, and this seam is
    reached from request threads and kernel job threads at once. Server/pgvector
    backends need none of this — their concurrency is the server's job."""

    def __init__(self, inner, lock: threading.RLock):
        self._inner, self._lock = inner, lock

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def _call(*a, **kw):
            with self._lock:
                return attr(*a, **kw)
        return _call


#: One client per embedded path, for the life of the process. Local mode takes an
#: exclusive lock on its directory, so a second QdrantClient(path=…) — even in the
#: same process — is refused by qdrant itself; per-path caching is what makes the
#: lock a property instead of a crash. Keyed by path so a test pointing
#: AUGHOR_QDRANT_PATH somewhere fresh gets a fresh index, not the first one opened.
_embedded: dict[str, _Serialized] = {}
_embedded_guard = threading.Lock()


def _client():
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise SemanticIndexUnavailable(
            "semantic search needs the 'semantic' extra (qdrant-client). Install it with:"
            "  uv pip install -e '.[semantic]'  — or call vector_store.available() first "
            "and degrade, which is what every function in this module does."
        ) from exc
    url = os.getenv(QDRANT_URL_ENV)
    if url:
        return QdrantClient(url=url)
    path = _embedded_path()
    with _embedded_guard:
        client = _embedded.get(path)
        if client is None:
            try:
                inner = QdrantClient(path=path)
            except Exception as exc:
                raise SemanticIndexUnavailable(
                    f"the embedded semantic index at {path!r} could not be opened — "
                    "most likely another process holds its exclusive lock. One process "
                    "per index directory (the same one-writer rule as data/system.db): "
                    "run through the API, or point AUGHOR_QDRANT_PATH at a throwaway "
                    "directory, or pin AUGHOR_QDRANT_URL at a server."
                ) from exc
            client = _embedded[path] = _Serialized(inner, threading.RLock())
    return client


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

    from aughor.db.dsn import split_dsn

    # Query params lifted into kwargs — see aughor/db/dsn.py. The same AUGHOR_DB_URL
    # the stores use, so it carries the same provider query string.
    _base, _params, _dropped = split_dsn(os.environ["AUGHOR_DB_URL"])
    conn = psycopg2.connect(_base, **_params)
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

def collection_dim(name: str) -> int | None:
    """The vector width an existing collection was created with, or None if there is no
    such collection (or the backend cannot say).

    Exists because `ensure_collection` silently does NOTHING when a collection is already
    there, whatever its width — so changing embedding model against an existing index
    produces a dimension mismatch at UPSERT (an opaque driver error) and, worse, at SEARCH,
    where `search_documents`' `except: return []` turns it into a silently empty result.
    """
    if not available():
        return None
    if backend() == "pgvector":
        return None                      # one shared column; width is not per collection
    try:
        from qdrant_client.models import VectorParams

        info = _client().get_collection(name)
        params = info.config.params.vectors
        if isinstance(params, VectorParams):
            return int(params.size)
        if isinstance(params, dict):     # named-vector collections
            first = next(iter(params.values()), None)
            return int(first.size) if first is not None else None
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an unknown collection width is reported as unknown, not as a match",
                 counter="vector_store.collection_dim")
    return None


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


def drop_collection(name: str) -> bool:
    """Delete a collection outright. True if it was there and is now gone.

    The only way to change a collection's VECTOR WIDTH: Qdrant fixes it at creation and
    `ensure_collection` no-ops on an existing one. So re-embedding with a model of a
    different dimension means dropping and recreating, which is why this exists and why its
    only caller reads every payload out first.
    """
    if not available():
        return False
    if backend() == "pgvector":
        conn = _pg()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM vectors WHERE collection = %s", (name,))
            removed = cur.rowcount
            cur.close()
            conn.commit()
            return bool(removed)
        finally:
            conn.close()
    client = _client()
    if name not in {c.name for c in client.get_collections().collections}:
        return False
    client.delete_collection(collection_name=name)
    return True


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


def scroll_points(collection: str, limit: int = 10_000) -> list[dict]:
    """All points as ``[{id: str, payload: dict}]`` — `scroll_payloads` plus the id.

    Exists for the callers that DELETE by id afterwards (org intelligence's list →
    remove flow): a payload without its point id is a row you can read but never
    address. Empty list on any error, same contract as `scroll_payloads`."""
    try:
        if backend() == "pgvector":
            conn = _pg()
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, payload FROM vectors WHERE collection = %s LIMIT %s",
                            (collection, limit))
                rows = [{"id": str(i), "payload": p} for i, p in cur.fetchall()]
                cur.close()
                return rows
            finally:
                conn.close()
        client = _client()
        out: list[dict] = []
        offset = None
        while len(out) < limit:
            records, offset = client.scroll(
                collection_name=collection, limit=min(1000, limit - len(out)),
                offset=offset, with_payload=True, with_vectors=False,
            )
            out.extend({"id": str(r.id), "payload": r.payload or {}} for r in records)
            if offset is None:
                break
        return out
    except Exception:
        return []


def delete_ids(collection: str, ids: list) -> bool:
    """Delete points by id. True when the backend accepted the delete; False on error
    (an id that never existed is not an error — deletes are idempotent)."""
    try:
        wanted = [int(i) for i in ids]
        if not wanted:
            return True
        if backend() == "pgvector":
            conn = _pg()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM vectors WHERE collection = %s AND id = ANY(%s)",
                            (collection, wanted))
                cur.close()
                conn.commit()
                return True
            finally:
                conn.close()
        from qdrant_client.models import PointIdsList
        _client().delete(collection_name=collection,
                         points_selector=PointIdsList(points=wanted))
        return True
    except Exception:
        return False


def _hash_id(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:16], 16) % (2 ** 63)
