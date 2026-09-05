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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from aughor.licensing import Capability, gate
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
    now inspectable. Scoped to the current org, optionally to one connection.

    KI-0: this is the INSPECTION surface, so it lists every status — drafts and
    proposals included, each row carrying its status and provenance. The prompt path
    (`retrieve_trusted`) sees only ``approved``."""
    from aughor.semantic.trusted_queries import list_trusted

    cid = connection_id or ""
    return {
        "queries": [q.model_dump() for q in list_trusted(cid, include_unapproved=True)],
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


# ── KI-0 (§3.10): the trusted-SQL door ───────────────────────────────────────────────
#
# The single most prompt-authoritative store on the platform, writable until now only by
# two internal jobs or by editing data/trusted_queries.json on the host's disk. These
# endpoints are the HTTP door: seed → verify (real execution + the shared guard battery)
# → propose → a SECOND recorded act approves. Only `approved` reaches a prompt; a seed
# that fails verification lands as a draft with the error attached, never in the block.
# Lifecycle rides the metric governance machine; every step is journaled to the ledger
# under `trusted_query.governance` (categorized in govern/audit_categories.py — a kind
# alone renders nothing, the sink entry is the other mandatory half).


class TrustedQueryIn(BaseModel):
    connection_id: str
    question: str
    sql: str
    tables: list[str] = Field(default_factory=list)
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    actor: str            # who is seeding — provenance is not optional (§3.10)
    source: str = "api"   # api | <importer name>; internal writers stamp their own


class TrustedQueryEdit(BaseModel):
    question: Optional[str] = None
    sql: Optional[str] = None
    tables: Optional[list[str]] = None
    note: Optional[str] = None
    tags: Optional[list[str]] = None
    actor: str


class TrustedTransitionIn(BaseModel):
    action: str   # propose | approve | reject | deprecate
    actor: str


def _check_trusted_conn_org(request: Request, conn_id: str) -> None:
    """DATA-06 for body-carried connection ids (the query router's pattern): 403 when
    the connection belongs to another org; no-op in localhost mode."""
    from aughor.security.authz import check_owner, get_principal
    if conn_id:
        check_owner("connection", conn_id, get_principal(request))


def _emit_trusted_governance(payload: dict) -> None:
    from aughor.kernel.ledger import Ledger
    Ledger.default().emit("trusted_query.governance", payload)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@router.post("/learning/trusted", status_code=201,
             dependencies=[gate(Capability.SEMANTIC_EDIT)])
def create_trusted(body: TrustedQueryIn, request: Request):
    """Seed one golden query. Content-addressed on (connection, question) — re-seeding
    the same question REPLACES the entry rather than accumulating two contradictory
    trusted answers, and re-seeding IDENTICAL content that is already approved is a
    no-op (idempotence is what makes this door safe to point a sync at).

    The seed is verified NOW: executed (bounded) against its connection and walked
    through the same guard battery `/query/validate` runs. Passing lands it in
    `proposed` — approval is a separate recorded act. Failing lands it in `draft`
    with the report attached; a draft never reaches a prompt."""
    from aughor.evals.promote_trusted import trusted_id
    from aughor.semantic import trusted_verify
    from aughor.semantic.trusted_queries import TrustedQuery, get_trusted, save_trusted

    _check_trusted_conn_org(request, body.connection_id)
    if not (body.sql or "").strip() or not (body.question or "").strip():
        raise HTTPException(status_code=400, detail="question and sql are required")
    if not (body.actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")

    tq_id = trusted_id(body.connection_id, body.question)
    existing = get_trusted(tq_id)
    if (existing is not None and existing.status == "approved"
            and existing.sql.strip() == body.sql.strip()
            and existing.tables == body.tables and existing.note == body.note
            and existing.tags == body.tags):
        return {"trusted_query": existing.model_dump(),
                "verification": existing.verification, "unchanged": True}

    try:
        report = trusted_verify.verify(body.connection_id, body.sql)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    now = _now()
    passed = bool(report.get("passed"))
    tq = TrustedQuery(
        id=tq_id, connection_id=body.connection_id,
        question=body.question.strip(), sql=body.sql.strip(),
        tables=body.tables, note=body.note, tags=body.tags,
        status="proposed" if passed else "draft",
        source=(body.source or "api").strip() or "api",
        proposed_by=body.actor if passed else "",
        proposed_at=now if passed else "",
        last_executed_at=now if report.get("battery") is not None else "",
        verification=report,
    )
    save_trusted(tq)
    _emit_trusted_governance({
        "trusted_query": tq_id, "connection_id": body.connection_id,
        "action": "create", "actor": body.actor,
        "from": existing.status if existing else "",
        "to": tq.status, "version": tq.version, "at": now,
    })
    return {"trusted_query": tq.model_dump(), "verification": report,
            "unchanged": False}


@router.put("/learning/trusted/{tq_id}",
            dependencies=[gate(Capability.SEMANTIC_EDIT)])
def edit_trusted(tq_id: str, body: TrustedQueryEdit, request: Request):
    """Edit a seeded query. An edit changes the content, so it RESETS the lifecycle:
    the row is re-verified and lands back in `proposed` (or `draft` on failure), and
    any prior approval stamp is cleared — an approval covers the content it approved,
    nothing later."""
    from aughor.semantic import trusted_verify
    from aughor.semantic.trusted_queries import get_trusted, save_trusted

    tq = get_trusted(tq_id)
    if tq is None:
        raise HTTPException(status_code=404, detail="No such trusted query")
    _check_trusted_conn_org(request, tq.connection_id)
    if not (body.actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")

    was = tq.status
    if body.question is not None:
        tq.question = body.question.strip()
    if body.sql is not None:
        tq.sql = body.sql.strip()
    if body.tables is not None:
        tq.tables = body.tables
    if body.note is not None:
        tq.note = body.note
    if body.tags is not None:
        tq.tags = body.tags
    if not tq.question or not tq.sql:
        raise HTTPException(status_code=400, detail="question and sql are required")

    try:
        report = trusted_verify.verify(tq.connection_id, tq.sql)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    now = _now()
    passed = bool(report.get("passed"))
    tq.status = "proposed" if passed else "draft"
    tq.proposed_by, tq.proposed_at = (body.actor, now) if passed else ("", "")
    tq.verified_by = tq.verified_at = ""
    if report.get("battery") is not None:
        tq.last_executed_at = now
    tq.verification = report
    save_trusted(tq)
    _emit_trusted_governance({
        "trusted_query": tq_id, "connection_id": tq.connection_id,
        "action": "edit", "actor": body.actor,
        "from": was, "to": tq.status, "version": tq.version, "at": now,
    })
    return {"trusted_query": tq.model_dump(), "verification": report}


@router.post("/learning/trusted/{tq_id}/transition",
             dependencies=[gate(Capability.SEMANTIC_EDIT)])
def transition_trusted(tq_id: str, body: TrustedTransitionIn, request: Request):
    """Drive a trusted query through its lifecycle (propose → approve → deprecate …),
    on the metric governance state machine. `propose` RE-verifies first — the data may
    have moved since the seed — and refuses (409, report attached) when verification
    fails. `approve` is the human act that makes the entry prompt-authoritative: it
    stamps `verified_by`/`verified_at` and bumps the version."""
    from aughor.semantic import trusted_verify
    from aughor.semantic.governance import apply_transition
    from aughor.semantic.trusted_queries import TrustedQuery, get_trusted, save_trusted

    tq = get_trusted(tq_id)
    if tq is None:
        raise HTTPException(status_code=404, detail="No such trusted query")
    _check_trusted_conn_org(request, tq.connection_id)

    now = _now()
    action = str(body.action or "").strip().lower()
    if action == "propose":
        try:
            report = trusted_verify.verify(tq.connection_id, tq.sql)
        except KeyError:
            raise HTTPException(status_code=404, detail="Connection not found")
        tq.verification = report
        if report.get("battery") is not None:
            tq.last_executed_at = now
        if not report.get("passed"):
            save_trusted(tq)  # the failed report is worth keeping either way
            raise HTTPException(status_code=409, detail={
                "message": "verification failed — the query stays out of the prompt",
                "verification": report})

    try:
        updated, audit = apply_transition(
            {**tq.model_dump(), "name": tq.id}, action, body.actor, now)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    updated.pop("name", None)
    if action == "approve":
        # The governance machine stamps metrics vocabulary; this store's fields are
        # the VERIFIED_AT/VERIFIED_BY the roadmap named. One mapping site, tested.
        updated["verified_by"] = updated.pop("approved_by", body.actor)
        updated["verified_at"] = updated.pop("approved_at", now)
    row = TrustedQuery(**updated)
    save_trusted(row)
    _emit_trusted_governance({
        "trusted_query": tq_id, "connection_id": row.connection_id,
        "action": action, "actor": body.actor,
        "from": audit["from"], "to": audit["to"],
        "version": row.version, "at": now,
    })
    return {"trusted_query": row.model_dump(), "audit": audit}


@router.delete("/learning/trusted/{tq_id}",
               dependencies=[gate(Capability.SEMANTIC_EDIT)])
def remove_trusted(tq_id: str, request: Request, actor: str = ""):
    """Remove a trusted query — audited, because the metrics catalog already paid for
    an unaudited delete: two calls emptied it on a live install and nothing anywhere
    recorded that it happened."""
    from aughor.semantic.trusted_queries import delete_trusted, get_trusted

    tq = get_trusted(tq_id)
    if tq is None:
        raise HTTPException(status_code=404, detail="No such trusted query")
    _check_trusted_conn_org(request, tq.connection_id)
    delete_trusted(tq_id)
    _emit_trusted_governance({
        "trusted_query": tq_id, "connection_id": tq.connection_id,
        "action": "delete", "actor": actor,
        "from": tq.status, "to": "", "version": tq.version, "at": _now(),
        "question": (tq.question or "")[:120],
    })
    return {"deleted": tq_id}
