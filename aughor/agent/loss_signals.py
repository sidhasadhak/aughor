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

# Lifecycle/status columns — whether a unit actually consumed (or offered) capacity.
# Anchored on word parts so `real_estate` doesn't read as a state column.
LIFECYCLE_COL_RE = re.compile(r"(^|_)(status|state|lifecycle)($|_)", re.I)

# Values meaning the unit never consumed/offered the capacity it was counted against.
NOT_CONSUMED_RE = re.compile(
    r"(cancel|void|refund|no.?show|missed|abandon|fail|reject|return|deleted|expired)", re.I)


def _table_columns(schema_text: str) -> list:
    """(table, column) pairs off the schema text, in EITHER live format.

    Two producers feed the intake: `get_schema()` emits `TABLE: name` with indented
    `col TYPE` lines, and the deep path's Data Catalog (`build_data_catalog`) emits
    markdown — `## name` headers over `| col | TYPE | … |` rows. This parser knowing
    only the first was an invisible failure: the word-token scans (contra/capacity)
    are format-agnostic and kept firing, so the loss lenses ran while the lifecycle
    pin silently detected nothing on every live deep run (`lifecycle:0` in the gates
    log, while every offline repro — which used get_schema() — passed)."""
    out: list = []
    table = None
    for line in (schema_text or "").splitlines():
        m = re.match(r"\s*TABLE:\s+([A-Za-z0-9_.\"]+)", line) \
            or re.match(r"\s*##\s+([A-Za-z0-9_.\"]+)\s*$", line)
        if m:
            table = m.group(1).strip('"')
            continue
        if not table:
            continue
        m2 = re.match(r"\s*\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|", line)
        if m2:
            if m2.group(1).lower() != "column":     # the markdown header row is not a column
                out.append((table, m2.group(1)))
            continue
        if line[:1] in (" ", "\t"):
            m3 = re.match(r"\s+([A-Za-z0-9_]+)\s+\S", line)
            if m3:
                out.append((table, m3.group(1)))
    return out


def lifecycle_rules(probed: dict) -> list:
    """The probed lifecycle values as structured KEEP rules for the SQL guard:
    ``[{"table", "column", "keep", "exclude"}]``. Same classification as the prose
    directive (one source of truth for what counts); a column that pins nothing —
    no cancel-like value, or nothing left to keep — contributes no rule."""
    rules: list = []
    for qualified, vals in (probed or {}).items():
        table, _, col = str(qualified).rpartition(".")
        if not table or not col:
            continue
        drop = [v for v in vals if NOT_CONSUMED_RE.search(str(v))]
        keep = [v for v in vals if v not in drop]
        if drop and keep:
            rules.append({"table": table, "column": col,
                          "keep": [str(v) for v in keep],
                          "exclude": [str(v) for v in drop]})
    return rules


def lifecycle_directive(probed: dict) -> str:
    """Pin which units count, from values probed off THIS data ('' when nothing to pin).

    The A/B moved the same claim between 77.7/79.4 and 78.0/80.8 across runs because
    "paid units" was never defined — the planner silently decided whether refunded and
    no-show tickets counted, and it cannot see values in the schema block, so telling it
    to "exclude cancelled" in prose just makes it invent the literal. Reading the values
    off the data and naming them removes the choice. The pinned reading (units that
    actually flew, over capacity that actually operated) is the industry load factor and
    reproduces the reference report's 74.5% / 77.2% exactly."""
    rules = lifecycle_rules(probed)
    if not rules:
        return ""
    lines = ["LIFECYCLE FILTER (values probed from THIS data — filter on them literally):"]
    for r in rules:
        lines.append(f"  {r['table']}.{r['column']}: "
                     f"KEEP {', '.join(repr(v) for v in r['keep'])}"
                     f" — EXCLUDE {', '.join(repr(v) for v in r['exclude'])}.")
    lines.append(
        "  Apply each filter on ITS OWN table at its own grain. A unit belongs in the "
        "NUMERATOR only if it actually consumed the capacity — it flew, was occupied, was "
        "delivered; a cancelled or no-show unit did not, however it was paid for. Capacity "
        "belongs in the DENOMINATOR only if it was actually offered — a cancelled carrier "
        "unit offered none. Cancelled units are the LEAKAGE lens's story: counting them "
        "here double-counts them.")
    return "\n".join(lines) + "\n"


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
    # Qualified, because the lifecycle rule filters a specific table at its own grain.
    lifecycle = sorted({f"{t}.{c}" for t, c in _table_columns(schema_text)
                        if LIFECYCLE_COL_RE.search(c)})
    return {"contra_revenue": contra[:12], "capacity": capacity[:8],
            "lifecycle": lifecycle[:4]}


# Which loss CLASS a metric already covers — used to decide which forward-chained
# lens phases a run still owes after the intake picked its primary metric.
LEAKAGE_METRIC_RE = re.compile(
    r"refund|chargeback|discount|rebate|leakage|writeoff|write_off|clawback|penalt", re.I)
UTILIZATION_METRIC_RE = re.compile(
    r"load[ _-]?factor|utili[sz]ation|occupancy|capacity|fill[ _-]?rate|seats?\b", re.I)

# What a capacity column COUNTS. The utilization gap is dimensionless, so gap × capacity
# carries this noun ("1,135 seats") — the sentence the whole lens exists to produce.
_CAPACITY_UNIT_RE = re.compile(r"(seat|room|slot|bed|table|spot|unit)", re.I)


# A currency token on the amount column — the leakage opportunity is MONEY, so its
# sentence should say "480K CHF", not "480K of gross".
_MONEY_UNIT_RE = re.compile(r"_(chf|usd|eur|gbp|jpy|cad|aud|sek|nok|dkk|inr|brl|mxn)\b", re.I)


def _money_unit(cols: list) -> str:
    """The currency the contra columns are denominated in, or an honest generic."""
    for c in cols or []:
        m = _MONEY_UNIT_RE.search(str(c))
        if m:
            return m.group(1).upper()
    return "of gross"


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
            # NO lifecycle filter, and the A/B is why: this lens's numerator IS the
            # cancelled population — every one of the 6,907 refunds sits on a cancelled
            # ticket. Handing it the utilization rule ("keep 'flown'") filters away all
            # 2.38M CHF of leakage and reports a 0.0% rate with a straight face. The rule
            # defines which units consumed CAPACITY; it says nothing about which units
            # leaked money.
            "phase_id": "loss_leakage",
            "title": "Revenue Leakage — Where Money Walks Back Out",
            "emoji": "💸",
            "fprefix": "leakage",
            "metric_label": "leakage rate",
            "counter": "ada.loss_leakage_lens",
            "plan_system": (
                "You are planning a revenue-LEAKAGE scan: money that walks back out "
                "(refunds, chargebacks, discounts). Plan AT MOST 2 queries. "
                "(1) THE CLAIM — the leakage RATE by a LOW-CARDINALITY grouping: a categorical "
                "column with a HANDFUL of distinct values naming a class of business (cabin, "
                "fare brand, tier, channel, region). NEVER group the claim by a "
                "high-cardinality identifier (booking id, customer, SKU) — no single one of "
                "thousands is material enough to act on. For each group: 100.0 * SUM(<contra "
                "amount>) / NULLIF(SUM(<gross amount>), 0) AS metric_total, plus SUM(<gross "
                "amount>) AS n — n MUST be the same gross that is the rate's denominator, "
                "never a row count: the opportunity is money, so the volume has to be the "
                "money the rate is a share of. Aggregate the contra side and the gross side "
                "EACH AT ITS OWN GRAIN before combining (ratio of sums — never AVG of per-row "
                "ratios, and never a join that duplicates either side). ORDER BY metric_total "
                "DESC (the fastest leak first). Return exactly three columns: the group, "
                "metric_total, n. "
                "(2) THE EVIDENCE — the contra reason/category breakdown: total contra-revenue "
                "and 100.0 * SUM(contra) / NULLIF(SUM(gross), 0) AS metric_total by the reason "
                "or type column when one exists. Do NOT plan a plain revenue ranking."),
            "plan_ask": (
                "Where does contra-revenue leak fastest — which segments have the highest "
                "leakage RATE (contra as a share of gross), and what is the total? "
                f"CONTRA-REVENUE COLUMNS PRESENT: {cols}."),
            "interpret_system": (
                "Interpret a revenue-leakage scan. Lead with the TOTAL leaked and its share of "
                "gross, then where the leakage RATE concentrates (segments above the overall "
                "rate) and the dominant reason if present. These are contra-revenue rates, not "
                "profit — never claim segments are 'profitable' or that there are 'no losses'."),
            # `n` is now the gross the rate is a share of, so gap × volume is money the
            # business kept rather than a unitless count: bring the worst-leaking group to
            # its cleanest material peer's rate and that is the CHF that stops walking out.
            # Higher leakage is worse, so the laggard is the biggest number — benchmarking
            # upward would name the worst leaker as the target. The volume is an AMOUNT,
            # which disqualifies the sampling-error test (CHF are not Bernoulli trials).
            "opportunity": {
                "lower_is_better": True,
                "volume_label": _money_unit(sig.get("contra_revenue") or []),
                "volume_is_denominator": True,
                "volume_is_money": True,
            },
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
            # The grouping is the whole ballgame, and "the most decision-relevant segment"
            # lost it: an A/B on the real airline workspace (n=4/arm) had the planner pick
            # route_id — 84 routes — every single time, where no one route is material and
            # the opportunity is 0/4. Naming the claim's grain explicitly flips it to 4/4
            # at the haul level, which is also how the reference report framed it: the
            # GROUP carries the claim ("long-haul routes are under-filled") and the named
            # units are its evidence. Grain discipline held in both arms (no rate >100%).
            "plan_system": (
                "You are planning a capacity-UTILIZATION scan: paid units against available "
                "capacity. Plan AT MOST 2 queries. "
                "(1) THE CLAIM — utilization by a LOW-CARDINALITY grouping: a categorical "
                "column with a HANDFUL of distinct values naming a CLASS of operation (haul, "
                "cabin, aircraft type, region, service level). NEVER group the claim by a "
                "high-cardinality identifier (route id, flight number, SKU, customer) — "
                "benchmarking one identifier against another compares two specks of the "
                "business, and no single one of hundreds is material enough to act on. For "
                "each group: 100.0 * SUM(<units sold>) / NULLIF(SUM(<capacity>), 0) AS "
                "metric_total, plus the capacity as n. COUNT CAPACITY EXACTLY ONCE per "
                "carrier unit (per flight / slot / store) — joining capacity through a "
                "per-sale table multiplies it and corrupts the rate; aggregate each side at "
                "its own grain, then combine. ORDER BY metric_total ASC (the emptiest "
                "first). Return exactly three columns: the group, metric_total, n. "
                "(2) THE EVIDENCE — the same rate for the individual named units (routes / "
                "flights / stores), same three columns, same grain discipline, ORDER BY "
                "metric_total ASC LIMIT 10, so the weakest group's claim can be illustrated "
                "by name."),
            "plan_ask": (
                "Which segments run the lowest utilization (paid units vs available capacity), "
                "and what is the overall level? "
                f"CAPACITY COLUMNS PRESENT: {cols}."),
            # The old text told the model the opportunity was "supplied as a key number —
            # cite it, never recompute it". That was FALSE: the deterministic annotation is
            # appended AFTER interpretation, so the model never saw it, dutifully computed
            # its own, and the report shipped two opportunity key numbers that disagreed
            # (~1,136 seats beside 1,135). It cannot cite what it has not been given — so
            # tell it to leave the arithmetic alone instead.
            "interpret_system": (
                "Interpret a utilization scan. Lead with the weakest segments and the gap to "
                "the best segment, in percentage points. Do NOT compute, estimate or state a "
                "gap × volume / opportunity / 'seats that could be filled' figure yourself: "
                "one is appended deterministically from these same rows, and a second "
                "hand-computed one contradicts it. Utilization is not profit — never claim "
                "'profitable' or 'no losses'."),
            # This grid's `n` IS the rate's own denominator (capacity), so gap × volume is
            # unit-correct and deterministic: (79.4% − 77.7%) × capacity = empty seats.
            # Higher utilization is better, so the laggard is the emptiest segment.
            # This lens counts units that CONSUMED capacity, so the probed lifecycle rule
            # ("keep 'flown', drop 'cancelled'/'no_show'") is exactly its definition.
            "lifecycle_filter": True,
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
