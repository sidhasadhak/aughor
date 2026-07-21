"""SQLite-backed dashboard-card store.

Mirrors aughor/savedquery/store.py: one `dashboard_cards` table, flat columns for the
queryable identity/scope fields + JSON columns for the nested (frontend-owned or structured)
parts, idempotent schema creation on every operation. Scoped: `list_cards` filters by any of
connection_id / scope / scope_ref so a canvas cockpit, a shared workspace dashboard, or a
personal set can each be fetched independently.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional

from aughor.dashboard.models import CardProvenance, CardRefresh, DashboardCard
from aughor.util.time import now_iso as _now
from aughor.db.sqlite_util import resolve_db_path, tune

_DB_PATH = resolve_db_path(
    "AUGHOR_DASHBOARD_DB", Path(__file__).parent.parent.parent / "data" / "dashboard_cards.db"
)


def _conn() -> sqlite3.Connection:
    c = tune(sqlite3.connect(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_cards (
            id              TEXT PRIMARY KEY,
            connection_id   TEXT NOT NULL DEFAULT '',
            scope           TEXT NOT NULL DEFAULT 'canvas',
            scope_ref       TEXT NOT NULL DEFAULT '',
            source          TEXT NOT NULL DEFAULT 'authored',
            kind            TEXT NOT NULL DEFAULT 'kpi',
            title           TEXT NOT NULL DEFAULT '',
            sql             TEXT NOT NULL DEFAULT '',
            query_ref       TEXT,
            body            TEXT NOT NULL DEFAULT '',
            author          TEXT NOT NULL DEFAULT '',
            render_json     TEXT NOT NULL DEFAULT '{}',
            refresh_json    TEXT NOT NULL DEFAULT '{}',
            thresholds_json TEXT NOT NULL DEFAULT '{}',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            links_json      TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_dashboard_cards_scope ON dashboard_cards(scope, scope_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_dashboard_cards_conn ON dashboard_cards(connection_id)")
    # Cockpit layout — the user's arrangement (position + size per card) on a connection, saved at
    # the ACCOUNT level so any login/device sees the same cockpit. Keyed by (connection, user); the
    # user is 'default' until identity/RBAC is on, so it upgrades to true per-user with no migration.
    c.execute("""
        CREATE TABLE IF NOT EXISTS card_layouts (
            connection_id TEXT NOT NULL DEFAULT '',
            user_id       TEXT NOT NULL DEFAULT 'default',
            layout_json   TEXT NOT NULL DEFAULT '{}',
            updated_at    TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (connection_id, user_id)
        )
    """)
    # Per-chart display config for surfaces that have NO card row of their own — a findings-ledger
    # row, a digest tile, a KPI trend. A pinned card already persists its display in
    # `dashboard_cards.render`; these are charts the user edits in place, keyed by the thing they
    # are ABOUT (the insight) rather than by a card. Account-keyed like `card_layouts`, and scoped
    # by the same `scope_key` the briefing stamps ('<conn>:<schema>' | '<conn>' | 'canvas:<id>')
    # so one schema's edits never surface under another's.
    c.execute("""
        CREATE TABLE IF NOT EXISTS viz_configs (
            scope_key   TEXT NOT NULL DEFAULT '',
            target_id   TEXT NOT NULL,
            user_id     TEXT NOT NULL DEFAULT 'default',
            config_json TEXT NOT NULL DEFAULT '{}',
            updated_at  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (scope_key, target_id, user_id)
        )
    """)
    c.commit()


def _loads(raw: str, fallback):
    try:
        val = json.loads(raw)
        return val if isinstance(val, type(fallback)) else fallback
    except Exception:
        return fallback


def _row_to_card(row: sqlite3.Row) -> DashboardCard:
    return DashboardCard(
        id=row["id"],
        connection_id=row["connection_id"],
        scope=row["scope"],
        scope_ref=row["scope_ref"],
        source=row["source"],
        kind=row["kind"],
        title=row["title"],
        sql=row["sql"] or "",
        query_ref=row["query_ref"],
        render=_loads(row["render_json"] or "{}", {}),
        refresh=CardRefresh(**_loads(row["refresh_json"] or "{}", {})),
        thresholds=_loads(row["thresholds_json"] or "{}", {}),
        provenance=CardProvenance(**_loads(row["provenance_json"] or "{}", {})),
        links=_loads(row["links_json"] or "[]", []),
        body=row["body"] or "",
        author=row["author"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def upsert_card(card: DashboardCard) -> DashboardCard:
    """Create or update a card. Assigns an id + created_at on first write; always bumps
    updated_at. Returns the persisted card."""
    now = _now()
    cid = card.id or uuid.uuid4().hex[:8]
    c = _conn()
    _ensure_schema(c)
    existing = c.execute(
        "SELECT created_at FROM dashboard_cards WHERE id = ?", (cid,)
    ).fetchone()
    created_at = existing["created_at"] if existing else (card.created_at or now)
    card = card.model_copy(update={"id": cid, "created_at": created_at, "updated_at": now})
    c.execute(
        """INSERT INTO dashboard_cards
            (id, connection_id, scope, scope_ref, source, kind, title, sql, query_ref, body,
             author, render_json, refresh_json, thresholds_json, provenance_json, links_json,
             created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             connection_id=excluded.connection_id, scope=excluded.scope,
             scope_ref=excluded.scope_ref, source=excluded.source, kind=excluded.kind,
             title=excluded.title, sql=excluded.sql, query_ref=excluded.query_ref,
             body=excluded.body, author=excluded.author, render_json=excluded.render_json,
             refresh_json=excluded.refresh_json, thresholds_json=excluded.thresholds_json,
             provenance_json=excluded.provenance_json, links_json=excluded.links_json,
             updated_at=excluded.updated_at""",
        (
            card.id, card.connection_id, card.scope, card.scope_ref, card.source, card.kind,
            card.title, card.sql, card.query_ref, card.body, card.author,
            json.dumps(card.render or {}),
            card.refresh.model_dump_json(),
            json.dumps(card.thresholds or {}),
            card.provenance.model_dump_json(),
            json.dumps(card.links or []),
            card.created_at, card.updated_at,
        ),
    )
    c.commit()
    return card


def get_card(card_id: str) -> Optional[DashboardCard]:
    c = _conn()
    _ensure_schema(c)
    row = c.execute("SELECT * FROM dashboard_cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row) if row else None


def get_layout(connection_id: str, user_id: str) -> dict:
    """The saved cockpit layout ({card_id: {x, y, w, h}}) for a user on a connection ({} if none)."""
    c = _conn()
    _ensure_schema(c)
    row = c.execute(
        "SELECT layout_json FROM card_layouts WHERE connection_id = ? AND user_id = ?",
        (connection_id, user_id),
    ).fetchone()
    return _loads(row["layout_json"] or "{}", {}) if row else {}


def set_layout(connection_id: str, user_id: str, layout: dict) -> None:
    """Persist a user's cockpit layout (position + size per card) for a connection."""
    c = _conn()
    _ensure_schema(c)
    c.execute(
        """INSERT INTO card_layouts (connection_id, user_id, layout_json, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(connection_id, user_id) DO UPDATE SET
             layout_json = excluded.layout_json, updated_at = excluded.updated_at""",
        (connection_id, user_id, json.dumps(layout or {}), _now()),
    )
    c.commit()


def get_viz_configs(scope_key: str, user_id: str) -> dict:
    """Every saved chart config in a scope, as ``{target_id: config}``.

    Returned whole rather than per-chart: a brief renders many charts at once, and one fetch
    on mount beats N round-trips as rows expand."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        "SELECT target_id, config_json FROM viz_configs WHERE scope_key = ? AND user_id = ?",
        (scope_key, user_id),
    ).fetchall()
    return {r["target_id"]: _loads(r["config_json"] or "{}", {}) for r in rows}


def set_viz_config(scope_key: str, target_id: str, user_id: str, config: dict) -> None:
    """Persist one chart's display config. An EMPTY config deletes the row — "back to default"
    must leave no trace, so a later change to the default is picked up rather than shadowed by
    a stored copy of the old one."""
    c = _conn()
    _ensure_schema(c)
    if not config:
        c.execute(
            "DELETE FROM viz_configs WHERE scope_key = ? AND target_id = ? AND user_id = ?",
            (scope_key, target_id, user_id),
        )
    else:
        c.execute(
            """INSERT INTO viz_configs (scope_key, target_id, user_id, config_json, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(scope_key, target_id, user_id) DO UPDATE SET
                 config_json = excluded.config_json, updated_at = excluded.updated_at""",
            (scope_key, target_id, user_id, json.dumps(config), _now()),
        )
    c.commit()


def list_cards(
    connection_id: Optional[str] = None,
    scope: Optional[str] = None,
    scope_ref: Optional[str] = None,
) -> List[DashboardCard]:
    """Cards matching the given filters, newest-updated first. Any filter left None is
    ignored, so `list_cards(scope='canvas', scope_ref=canvas_id)` returns one canvas's
    cockpit and `list_cards()` returns everything."""
    clauses, params = [], []
    if connection_id is not None:
        clauses.append("connection_id = ?"); params.append(connection_id)
    if scope is not None:
        clauses.append("scope = ?"); params.append(scope)
    if scope_ref is not None:
        clauses.append("scope_ref = ?"); params.append(scope_ref)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        f"SELECT * FROM dashboard_cards{where} ORDER BY updated_at DESC", params
    ).fetchall()
    return [_row_to_card(r) for r in rows]


def delete_card(card_id: str) -> bool:
    c = _conn()
    _ensure_schema(c)
    affected = c.execute("DELETE FROM dashboard_cards WHERE id = ?", (card_id,)).rowcount
    c.commit()
    return bool(affected and affected > 0)
