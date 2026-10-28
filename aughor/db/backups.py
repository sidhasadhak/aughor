"""Rolling backups of the platform's own state, taken inside the API (Arc SV-2, ROADMAP §3.63).

Before this, no store was ever backed up on a schedule. The recovery recipe was `sqlite3 .recover` from the damaged
file (`kernel/ledger.py`), because no good copy existed to return to; three `system.db.corrupt*.bak` files from August
sit in the state directory to prove it. Arc SH makes it urgent: once people type into sheets, the platform holds data
that exists nowhere else.

**Inside the API process, never a second one.** Every corruption of `system.db` so far was two processes on one WAL
(`db/serving.py`). The backup is a job on the API's own hourly housekeeping clock (`monitors/scheduler.py`) and refuses
to run in any process that is not the one serving the state directory. Its connections are read-only and share the
serving process's WAL index; it writes nothing into a store it copies.

**What is copied.** Every SQLite store in `state_dir()` but `checkpoints.db`, through SQLite's backup API — never a file
copy, which drops whatever still sits in the WAL (`db/migrate.py` paid for that lesson) — each in one read transaction,
so the row counts and the copy see the same snapshot. The copy leaves WAL mode, must answer `quick_check` and hold the
rows the source held, and is then gzipped. Every other file — the JSON, JSONL and YAML stores, the uploads, the
documents, the sheets people bring — is copied byte for byte. Anything deliberately left out is NAMED in the manifest
with its reason (`_why_not`): DuckDB files (a byte copy of an open one is not safe; the platform's own are a cache that
expires, demo warehouses seeded again on demand, and a sheet's projection rebuilt from its files and edits), the old
hand-made backup folders, the backups themselves, `luxexperience_warehouse` (a person's folder the platform never
touches), the secret key, logs, the server's markers, SQLite's sidecars (carried by the backup API) and a store on
Postgres (`AUGHOR_DB_URL` — that database's backups are its operator's). The embedded vector index (`qdrant/`) IS
copied: its collections are SQLite files, and restoring them saves embedding every document again.

**Only when something changed.** Each source is fingerprinted — size, mtime and inode of the file, and of a store's
non-empty `-wal`, because a WAL store's database file does not change while its writes sit in the WAL (measured on the
live install: `audit.db` 23:55, its `-wal` 01:53). The fingerprint is read BEFORE the copy, so a write during the copy
makes the next run copy again rather than miss it. An unchanged source is hard-linked from the previous backup, so each
folder is a complete point in time and pruning one never breaks another. When nothing changed, no backup is taken and
`last_run.json` says so — a quiet install is not a failing one.

**Disk.** Measured on the live install 2026-10-27 (by listing only): `system.db` 391 MB, `audit.db` 360 MB,
`automations.db` 176 MB, the rest small, ~80 GiB free on a 460 GiB disk. Copied every hour and kept as `retention.py`
decides, uncompressed that would be ~45 GB. A ledger-shaped 340 MB test store gzips to 32% at level 1 in 3.1 s, 27% at
level 6 in 9.8 s; level 1 is the trade taken — a fifth more disk for a third of the time spent beside the API's own
work. A backup is skipped, and `/health` says so, when taking it would leave less free than the floor: the larger of
10 GiB and a tenth of the disk, or ``AUGHOR_BACKUPS_FREE_FLOOR_GB``.

**Layout.** `state_dir()/backups/<UTC stamp>[.<label>]/` — `stores/<rel>.gz`, `files/<rel>` and `manifest.json`, which
is written last: a folder without one is unfinished, ignored by every reader and removed by the next prune. SV-1's
copies before a migration share the folder (`<file>.<date>.v<old>-before-v<new>.bak`) and are kept 30 days.

**Restore** (`aughor restore <stamp>`, after Grist's `HostedStorageManager.replace`): refused while the API serves;
every stored file is checked against the manifest and staged before anything live moves; every removal recorded after
the backup that it would bring back is listed — tombstones, audited removals, connections, files — and the person is
asked; a labelled copy of the present is taken; then the live files move aside, the staged ones take their place and
are checked again, and on any failure the originals go back. Two records are never restored over, because they are the
account of what happened: `audit.db` (the SQL audit log) stays as it is, and the model-call log (`session_events`, in
`system.db`) is carried from the present into the restored ledger. A restore is a new state with the old one kept as a
labelled backup, never a rewind.

Part of the platform since 2026-10-28 (ROADMAP §3.65; it was the flag `state.backups`).

**Falsifier** (§3.63): the API's p95 on `/health` or `/catalog/tree` rising more than 20% while a backup runs → move
backups to a quiet hour.
"""
from __future__ import annotations

import errno
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from aughor.db.migrations import BACKUP_DIR
from aughor.db.retention import AUGHOR, LABELLED_ONLY, should_keep

logger = logging.getLogger(__name__)

MANIFEST = "manifest.json"
LAST_RUN = "last_run.json"
#: The manifest's envelope. A reader refuses a manifest newer than it understands rather than half-restoring it
#: (registered with the other envelopes in `kernel/freshness.py`).
MANIFEST_FORMAT = 1
#: A backup folder's name: its UTC time, to the second.
STAMP_PATTERN = "%Y-%m-%dT%H%M%SZ"
#: The label of the copy of the present a restore takes first; kept 30 days like any labelled backup.
BEFORE_RESTORE = "before-restore"

#: The clock: every hour, the first a few minutes after the server starts — an API restarted more often than hourly
#: would otherwise never reach its first tick. A run within 55 minutes of the last check does nothing, so a restart
#: never takes a second backup inside the hour.
EVERY = timedelta(hours=1)
FIRST_RUN_AFTER = timedelta(minutes=5)
NOT_DUE_WITHIN = timedelta(minutes=55)
#: `/health` goes degraded when the last check is older than this: the clock has stopped.
STALE_AFTER = timedelta(hours=2)

FREE_FLOOR_ENV = "AUGHOR_BACKUPS_FREE_FLOOR_GB"
_GIB = 1024 ** 3
_FLOOR_MIN = 10 * _GIB
_FLOOR_SHARE = 0.10
#: Measured (module docstring): level 1 is 32% of a ledger-shaped store in a third of level 6's time.
GZIP_LEVEL = 1

#: The copy reads a live store; a writer holding a lock is waited for rather than failed on.
_BUSY_TIMEOUT_MS = 30_000
_SQLITE_MAGIC = b"SQLite format 3\x00"
_SIDECARS = ("-wal", "-shm", "-journal")

_STORES = "stores"
_FILES = "files"

#: A finished backup's folder name: the stamp, a collision number, a label.
_FOLDER_RX = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{6}Z)(?:-(?P<n>\d+))?(?:\.(?P<label>[a-z0-9-]+))?$")
#: SV-1's copy before a migration (`migrations.backup_before_migrating`).
_SV1_RX = re.compile(r"^(?P<store>.+)\.\d{4}-\d{2}-\d{2}\.v(?P<old>\d+)-before-v(?P<new>\d+)(?:-\d+)?\.bak$")

# ── what is never copied, and why ──────────────────────────────────────────────────

#: Entries at the top of the state directory that are never copied. The reasons are written for the person reading a
#: manifest or `aughor backups`, so they say what the thing is, not where in the code it lives.
_NOT_COPIED_TOP: dict[str, str] = {
    "checkpoints.db": "resume points for runs in flight; a run restored to an old point would resume into a state that "
                      "has moved on (decided 2026-10-27)",
    BACKUP_DIR: "the backups themselves",
    "luxexperience_warehouse": "a person's own warehouse folder, which the platform never touches",
    ".aughor_key": "the secret key: never copied and never restored; it is never rewritten, so every backup's stored "
                   "secrets decrypt with the key in place — keep your own copy of it somewhere safe",
    ".serving.pid": "a marker of the running server, not state",
    ".restart.lock": "a marker of the running server, not state",
}
#: Folders a person made by hand before backups existed.
_HAND_MADE = ("_backup_", "_wipe_backup_", "_rerun_backup_")
_WHY_HAND_MADE = "a backup taken by hand — backups do not copy backups"
#: Paths below the top, by their path relative to the state directory.
_NOT_COPIED_REL: dict[str, str] = {
    "qdrant/.lock": "the vector index's lock, held while the server runs",
}
#: Names never copied wherever they are.
_NOT_COPIED_NAMES: dict[str, str] = {
    ".DS_Store": "the Mac's folder settings, not state",
}
_WHY_DUCKDB = ("a DuckDB file: a byte copy of an open one is not safe. The platform's own are a cache that expires or "
               "demo warehouses seeded again on demand; one a person brought is their file — keep the original")
_WHY_PROJECTION = ("a sheet's DuckDB projection or the stamps it was built at — rebuilt from the sheet's files and its "
                   "edits whenever they disagree with them, as they do after a restore")
_WHY_SIDECAR = "carried with its database by SQLite's backup"
_WHY_BAK = "a copy already — taken before a migration or by hand; backups do not copy copies"
_WHY_LOG = "a log the server writes as it runs — not state; copied, it would make every hour look changed"
_WHY_LINK = "a link: what it points at is not part of this folder"
_WHY_SPECIAL = "not a regular file"
#: The sheets' projection and the stamps it was built at (`sheets/projection.py`). The stamps go with the projection: a
#: restored stamp would match the restored stores and leave the live, newer projection standing unrebuilt.
_PROJECTION_RX = re.compile(r"^sheets/[^/]+/projection\.(?:duckdb(?:\.[a-z]+)?|marks\.json|marks\.tmp)$")
#: Files whose ninth to twelfth bytes may read DUCK by chance — a person's text is never taken for a DuckDB file.
_TEXT_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".md", ".json", ".jsonl", ".yaml", ".yml", ".sql", ".html",
                            ".xml", ".parquet", ".xlsx", ".xls"})

# ── what a restore never puts back ────────────────────────────────────────────────

#: Restored over never: the append-only record of what happened. The removal default (2026-10-11, `db/purge.py`
#: `KEPT_ON_DELETE`) keeps the same two records for the same reason.
NEVER_RESTORED: dict[str, str] = {
    "audit.db": "the SQL audit log — every statement run against a warehouse and by whom; append-only, kept as it is",
}
#: Tables carried from the present store into the restored one, so a restore never rolls them back.
CARRIED_FORWARD: dict[str, dict[str, str]] = {
    "system.db": {"session_events": "the model-call log — every model call and what it cost; the present's rows are "
                                    "carried into the restored ledger"},
}
#: Actions audited by `govern.audit` whose approval removed something a restore would bring back.
#: (`ontology.delete_override` is not among them: the overrides live in the checkout's `data/`, which no backup holds.)
_REMOVAL_ACTIONS = frozenset({"connection.delete", "connection.schema.delete", "connection.table.delete",
                              "metric.delete"})
_REGISTRY_FILE = "connections.db"
_LEDGER_FILE = "system.db"
_TOMBSTONE_NAME = "_removed_seeds.json"


class BackupCheckFailed(RuntimeError):
    """A copy that did not answer `quick_check`, or holds other rows than its source."""


@dataclass
class Source:
    rel: str            # posix path relative to the state directory
    path: Path
    kind: str           # "sqlite" | "file"
    fingerprint: dict


@dataclass
class Backup:
    """A finished backup's folder — read from its name, without opening the manifest."""
    name: str
    folder: Path
    stamp: str
    taken_at: datetime
    label: Optional[str]

    def manifest(self) -> dict:
        data = json.loads((self.folder / MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or int(data.get("format") or 0) > MANIFEST_FORMAT:
            raise ValueError(f"the manifest of {self.name} is a format newer than this version of Aughor reads "
                             f"({data.get('format') if isinstance(data, dict) else '?'} > {MANIFEST_FORMAT})")
        return data


@dataclass
class TakeOutcome:
    """A typed verdict: "taken", "unchanged", "skipped_space" and "failed" are recorded in `last_run.json`;
    "busy", "not_due" and "not_serving" are not, because nothing was checked."""
    status: str
    reason: str = ""
    stamp: Optional[str] = None
    folder: Optional[Path] = None
    copied: int = 0
    linked: int = 0
    failed: list = field(default_factory=list)
    pruned: list = field(default_factory=list)
    bytes_new: int = 0


@dataclass
class RestoreOutcome:
    status: str                       # "restored" | "refused" | "declined" | "failed"
    reason: str = ""
    backup: Optional[str] = None
    before_restore: Optional[str] = None
    restored: list = field(default_factory=list)
    set_aside: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    kept_aside: Optional[str] = None          # where a present file the restore could not keep a copy of is kept


# ── small helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime(STAMP_PATTERN)


def _parse_stamp(stamp: str) -> datetime:
    return datetime.strptime(stamp, STAMP_PATTERN).replace(tzinfo=timezone.utc)


def _try_stamp(stamp: str) -> Optional[datetime]:
    """A folder's stamp as a time; None for a name that only looks like one (a thirteenth month)."""
    try:
        return _parse_stamp(stamp)
    except ValueError:
        return None


def _root() -> Path:
    from aughor.db.paths import state_dir
    return state_dir()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, data: dict) -> None:
    """Written beside, then renamed over: a reader sees the old file or the new one, never half of one."""
    tmp = path.with_name(path.name + ".writing")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _ro_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _connect_ro(path: Path) -> sqlite3.Connection:
    """Read-only, autocommit, patient: a backup never writes into what it reads, and waits for a writer's lock."""
    conn = sqlite3.connect(_ro_uri(path), uri=True, isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    return conn


def _table_rows(conn: sqlite3.Connection, schema: str = "main") -> dict[str, int]:
    """``{table: rows}``. Virtual tables are left out — counting one needs its module loaded, and its rows live in
    shadow tables that are counted anyway."""
    tables = [r[0] for r in conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND COALESCE(sql, '') NOT LIKE 'CREATE VIRTUAL TABLE%' ORDER BY name").fetchall()]
    return {t: conn.execute(f'SELECT COUNT(*) FROM {schema}."{t.replace(chr(34), chr(34) * 2)}"').fetchone()[0]
            for t in tables}


def _header(path: Path) -> bytes:
    try:
        with path.open("rb") as fh:
            return fh.read(16)
    except OSError:
        return b""


def _is_duckdb(path: Path) -> bool:
    return path.suffix == ".duckdb" or _header(path)[8:12] == b"DUCK"


def _stat(path: Path) -> list:
    st = path.stat()
    return [st.st_size, st.st_mtime_ns, st.st_ino]


def source_fingerprint(path: Path, kind: str) -> dict:
    """Whether a source's copy in the last backup is out of date (registered in `kernel/freshness.py`) — size, mtime
    and inode, not a hash: hashing every byte each hour would cost what the copy costs. What says a source changed. A store's ``-wal`` counts only when it holds frames: an empty one appears whenever
    a reader opens a WAL store, and holds nothing."""
    fp: dict = {"file": _stat(path)}
    if kind == "sqlite":
        try:
            st = Path(f"{path}-wal").stat()
            fp["wal"] = [st.st_size, st.st_mtime_ns] if st.st_size else None
        except FileNotFoundError:
            fp["wal"] = None
    return fp


def _source_bytes(source: Source) -> int:
    fp = source.fingerprint
    return fp["file"][0] + ((fp.get("wal") or [0])[0])


def free_floor(total_bytes: int) -> int:
    """The free space a backup must leave: ``AUGHOR_BACKUPS_FREE_FLOOR_GB``, or the larger of 10 GiB and a tenth of
    the disk."""
    raw = os.environ.get(FREE_FLOOR_ENV, "").strip()
    if raw:
        try:
            return max(0, int(float(raw) * _GIB))
        except ValueError:
            logger.warning("backups: %s=%r is not a number of GB — using the default floor", FREE_FLOOR_ENV, raw)
    return max(_FLOOR_MIN, int(total_bytes * _FLOOR_SHARE))


def _gb(n: int) -> str:
    return f"{n / _GIB:.1f} GB"


# ── the population ─────────────────────────────────────────────────────────────────

def _why_not(rel: str, name: str, top: bool, siblings: set[str], folder: Path) -> Optional[str]:
    """Why ``rel`` is not copied — or None when it is."""
    if top:
        if name in _NOT_COPIED_TOP:
            return _NOT_COPIED_TOP[name]
        if name.startswith(_HAND_MADE):
            return _WHY_HAND_MADE
    if rel in _NOT_COPIED_REL:
        return _NOT_COPIED_REL[rel]
    if name in _NOT_COPIED_NAMES:
        return _NOT_COPIED_NAMES[name]
    if _PROJECTION_RX.match(rel):
        return _WHY_PROJECTION
    for suffix in _SIDECARS:
        if name.endswith(suffix) and name[: -len(suffix)] in siblings:
            return _WHY_SIDECAR
    if name.endswith(".duckdb") or ".duckdb." in name:      # the file, its `.wal`, the `.tmp` folder it spills into
        return _WHY_DUCKDB
    if name.endswith(".wal") and name[:-4] in siblings and _is_duckdb(folder / name[:-4]):
        return _WHY_DUCKDB
    # At the top only: below it, a `.log` or a `.bak` is as likely a file a person uploaded as anything else.
    if top and name.endswith(".bak"):
        return _WHY_BAK
    if top and name.endswith(".log"):
        return _WHY_LOG
    return None


def scan(root: Path) -> tuple[list[Source], list[dict]]:
    """``(what is copied, what is not and why)`` under the state directory. Never descends into a folder it does not
    copy, and never follows a link."""
    sources: list[Source] = []
    not_copied: list[dict] = []
    if not root.is_dir():
        return sources, not_copied

    def walk(folder: Path, rel_dir: str) -> None:
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as exc:
            not_copied.append({"path": rel_dir or ".", "why": f"could not be listed ({exc})"})
            return
        siblings = {e.name for e in entries}
        for e in entries:
            rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
            why = _why_not(rel, e.name, not rel_dir, siblings, folder)
            if why is None and e.is_symlink():
                why = _WHY_LINK
            if why is not None:
                not_copied.append({"path": rel, "why": why})
                continue
            if e.is_dir(follow_symlinks=False):
                walk(Path(e.path), rel)
                continue
            if not e.is_file(follow_symlinks=False):
                not_copied.append({"path": rel, "why": _WHY_SPECIAL})
                continue
            path = Path(e.path)
            head = _header(path)
            if head[8:12] == b"DUCK" and path.suffix.lower() not in _TEXT_SUFFIXES:
                not_copied.append({"path": rel, "why": _WHY_DUCKDB})   # a DuckDB file by another name
                continue
            kind = "sqlite" if head == _SQLITE_MAGIC else "file"
            try:
                sources.append(Source(rel, path, kind, source_fingerprint(path, kind)))
            except FileNotFoundError:
                logger.debug("backups: %s went between the listing and the stat — nothing to copy", rel)

    walk(root, "")
    return sources, not_copied


#: Environment variables that point a store or a folder somewhere — the population of "outside the state folder".
_PLACE_ENV_RX = re.compile(r"^AUGHOR_[A-Z0-9_]+_(?:DB|DIR|PATH|FILE|ROOT|REGISTRY)$")


def _elsewhere(root: Path) -> list[dict]:
    """What lives outside the state directory and so is not in any backup — said, not implied."""
    out: list[dict] = []
    from aughor.db.backend import DB_URL_ENV, is_postgres
    if is_postgres():
        out.append({"path": DB_URL_ENV, "why": "the platform's stores are on Postgres — that database's backups are "
                                              "its operator's"})
    base = root.resolve()
    for var in sorted(os.environ):
        if not _PLACE_ENV_RX.match(var) or var == "AUGHOR_STATE_DIR":
            continue
        target = Path(os.environ[var]).expanduser()
        try:
            resolved = target.resolve()
            inside = resolved == base or base in resolved.parents or not resolved.exists()
        except (OSError, RuntimeError) as exc:
            out.append({"path": f"{var}={target}", "why": f"could not be resolved ({exc}), so not in any backup"})
            continue
        if not inside:
            out.append({"path": f"{var}={target}", "why": "outside the state folder, so not in any backup"})
    return out


# ── reading what is there ──────────────────────────────────────────────────────────

def backups_dir(root: Optional[Path] = None) -> Path:
    """Where the backups live: ``backups/`` in the state directory, beside SV-1's copies before a migration."""
    return (root or _root()) / BACKUP_DIR



def list_backups(root: Optional[Path] = None) -> list[Backup]:
    """Every FINISHED backup, newest first — a folder with no manifest is unfinished and is not one."""
    bdir = backups_dir(root)
    found: list[tuple[tuple, Backup]] = []
    try:
        entries = list(os.scandir(bdir))
    except OSError:
        return []
    for e in entries:
        m = _FOLDER_RX.match(e.name)
        if not m or not e.is_dir(follow_symlinks=False) or not (Path(e.path) / MANIFEST).is_file():
            continue
        taken = _try_stamp(m.group("stamp"))
        if taken is None:
            continue
        found.append(((m.group("stamp"), int(m.group("n") or 1)),
                      Backup(e.name, Path(e.path), m.group("stamp"), taken, m.group("label"))))
    return [b for _, b in sorted(found, key=lambda x: x[0], reverse=True)]


def read_last_run(root: Optional[Path] = None) -> Optional[dict]:
    return _read_json(backups_dir(root) / LAST_RUN)


def resolve(name: str, root: Optional[Path] = None) -> Backup:
    """The finished backup ``name`` names — its folder name, or a stamp prefix only one folder has."""
    backups = list_backups(root)
    exact = [b for b in backups if b.name == name]
    if exact:
        return exact[0]
    prefixed = [b for b in backups if b.name.startswith(name)]
    if len(prefixed) == 1:
        return prefixed[0]
    if not prefixed:
        raise LookupError(f"no finished backup is called {name!r} — `aughor backups` lists them")
    raise LookupError(f"{name!r} names {len(prefixed)} backups ({', '.join(b.name for b in prefixed[:5])}) — "
                      "give the whole name")


# ── taking one ─────────────────────────────────────────────────────────────────────

_LOCK = threading.Lock()


def _claim_folder(bdir: Path, at: datetime, label: Optional[str]) -> Path:
    """A new folder named by the stamp, created exclusively — never two backups in one folder."""
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(at)
    for n in range(1, 100):
        name = stamp + (f"-{n}" if n > 1 else "") + (f".{label}" if label else "")
        folder = bdir / name
        try:
            folder.mkdir(mode=0o700)          # holds every store, encrypted secrets included: the owner's alone
        except FileExistsError:
            logger.debug("backups: %s is taken — trying the next number", name)
        else:
            return folder
    raise RuntimeError(f"no free backup folder name for {stamp} in {bdir}")


def _copy_store(source: Source, folder: Path) -> dict:
    """Through SQLite's backup API in one read transaction, checked, then gzipped."""
    stored = f"{_STORES}/{source.rel}.gz"
    dst = folder / stored
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name[:-3] + ".copying")
    try:
        src = _connect_ro(source.path)
        try:
            # One read transaction: the counts below and the backup see the same snapshot, so a write landing in
            # between cannot make a sound copy look short (the backup step reuses the transaction it finds open).
            src.execute("BEGIN")
            rows = _table_rows(src)
            version = src.execute("PRAGMA user_version").fetchone()[0]
            target = sqlite3.connect(str(tmp))
            try:
                target.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
                src.backup(target)
                # A WAL store's copy is a WAL file too; one self-contained file is what a backup is.
                target.execute("PRAGMA journal_mode=DELETE")
            finally:
                target.close()
            src.execute("ROLLBACK")
        finally:
            src.close()
        check = _connect_ro(tmp)
        try:
            verdict = check.execute("PRAGMA quick_check").fetchone()[0]
            copied_rows = _table_rows(check)
            copied_version = check.execute("PRAGMA user_version").fetchone()[0]
        finally:
            check.close()
        if str(verdict).lower() != "ok":
            raise BackupCheckFailed(f"the copy answered quick_check with {verdict!r}")
        if copied_rows != rows:
            short = sorted(t for t in set(rows) | set(copied_rows) if rows.get(t) != copied_rows.get(t))
            raise BackupCheckFailed(f"the copy's rows differ from the store's in {', '.join(short[:5])}")
        if copied_version != version:
            raise BackupCheckFailed(f"the copy reads version {copied_version}, the store {version}")
        with tmp.open("rb") as fi, gzip.open(dst, "wb", compresslevel=GZIP_LEVEL) as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
        os.chmod(dst, source.path.stat().st_mode & 0o777)
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    finally:
        tmp.unlink(missing_ok=True)
        for side in _SIDECARS:
            Path(f"{tmp}{side}").unlink(missing_ok=True)
    return {"kind": "sqlite", "stored": stored, "how": "copied", "sha256": _sha256(dst),
            "bytes": dst.stat().st_size, "source_bytes": _source_bytes(source), "rows": rows,
            "user_version": version, "fingerprint": source.fingerprint}


def _copy_file(source: Source, folder: Path) -> dict:
    """Byte for byte, mode and mtime kept. A file that changes while it is copied is copied again, twice at most —
    and a third change is said, not hidden."""
    stored = f"{_FILES}/{source.rel}"
    dst = folder / stored
    dst.parent.mkdir(parents=True, exist_ok=True)
    note = None
    fingerprint = source.fingerprint
    for _attempt in range(3):
        fingerprint = source_fingerprint(source.path, "file")
        shutil.copy2(source.path, dst)
        if source_fingerprint(source.path, "file") == fingerprint:
            break
    else:
        note = "it changed while it was copied, three times — the copy may end mid-write"
    entry = {"kind": "file", "stored": stored, "how": "copied", "sha256": _sha256(dst), "bytes": dst.stat().st_size,
             "source_bytes": fingerprint["file"][0], "fingerprint": fingerprint}
    if note:
        entry["note"] = note
    return entry


def _unchanged(source: Source, before: Optional[dict], prev: Optional[Backup]) -> bool:
    """Whether ``source`` is the same as in the previous backup, and that backup still holds its copy."""
    if prev is None or not before or before.get("kind") != source.kind or before.get("fingerprint") != source.fingerprint:
        return False
    try:
        return (prev.folder / before["stored"]).stat().st_size == before["bytes"]
    except (OSError, KeyError):
        return False


def _link(before: dict, prev: Backup, folder: Path) -> dict:
    """The previous backup's copy, hard-linked: one file on disk, a complete point in time in each folder. Where the
    disk cannot link, the copy is copied, and the entry says so."""
    src, dst = prev.folder / before["stored"], folder / before["stored"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    entry = {k: v for k, v in before.items() if k not in ("how", "from")}
    try:
        os.link(src, dst)
        entry["how"] = "linked"
    except OSError:
        shutil.copy2(src, dst)
        entry["how"] = "carried"              # a copy of the previous backup's copy: this disk does not hard-link
    entry["from"] = before.get("from") or prev.name
    return entry


def _bytes_on_disk(root: Path) -> tuple[int, int]:
    """``(bytes, backups)`` the finished backups hold, a hard-linked file counted once."""
    seen: set[tuple[int, int]] = set()
    total = 0
    backups = list_backups(root)
    for b in backups:
        for dirpath, _dirs, files in os.walk(b.folder):
            for f in files:
                try:
                    st = os.stat(os.path.join(dirpath, f))
                except OSError:
                    st = None                 # pruned while being counted
                if st is None:
                    continue
                key = (st.st_dev, st.st_ino)
                if key not in seen:
                    seen.add(key)
                    total += st.st_size
    return total, len(backups)


def prune(root: Optional[Path] = None, now: Optional[datetime] = None) -> list[str]:
    """Drop what retention does not keep — whole folders — and every unfinished one; and SV-1's copies before a
    migration once their 30 days are up. Returns what went. Called with the backup lock held, so no folder being
    written can be taken for an unfinished one."""
    root = root or _root()
    bdir = backups_dir(root)
    now = now or _now()
    gone: list[str] = []
    finished = list_backups(root)
    for b, keep in zip(finished, should_keep([(b.taken_at, b.label) for b in finished], AUGHOR, now=now)):
        if not keep:
            shutil.rmtree(b.folder, ignore_errors=True)
            gone.append(b.name)
    names = {b.name for b in finished}
    series: dict[str, list[tuple[datetime, Path]]] = {}
    try:
        entries = list(os.scandir(bdir))
    except OSError:
        return gone
    for e in entries:
        if _FOLDER_RX.match(e.name) and e.is_dir(follow_symlinks=False) and e.name not in names:
            shutil.rmtree(e.path, ignore_errors=True)          # unfinished: no manifest was ever written
            gone.append(e.name)
            continue
        m = _SV1_RX.match(e.name)
        if m and e.is_file(follow_symlinks=False):
            at = datetime.fromtimestamp(e.stat().st_mtime, timezone.utc)
            series.setdefault(m.group("store"), []).append((at, Path(e.path)))
    for copies in series.values():
        copies.sort(key=lambda c: c[0], reverse=True)
        label = "before-migration"
        kept = should_keep([(at, label) for at, _ in copies], LABELLED_ONLY, now=now, protect_newest=False)
        for (_, path), keep in zip(copies, kept):
            if not keep:
                path.unlink(missing_ok=True)
                gone.append(path.name)
    return gone


def _record(root: Path, out: TakeOutcome, started: float, at: datetime) -> None:
    """What the last check found, beside the backups — `/health` reads this one small file, never the folders."""
    if out.status not in ("taken", "unchanged", "skipped_space", "failed"):
        return
    try:
        total, count = _bytes_on_disk(root)
        latest = list_backups(root)
        backups_dir(root).mkdir(parents=True, exist_ok=True)
        _write_json(backups_dir(root) / LAST_RUN, {
            "at": at.isoformat(timespec="seconds"), "outcome": out.status, "reason": out.reason,
            "stamp": out.stamp, "latest": latest[0].name if latest else None,
            "copied": out.copied, "linked": out.linked, "failed": out.failed, "pruned": out.pruned,
            "bytes_new": out.bytes_new, "bytes_total": total, "backups": count,
            "duration_s": round(time.monotonic() - started, 1),
        })
    except Exception as exc:                  # noqa: BLE001 — the record failing must not fail the backup it records
        logger.warning("backups: could not record the last run: %s", exc)


def take(*, label: Optional[str] = None, reason: str = "hourly", force: bool = False, root: Optional[Path] = None,
         now: Optional[datetime] = None, do_prune: bool = True) -> TakeOutcome:
    """Take a backup of the state directory, if anything changed since the last one (``force`` takes it anyway),
    then prune. Never raises: every outcome is a ``TakeOutcome``, and the ones that checked something are recorded."""
    if not _LOCK.acquire(blocking=False):
        return TakeOutcome("busy", "a backup is already being taken in this process")
    started = time.monotonic()
    root = root or _root()
    at = now or _now()
    try:
        out = _take_locked(root, at, label=label, reason=reason, force=force)
        # After every backup written — an incomplete one too: a store failing every hour must not pile them up.
        if do_prune and out.folder is not None:
            try:
                out.pruned = prune(root, at)
            except Exception as exc:          # noqa: BLE001 — a prune that fails leaves more backups, never fewer
                logger.warning("backups: pruning failed: %s", exc)
    except Exception as exc:                  # noqa: BLE001 — said on /health, never raised into the clock
        logger.error("backups: the backup failed: %s", exc, exc_info=True)
        out = TakeOutcome("failed", f"{type(exc).__name__}: {exc}")
    finally:
        _LOCK.release()
    _record(root, out, started, at)
    return out


def _take_locked(root: Path, at: datetime, *, label: Optional[str], reason: str, force: bool) -> TakeOutcome:
    if not root.is_dir():
        return TakeOutcome("failed", f"there is no state folder at {root}")
    bdir = backups_dir(root)
    sources, not_copied = scan(root)
    not_copied += _elsewhere(root)
    finished = list_backups(root)
    prev = finished[0] if finished else None
    prev_sources: dict = {}
    if prev is not None:
        try:
            prev_sources = prev.manifest().get("sources") or {}
        except (OSError, ValueError):
            prev, prev_sources = None, {}     # an unreadable manifest is no base to link from: copy everything
    changed = [s for s in sources if not _unchanged(s, prev_sources.get(s.rel), prev)]
    if (not force and prev is not None and not changed
            and set(prev_sources) == {s.rel for s in sources}):
        return TakeOutcome("unchanged", f"nothing changed since the backup {prev.name}", stamp=prev.name)

    need = sum(_source_bytes(s) for s in changed)
    need += max((_source_bytes(s) for s in changed if s.kind == "sqlite"), default=0)   # the uncompressed copy
    usage = shutil.disk_usage(bdir if bdir.exists() else root)
    floor = free_floor(usage.total)
    if usage.free - need < floor:
        return TakeOutcome("skipped_space",
                           f"taking it would leave {_gb(usage.free - need)} free, under the floor of {_gb(floor)} — "
                           f"free some space, or set {FREE_FLOOR_ENV}")

    folder = _claim_folder(bdir, at, label)
    out = TakeOutcome("taken", stamp=folder.name, folder=folder)
    entries: dict[str, dict] = {}
    try:
        for s in sources:
            before = prev_sources.get(s.rel)
            try:
                if _unchanged(s, before, prev):
                    entries[s.rel] = _link(before, prev, folder)
                    out.linked += 1
                    continue
                entries[s.rel] = _copy_store(s, folder) if s.kind == "sqlite" else _copy_file(s, folder)
                out.copied += 1
                out.bytes_new += entries[s.rel]["bytes"]
            except FileNotFoundError:
                logger.debug("backups: %s was removed after the scan — the next backup will not list it", s.rel)
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise
                out.failed.append({"path": s.rel, "error": f"{type(exc).__name__}: {exc}"})
            except Exception as exc:          # noqa: BLE001 — one store failing is named, and the rest are kept
                out.failed.append({"path": s.rel, "error": f"{type(exc).__name__}: {exc}"})
        manifest = {
            "format": MANIFEST_FORMAT, "name": folder.name, "taken_at": at.isoformat(timespec="seconds"),
            "label": label, "reason": reason, "state_dir": str(root), "complete": not out.failed,
            "sources": entries, "not_copied": not_copied, "failed": out.failed,
            "totals": {"copied": out.copied, "linked": out.linked, "bytes_new": out.bytes_new,
                       "bytes": sum(e["bytes"] for e in entries.values())},
        }
        _write_json(folder / MANIFEST, manifest)          # last: until it exists, the folder is unfinished
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if out.failed:
        out.status = "failed"
        out.reason = (f"{len(out.failed)} source(s) could not be copied — the backup {folder.name} holds the rest "
                      f"and says it is incomplete: " + "; ".join(f"{f['path']}: {f['error']}" for f in out.failed[:3]))
    else:
        out.reason = f"{out.copied} copied, {out.linked} unchanged and linked"
    logger.info("backups: %s — %s", folder.name, out.reason)
    return out


def run_scheduled(now: Optional[datetime] = None) -> TakeOutcome:
    """The hourly job: only in the process serving the state directory, at most hourly."""
    from aughor.db.serving import serving_pid
    pid = serving_pid()
    if pid != os.getpid():
        # Never a second process: a script or test that started the clock is not the writer of these stores.
        logger.warning("backups: not taken — this process (pid %d) does not serve the state folder (%s)",
                       os.getpid(), f"pid {pid} does" if pid else "nothing has claimed it")
        return TakeOutcome("not_serving")
    now = now or _now()
    last = read_last_run()
    try:
        last_at = datetime.fromisoformat(str((last or {}).get("at")))
    except ValueError:
        last_at = None
    if last_at is not None and now - last_at < NOT_DUE_WITHIN:
        return TakeOutcome("not_due")
    return take(reason="hourly", now=now)


# ── /health ────────────────────────────────────────────────────────────────────────

def health_block(root: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    """The backups block of `/health`: one small file and a folder listing, never a manifest — health stays instant.

    ``ok`` is None in the two processes the clock never runs in (serverless, or the in-process clocks off): no backup is
    taken there by design, which is said in ``detail`` and does not degrade `/health` — a process that is never the one
    keeping the state is not failing to keep it."""
    root = root or _root()
    now = now or _now()
    last = read_last_run(root)
    backups = list_backups(root)
    latest = backups[0] if backups else None
    out: dict = {
        "ok": False, "last_backup": latest.name if latest else None,
        "last_backup_age_hours": round((now - latest.taken_at).total_seconds() / 3600, 1) if latest else None,
        "last_check": None, "outcome": None, "copied": 0, "linked": 0,
        "total_bytes": None, "backups": len(backups), "skipped_for_space": None, "last_error": None, "detail": "",
    }
    # The two processes the clock never runs in, said rather than left to read as a backup not yet due.
    if os.environ.get("VERCEL"):
        out["ok"] = None
        out["detail"] = "backups do not run on a serverless instance — its disk is not the state's"
        return out
    if (os.environ.get("AUGHOR_DISABLE_SCHEDULERS") or "").strip().lower() not in ("", "0", "false", "no"):
        out["ok"] = None
        out["detail"] = "the in-process clocks are off here (AUGHOR_DISABLE_SCHEDULERS), so no backup is taken"
        return out
    if not last:
        out["detail"] = "no backup has been checked yet — the first is taken a few minutes after the server starts"
        return out
    try:
        at = datetime.fromisoformat(str(last.get("at")))
    except ValueError:
        out["detail"] = "the record of the last backup cannot be read"
        return out
    age = now - at
    outcome = last.get("outcome")
    out.update({"last_check": last.get("at"), "outcome": outcome, "copied": last.get("copied", 0),
                "linked": last.get("linked", 0), "total_bytes": last.get("bytes_total")})
    if outcome == "skipped_space":
        out["skipped_for_space"] = last.get("reason")
    if outcome == "failed":
        out["last_error"] = last.get("reason")
    hours = age.total_seconds() / 3600
    if age > STALE_AFTER:
        out["detail"] = (f"no backup has been checked for {hours:.1f} hours — the server's housekeeping clock may have "
                         "stopped")
    elif outcome == "failed":
        out["detail"] = f"the last backup failed: {last.get('reason')}"
    elif outcome == "skipped_space":
        out["detail"] = f"the last backup was skipped for space: {last.get('reason')}"
    elif outcome == "unchanged":
        out["ok"] = True
        out["detail"] = f"nothing changed since {out['last_backup']}; checked {hours * 60:.0f} minutes ago"
    elif outcome == "taken":
        out["ok"] = True
        size = f"; {_gb(out['total_bytes'])} in {out['backups']} backups" if out["total_bytes"] is not None else ""
        out["detail"] = (f"backed up {last.get('stamp')}: {out['copied']} copied, {out['linked']} unchanged and "
                         f"linked{size}")
    else:
        out["detail"] = f"the last backup's outcome {outcome!r} is not one this version knows"
    return out


# ── restoring one ──────────────────────────────────────────────────────────────────

def _group(rels: list[str]) -> list[str]:
    """Paths gathered by their first two folders, so a list a person reads stays short."""
    counts: dict[str, int] = {}
    for rel in rels:
        parts = rel.split("/")
        key = "/".join(parts[:2]) + ("/…" if len(parts) > 2 else "")
        counts[key] = counts.get(key, 0) + 1
    return [k if n == 1 else f"{k} ({n} files)" for k, n in sorted(counts.items())]


def _seeds(path: Path) -> tuple[set, set]:
    data = _read_json(path) or {}
    return set(data.get("schemas") or []), set(data.get("tables") or [])


def _removals(root: Path, staging: Path, manifest: dict, present: dict[str, Source]) -> list[str]:
    """Every removal recorded after the backup that restoring it would bring back, in sentences."""
    said: list[str] = []
    sources = manifest.get("sources") or {}
    # 1. Tombstones — a seed schema or table a person removed is held removed only by its tombstone (`local_upload`).
    for rel in sorted({r for r in set(sources) | set(present) if r.rsplit("/", 1)[-1] == _TOMBSTONE_NAME}):
        now_s, now_t = _seeds(root / rel) if rel in present else (set(), set())
        then_s, then_t = _seeds(staging / rel) if rel in sources else (set(), set())
        back = sorted(now_s - then_s) + sorted(now_t - then_t)
        if back:
            said.append(f"{rel}: {', '.join(back)} — removed after the backup; the restore brings them back")
    # 2. Removals the governance audit approved after the backup.
    ledger = root / _LEDGER_FILE
    if ledger.exists():
        try:
            conn = _connect_ro(ledger)
            try:
                rows = conn.execute("SELECT at, payload FROM events WHERE kind = 'action.approval' AND at > ? "
                                    "ORDER BY seq", (manifest.get("taken_at") or "",)).fetchall()
            finally:
                conn.close()
            for at, payload in rows:
                p = json.loads(payload or "{}")
                if p.get("action") in _REMOVAL_ACTIONS and p.get("decision") in ("approved", "auto"):
                    said.append(f"{str(at)[:16]} {p.get('action')} of {p.get('scope') or '?'} by "
                                f"{p.get('actor') or '?'}, approved after the backup — what it removed comes back")
        except (sqlite3.Error, ValueError) as exc:
            said.append(f"the audited removals could not be read ({exc}) — check them before going on")
    # 3. Connections the backup's registry holds and the present one does not — found whether or not approval was on.
    if _REGISTRY_FILE in sources and (staging / _REGISTRY_FILE).exists():
        def ids(path: Path) -> Optional[dict[str, str]]:
            """``{id: name}``; empty when there is no registry, None when there is one that cannot be read."""
            if not path.exists():
                return {}
            try:
                c = _connect_ro(path)
                try:
                    return {r[0]: r[1] for r in c.execute("SELECT id, name FROM connections").fetchall()}
                finally:
                    c.close()
            except sqlite3.Error as exc:
                logger.warning("backups: the registry at %s cannot be read: %s", path, exc)
                return None
        then, now_ids = ids(staging / _REGISTRY_FILE), ids(root / _REGISTRY_FILE)
        if then is None or now_ids is None:
            # Read as empty, an unreadable registry would list every connection as removed — or none.
            said.append("the connections now and in the backup could not both be read — compare them before going on")
        else:
            for cid in sorted(set(then) - set(now_ids)):
                said.append(f"connection {then[cid]} ({cid}) — removed after the backup; the restore brings it back")
    # 4. Files the backup holds that are gone now.
    gone = [r for r, e in sources.items() if e.get("kind") == "file" and r not in present and r not in NEVER_RESTORED]
    for line in _group(gone):
        said.append(f"{line} — gone since the backup; the restore brings it back")
    return said


def _carry(staged: Path, live: Path, tables: dict[str, str]) -> None:
    """Replace each table in the staged store with the live store's rows. Columns the live table has and the backup's
    lacks are added first — additive, as every migration here is — so no value is lost."""
    if not live.exists():
        return
    conn = sqlite3.connect(staged.resolve().as_uri(), uri=True, isolation_level=None)
    try:
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        conn.execute("ATTACH DATABASE ? AS present", (_ro_uri(live),))
        for table in tables:
            have = conn.execute("SELECT sql FROM present.sqlite_master WHERE type = 'table' AND name = ?",
                                (table,)).fetchone()
            if not have:
                continue
            q = '"' + table.replace('"', '""') + '"'
            if not conn.execute("SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = ?",
                                (table,)).fetchone():
                conn.execute(have[0])
            ours = {r[1] for r in conn.execute(f"PRAGMA main.table_info({q})")}
            theirs = [(r[1], r[2]) for r in conn.execute(f"PRAGMA present.table_info({q})")]
            for col, decl in theirs:
                if col not in ours:
                    conn.execute(f'ALTER TABLE main.{q} ADD COLUMN "{col}" {decl}')
            cols = ", ".join('"' + c.replace('"', '""') + '"' for c, _ in theirs)
            conn.execute("BEGIN")
            conn.execute(f"DELETE FROM main.{q}")
            conn.execute(f"INSERT INTO main.{q} ({cols}) SELECT {cols} FROM present.{q}")
            conn.execute("COMMIT")
        conn.execute("DETACH DATABASE present")
    finally:
        conn.close()


def _check_store(path: Path, entry: dict, skip: set[str]) -> list[str]:
    problems: list[str] = []
    conn = _connect_ro(path)
    try:
        verdict = conn.execute("PRAGMA quick_check").fetchone()[0]
        if str(verdict).lower() != "ok":
            problems.append(f"quick_check said {verdict!r}")
        rows = _table_rows(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    for table, n in (entry.get("rows") or {}).items():
        if table not in skip and rows.get(table) != n:
            problems.append(f"table {table} has {rows.get(table)} rows, the backup recorded {n}")
    if version != entry.get("user_version"):
        problems.append(f"reads version {version}, the backup recorded {entry.get('user_version')}")
    return problems


def _stage(backup: Backup, manifest: dict, root: Path, staging: Path) -> tuple[list[str], list[str], dict[str, str]]:
    """Put a checked copy of everything to restore under ``staging``: ``(restorable, problems, keep)``. ``keep`` names
    each present file the restore must not discard, and why — a store whose model-call log could not be carried,
    which is the case a damaged store is restored for, so it must not block the restore."""
    restorable, problems, keep = [], [], {}
    for rel, entry in sorted((manifest.get("sources") or {}).items()):
        if rel in NEVER_RESTORED:
            continue
        stored = backup.folder / entry["stored"]
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if entry["kind"] == "sqlite":
                if _sha256(stored) != entry["sha256"]:
                    problems.append(f"{rel}: the stored copy's contents differ from the manifest")
                    continue
                with gzip.open(stored, "rb") as fi, dst.open("wb") as fo:
                    shutil.copyfileobj(fi, fo, 1024 * 1024)
                os.chmod(dst, stored.stat().st_mode & 0o777)
                carried = CARRIED_FORWARD.get(rel, {})
                if carried:
                    try:
                        _carry(dst, root / rel, carried)
                    except sqlite3.Error as exc:
                        keep[rel] = (f"its {', '.join(carried)} could not be read to carry forward ({exc}); the file "
                                     "as it is now is kept beside the backups")
                problems += [f"{rel}: {p}" for p in _check_store(dst, entry, set(carried))]
            else:
                shutil.copy2(stored, dst)
                if _sha256(dst) != entry["sha256"]:
                    problems.append(f"{rel}: the stored copy's contents differ from the manifest")
                    continue
            restorable.append(rel)
        except (OSError, sqlite3.Error, EOFError, KeyError, gzip.BadGzipFile) as exc:
            problems.append(f"{rel}: could not be staged ({type(exc).__name__}: {exc})")
    return restorable, problems, keep


def _move_aside(live: Path, aside: Path, moved: list[tuple[Path, Path]]) -> None:
    """Move a live file — and, for a store, its sidecars — under ``aside``, remembering each move to undo it."""
    for p in [live] + [Path(f"{live}{s}") for s in _SIDECARS]:
        if p.exists():
            target = aside / p.name           # `aside` is the folder the file sits in, mirrored under the aside root
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(p, target)
            moved.append((p, target))


def restore(name: str, *, confirm: Callable[[dict], bool], root: Optional[Path] = None,
            force_serving: bool = False) -> RestoreOutcome:
    """Put the backup ``name`` back in place of the present state.

    ``confirm`` is shown what the restore would do — ``restored``, ``removals`` (what it brings back), ``set_aside``
    (files made since, which it moves out of the way) and ``kept`` (what it never restores over) — and answers whether
    to go on. Nothing live changes before it says yes."""
    root = root or _root()
    if not force_serving:
        from aughor.db.serving import serving_pid
        pid = serving_pid()
        if pid:
            return RestoreOutcome("refused", f"the API is serving as pid {pid}. A restore replaces the stores it has "
                                             f"open, and system.db has been corrupted four times by a second writer — "
                                             f"stop it first (kill {pid}), then run this again.")
    try:
        backup = resolve(name, root)
        manifest = backup.manifest()
    except (LookupError, OSError, ValueError) as exc:
        return RestoreOutcome("refused", str(exc))
    if not manifest.get("complete", False):
        failed = "; ".join(f"{f.get('path')}: {f.get('error')}" for f in manifest.get("failed") or [])
        return RestoreOutcome("refused", f"the backup {backup.name} is incomplete ({failed}) — choose another",
                              backup=backup.name)

    bdir = backups_dir(root)
    when = _stamp(_now())
    staging = bdir / f".restoring-{when}"
    aside = bdir / f".aside-{when}"
    out = RestoreOutcome("failed", backup=backup.name)
    try:
        need = sum(int(e.get("source_bytes") or e.get("bytes") or 0) for r, e in (manifest.get("sources") or {}).items()
                   if r not in NEVER_RESTORED)
        usage = shutil.disk_usage(bdir)
        if usage.free - need < free_floor(usage.total):
            return RestoreOutcome("refused", f"staging the restore needs {_gb(need)}, which would leave less than the "
                                             f"floor of {_gb(free_floor(usage.total))} free", backup=backup.name)
        restorable, problems, keep = _stage(backup, manifest, root, staging)
        if problems:
            out.reason = "the backup does not check — nothing was changed"
            out.problems = problems
            return out
        present_sources, _ = scan(root)
        present = {s.rel: s for s in present_sources}
        extra = sorted(r for r in present if r not in manifest["sources"] and r not in NEVER_RESTORED)
        out.restored, out.set_aside = restorable, extra
        out.kept = [f"{rel} — {why}" for rel, why in NEVER_RESTORED.items() if (root / rel).exists()]
        out.kept += [f"{rel}: {t} — {why}" for rel, tables in CARRIED_FORWARD.items() if rel in restorable
                     for t, why in tables.items()]
        out.warnings = [f"{rel}: {why}" for rel, why in keep.items()]
        plan = {"backup": backup.name, "taken_at": manifest.get("taken_at"), "restored": restorable,
                "removals": _removals(root, staging, manifest, present), "set_aside": _group(extra),
                "kept": out.kept, "warnings": out.warnings}
        if not confirm(plan):
            out.status, out.reason = "declined", "nothing was changed"
            return out
        present_copy = take(label=BEFORE_RESTORE, reason=f"before restoring {backup.name}", force=True, root=root,
                            do_prune=False)
        finished = present_copy.folder is not None and (present_copy.folder / MANIFEST).is_file()
        if present_copy.status not in ("taken", "failed") or not finished:
            out.status = "refused"
            out.reason = (f"the copy of the present could not be taken ({present_copy.status}: {present_copy.reason}) "
                          "— nothing was changed")
            return out
        # A store the copy could not take — a damaged one, which is what a restore is for — must not block it: it is
        # kept as it is beside the backups instead, and said.
        for f in present_copy.failed:
            keep.setdefault(f["path"], f"it could not be copied before the restore ({f['error']}); the file as it "
                                       "is now is kept beside the backups")
        out.warnings = [f"{rel}: {why}" for rel, why in keep.items()]
        out.before_restore = present_copy.stamp
        return _swap(root, staging, aside, manifest, restorable, extra, out, keep=set(keep))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _swap(root: Path, staging: Path, aside: Path, manifest: dict, restorable: list[str], extra: list[str],
          out: RestoreOutcome, *, keep: set[str] = frozenset()) -> RestoreOutcome:
    """Move the live files aside, put the staged ones in place, check them there; on any failure, put the originals
    back. The originals are removed only once the restore checks — the labelled backup holds them — except those in
    ``keep``, which it does not hold, and which stay under ``aside``."""
    moved: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    sources = manifest["sources"]
    try:
        for rel in restorable:
            live = root / rel
            _move_aside(live, (aside / rel).parent, moved)
            live.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / rel, live)
            placed.append(live)
        for rel in extra:
            _move_aside(root / rel, (aside / rel).parent, moved)
        problems: list[str] = []
        for rel in restorable:
            entry = sources[rel]
            if entry["kind"] == "sqlite":
                problems += [f"{rel}: {p}" for p in _check_store(root / rel, entry, set(CARRIED_FORWARD.get(rel, {})))]
            elif _sha256(root / rel) != entry["sha256"]:
                problems.append(f"{rel}: in place, its contents differ from the backup's")
        if problems:
            raise BackupCheckFailed("; ".join(problems[:5]))
    except Exception as exc:                  # noqa: BLE001 — every failure takes the same way back
        for live in placed:
            for p in [live] + [Path(f"{live}{s}") for s in _SIDECARS]:
                p.unlink(missing_ok=True)
        for live, target in reversed(moved):
            live.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, live)
        shutil.rmtree(aside, ignore_errors=True)
        out.status = "failed"
        out.reason = (f"the restore did not check in place ({type(exc).__name__}: {exc}) — the originals are back, "
                      f"and the copy of them is the backup {out.before_restore}")
        return out
    kept_any = False
    for live, target in moved:
        rel = live.relative_to(root).as_posix()
        base = next((rel[: -len(s)] for s in _SIDECARS if rel.endswith(s)), rel)
        if base in keep:
            kept_any = True                   # the labelled backup could not hold it: this is the only copy
        else:
            target.unlink(missing_ok=True)
    if kept_any:
        out.kept_aside = str(aside)
    else:
        shutil.rmtree(aside, ignore_errors=True)
    out.status = "restored"
    out.reason = (f"{len(restorable)} restored from {out.backup}, {len(extra)} set aside; the state before it is the "
                  f"backup {out.before_restore}"
                  + (f"; what it could not hold is kept at {aside}" if kept_any else ""))
    return out
