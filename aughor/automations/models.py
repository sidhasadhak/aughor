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
from typing import Literal, Optional

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
}


class Condition(BaseModel):
    """One precondition on an automation firing. Combinable via ``Automation.condition_logic``.

    ``schedule`` is a cron expression — the *only* condition monitors and briefs have today.
    ``metric`` delegates to an existing :class:`~aughor.monitors.models.Monitor` (by id) so the six
    already-tested alert conditions become available to any effect, not just to an alert.
    ``source_change`` fires when a table's cheap source version advanced (A3). ``entity_appears``
    fires when a new key shows up in a table.
    """
    kind: Literal["schedule", "metric", "source_change", "entity_appears"]
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
        return f"{self.kind}({self.table})"


# ── effects ──────────────────────────────────────────────────────────────────────

#: Required ``config`` keys per effect kind. Validated at construction.
_EFFECT_REQUIRED: dict[str, tuple[str, ...]] = {
    "investigate":    ("question",),
    "brief":          ("subscription_id",),
    "notify":         ("trigger_id",),
    "kinetic_action": ("action_id",),
}


class Effect(BaseModel):
    """What to do when the conditions hold — a reference to an existing primitive.

    ``kinetic_action`` is the governed write: it runs through
    :func:`~aughor.kinetic.executor.execute_kinetic_action`, inheriting submission criteria,
    the graduated-approval gate and the audit trail unchanged. Wave A never bypasses it, which is
    why nothing above LOW risk can auto-fire from an automation either.
    """
    kind: Literal["investigate", "brief", "notify", "kinetic_action"]
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
    def params(self) -> dict:
        p = self.config.get("params")
        return dict(p) if isinstance(p, dict) else {}

    def target(self) -> str:
        """The referenced primitive, for run history and audit detail."""
        for key in ("action_id", "subscription_id", "trigger_id", "question"):
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

    conditions: list[Condition] = Field(min_length=1)
    condition_logic: Literal["all", "any"] = "all"
    effects: list[Effect] = Field(min_length=1)
    fallback_effect: Optional[Effect] = Field(
        default=None,
        description="Runs only when EVERY declared effect failed after its retries — the "
                    "'tell someone the automation itself broke' escape hatch.",
    )

    enabled: bool = True
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

class EffectOutcome(BaseModel):
    """What happened to one effect on one tick."""
    kind: str
    target: str = ""
    status: Literal[
        "executed", "failed", "skipped",
        "criterion_failed", "approval_required", "invalid_params", "dispatch_error",
    ]
    message: str = ""      # authored criterion message / error, verbatim — never paraphrased
    attempts: int = 1


class AutomationRun(BaseModel):
    """One tick, always persisted — including the ticks that deliberately did nothing.

    ``outcome`` distinguishes the four cases the monitor store collapses into "no row":
    ``fired`` (conditions held, effects ran), ``not_fired`` (conditions evaluated, none held),
    ``gated`` (disabled / expired / paused — conditions never evaluated), ``error`` (the tick
    itself broke). ``reason`` carries the human sentence.
    """
    id: str = Field(default_factory=_new_id)
    automation_id: str
    automation_name: str = ""
    conn_id: str = ""

    started_at: str = Field(default_factory=now_iso_z)
    finished_at: Optional[str] = None
    duration_ms: int = 0

    outcome: Literal["fired", "not_fired", "gated", "error"]
    reason: str = ""
    conditions_fired: list[str] = Field(default_factory=list)
    effects: list[EffectOutcome] = Field(default_factory=list)
    fallback_used: bool = False
    error: str = ""
