"""Per-run answer receipts — make the machinery's per-answer work visible (the S3 receipts family).

Hosts two sibling, flag-gated receipts built from the shared run accumulator (``kernel/metering.py``):
the **Learning Receipt** (Wave 1 · E4, below) and the **Activation Receipt** (Wave 1 · E3,
``build_activation_receipt`` — which self-gating guards fired this run and why).

Learning Receipt (Wave 1 · E4) — make the closed loop's per-answer work visible.

Aughor's closed loop is captured and read back into prompts, but per answer the only visible learning
signal was the single ``◆ resolved reading`` badge. This builds a compact summary of what the loop DID on
one run, combining two sources:

  * **receipt-time read-backs** — the ambiguity resolutions THIS question matched (already computed by the
    Trust-Receipt writer via ``retrieve_resolutions``): readings reused, and how many were *corrections*
    (settled by a user/reviewer, not a probe);
  * **runtime events** — the ``LearningSignals`` the run accumulated (``kernel/metering.py``):
    resolutions crystallized, trusted plan-as-programs replayed.

Flag-gated (``learning.receipt``, default-off → returns ``None`` → no receipt section, no SSE event, output
byte-identical). Returns ``None`` when nothing happened, so an all-zero receipt never adds noise.
"""
from __future__ import annotations

from typing import Optional

# Resolution sources that represent a human CORRECTION (override-wins), vs an autonomous probe.
_CORRECTION_SOURCES = frozenset({"user", "verdict"})


def build_learning_receipt(resolved_ambig: Optional[list[dict]] = None) -> Optional[dict]:
    """A per-run learning summary, or ``None`` when the flag is off or nothing happened.

    ``resolved_ambig`` is the Trust-Receipt writer's list of ``{subject, reading, source}`` for the
    resolutions this question matched; pass it so the two receipts agree (single source of truth)."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("learning.receipt"):
        return None

    ra = resolved_ambig or []
    by_source: dict[str, int] = {}
    for r in ra:
        src = r.get("source") or "?"
        by_source[src] = by_source.get(src, 0) + 1

    from aughor.kernel import metering
    snap = metering.learning_snapshot() or {}

    receipt = {
        "readings_reused": len(ra),
        "corrections_applied": sum(1 for r in ra if r.get("source") in _CORRECTION_SOURCES),
        "by_source": by_source,
        "resolutions_crystallized": int(snap.get("resolutions_crystallized", 0) or 0),
        "trusted_program_replayed": int(snap.get("trusted_program_replayed", 0) or 0),
    }
    # An all-zero receipt is noise — only surface when the loop actually did something this run.
    if not any(receipt[k] for k in receipt if k != "by_source"):
        return None
    return receipt


def build_activation_receipt() -> Optional[list]:
    """The self-gating guards that fired this run, each with the deterministic trigger that fired it (the
    Activation Receipt, Wave 1 · E3) — or ``None`` when the ``capabilities.receipt`` flag is off or nothing
    fired. Entries are ``{capability, reason, count}``, deduped by capability (a guard may fire several times
    a run) in first-fired order. The 'why' is centralized in ``flags.CAPABILITY_TRIGGER`` so touchpoints
    only record the capability name."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("capabilities.receipt"):
        return None
    from aughor.kernel import metering
    fired = metering.activations_snapshot() or []
    if not fired:
        return None
    from aughor.kernel.flags import CAPABILITY_TRIGGER
    counts: dict[str, int] = {}
    for cap in fired:
        counts[cap] = counts.get(cap, 0) + 1
    return [{"capability": cap, "reason": CAPABILITY_TRIGGER.get(cap, ""), "count": n}
            for cap, n in counts.items()]
