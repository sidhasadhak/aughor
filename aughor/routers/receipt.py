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

    receipt = build_public_receipt(
        raw, connection=_connection_view(conn_id),
        health_caveats=_health_caveats(conn_id, raw))
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such receipt")
    return receipt


def _health_caveats(conn_id, raw: dict) -> list:
    """Wave Q4 — the data-quality caveats for the tables this answer read.

    Computed HERE rather than inside `build_public_receipt` because that projection is
    documented pure and other callers rely on it; the store read belongs on the side that
    already does I/O and holds the connection.

    Best-effort by construction: a quality plane that can break a receipt is a quality
    plane operators disable, so an unreadable store yields no caveats and the receipt
    renders exactly as it did before Q existed.
    """
    if not conn_id:
        return []
    try:
        from aughor.quality.caveats import caveats_for_answer

        payload = (raw.get("artifact") or {}).get("payload") or {}
        lineage = raw.get("lineage") or []
        # Prefer the lineage's declared input tables — they are what the answer actually
        # READ, where the payload's list is what the planner intended. A caveat about a
        # table the query never touched is noise the reader has to learn to ignore.
        tables = [(e.get("ref") or "").split("table:", 1)[1] for e in lineage
                  if e.get("relation") == "input"
                  and (e.get("ref") or "").startswith("table:")]
        tables = tables or list(payload.get("tables") or [])
        if not tables:
            return []
        return caveats_for_answer(str(conn_id), tables)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "health caveats are best-effort; the receipt renders without them",
                 counter="quality.receipt_caveats")
        return []
