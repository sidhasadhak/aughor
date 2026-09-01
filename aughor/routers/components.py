"""DS-10 — the component registry's door: what this deployment can actually do.

A sibling of `/automations/palette` rather than a replacement for it. The palette answers a
narrower question ("what may I place on THIS canvas") and answers it in the shape the
canvas draws; this answers the whole one, across all five families, in the shape every
family reports. The palette is now served FROM the same registry, so the two can no longer
disagree about whether a kind exists or whether it works here.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["components"])


@router.get("/components")
def list_components(
    conn_id: Optional[str] = None,
    family: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    """Every capability of this deployment: triggers, effects, connectors, platform tools,
    MCP tools, and the declared actions of one connection.

    ``conn_id`` is what makes the answer deployment-shaped rather than version-shaped. Four
    of the six families are the same on every install of this build; the prerequisite
    readings (is there a Slack bot, a monitor, a subscription) and the declared actions are
    not, and both need a connection to be true about.

    ``q`` is a plain normalised substring over label · description · kind · family, the
    same match the palette panel already makes — not a second, subtly different search on
    the same rows.
    """
    from aughor.components import FAMILIES, components

    if family and family not in FAMILIES:
        raise HTTPException(status_code=422,
                            detail=f"unknown family '{family}' — one of {list(FAMILIES)}")
    rows = components(conn_id=conn_id, family=family, q=q)
    counts: dict[str, int] = {f: 0 for f in FAMILIES}
    for c in rows:
        counts[c.family] = counts.get(c.family, 0) + 1
    return {
        "components": [c.model_dump() for c in rows],
        "total": len(rows),
        "by_family": counts,
        # Echoed so a reader can tell "this deployment has no declared actions" from
        # "you did not tell me which connection to ask about" — the two look identical in
        # a list of rows, and only one of them is the reader's to fix.
        "conn_id": conn_id or "",
    }


@router.get("/components/families")
def list_families():
    """The families and the display states a component may carry — the closed sets a
    surface needs before it can render a filter it has never seen a value for."""
    from aughor.components import BADGES, FAMILIES

    return {"families": list(FAMILIES), "badges": list(BADGES)}
