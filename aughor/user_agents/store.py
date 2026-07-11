"""SQLite store for user-defined agents — data/agents.db (env AUGHOR_AGENTS_DB)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.user_agents.models import UserAgent

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


def _db_path() -> str:
    return resolve_db_path("AUGHOR_AGENTS_DB", "agents.db")


def _connect() -> sqlite3.Connection:
    conn = tune(sqlite3.connect(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    # Additive columns (slice 4: schema scoping + pack bindings) — pre-existing
    # stores lack them; probe the live schema and ALTER only what's missing.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(user_agents)")}
    if "schema_scope" not in cols:
        conn.execute("ALTER TABLE user_agents ADD COLUMN schema_scope TEXT NOT NULL DEFAULT ''")
    if "pack_ids" not in cols:
        conn.execute("ALTER TABLE user_agents ADD COLUMN pack_ids TEXT NOT NULL DEFAULT '[]'")
    if "last_eval" not in cols:  # slice 5: the latest golden-suite result (JSON)
        conn.execute("ALTER TABLE user_agents ADD COLUMN last_eval TEXT NOT NULL DEFAULT ''")
    conn.execute(_GOLDENS_SCHEMA)
    return conn


def _row_to_agent(row: sqlite3.Row) -> UserAgent:
    return UserAgent(
        id=row["id"], name=row["name"], instructions=row["instructions"],
        connection_id=row["connection_id"], schema_scope=row["schema_scope"],
        doc_ids=json.loads(row["doc_ids"] or "[]"),
        pack_ids=json.loads(row["pack_ids"] or "[]"),
        owner=row["owner"], enabled=bool(row["enabled"]),
        last_eval=json.loads(row["last_eval"]) if row["last_eval"] else None,
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_agent(name: str, *, instructions: str = "", connection_id: str = "",
                 schema_scope: str = "", doc_ids: Optional[list[str]] = None,
                 pack_ids: Optional[list[str]] = None, owner: str = "") -> UserAgent:
    agent = UserAgent(
        id=f"ua_{uuid.uuid4().hex[:12]}", name=name.strip(),
        instructions=instructions, connection_id=connection_id,
        schema_scope=schema_scope, doc_ids=list(doc_ids or []),
        pack_ids=list(pack_ids or []), owner=owner,
        enabled=True, created_at=_now(), updated_at=_now(),
    )
    with _connect() as conn:
        conn.execute(
            "INSERT INTO user_agents (id, name, instructions, connection_id, schema_scope,"
            " doc_ids, pack_ids, owner, enabled, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (agent.id, agent.name, agent.instructions, agent.connection_id,
             agent.schema_scope, json.dumps(agent.doc_ids), json.dumps(agent.pack_ids),
             agent.owner, int(agent.enabled), agent.created_at, agent.updated_at),
        )
    return agent


def get_agent(agent_id: str) -> Optional[UserAgent]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM user_agents WHERE id = ?", (agent_id,)).fetchone()
    return _row_to_agent(row) if row else None


def list_agents() -> list[UserAgent]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM user_agents ORDER BY created_at DESC").fetchall()
    return [_row_to_agent(r) for r in rows]


_PATCHABLE = ("name", "instructions", "connection_id", "schema_scope",
              "doc_ids", "pack_ids", "enabled")


def update_agent(agent_id: str, **fields) -> Optional[UserAgent]:
    """Patch the provided fields (subset of ``_PATCHABLE``); returns the updated
    agent, or None when it doesn't exist."""
    updates = {k: v for k, v in fields.items() if k in _PATCHABLE and v is not None}
    if not updates:
        return get_agent(agent_id)
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
    return get_agent(agent_id)


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


def delete_golden(golden_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM user_agent_goldens WHERE id = ?", (golden_id,))
        return cur.rowcount > 0


def record_eval(agent_id: str, result: dict) -> None:
    """Stamp the latest golden-suite result onto the agent (the pass chip)."""
    with _connect() as conn:
        conn.execute("UPDATE user_agents SET last_eval = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(result), _now(), agent_id))
