"""HB-1 — groups and membership, the org's routing skeleton.

Two kinds of group, both plain rows (§6 item 24):

  - **built-in** — platform-shipped defaults (Viewer / Editor / Owner), a level per
    securable kind (``levels.ROLE_DEFAULT_LEVELS``). Built-in groups are NOT stored:
    they are the three roles wearing their HB-1 meaning, synthesized at read time so
    the stored role values stay frozen and a fresh deployment has them with zero rows.
  - **function** — the organisation's own (supply chain · finance · pricing), created
    by people or shipped by a pack (24 (c), open). A function group carries what a
    built-in group cannot: **members** (people AND agents — an agent in a group inherits its
    grants, the service-principal shape), **a channel** (an Action Hub trigger id, the
    same decoupling ``BriefSubscription`` uses — where a departure for this function
    lands), and grants held as ``group:<id>`` rows in the metastore grant store.

Lives in the SAME ``rbac.db`` as role assignments (``AUGHOR_RBAC_DB`` keeps every
table hermetic under test at once — no new store, no new env name). No enforcement
here: a pure record of who belongs where, read by ``access.py`` and ``routing.py``.
A member is a PRINCIPAL string (``user:a@b`` / ``agent:ua_x``), so people and agents
ride one column and one uniqueness rule.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from aughor.db.backend import connect_store
from aughor.db.store_pool import ensure_once
from aughor.metastore.models import principal_kind
from aughor.rbac.store import db_path
from aughor.util.time import now_iso as _now

BUILTIN = "builtin"
FUNCTION = "function"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Group:
    """A group within an org. ``kind`` is ``function`` for stored rows; built-in groups are
    synthesized (see module docstring) and never persisted."""
    org_id: str
    id: str
    name: str
    kind: str = FUNCTION
    description: str = ""
    #: The Action Hub trigger that carries this function's departures ("" = no channel
    #: yet — the group still routes, the destination just names no channel).
    channel_trigger_id: str = ""
    created_at: str = ""
    updated_at: str = ""


def _conn() -> sqlite3.Connection:
    c = connect_store(db_path())
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            org_id             TEXT NOT NULL,
            id                 TEXT NOT NULL,
            name               TEXT NOT NULL,
            description        TEXT NOT NULL DEFAULT '',
            channel_trigger_id TEXT NOT NULL DEFAULT '',
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            PRIMARY KEY (org_id, id)
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS group_members (
            org_id     TEXT NOT NULL,
            group_id   TEXT NOT NULL,
            principal  TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (org_id, group_id, principal)
        )
        """
    )
    # Reverse lookup: every group a principal belongs to (the access resolver's read).
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_group_members_principal"
        " ON group_members(org_id, principal)"
    )
    c.commit()


def _row_to_group(row: sqlite3.Row) -> Group:
    return Group(
        org_id=row["org_id"], id=row["id"], name=row["name"], kind=FUNCTION,
        description=row["description"], channel_trigger_id=row["channel_trigger_id"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def valid_group_id(group_id: str) -> bool:
    """A group id is a slug — it appears inside ``group:<id>`` principal strings and
    grant rows, so the vocabulary stays greppable and colon-free."""
    return bool(_SLUG_RE.match(group_id or ""))


# ── Groups ───────────────────────────────────────────────────────────────────

def upsert_group(org_id: str, group_id: str, name: str, description: str = "",
                 channel_trigger_id: str = "") -> Group:
    """Create or update a function group. Idempotent on (org_id, id)."""
    if not valid_group_id(group_id):
        raise ValueError(f"not a valid group id: {group_id!r} (lowercase slug, max 64)")
    now = _now()
    c = _conn()
    ensure_once(c, _ensure_schema)
    c.execute(
        """
        INSERT INTO groups (org_id, id, name, description, channel_trigger_id,
                            created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(org_id, id) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            channel_trigger_id = excluded.channel_trigger_id,
            updated_at = excluded.updated_at
        """,
        (org_id, group_id, name or group_id, description, channel_trigger_id, now, now),
    )
    c.commit()
    return get_group(org_id, group_id)  # type: ignore[return-value]


def get_group(org_id: str, group_id: str) -> Optional[Group]:
    c = _conn()
    ensure_once(c, _ensure_schema)
    row = c.execute(
        "SELECT * FROM groups WHERE org_id = ? AND id = ?", (org_id, group_id)
    ).fetchone()
    return _row_to_group(row) if row else None


def list_groups(org_id: str) -> List[Group]:
    c = _conn()
    ensure_once(c, _ensure_schema)
    rows = c.execute(
        "SELECT * FROM groups WHERE org_id = ? ORDER BY id ASC", (org_id,)
    ).fetchall()
    return [_row_to_group(r) for r in rows]


def delete_group(org_id: str, group_id: str) -> bool:
    """Remove a group and its memberships. Grant rows (``group:<id>`` in the
    metastore) are the caller's to revoke — two stores, one transaction each, and a
    dangling grant on a deleted group grants nobody anything (no member resolves it)."""
    c = _conn()
    ensure_once(c, _ensure_schema)
    c.execute("DELETE FROM group_members WHERE org_id = ? AND group_id = ?",
              (org_id, group_id))
    cur = c.execute("DELETE FROM groups WHERE org_id = ? AND id = ?", (org_id, group_id))
    c.commit()
    return cur.rowcount > 0


# ── Membership ───────────────────────────────────────────────────────────────

def add_member(org_id: str, group_id: str, principal: str) -> None:
    """Add a person (``user:...``) or an agent (``agent:...``) to a group.
    Idempotent. Refuses a principal outside those two kinds — a workspace or a group
    is not a member (no nested groups in the first slice; a union of flat groups is
    already additive, and nesting adds cycles before it adds expressiveness)."""
    if principal_kind(principal) not in ("user", "agent"):
        raise ValueError(f"not a member principal: {principal!r} (user:... or agent:...)")
    if get_group(org_id, group_id) is None:
        raise KeyError(f"no such group: {group_id!r}")
    c = _conn()
    ensure_once(c, _ensure_schema)
    c.execute(
        """
        INSERT INTO group_members (org_id, group_id, principal, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(org_id, group_id, principal) DO NOTHING
        """,
        (org_id, group_id, principal, _now()),
    )
    c.commit()


def remove_member(org_id: str, group_id: str, principal: str) -> bool:
    c = _conn()
    ensure_once(c, _ensure_schema)
    cur = c.execute(
        "DELETE FROM group_members WHERE org_id = ? AND group_id = ? AND principal = ?",
        (org_id, group_id, principal),
    )
    c.commit()
    return cur.rowcount > 0


def list_members(org_id: str, group_id: str) -> List[str]:
    c = _conn()
    ensure_once(c, _ensure_schema)
    rows = c.execute(
        "SELECT principal FROM group_members WHERE org_id = ? AND group_id = ?"
        " ORDER BY principal ASC",
        (org_id, group_id),
    ).fetchall()
    return [r["principal"] for r in rows]


def groups_of(org_id: str, principal: str) -> List[str]:
    """Every group id ``principal`` belongs to — the resolver's and router's read."""
    c = _conn()
    ensure_once(c, _ensure_schema)
    rows = c.execute(
        "SELECT group_id FROM group_members WHERE org_id = ? AND principal = ?"
        " ORDER BY group_id ASC",
        (org_id, principal),
    ).fetchall()
    return [r["group_id"] for r in rows]
