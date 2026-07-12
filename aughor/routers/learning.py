"""Learning / Memory-layer read API (Wave 1 · E4) — make the closed loop's accumulation visible.

Aughor's closed loop (ambiguity ledger → priors → verdicts → trusted queries/programs) is captured and
read back into prompts, but its *accumulation* was invisible: ``ledger_stats`` had no HTTP endpoint at all,
``/verify/verdicts/stats`` had zero consumers, and trusted assets were injected authoritatively into prompts
yet never displayed. These additive, read-only endpoints expose the "moat metric" as one coherent surface —
the backend the Agent Workspace Memory layer renders. Purely observability over existing stores: no answer
path changes, nothing gated, byte-identical behaviour everywhere else.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from aughor.org.context import current_org_id

router = APIRouter(tags=["learning"])


@router.get("/learning/summary")
def learning_summary(connection_id: Optional[str] = None):
    """The Memory-layer headline in one call: the ambiguity-ledger burn-down (resolutions crystallized by
    source + total times served — should grow as fresh probes/asks shrink), the verdict acceptance economy
    (the non-circular calibration signal), and trusted-asset counts. Scoped to the current org, optionally
    to one connection."""
    from aughor.semantic.ambiguity_ledger import ledger_stats
    from aughor.semantic.trusted_programs import list_trusted_programs
    from aughor.semantic.trusted_queries import list_trusted
    from aughor.verify import verdict_stats

    org = current_org_id()
    cid = connection_id or ""
    return {
        "connection_id": connection_id,
        "ledger": ledger_stats(cid, org_id=org),      # {resolutions, by_source, served_total}
        "verdicts": verdict_stats(connection_id),      # {counts, acceptance_rate, ...}
        "trusted": {
            "queries": len(list_trusted(cid)),
            "programs": len(list_trusted_programs(cid, org_id=org)),
        },
    }


@router.get("/learning/trusted")
def learning_trusted(connection_id: Optional[str] = None):
    """The trusted assets themselves — curated queries and replayable plan-as-programs injected
    authoritatively into prompts, now inspectable. Programs return metadata only (the serialized program
    body is omitted from the list view). Scoped to the current org, optionally to one connection."""
    from aughor.semantic.trusted_programs import list_trusted_programs
    from aughor.semantic.trusted_queries import list_trusted

    org = current_org_id()
    cid = connection_id or ""
    return {
        "queries": [q.model_dump() for q in list_trusted(cid)],
        "programs": [p.model_dump(exclude={"program"}) for p in list_trusted_programs(cid, org_id=org)],
    }
