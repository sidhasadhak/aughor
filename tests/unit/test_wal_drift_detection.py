"""The WAL index can move under a live mapping — and until now nothing could say so.

#379 gave every store a keepalive; #383 gave the one store that had opted out a front
door. Both work: measured 2026-08-24 with a long-lived holder and 40 rounds of visiting
subprocesses, the `-shm` was recreated 0/40 times with the keepalive and 40/40 without.

What neither could do is notice when the guarantee fails anyway. A SIGBUS report names no
file — `vmRegionInfo` carries an `Object_id` and a region size, so every post-mortem so
far could say only "a 32 KB mapped file". These cover the detector that answers it.

Two measurements shape what these tests are allowed to do, both taken by reproducing the
fault in throwaway subprocesses:

1. **Truncation is the fault, not unlink.** Unlinking a live `-shm` is survivable — an
   open fd keeps the inode alive and reads still succeed. Truncating it in place is
   `SIGBUS · FS pagein error 22` on the next read (exit 138). Truncation leaves the inode
   IDENTICAL, so a detector watching only inodes is blind to the only thing that kills
   the process. `test_drift_is_detected_when_the_size_moves_but_the_inode_does_not` is
   that regression, and it fails against an inode-only detector.

2. **A test may not truncate a real `-shm`.** SQLite keeps ONE shared-memory object per
   database inode per PROCESS, so after a truncation both re-attaching AND merely closing
   the mapped connection fault (exit 138 each) — and the interpreter closes every
   connection at exit. A test that moved the real file would take the runner down at
   teardown and report nothing. So drift is simulated in the RECORDED state, which is the
   half of the comparison a test can own; the file is never touched.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real platform store on a temp file, with the module globals left clean."""
    from aughor.db import backend
    db = tmp_path / "rbac.db"
    monkeypatch.setenv("AUGHOR_RBAC_DB", str(db))
    from aughor.rbac import store as rs
    importlib.reload(rs)
    rs.assign_role("org", "u0", "viewer")       # one op: opens the store, attaches the WAL
    key = str(db)
    assert key in backend._KEEPALIVE, "the store never attached; the rest proves nothing"
    yield backend, key, db
    # The registry is a MODULE global and the store's tmp file is about to vanish, so a
    # test that left a simulated-drift entry behind would report it again in every later
    # test in this file. Purge all three structures, not just the drift set.
    backend._KEEPALIVE_DRIFT_PATHS.discard(key)
    backend._KEEPALIVE_SHM.pop(key, None)
    backend._KEEPALIVE.pop(key, None)


def test_the_keepalive_records_the_shm_state_it_attached_to(store):
    """Without the recording there is nothing to compare against later, and the whole
    detector degrades to "a file exists"."""
    backend, key, db = store
    st = os.stat(str(db) + "-shm")
    assert backend._KEEPALIVE_SHM.get(key) == (st.st_ino, st.st_size)


def test_a_store_nobody_disturbed_never_reports_drift(store):
    backend, key, _db = store
    assert backend.check_wal_drift() == []
    assert key not in backend.wal_keepalive_report()["drifted_paths"]


def test_drift_is_detected_when_the_size_moves_but_the_inode_does_not(store):
    """The regression the first draft of this detector had.

    Truncation is the fault mode and it does not move the inode, so an inode-only
    comparison reports a healthy process right up until it dies. Here the recorded inode
    is left EXACTLY as it is and only the size differs — an inode-only detector returns
    [] and this fails.
    """
    backend, key, db = store
    inode, size = backend._KEEPALIVE_SHM[key]
    backend._KEEPALIVE_SHM[key] = (inode, size + 4096)   # same inode, different size

    drifted = backend.check_wal_drift()

    assert drifted == [key]
    assert os.stat(str(db) + "-shm").st_ino == inode, (
        "the probe was supposed to leave the inode alone — it proves nothing otherwise")


def test_drift_is_detected_when_the_wal_index_is_recreated(store):
    """The other half: a new inode, which is what an unlink-and-recreate looks like."""
    backend, key, _db = store
    inode, size = backend._KEEPALIVE_SHM[key]
    backend._KEEPALIVE_SHM[key] = (inode + 1, size)

    assert backend.check_wal_drift() == [key]


def test_the_detector_never_touches_what_it_found(store):
    """The repair that was written, measured, and removed.

    Dropping the stale connection and attaching a fresh one is itself a SIGBUS: SQLite
    hands the "fresh" connection the same per-inode shared mapping, and the attach read
    faults on it (exit 138). Closing the stale connection faults for the same reason. So
    the entry must stay in the registry, holding the same connection object — an absent
    entry is what would invite the next `connect_store` call to re-attach into the fault.
    """
    backend, key, db = store
    before = backend._KEEPALIVE[key]
    stat_before = os.stat(str(db) + "-shm")
    inode, size = backend._KEEPALIVE_SHM[key]
    backend._KEEPALIVE_SHM[key] = (inode, size + 4096)

    backend.check_wal_drift()

    assert backend._KEEPALIVE[key] is before, (
        "the drifted store's connection was replaced — re-attaching after a truncation "
        "is the crash this detector exists to report, not a repair for it")
    after = os.stat(str(db) + "-shm")
    assert (after.st_ino, after.st_size) == (stat_before.st_ino, stat_before.st_size), (
        "the detector modified the WAL index it was only meant to observe")


def test_drift_is_reported_once_not_every_tick(store):
    """The supervisor calls this every 30s for the life of the process; a condition that
    cannot be repaired would otherwise log forever."""
    backend, key, _db = store
    # Relative, not absolute: the counter is a module global and every test in this file
    # shares it, so an absolute assertion here passes or fails on test ORDER.
    before = backend._KEEPALIVE_DRIFTED
    inode, size = backend._KEEPALIVE_SHM[key]
    backend._KEEPALIVE_SHM[key] = (inode, size + 4096)

    assert backend.check_wal_drift() == [key]
    assert backend.check_wal_drift() == []
    report = backend.wal_keepalive_report()
    assert report["drifted"] == before + 1
    assert key in report["drifted_paths"]


def test_the_report_names_the_store_a_crash_report_cannot(store):
    backend, key, db = store
    entry = next(s for s in backend.wal_keepalive_report()["stores"] if s["path"] == key)
    st = os.stat(str(db) + "-shm")
    assert entry["shm_at_attach"] == [st.st_ino, st.st_size]
    assert entry["shm_present"] is True
    assert entry["drifted"] is False


def test_eviction_is_counted_so_the_cap_stays_a_measured_answer(tmp_path):
    """23 stores against a cap of 256 was measured on a live API, which is what retired
    eviction as a SIGBUS suspect. The high-water mark is what keeps that answer true
    rather than remembered."""
    from aughor.db import backend
    before = backend._KEEPALIVE_HIGHWATER
    for i in range(3):
        backend._hold_wal_open(tmp_path / f"s{i}.db")
    assert backend._KEEPALIVE_HIGHWATER >= before
    assert backend.wal_keepalive_report()["highwater"] == backend._KEEPALIVE_HIGHWATER
    assert backend.wal_keepalive_report()["max"] == backend._KEEPALIVE_MAX


# ── the visiting-process guard ──────────────────────────────────────────────────

@pytest.fixture
def served(tmp_path, monkeypatch):
    """A state directory, with the once-per-process memo reset between tests."""
    from aughor.db import serving
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path))
    serving._checked = False
    serving._foreign = False
    yield serving, tmp_path
    serving._checked = False
    serving._foreign = False


def test_an_unclaimed_directory_is_nobody_elses(served, tmp_path):
    serving, _ = served
    assert serving.serving_pid() is None
    assert serving.warn_if_foreign(tmp_path / "x.db") is False


def test_our_own_claim_is_not_a_foreign_process(served, tmp_path):
    serving, _ = served
    serving.claim()
    assert serving.serving_pid() == os.getpid()
    assert serving.warn_if_foreign(tmp_path / "x.db") is False


def test_a_live_foreign_claim_is_reported(served, tmp_path):
    """The measured shape of the crash population: bare scripts (`parent=zsh`,
    `parent=uv`) opening `data/` while a server holds the same files."""
    serving, _ = served
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        serving.claim(other.pid)
        assert serving.serving_pid() == other.pid
        assert serving.warn_if_foreign(tmp_path / "x.db") is True
    finally:
        other.terminate()
        other.wait(timeout=10)


def test_a_pidfile_left_by_a_crash_does_not_cry_wolf(served, tmp_path):
    """This module exists because of a crash, so a pidfile naming a dead process is the
    expected case — a guard that fired forever after the first SIGBUS would be ignored
    within a day."""
    serving, _ = served
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=10)
    serving.claim(dead.pid)
    assert serving.serving_pid() is None
    assert serving.warn_if_foreign(tmp_path / "x.db") is False


def test_the_claim_is_released_so_the_next_process_is_not_warned(served, tmp_path):
    serving, _ = served
    serving.claim()
    serving.release()
    assert serving.serving_pid() is None


# ── the surfaces an operator actually reads ─────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_the_diagnostics_route_names_every_held_store(client):
    """Without a route this is all invisible from outside the process, which is where
    every one of these investigations has had to start."""
    body = client.get("/diagnostics/wal-keepalive").json()
    assert body["backend"] in ("sqlite", "postgres")
    assert body["max"] == 256
    assert isinstance(body["stores"], list)
    assert {"path", "shm_at_attach", "shm_now", "shm_present", "drifted"} <= set(
        body["stores"][0]) if body["stores"] else True


def test_health_stays_ok_while_every_store_holds_its_wal(client):
    body = client.get("/health").json()
    assert body["stores"]["ok"] is True
    assert body["stores"]["wal_drifted"] == []


def test_health_goes_degraded_when_a_store_loses_its_wal_index(client, monkeypatch):
    """A condition with no in-process repair has to reach an operator the way a ledger
    integrity failure does. A log line is not that."""
    from aughor.db import backend
    real = backend.wal_keepalive_report

    def drifted():
        out = real()
        out["drifted_paths"] = ["/data/system.db"]
        return out

    monkeypatch.setattr(backend, "wal_keepalive_report", drifted)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["stores"]["ok"] is False
    assert body["stores"]["wal_drifted"] == ["/data/system.db"]
    assert "restart" in body["stores"]["detail"]


def test_the_duckdb_ops_attach_leaves_the_wal_index_alone(tmp_path):
    """A second SQLite library inside one process is a real hazard, and we run one.

    `AughorOpsConnection` ATTACHes the live `system.db` through duckdb's sqlite
    extension, which links its OWN copy of SQLite. POSIX advisory locks never conflict
    within a process, so that copy can be granted the exclusive lock SQLite treats as
    "nobody else is here" — and `unixOpenSharedMemory` truncates the `-shm` to zero when
    it gets it. That would strand every mapping we hold.

    Measured 2026-08-24: it does not, with `READ_ONLY`. This pins the boundary, because
    the first probe of it watched the INODE and reported "safe" for the wrong reason —
    truncation leaves the inode identical.
    """
    duckdb = pytest.importorskip("duckdb")
    import sqlite3

    db = tmp_path / "system.db"
    seed = sqlite3.connect(str(db))
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE task_history (span_id TEXT)")
    seed.executemany("INSERT INTO task_history VALUES (?)", [(f"s{i}",) for i in range(500)])
    seed.commit()
    seed.close()

    from aughor.db.backend import _hold_wal_open, _shm_state
    _hold_wal_open(db)
    before = _shm_state(str(db))
    assert before is not None, "no WAL index to protect — the probe proves nothing"

    d = duckdb.connect(":memory:")
    try:
        d.execute(f"ATTACH '{db.as_posix()}' AS aughor_ops (TYPE sqlite, READ_ONLY)")
        d.execute("SELECT count(*) FROM aughor_ops.task_history").fetchone()
    finally:
        d.close()

    assert _shm_state(str(db)) == before, (
        "duckdb's sqlite ATTACH moved the WAL index under our live mapping — every "
        "connection this process holds to that store is now one read from SIGBUS")


def test_a_store_whose_database_was_deleted_is_not_reported_as_drift(store):
    """A deleted database is a different fact from a stranded mapping, and only one of
    them is actionable.

    The fault needs a read THROUGH the mapping, and nothing reads a store that no longer
    exists. Found by running the full suite: hundreds of tests open temp stores and throw
    the directory away, and every one of them looked like drift — which would have left
    any long-lived process permanently "degraded" for a hazard it does not have. A
    per-tenant scratch store would do the same thing in production.
    """
    import shutil
    backend, key, db = store
    shutil.rmtree(db.parent, ignore_errors=True)
    assert not db.exists(), "the probe did not actually remove the store"

    assert backend.check_wal_drift() == []
    entry = next(s for s in backend.wal_keepalive_report()["stores"] if s["path"] == key)
    assert entry["gone"] is True
    assert entry["drifted"] is False


def test_the_serving_marker_is_not_committable(tmp_path, monkeypatch):
    """The pidfile is one machine's runtime state, and this repo is public.

    Caught in the browser-verification pass: a live API had written `data/.serving.pid`
    and it showed up as UNTRACKED — one `git add -A` from being published. That has
    happened here before with another session's files.
    """
    import subprocess
    from pathlib import Path

    from aughor.db import serving
    repo = Path(__file__).resolve().parents[2]
    marker = f"data/{serving.PIDFILE_NAME}"
    result = subprocess.run(["git", "check-ignore", marker], cwd=repo,
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f"{marker} is not gitignored — the name in `serving.PIDFILE_NAME` and the rule in "
        f".gitignore have drifted apart, and the file is one `git add -A` from a public repo")
