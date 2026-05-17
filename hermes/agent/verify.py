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
    from hermes.agent.state import AnalysisReport, DataQualityNote, QueryResult

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
    from hermes.agent.state import DataQualityNote

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
