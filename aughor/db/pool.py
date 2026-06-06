"""Connection pool — reuse open database connections across requests.

Opening a connection is the dominant per-request latency for anything but a
local file: Postgres/MotherDuck do a TCP + auth handshake, Google Sheets does an
HTTP fetch, warehouses negotiate a session. Previously every request called
``open_connection_for`` → built a fresh connection → ``close()`` in a finally,
so that cost was paid on *every* query, catalog browse and schema fetch.

Design (correctness first — stale/cross-thread data is worse than slow):
  * **Exclusive checkout.** ``acquire`` removes an idle connection from the pool
    (or builds a new one). Two concurrent requests for the same logical
    connection therefore get *distinct* physical connections — a pooled
    connection is never shared by two threads at once. This matches the existing
    model where parallel reads already use ``make_reader()`` clones.
  * **Return on close.** While checked out, the connection's ``close()`` is
    swapped to return it to the pool instead of physically closing. Idempotent —
    a double ``close()`` returns it once, never twice (which would let two
    threads grab the same object).
  * **Idle TTL + cap.** Idle connections are reused within ``AUGHOR_POOL_TTL``
    seconds and capped at ``AUGHOR_POOL_MAX_IDLE`` per key; older/excess ones are
    really closed.
  * **Health check.** Connectors may expose ``is_healthy()`` (Postgres does);
    an unhealthy idle connection is discarded rather than handed out.
  * **Opt-out.** ``poolable = False`` on a connector class, or env
    ``AUGHOR_POOL_DISABLED=1`` globally, falls back to direct open/close.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import types
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)


def _flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


_DISABLED = _flag("AUGHOR_POOL_DISABLED")
_TTL = float(os.getenv("AUGHOR_POOL_TTL", "300"))
_MAX_IDLE = int(os.getenv("AUGHOR_POOL_MAX_IDLE", "8"))


class ConnectionPool:
    def __init__(self) -> None:
        # key -> list of (idle_since, connection)
        self._idle: dict[str, list[tuple[float, "DatabaseConnection"]]] = {}
        self._lock = threading.Lock()

    # ── checkout ──────────────────────────────────────────────────────────────
    def acquire(self, key: str, factory: Callable[[], "DatabaseConnection"]) -> "DatabaseConnection":
        if _DISABLED:
            return factory()

        now = time.time()
        with self._lock:
            bucket = self._idle.get(key)
            while bucket:
                idle_since, conn = bucket.pop()
                if now - idle_since < _TTL and self._healthy(conn):
                    self._mark_out(conn, key)
                    return conn
                # too old or dead → physically close and try the next idle one
                self._real_close(conn)

        conn = factory()
        if not getattr(conn, "poolable", True):
            return conn  # connector opted out — its own close() does the real close
        self._mark_out(conn, key)
        return conn

    # ── return ────────────────────────────────────────────────────────────────
    def release(self, conn: "DatabaseConnection") -> None:
        # Idempotent: only a checked-out connection goes back, and only once.
        if getattr(conn, "_pool_state", None) != "out":
            return
        conn._pool_state = "idle"  # type: ignore[attr-defined]
        key = getattr(conn, "_pool_key", None)
        if key is None or _DISABLED:
            self._real_close(conn)
            return
        with self._lock:
            bucket = self._idle.setdefault(key, [])
            if len(bucket) >= _MAX_IDLE:
                self._real_close(conn)
            else:
                bucket.append((time.time(), conn))

    # ── helpers ───────────────────────────────────────────────────────────────
    def _mark_out(self, conn: "DatabaseConnection", key: str) -> None:
        conn._pool_key = key            # type: ignore[attr-defined]
        conn._pool_state = "out"        # type: ignore[attr-defined]
        if not getattr(conn, "_pool_wrapped", False):
            # Capture the real close once, then route close() back to THIS pool
            # (bind the instance — not the module global — so each pool owns its
            # own returns; critical for tests and any multi-pool use).
            pool_self = self
            conn._pool_real_close = conn.close            # type: ignore[attr-defined]
            conn.close = types.MethodType(                # type: ignore[method-assign]
                lambda c: pool_self.release(c), conn
            )
            conn._pool_wrapped = True   # type: ignore[attr-defined]

    def _real_close(self, conn: "DatabaseConnection") -> None:
        try:
            rc = getattr(conn, "_pool_real_close", None)
            (rc or conn.close)()
        except Exception:
            logger.debug("pool: error closing connection", exc_info=True)

    def _healthy(self, conn: "DatabaseConnection") -> bool:
        check = getattr(conn, "is_healthy", None)
        if check is None:
            return True
        try:
            return bool(check())
        except Exception:
            return False

    # ── maintenance ───────────────────────────────────────────────────────────
    def clear(self, key: str | None = None) -> int:
        """Physically close idle connections (all, or one key). Returns count closed."""
        with self._lock:
            keys = list(self._idle) if key is None else [key]
            n = 0
            for k in keys:
                for _, conn in self._idle.pop(k, []):
                    self._real_close(conn)
                    n += 1
            return n

    def clear_conn(self, conn_id: str) -> int:
        """Evict every pooled connection for a conn_id (any schema). Call after
        the connection is deleted or its DSN/schema/files change."""
        with self._lock:
            prefix = f"{conn_id}|"
            keys = [k for k in self._idle if k == conn_id or k.startswith(prefix)]
            n = 0
            for k in keys:
                for _, conn in self._idle.pop(k, []):
                    self._real_close(conn)
                    n += 1
            return n

    def stats(self) -> dict:
        with self._lock:
            return {
                "disabled": _DISABLED,
                "ttl": _TTL,
                "max_idle": _MAX_IDLE,
                "keys": {k: len(v) for k, v in self._idle.items()},
                "idle_total": sum(len(v) for v in self._idle.values()),
            }


_POOL = ConnectionPool()


def acquire(key: str, factory: Callable[[], "DatabaseConnection"]) -> "DatabaseConnection":
    return _POOL.acquire(key, factory)


def clear_pool(key: str | None = None) -> int:
    return _POOL.clear(key)


def evict_conn(conn_id: str) -> int:
    """Evict all pooled physical connections for a conn_id (any schema)."""
    return _POOL.clear_conn(conn_id)


def pool_stats() -> dict:
    return _POOL.stats()
