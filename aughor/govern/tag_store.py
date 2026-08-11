"""SQLite-backed store for governed tags (Wave G2) — org-scoped, provenance-required.

Persistence only, mirroring the `metastore/` + `org/` store conventions: idempotent
``_ensure_schema``, a ``_row_to_tag`` marshaller, CRUD. The policy — which tags gate and
which clearance each demands — lives in :mod:`aughor.govern.tags` and never touches a
database, so it stays testable without one.

**Provenance is required, not decorative.** ``set_tag`` refuses a write with no
``set_by``. A tag is an access-control fact; one that cannot say who asserted it is not
evidence, and the moment it becomes convenient to omit is the moment the plane stops
being auditable. This is J4's discipline reaching past the context graph — the same rule
that keeps a model from authoring a finding keeps an anonymous process from authoring a
clearance requirement.

**Deletes are real deletes here, deliberately.** Elsewhere the repo tombstones rather
than removes (C1's supersede-not-delete). A tag is the opposite case: leaving a retracted
``pii=true`` behind as a tombstone that still reads as present would keep denying access
after governance decided it should not. The audit trail belongs in the audit log, which
``set_tag``/``clear_tag`` both write, not in a row that still gates.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path
from aughor.db.backend import connect_store
from aughor.db.store_pool import ensure_once
from aughor.govern.tags import Tag, is_securable
from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now

_DB_PATH = resolve_db_path(
    "AUGHOR_GOVERN_TAGS_DB",
    Path(__file__).parent.parent.parent / "data" / "govern_tags.db")

_AUDIT_KIND = "govern.tag"


def _conn() -> sqlite3.Connection:
    c = connect_store(_DB_PATH)
    c.row_factory = sqlite3.Row
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS govern_tags (
            org_id     TEXT NOT NULL DEFAULT 'default',
            securable  TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            set_by     TEXT NOT NULL,
            set_at     TEXT NOT NULL,
            source     TEXT NOT NULL DEFAULT 'human',
            PRIMARY KEY (org_id, securable, key)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_govern_tags_key "
              "ON govern_tags (org_id, key, value)")
    c.commit()


def _row_to_tag(row: sqlite3.Row) -> Tag:
    return Tag(securable=row["securable"], key=row["key"], value=row["value"],
               set_by=row["set_by"], set_at=row["set_at"], source=row["source"])


def _audit(action: str, payload: dict) -> None:
    """Journal the change. Best-effort: a governance write must not fail because the
    audit sink is unavailable, but the failure is counted rather than swallowed."""
    try:
        from aughor.kernel.ledger import Ledger

        Ledger.default().emit(_AUDIT_KIND, {"action": action, **payload})
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "governance tag audit is best-effort; the write itself succeeded",
                 counter="govern.tag_audit")


def set_tag(securable: str, key: str, value: str, *, set_by: str,
            source: str = "human", org_id: Optional[str] = None) -> Tag:
    """Set (or replace) one governed tag. Raises on a malformed securable or no author."""
    if not is_securable(securable):
        raise ValueError(
            f"{securable!r} is not a securable — expected catalog:/schema:/table:/artifact:")
    key = str(key or "").strip().lower()
    if not key:
        raise ValueError("a tag needs a key")
    if not str(set_by or "").strip():
        # The one refusal worth being loud about: an access-control fact with no author
        # is not evidence, and defaulting it to "system" would launder exactly that.
        raise ValueError("a governed tag must record who set it (set_by)")

    org = org_id or current_org_id()
    tag = Tag(securable=securable, key=key, value=str(value), set_by=set_by,
              set_at=_now(), source=source)
    with _conn() as c:
        c.execute(
            "INSERT INTO govern_tags (org_id, securable, key, value, set_by, set_at, source) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(org_id, securable, key) DO UPDATE SET "
            "value=excluded.value, set_by=excluded.set_by, set_at=excluded.set_at, "
            "source=excluded.source",
            (org, tag.securable, tag.key, tag.value, tag.set_by, tag.set_at, tag.source))
        c.commit()
    _audit("set", {"org_id": org, **tag.to_dict()})
    return tag


def clear_tag(securable: str, key: str, *, cleared_by: str = "",
              org_id: Optional[str] = None) -> bool:
    """Remove one tag. Returns whether a row was actually removed."""
    org = org_id or current_org_id()
    key = str(key or "").strip().lower()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM govern_tags WHERE org_id=? AND securable=? AND key=?",
            (org, securable, key))
        c.commit()
        removed = cur.rowcount > 0
    if removed:
        _audit("clear", {"org_id": org, "securable": securable, "key": key,
                         "cleared_by": cleared_by})
    return removed


def tags_for(securable: str, *, org_id: Optional[str] = None) -> list[Tag]:
    """Every governed tag on one securable, key-ordered so decisions are stable."""
    org = org_id or current_org_id()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM govern_tags WHERE org_id=? AND securable=? ORDER BY key",
            (org, securable)).fetchall()
    return [_row_to_tag(r) for r in rows]


def list_tags(*, key: Optional[str] = None, securable_prefix: Optional[str] = None,
              org_id: Optional[str] = None, limit: int = 500) -> list[Tag]:
    """Browse the plane — by key (``pii``), by securable kind (``table:``), or all."""
    org = org_id or current_org_id()
    sql = "SELECT * FROM govern_tags WHERE org_id=?"
    args: list = [org]
    if key:
        sql += " AND key=?"
        args.append(str(key).strip().lower())
    if securable_prefix:
        sql += " AND securable LIKE ?"
        args.append(f"{securable_prefix}%")
    sql += " ORDER BY securable, key LIMIT ?"
    args.append(max(1, int(limit)))
    with _conn() as c:
        return [_row_to_tag(r) for r in c.execute(sql, args).fetchall()]
