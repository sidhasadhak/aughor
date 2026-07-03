"""One place that tunes every SQLite connection the platform opens.

Historically each store did a bare ``sqlite3.connect(path)`` — SQLite's default
``busy_timeout`` is 0, so the instant two writers overlap the second gets an
immediate ``SQLITE_BUSY``. In the kernel that surfaces as a tolerated heartbeat
write failing, the job later swept as a false orphan and marked FAILED with a
misleading cause (DATA-02 in the 2026-07-03 architecture review).

``tune(conn)`` is called right after every ``sqlite3.connect`` so the fix is
auditable by grep — a partial application is visible as a connect site with no
adjacent ``tune``.

- ``journal_mode=WAL``   — readers don't block the writer (harmless no-op on
  ``:memory:``, which stays in ``memory`` journal mode).
- ``busy_timeout=5000``  — wait up to 5s for a lock instead of failing instantly.
- ``synchronous=NORMAL`` — safe with WAL, materially faster than FULL.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

BUSY_TIMEOUT_MS = 5000


def resolve_db_path(env_var: str, default: Path | str) -> Path:
    """Resolve a store's SQLite path, honouring an ``AUGHOR_*_DB`` env override.

    Mirrors the registry/ledger convention (``AUGHOR_REGISTRY_DB`` /
    ``AUGHOR_SYSTEM_DB``): the env var wins when set, else the hard-coded
    default. The test conftest points these at a temp dir so the suite can
    NEVER mutate the live ``data/`` stores (OPS-02 / DATA-01) — and on-prem
    operators get per-store path control for free.
    """
    return Path(os.environ.get(env_var) or default)


def tune(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Apply the standard PRAGMAs to a freshly-opened SQLite connection.

    Returns the same connection so call sites can wrap inline:
    ``conn = tune(sqlite3.connect(path))``.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
