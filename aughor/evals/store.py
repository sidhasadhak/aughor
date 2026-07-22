"""The Evals plane's store — suites, cases, runs, results.

Follows the ``verify/verdicts.py`` idiom exactly: ``resolve_db_path`` for the
path, ``org_id`` from the ambient tenant on every row AND every WHERE, versioned
migrations, clamped limits.

Deliberately NOT reusing ``evals/ratchet.py``'s ``data/eval_baseline.db``, which
is otherwise close in shape: it has no tenant column, so it cannot back a
product surface. Its *logic* (summarise → compare-to-baseline → persist) is the
right shape and is mirrored here.

One thing the ratchet could not do, which this fixes: a run records the **model
and config it ran under**. The ratchet's five historical runs share a
``mean_overall`` between 0.62 and 0.66 with no record of which model produced
them, so those numbers cannot be compared to a new run — the comparison would
silently mix harness changes with model changes.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aughor.db.migrations import Migration, run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.org.context import current_org_id

_DB_PATH = resolve_db_path("AUGHOR_EVALS_DB", Path("data/evals.db"))

#: Run lifecycle. A run that dies mid-flight stays RUNNING rather than being
#: silently reported as finished — an unfinished measurement must look unfinished.
RUNNING, SUCCEEDED, FAILED = "running", "succeeded", "failed"

#: Per-case verdicts across iterations. `flaky` is a first-class outcome, not a
#: rounding of pass/fail: a case that passes 2 of 3 times is telling you
#: something a percentage hides.
STABLE_PASS, STABLE_FAIL, FLAKY = "stable_pass", "stable_fail", "flaky"

_MIGRATIONS: list[Migration] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH), check_same_thread=False))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS eval_suites (
            id            TEXT PRIMARY KEY,
            org_id        TEXT NOT NULL,
            name          TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            target        TEXT NOT NULL DEFAULT 'reference',
            connection_id TEXT NOT NULL DEFAULT '',
            config        TEXT,
            created_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_eval_suites_org ON eval_suites (org_id, created_at);

        CREATE TABLE IF NOT EXISTS eval_cases (
            id         TEXT PRIMARY KEY,
            suite_id   TEXT NOT NULL,
            org_id     TEXT NOT NULL,
            question   TEXT NOT NULL DEFAULT '',
            artifact   TEXT NOT NULL DEFAULT '',
            expected   TEXT,
            tags       TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_eval_cases_suite ON eval_cases (suite_id, created_at);

        CREATE TABLE IF NOT EXISTS eval_runs (
            id          TEXT PRIMARY KEY,
            suite_id    TEXT NOT NULL,
            org_id      TEXT NOT NULL,
            status      TEXT NOT NULL,
            iterations  INTEGER NOT NULL DEFAULT 1,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            trace_id    TEXT NOT NULL DEFAULT '',
            config      TEXT,
            summary     TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_eval_runs_suite ON eval_runs (suite_id, started_at);

        CREATE TABLE IF NOT EXISTS eval_run_results (
            run_id      TEXT NOT NULL,
            case_id     TEXT NOT NULL,
            org_id      TEXT NOT NULL,
            iteration   INTEGER NOT NULL,
            passed      INTEGER,
            correct     INTEGER,
            duration_ms REAL,
            error       TEXT,
            fired       TEXT,
            scores      TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_eval_results_run ON eval_run_results (run_id, case_id);
    """)
    run_migrations(c, _MIGRATIONS, store="evals")
    c.commit()


def _rid() -> str:
    return uuid.uuid4().hex[:12]


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


# ── suites ────────────────────────────────────────────────────────────────────

def create_suite(name: str, *, description: str = "", target: str = "reference",
                 connection_id: str = "", config: Optional[dict] = None) -> dict:
    suite_id, org, now = _rid(), current_org_id(), _now()
    c = _connect()
    try:
        c.execute(
            "INSERT INTO eval_suites (id, org_id, name, description, target, "
            "connection_id, config, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (suite_id, org, name, description, target, connection_id,
             json.dumps(config or {}, default=str), now))
        c.commit()
    finally:
        c.close()
    return {"id": suite_id, "org_id": org, "name": name, "description": description,
            "target": target, "connection_id": connection_id,
            "config": config or {}, "created_at": now}


def list_suites(limit: int = 100) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT * FROM eval_suites WHERE org_id=? ORDER BY created_at DESC LIMIT ?",
            (current_org_id(), max(1, min(int(limit), 500)))).fetchall()
    finally:
        c.close()
    return [_suite_row(r) for r in rows]


def get_suite(suite_id: str) -> Optional[dict]:
    c = _connect()
    try:
        row = c.execute("SELECT * FROM eval_suites WHERE id=? AND org_id=?",
                        (suite_id, current_org_id())).fetchone()
    finally:
        c.close()
    return _suite_row(row) if row else None


def delete_suite(suite_id: str) -> bool:
    """Delete a suite and everything under it. Cascade is manual because SQLite
    foreign keys are off by default here — leaving orphan cases behind would
    quietly inflate every later count."""
    org = current_org_id()
    c = _connect()
    try:
        runs = [r["id"] for r in c.execute(
            "SELECT id FROM eval_runs WHERE suite_id=? AND org_id=?", (suite_id, org))]
        for run_id in runs:
            c.execute("DELETE FROM eval_run_results WHERE run_id=? AND org_id=?", (run_id, org))
        c.execute("DELETE FROM eval_runs WHERE suite_id=? AND org_id=?", (suite_id, org))
        c.execute("DELETE FROM eval_cases WHERE suite_id=? AND org_id=?", (suite_id, org))
        cur = c.execute("DELETE FROM eval_suites WHERE id=? AND org_id=?", (suite_id, org))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def _suite_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["config"] = _loads(d.get("config"), {})
    return d


# ── cases ─────────────────────────────────────────────────────────────────────

def add_case(suite_id: str, *, question: str = "", artifact: str = "",
             expected: Optional[dict] = None, tags: Optional[list[str]] = None) -> dict:
    case_id, org, now = _rid(), current_org_id(), _now()
    c = _connect()
    try:
        c.execute(
            "INSERT INTO eval_cases (id, suite_id, org_id, question, artifact, "
            "expected, tags, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (case_id, suite_id, org, question, artifact,
             json.dumps(expected or {}, default=str),
             json.dumps(tags or [], default=str), now))
        c.commit()
    finally:
        c.close()
    return {"id": case_id, "suite_id": suite_id, "question": question,
            "artifact": artifact, "expected": expected or {},
            "tags": tags or [], "created_at": now}


def add_cases(suite_id: str, cases: list[dict]) -> int:
    """Bulk insert — one transaction, because importing a 53-case corpus one
    statement at a time is a visibly slow way to do the same thing."""
    org, now = current_org_id(), _now()
    c = _connect()
    try:
        c.executemany(
            "INSERT INTO eval_cases (id, suite_id, org_id, question, artifact, "
            "expected, tags, created_at) VALUES (?,?,?,?,?,?,?,?)",
            [(_rid(), suite_id, org, cs.get("question", ""), cs.get("artifact", ""),
              json.dumps(cs.get("expected") or {}, default=str),
              json.dumps(cs.get("tags") or [], default=str), now) for cs in cases])
        c.commit()
        return len(cases)
    finally:
        c.close()


def list_cases(suite_id: str, limit: int = 1000) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT * FROM eval_cases WHERE suite_id=? AND org_id=? "
            "ORDER BY created_at, id LIMIT ?",
            (suite_id, current_org_id(), max(1, min(int(limit), 5000)))).fetchall()
    finally:
        c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["expected"] = _loads(d.get("expected"), {})
        d["tags"] = _loads(d.get("tags"), [])
        out.append(d)
    return out


def delete_case(case_id: str) -> bool:
    c = _connect()
    try:
        cur = c.execute("DELETE FROM eval_cases WHERE id=? AND org_id=?",
                        (case_id, current_org_id()))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


# ── runs ──────────────────────────────────────────────────────────────────────

def start_run(suite_id: str, *, iterations: int = 1, config: Optional[dict] = None,
              trace_id: str = "") -> str:
    run_id, org = _rid(), current_org_id()
    c = _connect()
    try:
        c.execute(
            "INSERT INTO eval_runs (id, suite_id, org_id, status, iterations, "
            "started_at, trace_id, config) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, suite_id, org, RUNNING, max(1, int(iterations)), _now(),
             trace_id, json.dumps(config or {}, default=str)))
        c.commit()
    finally:
        c.close()
    return run_id


def record_result(run_id: str, case_id: str, iteration: int, *, passed: bool,
                  correct: Optional[bool] = None, duration_ms: float = 0.0,
                  error: str = "", fired: Optional[list[str]] = None,
                  scores: Optional[list[dict]] = None) -> None:
    c = _connect()
    try:
        c.execute(
            "INSERT INTO eval_run_results (run_id, case_id, org_id, iteration, passed, "
            "correct, duration_ms, error, fired, scores) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, case_id, current_org_id(), int(iteration), int(bool(passed)),
             None if correct is None else int(bool(correct)),
             round(float(duration_ms), 2), error,
             json.dumps(fired or [], default=str),
             json.dumps(scores or [], default=str)))
        c.commit()
    finally:
        c.close()


def finish_run(run_id: str, *, status: str = SUCCEEDED,
               summary: Optional[dict] = None) -> None:
    c = _connect()
    try:
        c.execute(
            "UPDATE eval_runs SET status=?, finished_at=?, summary=? "
            "WHERE id=? AND org_id=?",
            (status, _now(), json.dumps(summary or {}, default=str),
             run_id, current_org_id()))
        c.commit()
    finally:
        c.close()


def get_run(run_id: str) -> Optional[dict]:
    c = _connect()
    try:
        row = c.execute("SELECT * FROM eval_runs WHERE id=? AND org_id=?",
                        (run_id, current_org_id())).fetchone()
    finally:
        c.close()
    if not row:
        return None
    d = dict(row)
    d["config"] = _loads(d.get("config"), {})
    d["summary"] = _loads(d.get("summary"), {})
    return d


def list_runs(suite_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM eval_runs WHERE org_id=?"
    args: list[Any] = [current_org_id()]
    if suite_id:
        q += " AND suite_id=?"
        args.append(suite_id)
    q += " ORDER BY started_at DESC LIMIT ?"
    args.append(max(1, min(int(limit), 200)))
    c = _connect()
    try:
        rows = c.execute(q, args).fetchall()
    finally:
        c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = _loads(d.get("config"), {})
        d["summary"] = _loads(d.get("summary"), {})
        out.append(d)
    return out


def run_results(run_id: str, limit: int = 5000) -> list[dict]:
    c = _connect()
    try:
        rows = c.execute(
            "SELECT * FROM eval_run_results WHERE run_id=? AND org_id=? "
            "ORDER BY case_id, iteration LIMIT ?",
            (run_id, current_org_id(), max(1, min(int(limit), 20000)))).fetchall()
    finally:
        c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["passed"] = None if d["passed"] is None else bool(d["passed"])
        d["correct"] = None if d["correct"] is None else bool(d["correct"])
        d["fired"] = _loads(d.get("fired"), [])
        d["scores"] = _loads(d.get("scores"), [])
        out.append(d)
    return out
