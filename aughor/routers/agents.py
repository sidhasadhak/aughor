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
from pydantic import BaseModel, Field

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


def _spend_by_agent(limit: int = 500, *, since: Optional[str] = None,
                    until: Optional[str] = None) -> dict[str, dict]:
    """Aggregate metered runs per built-in agent (by the charter owning each job kind),
    inside ``[since, until)`` — AO-3: the roster's tiles read the window the page shows.
    Before 2026-10-03 this read the newest 500 jobs of any age, so a built-in agent's
    page said one number and its roster row (windowed, from the fleet fold) another."""
    out: dict[str, dict] = {}
    for job in Ledger.default().jobs_where(limit=limit, since=since, until=until):
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


def _window_dict(win) -> dict:
    """The window a response's numbers were read over, on the response itself — so a tile
    can caption what it counts instead of implying "all time" or "recent"."""
    return {"range": win.range_key or "", "since": win.since, "until": win.until}


@router.get("/agents")
def list_agents(workspace_id: Optional[str] = None, range: str = "",
                since: str = "", until: str = ""):
    """The fleet roster: each agent's charter + effective governance + spend in the window.

    ``range`` / ``since`` / ``until`` are the shared Agent Ops window (``obs/timeseries``
    names; the default is its default, 24h) — every number here is read over it, and the
    window rides on each row as ``window`` so the page can say so.

    No ``recommended_model`` any more, and no ``POST /agents/apply-recommended-models``
    to apply one: both existed only to serve per-charter model ids this repo hardcoded,
    and those were removed 2026-08-15. An agent's model is whatever the operator pinned,
    or the role binding it inherits.
    """
    from aughor.obs.timeseries import resolve_window
    win = resolve_window(range, since=since, until=until)
    spend = _spend_by_agent(since=win.since, until=win.until)
    backend = _active_backend_id()
    window = _window_dict(win)
    return [
        {
            **c.to_dict(),
            "governance": effective_governance(c.id, workspace_id).to_dict(),
            "spend": spend.get(c.id, {"runs": 0, "total_tokens": 0, "query_count": 0}),
            "window": window,
            "backend": backend,
        }
        for c in list_charters()
    ]


class AgentGovernancePatch(BaseModel):
    enabled: Optional[bool] = None
    token_budget: Optional[int] = None
    time_budget_s: Optional[int] = None
    model: Optional[str] = None          # per-agent LLM model; "" clears back to the role default
    #: Declared-knob values by knob id (the charter's `knobs` list names them); a null
    #: value clears that knob back to inherit. Undeclared or out-of-range → 400.
    limits: Optional[dict[str, Optional[int]]] = None
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
    try:
        gov = set_governance(
            agent_id,
            scope=body.workspace_id,
            enabled=body.enabled,
            token_budget=body.token_budget,
            time_budget_s=body.time_budget_s,
            model=body.model,
            limits=body.limits,
        )
    except ValueError as exc:
        # The registry's own sentence — an undeclared knob names the declared ones, an
        # out-of-range value names the range.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"agent_id": agent_id, "governance": gov.to_dict()}


# ── User-defined agents (flag `agents.user_defined`) ──────────────────────────
# Dynamic, user-created personas (aughor/custom_agents/) — distinct from the
# static built-in fleet charters above. Permanent since flag endgame Wave 2
# (2026-08-06, receipt df89c044999a): every behaviour is DATA-GATED — it needs an
# agent row the user created AND a request naming it, so a fresh clone's only
# delta is /agents/custom returning an empty roster instead of 404.


def _validate_agent_fields(name: Optional[str] = None, instructions: Optional[str] = None,
                           connection_id: Optional[str] = None,
                           doc_ids: Optional[list] = None,
                           schema_scope: Optional[str] = None) -> None:
    # SP-3 extracted the body to the store (`validate_agent_draft`) so the create route
    # and the draft-staging path check with ONE set of rules; this wrapper only turns
    # problem sentences into the 422 the form renders.
    from aughor.custom_agents.store import validate_agent_draft
    problems = validate_agent_draft(name=name, instructions=instructions,
                                    connection_id=connection_id, doc_ids=doc_ids,
                                    schema_scope=schema_scope)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))


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


def _validate_agent_grants(tool_grants: Optional[list], connection_id: str,
                           schema_scope: str = "") -> None:
    """Refuse a grant that could never propose anything — at WRITE time, in the words
    the runtime would use, instead of at ask time inside a background turn.

    The rules live in `custom_agents.store.validate_agent_grants` (one body — SP-3's
    grant proposals re-check the same sentences at stage and at accept); this wrapper
    only turns the first problem into the 422 this route has always raised.
    """
    from aughor.custom_agents.store import validate_agent_grants
    problems = validate_agent_grants(tool_grants, connection_id, schema_scope)
    if problems:
        raise HTTPException(status_code=422, detail=problems[0])


#: AO-1d — `purpose` is the one-line "what this agent is for" the delegation roster reads
#: (`delegate_tool.roster_block`, which deliberately never reads instructions). The store
#: had the column since migration 5; no door let a person write it, so every roster line
#: was the bounded fallback. Capped where the roster's own budget is measured.
PURPOSE_MAX = 240


class UserAgentCreate(BaseModel):
    name: str
    instructions: str = ""
    purpose: str = Field("", max_length=PURPOSE_MAX)
    connection_id: str = ""
    schema_scope: str = ""
    doc_ids: list[str] = []
    pack_ids: list[str] = []
    #: The declared actions this agent may PROPOSE, by id — never execute (VA-9c's rule,
    #: now stored: the column landed 2026-09-02 after a season as a phantom).
    tool_grants: list[str] = []


class UserAgentPatch(BaseModel):
    name: Optional[str] = None
    instructions: Optional[str] = None
    purpose: Optional[str] = Field(None, max_length=PURPOSE_MAX)
    connection_id: Optional[str] = None
    schema_scope: Optional[str] = None
    doc_ids: Optional[list[str]] = None
    pack_ids: Optional[list[str]] = None
    tool_grants: Optional[list[str]] = None
    enabled: Optional[bool] = None


class UserAgentFromTemplate(BaseModel):
    """AO-1d — the pack path takes the scratch path's body. Before, four fields: the Create
    flow let a person edit the prefilled instructions and tick documents, then sent only
    `pack_id`, `name`, `connection_id`, `schema_scope`, and the agent was born with the
    pack's text and no documents — silently."""
    pack_id: str
    name: str = ""
    instructions: str = ""
    purpose: str = Field("", max_length=PURPOSE_MAX)
    connection_id: str = ""
    schema_scope: str = ""
    doc_ids: list[str] = []
    pack_ids: list[str] = []
    tool_grants: list[str] = []


@router.get("/agents/custom")
def list_user_agents():
    """The active workspace's user-defined agents (the persona roster, newest first)."""
    from aughor.custom_agents import list_agents
    from aughor.metastore import scoped_to_workspace
    return [a.model_dump()
            for a in scoped_to_workspace(list_agents(), key="connection_id")]


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
    from aughor.org.context import current_org_id
    # AO-1d — the SAME validators the scratch path runs: the connection must exist, every
    # document must exist, the schema must be on the connection, the packs and grants must
    # be declared. Until 2026-10-03 this door checked only the schema, so a pack-path create could name
    # a connection nobody had and the agent was created bound to it.
    _validate_agent_fields(body.name or None, body.instructions, body.connection_id,
                           body.doc_ids, body.schema_scope)
    _validate_agent_packs(body.pack_ids)
    _validate_agent_grants(body.tool_grants, body.connection_id, body.schema_scope)
    made = create_from_template(body.pack_id, name=body.name,
                                connection_id=body.connection_id,
                                schema_scope=body.schema_scope,
                                instructions=body.instructions, purpose=body.purpose,
                                doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                                tool_grants=body.tool_grants,
                                owner=current_org_id() or "")
    if made is None:
        raise HTTPException(status_code=404, detail=f"no pack {body.pack_id!r}")
    return made


class AgentProposeRequest(BaseModel):
    #: What the agent should be able to answer, in the person's own words.
    description: str = ""
    #: Which connection it will answer on. The scope is drafted WITHIN this.
    connection_id: str = ""


@router.post("/agents/custom/propose")
async def propose_user_agent(body: AgentProposeRequest):
    """Describe an agent; get a drafted one back with its evidence. Nothing is created.

    Declared BEFORE the `/agents/custom/{agent_id}` routes for the reason the automations
    router learned the hard way: FastAPI matches in declaration order, and a static segment
    behind a path-parameter route is never reached.

    The catalogue, documents and packs are read HERE and handed to a pure proposer, so the
    judgment half stays testable without a database and without spending a token.
    """
    from aughor.custom_agents.propose import propose_agent

    conn_id = (body.connection_id or "").strip()
    if not conn_id:
        # 200 with a refusal, not a 422: "which connection?" is an answer to the question
        # asked, and the flow renders it as a step rather than as a form error.
        return {"verdict": "refused", "reason": "choose a connection first — an agent's "
                "scope is drafted inside one", "draft": {}, "goldens": [],
                "disclosures": [], "evidence": "", "notes": ""}

    catalogue: list[dict] = []
    try:
        from aughor.routers.catalog import get_catalog_tree
        tree = await get_catalog_tree()
        for section in tree.get("sections", []):
            for entry in section.get("entries", []):
                if entry.get("conn_id") == conn_id:
                    catalogue = entry.get("schemas") or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent proposal catalogue read", counter="agents.propose_catalogue")

    documents: list[dict] = []
    try:
        from aughor.knowledge.indexer import list_documents
        documents = list_documents() or []
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent proposal document read", counter="agents.propose_documents")

    packs: list[dict] = []
    try:
        from aughor.packs.intake import active_packs
        packs = [{"id": p.id, "name": getattr(p, "name", ""),
                  "description": getattr(p, "description", "")} for p in active_packs()]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent proposal pack read", counter="agents.propose_packs")

    return propose_agent(body.description, conn_id=conn_id, catalogue=catalogue,
                         documents=documents, packs=packs).as_response()


@router.post("/agents/custom", status_code=201)
def create_user_agent(body: UserAgentCreate):
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids,
                           body.schema_scope)
    _validate_agent_packs(body.pack_ids)
    _validate_agent_grants(body.tool_grants, body.connection_id, body.schema_scope)
    from aughor.org.context import current_org_id
    from aughor.custom_agents import create_agent
    agent = create_agent(body.name, instructions=body.instructions, purpose=body.purpose,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         tool_grants=body.tool_grants,
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
    from aughor.custom_agents import get_agent, update_agent
    # SP-7 — a schema is checked against the connection it will be read through: the one
    # this patch sets, or the stored one when the patch changes only the schema.
    schema_conn = body.connection_id
    if body.schema_scope and schema_conn is None:
        stored_for_schema = get_agent(agent_id)
        schema_conn = stored_for_schema.connection_id if stored_for_schema else None
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids)
    if body.schema_scope:
        _validate_agent_fields(connection_id=schema_conn, schema_scope=body.schema_scope)
    _validate_agent_packs(body.pack_ids)
    if body.tool_grants is not None:
        # Against the EFFECTIVE binding: a patch may change grants without restating the
        # connection, and validating against "" would skip the roster check exactly when
        # the agent is bound.
        stored = get_agent(agent_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="No such agent")
        eff_conn = body.connection_id if body.connection_id is not None else stored.connection_id
        eff_schema = body.schema_scope if body.schema_scope is not None else stored.schema_scope
        _validate_agent_grants(body.tool_grants, eff_conn, eff_schema)
    agent = update_agent(agent_id, name=body.name, instructions=body.instructions,
                         purpose=body.purpose,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         tool_grants=body.tool_grants,
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


class GuardrailBody(BaseModel):
    pii: str = "redact"
    max_tokens_per_run: Optional[int] = None


@router.get("/agents/custom/{agent_id}/guardrails")
def get_user_agent_guardrails(agent_id: str):
    """What this agent is allowed to do with what it sees, and how much it may spend (VA-8).

    Always answers — an agent with no policy gets the defaults, which are what the
    platform did before guardrails existed. `modes` is served from the code rather than
    written into the frontend, so a mode nothing enforces can never appear in the UI.
    """
    from aughor.custom_agents import get_agent
    from aughor.govern.guardrails import PII_MODES, policy_for
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    policy = policy_for(agent_id)
    return {"agent_id": agent_id, "guardrails": policy.to_dict(),
            "is_default": policy.is_default, "modes": {"pii": list(PII_MODES)}}


@router.put("/agents/custom/{agent_id}/guardrails")
def set_user_agent_guardrails(agent_id: str, body: GuardrailBody):
    """Set this agent's guardrails.

    Deliberately NOT part of the agent's governing configuration: a guardrail is an
    operator's decision ABOUT an agent rather than part of the configuration the revision
    plane versions, and folding it in would mark every eval chip stale the moment somebody
    tightened a cap.
    """
    from aughor.custom_agents import get_agent
    from aughor.govern.guardrails import PII_MODES, GuardrailPolicy, set_policy
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    if body.pii not in PII_MODES:
        raise HTTPException(status_code=422,
                            detail=f"unknown pii mode {body.pii!r} — known: {list(PII_MODES)}")
    if body.max_tokens_per_run is not None and body.max_tokens_per_run <= 0:
        raise HTTPException(status_code=422,
                            detail="max_tokens_per_run must be positive — a cap of zero "
                                   "is not a cap, it is an outage")
    policy = GuardrailPolicy(pii=body.pii, max_tokens_per_run=body.max_tokens_per_run)
    set_policy(agent_id, policy)
    return {"agent_id": agent_id, "guardrails": policy.to_dict(),
            "is_default": policy.is_default}


@router.delete("/agents/custom/{agent_id}")
def delete_user_agent(agent_id: str):
    """Delete an agent and everything that would keep answering as it (AO-1e).

    The receipt says what moved: which Slack bots were switched off (each now carries
    `disabled_reason`), which automations were detached from it, and that its configuration
    revisions are kept. Before 2026-10-03 the row and its goldens went and the bot's socket
    stayed open, answering as an agent that no longer existed.
    """
    from aughor.custom_agents.retire import retire_agent
    receipt = retire_agent(agent_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return receipt


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
    _check_reference_sql(body.reference_sql)
    return add_golden(agent_id, body.question, body.reference_sql)


def _check_reference_sql(sql: str) -> None:
    # WP-1c — fail CLOSED on unparseable SQL: `is_mutating` returns False on a parse
    # failure, so an unparseable statement previously slipped past the read-only check.
    # Goldens are user-authored ground truth; a parse failure is a user error to fix.
    import sqlglot
    try:
        _parsed = sqlglot.parse_one(sql)
    except Exception:
        _parsed = None
    if _parsed is None:
        raise HTTPException(
            status_code=422,
            detail="reference_sql could not be parsed — provide valid, read-only SQL")
    from aughor.sql.readonly import is_mutating
    if is_mutating(sql):
        raise HTTPException(status_code=422, detail="reference_sql must be read-only")


@router.delete("/agents/custom/{agent_id}/goldens/{golden_id}")
def delete_agent_golden(agent_id: str, golden_id: str):
    from aughor.custom_agents.store import delete_golden
    # Scoped to the agent in the path. Unscoped, that path parameter was decorative and
    # any agent's URL could delete any golden — the suite an agent is measured by.
    if not delete_golden(golden_id, agent_id=agent_id):
        raise HTTPException(status_code=404, detail="No such golden")
    return {"deleted": golden_id}


class GoldenCertify(BaseModel):
    reference_sql: str


@router.post("/agents/custom/{agent_id}/goldens/{golden_id}/certify")
def certify_agent_golden(agent_id: str, golden_id: str, body: GoldenCertify):
    """A person turns a CANDIDATE (drafted from the catalogue, or an answer accepted in
    use) into a golden the suite counts, with the SQL they say is right (AO-6, AO-7c).
    The same read-only parse the hand-written path runs; a judge never certifies."""
    from aughor.custom_agents.store import certify_golden
    if not body.reference_sql.strip():
        raise HTTPException(status_code=422, detail="reference_sql is required to certify")
    _check_reference_sql(body.reference_sql)
    row = certify_golden(golden_id, agent_id, body.reference_sql)
    if row is None:
        raise HTTPException(status_code=404, detail="No such golden")
    return row


@router.post("/agents/custom/{agent_id}/goldens/draft", status_code=201)
def draft_agent_goldens(agent_id: str):
    """AO-6 — draft golden QUESTIONS from the connection's metric catalogue and the agent's
    purpose: one model call, up to six candidates, no SQL (the model may not certify).
    Refused with the reason while the testing centre's flag is off."""
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.learning import draft_synthetic_goldens
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    try:
        return {"drafted": draft_synthetic_goldens(agent)}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/agents/custom/{agent_id}/doors")
def agent_doors(agent_id: str):
    """AO-5 — every door into this agent with its state: the MCP tool name, the HTTP door
    and its key (issued when, never what), the embed page, the webhook, the A2A card, and
    the Teams bots that front it."""
    import os
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.reach import doors_for
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    doors = doors_for(agent, public_api=os.environ.get("AUGHOR_PUBLIC_API_URL", ""),
                      public_web=os.environ.get("AUGHOR_WEB_URL", ""))
    try:
        from aughor.teamsbots.store import bots_for_agent
        doors["teams"] = {"bots": [b.to_safe_dict() for b in bots_for_agent(agent_id)],
                          "state": "open" if bots_for_agent(agent_id) else "no bot"}
    except Exception as exc:                            # noqa: BLE001 — said, not hidden
        doors["teams"] = {"bots": [], "state": f"could not read: {exc}"}
    return doors


@router.post("/agents/custom/{agent_id}/key")
def issue_agent_key_route(agent_id: str):
    """Mint the agent's HTTP-door key and return it ONCE. Issuing replaces (a rotation is
    the same gesture); the status never discloses it."""
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.keys import agent_key_issued_at, issue_agent_key
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    raw = issue_agent_key(agent_id)
    return {"key": raw, "issued_at": agent_key_issued_at(agent_id),
            "header": f"Authorization: Bearer {raw}",
            "curl": (f"curl -sS -X POST \"$AUGHOR_API/doors/agents/{agent_id}/ask\" "
                     f"-H 'Authorization: Bearer {raw}' -H 'content-type: application/json' "
                     "-d '{\"question\": \"How many orders yesterday?\", \"asker\": \"me@example.com\"}'")}


@router.delete("/agents/custom/{agent_id}/key")
def revoke_agent_key_route(agent_id: str):
    from aughor.custom_agents.keys import revoke_agent_key
    if not revoke_agent_key(agent_id):
        raise HTTPException(status_code=404, detail="No key is issued for this agent")
    return {"revoked": agent_id}


@router.get("/agents/custom/{agent_id}/learning")
def agent_learning(agent_id: str):
    """AO-7d — the loop's receipt: verdicts and corrections this agent earned, candidates
    waiting for a person's SQL, goldens certified from use, and the pass count before →
    after the latest evaluation. The flags' states are on it, so an empty receipt says
    whether the loop is off or merely unused."""
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.learning import learning_summary
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return learning_summary(agent_id)


@router.get("/agents/custom/{agent_id}/observability")
def user_agent_observability(agent_id: str, range: str = "", since: str = "",
                             until: str = ""):
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

    AO-3 (2026-10-03): everything here is read over ONE window — the shared Agent Ops
    range, 24h by default — and the window rides on the response. Measured before: the
    roster row said 76.7K tokens (24h, from the fleet fold) and this page said 3.5M
    (all time) for the same agent, and nothing on either screen said which was which.
    """
    from aughor.custom_agents import get_agent
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    from aughor import telemetry
    from aughor.db.history import list_investigations_for_agent
    from aughor.obs.timeseries import resolve_window
    win = resolve_window(range, since=since, until=until)
    # The newest 200 of the agent's runs, kept to the window. A window holding more than
    # 200 runs would be undercounted here, and `runs_scanned` lets a reader see that.
    scanned = list_investigations_for_agent(agent_id, limit=200)
    runs = [r for r in scanned
            if win.since <= str(r.get("started_at") or "") < win.until]
    return {
        "agent_id": agent_id,
        "window": _window_dict(win),
        "run_count": len(runs),
        "runs_scanned": len(scanned),
        "runs": runs,
        "trace_stats": telemetry.agent_trace_stats(agent_id),
        "spend": _agent_spend(agent_id, win),
    }


def _agent_spend(agent_id: str, win) -> dict:
    """This agent's slice of the G3 usage rollup, over ``win``.

    Recording is permanent, so an empty slice means this agent spent nothing in the
    window — not that nothing was watching. ``cost_is_complete`` carries G3's own caveat
    forward, and ``unpriced_calls`` is the number behind it: a model with no declared
    price contributes nothing to the total rather than counting as free, and a tile that
    knows HOW MANY calls were unpriced can say "unpriced" instead of "$0.00".
    """
    from aughor.obs.usage import rollup
    rows = Ledger.default().session_events(kind="llm_call", agent_id=agent_id,
                                           since=win.since, until=win.until, limit=5000)
    report = rollup(rows, axes=("agent_id",)).to_dict()
    for row in report.get("rows") or []:
        if row.get("agent_id") == agent_id:
            return {"measured": True, "calls": row.get("calls", 0),
                    "total_tokens": row.get("total_tokens", 0),
                    "cost_usd": row.get("cost_usd"),
                    "cost_is_complete": row.get("cost_is_complete", False),
                    "unpriced_calls": row.get("unpriced_calls", 0),
                    "calls_without_usage": row.get("calls_without_usage", 0),
                    "failure_rate": row.get("failure_rate")}
    return {"measured": True, "calls": 0, "total_tokens": 0, "cost_usd": 0.0,
            "cost_is_complete": True, "unpriced_calls": 0, "calls_without_usage": 0,
            "failure_rate": 0.0}


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
