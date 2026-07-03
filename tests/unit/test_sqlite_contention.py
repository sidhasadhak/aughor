"""REC-03 / DATA-02 — every SQLite store waits for a lock instead of failing.

Without ``PRAGMA busy_timeout`` (SQLite's default is 0ms), the instant two
writers overlap the second raises ``SQLITE_BUSY``. In the kernel that surfaced
as a tolerated heartbeat write failing → the job later swept as a false orphan
and marked FAILED. ``sqlite_util.tune`` sets busy_timeout on every connection;
this test proves overlapping writers no longer collide, and guards against a new
connect site forgetting to call ``tune``.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys

from aughor.db.sqlite_util import tune


def test_no_busy_error_under_overlapping_writers(tmp_path):
    import threading

    p = tmp_path / "t.db"
    a = tune(sqlite3.connect(p, check_same_thread=False))
    b = tune(sqlite3.connect(p, check_same_thread=False))
    a.execute("CREATE TABLE t(x)")
    a.commit()

    # A holds a write transaction open; B (on another thread) writes into the same
    # db. Without busy_timeout, B's INSERT raises sqlite3.OperationalError: database
    # is locked immediately. With busy_timeout=5000 it waits for A to release.
    a.execute("BEGIN IMMEDIATE")
    a.execute("INSERT INTO t VALUES (1)")

    err = {}
    reached = threading.Event()

    def _writer():
        reached.set()
        try:
            b.execute("INSERT INTO t VALUES (2)")  # blocks on A's lock, up to 5s
            b.commit()
        except Exception as exc:  # pragma: no cover - failure path
            err["exc"] = exc

    th = threading.Thread(target=_writer)
    th.start()
    reached.wait(timeout=5)
    a.commit()  # release the lock so B (waiting) can proceed
    th.join(timeout=10)

    assert not err, f"overlapping writer hit {err.get('exc')!r} — busy_timeout not applied"
    assert a.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2


def test_tune_sets_the_expected_pragmas(tmp_path):
    conn = tune(sqlite3.connect(tmp_path / "t.db"))
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    # REC-10c: a baseline schema version is stamped (nonzero after tune).
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_user_version_baseline_and_explicit_bump(tmp_path):
    from aughor.db.sqlite_util import set_user_version

    p = tmp_path / "v.db"
    conn = tune(sqlite3.connect(p))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1  # baseline
    set_user_version(conn, 3)  # a migration bumps it
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    # tune must NOT downgrade an already-migrated store.
    tune(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_registry_reports_migrated_schema_version():
    """The registry ships an org_id migration → its marker is bumped past baseline."""
    from aughor.db.registry import _db
    with _db() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 2


def test_every_store_is_isolated_from_live_data():
    """REC-04 / OPS-02 — under the test env (conftest sets AUGHOR_*_DB to a temp
    dir), NO store may resolve to the live repo ``data/`` directory. This is the
    guard that prevents a full-suite run from mutating real data, server-independent
    (a live dev server writing data/ can't mask a genuine isolation regression here).
    """
    from pathlib import Path as _P

    from aughor.db import history, registry
    from aughor.metastore import store as metastore_store
    from aughor.workspace import store as workspace_store
    from aughor.security import audit
    from aughor.canvas import store as canvas_store
    from aughor.evidence import store as evidence_store
    from aughor.monitors import store as monitors_store
    from aughor.org import store as org_store
    from aughor.savedquery import store as savedquery_store
    from aughor.volumes import store as volumes_store
    from aughor.verify import verdicts
    from aughor.packs import deltastore, bindings
    from aughor.agent import graph
    from aughor.util import idempotency

    live_data = (_P(__file__).parent.parent.parent / "data").resolve()
    stores = {
        "history": history._DB_PATH,
        "registry": registry.REGISTRY_DB,
        "metastore": metastore_store._DB_PATH,
        "workspaces": workspace_store._DB_PATH,
        "audit": audit._DB_PATH,
        "canvas": canvas_store._DB_PATH,
        "artifacts": canvas_store._ARTIFACT_DB_PATH,
        "evidence": evidence_store._DB_PATH,
        "monitors": monitors_store._DB_PATH,
        "orgs": org_store._DB_PATH,
        "savedquery": savedquery_store._DB_PATH,
        "volumes": volumes_store._DB_PATH,
        "verdicts": verdicts._DB_PATH,
        "pack_deltas": deltastore._DB_PATH,
        "pack_bindings": bindings._DB_PATH,
        "checkpoints": graph._CHECKPOINT_DB,
        "idempotency": idempotency._DB_PATH,
    }
    leaked = {n: str(p) for n, p in stores.items()
              if live_data in _P(p).resolve().parents}
    assert not leaked, f"stores NOT isolated from live data/ (would mutate real data): {leaked}"


def test_every_store_connect_site_is_tuned():
    """Mechanical guard: any file that opens a SQLite connection must also tune it
    (or set busy_timeout directly). The one intentional exception is the user-file
    connector, which opens the caller's own DB read-only and must not rewrite it."""
    out = subprocess.run(
        ["grep", "-rl", "sqlite3.connect", "aughor", "--include=*.py"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    ALLOWED_UNTUNED = {"aughor/connectors/file/sqlite.py"}
    offenders = []
    for f in out:
        text = open(f).read()
        if "tune(" not in text and "busy_timeout" not in text and f not in ALLOWED_UNTUNED:
            offenders.append(f)
    assert not offenders, f"connect sites missing tune()/busy_timeout: {offenders}"
