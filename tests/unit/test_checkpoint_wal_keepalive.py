"""The checkpoint store is the one #379 skipped — and it kept crashing the API.

#379 removed the SIGBUS precondition for every store on the `connect_store` seam: one
idle connection per store means SQLite never sees a last close, so `-wal`/`-shm` are
never unlinked under a live mapping. `tests/unit/test_store_wal_keepalive.py` asserts
that invariant and has passed ever since.

The API went on dying anyway. Measured 2026-08-23 from `~/Library/Logs/DiagnosticReports`:
five crashes across two days — 08-22 23:57, 08-23 00:58, 09:25, 18:21, 18:31 — all
identical, all `EXC_BAD_ACCESS / SIGBUS · "FS pagein error: 22"`, all faulting in
`walFindFrame`, with the fault address inside a 32 KB mapped-file region (a `-shm`).

`aughor/agent/graph.py` says why, in its own comment: the checkpointer is "deliberately
NOT on the connect_store seam" because LangGraph's `SqliteSaver` speaks to the connection
directly and wrapping it is unproven. That reasoning is sound and is not what these tests
change. What it missed is that opting out of the SEAM also opted out of the KEEPALIVE —
and `_checkpointer()` is not memoized, so every call opened a fresh WAL connection to a
151 MB store and dropped it on GC. Every call was a last close.

The existing suite could not catch this because it tests the MECHANISM against a store
that uses it. These test COVERAGE: that the store which opted out still holds its WAL,
and that a future store cannot opt out silently.

A real SIGBUS would take the runner down with it, so — like the sibling file — these
assert the invariant (`-shm` is never unlinked) rather than reproducing the fault.
"""
from __future__ import annotations

import gc
import importlib
import os
import re
import threading
from pathlib import Path

import pytest

pytest.importorskip("langgraph.checkpoint.sqlite", reason="langgraph not installed")


def _shm_inode(db: Path):
    try:
        return os.stat(str(db) + "-shm").st_ino
    except FileNotFoundError:
        return None


@pytest.fixture
def checkpoints(tmp_path, monkeypatch):
    """The real checkpoint module, redirected at a temp file.

    Reloaded because `_CHECKPOINT_DB` is resolved at import time — without the reload the
    test would exercise the developer's live 151 MB store, which is both slow and exactly
    the non-hermetic store access this repo has lost data to twice.
    """
    db = tmp_path / "checkpoints.db"
    monkeypatch.setenv("AUGHOR_CHECKPOINTS_DB", str(db))
    from aughor.agent import graph as g
    importlib.reload(g)
    # One read to create the file and its WAL; SqliteSaver sets up its schema lazily.
    g.read_checkpoint_values("seed-run")
    return g, db


def _diag(db: Path) -> str:
    from aughor.db import backend
    return (f"registry={len(backend._KEEPALIVE)}/{backend._KEEPALIVE_MAX} "
            f"held={str(db) in backend._KEEPALIVE}")


def test_the_checkpoint_wal_survives_a_single_read(checkpoints):
    """`_checkpointer()` is not memoized: each call is a fresh connection that dies on
    GC. Without a keepalive that is a last close, and a last close unlinks the `-shm` a
    concurrent reader is mapped into."""
    g, db = checkpoints
    g.read_checkpoint_values("run-1")
    gc.collect()                       # finalize the per-call connection

    assert _shm_inode(db) is not None, (
        "the checkpoint WAL index was unlinked after one read — a concurrent reader "
        f"holding that mapping takes SIGBUS on its next page-in. DIAG: {_diag(db)}")


def test_the_checkpoint_wal_is_not_recreated_across_reads(checkpoints):
    """A NEW inode is the same defect wearing a different face: the mapping a reader
    holds points at a file that no longer exists."""
    g, db = checkpoints
    seen = []
    for i in range(8):
        g.read_checkpoint_values(f"run-{i}")
        gc.collect()
        seen.append(_shm_inode(db))

    assert None not in seen, f"the checkpoint WAL index vanished mid-sequence: {seen}"
    assert len(set(seen)) == 1, (
        f"the checkpoint WAL index was recreated (inodes {sorted(set(seen))}) — "
        f"DIAG: {_diag(db)}")


def test_the_checkpoint_wal_holds_under_concurrent_readers(checkpoints):
    """The shape that actually crashed: one thread reading through the mapping while
    another thread's connection finalizes and takes the file with it."""
    g, db = checkpoints
    seen: list = []
    errors: list = []

    def work(n: int) -> None:
        try:
            for i in range(6):
                g.read_checkpoint_values(f"t{n}-run-{i}")
                g.read_checkpoint_state(f"t{n}-run-{i}")
                gc.collect()
                seen.append(_shm_inode(db))
        except Exception as exc:                    # noqa: BLE001 — reported below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"checkpoint reads failed under concurrency: {errors[:3]}"
    assert None not in seen, (
        "the checkpoint WAL index vanished while other threads were reading it — this is "
        f"the crash, reproduced without the fault. DIAG: {_diag(db)}")
    assert len(set(seen)) == 1, (
        f"the checkpoint WAL index was recreated under load: {sorted(set(seen))}")


def test_the_checkpoint_store_is_actually_registered(checkpoints):
    """Named separately from the invariant tests so a failure says WHY rather than only
    that an inode moved."""
    from aughor.db import backend
    _g, db = checkpoints
    assert str(db) in backend._KEEPALIVE, (
        "the checkpoint store holds no keepalive. It is off the `connect_store` seam by "
        "design (LangGraph owns that connection) — but opting out of the seam must not "
        "opt out of the WAL guarantee.")


# ── the coverage ratchet ────────────────────────────────────────────────────────

#: Every bare `sqlite3.connect(` in `aughor/` must be accounted for. A store that opens
#: its own connection is fine; a store that opens its own connection AND holds no
#: keepalive is the defect this file exists for, and it is invisible until the API dies
#: with no traceback. Adding a file here means deciding which of the two it is.
_SEAM_EXEMPT = {
    # Holds its own keepalive explicitly — see the call in `_checkpointer`.
    "aughor/agent/graph.py",
    # A USER's own SQLite file opened as a data source, not a platform store: its
    # lifetime is the connector's and it is never written by two of our threads.
    "aughor/connectors/file/sqlite.py",
    # One-shot read of a legacy file during migration; the process is not serving.
    "aughor/custom_agents/store.py",
    # The seam itself, and the tuning helper's docstring example.
    "aughor/db/backend.py",
    "aughor/db/sqlite_util.py",
}


def test_no_store_opens_sqlite_without_being_accounted_for():
    """The guard the last fix was missing.

    #379 protected every store on the seam and shipped. The one store that had opted out
    kept crashing the API for a further two days, because nothing anywhere asserted that
    opting out of the seam was a decision somebody made rather than a thing that happened.
    """
    root = Path(__file__).resolve().parents[2] / "aughor"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        if rel in _SEAM_EXEMPT:
            continue
        if re.search(r"\bsqlite3\.connect\(", path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == [], (
        f"{offenders} open SQLite directly, bypassing `connect_store` and therefore the "
        f"WAL keepalive. Either route them through `connect_store`, or call "
        f"`_hold_wal_open` on the path and add the file to _SEAM_EXEMPT with the reason.")


def test_the_exempt_list_has_not_gone_stale():
    """An exemption for a file that no longer opens SQLite is a hole waiting for the next
    author: the name stays on the list and stops meaning anything."""
    root = Path(__file__).resolve().parents[2]
    stale = [rel for rel in sorted(_SEAM_EXEMPT)
             if not re.search(r"\bsqlite3\.connect\(", (root / rel).read_text(encoding="utf-8"))]
    assert stale == [], f"{stale} no longer open SQLite directly — drop them from _SEAM_EXEMPT"
