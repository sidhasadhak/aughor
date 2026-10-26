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

**A labelled backup before every migration (Arc SV-1, ROADMAP §3.63).** No down runner
means the way back is a copy. Before the first pending migration of a store that holds
rows, the store is copied through SQLite's backup API — never the filesystem, which drops
what still sits in the WAL (`db/migrate.py`) — to
``backups/<file>.<UTC date>.v<old>-before-v<new>.bak`` beside it, numbered and never
overwriting, and the copy must answer ``PRAGMA quick_check`` before anything migrates.
A copy that cannot be made or does not check holds the migration back: the store opens at
the version it had, and ``migration_report()`` names it on ``/health``. Paid for on
2026-08-14, when a ledger migration committed its ALTERs and a 63,000-row UPDATE but left
``user_version`` behind, and came back only from a copy someone made by hand. Not copied,
and said: a store with no rows (nothing to lose), one in memory, one on Postgres
(``AUGHOR_DB_URL`` — that database's own backups are its operator's).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, NamedTuple, Optional

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


#: Where a store's pre-migration copies go: a folder of this name beside the store.
BACKUP_DIR = "backups"

_REPORT_LOCK = threading.Lock()
#: Arc SV-1 — what this process did before migrating, read by ``/health``: each copy made, and each
#: store whose migration was held back because its copy could not be made.
_BACKED_UP: list[dict] = []
_HELD_BACK: dict[str, str] = {}


class MigrationBackupFailed(RuntimeError):
    """The copy a migration waits for could not be made or did not check."""


def migration_report() -> dict:
    """What this process did before its migrations: the copies made, and the stores held back at their old version
    because a copy failed — ``ok`` is false while any is held back."""
    with _REPORT_LOCK:
        held = dict(_HELD_BACK)
        backed = list(_BACKED_UP)
    return {"ok": not held, "held_back": held, "backed_up": backed}


def _store_file(conn) -> Optional[Path]:
    """The file a SQLite connection's main database lives in; None in memory or a temporary database."""
    for _seq, name, file in conn.execute("PRAGMA database_list").fetchall():
        if name == "main":
            return Path(file) if file else None
    return None


def _holds_rows(conn: sqlite3.Connection) -> bool:
    """Whether any table of the store holds a row — a store with none has nothing a migration could lose."""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    for t in tables:
        quoted = '"' + t.replace('"', '""') + '"'
        if conn.execute(f"SELECT 1 FROM {quoted} LIMIT 1").fetchone():
            return True
    return False


def _claim_backup_path(folder: Path, stem: str) -> Path:
    """A new file in ``folder`` named ``stem.bak`` — or ``stem-2.bak``, ``stem-3.bak``, … — created exclusively, so two
    copies never share a name and none overwrites another."""
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        path = folder / (f"{stem}.bak" if n == 1 else f"{stem}-{n}.bak")
        try:
            with open(path, "x"):
                return path
        except FileExistsError:
            continue
    raise MigrationBackupFailed(f"no free backup name for {stem} in {folder}")


def backup_before_migrating(conn, store: str, current: int, target: int) -> Optional[Path]:
    """Copy ``conn``'s store before migrating it from ``current`` to ``target``; the copy's path, or None when the
    store is not copied (Postgres, in memory, or holding no rows — each logged). Raises ``MigrationBackupFailed`` when
    a copy was due and could not be made or did not answer ``quick_check``; the partial copy is removed."""
    if not isinstance(conn, sqlite3.Connection):
        logger.warning("migrations[%s]: v%d → v%d on Postgres — not copied here; that database's backups are its "
                       "operator's", store, current, target)
        return None
    path = None
    try:
        src = _store_file(conn)
        if src is None:
            return None
        # A damaged store raises here, while it is read — and a copy of a damaged store is no way back, so that is a
        # failed copy too: the store is held at its version and still opens (the ledger's own integrity probe says why).
        if not _holds_rows(conn):
            logger.info("migrations[%s]: v%d → v%d on a store with no rows — nothing to copy", store, current, target)
            return None
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = _claim_backup_path(src.parent / BACKUP_DIR, f"{src.name}.{day}.v{current}-before-v{target}")
        target_conn = sqlite3.connect(str(path))
        try:
            conn.backup(target_conn)
            # A WAL store's copy is a WAL file too, and any open of it grows -wal and -shm beside it; a backup is
            # one self-contained file, so the copy leaves WAL before it is closed.
            target_conn.execute("PRAGMA journal_mode=DELETE")
        finally:
            target_conn.close()
        check = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            verdict = check.execute("PRAGMA quick_check").fetchone()[0]
            copied_version = check.execute("PRAGMA user_version").fetchone()[0]
        finally:
            check.close()
        if str(verdict).lower() != "ok":
            raise MigrationBackupFailed(f"the copy answered quick_check with {verdict!r}")
        if copied_version != current:
            raise MigrationBackupFailed(f"the copy reads version {copied_version}, the store {current}")
    except Exception as exc:
        if path is not None:
            for leftover in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
                leftover.unlink(missing_ok=True)
        if isinstance(exc, MigrationBackupFailed):
            raise
        raise MigrationBackupFailed(f"{type(exc).__name__}: {exc}") from exc
    with _REPORT_LOCK:
        _BACKED_UP.append({"store": store, "path": str(path), "from": current, "to": target,
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        _HELD_BACK.pop(store, None)
    logger.info("migrations[%s]: copied to %s before v%d → v%d", store, path, current, target)
    return path


def run_migrations(conn: sqlite3.Connection, migrations: Iterable[Migration], *, store: str) -> int:
    """Bring ``conn`` up to the latest migration version. Forward-only + idempotent.

    Applies each migration whose ``version`` exceeds the DB's current
    ``PRAGMA user_version``, in ascending order, committing and bumping the marker
    after each. Returns the resulting version. A migration failure PROPAGATES (a
    broken schema evolution must be loud, not silently swallowed like the old idiom)
    and leaves ``user_version`` at the last successful step, so the next call retries
    from there.

    Arc SV-1: before the first pending migration the store is copied (``backup_before_migrating``). When the copy
    fails, nothing migrates — the version it had is returned and the store is named in ``migration_report()``.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    pending = [m for m in sorted(migrations, key=lambda x: x.version) if m.version > current]
    if not pending:
        return current
    try:
        backup_before_migrating(conn, store, current, pending[-1].version)
    except MigrationBackupFailed as exc:
        reason = (f"held at v{current}: the copy before migrating to v{pending[-1].version} failed — {exc}; "
                  "free space or fix the folder's permissions; the store's next open tries again")
        with _REPORT_LOCK:
            _HELD_BACK[store] = reason
        logger.critical("migrations[%s]: %s", store, reason)
        return current
    applied: list[tuple[int, str]] = []
    for m in pending:
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
