"""Arc SV-2 — rolling backups of the platform's own state (`aughor/db/backups.py`).

Every test builds its own state folder under ``tmp_path`` and points ``AUGHOR_STATE_DIR`` at it; nothing here opens the
suite's shared stores or a live one. The stores are raw SQLite files shaped like the platform's (the ledger's `events`
and `session_events`, the registry's `connections`, the audit's `audit_log`), each kept open by a writer in WAL mode the
way the API's keepalive keeps them, so a backup is always taken beside a live writer.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aughor.db import backups

NOW = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)


# ── a state folder shaped like the live one ────────────────────────────────────────

class State:
    def __init__(self, root: Path):
        self.root = root
        self.writers: dict[str, sqlite3.Connection] = {}

    def store(self, name: str, ddl: str) -> sqlite3.Connection:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")      # what a write leaves stays in the WAL, as between checkpoints
        c.executescript(ddl)
        self.writers[name] = c
        return c

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def close(self) -> None:
        for c in self.writers.values():
            c.close()
        self.writers.clear()


LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL,
  conn_id TEXT, canvas_id TEXT, job_id TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS session_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
  trace_id TEXT NOT NULL, kind TEXT NOT NULL, model TEXT, payload TEXT);
"""


def _event(c, at: datetime, kind: str, payload: dict) -> None:
    c.execute("INSERT INTO events(at, kind, payload) VALUES (?, ?, ?)", (at.isoformat(), kind, json.dumps(payload)))


def _model_call(c, at: datetime, model: str) -> None:
    c.execute("INSERT INTO session_events(at, trace_id, kind, model) VALUES (?, 't', 'llm_call', ?)",
              (at.isoformat(), model))


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "state"
    root.mkdir()
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(root))
    monkeypatch.setenv(backups.FREE_FLOOR_ENV, "0")       # a test machine's disk is not the question
    monkeypatch.setattr("aughor.db.serving.serving_pid", lambda: None)
    # The suite runs no clock (conftest); here /health is read as the serving API reads it, where the clock runs.
    monkeypatch.delenv("AUGHOR_DISABLE_SCHEDULERS", raising=False)
    s = State(root)
    led = s.store("system.db", LEDGER_DDL)
    _event(led, NOW - timedelta(days=2), "job.finished", {"ok": True})
    _model_call(led, NOW - timedelta(days=2), "model-a")
    reg = s.store("connections.db", "CREATE TABLE connections (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                                    "conn_type TEXT NOT NULL, dsn_enc TEXT NOT NULL, meta TEXT, org_id TEXT)")
    reg.execute("INSERT INTO connections VALUES ('c1', 'Shop', 'duckdb', 'x', '{}', 'default')")
    reg.execute("INSERT INTO connections VALUES ('c2', 'Old CRM', 'postgres', 'y', '{}', 'default')")
    aud = s.store("audit.db", "CREATE TABLE audit_log (id INTEGER PRIMARY KEY, at TEXT, sql TEXT)")
    aud.execute("INSERT INTO audit_log(at, sql) VALUES ('2026-10-25', 'SELECT 1')")
    s.store("checkpoints.db", "CREATE TABLE checkpoints (id TEXT)").execute("INSERT INTO checkpoints VALUES ('r1')")
    s.store("qdrant/collection/docs/storage.sqlite", "CREATE TABLE points (id TEXT, v BLOB)").execute(
        "INSERT INTO points VALUES ('p1', x'00')")
    s.write("qdrant/.lock", "locked")
    s.write("qdrant/meta.json", '{"collections": {}}')
    s.write("metrics.instance.json", '{"metrics": []}')
    s.write("episodes_c1.jsonl", '{"e": 1}\n')
    s.write("glossary.instance.yaml", "terms: []\n")
    s.write("uploads/default/c1/orders.csv", "id,total\n1,10\n")
    s.write("uploads/default/c1/_removed_seeds.json", json.dumps({"schemas": [], "tables": ["seed_a"]}))
    s.write("uploads/default/c1/import.log", "a person's upload that happens to be a log")
    s.write("documents/default/d1/original.md", "# A document\n")
    s.write("sheets/default/s1/original.csv", "a,b\n1,2\n")
    (s.root / "sheets/default/s1/source.parquet").write_bytes(b"PAR1" + b"\x00" * 64 + b"PAR1")
    (s.root / "sheets/default/projection.duckdb").write_bytes(b"\x00" * 8 + b"DUCK" + b"\x00" * 64)
    (s.root / "sheets/default/projection.duckdb.wal").write_bytes(b"\x01" * 32)
    s.write("sheets/default/projection.marks.json", "{}")
    (s.root / "mat_cache.duckdb").write_bytes(b"\x00" * 8 + b"DUCK" + b"\x00" * 64)
    (s.root / "mat_cache.duckdb.wal").write_bytes(b"\x01" * 32)
    s.write("api_sync/hubspot.duckdb", "")                     # a DuckDB file being made: no header yet
    s.write("mat_cache.duckdb.tmp/spill_0.block", "x")          # the folder DuckDB spills into
    s.write("supervisor.log", "started\n")
    s.write("system.db.corrupt.bak", "an old damaged copy")
    s.write("_backup_freshrun_20260623/system.db", "a hand-made backup")
    s.write("luxexperience_warehouse/orders.parquet", "a person's own warehouse")
    s.write(".aughor_key", "secret")
    s.write(".serving.pid", "not a pid")
    s.write(".DS_Store", "finder")
    os.symlink(tmp_path, s.root / "elsewhere_link")
    yield s
    s.close()


def _take(**kw):
    kw.setdefault("now", NOW)
    return backups.take(**kw)


def _stored(folder: Path, entry: dict) -> bytes:
    data = (folder / entry["stored"]).read_bytes()
    return gzip.decompress(data) if entry["kind"] == "sqlite" else data


def _rows(path: Path, table: str) -> int:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


def _fingerprints(root: Path) -> dict:
    """Every file, by size and mtime — what a backup must not change. A `-shm` and an EMPTY `-wal` are left out, as
    the module's own fingerprint leaves them out: SQLite makes both whenever a reader opens a WAL store that had none,
    and neither holds a row."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.name.endswith("-wal") and p.is_file() and p.stat().st_size == 0:
            continue
        if p.is_file() and not p.name.endswith("-shm") and "backups" not in p.relative_to(root).parts:
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return out


# ── what is copied, and what is named ──────────────────────────────────────────────

def test_a_backup_copies_every_store_but_checkpoints_and_names_everything_it_leaves(state):
    out = _take()
    assert out.status == "taken", out.reason
    manifest = json.loads((out.folder / "manifest.json").read_text())
    sources = manifest["sources"]
    assert {r for r, e in sources.items() if e["kind"] == "sqlite"} == {
        "system.db", "connections.db", "audit.db", "qdrant/collection/docs/storage.sqlite"}
    assert {"metrics.instance.json", "episodes_c1.jsonl", "glossary.instance.yaml", "qdrant/meta.json",
            "uploads/default/c1/orders.csv", "uploads/default/c1/_removed_seeds.json",
            "uploads/default/c1/import.log", "documents/default/d1/original.md", "sheets/default/s1/original.csv",
            "sheets/default/s1/source.parquet"} <= set(sources)
    why = {i["path"]: i["why"] for i in manifest["not_copied"]}
    assert "resume points" in why["checkpoints.db"]
    assert "DuckDB" in why["mat_cache.duckdb"] and "DuckDB" in why["mat_cache.duckdb.wal"]
    assert "DuckDB" in why["api_sync/hubspot.duckdb"]           # by its name, before it has a header to read
    assert "DuckDB" in why["mat_cache.duckdb.tmp"]
    assert "projection" in why["sheets/default/projection.duckdb"]
    assert "projection" in why["sheets/default/projection.duckdb.wal"]
    # its stamps too: restored, they would match the restored stores and leave the newer projection unrebuilt
    assert "projection" in why["sheets/default/projection.marks.json"]
    assert "backup taken by hand" in why["_backup_freshrun_20260623"]
    assert "never touches" in why["luxexperience_warehouse"]
    assert "secret key" in why[".aughor_key"]
    assert "log" in why["supervisor.log"] and "copy already" in why["system.db.corrupt.bak"]
    assert "link" in why["elsewhere_link"] and "lock" in why["qdrant/.lock"]
    assert why["system.db-wal"] == backups._WHY_SIDECAR
    # Named at the top and never entered: nothing inside a folder that is not copied is listed, or read.
    assert not [p for p in why if p.startswith(("luxexperience_warehouse/", "_backup_freshrun_20260623/"))]
    # Every entry of the state folder is either copied or named — nothing is skipped in silence.
    named = set(sources) | set(why)
    for p in state.root.rglob("*"):
        rel = p.relative_to(state.root).as_posix()
        if p.is_dir() or rel.startswith("backups/"):
            continue
        assert rel in named or any(rel.startswith(n + "/") for n in why), rel


def test_a_wal_store_is_copied_with_what_sits_in_its_wal(state):
    led = state.writers["system.db"]
    for i in range(50):
        _event(led, NOW, "job.finished", {"i": i})
    assert (state.root / "system.db-wal").stat().st_size > 0        # the writes are in the WAL, not the file
    out = _take()
    entry = json.loads((out.folder / "manifest.json").read_text())["sources"]["system.db"]
    copy = out.folder.parent / "_check.db"
    copy.write_bytes(_stored(out.folder, entry))
    assert _rows(copy, "events") == 51 == entry["rows"]["events"]
    c = sqlite3.connect(copy)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"   # one self-contained file
    c.close()
    assert entry["sha256"] == backups._sha256(out.folder / entry["stored"])


def test_the_counts_and_the_copy_read_one_snapshot(state, monkeypatch):
    """A write landing between the row counts and the copy must not make a sound copy look short: both are read in one
    read transaction. Without it the copy holds a row the counts did not, and the check refuses a good backup."""
    real = backups._table_rows
    writer = state.writers["system.db"]
    calls = {"n": 0}

    def counting_then_a_write(conn, schema="main"):
        got = real(conn, schema)
        if conn.execute("PRAGMA database_list").fetchone()[2].endswith("/system.db") and not calls["n"]:
            calls["n"] += 1                       # right after the live ledger's counts, before its copy
            _event(writer, NOW, "job.finished", {"late": True})
        return got

    monkeypatch.setattr(backups, "_table_rows", counting_then_a_write)
    out = _take()
    assert out.status == "taken", out.failed
    entry = json.loads((out.folder / "manifest.json").read_text())["sources"]["system.db"]
    assert entry["rows"]["events"] == 1            # the snapshot, not the write that landed after it


def test_a_backup_writes_nothing_into_what_it_copies(state):
    before = _fingerprints(state.root)
    _take()
    after = _fingerprints(state.root)
    # The only new files outside backups/ may be the empty -wal a read-only open leaves on a store that had none.
    assert after == before


# ── only when something changed ────────────────────────────────────────────────────

def test_nothing_changed_takes_no_backup_and_says_so(state):
    first = _take()
    second = _take(now=NOW + timedelta(hours=1))
    assert second.status == "unchanged" and first.stamp in second.reason
    assert [b.name for b in backups.list_backups()] == [first.stamp]
    last = backups.read_last_run()
    assert last["outcome"] == "unchanged" and last["latest"] == first.stamp


def test_an_unchanged_source_is_hard_linked_and_survives_its_first_backup_being_pruned(state):
    first = _take()
    state.write("metrics.instance.json", '{"metrics": ["revenue"]}')
    second = _take(now=NOW + timedelta(hours=1))
    assert second.status == "taken" and second.copied == 1, (second.copied, second.linked)
    m2 = json.loads((second.folder / "manifest.json").read_text())["sources"]
    assert m2["metrics.instance.json"]["how"] == "copied"
    assert m2["system.db"]["how"] == "linked" and m2["system.db"]["from"] == first.stamp
    assert (second.folder / m2["system.db"]["stored"]).stat().st_ino == \
           (first.folder / m2["system.db"]["stored"]).stat().st_ino
    shutil.rmtree(first.folder)                    # pruning one backup never breaks another
    for rel, e in m2.items():
        assert backups._sha256(second.folder / e["stored"]) == e["sha256"], rel


def test_a_write_that_sits_only_in_the_wal_counts_as_a_change(state):
    """A WAL store's file does not change while its writes sit in the WAL — measured on the live install."""
    first = _take()
    db_stat = (state.root / "system.db").stat()
    _model_call(state.writers["system.db"], NOW, "model-b")
    assert (state.root / "system.db").stat().st_mtime_ns == db_stat.st_mtime_ns
    second = _take(now=NOW + timedelta(hours=1))
    assert second.status == "taken", second.reason
    m2 = json.loads((second.folder / "manifest.json").read_text())["sources"]
    assert m2["system.db"]["how"] == "copied" and m2["system.db"]["rows"]["session_events"] == 2
    assert first.stamp != second.stamp


def test_a_removed_file_is_a_change(state):
    _take()
    (state.root / "episodes_c1.jsonl").unlink()
    second = _take(now=NOW + timedelta(hours=1))
    assert second.status == "taken"
    assert "episodes_c1.jsonl" not in json.loads((second.folder / "manifest.json").read_text())["sources"]


# ── space, failure, unfinished ─────────────────────────────────────────────────────

def test_a_backup_that_would_cross_the_free_space_floor_is_skipped_and_said(state, monkeypatch):
    monkeypatch.setenv(backups.FREE_FLOOR_ENV, "1000000000")       # a billion GB: never free
    out = _take()
    assert out.status == "skipped_space" and "floor" in out.reason
    assert backups.list_backups() == []
    block = backups.health_block(now=NOW + timedelta(minutes=1))
    assert not block["ok"] and "floor" in block["skipped_for_space"]


def test_the_default_floor_is_ten_gib_or_a_tenth_of_the_disk(monkeypatch):
    monkeypatch.delenv(backups.FREE_FLOOR_ENV, raising=False)
    gib = 1024 ** 3
    assert backups.free_floor(50 * gib) == 10 * gib
    assert backups.free_floor(460 * gib) == 46 * gib
    monkeypatch.setenv(backups.FREE_FLOOR_ENV, "2.5")
    assert backups.free_floor(460 * gib) == int(2.5 * gib)


def test_a_copy_that_does_not_check_is_named_and_the_backup_says_it_is_incomplete(state, monkeypatch):
    real = backups._table_rows

    def short_copy(conn, schema="main"):
        got = real(conn, schema)
        file = conn.execute("PRAGMA database_list").fetchone()[2]
        if file.endswith("connections.db.copying"):
            got = {**got, "connections": got.get("connections", 0) - 1}
        return got

    monkeypatch.setattr(backups, "_table_rows", short_copy)
    out = _take()
    assert out.status == "failed" and "connections.db" in out.reason
    manifest = json.loads((out.folder / "manifest.json").read_text())
    assert manifest["complete"] is False and "connections.db" not in manifest["sources"]
    assert manifest["failed"][0]["path"] == "connections.db"
    assert not list(out.folder.rglob("*.copying")) and not (out.folder / "stores/connections.db.gz").exists()
    refused = backups.restore(out.stamp, confirm=lambda plan: True)
    assert refused.status == "refused" and "incomplete" in refused.reason


def test_an_unfinished_backup_is_ignored_by_readers_and_pruned(state):
    (state.root / "backups" / "2026-10-27T120000Z" / "stores").mkdir(parents=True)   # a crash before the manifest
    assert backups.list_backups() == []
    out = _take()
    assert "2026-10-27T120000Z" in out.pruned
    assert not (state.root / "backups" / "2026-10-27T120000Z").exists()


def test_pruning_keeps_what_retention_keeps_and_sv1_copies_thirty_days(state):
    bdir = state.root / "backups"
    stamps = [NOW - timedelta(hours=h) for h in range(0, 30)] + [NOW - timedelta(weeks=9)]
    for at in stamps:
        folder = bdir / backups._stamp(at)
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{}")
    # Twenty days back: one kept by its day, a labelled one the same day kept by its label, and one kept by neither.
    day20 = NOW - timedelta(days=20)
    for name in (backups._stamp(day20), backups._stamp(day20 - timedelta(hours=1)) + ".before-restore",
                 backups._stamp(day20 - timedelta(hours=2)), backups._stamp(NOW - timedelta(weeks=9)) + ".before-restore"):
        (bdir / name).mkdir()
        (bdir / name / "manifest.json").write_text("{}")
    young, old = bdir / "system.db.2026-10-20.v11-before-v12.bak", bdir / "system.db.2026-09-01.v10-before-v11.bak"
    for path, age in ((young, timedelta(days=7)), (old, timedelta(days=40))):
        path.write_text("copy")
        t = (NOW - age).timestamp()
        os.utime(path, (t, t))
    gone = set(backups.prune(now=NOW))
    left = {b.name for b in backups.list_backups()}
    assert backups._stamp(NOW - timedelta(weeks=9)) in gone          # nothing older than eight weeks
    assert backups._stamp(NOW - timedelta(hours=29)) in gone         # the 25th hour, in a day already kept
    assert {backups._stamp(NOW - timedelta(hours=h)) for h in range(25)} <= left
    assert backups._stamp(day20) in left
    assert backups._stamp(day20 - timedelta(hours=1)) + ".before-restore" in left     # its day is used: its label
    assert backups._stamp(day20 - timedelta(hours=2)) in gone                         # neither
    assert backups._stamp(NOW - timedelta(weeks=9)) + ".before-restore" in gone       # a label never outlives the window
    assert young.exists() and not old.exists() and old.name in gone


# ── the clock and /health ──────────────────────────────────────────────────────────

def test_the_job_is_put_on_the_clock_when_it_starts(state):
    from aughor.monitors import scheduler
    try:
        scheduler._schedule_backups()
        job = scheduler._scheduler.get_job(scheduler.BACKUPS_JOB_ID)
        assert job is not None and job.func is scheduler.backup_state_once
    finally:
        if scheduler._scheduler.get_job(scheduler.BACKUPS_JOB_ID) is not None:
            scheduler._scheduler.remove_job(scheduler.BACKUPS_JOB_ID)


def test_the_hourly_run_happens_only_in_the_serving_process_and_at_most_hourly(state, monkeypatch):
    monkeypatch.setattr("aughor.db.serving.serving_pid", lambda: os.getpid() + 1)
    assert backups.run_scheduled(now=NOW).status == "not_serving"
    assert not (state.root / "backups").exists()
    monkeypatch.setattr("aughor.db.serving.serving_pid", lambda: os.getpid())
    assert backups.run_scheduled(now=NOW).status == "taken"
    assert backups.run_scheduled(now=NOW + timedelta(minutes=30)).status == "not_due"
    state.write("metrics.instance.json", '{"changed": true}')
    assert backups.run_scheduled(now=NOW + timedelta(minutes=61)).status == "taken"


def test_health_says_what_the_last_backup_did(state, monkeypatch):
    from aughor.routers.system import health
    monkeypatch.setattr(backups, "_now", lambda: NOW + timedelta(minutes=5))
    empty = health()["backups"]
    assert empty["ok"] is False and "no backup" in empty["detail"]
    out = _take()
    body = health()
    assert body["backups"]["ok"] and body["backups"]["last_backup"] == out.stamp
    assert body["backups"]["copied"] == out.copied and body["backups"]["total_bytes"] > 0
    assert list(body)[:4] == ["status", "ledger", "migrations", "backups"]
    monkeypatch.setattr(backups, "_now", lambda: NOW + timedelta(hours=3))
    stale = health()
    assert stale["status"] == "degraded" and "3.0 hours" in stale["backups"]["detail"]


def test_health_says_where_the_clock_never_runs_and_is_not_degraded_by_it(state, monkeypatch):
    """No backup is ever taken where the clock never runs — a test process, a serverless instance. Said, with `ok`
    None, never read as a failing backup: a process that never keeps the state is not failing to keep it."""
    from aughor.routers.system import health
    monkeypatch.setenv("AUGHOR_DISABLE_SCHEDULERS", "1")
    block = backups.health_block(now=NOW)
    assert block["ok"] is None and "clocks are off" in block["detail"]
    body = health()
    assert body["backups"]["ok"] is None and body["status"] == "ok", body
    monkeypatch.setenv("VERCEL", "1")
    block = backups.health_block(now=NOW)
    assert block["ok"] is None and "serverless" in block["detail"]


def test_a_failed_backup_degrades_health(state, monkeypatch):
    real = backups._copy_file

    def fail_on_metrics(source, folder):
        if source.rel == "metrics.instance.json":
            raise OSError(13, "Permission denied")
        return real(source, folder)

    monkeypatch.setattr(backups, "_copy_file", fail_on_metrics)
    _take()
    block = backups.health_block(now=NOW + timedelta(minutes=1))
    assert block["ok"] is False and "metrics.instance.json" in block["last_error"]


# ── restore ────────────────────────────────────────────────────────────────────────

def _after_the_backup(state: State) -> None:
    """What happens after a backup: a removal approved, rows written, a model call, a query audited, a seed removed,
    an upload removed, a file made."""
    led, reg, aud = state.writers["system.db"], state.writers["connections.db"], state.writers["audit.db"]
    later = NOW + timedelta(hours=2)
    _event(led, later, "action.approval", {"action": "connection.delete", "decision": "approved", "scope": "c2",
                                           "actor": "user:amit"})
    _event(led, later, "action.approval", {"action": "metric.define", "decision": "auto", "scope": "c1"})
    _model_call(led, later, "model-b")
    reg.execute("DELETE FROM connections WHERE id = 'c2'")
    aud.execute("INSERT INTO audit_log(at, sql) VALUES ('2026-10-27', 'SELECT 2')")
    state.write("uploads/default/c1/_removed_seeds.json", json.dumps({"schemas": ["seed_s"],
                                                                     "tables": ["seed_a", "seed_b"]}))
    (state.root / "uploads/default/c1/orders.csv").unlink()
    state.write("uploads/default/c3/new.csv", "made after the backup\n")


def test_a_restore_is_refused_while_the_api_serves(state, monkeypatch):
    out = _take()
    monkeypatch.setattr("aughor.db.serving.serving_pid", lambda: 4242)
    asked = []
    refused = backups.restore(out.stamp, confirm=lambda plan: asked.append(plan) or True)
    assert refused.status == "refused" and "pid 4242" in refused.reason
    assert asked == [] and [b.name for b in backups.list_backups()] == [out.stamp]


def test_a_restore_lists_what_it_brings_back_asks_and_puts_the_backup_back(state):
    out = _take(now=NOW)
    _after_the_backup(state)
    state.close()                                  # the API is stopped
    audit_before = (state.root / "audit.db").read_bytes()
    plans = []
    done = backups.restore(out.stamp, confirm=lambda plan: plans.append(plan) or True)
    assert done.status == "restored", (done.reason, done.problems)
    plan = plans[0]
    said = "\n".join(plan["removals"])
    assert "connection Old CRM (c2)" in said
    assert "connection.delete of c2 by user:amit" in said and "metric.define" not in said
    assert "seed_s" in said and "seed_b" in said
    assert "uploads/default/c1/orders.csv" in said or "uploads/default/…" in said
    assert any("uploads/default" in line for line in plan["set_aside"])
    assert any("audit.db" in k for k in plan["kept"]) and any("session_events" in k for k in plan["kept"])
    # The backup's state is back …
    assert _rows(state.root / "connections.db", "connections") == 2
    assert _rows(state.root / "system.db", "events") == 1
    assert (state.root / "uploads/default/c1/orders.csv").read_text() == "id,total\n1,10\n"
    assert json.loads((state.root / "uploads/default/c1/_removed_seeds.json").read_text())["tables"] == ["seed_a"]
    assert not (state.root / "uploads/default/c3/new.csv").exists()
    # … but never over the record of what happened.
    assert (state.root / "audit.db").read_bytes() == audit_before
    assert _rows(state.root / "system.db", "session_events") == 2
    for side in ("-wal", "-shm"):
        assert not (state.root / f"system.db{side}").exists()        # the present's WAL never meets the old file
    # The present is kept as a labelled backup, and the scratch folders are gone.
    labelled = [b for b in backups.list_backups() if b.label == backups.BEFORE_RESTORE]
    assert len(labelled) == 1 and done.before_restore == labelled[0].name
    kept = json.loads((labelled[0].folder / "manifest.json").read_text())["sources"]
    assert "uploads/default/c3/new.csv" in kept
    assert not [p for p in (state.root / "backups").iterdir() if p.name.startswith((".aside-", ".restoring-"))]


def test_a_declined_restore_changes_nothing(state):
    out = _take()
    _after_the_backup(state)
    state.close()
    before = _fingerprints(state.root)
    declined = backups.restore(out.stamp, confirm=lambda plan: False)
    assert declined.status == "declined"
    assert _fingerprints(state.root) == before
    assert [b.name for b in backups.list_backups()] == [out.stamp]


def test_a_restore_that_does_not_check_in_place_puts_the_originals_back(state, monkeypatch):
    out = _take()
    _after_the_backup(state)
    state.close()
    before = {rel: (state.root / rel).read_bytes() for rel in ("system.db", "connections.db",
                                                                "uploads/default/c1/_removed_seeds.json",
                                                                "uploads/default/c3/new.csv")}
    real = backups._check_store

    def fails_in_place(path, entry, skip):
        if path.parent == state.root and path.name == "connections.db":
            return ["the disk returned something else"]
        return real(path, entry, skip)

    monkeypatch.setattr(backups, "_check_store", fails_in_place)
    failed = backups.restore(out.stamp, confirm=lambda plan: True)
    assert failed.status == "failed" and "originals are back" in failed.reason
    assert {rel: (state.root / rel).read_bytes() for rel in before} == before
    assert not (state.root / "uploads/default/c1/orders.csv").exists()   # what was gone stays gone
    assert failed.before_restore in {b.name for b in backups.list_backups()}
    assert not [p for p in (state.root / "backups").iterdir() if p.name.startswith((".aside-", ".restoring-"))]


def test_a_backup_whose_copy_was_damaged_is_refused_before_anything_moves(state):
    out = _take()
    state.close()
    entry = json.loads((out.folder / "manifest.json").read_text())["sources"]["connections.db"]
    stored = out.folder / entry["stored"]
    stored.unlink()                                 # a hard link: write a new file, never into the shared one
    stored.write_bytes(gzip.compress(b"not the store"))
    before = _fingerprints(state.root)
    failed = backups.restore(out.stamp, confirm=lambda plan: True)
    assert failed.status == "failed" and any("connections.db" in p for p in failed.problems)
    assert _fingerprints(state.root) == before
    assert not [b for b in backups.list_backups() if b.label]


def test_a_damaged_store_does_not_block_its_own_restore(state):
    """The restore is for the day a store is damaged: neither the copy of the present nor the model-call log it cannot
    carry may refuse it. The damaged file is kept beside the backups, and the restore says so."""
    out = _take()
    _after_the_backup(state)
    state.close()
    db = state.root / "system.db"
    damaged = db.read_bytes()[:100] + os.urandom(db.stat().st_size - 100)
    db.write_bytes(damaged)
    for side in ("-wal", "-shm"):
        Path(f"{db}{side}").unlink(missing_ok=True)
    plans = []
    done = backups.restore(out.stamp, confirm=lambda plan: plans.append(plan) or True)
    assert done.status == "restored", (done.reason, done.problems)
    assert any(w.startswith("system.db:") for w in done.warnings) and "kept at" in done.reason
    assert (Path(done.kept_aside) / "system.db").read_bytes() == damaged
    assert _rows(db, "events") == 1                                   # the backup's ledger, readable again
    assert any("could not be read" in line for line in plans[0]["removals"])
    assert done.before_restore in {b.name for b in backups.list_backups()}


def test_a_manifest_newer_than_this_version_reads_is_refused(state):
    out = _take()
    path = out.folder / "manifest.json"
    manifest = json.loads(path.read_text())
    path.write_text(json.dumps({**manifest, "format": backups.MANIFEST_FORMAT + 1}))
    refused = backups.restore(out.stamp, confirm=lambda plan: True)
    assert refused.status == "refused" and "newer" in refused.reason


def test_a_stamp_prefix_names_one_backup(state):
    out = _take()
    assert backups.resolve(out.stamp[:13]).name == out.stamp
    with pytest.raises(LookupError):
        backups.resolve("1999")


# ── the names this module keys on are the stores' own ──────────────────────────────

def test_the_files_it_keys_on_are_what_the_stores_resolve():
    """Name-keyed rules drift silently when a store renames its file; these read each store's own default."""
    pytest.importorskip("langgraph.checkpoint.sqlite", reason="the checkpoint store needs langgraph")
    from aughor.agent import graph
    from aughor.connectors.file import local_upload
    from aughor.db import purge, registry
    from aughor.kernel import ledger
    from aughor.security import audit
    assert audit._DB_PATH.name in backups.NEVER_RESTORED
    assert ledger._DEFAULT_DB.name in backups.CARRIED_FORWARD
    assert registry.REGISTRY_DB.name == backups._REGISTRY_FILE
    assert graph._CHECKPOINT_DB.name in backups._NOT_COPIED_TOP
    assert local_upload._TOMBSTONE_FILE == backups._TOMBSTONE_NAME
    # The two records a removal keeps are the two a restore never rolls back.
    assert set(purge.KEPT_ON_DELETE) == {"audit_log", "session_events"}
    assert "session_events" in backups.CARRIED_FORWARD[ledger._DEFAULT_DB.name]


# ── the CLI ────────────────────────────────────────────────────────────────────────

def test_the_cli_lists_backups_and_refuses_a_restore_while_serving(state, monkeypatch):
    from click.testing import CliRunner

    from aughor.cli import cli
    monkeypatch.setenv("AUGHOR_SKIP_DOTENV", "1")
    out = _take()
    runner = CliRunner()
    listed = runner.invoke(cli, ["backups"])
    assert listed.exit_code == 0 and out.stamp in listed.output
    shown = runner.invoke(cli, ["backups", out.stamp])
    assert shown.exit_code == 0 and "checkpoints.db" in shown.output
    monkeypatch.setattr("aughor.db.serving.serving_pid", lambda: 4242)
    refused = runner.invoke(cli, ["restore", out.stamp, "--yes"])
    assert refused.exit_code == 1 and "4242" in refused.output
