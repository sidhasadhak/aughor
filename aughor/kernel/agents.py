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

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

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
class Knob:
    """One declared, governable LIMIT an agent's pipelines read at run time — a cap on
    how much of a warehouse one act may touch (tables seeded, schema chars in a prompt),
    as distinct from the per-run token/time budget the kernel enforces from outside.

    Declared on the charter so every surface reads ONE registry: the /agents route
    serves it, the Agent Ops roster renders it, Spotlight's Know limb reports it and its
    Act limb proposes changes to it — and the enforcement site reads the resolved value
    through `effective_limit`. A knob nobody declared cannot be set, and a value outside
    [min, max] is refused in the same words on every door.
    """
    id: str
    label: str                      # display copy ("Glossary autoseed · tables per connection")
    description: str                # what it bounds and what happens past it
    default: int
    min: int
    max: int
    unit: str                       # "tables", "chars"
    applies_to: str                 # WHERE it bites, in a reader's words — Spotlight's "what is where"

    def clamp_or_refuse(self, value) -> int:
        """Coerce and range-check one proposed value; ValueError names the range."""
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{self.id} must be a whole number of {self.unit}") from None
        if v < self.min or v > self.max:
            raise ValueError(f"{self.id} must be between {self.min:,} and {self.max:,} {self.unit}")
        return v


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
    #: The limits this agent's pipelines honour (see `Knob`). Empty for most charters —
    #: their spend is bounded by the per-run budget alone.
    knobs: tuple = ()
    # There is no `recommended_models` field any more (removed 2026-08-15, with the rest
    # of this repo's hardcoded model ids). A charter describes what an agent DOES and
    # what it may spend; which model serves it is the operator's binding, and a
    # suggestion baked in here was this repo asserting a fact about another vendor's
    # catalogue that it had no way to keep true.

    def to_dict(self) -> dict:
        d = asdict(self)
        d["job_kinds"] = list(self.job_kinds)
        d["tools"] = list(self.tools)
        d["knobs"] = [asdict(k) for k in self.knobs]
        return d


# The roster. Explorer + Analyst + Responder run interactive/background work today; Watcher +
# Briefer are wired to the metered monitor/briefing cron (WP-7, flag `ops.metered_monitors`);
# Curator runs the R12 birth job (kind "profile" — eager intelligence at connection/canvas
# birth, flag `birth.job`), moved under the kernel per its original Phase-3 reservation.
AGENTS: tuple[AgentCharter, ...] = (
    AgentCharter(
        # id is a persisted governance key (see docs/GLOSSARY.md, "Names that are frozen") —
        # only `name`/`role`/`goal` are display copy.
        id="scout", name="Explorer", role="Autonomous data explorer",
        goal="Continuously explore connected data and surface findings — no prompts, no dashboards.",
        lane="background", job_kinds=("exploration",),
        tools=("schema profiling", "grounded SQL", "finding synthesis"),
        icon="telescope",
        # runs continuously at volume, so the budget is the lever that matters
        default_budget=Budget(token_budget=200_000, time_budget_s=600),
    ),
    AgentCharter(
        id="analyst", name="Analyst", role="Deep analysis reasoner",
        goal="Root-cause a question with evidence — plan → query → score → synthesize.",
        lane="interactive", job_kinds=("investigation", "investigation_salvage"),
        tools=("NL→SQL", "fan-out / additivity guards", "evidence scoring", "Trust Receipt"),
        icon="microscope",
        # highest stakes and the widest schemas; latency is noise on a 900s job
        default_budget=Budget(token_budget=500_000, time_budget_s=900),
    ),
    AgentCharter(
        id="insight", name="Responder", role="Quick answerer",
        goal="Answer a question fast in chat — grounded NL→SQL with a Trust Receipt.",
        lane="interactive", job_kinds=(),
        tools=("NL→SQL", "auto-repair", "Trust Receipt"),
        icon="search",
        # the user is WAITING — this is the one lane where latency is the budget
        default_budget=Budget(token_budget=150_000, time_budget_s=300),
    ),
    AgentCharter(
        id="watcher", name="Watcher", role="KPI sentinel",
        goal="Watch metrics, start a deep analysis when something moves, and propose the "
             "alerts worth having once a connection is mapped.",
        # Idea 2 — `alert_proposals`: after an exploration the Watcher reads every metric's
        # daily series, learns its distribution and stages an anomaly watch in the inbox
        # (`monitors/sentinel.py`). SQL only; a person arms it.
        lane="background", job_kinds=("monitor", "alert_proposals"),
        tools=("thresholds", "anomaly checks", "alert proposals"),
        icon="radar",
        # WP-7: a tick is a scalar/threshold SQL check (rarely any LLM) — a small token
        # ceiling + generous time for a slow warehouse query. Governable per-agent.
        # ⚠️ Whatever model an operator binds here must return content for STRUCTURED
        # calls — every agent call is one. A reasoning-tuned variant that returns empty
        # content for them looks healthy (measured 2026-08-13: the fallback chain
        # silently answered from another backend), so verify a binding in
        # Settings ▸ Models rather than inferring it from a run that succeeded.
        # Threshold checks are near-trivial, hence the small ceiling.
        default_budget=Budget(token_budget=50_000, time_budget_s=120)),
    AgentCharter(
        id="briefer", name="Briefer", role="Verdict synthesizer",
        goal="Synthesize the briefing — the state of the business in one read.",
        lane="background", job_kinds=("brief",), tools=("tree-reduce", "grounding"),
        icon="newspaper",
        # WP-7: a briefing runs real tree-reduce synthesis (LLM) over the workspace findings.
        # scheduled, so latency-tolerant; briefing prose quality is user-visible
        default_budget=Budget(token_budget=400_000, time_budget_s=300)),
    AgentCharter(
        id="curator", name="Curator", role="Semantic-layer keeper",
        goal="Keep the profile, ontology, and metrics fresh and governed.",
        lane="background", job_kinds=("profile",), tools=("inference", "override-merge"),
        icon="folder",
        # R12: the birth job's intelligence step includes ONE ontology-enrichment LLM
        # pass (+ deterministic profiling/validation SQL) — a modest token ceiling with
        # generous time for slow warehouses. Exploration runs under Scout's own budget.
        # background enrichment — quality matters, urgency does not
        default_budget=Budget(token_budget=200_000, time_budget_s=900),
        # The two birth-time prompts whose size is a function of the WAREHOUSE, not of
        # the question (measured 2026-09-22: the glossary autoseed is one model call per
        # table with no cap, and the token budget above cannot stop it — the birth job's
        # intelligence step runs in an executor thread the kernel's cancel does not reach;
        # the business-profile prompt carries the whole rendered schema, and the provider
        # chokepoint only WARNS on overflow). A 1,500-table warehouse was 1.7–4M tokens on
        # birth. These knobs are the operator's cap on both, from Agent Ops or Spotlight.
        knobs=(
            Knob(
                id="autoseed_max_tables",
                label="Glossary autoseed · tables per connection",
                description=("How many tables the Curator writes model-generated glossary "
                             "words for, largest first by row count. Tables past the cap keep "
                             "their raw schema and never spend a model call. 0 turns "
                             "autoseed off for the connection."),
                # Mirrors tools/profiler.MAX_PROFILED_TABLES (pinned by test): the tables
                # the explorer can ever see are the same largest sixty.
                default=60, min=0, max=10_000, unit="tables",
                applies_to=("the glossary autoseed that runs inside the connection's birth "
                            "job and on every schema rebuild — one model call per table"),
            ),
            Knob(
                id="profile_schema_chars",
                label="Business profile · schema chars per prompt",
                description=("The most rendered-schema text the business-profile inference "
                             "sends in one prompt. Over the cap the largest tables are kept, "
                             "the rest are cut, and the prompt says so. ~3.5 chars per "
                             "token; the default matches the large-context tier's schema "
                             "budget."),
                default=60_000, min=2_000, max=400_000, unit="chars",
                applies_to=("the business-profile inference at connection birth, on Profile "
                            "refresh, and when the explorer's Phase 8 needs a profile"),
            ),
        )),
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


# Sub-roles that collaborate *inside* an Analyst deep analysis (Phase 2):
# Orchestrator → SQL Engineer → Verifier → Narrator. They run within Analyst's
# budget/governance, so they're not in the governable roster — this is just identity for
# the agent.handoff provenance, so the collaboration is legible in the agents view +
# Trust Receipt.
#
# `orchestrator` emits handoffs (agent/investigate.py) but was never registered here, so
# every one of its handoffs rendered through the unknown-echo fallback below: the raw id
# as its name, an empty role, and a gear icon. It is a real sub-role; it is declared here.
SPECIALISTS: dict[str, dict] = {
    "orchestrator": {"name": "Orchestrator", "role": "Phase plan + contradiction check",
                     "icon": "gear"},
    "sql_engineer": {"name": "SQL Engineer", "role": "Grounded SQL + repair", "icon": "builder"},
    "verifier":     {"name": "Verifier", "role": "Trust guards + plausibility", "icon": "shield"},
    "narrator":     {"name": "Narrator", "role": "Grounded prose", "icon": "brief"},
}


def specialist(agent_id: str) -> dict:
    """Identity for a deep-analysis sub-role (never raises; unknown → echoed).

    Falls back to the ROSTER before echoing, because a handoff names both sub-roles and
    charters — `investigate.py` emits `orchestrator → analyst` and `analyst → orchestrator`,
    and `analyst` is a charter, not a sub-role. Without this it rendered as the bare
    lowercase id with no role, so one side of every such handoff looked unknown.
    """
    hit = SPECIALISTS.get(agent_id)
    if hit is not None:
        return hit
    charter = _BY_ID.get(agent_id)
    if charter is not None:
        return {"name": charter.name, "role": charter.role, "icon": charter.icon}
    return {"name": agent_id, "role": "", "icon": "gear"}


# ── Governance (override-wins: workspace > app > charter default) ─────────────

@dataclass
class Governance:
    enabled: bool
    token_budget: Optional[int]
    time_budget_s: Optional[int]
    model: Optional[str] = None   # per-agent LLM model override; None = use the role default
    #: Resolved knob values by knob id (charter default < app override < workspace
    #: override) — only the knobs the charter declares, always all of them.
    limits: dict = field(default_factory=dict)

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
    knobs = {k.id: k for k in (c.knobs if c else ())}
    limits = {k.id: k.default for k in knobs.values()}
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
        for kid, raw in (ov.get("limits") or {}).items():
            # A stored value for a knob the charter no longer declares is ignored, and a
            # stored value outside today's range is clamped — the registry is the law,
            # the store is history.
            k = knobs.get(kid)
            if k is None or raw is None:
                continue
            try:
                limits[kid] = min(k.max, max(k.min, int(raw)))
            except (TypeError, ValueError) as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, f"stored limit {kid!r} for {agent_id} is not a number — "
                              f"the charter default stands", counter="agents.limit_unreadable")
                continue
    # P6: a deployment-wide hard ceiling. An operator can bound worst-case cost across
    # ALL agents at once (without per-agent config) by setting AUGHOR_MAX_TOKEN_BUDGET;
    # it only ever LOWERS the resolved budget, and both the kernel heartbeat and the
    # synchronous _metered_stream read effective_governance, so it caps every governed run.
    import os
    _ceiling = os.getenv("AUGHOR_MAX_TOKEN_BUDGET", "").strip()
    if _ceiling.isdigit():
        cap = int(_ceiling)
        tok = cap if tok is None else min(tok, cap)
    return Governance(enabled=enabled, token_budget=tok, time_budget_s=tim, model=model,
                      limits=limits)


def set_governance(agent_id: str, *, scope: Optional[str] = None,
                   enabled: Optional[bool] = None,
                   token_budget: Optional[int] = None,
                   time_budget_s: Optional[int] = None,
                   model: Optional[str] = None,
                   limits: Optional[dict] = None) -> Governance:
    """Persist an override for `agent_id` at `scope` (app by default). Only the
    provided fields are written; the rest keep inheriting. Returns the new effective.
    Pass ``model=""`` to clear a previously-set per-agent model back to the role default.
    ``limits`` maps knob id → value; a ``None`` value clears that knob back to inherit.
    An undeclared knob or an out-of-range value raises ValueError naming what is
    allowed — the same sentence on every door (route, inbox accept, Spotlight)."""
    sc = scope or _APP_SCOPE
    cur = _override(sc, agent_id)
    if limits:
        c = get_charter(agent_id)
        known = {k.id: k for k in (c.knobs if c else ())}
        stored = dict(cur.get("limits") or {})
        for kid, raw in limits.items():
            k = known.get(kid)
            if k is None:
                raise ValueError(
                    f"{agent_id} declares no limit {kid!r}; its limits are: "
                    + (", ".join(sorted(known)) or "none"))
            if raw is None:
                stored.pop(kid, None)
            else:
                stored[kid] = k.clamp_or_refuse(raw)
        cur["limits"] = stored
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if token_budget is not None:
        cur["token_budget"] = int(token_budget)
    if time_budget_s is not None:
        cur["time_budget_s"] = int(time_budget_s)
    if model is not None:
        # No validation against a known-model list: there is none any more, and there
        # was never a way to keep one true. A wrong id fails as a config error on the
        # next call rather than silently — see NoModelConfigured in llm/provider.py.
        cur["model"] = str(model).strip()   # "" clears it (treated as 'inherit' on read)
    _ledger().kv_put(_GOV_STORE, f"{sc}:{agent_id}", cur)
    return effective_governance(agent_id, None if sc == _APP_SCOPE else sc)


def is_enabled(agent_id: str, workspace_id: Optional[str] = None) -> bool:
    """Whether this agent may run. Fail-open (a governance read error never blocks work)."""
    try:
        return effective_governance(agent_id, workspace_id).enabled
    except Exception:
        return True


def get_knob(agent_id: str, knob_id: str) -> Optional[Knob]:
    c = get_charter(agent_id)
    return next((k for k in (c.knobs if c else ()) if k.id == knob_id), None)


def effective_limit(agent_id: str, knob_id: str, workspace_id: Optional[str] = None) -> int:
    """The resolved value of one declared knob — what an enforcement site reads.
    Fails SAFE to the charter default (never to unbounded): a governance read error
    must not turn a cap off. KeyError for a knob the charter never declared — that is
    a programming error at the call site, not a runtime condition to tolerate."""
    k = get_knob(agent_id, knob_id)
    if k is None:
        raise KeyError(f"{agent_id} declares no limit {knob_id!r}")
    try:
        return int(effective_governance(agent_id, workspace_id).limits[knob_id])
    except Exception:
        return k.default
