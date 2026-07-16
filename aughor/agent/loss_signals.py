"""Loss-signal directive — a "losing money" question must scan LOSS signals.

The live A/B that motivated this (2026-07-16, the airline workspace): the intake
honestly noted "no cost data — don't fabricate a margin verdict", then reduced the
question to a NET-REVENUE RANKING — a lens structurally incapable of finding losses
(segment revenue is never negative) — and the report concluded "broadly healthy, no
segment showing losses". The same data answered differently when the loss lenses ran:
refunds leaked 2.38M CHF (2.77% of gross, 100% voluntary cancellations, concentrated
in first class and corporate), and long-haul flew 77.7% full vs the short-haul 79.4%
benchmark — ~1,135 empty seats ≈ 1.18M CHF.

This module is the deterministic fix: detect loss INTENT in the question, scan the
schema text for the loss SIGNALS the data actually carries (contra-revenue columns,
capacity columns), and emit a directive block for the intake prompt that (a) names
the signals, (b) demands the leakage/utilization lenses when they exist, and (c)
forbids the profitability verdict that profit-less data cannot support. No model in
the detector; flag-gated at the caller (``intake.loss_signals``)."""
from __future__ import annotations

import re

# "Losing money" and its siblings — the intents a revenue ranking cannot answer.
LOSS_INTENT_RE = re.compile(
    r"(lo(?:s|z)ing money|lose money|losses?\b|leak(?:age|ing)?\b|bleed|drain"
    r"|wast(?:e|ing)\b|unprofitab|underperform|margin (?:erosion|pressure|squeeze)"
    r"|cost overrun|money (?:pit|sink))", re.I)

# Contra-revenue: money that walks back out. Word-token scan over the schema text.
CONTRA_REVENUE_RE = re.compile(
    r"\b([a-z0-9_]*(?:refund|chargeback|discount|rebate|writeoff|write_off"
    r"|cancellation_fee|credit_note|clawback|penalt)[a-z0-9_]*)\b", re.I)

# Capacity/utilization: paid units vs available units.
CAPACITY_RE = re.compile(
    r"\b([a-z0-9_]*(?:total_seats|capacity|occupancy|utilization|utilisation"
    r"|load_factor|slots_available)[a-z0-9_]*)\b", re.I)


def detect_loss_signals(question: str, schema_text: str) -> dict | None:
    """The loss signals THIS schema carries, or None when the question isn't a loss
    question / the schema carries none. Pure text scan — deterministic, no model."""
    if not LOSS_INTENT_RE.search(question or ""):
        return None
    contra = sorted({m.group(1).lower() for m in CONTRA_REVENUE_RE.finditer(schema_text or "")})
    capacity = sorted({m.group(1).lower() for m in CAPACITY_RE.finditer(schema_text or "")})
    if not contra and not capacity:
        return None
    return {"contra_revenue": contra[:12], "capacity": capacity[:8]}


def loss_signal_directive(question: str, schema_text: str) -> str:
    """The intake-prompt directive, or '' when it doesn't apply (safe to prepend
    unconditionally). Kept to facts the detector verified — the block never claims
    signals that aren't in the schema."""
    sig = detect_loss_signals(question, schema_text)
    if not sig:
        return ""
    lines = ["LOSS-SIGNAL DIRECTIVE (deterministic scan of THIS schema — these columns exist):"]
    if sig["contra_revenue"]:
        lines.append(f"  Contra-revenue signals: {', '.join(sig['contra_revenue'])}.")
    if sig["capacity"]:
        lines.append(f"  Capacity/utilization signals: {', '.join(sig['capacity'])}.")
    lines.append(
        "  A 'losing money' question is NOT a revenue ranking — segment revenue is never "
        "negative, so a revenue ranking can only ever conclude 'no losses'. Frame the "
        "metric around the STRONGEST loss signal instead: "
        "(1) LEAKAGE — the contra-revenue amount as a RATE of gross per segment (which "
        "segment leaks fastest, not which is biggest); "
        "(2) UTILIZATION — sold units vs capacity per segment, and the gap to the best "
        "segment as units × revenue-per-unit, when capacity columns exist; "
        "(3) the below-benchmark revenue ranking is CONTEXT, never the whole answer. "
        "HONESTY: without cost data profit is NOT computable — never conclude segments are "
        "'profitable' or that there are 'no losses'; quantify leakage and utilization "
        "opportunity, or state plainly that only revenue was measurable.")
    return "\n".join(lines) + "\n"
