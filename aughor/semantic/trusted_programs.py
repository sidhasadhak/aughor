"""The Trusted-Program store — plan-as-program replay that COMPOUNDS (Rec 4, Stage C).

A validated, cleanly-executed plan-as-program (`agent/program_planner.Program`) is crystallized here, keyed
by (org, connection, question-fingerprint). On the next near-identical question the answer path REPLAYS the
stored program deterministically — re-validated against the current schema — instead of paying the LLM to
re-plan. A stale/invalid cached plan simply falls through to fresh planning, so replay is always safe.

This is the plan-level twin of `semantic/trusted_queries.py` (which stores a single SQL string) and mirrors
the `ambiguity_ledger` house idiom exactly: `resolve_db_path` env override so the suite NEVER touches live
`data/`, `tune()` PRAGMAs, `run_migrations` for forward-only schema evolution, and deterministic lexical
token-overlap matching (`semantic/lexical.tokenize`) — no embedding dependency, reproducible in tests.

The program is stored as a JSON dict (not the typed `Program`) to keep this platform/semantic module free of
any `agent/` import; the agent layer reconstructs and re-validates it on replay.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.semantic.lexical import tokenize

_LOCK = threading.Lock()
_DB_PATH = resolve_db_path(
    "AUGHOR_TRUSTED_PROGRAMS_DB",
    Path(__file__).parent.parent.parent / "data" / "trusted_programs.db",
)
_MIGRATIONS: list = [
    # Wave G6 — sealed programs: executed, never displayed. Existing rows default to 0
    # (unsealed), which is the only safe default: silently sealing programs an operator
    # had been reading would look like the platform had started hiding its work.
    Migration(2, "trusted_programs.sealed (G6)",
              lambda c: add_column_if_missing(
                  c, "trusted_programs", "sealed", "INTEGER NOT NULL DEFAULT 0")),
]


class TrustedProgram(BaseModel):
    """A validated plan-as-program crystallized for deterministic replay on one connection."""
    connection_id: str
    org_id: str = ""
    question: str                                   # the question it answers (canonical)
    program: dict = Field(default_factory=dict)     # a serialized Program (steps + rationale)
    plan_source: str = "auto"                       # auto (LLM-planned + run clean) | user (hand-authored)
    sealed: bool = False                            # G6: execute it, never display its steps
    question_fingerprint: str = ""                  # token signature (auto)
    id: str = ""                                    # deterministic natural-key hash (auto)
    verified_at: str = ""                           # when it first validated + ran clean
    last_used_at: Optional[str] = None
    use_count: int = 0

    def natural_key(self) -> str:
        """Same question on same connection ⇒ same row (idempotent)."""
        fp = self.question_fingerprint or _fingerprint(self.question)
        raw = f"{self.org_id}|{self.connection_id}|{fp}"
        return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fingerprint(text: str) -> str:
    """Order-insensitive content-token signature — the matching key."""
    return " ".join(sorted(set(tokenize(text or ""))))


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS trusted_programs (
            id                   TEXT PRIMARY KEY,
            org_id               TEXT NOT NULL DEFAULT '',
            connection_id        TEXT NOT NULL,
            question             TEXT NOT NULL,
            question_fingerprint TEXT NOT NULL DEFAULT '',
            program              TEXT NOT NULL DEFAULT '{}',
            plan_source          TEXT NOT NULL DEFAULT 'auto',
            verified_at          TEXT NOT NULL,
            last_used_at         TEXT,
            use_count            INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_tp_conn ON trusted_programs (org_id, connection_id)")
    run_migrations(c, _MIGRATIONS, store="trusted_programs")
    c.commit()


def _row_to_tp(row: sqlite3.Row) -> TrustedProgram:
    d = dict(row)
    d["program"] = json.loads(d.get("program") or "{}")
    d["sealed"] = bool(d.get("sealed") or 0)
    return TrustedProgram(**d)


def redacted_for_display(tp: TrustedProgram) -> TrustedProgram:
    """Wave G6 — the display twin of a trusted program.

    A SEALED program is executed in full and shown as a stated absence: the steps are
    replaced with a marker that says the program is governed and withheld, rather than
    with nothing. An empty `program` would read as "there was no plan", which is the
    same confusion between *withheld* and *absent* that G5's trim notice exists to
    prevent — one layer down.

    Returns a COPY. Redacting in place would mean one caller's display pass silently
    disarms the next caller's execution.
    """
    if not tp.sealed:
        return tp
    return tp.model_copy(update={
        "program": {"sealed": True,
                    "note": ("This program is governed and executed, and its steps are "
                             "deliberately not displayed.")}})


# ── write path ────────────────────────────────────────────────────────────────

def save_trusted_program(tp: TrustedProgram) -> TrustedProgram:
    """Crystallize a validated program (idempotent by natural key). A re-save of the same question on the
    same connection updates the one row, preserving ``verified_at`` + ``use_count`` (the compounding proof)."""
    tp.question_fingerprint = tp.question_fingerprint or _fingerprint(tp.question)
    tp.id = tp.id or tp.natural_key()
    tp.verified_at = tp.verified_at or _now()
    with _LOCK:
        c = _conn()
        try:
            existing = c.execute(
                "SELECT verified_at, use_count FROM trusted_programs WHERE id=?", (tp.id,)).fetchone()
            if existing is not None:
                tp.verified_at = existing["verified_at"]
                tp.use_count = existing["use_count"]
            c.execute(
                """INSERT OR REPLACE INTO trusted_programs
                   (id, org_id, connection_id, question, question_fingerprint, program,
                    plan_source, verified_at, last_used_at, use_count, sealed)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (tp.id, tp.org_id, tp.connection_id, tp.question, tp.question_fingerprint,
                 json.dumps(tp.program), tp.plan_source, tp.verified_at, tp.last_used_at,
                 tp.use_count, 1 if tp.sealed else 0),
            )
            c.commit()
        finally:
            c.close()
    _bump("trusted_programs.saved")
    return tp


# ── read path ─────────────────────────────────────────────────────────────────

def list_trusted_programs(connection_id: str = "", org_id: str = "") -> list[TrustedProgram]:
    with _LOCK:
        c = _conn()
        try:
            q = "SELECT * FROM trusted_programs"
            args: tuple = ()
            clauses = []
            if connection_id:
                clauses.append("connection_id = ?"); args += (connection_id,)
            if org_id:
                clauses.append("org_id = ?"); args += (org_id,)
            if clauses:
                q += " WHERE " + " AND ".join(clauses)
            q += " ORDER BY verified_at DESC"
            return [_row_to_tp(r) for r in c.execute(q, args).fetchall()]
        finally:
            c.close()


def retrieve_trusted_program(question: str, connection_id: str, *, org_id: str = "",
                             min_score: float = 0.34) -> Optional[tuple[TrustedProgram, float]]:
    """The trusted program whose question overlaps this one most, by token overlap (intersection /
    question-token count — the `trusted_queries` idiom). Conservative threshold so an unrelated question
    replays nothing. Returns the top match or None."""
    qtok = set(tokenize(question or ""))
    if not qtok:
        return None
    best: Optional[tuple[TrustedProgram, float]] = None
    for tp in list_trusted_programs(connection_id, org_id=org_id):
        ptok = set((tp.question_fingerprint or _fingerprint(tp.question)).split())
        if not ptok:
            continue
        score = len(qtok & ptok) / len(qtok)
        if score >= min_score and (best is None or score > best[1]):
            best = (tp, round(score, 3))
    return best


def record_program_hit(tp_id: str) -> None:
    """Count a replayed program (the burn-down metric's numerator)."""
    with _LOCK:
        c = _conn()
        try:
            c.execute("UPDATE trusted_programs SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                      (_now(), tp_id))
            c.commit()
        finally:
            c.close()
    _bump("trusted_programs.served")


def _bump(counter: str) -> None:
    try:
        from aughor.stats import stats
        stats.inc(counter)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "trusted-program telemetry bump is best-effort", counter="trusted_programs.bump_fail")
