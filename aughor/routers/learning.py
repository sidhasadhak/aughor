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
    from aughor.semantic.trusted_queries import list_trusted
    from aughor.feedback import verdict_stats

    org = current_org_id()
    cid = connection_id or ""
    return {
        "connection_id": connection_id,
        "ledger": ledger_stats(cid, org_id=org),      # {resolutions, by_source, served_total}
        "verdicts": verdict_stats(connection_id),      # {counts, acceptance_rate, ...}
        "trusted": {
            "queries": len(list_trusted(cid)),
        },
    }


@router.get("/learning/trusted")
def learning_trusted(connection_id: Optional[str] = None):
    """The trusted assets themselves — curated queries injected authoritatively into prompts,
    now inspectable. Scoped to the current org, optionally to one connection."""
    from aughor.semantic.trusted_queries import list_trusted

    cid = connection_id or ""
    return {
        "queries": [q.model_dump() for q in list_trusted(cid)],
    }


@router.get("/learning/resolutions")
def get_resolutions(connection_id: str = ""):
    """S5 cited memory — the remembered readings, listed with their citations:
    who settled each (probe/user/reviewer), when, and how many times it has been
    served as a prior. The revoke route below is what makes showing them honest."""
    from aughor.org.context import current_org_id
    from aughor.semantic.ambiguity_ledger import list_resolutions
    return [r.model_dump() for r in list_resolutions(connection_id, org_id=current_org_id() or "")]


@router.delete("/learning/resolutions/{res_id}", status_code=204)
def delete_resolution(res_id: str):
    """S5 cited memory — revoke one remembered reading. The next matching question
    re-ambiguates instead of inheriting a reading the user no longer stands behind."""
    from fastapi import HTTPException

    from aughor.semantic.ambiguity_ledger import revoke_resolution
    if not revoke_resolution(res_id):
        raise HTTPException(status_code=404, detail="No such resolution")


# ── MI-3: the dataset plane ──────────────────────────────────────────────────────────
#
# These sit in THIS router rather than a new one because they answer the same question it
# was built for — "is the closed loop actually accumulating?" — one step further along.
# Wave 1's endpoints made verdicts and trusted assets visible; these make the corpus those
# verdicts become visible, and publish the measured distance to MI-4's entry gates.
#
# Scheduling is deliberately absent. Periodic work joins the one loop that exists rather
# than growing a timer, and a nightly export over a two-example corpus is motion without
# progress. The gate report is what says when that changes.


@router.get("/learning/datasets")
def get_datasets():
    """Corpus size per kind, and the measured distance to MI-4's entry gates.

    Published rather than kept in a document because §3.9 made the arc falsifiable by
    measurement: if the graded-pair rate cannot plausibly reach these gates, the
    distillation premise is unproven here and the arc stops at the ledger. Someone has to
    be able to SEE the inputs to that decision."""
    from aughor.learning import exporters, store
    return {"stats": store.stats(), "gates": exporters.gate_status()}


@router.get("/learning/datasets/{name}")
def get_dataset(name: str, version: Optional[int] = None):
    """One dataset node plus its provenance — which verdicts fed it. The question MI-4
    owes about any adapter it promotes."""
    from aughor.learning import store
    node = store.get(name, version=version)
    if node is None:
        return {"found": False, "name": name, "version": version}
    return {"found": True, "dataset": node, "lineage": store.lineage_of(node["id"])}


@router.post("/learning/export")
def post_export(task: str = "nl2sql", publish_golden: bool = True):
    """Run every exporter once. Idempotent — an unchanged corpus registers no new version,
    so this is safe to call repeatedly and safe to put on a schedule later.

    `publish_golden` also registers the held-out set as an eval suite: a golden set that
    never reaches the plane enforcing promotion gates is a measuring stick nobody measures
    with, which is this codebase's most-repeated failure shape."""
    from aughor.learning import exporters
    nodes = exporters.export_all(task=task)
    suite_id = exporters.publish_golden_to_evals(nodes["golden"]) if publish_golden else None
    return {"datasets": nodes, "golden_suite_id": suite_id,
            "gates": exporters.gate_status()}
