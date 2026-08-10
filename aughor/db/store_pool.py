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
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

_DISABLED = os.getenv("AUGHOR_STORE_POOL_DISABLED", "").strip().lower() in ("1", "true", "yes", "on")

_local = threading.local()


def _bucket() -> dict[str, Any]:
    b = getattr(_local, "conns", None)
    if b is None:
        b = {}
        _local.conns = b
    return b


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
    """This thread's connection for `key`, building one if it has none."""
    if _DISABLED:
        return factory()
    bucket = _bucket()
    conn = bucket.get(key)
    if conn is not None:
        if _is_reusable(conn):
            return conn
        bucket.pop(key, None)
        try:
            getattr(conn, "_real_close", conn.close)()
        except Exception:
            logger.debug("store pool: discarding an unusable connection failed", exc_info=True)
    conn = factory()
    _neutralize_close(conn)
    bucket[key] = conn
    return conn


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
    return n


def pooled_count() -> int:
    """How many connections this thread holds — for tests and diagnostics."""
    return len(_bucket())
