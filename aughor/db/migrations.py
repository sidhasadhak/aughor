"""A small, forward-only SQLite migration runner keyed on ``PRAGMA user_version``.

DATA-05 in the 2026-07-03 review: schema evolution was an ad-hoc
``CREATE TABLE IF NOT EXISTS`` plus a loop of ``try: ALTER ADD COLUMN except: pass``
with no version tracking — every ``_ensure_schema`` re-attempted (and swallowed)
every historical ALTER, and nothing recorded what a DB had been migrated through.

This replaces that with an ordered, named, version-gated migration list:

  - The BASE schema stays a ``CREATE TABLE IF NOT EXISTS`` (conceptually version 1;
    ``sqlite_util.tune`` stamps ``user_version=1`` on first touch).
  - Each subsequent schema change is a ``Migration(version>=2, name, apply)``.
  - ``run_migrations`` applies only migrations whose version exceeds the DB's
    current ``user_version``, in order, bumping the marker after each — so once a DB
    is at the latest version NO ALTERs are attempted (a correctness *and* perf win
    over the old every-call retry-and-swallow).

FORWARD-ONLY + ADDITIVE INVARIANT — this is DATA-05's answer to "no downgrade
path": migrations MUST be backward-compatible (additive columns/tables only, never
a drop or rename), so rolling the *code* back after a migration ships is always
safe — older code simply ignores the new column. A genuinely destructive change is
done as a new column + dual-write/backfill, never an in-place rewrite. There is
deliberately no automatic ``down`` runner: SQLite can't cleanly drop columns before
3.35, and a destructive down-migration is exactly what the additive invariant
exists to avoid.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Iterable, NamedTuple

logger = logging.getLogger(__name__)


class Migration(NamedTuple):
    version: int                                   # target user_version (>= 2)
    name: str                                      # human-readable; shows in logs
    apply: Callable[[sqlite3.Connection], None]    # must be additive + idempotent


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, coldef: str) -> None:
    """Idempotent ``ALTER TABLE ... ADD COLUMN`` — no-op when the column exists.

    The workhorse of additive migrations; safe against any DB state (fresh, or one
    that already grew the column via the old ad-hoc idiom)."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")


def run_migrations(conn: sqlite3.Connection, migrations: Iterable[Migration], *, store: str) -> int:
    """Bring ``conn`` up to the latest migration version. Forward-only + idempotent.

    Applies each migration whose ``version`` exceeds the DB's current
    ``PRAGMA user_version``, in ascending order, committing and bumping the marker
    after each. Returns the resulting version. A migration failure PROPAGATES (a
    broken schema evolution must be loud, not silently swallowed like the old idiom)
    and leaves ``user_version`` at the last successful step, so the next call retries
    from there.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    applied: list[tuple[int, str]] = []
    for m in sorted(migrations, key=lambda x: x.version):
        if m.version <= current:
            continue
        try:
            m.apply(conn)
            conn.execute(f"PRAGMA user_version = {int(m.version)}")
            conn.commit()
        except Exception:
            logger.error("migration failed [%s v%d: %s] — user_version stays %d",
                         store, m.version, m.name, current)
            raise
        applied.append((m.version, m.name))
        current = m.version
    if applied:
        logger.info("migrations[%s]: applied %s → user_version=%d", store, applied, current)
    return current
