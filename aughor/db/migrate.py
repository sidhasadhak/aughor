"""IN-4 — the one-time move of generated state out of the checkout, verified before it counts.

`aughor migrate-state` copies, verifies, then writes the marker that makes
`aughor.db.home.in_use()` true. Nothing before the marker changes where a single store reads,
and the source is NEVER deleted — the install this was written against holds 1.4 GB under
`data/`, and reclaiming that is a person's decision made after they are satisfied, not a step
buried inside a migration.

Three properties, each here because getting it wrong is expensive:

**It refuses while the API is serving.** `data/system.db` has been corrupted four separate
times by concurrent writers, and a migration is the most write-heavy thing the platform can
do. `db.serving.serving_pid()` already answers "is something serving, and is it alive"; if it
says yes, this stops and says which pid to stop.

**A SQLite store is copied through SQLite, not through the filesystem.** These stores run in
WAL mode, where committed transactions can live in `-wal` until a checkpoint. `shutil.copy2`
of the `.db` alone silently drops them, and the copy still opens cleanly — a verified-looking
migration that quietly lost the most recent writes. `sqlite3.Connection.backup()` reads
through the engine and produces a consistent copy including anything in the WAL.

**Verification is per-file and specific.** Every copied byte is compared by SHA-256 for
ordinary files; every SQLite copy answers `PRAGMA integrity_check` and is compared by table
row counts against its source. A count that disagrees fails the whole migration and the marker
is not written, so the deployment goes on reading the state it already had.
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from aughor.db import home

#: Suffixes SQLite writes beside a database. They are copied through `backup()` rather than by
#: hand, so they are SKIPPED as sources in their own right — copying a stale `-wal` over a
#: freshly-backed-up database would be worse than not copying it at all.
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")

#: What a SQLite file is called here. `.duckdb` is deliberately absent: DuckDB is not SQLite and
#: must be copied as bytes, which is safe because it has no separate WAL sidecar convention.
_SQLITE_SUFFIXES = (".db",)


@dataclass
class Outcome:
    """A typed verdict, never `X or {}` — "nothing to do" and "it failed" must not read alike."""
    status: str                                    # "migrated" | "already" | "refused" | "failed"
    reason: str = ""
    source: Path | None = None
    destination: Path | None = None
    copied: int = 0
    bytes_copied: int = 0
    skipped_authored: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("migrated", "already")


#: Every connection this module opens sets it. Neither side should ever contend — the source is
#: read-only and the API is refused while serving — but a migration that fails instantly on a
#: stray reader is worse than one that waits, and `tests/unit/test_sqlite_contention.py` is right
#: to insist a connect site says what it does about contention rather than staying silent.
_BUSY_TIMEOUT_MS = 30_000


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro" if read_only else f"file:{path}"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    return conn


def _is_sqlite(path: Path) -> bool:
    return path.suffix in _SQLITE_SUFFIXES


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _table_counts(path: Path) -> dict[str, int]:
    """`{table: rows}` read read-only. Used on BOTH sides of a SQLite copy, because a file that
    opens and passes integrity_check can still be missing everything the WAL held."""
    with _connect(path, read_only=True) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def _copy_sqlite(src: Path, dst: Path) -> None:
    """Through the engine, so anything sitting in the WAL comes with it."""
    with _connect(src, read_only=True) as source, _connect(dst) as target:
        source.backup(target)


def _verify(src: Path, dst: Path) -> list[str]:
    """What is wrong with this copy, in sentences. Empty means verified."""
    problems: list[str] = []
    if not dst.exists():
        return [f"{src.name}: the copy is not there"]
    if _is_sqlite(src):
        try:
            with _connect(dst, read_only=True) as conn:
                verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if verdict != "ok":
                problems.append(f"{src.name}: integrity_check said {verdict!r}")
            before, after = _table_counts(src), _table_counts(dst)
            for table, rows in before.items():
                if after.get(table) != rows:
                    problems.append(
                        f"{src.name}: table {table} has {after.get(table)} rows, source has {rows}")
        except sqlite3.Error as exc:
            problems.append(f"{src.name}: the copy could not be read back ({exc})")
    elif _sha256(src) != _sha256(dst):
        problems.append(f"{src.name}: the copy's contents differ from the source")
    return problems


def sources(state: Path) -> tuple[list[Path], list[str]]:
    """``(what moves, what stays)`` for a state directory — top-level entries only.

    Authored entries stay: `data/` is mixed, and its versioned content belongs to the checkout.
    SQLite sidecars are skipped because `backup()` carries their contents."""
    moving: list[Path] = []
    staying: list[str] = []
    for entry in sorted(state.iterdir()):
        if entry.name in home.AUTHORED_ENTRIES:
            staying.append(entry.name)
            continue
        if any(entry.name.endswith(s) for s in _SQLITE_SIDECARS):
            continue
        moving.append(entry)
    return moving, staying


def migrate(source: Path, *, force_serving: bool = False) -> Outcome:
    """Copy `source` into the data home, verify it, and only then write the marker."""
    destination = home.state_home()

    if home.in_use():
        return Outcome("already", f"the home is already in use at {destination}",
                       source=source, destination=destination)
    if not source.is_dir():
        return Outcome("refused", f"there is nothing at {source} to migrate", source=source)

    # A home pointed inside the checkout's own `data/` would make `copytree` walk into the copy
    # it is writing. Cheap to refuse, unbounded to discover.
    src_res, dst_res = source.resolve(), destination.resolve()
    if dst_res == src_res or src_res in dst_res.parents:
        return Outcome("refused",
                       f"the data home ({dst_res}) is inside the directory being migrated "
                       f"({src_res}). Point AUGHOR_HOME somewhere outside the checkout.",
                       source=source, destination=destination)

    if not force_serving:
        from aughor.db.serving import serving_pid
        pid = serving_pid()
        if pid:
            return Outcome(
                "refused",
                f"the API is serving as pid {pid}. A migration is the most write-heavy thing "
                f"the platform does, and data/system.db has been corrupted four times by a "
                f"second writer — stop it first, then run this again.",
                source=source, destination=destination)

    moving, staying = sources(source)
    if not moving:
        return Outcome("refused", f"{source} holds no generated state to move",
                       source=source, destination=destination, skipped_authored=staying)

    destination.mkdir(parents=True, exist_ok=True)
    out = Outcome("migrated", source=source, destination=destination, skipped_authored=staying)

    for entry in moving:
        target = destination / entry.name
        try:
            if entry.is_dir():
                shutil.copytree(entry, target, dirs_exist_ok=True)
                out.bytes_copied += sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            elif _is_sqlite(entry):
                _copy_sqlite(entry, target)
                out.bytes_copied += entry.stat().st_size
            else:
                shutil.copy2(entry, target)
                out.bytes_copied += entry.stat().st_size
            out.copied += 1
        except Exception as exc:                      # noqa: BLE001 — reported, never swallowed
            out.problems.append(f"{entry.name}: could not be copied ({exc})")

    for entry in moving:
        if entry.is_dir():
            for f in entry.rglob("*"):
                if f.is_file():
                    out.problems.extend(_verify(f, destination / entry.name / f.relative_to(entry)))
        else:
            out.problems.extend(_verify(entry, destination / entry.name))

    if out.problems:
        out.status = "failed"
        out.reason = (f"{len(out.problems)} problem(s) verifying the copy. The marker was NOT "
                      f"written, so the platform goes on reading {source} exactly as before.")
        return out

    home.marker_path().parent.mkdir(parents=True, exist_ok=True)
    home.marker_path().write_text(
        f"state migrated from {source}\n", encoding="utf-8")
    out.reason = (f"{out.copied} entries verified into {destination}. The originals are "
                  f"UNTOUCHED at {source} — delete them yourself once you are satisfied.")
    return out
