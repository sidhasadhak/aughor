"""Grain-correct recompute for a conditioned-denominator ratio scan.

The suppression caveat has promised the reader the same sentence for weeks: "a
grain-correct recompute (pre-aggregate each side to the dimension grain, then
divide) is needed before this can be ranked or trusted." This module IS that
recompute. When the guards prove a per-segment cross-table ratio was corrupted
(the planner joined the denominator through the numerator's event table, or a
join multiplied one side), we rebuild the scan deterministically — numerator
aggregated over ITS table, denominator over ITS table, joined only at the
segment grain — instead of merely suppressing the artifact.

The repair never trusts itself: the caller must accept it only when the
recomputed whole-population level matches the independently-computed true
global (see ``validate_totals``). A wrong join guess re-multiplies a side,
the totals stop matching, and the caller falls back to suppression — a wrong
repair produces a wrong checksum, never a confident wrong ranking.

Scope (v1, deliberately narrow — everything else fails open to suppression):
segment on the DENOMINATOR table (rate by population attribute: channel, cabin,
haul) with the numerator one shared-key hop away, or segment on the NUMERATOR
table (share-of-population by event attribute: refund reason). SUM/COUNT sides
only; AVG has per-row-mean semantics this shape cannot honestly reproduce.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# A shared column that can carry a join: id-shaped names only.
_KEY_COL_RE = re.compile(r"(^|_)id$", re.I)

Probe = Callable[[str], Optional[list]]     # sql -> rows (or None on error)


def _qt(table: str) -> str:
    """Quote a possibly schema-qualified table name part-by-part."""
    return ".".join(f'"{p}"' for p in str(table).split("."))


def _columns_of(probe: Probe, table: str) -> list:
    parts = str(table).split(".")
    where = f"table_name = '{parts[-1]}'"
    if len(parts) >= 2:
        where += f" AND table_schema = '{parts[-2]}'"
    rows = probe("SELECT column_name FROM information_schema.columns WHERE " + where) or []
    return [str(r[0]) for r in rows]


def _shared_key(cols_a: list, cols_b: list, table_a: str, table_b: str) -> Optional[str]:
    """The one id-shaped column both tables carry. Preference: a key whose stem names
    either table (``booking_id`` ↔ ``bookings``); else a single candidate; else None —
    two unrelated shared ids is a guess, and a guess is what got us here."""
    shared = sorted({c for c in cols_a if c in set(cols_b) and _KEY_COL_RE.search(c)})
    if not shared:
        return None
    stems = {t.split(".")[-1].lower().rstrip("s") for t in (table_a, table_b)}
    stem_hits = [c for c in shared if c.lower()[:-3].rstrip("_") in stems]
    if len(stem_hits) == 1:
        return stem_hits[0]
    if len(shared) == 1:
        return shared[0]
    return None


def _agg_expr(agg: str, ref: str) -> Optional[str]:
    agg = (agg or "SUM").upper()
    if agg == "SUM":
        return f"SUM({ref})"
    if agg == "COUNT":
        return f"COUNT({ref})"
    return None                                # AVG: not a ratio-of-sums — refuse


def plan_grain_correct_scan(probe: Probe, sources: dict, segment_col: str) -> Optional[dict]:
    """Plan the recompute for one segment column, or None when it can't be built
    safely. ``sources`` is investigate._parse_ratio_sources output with tables
    resolved. Returns {"sql", "case", "segment_col"}."""
    try:
        num_t, den_t = sources.get("num_table"), sources.get("den_table")
        if not num_t or not den_t or num_t == den_t:
            return None
        if not segment_col or not re.fullmatch(r"\w+", str(segment_col)):
            return None
        num_agg = _agg_expr(sources.get("num_agg", "SUM"), f'n."{sources["num_col"]}"')
        den_agg = _agg_expr(sources.get("den_agg", "SUM"), f'd."{sources["den_col"]}"')
        if not num_agg or not den_agg:
            return None
        scale = float(sources.get("scale") or 1.0)
        num_cols = _columns_of(probe, num_t)
        den_cols = _columns_of(probe, den_t)
        if not num_cols or not den_cols:
            return None
        seg = str(segment_col)
        on_den, on_num = seg in den_cols, seg in num_cols
        if on_den and on_num:
            return None                        # ambiguous owner — don't guess
        if on_den:
            key = _shared_key(num_cols, den_cols, num_t, den_t)
            if not key:
                return None
            sql = (
                f'WITH den AS (\n'
                f'  SELECT d."{seg}" AS segment, {den_agg} AS den_total\n'
                f'  FROM {_qt(den_t)} AS d GROUP BY 1\n'
                f'), num AS (\n'
                f'  SELECT d."{seg}" AS segment, {num_agg} AS num_total\n'
                f'  FROM {_qt(num_t)} AS n JOIN {_qt(den_t)} AS d ON n."{key}" = d."{key}"\n'
                f'  GROUP BY 1\n'
                f')\n'
                f'SELECT den.segment AS "{seg}",\n'
                f'       {scale} * COALESCE(num.num_total, 0) / NULLIF(den.den_total, 0) AS metric_total,\n'
                f'       den.den_total AS n, COALESCE(num.num_total, 0) AS num_total\n'
                f'FROM den LEFT JOIN num ON den.segment IS NOT DISTINCT FROM num.segment\n'
                f'ORDER BY metric_total DESC'
            )
            return {"sql": sql, "case": "den_segment", "segment_col": seg}
        if on_num:
            # Event-side attribute: the honest denominator is the WHOLE population —
            # "share of gross leaked, by reason" — a per-reason denominator is exactly
            # the conditioned shape being repaired.
            num_agg_bare = _agg_expr(sources.get("num_agg", "SUM"), f'"{sources["num_col"]}"')
            den_agg_bare = _agg_expr(sources.get("den_agg", "SUM"), f'"{sources["den_col"]}"')
            sql = (
                f'WITH den AS (SELECT {den_agg_bare} AS den_total FROM {_qt(den_t)}),\n'
                f'num AS (\n'
                f'  SELECT "{seg}" AS segment, {num_agg_bare} AS num_total, COUNT(*) AS n_events\n'
                f'  FROM {_qt(num_t)} GROUP BY 1\n'
                f')\n'
                f'SELECT num.segment AS "{seg}",\n'
                f'       {scale} * num.num_total / NULLIF(den.den_total, 0) AS metric_total,\n'
                f'       num.n_events AS n, num.num_total AS num_total\n'
                f'FROM num CROSS JOIN den\n'
                f'ORDER BY metric_total DESC'
            )
            return {"sql": sql, "case": "num_segment", "segment_col": seg}
        return None                            # third-table segment: out of v1 scope
    except Exception:
        return None


def validate_totals(rows: list, scale: float, true_global: float,
                    case: str, tolerance: float = 0.02) -> bool:
    """The acceptance gate: does the recompute's own whole-population level match the
    independently computed true global? Rows carry ``num_total`` as the 4th column
    (and ``n`` = den_total for den_segment). A re-multiplied side breaks this
    identity — the wrong repair fails its checksum instead of shipping."""
    try:
        if not rows or len(rows) < 2 or not true_global or true_global <= 0:
            return False
        num_sum = sum(float(r[3]) for r in rows if r[3] is not None)
        if case == "den_segment":
            den_sum = sum(float(r[2]) for r in rows if r[2] is not None)
        else:                                  # num_segment: same total denominator each row
            # metric_total = scale*num_total/den_total  ⇒ den_total = scale*num/rate
            first = next((r for r in rows if r[1] and float(r[1]) != 0), None)
            if first is None:
                return False
            den_sum = scale * float(first[3]) / float(first[1])
        if den_sum <= 0:
            return False
        recomputed = scale * num_sum / den_sum
        return abs(recomputed / true_global - 1.0) <= tolerance
    except Exception:
        return False
