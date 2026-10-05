"""The organisation's Briefing — the fold of every connection's latest kept Briefing (the 2027 study
§E item 2, "the organisation first, the connection second"; the arc's close-out, C2).

A Briefing is written per connection and kept per connection (`briefing/versions.py`); the
organisation is the scope a reader holds, and until now nothing read across its connections. This
module folds what IS kept — no new narrative, no model call: each visible connection's latest kept
Briefing with its as-of, its version, its headline theme, its lede and its measured figures — into
one view, and says of each connection that has no kept Briefing yet that it has none, rather than
leaving it out. Served by ``GET /briefing/organisation``. The kernel's ``artifacts_of_kind`` is
organisation-scoped, so another organisation's Briefings are not in the fold by construction.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.briefing.versions import KIND, figures


def _visible_connections() -> list[dict]:
    """The connections this reader's organisation can see: the registry's own filter when identity
    is on, every registered connection when it is off (one tenant)."""
    try:
        from aughor.db.registry import list_connections
        return list(list_connections() or [])
    except Exception as exc:  # noqa: BLE001 — a registry that cannot answer folds nothing, and says so
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the connections could not be listed for the organisation's Briefing", counter="briefing.organisation")
        return []


def _lede(narrative: str) -> str:
    text = (narrative or "").strip()
    return text.split("\n\n", 1)[0][:600] if text else ""


def latest_kept(conn_id: str) -> Optional[dict]:
    """The newest kept Briefing version for a connection, as the ledger holds it, or None."""
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().artifacts_of_kind(KIND, conn_id=conn_id, limit=1)
    return rows[0] if rows else None


def organisation_briefing(*, now: Optional[str] = None) -> dict[str, Any]:
    """The fold. ``briefings`` is newest first; every connection is a row, with or without one."""
    from aughor.org.context import current_org_id
    rows: list[dict] = []
    for c in _visible_connections():
        cid = str(c.get("id") or "")
        if not cid:
            continue
        row: dict[str, Any] = {"connection_id": cid, "connection_name": str(c.get("name") or cid)}
        try:
            art = latest_kept(cid)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"the kept Briefing of {cid} could not be read", counter="briefing.organisation", conn_id=cid)
            art = None
        if art is None:
            row.update({"briefing": None, "note": "no Briefing kept for this connection yet"})
            rows.append(row)
            continue
        payload = dict(art.get("payload") or {})
        brief = dict(payload.get("briefing") or {})
        row.update({
            "as_of": str(payload.get("as_of") or art.get("created_at") or "")[:10],
            "version": int(art.get("version") or 0),
            "scope_key": str(payload.get("scope_key") or ""),
            "range_key": str(payload.get("range_key") or ""),
            "headline_theme": str(brief.get("headline_theme") or ""),
            "lede": _lede(str(brief.get("narrative") or "")),
            "figures": figures(brief),
            "revisions": len(payload.get("revisions") or []),
            "artifact_id": str(art.get("id") or ""),
        })
        rows.append(row)
    rows.sort(key=lambda r: (r.get("as_of") or "", r.get("connection_id") or ""), reverse=True)
    kept = [r for r in rows if r.get("briefing", "") is not None]
    return {
        "organisation": current_org_id(),
        "connections": len(rows),
        "with_briefing": len(kept),
        "briefings": rows,
        "note": ("the fold of each connection's latest kept Briefing — no new narrative is written across "
                 "connections; a connection with none kept says so"),
    }
