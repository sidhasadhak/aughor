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

    No ``recommended_model`` any more, and no ``POST /agents/apply-recommended-models``
    to apply one: both existed only to serve per-charter model ids this repo hardcoded,
    and those were removed 2026-08-15. An agent's model is whatever the operator pinned,
    or the role binding it inherits.
    """
    spend = _spend_by_agent()
    backend = _active_backend_id()
    return [
        {
            **c.to_dict(),
            "governance": effective_governance(c.id, workspace_id).to_dict(),
            "spend": spend.get(c.id, {"runs": 0, "total_tokens": 0, "query_count": 0}),
            "backend": backend,
        }
        for c in list_charters()
    ]


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
# Dynamic, user-created personas (aughor/custom_agents/) — distinct from the
# static built-in fleet charters above. Permanent since flag endgame Wave 2
# (2026-08-06, receipt df89c044999a): every behaviour is DATA-GATED — it needs an
# agent row the user created AND a request naming it, so a fresh clone's only
# delta is /agents/custom returning an empty roster instead of 404.


def _validate_agent_fields(name: Optional[str] = None, instructions: Optional[str] = None,
                           connection_id: Optional[str] = None,
                           doc_ids: Optional[list] = None) -> None:
    from aughor.custom_agents.models import INSTRUCTIONS_MAX, NAME_MAX
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
    """Refuse a pack id that does not EXIST. Do not refuse one that is not yet active.

    These were the same check, and the asymmetry was a live trap: `create_from_template`
    binds `pack_ids=[pack_id]` without validating, while this ran on every PATCH against
    `active_packs()` — status == "active" only. The one pack that ships is `status: draft`,
    so hiring from it produced an agent whose very next Save returned 422 about a binding
    the user never chose, on the primary creation path.

    Existence is the right gate here because activation is already enforced where it
    matters: `packs.intake` steers a question only when the pack is active AND a human has
    pinned it to that connection. Refusing the id at write time is a second, stricter gate
    that contradicts the first and blocks a binding that is simply inert until the pack
    ships. A typo is still a 422.
    """
    if not pack_ids:
        return
    try:
        from aughor.packs.intake import known_pack_ids
        known = set(known_pack_ids())
    except Exception:
        known = set()
    missing = [p for p in pack_ids if p not in known]
    if missing:
        raise HTTPException(status_code=422,
                            detail=f"unknown pack id(s): {', '.join(missing)}")


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
    from aughor.custom_agents import list_agents
    return [a.model_dump() for a in list_agents()]


@router.get("/agents/templates")
def list_agent_templates():
    """Domain Expertise Packs offered as agent templates (Wave H4).

    Each carries the instructions a hire would start with and the domain's own questions as
    ``suggested_goldens`` — suggestions, each stating what it still needs. A pack cannot
    supply a golden's reference SQL (it does not know your schema, and its evals are
    behavioural expectations rather than queries), so the template says so rather than
    seeding a suite that would measure nothing. See :mod:`aughor.custom_agents.templates`.
    """
    from aughor.custom_agents.templates import list_templates
    return {"templates": list_templates()}


@router.post("/agents/custom/from-template", status_code=201)
def create_user_agent_from_template(body: UserAgentFromTemplate):
    """Hire an agent from a pack: its stance becomes the instructions, the pack stays bound.

    Returns the agent plus the suggested goldens, so the creator is asked for reference SQL
    while they still have the domain in mind — the agent is born with a stance, and earns
    its pass chip only once real ground truth exists.
    """
    from aughor.custom_agents.templates import create_from_template
    made = create_from_template(body.pack_id, name=body.name,
                                connection_id=body.connection_id,
                                schema_scope=body.schema_scope)
    if made is None:
        raise HTTPException(status_code=404, detail=f"no pack {body.pack_id!r}")
    return made


@router.post("/agents/custom", status_code=201)
def create_user_agent(body: UserAgentCreate):
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids)
    _validate_agent_packs(body.pack_ids)
    from aughor.org.context import current_org_id
    from aughor.custom_agents import create_agent
    agent = create_agent(body.name, instructions=body.instructions,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         owner=current_org_id() or "")
    return agent.model_dump()


@router.get("/agents/custom/{agent_id}")
def get_user_agent(agent_id: str):
    from aughor.custom_agents import get_agent
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return agent.model_dump()


@router.patch("/agents/custom/{agent_id}")
def patch_user_agent(agent_id: str, body: UserAgentPatch):
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids)
    _validate_agent_packs(body.pack_ids)
    from aughor.custom_agents import update_agent
    agent = update_agent(agent_id, name=body.name, instructions=body.instructions,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         enabled=body.enabled)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return agent.model_dump()


@router.get("/agents/custom/{agent_id}/revisions")
def list_user_agent_revisions(agent_id: str, limit: int = 50):
    """The agent's governing-configuration history, newest first (Wave H6).

    ``current_rev`` is what the agent is configured as right now, so a caller can mark the
    entry it matches without recomputing the digest. Only the fields that decide how the
    agent answers are versioned — a rename does not appear here, because it changed nothing
    about what the agent does.
    """
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.revisions import list_revisions
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return {"agent_id": agent_id, "current_rev": agent.config_rev,
            "eval_basis": agent.eval_basis,
            "revisions": list_revisions(agent_id, limit=max(1, min(int(limit), 200)))}


@router.post("/agents/custom/{agent_id}/revisions/{version}/restore")
def restore_user_agent_revision(agent_id: str, version: int):
    """Put an earlier configuration back — as a NEW revision, never a rewind.

    History stays append-only: "I went back to how it was on Tuesday" is itself worth
    keeping, and erasing the revisions in between would destroy the record of what was
    tried. If the restored configuration is one the golden suite already measured, the pass
    chip becomes ``current`` again on its own — the revision is a digest of the
    configuration, not a counter, so returning to a measured state returns the measurement
    with it.
    """
    from aughor.custom_agents import get_agent, update_agent
    from aughor.custom_agents.revisions import revision_config
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    config = revision_config(agent_id, version)
    if config is None:
        raise HTTPException(status_code=404, detail=f"No revision {version} for this agent")
    agent = update_agent(agent_id, **config)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return {"restored_from": version, "agent": agent.model_dump()}


@router.delete("/agents/custom/{agent_id}")
def delete_user_agent(agent_id: str):
    from aughor.custom_agents import delete_agent
    if not delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="No such agent")
    return {"deleted": agent_id}


# ── Golden questions + evaluation ("measured agents") ─────────────────────────

class GoldenCreate(BaseModel):
    question: str
    reference_sql: str


@router.get("/agents/custom/{agent_id}/goldens")
def list_agent_goldens(agent_id: str):
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.store import list_goldens
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return list_goldens(agent_id)


@router.post("/agents/custom/{agent_id}/goldens", status_code=201)
def create_agent_golden(agent_id: str, body: GoldenCreate):
    """Pin a golden question: the agent's own regression suite. reference_sql is
    the ground truth the evaluation compares against (executed, not matched as
    text) — read-only statements only."""
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.store import add_golden
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
    from aughor.custom_agents.store import delete_golden
    # Scoped to the agent in the path. Unscoped, that path parameter was decorative and
    # any agent's URL could delete any golden — the suite an agent is measured by.
    if not delete_golden(golden_id, agent_id=agent_id):
        raise HTTPException(status_code=404, detail="No such golden")
    return {"deleted": golden_id}


@router.get("/agents/custom/{agent_id}/observability")
def user_agent_observability(agent_id: str):
    """The Agent Workspace overview data for one agent: its run history (from the
    history store, stamped with agent_id) enriched with MLflow trace stats when
    MLflow tracing is configured. Degrades to history-only (`trace_stats: null`) when the
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
    from aughor.custom_agents import get_agent
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
    """This agent's slice of the G3 usage rollup.

    Recording is permanent, so an empty slice means this agent spent nothing —
    not that nothing was watching. ``cost_is_complete`` carries G3's own caveat
    forward: a model with no declared price contributes nothing to the total
    rather than counting as free.
    """
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
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.quality import evaluate_agent
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return evaluate_agent(agent)
