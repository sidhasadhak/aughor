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

# The same question, asked from the other side. "Where are we losing money?" is a flip
# question — it asks where the business could be doing better, and the honest answer
# ("long-haul flies 77.7% full against short-haul's 79.4%") is an OPPORTUNITY framed as
# a loss. So "where can we optimise?" must reach the same lenses over the same columns;
# only this gate was loss-worded, while the signal scan below is already intent-agnostic.
# Deliberately tight: bare "improve"/"efficiency" also read as ordinary temporal
# questions ("did load factor improve?"), which these lenses would distort.
OPPORTUNITY_INTENT_RE = re.compile(
    r"(optimi[sz](?:e|ing|ation)|biggest opportunit|opportunit(?:y|ies) (?:to|for|in)"
    r"|where (?:can|could|should) we (?:improve|focus|do better|gain)"
    r"|room (?:to|for) (?:grow|improv)|head ?room|upside\b|untapped"
    r"|left on the table|low[- ]hanging|under[- ]?utili[sz]|under[- ]?fill"
    r"|idle (?:capacity|time|asset)|capacity gap|efficiency gap)", re.I)

# Contra-revenue: money that walks back out. Word-token scan over the schema text.
CONTRA_REVENUE_RE = re.compile(
    r"\b([a-z0-9_]*(?:refund|chargeback|discount|rebate|writeoff|write_off"
    r"|cancellation_fee|credit_note|clawback|penalt)[a-z0-9_]*)\b", re.I)

# Capacity/utilization: paid units vs available units.
CAPACITY_RE = re.compile(
    r"\b([a-z0-9_]*(?:total_seats|capacity|occupancy|utilization|utilisation"
    r"|load_factor|slots_available)[a-z0-9_]*)\b", re.I)


def detect_loss_signals(question: str, schema_text: str) -> dict | None:
    """The loss signals THIS schema carries, or None when the question asks neither
    side of the loss/opportunity question / the schema carries none. Pure text scan —
    deterministic, no model."""
    q = question or ""
    if not (LOSS_INTENT_RE.search(q) or OPPORTUNITY_INTENT_RE.search(q)):
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

# What a capacity column COUNTS. The utilization gap is dimensionless, so gap × capacity
# carries this noun ("1,135 seats") — the sentence the whole lens exists to produce.
_CAPACITY_UNIT_RE = re.compile(r"(seat|room|slot|bed|table|spot|unit)", re.I)


def _capacity_unit(cols: list) -> str:
    """The noun the capacity columns count, or an honest generic when they don't say."""
    for c in cols or []:
        m = _CAPACITY_UNIT_RE.search(str(c))
        if m:
            return m.group(1).lower() + "s"
    return "units of capacity"


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
            # No deterministic opportunity: this grid's `n` is COUNT(*), but the leakage
            # rate's denominator is SUM(gross). gap × records would be a number with no
            # unit — so the lens stays silent rather than ship a confident one. Wiring it
            # means changing the SQL to return the gross as the volume, which moves a
            # live-validated prompt and needs its own A/B.
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
                "the best segment. The gap × volume opportunity is computed for you and "
                "supplied as a key number — cite it, never recompute it. Utilization is not "
                "profit — never claim 'profitable' or 'no losses'."),
            # This grid's `n` IS the rate's own denominator (capacity), so gap × volume is
            # unit-correct and deterministic: (79.4% − 77.7%) × capacity = empty seats.
            # Higher utilization is better, so the laggard is the emptiest segment.
            "opportunity": {
                "lower_is_better": False,
                "volume_label": _capacity_unit(sig.get("capacity") or []),
                # sold/capacity over the capacity IS a proportion → the gap is tested
                # against its own sampling error, not a flat floor that a thin-margin
                # capacity gap (77.7 vs 79.4) could never clear.
                "volume_is_denominator": True,
            },
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
        "  A 'losing money' / 'where can we do better' question is NOT a revenue ranking "
        "— segment revenue is never "
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
