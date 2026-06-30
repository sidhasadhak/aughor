"""
Post-synthesis numeric claim verifier.

Extracts numbers from the narrator's report and checks each one against
the executed query results and stats. Unverifiable numbers are flagged
as a DataQualityNote rather than blocking the report.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.agent.state import AnalysisReport, QueryResult

# Match numbers: integers, decimals, percentages (but not bare years like 2024)
_NUM_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+)(%?)\b")

# Tolerance bands for matching
_REL_TOL = 0.10   # ±10% for row/aggregate values
_STAT_TOL = 0.15  # ±15% for stat-derived values (sigma, p_value)

# Years that look like numbers but aren't claims (2020–2035 range)
_YEAR_RE = re.compile(r"\b20[2-3]\d\b")


def _parse_numbers(text: str) -> list[float]:
    """Extract unique numeric values from a text string, skipping years."""
    seen: set[float] = set()
    results: list[float] = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        is_pct = m.group(2) == "%"
        if _YEAR_RE.match(m.group(0)):
            continue
        try:
            val = float(raw)
            if is_pct:
                val = val / 100.0   # normalise to fraction for comparison
            if val not in seen:
                seen.add(val)
                results.append(val)
        except ValueError:
            pass
    return results


# ── Narration-inversion guard ──────────────────────────────────────────────────
# A per-group / per-row value narrated as a UNIVERSAL per-entity property. A result
# like (1 item → 3 orders), (2 items → 5 orders) becomes "all orders have 3 items":
# the narrator lifts one row's number and asserts it of EVERY entity, over a
# distribution that visibly varies. The numeric-grounding check above can't catch it
# — 3 IS a real cell — and _mislabeled_per_grain only covers AVG-of-line-items.
#
# High precision by construction: fires ONLY when the prose makes an
# "all/every/each <entity> have/has/contain/average <N>" claim AND the result is a
# multi-row breakdown whose column holding N is non-constant — so the data itself
# disproves the universal. A genuinely uniform result (every row = N) is NOT flagged,
# and a claim whose N is absent from the data is left to the numeric verifier.
# The entity word may be singular ("every customer has 2 orders") or plural — the
# real precision gate is the data-contradiction check below, not the phrasing, so we
# match either and let the distribution decide. A possession/aggregation verb plus a
# number is required, which excludes count-of-entity phrasing ("all 12 months are
# represented" — number before the entity, no possession verb).
_UNIVERSAL_PER_ENTITY = re.compile(
    r"\b(?:all|every|each)\s+(?:of\s+the\s+|the\s+)?\w+\b[^.]{0,30}?"
    r"\b(?:have|has|contain|contains|include|includes|average|averages|averaged)\b\s*"
    r"(?:about\s+|around\s+|roughly\s+|~\s*|approximately\s+|exactly\s+|only\s+|just\s+)?"
    r"(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def _cell_to_float(cell) -> "float | None":
    """Parse a result cell to float, or None if it isn't numeric (return-None, not a
    silent except-continue, so it stays off the swallow ratchet)."""
    if cell is None or cell == "NULL":
        return None
    try:
        return float(str(cell).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def _numeric_columns(rows) -> "dict[int, list[float]]":
    """Per-column numeric cell values (column index → list of floats)."""
    cols: "dict[int, list[float]]" = {}
    for row in rows or []:
        for i, cell in enumerate(row):
            v = _cell_to_float(cell)
            if v is not None:
                cols.setdefault(i, []).append(v)
    return cols


def inverted_universal_claim(text: str, rows) -> "str | None":
    """Detect a universal per-entity claim ('all orders have 3 items') that the
    result distribution contradicts (the asserted value N varies across rows).

    Returns a one-line reason to flag/drop the finding, or None. Never raises.
    Conservative: needs ≥2 rows, the universal phrasing, N present in a NON-constant
    column, and NO column where N is uniform (which would make the claim defensible)."""
    try:
        if not text or not rows or len(rows) < 2:
            return None
        cols = _numeric_columns(rows)
        if not cols:
            return None
        for m in _UNIVERSAL_PER_ENTITY.finditer(text):
            n = float(m.group(1))
            # If some column is uniformly N, the universal is defensible at that grain.
            if any(vals and all(v == n for v in vals) for vals in cols.values()):
                continue
            for vals in cols.values():
                distinct = set(vals)
                if n in distinct and len(distinct) > 1:
                    return (
                        f"'{m.group(0).strip()}' over-generalises: {n:g} is one of "
                        f"{len(distinct)} differing values in the result, not a constant"
                    )
        return None
    except Exception:
        return None


def _values_from_history(query_history: list["QueryResult"]) -> list[float]:
    """Flatten all cell values and stat fields from executed queries into floats."""
    vals: list[float] = []
    for r in query_history:
        if r.error:
            continue
        for row in r.rows:
            for cell in row:
                if cell is None or cell == "NULL":
                    continue
                try:
                    vals.append(float(str(cell).replace(",", "").replace("%", "")))
                except (ValueError, TypeError):
                    pass
        for s in (r.stats or []):
            if s.sigma is not None:
                vals.append(s.sigma)
            if s.p_value is not None:
                vals.append(s.p_value)
    return vals


def _near(val: float, reference: float, tol: float) -> bool:
    if reference == 0:
        return abs(val) < 1e-6
    return abs(val - reference) / max(abs(reference), 1e-9) <= tol


def verify_numeric_claims(
    report: "AnalysisReport",
    query_history: list["QueryResult"],
) -> list[str]:
    """
    Returns a list of numbers (as strings) that appear in the report but cannot
    be traced to any row value, aggregate, or stat in the executed query results.
    Empty list = all numbers verified (or no numbers found).
    """

    reference_vals = _values_from_history(query_history)
    if not reference_vals:
        return []  # no evidence at all — verifier can't help

    unverified: list[str] = []

    # Collect text from verdict, diagnosis, and each key finding claim + evidence
    texts: list[str] = [report.headline, report.verdict]
    for f in report.key_findings:
        texts.append(f.claim)
        texts.append(f.evidence)
    for r in report.recommended_actions:
        texts.append(r)

    full_text = " ".join(t for t in texts if t)
    candidates = _parse_numbers(full_text)

    for val in candidates:
        # Skip trivially common values (0, 1, 100, small ordinals)
        if val in (0, 0.0, 1.0, 100.0) or (val == int(val) and val <= 10):
            continue
        # Check against reference values with tolerances
        if not any(_near(val, ref, _REL_TOL) for ref in reference_vals):
            # Try as percentage too (val could be stored as fraction in data)
            pct_val = val * 100 if val <= 1.0 else val / 100.0
            if not any(_near(pct_val, ref, _REL_TOL) for ref in reference_vals):
                unverified.append(f"{val:.4g}")

    return unverified


def verify_universal_claims(
    report: "AnalysisReport",
    query_history: list["QueryResult"],
) -> list[str]:
    """Universal per-entity claims in the report ('all orders have 3 items') that an
    executed result distribution disproves. Returns reason strings (empty = none).

    Each executed result's rows are checked against the report's full narrative text.
    The detector is high-precision — it needs the universal phrasing AND the number to
    be one of several DIFFERING values in that result's columns — so a cross-query
    false match is unlikely. Surfaced as a DataQualityNote caveat, never blocking."""
    texts: list[str] = [report.headline, report.verdict]
    for f in report.key_findings:
        texts.append(f.claim)
        texts.append(f.evidence)
    for r in report.recommended_actions:
        texts.append(r)
    full_text = " ".join(t for t in texts if t)
    if not full_text.strip():
        return []

    reasons: list[str] = []
    seen: set[str] = set()
    for r in query_history:
        if getattr(r, "error", None):
            continue
        reason = inverted_universal_claim(full_text, getattr(r, "rows", None))
        if reason and reason not in seen:
            seen.add(reason)
            reasons.append(reason)
    return reasons


def build_pre_synthesis_number_check(
    query_history: list["QueryResult"],
) -> str:
    """
    Build a *pre-synthesis* numbers block to inject into the synthesis prompt
    so the narrator can only use numbers that actually appear in the data.

    Returns a prompt section (str).  Empty string if nothing useful to inject.

    This is different from verify_numeric_claims (which runs after the fact) —
    this runs *before* the LLM writes the report so hallucinated numbers are
    prevented rather than flagged.
    """
    try:
        reference_vals = _values_from_history(query_history)
        if not reference_vals:
            return ""

        # Collect notable values: top-10 largest (likely headline aggregates) +
        # any small non-trivial values that could be percentages or rates
        interesting: list[float] = []
        for v in reference_vals:
            if v in (0, 0.0, 1.0, 100.0) or (v == int(v) and v <= 10):
                continue
            interesting.append(v)

        if not interesting:
            return ""

        # De-duplicate and pick a representative sample
        seen: set[str] = set()
        deduped: list[float] = []
        for v in sorted(set(interesting), reverse=True):
            key = f"{v:.6g}"
            if key not in seen:
                seen.add(key)
                deduped.append(v)
            if len(deduped) >= 30:
                break

        val_list = ", ".join(f"{v:.6g}" for v in deduped)
        return (
            "\nVERIFIED NUMERIC VALUES (only these numbers — or values within ±10% of them — "
            "may appear in headline, verdict, findings, and recommendations; "
            "any other number is unverified and must NOT be stated as fact):\n"
            f"  {val_list}\n"
        )
    except Exception:
        return ""
