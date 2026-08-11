"""Reuse platform-store connections instead of opening one per operation.

`connect_store` built a brand-new connection on every call. On SQLite that is a
cheap file open; on Postgres it is a TCP + TLS + auth handshake to the database,
followed by `CREATE SCHEMA IF NOT EXISTS`, `SET search_path` and a commit — per
store operation. Requests make several. Measured against production, warm, with the
function already hot (`/health` answering in 0.24s):

    /connections     1.7s    ~1 store connection
    /workspaces      6.5s    ~3-4
    /catalog/tree   10.9s    ~7

Latency tracked the NUMBER of store operations, not the amount of data. `/workspaces`
opened three or four connections to Supabase to return three rows.

WHY THREAD-LOCAL OWNERSHIP RATHER THAN CHECKOUT
-----------------------------------------------
`aughor/db/pool.py` pools DATA connections with exclusive checkout: `acquire` removes
an idle connection and `close()` is swapped to return it. The safety property that
buys is that **one connection is never used by two threads at once** — psycopg2
connections are not thread-safe, and the data pool's own note says stale/cross-thread
data is worse than slow.

That mechanism cannot work here, because it depends on callers closing. They do not:
of 142 store opens across the codebase, five stores close ZERO of them —
`workspace/store.py`, `canvas/store.py`, `dashboard/store.py`, `rbac/store.py` and
`savedquery/store.py`. `workspace/store.py` is the 6.5s endpoint. A return-on-close
pool would have delivered nothing exactly where the cost is worst.

So the connection is owned by the THREAD instead. Each thread keeps its own
connection per store schema, forever; no connection is ever handed to a second
thread. That is the same exclusivity guarantee, enforced by ownership rather than by
a protocol the code does not follow — and it cannot be broken by a missing `close()`.

WHAT REUSE MAKES POSSIBLE THAT A FRESH CONNECTION DID NOT
----------------------------------------------------------
A reused transactional connection carries state a fresh one never had, so acquiring
one is not just a dictionary lookup:

  * **Aborted transactions.** A failed statement leaves psycopg2 INERROR, and EVERY
    later statement on that connection fails until a rollback. Fresh connections hid
    this; reuse would turn one bad query into a permanently broken store. Acquire
    rolls back anything not IDLE.
  * **Dead sockets.** Supabase, a pooler, or an idle timeout can close the server
    side. A connection that is `closed`, or whose state cannot be read, is discarded
    and rebuilt rather than handed out.
  * **`close()` from the 133 call sites that do call it.** Physically closing would
    defeat the reuse for every well-behaved store. It is swapped to a no-op that
    keeps the connection on its thread, mirroring how the data pool swaps close to
    "return to pool".

SQLite is deliberately NOT pooled: a local file open is microseconds, so pooling
would add lifetime bugs in exchange for nothing.

Reuse also makes `ensure_once` possible, which is where the rest of the latency was:
a pooled connection can remember that it has already run its store's schema DDL, so
the `CREATE TABLE IF NOT EXISTS` block stops being replayed on every operation.

⚠️ THIS POOL TAKES A SERVERLESS DEPLOYMENT DOWN — OFF BY DEFAULT THERE
----------------------------------------------------------------------
Everything above is true of a long-lived server and false of Vercel. Enabling this
pool in production caused a TOTAL outage: every route, including `/health`, failed
with FUNCTION_INVOCATION_FAILED. Verified by isolating one variable — the same
commit (240f182) boots and serves 200s with the pool off, and does not boot with it
on.

Why the failure is total rather than a slow endpoint: **the app cannot boot without
store access.** `api.py`'s lifespan runs ten steps that hit Postgres before the
first request is served — `_ensure_default_org`, `_ensure_default_workspace`,
`_sync_metastore`, `_validate_connections`, `_start_explorers` among them. Lose the
stores and you lose boot, not just a route.

And the arithmetic does not fit:

    19 platform stores, each its own connection per thread
    x  several threads per instance
    x  several instances, all cold at once on a deploy
    ------------------------------------------------------
       far more than the ~60 connection ceiling on a small Postgres

Holding connections is the whole point of a pool and is exactly what cannot be
afforded here. `_MAX_PER_THREAD` bounds ONE thread; nothing bounds the process, and
nothing can bound the fleet. A failed boot spawns more instances, which open more
connections, which is self-reinforcing.

**Do not "fix" this by raising the cap.** The lever that works on this deployment is
FEWER STORE OPERATIONS PER REQUEST, not cheaper ones — see the `/catalog/tree`
reconcile that wrote to the metastore on every read. Pooling was the wrong tool for
a fleet of short-lived processes sharing one small ceiling.

A related correction, recorded because the reasoning error is the reusable part:
connection exhaustion was dismissed early on by measuring 8 connections in use of
60 — a measurement taken while the pool was DISABLED, i.e. in the one state where
the mechanism under test cannot occur. The hypothesis was not tested; something
adjacent to it was.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

def _resolve_disabled() -> bool:
    """Off by default where it is known to break, on by default where it helps.

    This used to read one env var, so production stayed up only because that var
    happened to be set — and deleting it took the whole deployment down within
    minutes. A safety property that depends on someone remembering an env var is
    not a safety property; the code has to know where it is running.

    An explicit value still wins in BOTH directions, so a serverless deployment
    can opt back in to measure, and a server can opt out.
    """
    raw = os.getenv("AUGHOR_STORE_POOL_DISABLED", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return bool(os.getenv("VERCEL"))     # unset: safe where the fleet shares a ceiling


_DISABLED = _resolve_disabled()

#: Bounds, mirroring `aughor/db/pool.py` (`AUGHOR_POOL_TTL` / `AUGHOR_POOL_MAX_IDLE`).
#: "The thread keeps its connection forever" is fine for a long-lived server and wrong
#: for serverless: there are NINETEEN platform stores, each taking its own connection
#: per thread, and Postgres has a hard connection ceiling (~60 on smaller Supabase
#: plans). Nothing outside this module ever closed one — `close()` is a deliberate
#: no-op — so a deployment that spreads work across threads and instances could hold
#: connections open without limit. The data pool has bounded itself from the start;
#: this one did not, and that asymmetry was the defect.
_TTL = float(os.getenv("AUGHOR_STORE_POOL_TTL", "300"))
_MAX_PER_THREAD = max(1, int(os.getenv("AUGHOR_STORE_POOL_MAX", "8")))

_local = threading.local()


def _bucket() -> dict[str, Any]:
    b = getattr(_local, "conns", None)
    if b is None:
        b = {}
        _local.conns = b
    return b


def _stamps() -> dict[str, float]:
    """Last-used time per key, for this thread. Parallel to `_bucket`."""
    s = getattr(_local, "stamps", None)
    if s is None:
        s = {}
        _local.stamps = s
    return s


def _note_thread() -> None:
    """Count acquires, and how many of them came from a thread never seen before.

    The pool keys connections to a THREAD, so it can only ever hit if threads
    outlive a request. Production says they do not: an instance 1709s old still
    reported `store.schema_ddl.skipped=0`, and six requests to one endpoint opened
    eighteen connections without reusing one. That points at a fresh thread per
    invocation — but it is an inference, and the fix it implies is large.

    These two counters decide it directly:
      new ≈ acquires  → every acquire is on a brand-new thread; thread-local
                        pooling cannot work here and the mechanism must change.
      new ≪ acquires  → threads DO persist, the inference is wrong, and the real
                        cause of the misses is somewhere else entirely.

    "Have I been here before?" is answered from THREAD-LOCAL state, not from a set
    of thread identifiers. Two reasons, and the first is disqualifying: the OS
    recycles identifiers, so a genuinely new thread can inherit a dead one's id and
    be counted as already-seen — which would under-report exactly the thing being
    measured and wrongly clear the hypothesis. The second is that a set would grow
    by one entry per request forever if threads really are per-invocation, which is
    the very scenario under test.
    """
    fresh = not getattr(_local, "seen", False)
    if fresh:
        _local.seen = True
    _count("acquire", "store.pool")
    if fresh:
        _count("thread_new", "store.pool")


def _close_now(conn: Any) -> None:
    """Physically close, bypassing the no-op `close` the pool installed."""
    try:
        getattr(conn, "_real_close", conn.close)()
    except Exception:
        logger.debug("store pool: physical close failed", exc_info=True)


def _drop(bucket: dict, stamps: dict, key: str) -> None:
    conn = bucket.pop(key, None)
    stamps.pop(key, None)
    if conn is not None:
        _close_now(conn)


def _reap(bucket: dict, stamps: dict, now: float) -> int:
    """Close this thread's connections idle past the TTL. Returns how many."""
    stale = [k for k, t in stamps.items() if now - t > _TTL]
    for k in stale:
        _drop(bucket, stamps, k)
    return len(stale)


def _trim(bucket: dict, stamps: dict) -> int:
    """Hold at most `_MAX_PER_THREAD`, closing the least recently used first.

    The connection just handed out is the most recent, so it is never the one
    evicted — the caller is about to use it.
    """
    n = 0
    while len(bucket) > _MAX_PER_THREAD and stamps:
        _drop(bucket, stamps, min(stamps, key=lambda k: stamps[k]))
        n += 1
    return n


def _is_reusable(conn: Any) -> bool:
    """True when this connection can serve another operation on this thread.

    Anything unreadable counts as NOT reusable: the cost of rebuilding is one
    handshake, and the cost of handing back a broken connection is every subsequent
    store operation on this thread failing.
    """
    pg = getattr(conn, "_pg", None)
    if pg is None or getattr(pg, "closed", 1):
        return False
    try:
        import psycopg2.extensions as _ext
        status = pg.get_transaction_status()
    except Exception:
        return False
    if status == _ext.TRANSACTION_STATUS_IDLE:
        return True
    # INTRANS (someone left a transaction open) or INERROR (a statement failed and
    # every later one will too). Both are recoverable with a rollback; if that fails
    # the connection is not salvageable.
    try:
        pg.rollback()
        return pg.get_transaction_status() == _ext.TRANSACTION_STATUS_IDLE
    except Exception:
        logger.info("store pool: discarding a connection that would not roll back",
                    exc_info=True)
        return False


def _neutralize_close(conn: Any) -> None:
    """Keep `close()` from ending a pooled connection's life.

    133 call sites close their store connection; the five that matter most do not.
    Physically closing here would give the well-behaved stores no reuse at all, so
    close becomes a no-op and the thread keeps the connection. `commit`/`rollback`
    are untouched — those are the caller's transaction, not the connection's life.
    """
    if getattr(conn, "_pooled", False):
        return
    conn._pooled = True
    conn._real_close = conn.close
    conn.close = lambda: None       # noqa: E731 — deliberate lifetime override


def acquire(key: str, factory: Callable[[], Any]) -> Any:
    """This thread's connection for `key`, building one if it has none.

    Bounded on the way through: connections idle past `_TTL` are closed first, and
    the thread never holds more than `_MAX_PER_THREAD`. Both really close the
    socket — dropping the reference alone would leave the server side established
    until the object was collected, which is the leak this is here to prevent.
    """
    # Counted BEFORE the opt-out, deliberately. With the counter below this guard,
    # "the pool is switched off" and "the pool is on and never reuses" produced an
    # IDENTICAL reading — acquire=0 either way — and that ambiguity cost a wrong
    # diagnosis: missing reuse in production was read as evidence that every request
    # got a fresh thread, and nearly bought a rewrite of the pool as process-wide.
    # The pool was simply disabled. A diagnostic whose silence has two explanations
    # is not a diagnostic.
    _note_thread()
    if _DISABLED:
        _count("disabled", "store.pool")
        return factory()
    bucket = _bucket()
    stamps = _stamps()
    now = time.time()
    _reap(bucket, stamps, now)

    conn = bucket.get(key)
    if conn is not None:
        if _is_reusable(conn):
            stamps[key] = now
            return conn
        _drop(bucket, stamps, key)

    conn = factory()
    _neutralize_close(conn)
    bucket[key] = conn
    stamps[key] = now
    _trim(bucket, stamps)
    return conn


def ensure_once(conn: Any, ensure: Callable[[Any], None]) -> bool:
    """Run a store's schema DDL once per CONNECTION rather than once per operation.

    Every store opens with `CREATE TABLE IF NOT EXISTS` (plus indexes, plus
    `run_migrations`, plus a commit) before its first real statement. On SQLite that
    idiom is free — the statements never leave the process. On Postgres each one is a
    round trip, and stores replay the whole block on EVERY operation:

        metastore   9 statements per operation
        workspace  11
        dashboard   6
        savedquery  3
        org         2
        canvas      2

    Pooling the connection (see `acquire`) removed the handshake but not this, which is
    why production latency kept tracking the number of store operations after #311.
    Measured warm against production, the residual over the `/health` floor came to
    64-94 ms per statement on three independent endpoints — one round trip each:

        /connections   0.58s over floor,  ~9 statements
        /workspaces    2.78s over floor, ~42 statements
        /catalog/tree  3.68s over floor, ~39 statements

    The DDL is idempotent, so replaying it is harmless — merely expensive. Running it
    once per connection keeps the guarantee that any connection handed out has its
    tables, while paying for it once instead of per operation.

    SQLITE IS UNCHANGED, BY CONSTRUCTION
    ------------------------------------
    Two independent reasons, either one sufficient. `connect_store` does not pool
    SQLite, so every call gets a brand-new connection whose memo is empty. And a raw
    `sqlite3.Connection` has no `__dict__`, so the memo cannot be attached to one at
    all — that path runs `ensure` every time, exactly as before.

    Returns True when `ensure` actually ran, for tests.

    Both outcomes are counted into `/dev/stats` (`store.schema_ddl.ran` /
    `.skipped`), so the next production check reads the claim directly instead of
    inferring it from endpoint arithmetic — which is how the residual this fixes had
    to be found in the first place. In steady state `ran` plateaus at roughly
    stores × threads while `skipped` keeps climbing.
    """
    key = f"{ensure.__module__}.{ensure.__qualname__}"
    done = getattr(conn, "_ensured", None)
    if done is None:
        done = set()
        try:
            conn._ensured = done
        except AttributeError:
            # A raw sqlite3.Connection rejects attributes. Nothing to memoize on, and
            # nothing to gain — this connection was opened for this operation alone.
            _count("ran")
            ensure(conn)
            return True
    if key in done:
        _count("skipped")
        return False
    _count("ran")
    ensure(conn)
    # Added only on success: a failed CREATE must not mark the schema as present.
    done.add(key)
    return True


def _count(outcome: str, prefix: str = "store.schema_ddl") -> None:
    """Best-effort — a diagnostic counter must never be able to break a store."""
    try:
        from aughor.stats import stats
        stats.inc(f"{prefix}.{outcome}")
    except Exception:
        logger.debug("store pool: counter failed", exc_info=True)


def evict_all() -> int:
    """Drop this thread's pooled connections. Returns how many were closed.

    For tests and for any caller that must guarantee a fresh session (a schema
    change this process made through another path, say).
    """
    bucket = _bucket()
    n = 0
    for conn in list(bucket.values()):
        try:
            getattr(conn, "_real_close", conn.close)()
            n += 1
        except Exception:
            logger.debug("store pool: close during evict failed", exc_info=True)
    bucket.clear()
    _stamps().clear()
    return n


def pooled_count() -> int:
    """How many connections this thread holds — for tests and diagnostics."""
    return len(_bucket())
