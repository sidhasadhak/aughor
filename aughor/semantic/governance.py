"""B-8 — metric governance lifecycle: draft → proposed → approved (→ deprecated),
with an auditable record for every transition.

A governed metric is an organisational artifact, not free-text config. This module is
the single source of truth for the state machine and the audit record each transition
produces; the router persists the updated metric and journals the audit event to the
Ledger — so "who approved revenue, and when" becomes a query, not an archaeology dig.

Pure + deterministic (time is injected) so the whole machine is unit-testable without
a clock, a DB, or the LLM.
"""
from __future__ import annotations

STATES: tuple[str, ...] = ("draft", "proposed", "approved", "deprecated")

# action → (states it is allowed FROM, resulting state)
TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "propose":   (("draft", "deprecated"), "proposed"),
    "approve":   (("proposed",),           "approved"),
    "reject":    (("proposed",),           "draft"),
    "deprecate": (("approved",),           "deprecated"),
}


def can_transition(status: str | None, action: str) -> bool:
    """Is `action` legal from `status`? (status None ⇒ 'draft')."""
    t = TRANSITIONS.get(action)
    return bool(t) and (status or "draft") in t[0]


def apply_transition(metric: dict, action: str, actor: str, now: str) -> tuple[dict, dict]:
    """Apply a governance `action` to a metric dict. Returns ``(updated_metric, audit)``.

    Raises ``ValueError`` on an unknown action, an illegal transition for the current
    state, or a blank actor. Pure: the caller persists the metric and journals the
    audit record — this never touches disk or the clock (``now`` is injected).

    `approve` stamps ``approved_by``/``approved_at`` and bumps ``version`` (so each
    approved revision is numbered); `propose` stamps ``proposed_by``/``proposed_at``."""
    t = TRANSITIONS.get(action)
    if not t:
        raise ValueError(
            f"unknown governance action '{action}' (expected one of {sorted(TRANSITIONS)})"
        )
    if not (actor or "").strip():
        raise ValueError("an actor is required for a governance transition")
    allowed_from, to = t
    cur = metric.get("status") or "draft"
    if cur not in allowed_from:
        raise ValueError(
            f"cannot '{action}' a metric in state '{cur}' (allowed from {list(allowed_from)})"
        )

    m = dict(metric)
    m["status"] = to
    if action == "propose":
        m["proposed_by"], m["proposed_at"] = actor, now
    elif action == "approve":
        m["approved_by"], m["approved_at"] = actor, now
        m["version"] = int(metric.get("version") or 0) + 1
    audit = {
        "metric": metric.get("name"),
        "action": action,
        "actor": actor,
        "from": cur,
        "to": to,
        "version": m.get("version", metric.get("version", 1)),
        "at": now,
    }
    return m, audit
