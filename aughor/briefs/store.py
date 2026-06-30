"""Brief subscription persistence — data/brief_subscriptions.json.

Mirrors the Action Hub trigger store: a flat JSON list, upsert-by-id, idempotent.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from aughor.briefs.models import BriefSubscription

_PATH = Path("data/brief_subscriptions.json")


from aughor.util.time import now_iso_z as _now


def _load() -> list[dict]:
    try:
        if _PATH.exists():
            return json.loads(_PATH.read_text())
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "subscription store read is best-effort; a missing/corrupt file degrades to an empty list",
                 counter="briefs.store.load")
    return []


def _save(rows: list[dict]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(rows, indent=2, default=str))


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
