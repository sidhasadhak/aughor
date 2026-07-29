"""SQLite store for usage caps (Wave G4) — org-scoped, provenance-required.

Persistence only; the algebra lives in :mod:`aughor.govern.usage_caps` and never touches a
database, so most-permissive-within / most-restrictive-across stay testable without one.

Follows the G2 tag store's conventions deliberately, including the two decisions that
matter for a governance record: an author is REQUIRED (a limit nobody set is not a policy),
and removal is a real delete rather than a tombstone (a retired cap that still reads as
present would keep refusing work after the operator lifted it — the audit trail belongs in
the audit log, which both mutations write).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.govern.usage_caps import ACTIONS, METRICS, SCOPES, UsageCap
from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now

_DB_PATH = resolve_db_path(
    "AUGHOR_GOVERN_CAPS_DB",
    Path(__file__).parent.parent.parent / "data" / "govern_caps.db")

_AUDIT_KIND = "govern.cap"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS govern_caps (
            org_id       TEXT NOT NULL DEFAULT 'default',
            scope        TEXT NOT NULL,
            subject      TEXT NOT NULL,
            metric       TEXT NOT NULL,
            limit_value  REAL NOT NULL,
            window_hours INTEGER NOT NULL DEFAULT 24,
            action       TEXT NOT NULL DEFAULT 'alert',
            set_by       TEXT NOT NULL,
            set_at       TEXT NOT NULL,
            PRIMARY KEY (org_id, scope, subject, metric, window_hours)
        )
    """)
    c.commit()


def _row_to_cap(row: sqlite3.Row) -> UsageCap:
    return UsageCap(scope=row["scope"], subject=row["subject"], metric=row["metric"],
                    limit=row["limit_value"], window_hours=row["window_hours"],
                    action=row["action"])


def _audit(action: str, payload: dict) -> None:
    try:
        from aughor.kernel.ledger import Ledger

        Ledger.default().emit(_AUDIT_KIND, {"action": action, **payload})
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "usage-cap audit is best-effort; the write itself succeeded",
                 counter="govern.cap_audit")


def set_cap(scope: str, subject: str, metric: str, limit: float, *,
            window_hours: int = 24, action: str = "alert", set_by: str,
            org_id: Optional[str] = None) -> UsageCap:
    """Declare (or replace) one cap. Raises on an unknown dimension or no author."""
    if scope not in SCOPES:
        raise ValueError(f"unknown cap scope {scope!r} — known: {list(SCOPES)}")
    if metric not in METRICS:
        raise ValueError(f"unknown cap metric {metric!r} — known: {list(METRICS)}")
    if action not in ACTIONS:
        raise ValueError(f"unknown cap action {action!r} — known: {list(ACTIONS)}")
    if float(limit) < 0:
        raise ValueError("a cap limit cannot be negative")
    if not str(set_by or "").strip():
        raise ValueError("a usage cap must record who set it (set_by)")

    org = org_id or current_org_id()
    cap = UsageCap(scope=scope, subject=str(subject or "*"), metric=metric,
                   limit=float(limit), window_hours=max(1, int(window_hours)),
                   action=action)  # type: ignore[arg-type]
    with _conn() as c:
        c.execute(
            "INSERT INTO govern_caps (org_id, scope, subject, metric, limit_value, "
            "window_hours, action, set_by, set_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(org_id, scope, subject, metric, window_hours) DO UPDATE SET "
            "limit_value=excluded.limit_value, action=excluded.action, "
            "set_by=excluded.set_by, set_at=excluded.set_at",
            (org, cap.scope, cap.subject, cap.metric, cap.limit, cap.window_hours,
             cap.action, set_by, _now()))
        c.commit()
    _audit("set", {"org_id": org, "set_by": set_by, **cap.to_dict()})
    return cap


def clear_cap(scope: str, subject: str, metric: str, *, window_hours: int = 24,
              cleared_by: str = "", org_id: Optional[str] = None) -> bool:
    """Remove one cap. Returns whether a row was actually removed."""
    org = org_id or current_org_id()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM govern_caps WHERE org_id=? AND scope=? AND subject=? "
            "AND metric=? AND window_hours=?",
            (org, scope, str(subject or "*"), metric, max(1, int(window_hours))))
        c.commit()
        removed = cur.rowcount > 0
    if removed:
        _audit("clear", {"org_id": org, "scope": scope, "subject": subject,
                         "metric": metric, "window_hours": window_hours,
                         "cleared_by": cleared_by})
    return removed


def list_caps(*, org_id: Optional[str] = None, limit: int = 500) -> list[UsageCap]:
    """Every cap declared for an org."""
    org = org_id or current_org_id()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM govern_caps WHERE org_id=? ORDER BY scope, metric, subject "
            "LIMIT ?", (org, max(1, int(limit)))).fetchall()
    return [_row_to_cap(r) for r in rows]
