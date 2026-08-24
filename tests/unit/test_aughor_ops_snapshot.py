"""`aughor_ops` must never attach the LIVE ledger, and this is why.

DuckDB's `sqlite_scanner` links its OWN copy of SQLite, so a process using both contains
two SQLite libraries. POSIX advisory locks do not conflict WITHIN a process, so when
duckdb's copy asks for the exclusive dead-man-switch lock on a `-shm`, the kernel grants
it — even though our python-sqlite3 connections hold that lock and are mapped into the
file. SQLite's response to winning it is `robust_ftruncate(shm, 0)`: it truncates the WAL
index, on the theory that nobody else is using it. Every mapping we hold is then over a
file with no backing pages, and the next read through one is a bus error.

Measured 2026-08-24 on a store with a keepalive and four reader threads, 60 rounds:

    live ATTACH   503 `-shm` transitions (32768 → 3 bytes and back, SAME inode)
    no duckdb       1 transition (the initial creation)
    snapshot        1 transition, 0 shrinks

That is the SIGBUS in `walFindFrame` that had been killing this application, and the WAL
keepalive never helped because it was never a last-close problem.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest


def _shm(db: Path):
    try:
        st = os.stat(str(db) + "-shm")
        return (st.st_ino, st.st_size)
    except FileNotFoundError:
        return None


@pytest.fixture
def ledger_like(tmp_path):
    """A store shaped like `system.db`: WAL, the four curated tables, rows to page in."""
    from aughor.db.backend import connect_store

    db = tmp_path / "system.db"
    conn = connect_store(db)
    for tbl in ("task_history", "jobs", "events", "session_events"):
        conn.execute(f"CREATE TABLE {tbl} (a TEXT, b TEXT, payload TEXT)")
        conn.executemany(f"INSERT INTO {tbl} VALUES (?,?,?)",
                         [(f"x{i}", f"y{i}", "p" * 200) for i in range(300)])
    conn.commit()
    conn.close()
    # A live mapping, exactly as the keepalive holds one in the serving process.
    holder = sqlite3.connect(str(db), check_same_thread=False)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("SELECT count(*) FROM sqlite_master").fetchone()
    yield db
    holder.close()


def test_opening_the_ops_connection_never_shrinks_the_live_wal_index(ledger_like):
    """THE regression, and it has to be sampled DURING the attach.

    The first version of this test compared `(inode, size)` before and after and PASSED
    with the defect restored: the truncate is to 3 bytes and SQLite grows the file back to
    32768 immediately, same inode, so by the time the assertion runs there is nothing left
    to see. A test that cannot fail is worse than no test — it is the third time today the
    transience of this fault has hidden it from an instrument pointed straight at it.

    So a thread samples the size in a tight loop while the connection is opened, and the
    assertion is on SHRINKS. Measured: 503 transitions with the live attach over 60
    rounds, 0 with the snapshot.
    """
    import threading

    from aughor.db.connection import AughorOpsConnection

    start = _shm(ledger_like)
    assert start is not None, "no WAL index on the source — the probe proves nothing"

    stop = threading.Event()
    shrinks: list = []

    def sample():
        last = start
        while not stop.is_set():
            cur = _shm(ledger_like)
            if cur != last:
                if cur is None or (last is not None and cur[1] < last[1]):
                    shrinks.append((last, cur))
                last = cur

    watcher = threading.Thread(target=sample, daemon=True)
    watcher.start()
    try:
        for _ in range(5):
            conn = AughorOpsConnection(ledger_like)
            try:
                conn._conn.execute("SELECT count(*) FROM aughor_ops.task_history").fetchone()
            finally:
                conn.close()
    finally:
        stop.set()
        watcher.join(timeout=5)

    assert shrinks == [], (
        f"the live store's WAL index was TRUNCATED {len(shrinks)} time(s) — {shrinks[:3]} — "
        f"so every mapping this process holds is over a file with no backing pages, and "
        f"the next read through one is SIGBUS in walFindFrame")


def test_it_attaches_a_copy_and_not_the_store_itself(ledger_like):
    """Naming the mechanism, not just its symptom: a future author who 'restores the
    liveness' has to delete this test to do it."""
    from aughor.db.connection import AughorOpsConnection

    conn = AughorOpsConnection(ledger_like)
    try:
        attached = conn._conn.execute(
            "SELECT path FROM duckdb_databases() WHERE database_name = 'aughor_ops'"
        ).fetchone()
        assert attached and attached[0], "aughor_ops is not attached at all"
        assert Path(attached[0]) != ledger_like, (
            "aughor_ops is attached directly to the live ledger — this is the defect")
        assert conn._snapshot is not None
    finally:
        conn.close()


def test_every_curated_table_survives_the_snapshot(ledger_like):
    """The cheaper fix — always taking the old fallback — would have shrunk this surface
    to `task_history` alone while `_OPS_TABLES` and `get_schema()` kept advertising four."""
    from aughor.db.connection import AughorOpsConnection

    conn = AughorOpsConnection(ledger_like)
    try:
        names = {r[0] for r in conn._conn.execute(
            "SELECT DISTINCT table_name FROM duckdb_columns() "
            "WHERE database_name = 'aughor_ops'").fetchall()}
        assert set(AughorOpsConnection._OPS_TABLES) <= names
        schema = conn.get_schema()
        for tbl in AughorOpsConnection._OPS_TABLES:
            assert f"aughor_ops.{tbl}" in schema
    finally:
        conn.close()


def test_the_snapshot_is_deleted_when_the_connection_closes(ledger_like):
    """A per-open temp copy that is never removed is a disk leak on a long-running server."""
    from aughor.db.connection import AughorOpsConnection

    conn = AughorOpsConnection(ledger_like)
    snap = conn._snapshot
    assert snap is not None and snap.exists()

    conn.close()

    assert not snap.exists(), f"{snap} outlived the connection that made it"
    assert conn._snapshot is None


def test_closing_twice_is_harmless(ledger_like):
    from aughor.db.connection import AughorOpsConnection

    conn = AughorOpsConnection(ledger_like)
    conn.close()
    conn.close()


def test_the_row_cap_keeps_the_NEWEST_rows(ledger_like, monkeypatch):
    """A cap that kept the oldest rows would answer "why was yesterday slow" with the
    first thing this install ever did."""
    from aughor.db.connection import AughorOpsConnection

    monkeypatch.setattr(AughorOpsConnection, "_SNAPSHOT_ROW_CAP", 10)
    conn = AughorOpsConnection(ledger_like)
    try:
        rows = conn._conn.execute(
            "SELECT a FROM aughor_ops.task_history").fetchall()
        assert len(rows) == 10
        # seeded x0..x299, so the newest ten are x290..x299
        assert {r[0] for r in rows} == {f"x{i}" for i in range(290, 300)}
    finally:
        conn.close()


def test_a_missing_table_does_not_cost_the_whole_snapshot(tmp_path):
    """An install that has not written `session_events` yet still gets the other three."""
    from aughor.db.backend import connect_store
    from aughor.db.connection import AughorOpsConnection

    db = tmp_path / "system.db"
    conn = connect_store(db)
    conn.execute("CREATE TABLE task_history (a TEXT)")
    conn.execute("INSERT INTO task_history VALUES ('only')")
    conn.commit()
    conn.close()

    ops = AughorOpsConnection(db)
    try:
        names = {r[0] for r in ops._conn.execute(
            "SELECT DISTINCT table_name FROM duckdb_columns() "
            "WHERE database_name = 'aughor_ops'").fetchall()}
        assert "task_history" in names
    finally:
        ops.close()


def test_nothing_attaches_a_sqlite_file_through_duckdb_without_a_reason():
    """The ratchet.

    `ATTACH … (TYPE sqlite)` puts a SECOND SQLite library onto a file. That is safe only
    when nothing else in this process has that file open — which is true of a temp
    snapshot and false of every store under `data/`. A new one arrives with its reason or
    it does not arrive.
    """
    import re

    root = Path(__file__).resolve().parents[2] / "aughor"
    allowed = {
        # Attaches the snapshot it just built, never the live ledger — asserted above by
        # `test_it_attaches_a_copy_and_not_the_store_itself`.
        "aughor/db/connection.py",
    }
    offenders = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        if rel in allowed:
            continue
        # The SQL form `(TYPE sqlite, …)`, not the words. Matching the bare phrase made
        # this fire on the docstring that EXPLAINS the hazard — a guard that cannot tell
        # code from prose about the code.
        if re.search(r"\(\s*TYPE\s+sqlite\b", path.read_text(encoding="utf-8"), re.IGNORECASE):
            offenders.append(rel)
    assert offenders == [], (
        f"{offenders} attach a SQLite file through duckdb's sqlite_scanner. If the file is "
        f"one this process also opens with python-sqlite3, duckdb's own SQLite will "
        f"truncate its -shm out from under every live mapping — the SIGBUS in "
        f"walFindFrame. Attach a copy, or add the file here with the reason it is safe.")
