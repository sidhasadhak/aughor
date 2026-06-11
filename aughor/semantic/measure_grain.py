"""Measure-grain detection — per-UNIT vs per-LINE additivity (the additivity semantic layer).

The platform models a column's semantic_type ("measure") but NOT its GRAIN. Two measures can
sit in the SAME table at DIFFERENT grains:
  • per-UNIT  — a unit price/cost (final_price_usd, unit_price_usd, cogs_usd): the additive
    line value is `measure × quantity`. SUM(measure) alone UNDER-counts (the beautycommerce
    revenue $252M-vs-$503M bug).
  • per-LINE  — a line total already ×quantity (gross_margin_usd = (price−cogs)×qty):
    SUM(measure) is already correct, and SUM(measure × quantity) DOUBLE-counts (the
    gross_margin −$20,882 vs the correct −$8,712 bug).

Modelling semantic_type + entity grain + joins is not enough to aggregate these correctly —
this module adds the missing piece.

DETECTION SIGNAL (verified on real data, beautycommerce): bucket rows by the quantity column
and compare AVG(measure) across buckets. A per-UNIT measure is INDEPENDENT of quantity → AVG
is flat (ratio ≈ 1 at every bucket: final_price_usd was 1.00/1.00/1.00). A per-LINE measure
SCALES with quantity → AVG(q=k) ≈ k·AVG(q=1) (gross_margin_usd was 1.00/2.00/3.00).
Deterministic, one cheap GROUP BY probe; CONSERVATIVE — returns "unknown" unless the fit is
clean and unambiguous, so it never mislabels a noisy measure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

Grain = Literal["per_unit", "per_line", "unknown"]

# A quantity / units-per-line column (the multiplier that distinguishes the two grains).
_QTY_RE = re.compile(r"(?:^|_)(quantity|qty|units?|item_count|n_items|num_items|line_qty)(?:$|_)", re.I)
# Columns worth probing for grain — value-bearing measures. Keeps probe count bounded and
# avoids scanning ids/dates. Quantity columns and obvious non-measures are excluded by the caller.
_MEASURE_RE = re.compile(
    r"(price|cost|margin|amount|revenue|sales|value|spend|fee|charge|discount|tax|profit|"
    r"gross|net|paid|cogs|total|subtotal|freight|shipping)", re.I)
_NON_MEASURE_RE = re.compile(r"(?:^|_)(id|key|sk|code|date|ts|timestamp|at|flag|status|type|name)(?:$|_)", re.I)
# Rates / percentages / ratios are NOT additive base measures — a per-unit percentage is
# still flat across quantity (so the grain probe would label it per_unit), but you never
# SUM(pct × quantity). Exclude them so they're neither guarded nor put in the grains block.
_RATE_RE = re.compile(r"_(pct|percent|rate|ratio|share)$|(?:^|_)(pct|percent)(?:_|$)", re.I)


@dataclass(frozen=True)
class GrainVerdict:
    measure: str
    grain: Grain
    quantity_col: str = ""
    detail: str = ""


def classify_from_buckets(
    buckets: "list[tuple[int, float, int]]",
    *,
    min_rows: int = 200,
    tol: float = 0.20,
) -> Grain:
    """Classify a measure's grain from AVG-by-quantity buckets.

    ``buckets``: list of (quantity, avg_measure, n_rows), quantity ≥ 1. Pure (no DB) so the
    decision logic is exhaustively unit-testable.

    per_unit  ⇔ AVG(measure|q=k) ≈ AVG(measure|q=1)        (ratio ≈ 1, flat)
    per_line  ⇔ AVG(measure|q=k) ≈ k · AVG(measure|q=1)    (ratio ≈ k, scales)
    unknown   ⇔ ambiguous, too few rows, ~0 baseline, or neither fit cleanly.
    """
    bymap = {q: avg for q, avg, n in buckets if n >= min_rows and q >= 1}
    if 1 not in bymap:
        return "unknown"
    base = bymap[1]
    if abs(base) < 1e-9:
        return "unknown"  # baseline ~0 makes ratios meaningless
    ks = sorted(k for k in bymap if k >= 2)
    if not ks:
        return "unknown"  # need at least one higher bucket to see scaling
    unit_fit, line_fit = [], []
    for k in ks:
        ratio = bymap[k] / base
        unit_fit.append(abs(ratio - 1.0) <= tol)        # flat
        line_fit.append(abs(ratio - k) <= tol * k)      # scales with k (tolerance widens with k)
    all_unit, all_line = all(unit_fit), all(line_fit)
    if all_unit and not all_line:
        return "per_unit"
    if all_line and not all_unit:
        return "per_line"
    return "unknown"  # both (only when k makes 1≈k, impossible for k≥2) or neither → stay silent


# Per-connection grain map cache — grains are a property of the data, not the query, so
# detect once and reuse. Keyed by connection id; cleared only on process restart.
_GRAIN_CACHE: "dict[str, tuple[dict, set]]" = {}


def connection_measure_grains(
    conn_id: str, db, table_cols: "dict[str, list[str]]", *, max_probes: int = 24
) -> "tuple[dict[str, str], set[str]]":
    """Detect per-unit/per-line grains for the measure columns of tables that carry a
    quantity column. Returns (grains: col_lower→'per_unit'|'per_line', qcols: set), cached
    per connection (the AVG-by-quantity probe is a real scan, run once). Bounded by
    max_probes; best-effort (any failure → whatever was detected so far)."""
    if conn_id in _GRAIN_CACHE:
        return _GRAIN_CACHE[conn_id]
    grains: "dict[str, str]" = {}
    qcols: "set[str]" = set()
    probes = 0
    try:
        for table, cols in (table_cols or {}).items():
            qty = next((c for c in cols if _QTY_RE.search(c)), None)
            if not qty:
                continue
            qcols.add(qty.lower())
            for c in cols:
                if probes >= max_probes:
                    break
                if (c == qty or _NON_MEASURE_RE.search(c) or _RATE_RE.search(c)
                        or not _MEASURE_RE.search(c)):
                    continue
                probes += 1
                g = detect_measure_grain(db, table, c, qty)
                if g in ("per_unit", "per_line"):
                    grains[c.lower()] = g
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "measure-grain detection is best-effort; partial grains are safe "
                 "(an undetected measure is just not guarded, no worse than before)",
                 counter="measure_grain.detect_failed")
    _GRAIN_CACHE[conn_id] = (grains, qcols)
    return grains, qcols


def render_grains_block(grains: "dict[str, str]", quantity_cols: "set[str]") -> str:
    """Format detected grains as a generator-prompt block (pure; testable without a DB).
    Returns "" when nothing was classified, so callers can append unconditionally."""
    per_unit = sorted(c for c, g in grains.items() if g == "per_unit")
    per_line = sorted(c for c, g in grains.items() if g == "per_line")
    if not per_unit and not per_line:
        return ""
    qty = sorted(quantity_cols)
    qty_name = qty[0] if len(qty) == 1 else "quantity"
    lines = ["MEASURE GRAINS — aggregate each measure at the RIGHT grain (verified from the data):"]
    if per_unit:
        lines.append(
            f"  - PER-UNIT (a per-item value; the additive line total is the measure × {qty_name}): "
            f"{', '.join(per_unit)}. For a SUM/total/revenue, write SUM(<measure> * {qty_name}) — "
            f"NEVER SUM(<measure>) alone (it under-counts by the units per line)."
        )
    if per_line:
        lines.append(
            f"  - PER-LINE (already a line total, includes {qty_name}): {', '.join(per_line)}. "
            f"Write SUM(<measure>) directly — NEVER SUM(<measure> * {qty_name}) (it double-counts)."
        )
    return "\n".join(lines)


def measure_grains_block(conn_id: str, db, table_cols: "Optional[dict]" = None,
                         *, schema_text: "Optional[str]" = None) -> str:
    """Convenience: detect (cached) + render the measure-grains block for a connection.
    Pass table_cols, or a schema_text to parse. No-op safe — returns "" on any trouble
    or when nothing is classified, so callers can append it unconditionally."""
    try:
        if table_cols is None:
            from aughor.tools.schema import parse_schema_tables
            table_cols = parse_schema_tables(schema_text or "")
        grains, qcols = connection_measure_grains(conn_id, db, table_cols or {})
        return render_grains_block(grains, qcols)
    except Exception:
        return ""


def measure_grain_misuse(
    sql: str,
    grains: "dict[str, str]",
    quantity_cols: "set[str]",
    *,
    dialect: str = "duckdb",
) -> "Optional[str]":
    """Flag a SUM that aggregates a measure at the WRONG grain. Deterministic, driven by
    the detected ``grains`` (col→'per_unit'|'per_line') — no hardcoded column names.

      • SUM(<per_line> × quantity)        → DOUBLE-count (the gross_margin −$20,882 bug)
      • SUM(<per_unit>) without ×quantity → UNDER-count  (the revenue $252M bug)

    Correct forms — SUM(per_unit × quantity) and SUM(per_line) — are silent. Returns a
    one-line reason or None; never raises (any parse trouble → None). Only KNOWN grains
    (per_unit/per_line) are checked; 'unknown' columns are ignored, so it stays high-precision."""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None
    qcols = {q.lower() for q in (quantity_cols or set())}

    for s in tree.find_all(exp.Sum):
        inner = s.this
        # SUM(<col>) — a bare measure column
        if isinstance(inner, exp.Column):
            g = grains.get(inner.name.lower())
            if g == "per_unit":
                return (f"SUM({inner.name}) sums a PER-UNIT measure without × quantity — it "
                        f"under-counts by the units-per-line (use SUM({inner.name} * quantity))")
            continue
        # SUM(<a> * <b>) — a product; look for measure × quantity
        if isinstance(inner, exp.Mul):
            cols = [c for c in (inner.left, inner.right) if isinstance(c, exp.Column)]
            if len(cols) != 2:
                continue
            names = [c.name.lower() for c in cols]
            # one operand a measure we know, the other a quantity column
            for i, j in ((0, 1), (1, 0)):
                m, other = names[i], names[j]
                if grains.get(m) == "per_line" and other in qcols:
                    return (f"SUM({cols[i].name} * {cols[j].name}) multiplies a PER-LINE measure "
                            f"by quantity — it DOUBLE-counts (the per-line total already includes "
                            f"quantity; use SUM({cols[i].name}))")
    return None


def detect_measure_grain(db, table: str, measure_col: str, quantity_col: str,
                         *, max_qty: int = 6) -> Grain:
    """Run the AVG-by-quantity-bucket probe against the live DB and classify.
    Best-effort: any error (bad column, non-numeric, no quantity) → "unknown" (never raises)."""
    try:
        res = db.execute("measure_grain", (
            f"SELECT {quantity_col} AS q, AVG({measure_col}) AS a, COUNT(*) AS n "
            f"FROM {table} "
            f"WHERE {quantity_col} BETWEEN 1 AND {int(max_qty)} AND {measure_col} IS NOT NULL "
            f"GROUP BY {quantity_col} ORDER BY {quantity_col}"
        ))
        if getattr(res, "error", None):
            return "unknown"
        buckets = []
        for row in res.rows:
            if row[0] is None or row[1] is None:
                continue
            buckets.append((int(row[0]), float(row[1]), int(row[2])))
        return classify_from_buckets(buckets)
    except Exception:
        return "unknown"
