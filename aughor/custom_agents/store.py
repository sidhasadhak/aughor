"""SQLite store for user-defined agents — data/agents.db (env AUGHOR_AGENTS_DB)."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.custom_agents.models import UserAgent

logger = logging.getLogger(__name__)

# WP-4 — the default was a bare "agents.db", so a live runtime DB materialized at the
# repo root, escaped data/'s gitignore, was tracked in git, and churned every run.
_DEFAULT_DB_PATH = Path("data") / "agents.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    connection_id TEXT NOT NULL DEFAULT '',
    doc_ids TEXT NOT NULL DEFAULT '[]',
    owner TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

# Golden questions — the agent's own regression suite ("measured agents",
# study Part B Phase 3). reference_sql is the ground truth; an evaluation
# generates SQL AS the agent and compares executed results deterministically.
_GOLDENS_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_agent_goldens (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    question TEXT NOT NULL,
    reference_sql TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


# WP-4 — additive schema evolution, now on the forward-only migration framework
# (was an ad-hoc PRAGMA table_info probe-and-ALTER block). add_column_if_missing is
# idempotent, so a DB that already grew these via the old idiom is a clean no-op.
_MIGRATIONS = [
    Migration(2, "schema_scope (agent schema scoping)",
              lambda c: add_column_if_missing(c, "user_agents", "schema_scope",
                                              "TEXT NOT NULL DEFAULT ''")),
    Migration(3, "pack_ids (specialist-pack binding preference)",
              lambda c: add_column_if_missing(c, "user_agents", "pack_ids",
                                              "TEXT NOT NULL DEFAULT '[]'")),
    Migration(4, "last_eval (latest golden-suite result JSON)",
              lambda c: add_column_if_missing(c, "user_agents", "last_eval",
                                              "TEXT NOT NULL DEFAULT ''")),
    # VA-2. Verified against the live store before numbering (user_version was 4, and
    # this file's list ended at 4) — the check that a skipped-forever migration taught us
    # to run every time.
    Migration(5, "purpose (short routing line for delegation rosters)",
              lambda c: add_column_if_missing(c, "user_agents", "purpose",
                                              "TEXT NOT NULL DEFAULT ''")),
]

_legacy_checked = False


def _maybe_adopt_legacy_db(target: Path) -> None:
    """One-time relocation of a pre-WP-4 repo-root ``agents.db`` into ``data/``.

    If the old bare-path file exists and the new ``data/agents.db`` does not, consolidate
    it (``VACUUM INTO`` folds any WAL) so agents created before the fix survive. Runs at
    most once per process. Skipped entirely when ``AUGHOR_AGENTS_DB`` is set (tests /
    on-prem) — a controlled path must never have a repo-root file read out from under it.
    """
    global _legacy_checked
    if _legacy_checked or os.environ.get("AUGHOR_AGENTS_DB"):
        _legacy_checked = True
        return
    _legacy_checked = True
    legacy = Path("agents.db")
    if target.exists() or not legacy.exists() or legacy.resolve() == target.resolve():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        src = tune(sqlite3.connect(str(legacy)))
        try:
            src.execute(f"VACUUM INTO '{target}'")
        finally:
            src.close()
        logger.info("relocated legacy agents.db → %s (existing agents preserved)", target)
    except Exception as exc:
        logger.warning("legacy agents.db relocation skipped (%s); using a fresh %s",
                       exc, target)


def _db_path() -> str:
    target = resolve_db_path("AUGHOR_AGENTS_DB", _DEFAULT_DB_PATH)
    _maybe_adopt_legacy_db(target)
    return str(target)


def _connect() -> sqlite3.Connection:
    from aughor.db.backend import connect_store
    conn = connect_store(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.execute(_GOLDENS_SCHEMA)
    run_migrations(conn, _MIGRATIONS, store="user_agents")
    return conn


def _row_to_agent(row: sqlite3.Row) -> UserAgent:
    return UserAgent(
        id=row["id"], name=row["name"], instructions=row["instructions"],
        purpose=(row["purpose"] if "purpose" in row.keys() else ""),
        connection_id=row["connection_id"], schema_scope=row["schema_scope"],
        doc_ids=json.loads(row["doc_ids"] or "[]"),
        pack_ids=json.loads(row["pack_ids"] or "[]"),
        owner=row["owner"], enabled=bool(row["enabled"]),
        last_eval=json.loads(row["last_eval"]) if row["last_eval"] else None,
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_agent(name: str, *, instructions: str = "", purpose: str = "",
                 connection_id: str = "",
                 schema_scope: str = "", doc_ids: Optional[list[str]] = None,
                 pack_ids: Optional[list[str]] = None, owner: str = "") -> UserAgent:
    agent = UserAgent(
        id=f"ua_{uuid.uuid4().hex[:12]}", name=name.strip(),
        instructions=instructions, purpose=purpose, connection_id=connection_id,
        schema_scope=schema_scope, doc_ids=list(doc_ids or []),
        pack_ids=list(pack_ids or []), owner=owner,
        enabled=True, created_at=_now(), updated_at=_now(),
    )
    with _connect() as conn:
        conn.execute(
            "INSERT INTO user_agents (id, name, instructions, purpose, connection_id,"
            " schema_scope, doc_ids, pack_ids, owner, enabled, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (agent.id, agent.name, agent.instructions, agent.purpose,
             agent.connection_id, agent.schema_scope, json.dumps(agent.doc_ids),
             json.dumps(agent.pack_ids),
             agent.owner, int(agent.enabled), agent.created_at, agent.updated_at),
        )
    from aughor.custom_agents.revisions import record_revision
    record_revision(agent, author=owner)   # revision 1 — the configuration it was born with
    return agent


def get_agent(agent_id: str) -> Optional[UserAgent]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM user_agents WHERE id = ?", (agent_id,)).fetchone()
    return _row_to_agent(row) if row else None


def list_agents() -> list[UserAgent]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM user_agents ORDER BY created_at DESC").fetchall()
    return [_row_to_agent(r) for r in rows]


_PATCHABLE = ("name", "instructions", "purpose", "connection_id", "schema_scope",
              "doc_ids", "pack_ids", "enabled")


def update_agent(agent_id: str, **fields) -> Optional[UserAgent]:
    """Patch the provided fields (subset of ``_PATCHABLE``); returns the updated
    agent, or None when it doesn't exist.

    Wave H6: when the edit changes the agent's GOVERNING configuration, the new
    configuration is appended to its revision history. ``last_eval`` is deliberately left
    alone — the chip is labelled stale by :attr:`UserAgent.eval_basis`, never deleted,
    because a past measurement of a past configuration is real evidence and erasing it
    would lose what the agent used to be able to do.
    """
    updates = {k: v for k, v in fields.items() if k in _PATCHABLE and v is not None}
    if not updates:
        return get_agent(agent_id)
    # Before the write, not after: an agent that predates revision tracking has no
    # history, and recording its CURRENT configuration first is what gives the edge about
    # to be made something to be measured against. Without this the first edit produces a
    # single entry with no predecessor — a history that cannot be read as a change.
    before = get_agent(agent_id)
    if before is not None:
        from aughor.custom_agents.revisions import ensure_baseline
        ensure_baseline(before)
    sets, params = [], []
    for k, v in updates.items():
        sets.append(f"{k} = ?")
        if k in ("doc_ids", "pack_ids"):
            params.append(json.dumps(list(v)))
        elif k == "enabled":
            params.append(int(bool(v)))
        else:
            params.append(v)
    sets.append("updated_at = ?")
    params.extend([_now(), agent_id])
    with _connect() as conn:
        cur = conn.execute(f"UPDATE user_agents SET {', '.join(sets)} WHERE id = ?", params)
        if cur.rowcount == 0:
            return None
    agent = get_agent(agent_id)
    if agent is not None:
        from aughor.custom_agents.revisions import record_revision
        record_revision(agent)   # a no-op when only the name or the enabled switch moved
    return agent


def delete_agent(agent_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM user_agents WHERE id = ?", (agent_id,))
        conn.execute("DELETE FROM user_agent_goldens WHERE agent_id = ?", (agent_id,))
        return cur.rowcount > 0


# ── Golden questions (the agent's own regression suite) ──────────────────────

def add_golden(agent_id: str, question: str, reference_sql: str) -> dict:
    row = {"id": f"ag_{uuid.uuid4().hex[:12]}", "agent_id": agent_id,
           "question": question.strip(), "reference_sql": reference_sql.strip(),
           "created_at": _now()}
    with _connect() as conn:
        conn.execute(
            "INSERT INTO user_agent_goldens (id, agent_id, question, reference_sql,"
            " created_at) VALUES (?,?,?,?,?)",
            (row["id"], row["agent_id"], row["question"], row["reference_sql"],
             row["created_at"]),
        )
    return row


def list_goldens(agent_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM user_agent_goldens WHERE agent_id = ? ORDER BY created_at",
            (agent_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_golden(golden_id: str, agent_id: Optional[str] = None) -> bool:
    """Delete one golden. Pass ``agent_id`` to scope the delete to its owner.

    The route has always taken both ids in its path and passed only the golden's, so the
    agent id was decorative and any agent's URL could delete any golden. Scoping is
    optional here rather than required so the existing single-argument callers keep their
    meaning, but every route-level caller supplies it.
    """
    q = "DELETE FROM user_agent_goldens WHERE id = ?"
    args: list = [golden_id]
    if agent_id is not None:
        q += " AND agent_id = ?"
        args.append(agent_id)
    with _connect() as conn:
        return conn.execute(q, args).rowcount > 0


def record_eval(agent_id: str, result: dict) -> None:
    """Stamp the latest golden-suite result onto the agent (the pass chip).

    The result carries the ``config_rev`` it was measured against (Wave H6). Without it a
    chip is a number with no subject: the suite graded the instructions, document scope and
    pack bindings that were live when it ran, and any of those can change a minute later.
    Stamping the revision is what lets :attr:`UserAgent.eval_basis` tell a current pass from
    one earned by an agent that no longer exists.
    """
    agent = get_agent(agent_id)
    if agent is None:
        return
    stamped = {**result, "config_rev": agent.config_rev}
    with _connect() as conn:
        conn.execute("UPDATE user_agents SET last_eval = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(stamped), _now(), agent_id))
