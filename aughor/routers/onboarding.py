"""The day-one door (the 2027 study §P and §W, phase 6) — ``GET /onboarding``: hours from connect to
the first relied-on claim against the release gate, the data shopping list, coverage, and the bound
packs' priors and templates, for one connection. Reads only; a person confirms what it proposes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from aughor.security.authz import connection_owner_guard

router = APIRouter(tags=["onboarding"], dependencies=[Depends(connection_owner_guard)])
BUILTIN_ID = "builtin"


@router.get("/onboarding")
def get_onboarding(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None),
                   pack_id: str = Query(default="", description="measure one pack's map against the connection; "
                                                                 "default: the packs bound to it")) -> dict:
    from aughor.agent.framing import served_graph
    from aughor.packs.onboarding import GATE_HOURS, onboarding
    graph = served_graph(connection_id, schema_name)       # a read; never builds
    context_graph = None
    try:
        from aughor.ontology.context_graph_store import load_graph
        from aughor.org.context import current_org_id
        context_graph = load_graph(current_org_id(), connection_id, schema_name or (getattr(graph, "schema_name", "") or ""))
    except Exception as exc:  # noqa: BLE001 — the joins line is additive
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the context graph could not be read for the coverage line", counter="onboarding.context_graph")
    out = onboarding(connection_id, schema_name, pack_id=pack_id, graph=graph, context_graph=context_graph)
    out["gate"] = {"hours": GATE_HOURS, "rule": "connect to the first claim a decision relied on, in under a day — a release gate, measured on a customer's install"}
    return out
