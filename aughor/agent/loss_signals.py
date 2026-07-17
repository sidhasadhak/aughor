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


# Which loss CLASS a metric already covers — used to decide which forward-chained
# lens phases a run still owes after the intake picked its primary metric.
LEAKAGE_METRIC_RE = re.compile(
    r"refund|chargeback|discount|rebate|leakage|writeoff|write_off|clawback|penalt", re.I)
UTILIZATION_METRIC_RE = re.compile(
    r"load[ _-]?factor|utili[sz]ation|occupancy|capacity|fill[ _-]?rate|seats?\b", re.I)


def lens_specs(sig: dict | None, primary_metric_blob: str) -> list[dict]:
    """The forward-chained LOSS phases this run still owes. One investigation carries
    ONE primary metric — the live A/B showed the intake (correctly) picking utilization
    and the leakage story going untold. Every detected signal class the primary metric
    does NOT cover gets a phase spec: deterministic prompts seeded with the columns the
    detector actually found. Empty when nothing is owed."""
    sig = sig or {}
    blob = primary_metric_blob or ""
    specs: list[dict] = []
    if sig.get("contra_revenue") and not LEAKAGE_METRIC_RE.search(blob):
        cols = ", ".join(sig["contra_revenue"])
        specs.append({
            "kind": "leakage",
            "phase_id": "loss_leakage",
            "title": "Revenue Leakage — Where Money Walks Back Out",
            "emoji": "💸",
            "fprefix": "leakage",
            "metric_label": "leakage rate",
            "counter": "ada.loss_leakage_lens",
            "plan_system": (
                "You are planning a revenue-LEAKAGE scan: money that walks back out "
                "(refunds, chargebacks, discounts). Plan AT MOST 2 queries. "
                "(1) The leakage RATE by the single most decision-relevant segment: for each "
                "segment value, 100.0 * SUM(<contra amount>) / NULLIF(SUM(<gross amount>), 0) "
                "AS metric_total, plus COUNT(*) AS n. Aggregate the contra side and the gross "
                "side EACH AT ITS OWN GRAIN before combining (ratio of sums — never AVG of "
                "per-row ratios, and never a join that duplicates either side). ORDER BY "
                "metric_total DESC (the fastest leak first). Return exactly three columns: "
                "the segment, metric_total, n. "
                "(2) The overall picture: total contra-revenue and 100.0 * SUM(contra) / "
                "NULLIF(SUM(gross), 0) AS metric_total, with the contra reason/category as the "
                "segment when one exists. Do NOT plan a plain revenue ranking."),
            "plan_ask": (
                "Where does contra-revenue leak fastest — which segments have the highest "
                "leakage RATE (contra as a share of gross), and what is the total? "
                f"CONTRA-REVENUE COLUMNS PRESENT: {cols}."),
            "interpret_system": (
                "Interpret a revenue-leakage scan. Lead with the TOTAL leaked and its share of "
                "gross, then where the leakage RATE concentrates (segments above the overall "
                "rate) and the dominant reason if present. These are contra-revenue rates, not "
                "profit — never claim segments are 'profitable' or that there are 'no losses'."),
        })
    if sig.get("capacity") and not UTILIZATION_METRIC_RE.search(blob):
        cols = ", ".join(sig["capacity"])
        specs.append({
            "kind": "utilization",
            "phase_id": "loss_utilization",
            "title": "Capacity Utilization — Paid vs Available",
            "emoji": "🪑",
            "fprefix": "utilization",
            "metric_label": "utilization",
            "counter": "ada.loss_utilization_lens",
            "plan_system": (
                "You are planning a capacity-UTILIZATION scan: paid units against available "
                "capacity. Plan AT MOST 2 queries. "
                "(1) Utilization by the most decision-relevant segment: for each segment value, "
                "100.0 * SUM(<units sold>) / NULLIF(SUM(<capacity>), 0) AS metric_total, plus "
                "the capacity as n. COUNT CAPACITY EXACTLY ONCE per carrier unit (per flight / "
                "slot / store) — joining capacity through a per-sale table multiplies it and "
                "corrupts the rate; aggregate each side at its own grain, then combine. ORDER "
                "BY metric_total ASC (the emptiest first). Return exactly three columns: the "
                "segment, metric_total, n. "
                "(2) The overall utilization as one row for context."),
            "plan_ask": (
                "Which segments run the lowest utilization (paid units vs available capacity), "
                "and what is the overall level? "
                f"CAPACITY COLUMNS PRESENT: {cols}."),
            "interpret_system": (
                "Interpret a utilization scan. Lead with the weakest segments and the gap to "
                "the best segment; if volume is present, size the opportunity as gap × volume, "
                "hedged as a ceiling. Utilization is not profit — never claim 'profitable' or "
                "'no losses'."),
        })
    return specs


def directive_from_signals(sig: dict | None) -> str:
    """The intake-prompt directive for already-detected signals ('' when none)."""
    if not sig:
        return ""
    lines = ["LOSS-SIGNAL DIRECTIVE (deterministic scan of THIS schema — these columns exist):"]
    if sig.get("contra_revenue"):
        lines.append(f"  Contra-revenue signals: {', '.join(sig['contra_revenue'])}.")
    if sig.get("capacity"):
        lines.append(f"  Capacity/utilization signals: {', '.join(sig['capacity'])}.")
    lines.append(
        "  A 'losing money' question is NOT a revenue ranking — segment revenue is never "
        "negative, so a revenue ranking can only ever conclude 'no losses'. Frame the "
        "metric around the STRONGEST loss signal instead: "
        "(1) LEAKAGE — the contra-revenue amount as a RATE of gross per segment (which "
        "segment leaks fastest, not which is biggest). Leakage means REALIZED "
        "contra-revenue — amounts actually refunded/credited — never exposure such as "
        "the share of fares that are merely refundABLE; "
        "(2) UTILIZATION — sold units vs capacity per segment, and the gap to the best "
        "segment as units × revenue-per-unit, when capacity columns exist; "
        "(3) the below-benchmark revenue ranking is CONTEXT, never the whole answer. "
        "HONESTY: without cost data profit is NOT computable — never conclude segments are "
        "'profitable' or that there are 'no losses'; quantify leakage and utilization "
        "opportunity, or state plainly that only revenue was measurable.")
    return "\n".join(lines) + "\n"

def loss_signal_directive(question: str, schema_text: str) -> str:
    """The intake-prompt directive, or '' when it doesn't apply (safe to prepend
    unconditionally). Kept to facts the detector verified — the block never claims
    signals that aren't in the schema."""
    return directive_from_signals(detect_loss_signals(question, schema_text))
