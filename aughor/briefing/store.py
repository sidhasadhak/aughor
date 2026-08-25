"""Brief subscription persistence — the Ledger, with data/brief_subscriptions.json
as the legacy file it imports once and falls back to.

Mirrors the Action Hub trigger store: a flat list, upsert-by-id, idempotent. The
truth moved off the bare file because a serverless bundle ships ``data/`` empty
and read-only: every deployed instance read an empty list (so the cron tick
evaluated zero briefs, forever) and creating a subscription failed on the write.
:class:`~aughor.util.json_store.LedgerListStore` rides the Ledger — Postgres
behind ``AUGHOR_DB_URL`` on serverless — so a subscription survives the instance
that created it; local deployments keep working file-first via its fallback.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from aughor.briefing.models import BriefSubscription
from aughor.db.sqlite_util import resolve_db_path
from aughor.util.json_store import LedgerListStore

# Honour an AUGHOR_BRIEFS_FILE override (the conftest points it at a temp dir) so the
# suite can never mutate the live data/ store — the OPS-02/DATA-01 hermeticity rule.
_PATH = resolve_db_path("AUGHOR_BRIEFS_FILE", Path("data/brief_subscriptions.json"))

_store = LedgerListStore(_PATH)


from aughor.util.time import now_iso_z as _now


def _load() -> list[dict]:
    return _store.all()


def _save(rows: list[dict]) -> None:
    _store.save_all(rows)


def list_subscriptions(conn_id: Optional[str] = None) -> list[BriefSubscription]:
    rows = _load()
    subs = [BriefSubscription(**r) for r in rows]
    if conn_id:
        subs = [s for s in subs if s.conn_id == conn_id]
    return subs


def get_subscription(sub_id: str) -> Optional[BriefSubscription]:
    for r in _load():
        if r.get("id") == sub_id:
            return BriefSubscription(**r)
    return None


def save_subscription(sub: BriefSubscription) -> BriefSubscription:
    """Insert (assigns id) or update by id. Bumps updated_at."""
    rows = _load()
    if not sub.id:
        sub.id = str(uuid.uuid4())[:8]
    sub.updated_at = _now()
    replaced = False
    for i, r in enumerate(rows):
        if r.get("id") == sub.id:
            rows[i] = sub.to_dict()
            replaced = True
            break
    if not replaced:
        rows.append(sub.to_dict())
    _save(rows)
    return sub


def delete_subscription(sub_id: str) -> bool:
    rows = _load()
    new_rows = [r for r in rows if r.get("id") != sub_id]
    if len(new_rows) == len(rows):
        return False
    _save(new_rows)
    return True


def delete_for_connection(conn_id: str) -> int:
    """Remove every brief subscription bound to a connection (catalog delete
    cascade). Returns the number removed."""
    rows = _load()
    kept = [r for r in rows if r.get("conn_id") != conn_id]
    removed = len(rows) - len(kept)
    if removed:
        _save(kept)
    return removed
