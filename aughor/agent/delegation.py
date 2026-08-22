"""VA-2 — the delegation spine: who may hand work to whom, and when it must stop.

The user chose **unbounded depth**: any agent may delegate to any agent, and a delegate
may itself delegate. That is the most capable topology available, and it moves the entire
safety burden out of the shape of the graph and into the runtime — which is what this
module is. There is no arrangement of agents this refuses; there are only *runs* it stops.

Four stops, and each exists because an unbounded tree fails in a different way:

1. **Cycles.** A→B→A is not hypothetical once any agent may target any agent; two agents
   whose purposes overlap will find each other. `agent_path` is the authority, and a
   repeat is a *typed refusal the model can read*, never a silent drop — an agent that
   cannot see why its delegation failed will simply try again.
2. **Steps, counted per RUN and not per level.** The obvious bound —
   `10 x len(targets)`, the reference implementation's — is per supervisor. Compose it
   down three levels and the ceiling multiplies into the thousands while every individual
   level still looks well behaved. The only number that means anything is the whole run's.
3. **Cost.** A delegation tree is the one shape in this product that can spend without
   bound, because every hop is a full turn with its own context. The cap ends the run with
   a stated partial result; "unknown is never zero" applies to spend as much as to data.
4. **Wall clock.** A tree that neither cycles nor overspends can still simply not finish.

`max_depth` is deliberately generous and configurable: it is a **runaway backstop**, not a
design limit. If it fires it means something is wrong, and it says so in those terms.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class DelegationLimits:
    """What one run may spend before delegation stops. All four are backstops."""

    #: Total model steps across the WHOLE run — every agent, every level.
    max_run_steps: int = 60
    #: Runaway backstop, not a topology limit. Reaching it means a loop we failed to see.
    max_depth: int = 8
    #: Wall clock for the whole tree.
    deadline_s: float = 300.0
    #: USD across the run; None = governed only by `govern.usage_caps`.
    max_cost_usd: Optional[float] = None


class DelegationRefused(Exception):
    """A delegation the runtime will not perform. Carries a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_result(self, agent_name: str = "") -> dict:
        """The shape `delegate_task` returns for a refusal.

        A refusal is a RESULT, not an exception, by the time the model sees it: the model
        must be able to read why and choose differently. Raising here would strand the
        supervisor mid-turn with nothing to reason about.
        """
        return {"agent_name": agent_name, "response": self.message,
                "usage": {}, "bailed": False, "refused": True, "code": self.code}


@dataclass
class DelegationContext:
    """One run's delegation state. Created at the top turn, threaded down every hop."""

    limits: DelegationLimits = field(default_factory=DelegationLimits)
    #: Agent ids from the root to the caller, in order. The cycle authority.
    agent_path: tuple[str, ...] = ()
    steps_used: int = 0
    cost_usd: float = 0.0
    started_at: float = field(default_factory=time.monotonic)

    @property
    def depth(self) -> int:
        return len(self.agent_path)

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def child(self, agent_id: str) -> "DelegationContext":
        """The context a delegate runs under. Budgets are SHARED, not per-agent.

        The child holds a reference to the same counters by construction (it is the same
        object's fields copied forward and written back through `spend`), because a
        per-agent budget is exactly how an unbounded tree escapes a run-level ceiling.
        """
        return DelegationContext(
            limits=self.limits,
            agent_path=self.agent_path + (agent_id,),
            steps_used=self.steps_used,
            cost_usd=self.cost_usd,
            started_at=self.started_at,
        )

    def spend(self, *, steps: int = 0, usd: float = 0.0) -> None:
        self.steps_used += max(0, int(steps))
        self.cost_usd += max(0.0, float(usd))

    # ── the four stops ────────────────────────────────────────────────────────────

    def check(self, target_id: str, *, known_ids: Optional[set[str]] = None) -> None:
        """Raise `DelegationRefused` if this hop must not happen.

        Order matters: identity errors first (they are the user's mistake and the cheapest
        to explain), then the run-wide budgets (which are ours), so a message never blames
        a budget for what was really a typo.
        """
        if known_ids is not None and target_id not in known_ids:
            raise DelegationRefused(
                "UNKNOWN_TARGET",
                f"No agent '{target_id}' is available to delegate to.")

        if target_id in self.agent_path:
            loop = " -> ".join(self.agent_path + (target_id,))
            raise DelegationRefused(
                "DELEGATION_CYCLE",
                f"Refusing a delegation cycle ({loop}). This agent is already working on "
                f"this run. Answer with what you have, or delegate to a different agent.")

        if self.depth >= self.limits.max_depth:
            raise DelegationRefused(
                "MAX_DEPTH",
                f"Delegation is {self.depth} levels deep, which is the runaway backstop "
                f"({self.limits.max_depth}). Something is looping without repeating an "
                f"agent. Answer with what you have.")

        if self.steps_used >= self.limits.max_run_steps:
            raise DelegationRefused(
                "RUN_STEP_BUDGET",
                f"This run has used its {self.limits.max_run_steps} model steps across all "
                f"agents. Answer with what you have — say what you could not check.")

        if self.elapsed_s() >= self.limits.deadline_s:
            raise DelegationRefused(
                "RUN_DEADLINE",
                f"This run passed its {self.limits.deadline_s:.0f}s budget. Answer with "
                f"what you have — say what you could not check.")

        cap = self.limits.max_cost_usd
        if cap is not None and self.cost_usd >= cap:
            raise DelegationRefused(
                "RUN_COST_CAP",
                f"This run reached its ${cap:.2f} budget (spent ${self.cost_usd:.2f}). "
                f"Answer with what you have, and say the answer is partial.")

    def span_attributes(self) -> dict:
        """What every delegated hop stamps on its span, so VA-5 can draw the tree and
        VA-6 can alert on runaway depth."""
        return {
            "aughor.delegation.depth": self.depth,
            "aughor.delegation.path": "/".join(self.agent_path),
            "aughor.delegation.steps_used": self.steps_used,
            "aughor.delegation.cost_usd": round(self.cost_usd, 6),
        }
