"""WP-10 — the unified public Trust Receipt surface: `GET /receipt/{receipt_id}`.

One id (the kernel ledger artifact id) resolves an answer of any mode (quick / deep /
builder / briefing figure) into one signed, inspectable contract — executed SQL, input
tables, the guards that fired, caveats, governed-metric enforcement, cost and model — so
every number a user sees can open the same "why this number" object.

RBAC: a receipt is visible only when its connection is in the caller's org. A foreign (or
missing) id returns 404 identically, so the surface never leaks which receipts exist.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(tags=["receipt"])


def _connection_view(conn_id: Optional[str]) -> dict:
    """A small {id, name, dialect} view of the receipt's connection (best-effort)."""
    if not conn_id:
        return {"id": conn_id, "name": None, "dialect": None}
    try:
        from aughor.db.registry import get_meta, list_connections
        c = next((x for x in list_connections() if x.get("id") == conn_id), None)
        meta = get_meta(conn_id) or {}
        return {"id": conn_id, "name": (c or {}).get("name"),
                "dialect": meta.get("dialect") or (c or {}).get("conn_type")}
    except Exception:
        logger.debug("connection view lookup failed for %s", conn_id, exc_info=True)
        return {"id": conn_id, "name": None, "dialect": None}


@router.get("/receipt/{receipt_id}")
def get_receipt(receipt_id: str) -> dict:
    """The unified public Trust Receipt for one answer id. 404 when absent OR outside the
    caller's org (fail-closed, no existence leak)."""
    from aughor.kernel.ledger import Ledger
    from aughor.security.authz import org_visible_conn_ids
    from aughor.trust.receipt import build_public_receipt

    raw = Ledger.default().receipt_by_id(receipt_id)
    if raw is None or not raw.get("artifact"):
        raise HTTPException(status_code=404, detail="No such receipt")

    conn_id = raw["artifact"].get("conn_id")
    # DATA-06 read-path: under identity, only receipts on a connection this org can see.
    visible = org_visible_conn_ids()
    if visible is not None and (conn_id is None or conn_id not in visible):
        raise HTTPException(status_code=404, detail="No such receipt")

    receipt = build_public_receipt(raw, connection=_connection_view(conn_id))
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt")
    return receipt
