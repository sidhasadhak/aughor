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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from aughor.licensing import Capability, gate
from aughor.org.context import current_org_id
from aughor.security.authz import connection_owner_guard

#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
router = APIRouter(tags=["learning"], dependencies=[Depends(connection_owner_guard)])


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
        "few_shot": _few_shot_status(),
    }


def _few_shot_status() -> dict:
    """The few-shot memory's two collections, counted (TJ-1's receipt door: *"prove the
    collections come into being on the next clean answer"*). Read in THIS process — the
    local vector store has one writer — and honest about failure: a count that could not
    be taken reads `None`, never 0."""
    from aughor.tools.prior_analyses import INVESTIGATIONS_COLLECTION, SQL_EXAMPLES_COLLECTION
    out: dict = {"backend": None, "model": None, "sql_examples": None, "investigations": None}
    try:
        from aughor.semantic.embedder import embed_backend, embed_model
        out["backend"] = embed_backend()
        out["model"] = embed_model(out["backend"])
    except Exception as exc:  # noqa: BLE001 — an unconfigured embedder is a state, not a crash
        out["note"] = f"embedder not configured: {type(exc).__name__}: {str(exc)[:160]}"
    try:
        from aughor.semantic.vector_store import collection_count
        out["sql_examples"] = collection_count(SQL_EXAMPLES_COLLECTION)
        out["investigations"] = collection_count(INVESTIGATIONS_COLLECTION)
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"the vector store could not be counted: {type(exc).__name__}"
    return out


@router.get("/learning/run-labels")
def learning_run_labels(days: int = 30, limit: int = 100, rows: bool = False):
    """TJ-3 — the run label's live distribution: the most recent completed runs with a
    recorded trace, chat turns and deep runs alike, each labelled by the one rule
    (`learning.reward.run_label`) from its own trajectory, and counted per run kind. `discriminating` is §3.47's falsifier read live: a label constant on real
    traffic is a finding, not a dataset. ``rows=true`` returns the labelled rows — the audit
    sheet a person fills before bronze is fuel."""
    from datetime import datetime, timedelta, timezone

    from aughor.db import history
    from aughor.learning.reward import distribution, label_of_trace

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
    runs = history.recent_runs(since, limit=max(1, min(int(limit), 500)))
    labelled = []
    for a in runs:
        verdict = label_of_trace(a["trace_id"])
        labelled.append({"trace_id": a["trace_id"], "id": a.get("id"), "kind": a.get("kind"),
                         "question": a.get("question"), "connection_id": a.get("connection_id"),
                         "completed_at": a.get("completed_at"), "sql": a.get("sql") or "", **verdict})
    by_kind: dict[str, dict] = {}
    for r in labelled:
        k = by_kind.setdefault(str(r.get("kind") or "investigation"), {"positive": 0, "negative": 0, "unlabeled": 0})
        k[r["label"]] = k.get(r["label"], 0) + 1
    out = {"days": days, "asked": len(runs), **distribution(labelled), "by_kind": by_kind,
           "note": ("step credit and a NULL confidence are not built: a reject still closes every decision "
                    "of its run, and the headline-against-rows check is not recorded on a chat answer")}
    if rows:
        out["rows"] = labelled
    return out


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


#: Fields a decision row carries that are PAYLOAD under §6 item 4 ("visible metadata, gated
#: payloads"). `context` embeds the user's question verbatim — the recorder writes
#: `step N | last <tool> | <question>` — and §6 item 4 defines a payload as "a prompt or a
#: response body". Everything else on the row (site, menu, choice, label, confidence, outcome,
#: provenance, the prompt Fingerprint) is metadata and stays visible without ceremony.
_PAYLOAD_FIELDS = ("context",)


def _metadata_only(row: dict) -> dict:
    """A decision row with its payload withheld, and a sentence saying so.

    Withheld EXPLICITLY rather than deleted: a row whose `context` simply vanished would read
    as a row that never had one, and a reader would conclude the recorder is broken. The key
    stays, empty, and `payload_withheld` says why and where the posture is decided.
    """
    out = dict(row)
    for field in _PAYLOAD_FIELDS:
        if field in out:
            out[field] = ""
    out["payload_withheld"] = ("context carries the user's question verbatim, which is a payload "
                               "under ROADMAP §6 item 4; it is not served on this ungated read")
    return out


@router.get("/learning/decisions")
def get_decisions(site: Optional[str] = None, limit: int = 50):
    """The decision-record accumulation, made visible: per-site volume (total, trainable,
    outcome-closed) and the newest rows. This is the observability half of "is this
    decision learnable" — the volume answer that must exist before any scorer does.

    🔴 Rows are served METADATA-ONLY. Until 2026-09-21 this returned `list_decisions` verbatim,
    so an UNAUTHENTICATED request received every user's question text: measured live, a
    `GET /learning/decisions` with no auth header answered 200 with 58 rows whose `context`
    included questions such as "What is today's revenue and profit?". §6 item 4 decided that a
    prompt is a payload readable only through an audited break-glass, and the product's own
    `obs/prompt_window.py` calls the user's question "the most sensitive thing this product can
    write down" — while this door served it to anyone. The volume answer this route exists for
    needs no payload at all, so none is served. In-process, operator-run readers
    (`evals/judgment_battery_eval.py`) call `decisions.list_decisions` directly and are
    unaffected; it is the open HTTP door that was the leak.
    """
    from aughor.learning.decisions import list_decisions, site_stats
    return {"stats": site_stats(),
            "recent": [_metadata_only(r) for r in list_decisions(site=site, limit=limit)]}


@router.post("/learning/export/decisions", dependencies=[gate(Capability.SEMANTIC_EDIT)])
def post_export_decisions(site: Optional[str] = None, task: str = "decision"):
    """Export decision records as selection corpora (`choice` + held-out `choice_golden`
    per site). Idempotent like every exporter — an unchanged corpus registers no new
    version — so it is safe to call repeatedly and safe to schedule later."""
    from aughor.learning import exporters
    return {"datasets": exporters.export_decisions(site=site, task=task)}


@router.get("/learning/datasets/{name}")
def get_dataset(name: str, version: Optional[int] = None):
    """One dataset node plus its provenance — which verdicts fed it. The question MI-4
    owes about any adapter it promotes."""
    from aughor.learning import store
    node = store.get(name, version=version)
    if node is None:
        return {"found": False, "name": name, "version": version}
    # Said, never implied: a registry row whose bytes are gone is not an empty dataset.
    state = store.bytes_state(node)
    out = {"found": True, "dataset": node, "lineage": store.lineage_of(node["id"]),
           "bytes": state}
    if state != "present":
        out["note"] = (f"the rows cannot be read back: the bytes are {state} "
                       + ("(deleted on purpose; the lineage is kept)" if state == "purged"
                          else "(the registry names a file that is not on disk — re-run "
                               "the export; an unchanged corpus writes the same path)"))
    return out


@router.post("/learning/export", dependencies=[gate(Capability.SEMANTIC_EDIT)])
def post_export(task: str = "nl2sql", publish_golden: bool = True):
    """Run every exporter once. Idempotent — an unchanged corpus registers no new version,
    so this is safe to call repeatedly and safe to put on a schedule later. Gated like the
    trusted-query doors beside it (PENDING item 23: it had no gate, and it writes users'
    questions into files).

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
    with the report attached; a draft never reaches a prompt.

    The flow itself lives in `semantic/trusted_verify.seed_trusted` — KI-1's intake
    lane seeds through the SAME function, so there is one door, not two."""
    from aughor.semantic.trusted_verify import seed_trusted

    _check_trusted_conn_org(request, body.connection_id)
    if not (body.sql or "").strip() or not (body.question or "").strip():
        raise HTTPException(status_code=400, detail="question and sql are required")
    if not (body.actor or "").strip():
        raise HTTPException(status_code=400, detail="actor is required")
    try:
        return seed_trusted(body.connection_id, body.question, body.sql,
                            tables=body.tables, note=body.note, tags=body.tags,
                            actor=body.actor, source=body.source)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")


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


@router.post("/learning/trusted/{tq_id}/promote",
             dependencies=[gate(Capability.SEMANTIC_EDIT)])
def promote_trusted(tq_id: str, request: Request, actor: str = ""):
    """DS-19 — a query authored on an automation's node joins the connection's catalogue.

    §6 item 26 (c), the user's call: an authored query is PRIVATE to its chain, with the
    option to promote it later. This is that option, and it is deliberately one field
    going empty rather than a row moving — there is one trusted-query store, so a
    promotion changes who may SEE a query and touches neither its SQL, its verification
    report, its approval stamp nor its version. Nothing to re-verify, because nothing
    about the content changed.

    Audited like every other transition on this store, and for the same reason: the
    metrics catalog paid for an unaudited write once already.
    """
    from aughor.semantic.trusted_queries import get_trusted, save_trusted

    tq = get_trusted(tq_id)
    if tq is None:
        raise HTTPException(status_code=404, detail="No such trusted query")
    _check_trusted_conn_org(request, tq.connection_id)
    if not tq.owner_automation:
        # Not an error worth a 4xx — the caller wanted it in the catalogue and it is.
        return {"trusted_query": tq.model_dump(), "promoted": False,
                "reason": "already in this connection's catalogue"}

    was = tq.owner_automation
    tq.owner_automation = ""
    save_trusted(tq)
    _emit_trusted_governance({
        "trusted_query": tq_id, "connection_id": tq.connection_id,
        "action": "promote", "actor": actor,
        "from": f"automation:{was}", "to": "catalogue",
        "status": tq.status, "version": tq.version, "at": _now(),
        "question": (tq.question or "")[:120],
    })
    return {"trusted_query": tq.model_dump(), "promoted": True}


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
