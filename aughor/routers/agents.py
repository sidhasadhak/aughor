"""The /agents surface — manage the fleet (Phase 0).

The roster of agent charters + each one's effective governance (enabled, budget)
+ recent spend (aggregated from the metered job rows), and a PATCH to enable/disable
or re-budget an agent. v1 operates the app scope (the Org's fleet config); pass
`workspace_id` to read/write a workspace override (resolver is ready for it).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.kernel.agents import (
    charter_for_kind,
    effective_governance,
    get_charter,
    list_charters,
    set_governance,
)
from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)
router = APIRouter()


def _spend_by_agent(limit: int = 500) -> dict[str, dict]:
    """Aggregate recent metered runs per agent (by the charter owning each job kind)."""
    out: dict[str, dict] = {}
    for job in Ledger.default().jobs_where(limit=limit):
        c = charter_for_kind(job.get("kind"))
        agg = out.setdefault(c.id, {"runs": 0, "total_tokens": 0, "query_count": 0})
        agg["runs"] += 1
        m = job.get("metrics")
        if isinstance(m, dict):
            agg["total_tokens"] += int(m.get("total_tokens") or 0)
            agg["query_count"] += int(m.get("query_count") or 0)
    return out


def _active_backend_id() -> str:
    """The backend the fleet would run under right now."""
    try:
        from aughor.llm.provider import resolve_binding
        return resolve_binding("coder")[0]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent roster: backend unresolved; recommendations omitted",
                 counter="agents.backend")
        return ""


@router.get("/agents")
def list_agents(workspace_id: Optional[str] = None):
    """The fleet roster: each agent's charter + effective governance + recent spend.

    ``recommended_model`` is the charter's suggestion RESOLVED for the backend in
    use — the ids are provider-specific, so a recommendation shown while a
    different provider is bound would be unusable advice.
    """
    spend = _spend_by_agent()
    backend = _active_backend_id()
    return [
        {
            **c.to_dict(),
            "governance": effective_governance(c.id, workspace_id).to_dict(),
            "spend": spend.get(c.id, {"runs": 0, "total_tokens": 0, "query_count": 0}),
            "recommended_model": (c.recommended_models or {}).get(backend, ""),
            "backend": backend,
        }
        for c in list_charters()
    ]


class ApplyRecommendedIn(BaseModel):
    workspace_id: Optional[str] = None
    agent_ids: Optional[list[str]] = None     # None → the whole fleet
    overwrite: bool = False                   # keep operator-set pins unless asked


@router.post("/agents/apply-recommended-models")
def apply_recommended_models(body: ApplyRecommendedIn):
    """Pin each agent to its recommended model for the ACTIVE backend.

    Skips agents that already carry an explicit pin unless ``overwrite`` — a
    suggestion should never silently replace a choice someone made. Agents with
    no recommendation for this backend are skipped and reported, so "nothing
    happened" is never ambiguous.
    """
    backend = _active_backend_id()
    if not backend:
        raise HTTPException(status_code=400, detail="no inference backend resolved")

    wanted = set(body.agent_ids or [])
    applied, skipped = [], []
    for c in list_charters():
        if wanted and c.id not in wanted:
            continue
        rec = (c.recommended_models or {}).get(backend, "")
        if not rec:
            skipped.append({"agent_id": c.id, "reason": f"no recommendation for {backend}"})
            continue
        current = effective_governance(c.id, body.workspace_id).model
        if current and not body.overwrite:
            skipped.append({"agent_id": c.id, "reason": f"already pinned to {current}"})
            continue
        set_governance(c.id, scope=body.workspace_id, model=rec)
        applied.append({"agent_id": c.id, "model": rec})
    return {"backend": backend, "applied": applied, "skipped": skipped}


class AgentGovernancePatch(BaseModel):
    enabled: Optional[bool] = None
    token_budget: Optional[int] = None
    time_budget_s: Optional[int] = None
    model: Optional[str] = None          # per-agent LLM model; "" clears back to the role default
    workspace_id: Optional[str] = None   # None → app scope (the Org default)
    # Free-by-default: pinning a non-`:free` OpenRouter model needs explicit consent.
    allow_paid: Optional[bool] = None


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: str, body: AgentGovernancePatch):
    """Enable/disable, re-budget, or pin the model for an agent. Only the provided fields change."""
    if get_charter(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    if body.model:
        # The same free-by-default guard the central config enforces — a per-agent
        # pin is just as much a binding as a role binding.
        from aughor.llm import provider as _provider
        try:
            _provider.ensure_free_or_allowed(
                _provider.active_backend(), body.model,
                allow_paid=bool(body.allow_paid))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    gov = set_governance(
        agent_id,
        scope=body.workspace_id,
        enabled=body.enabled,
        token_budget=body.token_budget,
        time_budget_s=body.time_budget_s,
        model=body.model,
    )
    return {"agent_id": agent_id, "governance": gov.to_dict()}


# ── User-defined agents (flag `agents.user_defined`) ──────────────────────────
# Dynamic, user-created personas (aughor/user_agents/) — distinct from the
# static built-in fleet charters above. Routes 404 when the flag is off.

def _require_user_agents() -> None:
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("agents.user_defined"):
        raise HTTPException(status_code=404,
                            detail="user-defined agents are disabled (flag agents.user_defined)")


def _validate_agent_fields(name: Optional[str] = None, instructions: Optional[str] = None,
                           connection_id: Optional[str] = None,
                           doc_ids: Optional[list] = None) -> None:
    from aughor.user_agents.models import INSTRUCTIONS_MAX, NAME_MAX
    if name is not None and not (0 < len(name.strip()) <= NAME_MAX):
        raise HTTPException(status_code=422, detail=f"name must be 1..{NAME_MAX} chars")
    if instructions is not None and len(instructions) > INSTRUCTIONS_MAX:
        raise HTTPException(status_code=422,
                            detail=f"instructions exceed {INSTRUCTIONS_MAX} chars")
    if connection_id:
        from aughor.db.registry import BUILTIN_ID, list_connections
        known = {c.get("id") for c in list_connections()} | {BUILTIN_ID}
        if connection_id not in known:
            raise HTTPException(status_code=422,
                                detail=f"unknown connection '{connection_id}'")
    if doc_ids:
        from aughor.knowledge.indexer import get_document
        missing = [d for d in doc_ids if get_document(d) is None]
        if missing:
            raise HTTPException(status_code=422,
                                detail=f"unknown document id(s): {', '.join(missing)}")


def _validate_agent_packs(pack_ids: Optional[list]) -> None:
    if not pack_ids:
        return
    try:
        from aughor.packs.intake import active_packs
        known = {p.id for p in active_packs()}
    except Exception:
        known = set()
    missing = [p for p in pack_ids if p not in known]
    if missing:
        raise HTTPException(status_code=422,
                            detail=f"unknown/inactive pack id(s): {', '.join(missing)}")


class UserAgentCreate(BaseModel):
    name: str
    instructions: str = ""
    connection_id: str = ""
    schema_scope: str = ""
    doc_ids: list[str] = []
    pack_ids: list[str] = []


class UserAgentPatch(BaseModel):
    name: Optional[str] = None
    instructions: Optional[str] = None
    connection_id: Optional[str] = None
    schema_scope: Optional[str] = None
    doc_ids: Optional[list[str]] = None
    pack_ids: Optional[list[str]] = None
    enabled: Optional[bool] = None


class UserAgentFromTemplate(BaseModel):
    pack_id: str
    name: str = ""
    connection_id: str = ""
    schema_scope: str = ""


@router.get("/agents/custom")
def list_user_agents():
    """All user-defined agents (the persona roster, newest first)."""
    _require_user_agents()
    from aughor.user_agents import list_agents
    return [a.model_dump() for a in list_agents()]


@router.get("/agents/templates")
def list_agent_templates():
    """Domain Expertise Packs offered as agent templates (Wave H4).

    Each carries the instructions a hire would start with and the domain's own questions as
    ``suggested_goldens`` — suggestions, each stating what it still needs. A pack cannot
    supply a golden's reference SQL (it does not know your schema, and its evals are
    behavioural expectations rather than queries), so the template says so rather than
    seeding a suite that would measure nothing. See :mod:`aughor.user_agents.templates`.
    """
    _require_user_agents()
    from aughor.user_agents.templates import list_templates
    return {"templates": list_templates()}


@router.post("/agents/custom/from-template", status_code=201)
def create_user_agent_from_template(body: UserAgentFromTemplate):
    """Hire an agent from a pack: its stance becomes the instructions, the pack stays bound.

    Returns the agent plus the suggested goldens, so the creator is asked for reference SQL
    while they still have the domain in mind — the agent is born with a stance, and earns
    its pass chip only once real ground truth exists.
    """
    _require_user_agents()
    from aughor.user_agents.templates import create_from_template
    made = create_from_template(body.pack_id, name=body.name,
                                connection_id=body.connection_id,
                                schema_scope=body.schema_scope)
    if made is None:
        raise HTTPException(status_code=404, detail=f"no pack {body.pack_id!r}")
    return made


@router.post("/agents/custom", status_code=201)
def create_user_agent(body: UserAgentCreate):
    _require_user_agents()
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids)
    _validate_agent_packs(body.pack_ids)
    from aughor.org.context import current_org_id
    from aughor.user_agents import create_agent
    agent = create_agent(body.name, instructions=body.instructions,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         owner=current_org_id() or "")
    return agent.model_dump()


@router.get("/agents/custom/{agent_id}")
def get_user_agent(agent_id: str):
    _require_user_agents()
    from aughor.user_agents import get_agent
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return agent.model_dump()


@router.patch("/agents/custom/{agent_id}")
def patch_user_agent(agent_id: str, body: UserAgentPatch):
    _require_user_agents()
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids)
    _validate_agent_packs(body.pack_ids)
    from aughor.user_agents import update_agent
    agent = update_agent(agent_id, name=body.name, instructions=body.instructions,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         enabled=body.enabled)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return agent.model_dump()


@router.delete("/agents/custom/{agent_id}")
def delete_user_agent(agent_id: str):
    _require_user_agents()
    from aughor.user_agents import delete_agent
    if not delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="No such agent")
    return {"deleted": agent_id}


# ── Golden questions + evaluation ("measured agents") ─────────────────────────

class GoldenCreate(BaseModel):
    question: str
    reference_sql: str


@router.get("/agents/custom/{agent_id}/goldens")
def list_agent_goldens(agent_id: str):
    _require_user_agents()
    from aughor.user_agents import get_agent
    from aughor.user_agents.store import list_goldens
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return list_goldens(agent_id)


@router.post("/agents/custom/{agent_id}/goldens", status_code=201)
def create_agent_golden(agent_id: str, body: GoldenCreate):
    """Pin a golden question: the agent's own regression suite. reference_sql is
    the ground truth the evaluation compares against (executed, not matched as
    text) — read-only statements only."""
    _require_user_agents()
    from aughor.user_agents import get_agent
    from aughor.user_agents.store import add_golden
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    if not body.question.strip() or not body.reference_sql.strip():
        raise HTTPException(status_code=422, detail="question and reference_sql are required")
    # WP-1c — fail CLOSED on unparseable SQL: `is_mutating` returns False on a parse
    # failure, so an unparseable statement previously slipped past the read-only check.
    # Goldens are user-authored ground truth; a parse failure is a user error to fix.
    import sqlglot
    try:
        _parsed = sqlglot.parse_one(body.reference_sql)
    except Exception:
        _parsed = None
    if _parsed is None:
        raise HTTPException(
            status_code=422,
            detail="reference_sql could not be parsed — provide valid, read-only SQL")
    from aughor.sql.readonly import is_mutating
    if is_mutating(body.reference_sql):
        raise HTTPException(status_code=422, detail="reference_sql must be read-only")
    return add_golden(agent_id, body.question, body.reference_sql)


@router.delete("/agents/custom/{agent_id}/goldens/{golden_id}")
def delete_agent_golden(agent_id: str, golden_id: str):
    _require_user_agents()
    from aughor.user_agents.store import delete_golden
    if not delete_golden(golden_id):
        raise HTTPException(status_code=404, detail="No such golden")
    return {"deleted": golden_id}


@router.get("/agents/custom/{agent_id}/observability")
def user_agent_observability(agent_id: str):
    """The Agent Workspace overview data for one agent: its run history (from the
    history store, stamped with agent_id) enriched with MLflow trace stats when
    `obs.mlflow` is on. Degrades to history-only (`trace_stats: null`) when the
    tracking server is off — the workspace is useful without MLflow (B3: the
    dependency is one-directional).

    Wave H3 adds ``spend`` from the G3 usage store (H2's ``agent_id`` axis over the
    session log), so calls, tokens and cost are answerable **without** MLflow — a
    second, optional dependency should not be what stands between an operator and
    "what did this agent cost". When the session log is off nothing has been
    recorded to report, and ``spend`` says so with the flag to turn on rather than
    returning zeros: a confident 0 tokens and an unmeasured 0 tokens look identical
    on a tile, and only one of them is true.
    """
    _require_user_agents()
    from aughor.user_agents import get_agent
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    from aughor import telemetry
    from aughor.db.history import list_investigations_for_agent
    runs = list_investigations_for_agent(agent_id)
    return {
        "agent_id": agent_id,
        "run_count": len(runs),
        "runs": runs,
        "trace_stats": telemetry.agent_trace_stats(agent_id),
        "spend": _agent_spend(agent_id),
    }


def _agent_spend(agent_id: str) -> dict:
    """This agent's slice of the G3 usage rollup, or an honest unmeasured verdict.

    ``measured`` is the field a caller must read first: False means the session log
    recorded nothing to roll up (flag ``obs.session_log`` is off), not that the agent
    spent nothing. ``cost_is_complete`` carries G3's own caveat forward — a model with
    no declared price contributes nothing to the total rather than counting as free.
    """
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("obs.session_log"):
        return {"measured": False, "reason": "the session log is off; no model calls are "
                                             "recorded to attribute",
                "enable_flag": "obs.session_log"}
    from aughor.obs.usage import usage_report
    report = usage_report(axes=("agent_id",)).to_dict()
    for row in report.get("rows") or []:
        if row.get("agent_id") == agent_id:
            return {"measured": True, "calls": row.get("calls", 0),
                    "total_tokens": row.get("total_tokens", 0),
                    "cost_usd": row.get("cost_usd"),
                    "cost_is_complete": row.get("cost_is_complete", False),
                    "failure_rate": row.get("failure_rate")}
    return {"measured": True, "calls": 0, "total_tokens": 0, "cost_usd": 0.0,
            "cost_is_complete": True, "failure_rate": 0.0}


@router.post("/agents/custom/{agent_id}/evaluate")
def evaluate_user_agent(agent_id: str):
    """Run the agent's golden suite NOW (one coder-model call per golden, capped)
    and stamp the result on the agent — 'your agent still passes 11/12'. Run it
    after editing instructions or documents to catch regressions."""
    _require_user_agents()
    from aughor.user_agents import get_agent
    from aughor.user_agents.quality import evaluate_agent
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return evaluate_agent(agent)
