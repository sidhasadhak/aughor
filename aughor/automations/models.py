"""Wave A1 — the Automation data model: combinable conditions → ordered effects.

Three design choices carried over from Wave K, each load-bearing:

* **`kind` + opaque `config`**, like :class:`~aughor.ontology.models.SideEffect` — but validated
  **at construction**, not at execute. A malformed condition is rejected before it can ever be
  stored, so a broken automation cannot sit in the DB looking schedulable (K1's lesson: reject at
  parse, never surface).
* **An `Effect` is a REFERENCE, never a new action type.** It names something that already exists —
  an investigation question, a brief subscription, an ActionHub trigger, a declared
  :class:`~aughor.ontology.models.KineticAction` — plus the arguments to invoke it with. Wave A adds
  no fourth "action" concept and, critically, no second write path.
* **The six metric conditions are delegated to, not redefined.** ``threshold_cross``, ``anomaly``,
  ``segment_drift`` and friends already exist and are already tested inside ``Monitor.alert_on``,
  where they are reachable only by a monitor. A ``metric`` condition therefore names a Monitor by
  id and evaluates it — freeing the vocabulary for any effect, without a second copy of the
  statistics that could drift from the first.

:class:`AutomationRun` is the answer to a question the monitor store cannot answer today: it persists
only *fired* alerts, so a tick that evaluated cleanly — or crashed — leaves no row at all. Every tick
writes exactly one run, including the ones that deliberately did nothing, and ``reason`` says why.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from aughor.util.time import now_iso_z


def _new_id() -> str:
    return str(uuid.uuid4())


# ── conditions ───────────────────────────────────────────────────────────────────

#: Required ``config`` keys per condition kind. Validated at construction.
_CONDITION_REQUIRED: dict[str, tuple[str, ...]] = {
    "schedule":       ("cron",),
    "metric":         ("monitor_id",),
    "source_change":  ("table",),
    "entity_appears": ("table",),
    # DS-17 — the webhook trigger requires NOTHING, and that is the wave's point rather
    # than an oversight. Every other trigger is configured by naming something (a cron, a
    # monitor, a table); a webhook is configured by ISSUING A URL, which is a deployment
    # act and lives behind the Deploy door. So the step is complete the moment it is
    # placed, and a chain that has one but has never been given a URL is a chain whose
    # DOOR is shut — a distinction the create form would flatten if it demanded a key here.
    "webhook":        (),
}


class Condition(BaseModel):
    """One precondition on an automation firing. Combinable via ``Automation.condition_logic``.

    ``schedule`` is a cron expression — the *only* condition monitors and briefs have today.
    ``metric`` delegates to an existing :class:`~aughor.monitors.models.Monitor` (by id) so the six
    already-tested alert conditions become available to any effect, not just to an alert.
    ``source_change`` fires when a table's cheap source version advanced (A3). ``entity_appears``
    fires when a new key shows up in a table.

    ``webhook`` (DS-17) fires when something outside this deployment calls the chain's own
    URL. It is the only kind whose cause is not something the engine can observe on a tick,
    which is why its probe reads the RUN rather than the world — see ``evaluate_conditions``.

    ⚠️ ``webhook`` is a trigger kind and also, unrelatedly, a declared-action kind
    (``ontology/models.py``) and a notification-destination kind (``notifications/models.py``).
    Those two are OUTBOUND — a URL Aughor posts to; this one is INBOUND — a URL Aughor is
    posted to. The three never meet because every lookup in this plane is family-scoped
    (``required_keys(kind, family=…)``); a flat kind→handler map added anywhere would start
    answering confidently and wrongly.
    """
    kind: Literal["schedule", "metric", "source_change", "entity_appears", "webhook"]
    config: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_config_keys(self) -> "Condition":
        missing = [k for k in _CONDITION_REQUIRED.get(self.kind, ()) if not self.config.get(k)]
        if missing:
            raise ValueError(
                f"condition kind '{self.kind}' requires config key(s): {', '.join(missing)}"
            )
        return self

    # Typed accessors — call sites never reach into `config` by hand.
    @property
    def cron(self) -> str:
        return str(self.config.get("cron", ""))

    @property
    def monitor_id(self) -> str:
        return str(self.config.get("monitor_id", ""))

    @property
    def table(self) -> str:
        return str(self.config.get("table", ""))

    def describe(self) -> str:
        """A short human string for run history — why this condition did or didn't fire."""
        if self.kind == "schedule":
            return f"schedule({self.cron})"
        if self.kind == "metric":
            return f"metric({self.monitor_id})"
        if self.kind == "webhook":
            return "webhook"       # nothing to name — the URL is the whole configuration
        return f"{self.kind}({self.table})"


# ── effects ──────────────────────────────────────────────────────────────────────

#: Required ``config`` keys per effect kind. Validated at construction.
_EFFECT_REQUIRED: dict[str, tuple[str, ...]] = {
    "investigate":    ("question",),
    "brief":          ("subscription_id",),
    "notify":         ("trigger_id",),
    "kinetic_action": ("action_id",),
    "monitor":        ("monitor_id",),
    "agent_alert":    ("rule_id",),
    # RC-5.4 — post AS a Slack bot. Both keys are required at CONSTRUCTION, like every
    # sibling: an automation missing its channel would otherwise sit in the DB looking
    # schedulable and fail at 03:00, which is K1's lesson (reject at parse, never surface).
    "slack_post":     ("bot_id", "channel"),
    # DS-9 — the chain this step runs. Required at construction like every sibling: a
    # subchain step with no child names nothing, and "looking schedulable" is the
    # expensive kind of broken (K1: reject at parse, never surface).
    "subchain":       ("automation_id",),
    # DS-11 — WHOSE grant, and WHICH declared operation. Both at construction like every
    # sibling: a step naming neither is a step that would ask a provider nothing on
    # behalf of nobody, and "looking schedulable" is the expensive kind of broken.
    "integration_call": ("connection_id", "operation"),
    # DS-12 — the ontology plane, as steps. Each names a GOVERNED object rather than
    # carrying SQL: a metric by the name Finance approved, a query by the id someone
    # vetted. That is the whole difference between this and a step that takes a string
    # of SQL — there is no expression here for anyone to author, so there is none for
    # anyone to inject, and the number a chain acts on is the number the registry
    # defines rather than one an LLM re-derived.
    "metric_value":   ("metric",),
    "trusted_query":  ("query_id",),
    # VA-9d — WHICH allowlisted server, and WHICH of its discovered tools. Both at
    # construction like every sibling: a step naming neither would ask nobody for nothing,
    # and "looking schedulable" is the expensive kind of broken. Note what is NOT here —
    # there is no url, no command and no transport. A step names a row in the allowlist; it
    # cannot describe a destination, which is what keeps "no node is code" true across a
    # boundary that leaves the platform.
    "mcp_call":       ("server_id", "tool"),
}


def required_keys(kind: str, *, family: str) -> tuple[str, ...]:
    """The ``config`` keys a condition or effect of this kind must carry.

    The public reading of the two tables above, added for DS-10's registry. Keyed by
    FAMILY rather than by kind alone: the two maps are separate namespaces that happen not
    to collide today (`metric` is a trigger, `monitor` is an effect), and a lookup that
    fell through from one to the other would start answering confidently the first time
    they did.
    """
    table = _CONDITION_REQUIRED if family == "trigger" else _EFFECT_REQUIRED
    return tuple(table.get(kind, ()))


class GuardClause(BaseModel):
    """W1 — one comparison in a step's ``when`` guard.

    Either side may be a literal or a ``{"$from": "step1.answer"}`` binding, resolved
    against the same accumulated chain context the step's params are. Structural, never
    an expression string, for this plane's three standing reasons: it is validated when
    the automation is saved, it is not an injection surface, and it DRAWS — a guard that
    reads step 1 is an edge on the canvas exactly like a param that does.
    """
    left: Any = None
    op: Literal["truthy", "falsy", "eq", "ne", "gt", "gte", "lt", "lte", "contains"]
    #: Ignored by the unary operators (`truthy`/`falsy`) rather than rejected: an
    #: authoring form that switches the operator on a filled-in row should not have to
    #: clear a field to stay valid.
    right: Any = None

    @model_validator(mode="after")
    def _require_a_subject(self) -> "GuardClause":
        if self.left is None:
            raise ValueError("a guard clause needs a left side — the value being tested")
        return self


class ForEach(BaseModel):
    """W2 — the list a step runs once per item of.

    Our engine ran a strictly sequential list: one step, one dispatch. "Post a summary per
    region" was therefore not expressible — the author wrote three near-identical steps, or
    did it by hand. A fan-out is the second of the two primitives the sequential list is
    missing (the first was W1's guard).

    ``source`` is a **literal list** or a ``{"$from": "step1.rows"}`` binding, and nothing
    else. Two refusals are deliberate and are enforced here rather than at 09:00:

    * **a string is not a list.** Python would happily iterate ``"EMEA"`` into four
      messages, one per character. A source that is text is a mistake with a loud symptom,
      so it is named as one.
    * **a literal longer than** :data:`~aughor.automations.dataflow.MAX_FAN_OUT` **is
      refused, never truncated.** These steps send messages; posting the first 50 of 500
      and dropping the rest silently is worse than refusing to post at all (`no silent
      caps` — say what was dropped, or do not drop).

    Each iteration publishes its item under the reserved alias ``item``: a dict item is
    read field-wise (``{"$from": "item.channel"}``), a scalar as ``{"$from": "item.value"}``.
    That is not new resolution machinery — the item is simply one more entry in the same
    accumulated context every binding already resolves against.
    """
    source: Any = None

    @model_validator(mode="after")
    def _check_source(self) -> "ForEach":
        from aughor.automations.dataflow import MAX_FAN_OUT, is_binding
        if is_binding(self.source):
            return self
        if isinstance(self.source, str) or not isinstance(self.source, list):
            raise ValueError(
                "for_each needs a list of items or a {\"$from\": \"step.key\"} binding — "
                f"got {type(self.source).__name__}"
                + (" (a string would run once per character)" if isinstance(self.source, str) else "")
            )
        if len(self.source) > MAX_FAN_OUT:
            raise ValueError(
                f"for_each over {len(self.source)} items exceeds the {MAX_FAN_OUT}-item cap; "
                "narrow the list rather than sending a truncated part of it"
            )
        return self


class Effect(BaseModel):
    """What to do when the conditions hold — a reference to an existing primitive.

    ``kinetic_action`` is the governed write: it runs through
    :func:`~aughor.actions.executor.execute_kinetic_action`, inheriting submission criteria,
    the graduated-approval gate and the audit trail unchanged. Wave A never bypasses it, which is
    why nothing above LOW risk can auto-fire from an automation either.

    ``monitor`` (Wave A5) runs an existing :class:`~aughor.monitors.models.Monitor`'s check and
    appends its alert — a faithful replay of the legacy monitor job, used when a monitor is *adopted*
    onto this engine. It is not authored by hand; it exists so a monitor can execute through the one
    engine instead of its own scheduler.

    ``agent_alert`` (VA-6) evaluates one :class:`~aughor.obs.agent_alerts.AgentAlertRule` and,
    when it crosses, records the alert and delivers it. Sibling of ``monitor`` in every way that
    matters — an adopted object running through the one engine rather than a loop of its own —
    and different only in its subject: a monitor watches a warehouse metric on a connection,
    a rule watches what the agents are doing, fleet-wide.

    ``subchain`` (DS-9) runs another automation as one step. The child runs as if someone
    pressed Run now — its own conditions are not re-asked, because a chain that INVOKES
    another is stating when it should happen, and a child whose trigger is "every Monday"
    would otherwise answer "not due" to every caller on every other day. The child keeps its
    own run row (it belongs in its own history) but emits its steps under the PARENT's trace,
    so one nested chain reads as one waterfall rather than two unrelated ones.

    ``investigate`` accepts an OPTIONAL ``agent_id`` (Wave H1) — the user-defined agent the
    scheduled run answers *as*. It is a parameter on an existing effect kind, not a new kind:
    the run still drains the one ask path, and the agent's instructions, document/pack scope
    and connection binding are applied by that path, not re-implemented here.
    """
    kind: Literal["investigate", "brief", "notify", "kinetic_action", "monitor", "agent_alert",
                  "slack_post", "subchain", "integration_call",
                  "metric_value", "trusted_query", "mcp_call"]
    #: VA-4a — this step's name, for `{"$from": "<alias>.<key>"}` references. Defaults to
    #: its 1-based position (`step1`, `step2`, …) so an existing automation gains
    #: referable steps without being rewritten.
    alias: str = ''
    #: W1 — run this step ONLY IF every (or any) clause holds against the accumulated
    #: chain context. Empty = always, which is every automation written before W1.
    #:
    #: The engine could only skip a step by ABSENCE before this — a binding that would
    #: not resolve — so "post it only if there is something worth posting" was not
    #: expressible, and a daily chain either sent an empty report or was not automated.
    #: Named `when` on the wire and **"Only if" on every surface**: the trigger node is
    #: already labelled "When" on the canvas, and two Whens on one picture is a name
    #: collision a reader pays for.
    when: list[GuardClause] = Field(default_factory=list)
    when_logic: Literal["all", "any"] = "all"
    #: W2 — run this step once per item of a list instead of exactly once. Absent = the
    #: single dispatch every automation written before W2 performs, byte for byte.
    #:
    #: The guard is evaluated PER ITEM (a fan-out whose guard were checked once would be
    #: an all-or-nothing filter, and "post the regions that moved" is the point), and each
    #: iteration appends its own `EffectOutcome`, so the run history shows what actually
    #: went out rather than one row standing for N sends.
    for_each: Optional[ForEach] = None
    #: DS-6 — the route: run this step exactly when the named step's ``when`` guard was
    #: evaluated and did NOT hold. Named **"Otherwise"** on every surface. Empty = the
    #: unrouted step every automation written before DS-6 is, byte for byte.
    #:
    #: A field naming a sibling rather than a branch construct wrapping the list, for
    #: this plane's standing reasons: it is structural (validated at save — the target
    #: must exist, run earlier, and carry a guard; never an expression), it DRAWS (one
    #: labelled edge from the deciding step), and the two arms are complementary BY
    #: CONSTRUCTION — two hand-written opposite guards can drift apart, one guard read
    #: from both sides cannot. The route reads only the guard's VERDICT, so it adds no
    #: second dataflow: a guard that was never evaluated (upstream missing, or a
    #: comparison that cannot be made) takes NEITHER arm — skipped, never guessed.
    else_of: str = ""
    config: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_config_keys(self) -> "Effect":
        missing = [k for k in _EFFECT_REQUIRED.get(self.kind, ()) if not self.config.get(k)]
        if missing:
            raise ValueError(
                f"effect kind '{self.kind}' requires config key(s): {', '.join(missing)}"
            )
        return self

    @property
    def action_id(self) -> str:
        return str(self.config.get("action_id", ""))

    @property
    def automation_id(self) -> str:
        """DS-9 — the chain a ``subchain`` step runs."""
        return str(self.config.get("automation_id", ""))

    @property
    def metric(self) -> str:
        """DS-12 — the governed metric a ``metric_value`` step reads."""
        return str(self.config.get("metric", ""))

    @property
    def query_id(self) -> str:
        """DS-12 — the vetted query a ``trusted_query`` step runs."""
        return str(self.config.get("query_id", ""))

    @property
    def agent_id(self) -> str:
        """The user-defined agent THIS STEP runs as ("" = inherit the automation's).

        Was documented as investigate-only, but the property always read `config` for any
        kind — the plumbing existed and nothing consumed it (VA-9b). A step may name its
        own agent to delegate one part of a chain; leaving it empty inherits, which is
        what makes an automation read as one agent's work rather than a bag of effects.

        Not in ``_EFFECT_REQUIRED``: an unbound step is still valid, so the absence of
        this key is the pre-H1 behaviour byte-for-byte.
        """
        return str(self.config.get("agent_id", ""))

    @property
    def params(self) -> dict:
        p = self.config.get("params")
        return dict(p) if isinstance(p, dict) else {}

    def target(self) -> str:
        """The referenced primitive, for run history and audit detail."""
        for key in ("action_id", "subscription_id", "trigger_id", "monitor_id", "rule_id",
                    "automation_id", "question"):
            if self.config.get(key):
                return str(self.config[key])[:200]
        return ""


# ── the automation ───────────────────────────────────────────────────────────────

class Automation(BaseModel):
    """A declared condition → effect binding, with a full lifecycle.

    Muting (``paused_until``) and expiry (``expires_at``) are checked BEFORE any condition is
    evaluated, so a muted automation costs nothing — it never reaches the warehouse. That ordering
    is asserted by a test, not just intended.
    """
    id: str = Field(default_factory=_new_id)
    conn_id: str = Field(description="Connection this automation runs against")
    name: str
    description: str = ""
    #: VA-9b — the UserAgent this automation OPERATES AS. "" = unattributed, which is
    #: every automation written before this field and stays byte-identical.
    #:
    #: This is what makes an automation an *agentic operation* rather than a cron with
    #: side effects. Measured before adding it: only `investigate` consulted an agent,
    #: `AutomationRun` recorded none, and the engine attributed every governed action to
    #: `automation:<id>` — a MECHANISM, not an actor with a charter, instructions,
    #: bound documents or an eval chip. An agent already carries all of those, and an
    #: `owner`, so naming one here connects the whole chain: person → agent →
    #: automation → connection. A step may still name its own agent to delegate; empty
    #: inherits this one.
    agent_id: str = ""

    conditions: list[Condition] = Field(min_length=1)
    condition_logic: Literal["all", "any"] = "all"
    effects: list[Effect] = Field(min_length=1)
    #: DS-7 — how the steps are scheduled. ``ordered`` = the strictly sequential walk
    #: every automation written before DS-7 performs, byte for byte. ``parallel`` =
    #: frontier scheduling: steps run as their ARROWS allow — a step waits for every
    #: step it references (params, guard, fan source, `else_of`) and for nothing else,
    #: so two independent investigations overlap.
    #:
    #: Per-AUTOMATION and opt-in, deliberately. The declared list is today a documented
    #: contract ("Then, in order" on every surface), and two steps with no data edge can
    #: still be order-sensitive in the world (two posts into one channel arrive in list
    #: order). Only the author knows; silently reordering every existing automation
    #: would be a semantics change nobody asked for.
    scheduling: Literal["ordered", "parallel"] = "ordered"
    fallback_effect: Optional[Effect] = Field(
        default=None,
        description="Runs only when EVERY declared effect failed after its retries — the "
                    "'tell someone the automation itself broke' escape hatch.",
    )

    enabled: bool = True
    #: DS-14 — may an external MCP client invoke this chain as a tool?
    #:
    #: OPT-IN, and default False on purpose. A deployment's automations are its private
    #: machinery; exposing every one of them because the MCP server happens to front the
    #: same API would be the opposite of the posture the rest of that server exists for.
    #: `enabled` is a separate question and both must hold — a chain someone deliberately
    #: switched off must not stay callable from outside, which would make the off switch a
    #: lie for exactly the caller nobody is watching.
    exposed_as_tool: bool = False
    paused_until: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC. While in the future the automation is muted: it does not "
                    "evaluate conditions and does not dispatch. Distinct from enabled=False, "
                    "which is indefinite.",
    )
    expires_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC after which the automation never fires again (an automation "
                    "created for a one-quarter migration should not outlive it).",
    )

    max_retries: int = Field(
        default=1,
        description="Per-effect retry attempts after the first failure. Default 1 — the #200 "
                    "lesson: every retry is itself another request against whatever refused it.",
        ge=0, le=5,
    )
    retry_backoff_seconds: float = Field(
        default=30.0,
        description="Base backoff; the engine jitters it so N automations failing together do "
                    "not retry in lockstep.",
        ge=0.0,
    )

    created_at: str = Field(default_factory=now_iso_z)
    updated_at: str = Field(default_factory=now_iso_z)
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None    # mirrors AutomationRun.outcome


# ── run history ──────────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_chain(self):
        """VA-4a — a chain that cannot run is refused here, not discovered on a schedule.

        Same rule the conditions and effects already follow (K1: reject at parse, never
        surface). An automation whose step 2 reads a step that does not exist, or reads a
        step that runs after it, is not schedulable — and looking schedulable is the
        expensive part.
        """
        from aughor.automations.dataflow import validate_chain
        problem = validate_chain(list(self.effects or []))
        if problem:
            raise ValueError(problem)
        return self

class EffectOutcome(BaseModel):
    """What happened to one effect on one tick."""
    kind: str
    target: str = ""
    status: Literal[
        "executed", "failed", "skipped",
        "criterion_failed", "approval_required", "invalid_params", "dispatch_error",
        # 4.1a — the send may or may not have landed. Distinct from "failed", which
        # asserts it did not: a webhook that times out AFTER the receiver has it is
        # reported as a failure by every layer below, and retrying that is how one
        # alert becomes two. Never retried; "failed" still is.
        "uncertain",
    ]
    message: str = ""      # authored criterion message / error, verbatim — never paraphrased
    attempts: int = 1
    #: VA-9b — the agent this step ran as ("" = unattributed). Recorded per STEP, not
    #: only per run, because a chain may delegate one part to a different agent and a
    #: run-level field could not say which step that was.
    agent_id: str = ""
    #: VA-4c — how long this step took, and when it began. The run carried a single
    #: `duration_ms` for the whole tick, which cannot answer "which step was slow" —
    #: the question a run canvas exists to answer. Measured around the dispatch, so it
    #: includes the retries a step actually spent.
    duration_ms: float = 0.0
    started_at: str = ""
    #: VA-4c — the investigation this step produced, when it produced one. An
    #: `investigate` step's TOKENS live on its investigation, not here; carrying the id
    #: is how a node links to its own spend without this model inventing a usage field
    #: it cannot fill for the other five effect kinds.
    investigation_id: str = ""
    #: W2 — which iteration of a fan-out this outcome is (1-based), and how many there
    #: were. Both 0 on an ordinary step, which is every outcome recorded before W2.
    #:
    #: Structured rather than folded into `message`, and the reason is a standing lesson
    #: of this module: `graph.py` decides a step was HELD by reading `message` against
    #: the `GUARD_SKIP` constant, so a "[2/3] " prefix would have made every guarded
    #: iteration read as an ordinary skip. A number a surface can render as "2 of 3"
    #: cannot go blind that way.
    fan_index: int = 0
    fan_count: int = 0
    #: VA-4a — what this effect PRODUCED, for later effects to consume. Every dispatcher
    #: already held this and discarded it here: the investigate runner had its run, the
    #: declared-action executor its dispatch result, `slack_post` the thread `ts` it was
    #: putting into a message string. A chain needs it structured, not narrated.
    data: dict = Field(default_factory=dict)


class AutomationRun(BaseModel):
    """One tick, always persisted — including the ticks that deliberately did nothing.

    ``outcome`` distinguishes the five cases the monitor store collapses into "no row":
    ``fired`` (conditions held, effects ran), ``not_fired`` (conditions evaluated, none held),
    ``gated`` (disabled / expired / paused — conditions never evaluated), ``error`` (the tick
    itself broke), and DS-8's ``paused`` (a step reached a governed write that needs a human,
    and the run is PARKED mid-chain waiting for one). ``reason`` carries the human sentence.

    DS-8 — ``paused`` is the first NON-TERMINAL outcome this model has ever had, and the
    distinction matters to every reader: a paused run is not a run that finished badly, it is
    a run that has not finished. It ends exactly once, when its proposal resolves — accepted
    (the chain continues in THIS row), rejected, or expired. `gated` is the near neighbour and
    is not the same thing: gated means the tick never started, paused means it started, did
    real work, and stopped in the middle of the chain with that work already committed.
    """
    id: str = Field(default_factory=_new_id)
    automation_id: str
    automation_name: str = ""
    conn_id: str = ""
    #: VA-9b — the agent this run operated as, so a run can say WHOSE work it was.
    agent_id: str = ""

    started_at: str = Field(default_factory=now_iso_z)
    finished_at: Optional[str] = None
    duration_ms: int = 0

    outcome: Literal["fired", "not_fired", "gated", "error", "paused"]
    reason: str = ""
    conditions_fired: list[str] = Field(default_factory=list)
    effects: list[EffectOutcome] = Field(default_factory=list)
    fallback_used: bool = False
    error: str = ""
    #: DS-8 — everything the chain needs to pick itself up where it stopped, and nothing
    #: else. The roadmap's definition is exact: *checkpoint = the persisted run + the
    #: accumulated context*. The run row already holds every prior step's outcome, so what
    #: has to be added is only what lives in engine LOCALS and would otherwise die with the
    #: tick — the accumulated chain context, the guard verdicts the route reads, and where
    #: to start again.
    #:
    #: Empty on every run that never paused, which is every run written before DS-8. Kept as
    #: an open dict rather than a model because it is engine-internal bookkeeping that no
    #: surface renders: giving it a public schema would invite a reader to depend on a shape
    #: the engine must stay free to change.
    #:
    #: Keys: ``next_index`` (resume the ordered walk here) · ``context`` / ``verdicts`` (the
    #: accumulated state, verbatim) · ``done_aliases`` (what the parallel frontier had already
    #: completed) · ``proposal_id`` · ``step_index`` / ``step_alias`` (which step parked).
    checkpoint: dict = Field(default_factory=dict)
