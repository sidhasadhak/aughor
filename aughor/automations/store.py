"""Wave A1 — SQLite persistence for Automations and their run history.

Two tables in ``data/automations.db`` (env ``AUGHOR_AUTOMATIONS_DB``), following the
:mod:`aughor.monitors.store` idiom exactly — ``resolve_db_path`` so the suite can never touch the
live store (DATA-01), a module lock, and the forward-only migration framework (DATA-05) registered
from day one so the first additive column rides it instead of an ad-hoc ALTER.

  automations     — configuration rows; mutable (upsert by id)
  automation_runs — append-only tick history, INCLUDING ticks that did nothing

The second table is the point. ``monitor_alerts`` records only alerts that fired, so "did my monitor
run at 03:00, and if so why did nothing happen?" is unanswerable today. Every tick writes exactly one
row here with an ``outcome`` and a human ``reason``.

Composite fields (conditions, effects, per-effect outcomes) are stored as JSON columns rather than
child tables: they are always read as a whole automation, never queried across, and JSON keeps the
pydantic model the single source of truth for their shape.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from aughor.automations.models import Automation, AutomationRun
from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.backend import connect_store
from aughor.util.time import now_iso_z

logger = logging.getLogger(__name__)

_DB_PATH = resolve_db_path("AUGHOR_AUTOMATIONS_DB", Path("data") / "automations.db")
_LOCK = threading.Lock()


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS automations (
    id                    TEXT PRIMARY KEY,
    conn_id               TEXT NOT NULL,
    name                  TEXT NOT NULL,
    description           TEXT NOT NULL DEFAULT '',
    conditions            TEXT NOT NULL DEFAULT '[]',
    condition_logic       TEXT NOT NULL DEFAULT 'all',
    effects               TEXT NOT NULL DEFAULT '[]',
    fallback_effect       TEXT,
    enabled               INTEGER NOT NULL DEFAULT 1,
    paused_until          TEXT,
    expires_at            TEXT,
    max_retries           INTEGER NOT NULL DEFAULT 1,
    retry_backoff_seconds REAL NOT NULL DEFAULT 30.0,
    agent_id              TEXT NOT NULL DEFAULT '',
    scheduling            TEXT NOT NULL DEFAULT 'ordered',
    created_at            TEXT NOT NULL DEFAULT '',
    updated_at            TEXT NOT NULL DEFAULT '',
    last_run_at           TEXT,
    last_status           TEXT
);

CREATE TABLE IF NOT EXISTS automation_runs (
    id               TEXT PRIMARY KEY,
    automation_id    TEXT NOT NULL,
    automation_name  TEXT NOT NULL DEFAULT '',
    conn_id          TEXT NOT NULL DEFAULT '',
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    duration_ms      INTEGER NOT NULL DEFAULT 0,
    outcome          TEXT NOT NULL,
    reason           TEXT NOT NULL DEFAULT '',
    conditions_fired TEXT NOT NULL DEFAULT '[]',
    effects          TEXT NOT NULL DEFAULT '[]',
    fallback_used    INTEGER NOT NULL DEFAULT 0,
    error            TEXT NOT NULL DEFAULT '',
    -- DS-8: the durable pause checkpoint (JSON). '{}' on every run that never parked.
    checkpoint       TEXT NOT NULL DEFAULT '{}'
);

-- A3: last-committed source-version fingerprints, keyed PER AUTOMATION so two automations
-- watching the same table each keep their own "since last time" cursor (a shared cursor would
-- let the first automation's tick consume the second's trigger). A new table rides the base DDL
-- rather than a migration: executescript re-runs on every init and IF NOT EXISTS is idempotent,
-- so both fresh and existing DBs converge — the migration framework is for non-idempotent ALTERs.
CREATE TABLE IF NOT EXISTS probe_state (
    automation_id TEXT NOT NULL,
    target        TEXT NOT NULL,
    version       TEXT NOT NULL,
    updated_at    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (automation_id, target)
);

-- DS-4: where a person ARRANGED the steps on the Design canvas. A sidecar for the same
-- reason `probe_state` is one, plus a sharper one: a layout is a VIEW PREFERENCE, and the
-- automation row is a governed record the engine reads at 09:00. Putting an arrangement in
-- it would mean the authoring PUT has to carry it (that request body is what a person
-- types) and a stale client could erase where somebody put their nodes by renaming the
-- automation — the exact family of silent write-loss this subsystem has paid for three
-- times. Account-keyed like `card_layouts`: 'default' until identity is bound, so it
-- upgrades to true per-user with no migration.
CREATE TABLE IF NOT EXISTS automation_layouts (
    automation_id TEXT NOT NULL,
    user_id       TEXT NOT NULL DEFAULT 'default',
    layout_json   TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (automation_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_auto_conn      ON automations (conn_id);
CREATE INDEX IF NOT EXISTS idx_runs_automation ON automation_runs (automation_id);
CREATE INDEX IF NOT EXISTS idx_runs_conn       ON automation_runs (conn_id);
CREATE INDEX IF NOT EXISTS idx_runs_time       ON automation_runs (started_at DESC);
"""

# Base DDL is conceptually v1; every later additive change is a versioned step (DATA-05).
def _add_agent_binding(conn: sqlite3.Connection) -> None:
    """VA-9b's `Automation.agent_id` never had a column.

    The model gained the field and the INSERT did not, so SQLite's named binding
    quietly ignored it: an automation-level agent was accepted by the API, echoed back
    in the response, and read as `""` from the next request onward. The per-STEP agent
    survived only because it rides inside the `effects` JSON. Additive and idempotent,
    like every migration here."""
    add_column_if_missing(conn, "automations", "agent_id", "TEXT NOT NULL DEFAULT ''")


def _add_scheduling(conn: sqlite3.Connection) -> None:
    """DS-7's `Automation.scheduling` — added everywhere AT ONCE, because this store has
    already shipped the half-added version of this change: VA-9b's field had a model
    attribute and no column, so the named INSERT quietly ignored it and the API echoed a
    value the row never held. Model + DDL + this migration + both halves of the upsert,
    one commit."""
    add_column_if_missing(conn, "automations", "scheduling",
                          "TEXT NOT NULL DEFAULT 'ordered'")


def _add_run_checkpoint(conn: sqlite3.Connection) -> None:
    """DS-8's ``AutomationRun.checkpoint`` — the accumulated chain state a paused run
    resumes from.

    Added the way this store has learned to add things: model + DDL + migration + both
    halves of the INSERT in ONE commit. Twice now a field has shipped here with a model
    attribute and no column (VA-9b's `agent_id`, and `scheduling` was written this way
    only because VA-9b had already taught the lesson), and the failure mode is the quiet
    one — SQLite's named binding ignores a key with no column, so the API echoes back a
    value the row never held and nothing raises until a reader needs it.

    A paused run whose checkpoint did not persist is worse than that: it is a run that can
    never be resumed, holding a proposal that can never be honoured."""
    add_column_if_missing(conn, "automation_runs", "checkpoint", "TEXT NOT NULL DEFAULT '{}'")


#: Version 2 because the live store reads `PRAGMA user_version = 1` — checked against the
#: deployed database, not assumed from this file, which is the only way to number one.
#: Version 3 numbered off the same fact one release later: the deployed store runs this
#: file's migrations at boot, so it sits at 2 — the highest version listed here on main.
_MIGRATIONS: list[Migration] = [
    Migration(version=2, name="automation agent binding (VA-9b's missing column)",
              apply=_add_agent_binding),
    Migration(version=3, name="step scheduling (DS-7: ordered | parallel)",
              apply=_add_scheduling),
    #: Version 4 read off the LIVE store the same way: `PRAGMA user_version` on the
    #: deployed `data/automations.db` returns 3 (DS-7's migration ran at its boot), so 4
    #: is the next one that will actually execute. A migration numbered at or below the
    #: deployed version is silently skipped forever, and no hermetic test can catch it —
    #: a fresh database gets the column from the DDL above and passes either way.
    Migration(version=4, name="run checkpoint (DS-8: durable pause)",
              apply=_add_run_checkpoint),
]


def _connect() -> sqlite3.Connection:
    conn = connect_store(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    with _LOCK:
        conn = _connect()
        try:
            conn.executescript(_DDL)
            conn.commit()
            run_migrations(conn, _MIGRATIONS, store="automations")
        finally:
            conn.close()


_init_schema()


# ── Automation CRUD ───────────────────────────────────────────────────────────

def _row_to_automation(row: sqlite3.Row) -> Automation:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    d["conditions"] = json.loads(d["conditions"] or "[]")
    d["effects"] = json.loads(d["effects"] or "[]")
    d["fallback_effect"] = json.loads(d["fallback_effect"]) if d.get("fallback_effect") else None
    return Automation(**d)


def _automation_params(a: Automation) -> dict:
    p = a.model_dump()
    p["conditions"] = json.dumps([c.model_dump() for c in a.conditions])
    p["effects"] = json.dumps([e.model_dump() for e in a.effects])
    p["fallback_effect"] = json.dumps(a.fallback_effect.model_dump()) if a.fallback_effect else None
    p["enabled"] = int(a.enabled)
    return p


def list_automations(conn_id: Optional[str] = None,
                     enabled_only: bool = False) -> list[Automation]:
    clauses, params = [], []
    if conn_id:
        clauses.append("conn_id = ?"); params.append(conn_id)
    if enabled_only:
        clauses.append("enabled = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM automations {where} ORDER BY name", params
            ).fetchall()
            return [_row_to_automation(r) for r in rows]
        finally:
            conn.close()


def get_automation(automation_id: str) -> Optional[Automation]:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM automations WHERE id = ?", (automation_id,)
            ).fetchone()
            return _row_to_automation(row) if row else None
        finally:
            conn.close()


def _subchain_children(automation: Automation) -> list[str]:
    return [e.automation_id for e in (automation.effects or [])
            if e.kind == "subchain" and e.automation_id]


def cycle_problem(automation: Automation) -> Optional[str]:
    """DS-9 — the sentence explaining the cycle this save would create, or None.

    Walked from the automation being saved, using its NEW effects for the root and the
    stored effects for everything below it: a cycle is created by the edge you are adding,
    so the question is always "does the rest of the library already lead back here".

    Refused at SAVE rather than caught at run time, which is this plane's standing rule (K1:
    reject at parse, never surface). A cycle discovered at 09:00 is not an error message —
    it is a chain calling itself until something else gives out, holding a scheduler thread
    the whole way down, and the automation that finally errors is rarely the one that is
    wrong. Refusing the edge names the loop while the person who drew it is still looking
    at it.

    Breadth-first with a `seen` set, so a diamond (two steps invoking the same subchain) is
    walked once and is NOT a cycle — sharing a subchain is the entire point of the wave.
    """
    root = automation.id
    frontier = list(_subchain_children(automation))
    if root in frontier:
        return (f"'{automation.name or root}' would run itself — a chain cannot be its own "
                f"subchain.")
    seen: set[str] = set()
    while frontier:
        child_id = frontier.pop(0)
        if child_id in seen:
            continue
        seen.add(child_id)
        child = get_automation(child_id)
        if child is None:
            continue          # a dangling reference is the dispatcher's problem, not a cycle
        for grandchild in _subchain_children(child):
            if grandchild == root:
                return (f"'{automation.name or root}' would run itself: it invokes "
                        f"'{child.name or child_id}', which invokes it back.")
            if grandchild not in seen:
                frontier.append(grandchild)
    return None


def upsert_automation(automation: Automation) -> Automation:
    """Create or update an automation (full replace by id).

    DS-9 — refuses a save that would close a subchain cycle. Here rather than on the model,
    because the question cannot be answered from the automation alone: it needs the rest of
    the library, and a `model_validator` that read the store would fire on every load, every
    fixture and every deserialisation from the DB. Here rather than only on the route,
    because this is the one write path and a cycle written by any other caller is the same
    cycle.
    """
    problem = cycle_problem(automation)
    if problem:
        raise ValueError(problem)
    now = now_iso_z()
    if not automation.created_at:
        automation = automation.model_copy(update={"created_at": now})
    automation = automation.model_copy(update={"updated_at": now})

    with _LOCK:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO automations (
                    id, conn_id, name, description, conditions, condition_logic, effects,
                    fallback_effect, enabled, paused_until, expires_at, max_retries,
                    retry_backoff_seconds, agent_id, scheduling, created_at, updated_at,
                    last_run_at, last_status
                ) VALUES (
                    :id, :conn_id, :name, :description, :conditions, :condition_logic, :effects,
                    :fallback_effect, :enabled, :paused_until, :expires_at, :max_retries,
                    :retry_backoff_seconds, :agent_id, :scheduling, :created_at, :updated_at,
                    :last_run_at, :last_status
                )
                ON CONFLICT(id) DO UPDATE SET
                    -- `conn_id` belongs here like every other authored field. Left out,
                    -- an update silently kept the old connection: the API returned the
                    -- CHANGED model (so every caller reported success) while the row kept
                    -- the old value — the shape of wrong answer this codebase treats as
                    -- worse than an exception. Found live, moving an automation onto the
                    -- connection its own agent is bound to.
                    conn_id=excluded.conn_id,
                    name=excluded.name,
                    description=excluded.description,
                    conditions=excluded.conditions,
                    condition_logic=excluded.condition_logic,
                    effects=excluded.effects,
                    fallback_effect=excluded.fallback_effect,
                    enabled=excluded.enabled,
                    paused_until=excluded.paused_until,
                    expires_at=excluded.expires_at,
                    max_retries=excluded.max_retries,
                    retry_backoff_seconds=excluded.retry_backoff_seconds,
                    agent_id=excluded.agent_id,
                    scheduling=excluded.scheduling,
                    updated_at=excluded.updated_at,
                    last_run_at=excluded.last_run_at,
                    last_status=excluded.last_status
            """, _automation_params(automation))
            conn.commit()
        finally:
            conn.close()
    return automation


def delete_automation(automation_id: str) -> bool:
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
            conn.execute("DELETE FROM automation_runs WHERE automation_id = ?", (automation_id,))
            conn.execute("DELETE FROM probe_state WHERE automation_id = ?", (automation_id,))
            # The arrangement goes with the thing it arranged — otherwise a new automation
            # that reused the id would open onto a stranger's layout.
            conn.execute("DELETE FROM automation_layouts WHERE automation_id = ?",
                         (automation_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def set_automation_enabled(automation_id: str, enabled: bool) -> Optional[Automation]:
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE automations SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), now_iso_z(), automation_id),
            )
            conn.commit()
        finally:
            conn.close()
    return get_automation(automation_id)


def pause_automation(automation_id: str, until_iso: Optional[str]) -> Optional[Automation]:
    """Mute until ``until_iso`` (or clear the mute with None). Distinct from disabling:
    a pause has an end, and the run history keeps saying *why* nothing fired."""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE automations SET paused_until = ?, updated_at = ? WHERE id = ?",
                (until_iso, now_iso_z(), automation_id),
            )
            conn.commit()
        finally:
            conn.close()
    return get_automation(automation_id)


def purge_connection(conn_id: str) -> int:
    """Delete every automation, run, and probe baseline for a connection (catalog-delete
    cascade). Returns the total rows removed across the three tables. Probe state goes first —
    it is keyed by automation_id, so it must be resolved while the automations rows still exist."""
    with _LOCK:
        conn = _connect()
        try:
            n = conn.execute(
                "DELETE FROM probe_state WHERE automation_id IN "
                "(SELECT id FROM automations WHERE conn_id = ?)", (conn_id,)).rowcount
            n += conn.execute("DELETE FROM automations WHERE conn_id = ?", (conn_id,)).rowcount
            n += conn.execute("DELETE FROM automation_runs WHERE conn_id = ?", (conn_id,)).rowcount
            conn.commit()
            return n
        finally:
            conn.close()


# ── Run history ───────────────────────────────────────────────────────────────

def _row_to_run(row: sqlite3.Row) -> AutomationRun:
    d = dict(row)
    d["fallback_used"] = bool(d["fallback_used"])
    d["conditions_fired"] = json.loads(d["conditions_fired"] or "[]")
    d["effects"] = json.loads(d["effects"] or "[]")
    # `.get`, not `[...]`: a row read through a connection opened before the migration ran
    # has no such key, and a paused run is not worth crashing a history list over.
    d["checkpoint"] = json.loads(d.get("checkpoint") or "{}")
    return AutomationRun(**d)


def append_run(run: AutomationRun) -> AutomationRun:
    """Persist one tick. Idempotent — silent no-op on a duplicate id.

    Also advances the parent automation's ``last_run_at``/``last_status`` in the same
    transaction, so the summary on the config row can never disagree with its history.
    """
    p = run.model_dump()
    p["conditions_fired"] = json.dumps(run.conditions_fired)
    p["effects"] = json.dumps([e.model_dump() for e in run.effects])
    p["fallback_used"] = int(run.fallback_used)
    p["checkpoint"] = json.dumps(run.checkpoint or {})

    with _LOCK:
        conn = _connect()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO automation_runs (
                    id, automation_id, automation_name, conn_id, started_at, finished_at,
                    duration_ms, outcome, reason, conditions_fired, effects, fallback_used,
                    error, checkpoint
                ) VALUES (
                    :id, :automation_id, :automation_name, :conn_id, :started_at, :finished_at,
                    :duration_ms, :outcome, :reason, :conditions_fired, :effects,
                    :fallback_used, :error, :checkpoint
                )
            """, p)
            conn.execute(
                "UPDATE automations SET last_run_at = ?, last_status = ? WHERE id = ?",
                (run.finished_at or run.started_at, run.outcome, run.automation_id),
            )
            conn.commit()
        finally:
            conn.close()

    # Surface the tick on the event spine so a panel sees it live — the same treatment
    # monitor alerts get. The row is the source of truth; a failed emit never blocks it.
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(
            "automation.run",
            {"automation_id": run.automation_id, "automation_name": run.automation_name,
             "outcome": run.outcome, "reason": run.reason[:200],
             "effects": [e.status for e in run.effects]},
            conn_id=run.conn_id,
        )
    except Exception:
        logger.debug("automation.run emit failed", exc_info=True)
    return run


def get_runs(automation_id: Optional[str] = None, conn_id: Optional[str] = None,
             limit: int = 100) -> list[AutomationRun]:
    clauses, params = [], []
    if automation_id:
        clauses.append("automation_id = ?"); params.append(automation_id)
    if conn_id:
        clauses.append("conn_id = ?"); params.append(conn_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM automation_runs {where} ORDER BY started_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [_row_to_run(r) for r in rows]
        finally:
            conn.close()


def last_run(automation_id: str) -> Optional[AutomationRun]:
    """The most recent tick, or None. Used by ``schedule`` conditions to know what
    'since last time' means and by the UI to explain the current state."""
    runs = get_runs(automation_id=automation_id, limit=1)
    return runs[0] if runs else None


def get_run(run_id: str) -> Optional[AutomationRun]:
    """One run by id — DS-8's resume path, which starts from a proposal holding a run id
    and nothing else."""
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM automation_runs WHERE id = ?", (run_id,)).fetchone()
        finally:
            conn.close()
    return _row_to_run(row) if row else None


def update_run(run: AutomationRun) -> AutomationRun:
    """Overwrite an existing run row in place — DS-8 only.

    Every other write here is ``append_run``'s ``INSERT OR IGNORE``: a tick is a fact, and
    a fact does not get edited. A PAUSED run is the one exception in the model, because it
    is the one run that has not finished yet. Its resumption has to land in the SAME row —
    that is the whole receipt ("the trace shows one run with a human in its middle"), and
    the run id is also the trace id, so a second row would split one waterfall into two
    and orphan the spans the first half already wrote.

    Guarded by ``WHERE outcome = 'paused'`` for exactly the reason the proposal inbox
    resolves under ``WHERE status = 'pending'``: two accepts racing (an HTTP click and a
    Slack tap, a double-press, a replay) must not both resume the chain. The first UPDATE
    moves the row off ``paused``, the second matches zero rows and is a no-op. Returns the
    run unchanged either way; the caller learns which it was from ``rowcount``.
    """
    p = run.model_dump()
    p["conditions_fired"] = json.dumps(run.conditions_fired)
    p["effects"] = json.dumps([e.model_dump() for e in run.effects])
    p["fallback_used"] = int(run.fallback_used)
    p["checkpoint"] = json.dumps(run.checkpoint or {})

    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute("""
                UPDATE automation_runs SET
                    finished_at = :finished_at, duration_ms = :duration_ms,
                    outcome = :outcome, reason = :reason, effects = :effects,
                    fallback_used = :fallback_used, error = :error, checkpoint = :checkpoint
                WHERE id = :id AND outcome = 'paused'
            """, p)
            moved = cur.rowcount
            if moved:
                conn.execute(
                    "UPDATE automations SET last_run_at = ?, last_status = ? WHERE id = ?",
                    (run.finished_at or run.started_at, run.outcome, run.automation_id),
                )
            conn.commit()
        finally:
            conn.close()

    if not moved:
        return run
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(
            "automation.run",
            {"automation_id": run.automation_id, "automation_name": run.automation_name,
             "outcome": run.outcome, "reason": run.reason[:200],
             "effects": [e.status for e in run.effects], "resumed": True},
            conn_id=run.conn_id,
        )
    except Exception:
        logger.debug("automation.run resume emit failed", exc_info=True)
    return run


def paused_runs(conn_id: Optional[str] = None, limit: int = 100) -> list[AutomationRun]:
    """Every run currently parked on a human (DS-8). The `needs human` view reads this
    instead of scanning run history for an `approval_required` step, which is what it did
    before a pause was durable — that scan could only ever see the last 200 runs, so a
    busy deployment aged its own approvals out of the only view that listed them."""
    clauses, params = ["outcome = 'paused'"], []
    if conn_id:
        clauses.append("conn_id = ?")
        params.append(conn_id)
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM automation_runs WHERE {' AND '.join(clauses)} "
                f"ORDER BY started_at DESC LIMIT ?", (*params, limit)).fetchall()
        finally:
            conn.close()
    return [_row_to_run(r) for r in rows]


# ── Probe baselines (A3) ──────────────────────────────────────────────────────

def get_layout(automation_id: str, user_id: str) -> dict:
    """Where this user put the nodes of one automation (`{alias: {x, y}}`), `{}` if never.

    Keyed by ALIAS, because an alias is the only name a step has — `aliasFor` derives it
    from position when none is authored. So deleting a middle step shifts the ones after
    it and they inherit the previous occupant's coordinates. That is a view preference
    landing in a stale spot, not a wrong binding: the whole-replace on the next drag
    corrects it, and the alternative (an id on every effect) is a model change to solve a
    cosmetic problem.
    """
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT layout_json FROM automation_layouts "
                "WHERE automation_id = ? AND user_id = ?",
                (automation_id, user_id),
            ).fetchone()
            if not row:
                return {}
            try:
                loaded = json.loads(row[0] or "{}")
            except (TypeError, ValueError):
                # A layout is a convenience. A corrupt one opens the canvas at the default
                # arrangement rather than refusing to draw it at all.
                return {}
            return loaded if isinstance(loaded, dict) else {}
        finally:
            conn.close()


def set_layout(automation_id: str, user_id: str, layout: dict) -> None:
    """Persist the whole arrangement, replacing what was there.

    Whole-replace rather than merge, the way the cockpit's layout does it: a step that was
    removed must not keep a coordinate in the row forever, and merging would mean the
    stored layout only ever grows.
    """
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO automation_layouts
                       (automation_id, user_id, layout_json, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(automation_id, user_id) DO UPDATE SET
                       layout_json = excluded.layout_json,
                       updated_at  = excluded.updated_at""",
                (automation_id, user_id, json.dumps(layout or {}), now_iso_z()),
            )
            conn.commit()
        finally:
            conn.close()


def get_probe_baseline(automation_id: str, target: str) -> Optional[str]:
    """The last COMMITTED source-version fingerprint for (automation, table), or None when the
    condition has never fired (first observation)."""
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT version FROM probe_state WHERE automation_id = ? AND target = ?",
                (automation_id, target),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()


def set_probe_baseline(automation_id: str, target: str, version: str) -> None:
    """Record the fingerprint observed after a FIRED tick (see probes.commit_fired_baselines —
    committing anywhere else silently consumes changes under ``all`` logic)."""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO probe_state (automation_id, target, version, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(automation_id, target) DO UPDATE SET
                       version = excluded.version, updated_at = excluded.updated_at""",
                (automation_id, target, version, now_iso_z()),
            )
            conn.commit()
        finally:
            conn.close()
