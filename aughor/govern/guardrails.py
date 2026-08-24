"""VA-8 — per-agent guardrails: a policy, an enforcement point, and a record of both.

**What was already here, and what was not.** Three of the four things VA-8 named exist
and work: schema scope is a governing field on the agent and `_apply_agent_bindings`
fails an ask CLOSED with a 409 when it conflicts; per-run token/time budgets exist in
`kernel.metering` and are enforced at three points inside the LLM funnel; PII scanning
and redaction exist in `security.pii` and run on every non-internal query result. What
did not exist was any way to configure ANY of it per agent, and — the part VA-6 needs —
any record that a guardrail had been evaluated at all. An alert on block rate had nothing
to count.

**Why the cap is in tokens and not dollars.** VA-8 said "cost caps". A cost cap can only
be enforced after a call is priced, which is after it has been paid for: a USD ceiling
could stop the NEXT run, never this one. Tokens are what the pre-spend gate can actually
see, so that is the unit here, and the alert plane keeps `cost_usd` for the after-the-fact
question it is good at. Naming it `max_tokens_per_run` rather than a "cost cap" that
cannot cap cost is the whole of the difference.

**Why `redact` is the default.** It is what the platform does today for every result, so
an agent with no policy behaves exactly as it did before this module existed. `off` and
`block` are the two new choices, and `block` is the one an operator reaches for when a
result containing PII should not be shown at all rather than shown with holes in it.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Literal, Optional

_LOG = logging.getLogger(__name__)

#: The kinds a policy can express. Closed on purpose — a reader should be able to hold
#: the list in their head, and an operator should never configure a guardrail that
#: nothing enforces.
GuardrailKind = Literal["pii", "tokens"]
PiiMode = Literal["off", "redact", "block"]
PII_MODES: tuple[str, ...] = ("off", "redact", "block")

#: One kv store in the ledger rather than a column on `user_agents`. A guardrail is an
#: operator's decision ABOUT an agent, not part of the configuration whose changes the
#: revision plane versions and whose identity the eval chip cites — putting it in
#: GOVERNING_FIELDS would mark every eval stale the moment somebody tightened a cap.
KV_STORE = "agent_guardrails"

#: The event kind guardrail verdicts are recorded under.
EVENT_KIND = "guardrail"


@dataclass
class GuardrailPolicy:
    """What an operator has decided about one agent. Defaults reproduce today's behaviour."""

    pii: PiiMode = "redact"
    max_tokens_per_run: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "GuardrailPolicy":
        """Tolerant by construction: a policy read from storage must never be able to
        break the run it governs. An unknown pii mode falls back to the default rather
        than raising — a typo in one agent's policy is not a reason to stop answering."""
        if not isinstance(raw, dict):
            return cls()
        pii = raw.get("pii")
        if pii not in PII_MODES:
            pii = "redact"
        cap = raw.get("max_tokens_per_run")
        try:
            cap = int(cap) if cap is not None else None
        except (TypeError, ValueError):
            cap = None
        if cap is not None and cap <= 0:
            cap = None                      # a cap of zero is not a cap, it is an outage
        return cls(pii=pii, max_tokens_per_run=cap)

    @property
    def is_default(self) -> bool:
        return self == GuardrailPolicy()


def policy_for(agent_id: str) -> GuardrailPolicy:
    """The policy governing one agent — the default when none is set. Never raises."""
    if not agent_id:
        return GuardrailPolicy()
    try:
        from aughor.kernel.ledger import Ledger
        return GuardrailPolicy.from_dict(Ledger.default().kv_get(KV_STORE, agent_id))
    except Exception as exc:                # noqa: BLE001 — a guardrail read must not break a run
        _LOG.warning("guardrail policy unreadable for %s: %s — using defaults", agent_id, exc)
        return GuardrailPolicy()


def set_policy(agent_id: str, policy: GuardrailPolicy) -> None:
    """Store one agent's policy. A policy identical to the default is DELETED rather than
    written, so "unset" and "explicitly set to the defaults" cannot drift apart."""
    from aughor.kernel.ledger import Ledger
    ledger = Ledger.default()
    if policy.is_default:
        ledger.kv_delete(KV_STORE, agent_id)
        return
    ledger.kv_put(KV_STORE, agent_id, policy.to_dict())


def all_policies() -> dict:
    try:
        from aughor.kernel.ledger import Ledger
        return {k: GuardrailPolicy.from_dict(v)
                for k, v in (Ledger.default().kv_load_all(KV_STORE) or {}).items()}
    except Exception:                       # noqa: BLE001
        return {}


def active_policy() -> tuple[str, GuardrailPolicy]:
    """``(agent_id, policy)`` for the agent running right now.

    ``("", default)`` when no agent is active — the seam is inert on the default path,
    which is the same shape every other agent-scoped read in this codebase takes.
    """
    try:
        from aughor.custom_agents.context import current_agent
        agent = current_agent()
    except Exception:                       # noqa: BLE001
        agent = None
    if agent is None:
        return "", GuardrailPolicy()
    return agent.id, policy_for(agent.id)


def record(kind: str, *, blocked: bool, detail: str = "", agent_id: str = "",
           observed: Optional[dict] = None) -> None:
    """Record that a guardrail was EVALUATED — allowed as well as blocked.

    Both halves are written because the question VA-6 asks is a rate, and a rate whose
    denominator is missing is a count wearing a percent sign. Recording only blocks would
    make an agent that was never checked indistinguishable from one that always passed.

    Best-effort: a guardrail that cannot be recorded still has to be enforced.
    """
    try:
        from aughor.obs import session_log
        session_log.emit(
            EVENT_KIND,
            name=kind,
            ok=not blocked,
            payload={"guardrail": kind, "blocked": blocked, "detail": detail,
                     "agent_id": agent_id, **(observed or {})},
        )
    except Exception as exc:                # noqa: BLE001
        _LOG.debug("guardrail verdict not recorded (%s): %s", kind, exc)


def arm_run_cap(policy: GuardrailPolicy):
    """Arm this agent's per-run token cap on the existing metering budget, or None.

    Enforcement is not new: `kernel.metering.check_budget` is already called at three
    points inside the LLM funnel and raises before the spend. What is new is that an
    agent can carry its own ceiling into a run.

    Where a budget is already armed, the SMALLER token ceiling wins. Two budgets on one
    run are statements about different things — what this run may spend, and what this
    agent may ever spend — and both hold, so the binding one is whichever is breached
    first. `govern.usage_caps` reasons the same way about caps across scopes, and getting
    it backwards here would let an agent's generous cap raise a run's tight one.
    """
    if policy.max_tokens_per_run is None:
        return None
    from aughor.kernel import metering
    tokens = policy.max_tokens_per_run
    time_s = None
    existing = metering.current_budget()
    if existing is not None:
        existing_tokens, time_s = existing
        if existing_tokens:
            tokens = min(int(existing_tokens), tokens)
    return metering.set_budget(tokens, time_s)


def disarm_run_cap(token) -> None:
    if token is None:
        return
    from aughor.kernel import metering
    metering.clear_budget(token)
