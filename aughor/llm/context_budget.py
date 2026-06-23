"""Capability-aware context budgeting — Layer A (PLATFORM_ARCHITECTURE.md §5b.3).

Aughor's prompts are already curated (schema-linking picks ~4 tables, results cap at 12
rows, schema/scan have char caps), so the headroom-style "massive compression" has a low
ceiling here — the relevance selection *is* the compression. The Layer-A win that actually
matters across heterogeneous BYO-model backends is **adaptation, not compression**: a payload
sized for a 131k window must be *trimmed to fit* when an operator binds a small-context local
model, or ADA overflows it and fails opaquely.

So this module derives the existing intake budgets from the bound model's ``max_context``
(via the capability seam) instead of a fixed guess — and only ever in the SAFE direction:
identical to today on a large window, tighter on a small one. Never looser (no token-cost or
grounding regression on the shipped binding), never silent (the caller's ``_trim`` already
marks truncation).
"""
from __future__ import annotations

# Mixed SQL/prose runs ~3.5 chars/token (the calibration the intake caps were written for);
# 4 chars/token is the conservative figure for *budget headroom* (over-estimate input).
_CHARS_PER_TOKEN = 3.5
_EST_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Conservative token estimate for budgeting when the backend can't be asked
    (``token_accounting == 'estimated'``). Over-estimates rather than under."""
    return max(1, int(len(text or "") / _EST_CHARS_PER_TOKEN))


def input_budget_tokens(max_context: int, *, reserve_output: int = 4096,
                        headroom: float = 0.85) -> int:
    """Tokens available for the whole *input* prompt: the window minus room for the
    completion, with headroom for estimation error. Floored so a tiny window still
    returns something workable."""
    return max(512, int((max(1024, int(max_context)) - reserve_output) * headroom))


def overflow_tokens(system: str, user: str, max_context: int, *,
                    reserve_output: int = 4096) -> tuple[int, int] | None:
    """If the assembled prompt would exceed the bound model's usable input window, return
    ``(estimated_input_tokens, budget_tokens)``; otherwise None. Used by the chokepoint to
    *warn* — never to truncate, since silently cutting evidence would risk grounding. The
    honest signal is "this binding is too small for this prompt; bind a larger-context one"."""
    est = estimate_tokens(system) + estimate_tokens(user)
    budget = input_budget_tokens(max_context, reserve_output=reserve_output)
    return (est, budget) if est > budget else None


def schema_scan_char_limits(max_context: int, *, default_schema: int = 20_000,
                            default_scan: int = 6_000) -> tuple[int, int]:
    """The (schema, scan) char caps for ADA intake, sized to the bound model.

    Policy — safe direction only:
      • large window  → return the defaults unchanged (byte-identical to today;
        no token or grounding regression on the shipped binding);
      • small window  → scale both down proportionally (keeping the 20k:6k ratio),
        floored, so the curated payload fits instead of overflowing.

    schema+scan may claim at most ~half the input budget (the prompt also carries rules,
    the question, ledger and per-phase results)."""
    default_pair = default_schema + default_scan
    pair_char_cap = int(input_budget_tokens(max_context) * 0.5 * _CHARS_PER_TOKEN)
    if pair_char_cap >= default_pair:
        return default_schema, default_scan                 # large window → unchanged
    scale = pair_char_cap / default_pair
    return (max(2_000, int(default_schema * scale)),
            max(800, int(default_scan * scale)))            # small window → fit, with floors
