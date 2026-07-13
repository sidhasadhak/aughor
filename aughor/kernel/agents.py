"""The agent registry + governance — Phase 0 of the agent fleet.

Every background/active process Aughor runs is a named **agent** with a charter
(role · goal · lane · the job kinds it owns · default budget). The Org governs the
fleet: enable/disable an agent and cap its per-run budget. Governance resolves
**override-wins** (workspace > app > charter default), mirroring org settings — v1
operates the **app scope** (the Org's fleet config); the storage + resolver already
accept a workspace scope for later per-workspace control.

This is what makes the platform legible and manageable as a fleet: the Fleet view
reads charters so runs show as agents (Scout/Analyst), and the /agents surface lets
an admin manage the roster. Budgets are meaningful because runs are metered
(see kernel/metering.py).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

_GOV_STORE = "agent_governance"
_APP_SCOPE = "__app__"


@dataclass(frozen=True)
class Budget:
    """A soft per-run cap. None = unbounded."""
    token_budget: Optional[int] = None
    time_budget_s: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AgentCharter:
    id: str
    name: str                       # display name ("Scout")
    role: str                       # one-line role
    goal: str                       # what it's for
    lane: str                       # "background" (autonomous) | "interactive" (user-initiated)
    job_kinds: tuple                # the kernel job kinds this agent runs
    tools: tuple                    # descriptive tool list (for the charter card)
    icon: str
    default_enabled: bool = True
    default_budget: Budget = field(default_factory=Budget)
    reserved: bool = False          # defined but not yet wired to runs (Phase 0 → 3)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["job_kinds"] = list(self.job_kinds)
        d["tools"] = list(self.tools)
        return d


# The roster. Scout + Analyst + Insight run interactive/background work today; Watcher +
# Briefer are wired to the metered monitor/brief cron (WP-7, flag `ops.metered_monitors`);
# only Curator (profile refresh) stays reserved until it moves under the kernel.
AGENTS: tuple[AgentCharter, ...] = (
    AgentCharter(
        id="scout", name="Scout", role="Autonomous data explorer",
        goal="Continuously explore connected data and surface findings — no prompts, no dashboards.",
        lane="background", job_kinds=("exploration",),
        tools=("schema profiling", "grounded SQL", "finding synthesis"),
        icon="telescope", default_budget=Budget(token_budget=200_000, time_budget_s=600),
    ),
    AgentCharter(
        id="analyst", name="Analyst", role="Deep-analysis reasoner",
        goal="Root-cause a question with evidence — plan → query → score → synthesize.",
        lane="interactive", job_kinds=("investigation", "investigation_salvage"),
        tools=("NL→SQL", "fan-out / additivity guards", "evidence scoring", "Trust Receipt"),
        icon="microscope", default_budget=Budget(token_budget=500_000, time_budget_s=900),
    ),
    AgentCharter(
        id="insight", name="Insight", role="Quick answerer",
        goal="Answer a question fast in chat — grounded NL→SQL with a Trust Receipt.",
        lane="interactive", job_kinds=(),
        tools=("NL→SQL", "auto-repair", "Trust Receipt"),
        icon="search", default_budget=Budget(token_budget=150_000, time_budget_s=300),
    ),
    AgentCharter(
        id="watcher", name="Watcher", role="KPI sentinel",
        goal="Watch metrics and spawn an investigation when something moves.",
        lane="background", job_kinds=("monitor",), tools=("thresholds", "anomaly checks"),
        icon="radar",
        # WP-7: a tick is a scalar/threshold SQL check (rarely any LLM) — a small token
        # ceiling + generous time for a slow warehouse query. Governable per-agent.
        default_budget=Budget(token_budget=50_000, time_budget_s=120)),
    AgentCharter(
        id="briefer", name="Briefer", role="Verdict synthesizer",
        goal="Synthesize the briefing — the state of the business in one read.",
        lane="background", job_kinds=("brief",), tools=("tree-reduce", "grounding"),
        icon="newspaper",
        # WP-7: a brief runs real tree-reduce synthesis (LLM) over the workspace insights.
        default_budget=Budget(token_budget=400_000, time_budget_s=300)),
    AgentCharter(
        id="curator", name="Curator", role="Semantic-layer keeper",
        goal="Keep the profile, ontology, and metrics fresh and governed.",
        lane="background", job_kinds=("profile",), tools=("inference", "override-merge"),
        icon="folder", reserved=True),
)

_BY_ID: dict[str, AgentCharter] = {a.id: a for a in AGENTS}
_BY_KIND: dict[str, AgentCharter] = {k: a for a in AGENTS for k in a.job_kinds}
_UNKNOWN = AgentCharter(id="worker", name="Worker", role="Background work", goal="",
                        lane="background", job_kinds=(), tools=(), icon="gear")


def list_charters() -> list[AgentCharter]:
    return list(AGENTS)


def get_charter(agent_id: str) -> Optional[AgentCharter]:
    return _BY_ID.get(agent_id)


def charter_for_kind(kind: str | None) -> AgentCharter:
    return _BY_KIND.get(kind or "", _UNKNOWN)


def agent_for(kind: str | None) -> dict:
    """The compact agent badge for a job kind — what the Fleet view shows."""
    c = charter_for_kind(kind)
    return {"id": c.id, "agent": c.name, "blurb": c.role, "icon": c.icon}


# Specialist sub-agents that collaborate *inside* an Analyst investigation (Phase 2):
# SQL-Engineer → Verifier → Narrator. They run within Analyst's budget/governance, so
# they're not in the governable roster — this is just identity for the agent.handoff
# provenance, so the collaboration is legible in the Fleet view + Trust Receipt.
SPECIALISTS: dict[str, dict] = {
    "sql_engineer": {"name": "SQL Engineer", "role": "Grounded SQL + repair", "icon": "builder"},
    "verifier":     {"name": "Verifier", "role": "Trust guards + plausibility", "icon": "shield"},
    "narrator":     {"name": "Narrator", "role": "Grounded prose", "icon": "brief"},
}


def specialist(agent_id: str) -> dict:
    """Identity for an ADA specialist sub-agent (never raises; unknown → echoed)."""
    return SPECIALISTS.get(agent_id, {"name": agent_id, "role": "", "icon": "gear"})


# ── Governance (override-wins: workspace > app > charter default) ─────────────

@dataclass
class Governance:
    enabled: bool
    token_budget: Optional[int]
    time_budget_s: Optional[int]
    model: Optional[str] = None   # per-agent LLM model override; None = use the role default

    def to_dict(self) -> dict:
        return asdict(self)


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _override(scope: str, agent_id: str) -> dict:
    try:
        return _ledger().kv_get(_GOV_STORE, f"{scope}:{agent_id}", {}) or {}
    except Exception:
        return {}


def effective_governance(agent_id: str, workspace_id: Optional[str] = None) -> Governance:
    """Resolve an agent's governance — workspace override > app override > charter default.
    A `None` field in an override means 'inherit', so a scope can override just one field."""
    c = get_charter(agent_id)
    enabled = c.default_enabled if c else True
    tok = c.default_budget.token_budget if c else None
    tim = c.default_budget.time_budget_s if c else None
    model: Optional[str] = None   # charter default = no override (use the role default)
    scopes = [_APP_SCOPE] + ([workspace_id] if workspace_id else [])
    for scope in scopes:
        ov = _override(scope, agent_id)
        if ov.get("enabled") is not None:
            enabled = bool(ov["enabled"])
        if ov.get("token_budget") is not None:
            tok = ov["token_budget"]
        if ov.get("time_budget_s") is not None:
            tim = ov["time_budget_s"]
        if ov.get("model") is not None:
            model = (str(ov["model"]).strip() or None)
    # P6: a deployment-wide hard ceiling. An operator can bound worst-case cost across
    # ALL agents at once (without per-agent config) by setting AUGHOR_MAX_TOKEN_BUDGET;
    # it only ever LOWERS the resolved budget, and both the kernel heartbeat and the
    # synchronous _metered_stream read effective_governance, so it caps every governed run.
    import os
    _ceiling = os.getenv("AUGHOR_MAX_TOKEN_BUDGET", "").strip()
    if _ceiling.isdigit():
        cap = int(_ceiling)
        tok = cap if tok is None else min(tok, cap)
    return Governance(enabled=enabled, token_budget=tok, time_budget_s=tim, model=model)


def set_governance(agent_id: str, *, scope: Optional[str] = None,
                   enabled: Optional[bool] = None,
                   token_budget: Optional[int] = None,
                   time_budget_s: Optional[int] = None,
                   model: Optional[str] = None) -> Governance:
    """Persist an override for `agent_id` at `scope` (app by default). Only the
    provided fields are written; the rest keep inheriting. Returns the new effective.
    Pass ``model=""`` to clear a previously-set per-agent model back to the role default."""
    sc = scope or _APP_SCOPE
    cur = _override(sc, agent_id)
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if token_budget is not None:
        cur["token_budget"] = int(token_budget)
    if time_budget_s is not None:
        cur["time_budget_s"] = int(time_budget_s)
    if model is not None:
        cur["model"] = str(model).strip()   # "" clears it (treated as 'inherit' on read)
    _ledger().kv_put(_GOV_STORE, f"{sc}:{agent_id}", cur)
    return effective_governance(agent_id, None if sc == _APP_SCOPE else sc)


def is_enabled(agent_id: str, workspace_id: Optional[str] = None) -> bool:
    """Whether this agent may run. Fail-open (a governance read error never blocks work)."""
    try:
        return effective_governance(agent_id, workspace_id).enabled
    except Exception:
        return True
