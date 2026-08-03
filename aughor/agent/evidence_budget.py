"""Duplicate-collapse evidence rendering (Wave R3) — pay each blob's context cost once.

One policy, **lossless by construction**: a result whose SQL exactly repeats an earlier
one in the same block renders as a one-line pointer, because the identical table is
already present. Nothing the narrator could cite disappears.

(The stale-stub sibling — rendering an already-scored result as a row-capped stub — was
DELETED 2026-08-01 in the flag endgame: it dropped rows the model could have read, the
exact opposite of the evidence-budget direction, and its quality effect was never
measured.)

Safe direction only, as in :mod:`aughor.agent.schema_focus`: below :data:`MIN_BLOCK_CHARS`
the block is returned untouched.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

#: Below this, render everything in full — a block this size is not straining anything,
#: and trimming it could only lose ground.
#:
#: Sized against a real run, not picked as a round number: a 5–7 hypothesis investigation
#: with 2–3 queries each renders roughly 12–20k characters here. A threshold above that
#: band would be a policy that never fires — which reads as "shipped" while doing nothing,
#: the exact failure the flag-graduation audit found 19 of. 12k matches
#: :data:`aughor.agent.schema_focus.FOCUS_MIN_CHARS` so the two Wave-R3 trims engage at
#: the same scale rather than at two unrelated magic numbers.
MIN_BLOCK_CHARS = 12_000


def _fingerprint(result: Any) -> str:
    from aughor.agent.wandering import args_fingerprint

    return args_fingerprint(getattr(result, "sql", "") or "")


def duplicate_pointer(result: Any, prior_step: str) -> str:
    """The one-line form of a result whose identical table is already in this block."""
    return (f"SQL: {getattr(result, 'sql', '')}\n"
            f"[identical to the query already shown for {prior_step} — see that result; "
            f"it is not repeated here]")


def render_history(
    results: Iterable[Any],
    *,
    full_renderer: Callable[[Any], str],
    collapse_duplicates: bool = True,
    seen: Optional[dict] = None,
) -> tuple[list[str], dict]:
    """Render each result, collapsing exact-repeat queries. Returns ``(parts, info)``.

    ``seen`` is the caller's fingerprint accumulator, and passing it is what makes
    duplicate-collapse work at all when the block is assembled in pieces: the synthesis
    prompt renders one section per hypothesis, so a purely local ``seen`` resets between
    sections and catches only same-section repeats — the rarest kind. Mutated in place.

    ``info`` reports ``{"full": n, "duplicates": n}`` so the effect is a number rather
    than a claim.
    """
    parts: list[str] = []
    info = {"full": 0, "duplicates": 0}
    seen = {} if seen is None else seen

    for r in results:
        step = getattr(r, "hypothesis_id", "") or ""
        fp = _fingerprint(r) if collapse_duplicates else ""
        if fp and fp in seen and not getattr(r, "error", None):
            parts.append(duplicate_pointer(r, seen[fp]))
            info["duplicates"] += 1
            continue
        if fp:
            seen[fp] = step or "an earlier step"
        parts.append(full_renderer(r))
        info["full"] += 1
    return parts, info
