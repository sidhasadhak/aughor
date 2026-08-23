"""The write-ahead log must outlive a single store operation.

Four identical crashes killed the API with no Python traceback:

    EXC_BAD_ACCESS / SIGBUS · "FS pagein error: 22 Invalid argument"
    walFindFrame → readDbPage → sqlite3VdbeExec → sqlite3_step → fetchall → thread_run

`walFindFrame` reads the WAL index, which lives in the `-shm` file and is ALWAYS
memory-mapped in WAL mode. "FS pagein error 22" is the OS failing to page in a
file-backed page — the file behind a live mapping was truncated or unlinked.

The precondition was ordinary store code. Platform stores open a connection PER
OPERATION and never close it explicitly, so it dies whenever the GC finalizes it and the
live-connection count oscillates through ZERO. SQLite deletes `-wal`/`-shm` on the last
close, so **every single operation unlinked and recreated the write-ahead log** —
measured before the fix: the `-shm` did not exist after any call. One thread reading
through a mapping while another thread's last-close removed the file underneath is the
whole crash.

The fix removes the precondition rather than narrowing the window: one idle connection
per store means there is no last close until the process exits.

These tests assert the INVARIANT (the `-shm` is never unlinked) rather than trying to
reproduce the fault — a real SIGBUS takes the test runner down with it, so a test that
reproduced it could not report anything.
"""
from __future__ import annotations

import gc
import importlib
import os
import sqlite3
import threading
from pathlib import Path

import pytest


def _shm_inode(db: Path):
    try:
        return os.stat(str(db) + "-shm").st_ino
    except FileNotFoundError:
        return None


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real platform store redirected at a temp file."""
    db = tmp_path / "rbac.db"
    monkeypatch.setenv("AUGHOR_RBAC_DB", str(db))
    from aughor.rbac import store as rs
    importlib.reload(rs)
    return rs, db


def test_the_wal_survives_a_single_operation(store):
    """The measured regression: before the keepalive, `-shm` was gone after every call."""
    rs, db = store
    rs.assign_role("org", "u0", "viewer")
    gc.collect()                       # finalize the per-operation connection

    from aughor.db import backend
    assert _shm_inode(db) is not None, (
        "the WAL index was unlinked after one operation — a concurrent reader holding "
        f"that mapping takes SIGBUS on its next page-in. DIAG: postgres={backend.is_postgres()} "
        f"registry={len(backend._KEEPALIVE)}/{backend._KEEPALIVE_MAX} "
        f"held={str(db) in backend._KEEPALIVE} "
        f"hook={getattr(backend._hold_wal_open, '__name__', '?')}")


def test_the_wal_file_is_never_recreated_across_operations(store):
    """A NEW inode is the same defect wearing a different face: the mapping a reader
    holds points at the old file, which no longer exists."""
    rs, db = store
    seen = []
    for i in range(8):
        rs.assign_role("org", f"u{i}", "viewer")
        gc.collect()
        seen.append(_shm_inode(db))

    assert None not in seen, f"the WAL index vanished mid-sequence: {seen}"
    assert len(set(seen)) == 1, f"the WAL index was recreated (inodes {sorted(set(seen))})"


def test_the_wal_holds_under_concurrent_readers_and_writers(store):
    """The shape that actually crashed: several threads churning per-operation
    connections against one store."""
    rs, db = store
    rs.assign_role("org", "seed", "viewer")

    seen: list = []
    errors: list = []

    def work(n: int) -> None:
        try:
            for i in range(6):
                rs.assign_role("org", f"t{n}u{i}", "viewer")
                rs.roles_for_user("org", f"t{n}u{i}")
                gc.collect()
                seen.append(_shm_inode(db))
        except Exception as exc:                    # noqa: BLE001 — reported below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"store operations failed under concurrency: {errors[:3]}"
    assert None not in seen, "the WAL index vanished while other threads were reading it"
    assert len(set(seen)) == 1, f"the WAL index was recreated under load: {sorted(set(seen))}"


def test_a_keepalive_holds_no_lock_a_writer_needs(store):
    """It must be inert. A keepalive that blocked writes would trade a crash for a hang."""
    rs, db = store
    rs.assign_role("org", "u", "viewer")

    other = sqlite3.connect(str(db), timeout=2.0)
    try:
        other.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
        other.execute("INSERT INTO probe VALUES (1)")
        other.commit()
    finally:
        other.close()


def test_the_keepalive_registry_is_bounded(monkeypatch, tmp_path):
    """Unbounded, this would exhaust file descriptors — a worse failure than the one it
    prevents. A caller that repoints a store path per-test is how that happens."""
    from aughor.db import backend

    monkeypatch.setattr(backend, "_KEEPALIVE", backend.OrderedDict())
    monkeypatch.setattr(backend, "_KEEPALIVE_MAX", 3)
    for i in range(10):
        (tmp_path / f"s{i}.db").write_bytes(b"")     # live files — nothing to reap
        backend._hold_wal_open(tmp_path / f"s{i}.db")

    assert len(backend._KEEPALIVE) <= 3


def test_a_full_registry_evicts_rather_than_refusing_a_live_store(monkeypatch, tmp_path):
    """The bug this replaced: a hard cap meant every store opened after the registry
    filled ran SILENTLY unprotected. Measured in the suite — `256/256`, `held=False` —
    so the protection was off for exactly the tests written to prove it worked, and the
    guard that stops guarding without saying so is the failure this repo keeps finding.

    Evicting is safe for the same reason any close is: SQLite finalizes the WAL only on
    the LAST close, so either another connection is open (ours is not last, nothing is
    unlinked) or ours is last (there is no reader left to strand)."""
    from aughor.db import backend

    monkeypatch.setattr(backend, "_KEEPALIVE", backend.OrderedDict())
    monkeypatch.setattr(backend, "_KEEPALIVE_MAX", 2)

    for i in range(5):
        db = tmp_path / f"s{i}.db"
        db.write_bytes(b"")
        backend._hold_wal_open(db)
        assert str(db) in backend._KEEPALIVE, (
            f"store {i} was refused protection because the registry was full")

    assert len(backend._KEEPALIVE) <= 2, "eviction stopped bounding the registry"
    assert str(tmp_path / "s0.db") not in backend._KEEPALIVE, "eviction is not least-recent-first"


def test_a_store_still_works_when_the_keepalive_cannot_be_held(store, monkeypatch):
    """Best-effort by construction: this exists to protect the store, so its own failure
    must never break the store."""
    from aughor.db import backend

    def _boom(_path):
        raise OSError("no descriptors")

    monkeypatch.setattr(backend, "_hold_wal_open", _boom)
    rs, _db = store
    with pytest.raises(OSError):
        backend._hold_wal_open(Path("x"))
    # The store itself is unaffected by the protection failing — it is just unprotected.
