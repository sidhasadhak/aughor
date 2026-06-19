"""
Numeral grounding for autonomous-explorer findings.

Phase-8 findings are 1-2 sentence business insights an LLM writes from a SQL
result. The LLM free-forms numbers into that prose, and it sometimes fabricates
the *magnitude* or *unit* — the canonical bug was a finding that read
``"2.49M attribution credit"`` when the underlying result cell was ``2.49`` (off
by 1e6, with an invented "M"). Directionally true, numerically false — and a
single wrong magnitude in a headline destroys trust in the whole surface (the
same failure mode as the ``$3T`` product-of-aggregates revenue bug).

This module is a deterministic guard: it extracts every numeral a finding
*claims* and verifies each **magnitude-bearing** one against the actual numeric
cells of the result it was derived from. It is deliberately conservative — it
only enforces grounding on numbers that carry a magnitude claim (a K/M/B/T
suffix, or a value ≥ 1000), so legitimately *derived* quantities (growth
percentages, ranks, small counts, calendar years) are never false-flagged. The
goal is to catch catastrophic magnitude/unit hallucinations, not to police every
digit.

Pure + dependency-free so it stays cheap to call on every finding and trivial to
unit-test. See ``tests/unit/test_grounding.py``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Word/letter magnitude suffixes → multiplier. "%" is handled separately (a
# percentage is a derived ratio, never enforced).
_SUFFIX_MULT: dict[str, float] = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "trillion": 1e12,
}

# A numeral token: optional currency, digits (optional thousands grouping),
# optional decimal, optional magnitude/percent suffix (letter or word). The
# lookbehind/lookahead keep us off the middle of larger tokens (IDs, dates,
# version strings). A trailing "." (sentence end) is allowed after a suffix.
_NUM_RE = re.compile(
    r"(?<![\w.])"
    r"[$€£]?\s?"
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)"
    r"(?P<frac>\.\d+)?"
    r"\s?(?P<suf>%|mm|bn|[kmbt]|thousand|million|billion|trillion)?"
    r"(?![\w])",
    re.I,
)


@dataclass(frozen=True)
class Numeral:
    """One numeric token parsed out of finding prose."""
    text: str            # the matched substring, e.g. "2.49M"
    value: float         # magnitude-expanded value, e.g. 2_490_000.0
    decimals: int        # decimal places shown (drives the rounding window)
    multiplier: float    # suffix multiplier (1.0 when none / percent)
    suffix: str          # normalised suffix ("m", "%", "" …)
    enforce: bool        # True ⇒ must be grounded in a real result cell


@dataclass
class GroundingResult:
    grounded: bool
    ungrounded: list[str] = field(default_factory=list)   # offending token texts
    checked: int = 0                                       # # enforced numerals


def extract_numerals(text: str) -> list[Numeral]:
    """Parse every numeric token from ``text`` into structured :class:`Numeral`s."""
    out: list[Numeral] = []
    for m in _NUM_RE.finditer(text or ""):
        int_str = m.group("int")
        frac = m.group("frac") or ""
        suf = (m.group("suf") or "").lower()
        try:
            raw = float(int_str.replace(",", "") + frac)
        except ValueError:  # pragma: no cover - regex guarantees digits
            continue
        is_percent = suf == "%"
        multiplier = 1.0 if is_percent else _SUFFIX_MULT.get(suf, 1.0)
        has_suffix_mult = suf in _SUFFIX_MULT
        decimals = len(frac) - 1 if frac else 0  # frac includes the leading "."
        value = raw * multiplier
        # Calendar years (1900-2100, integer, no suffix) read as dates, not metrics.
        is_year = (not suf) and decimals == 0 and 1900.0 <= raw <= 2100.0
        # Enforce grounding only on magnitude claims: an explicit K/M/B/T unit, or a
        # bare value ≥ 1000. Percentages, ranks, small counts and years are exempt.
        enforce = (
            (has_suffix_mult or (abs(value) >= 1000.0 and not is_percent))
            and not is_percent
            and not is_year
        )
        out.append(Numeral(
            text=m.group(0).strip(),
            value=value,
            decimals=decimals,
            multiplier=multiplier,
            suffix=suf,
            enforce=enforce,
        ))
    return out


def _to_float(cell) -> Optional[float]:
    """Best-effort numeric coercion of a single result cell; None when non-numeric."""
    if isinstance(cell, bool):           # bool is an int subclass — never a metric
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(float(cell)) else None
    if isinstance(cell, str):
        s = cell.strip().lstrip("$€£").rstrip("%").replace(",", "").strip()
        try:
            v = float(s)
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    try:                                  # Decimal and other numerics
        v = float(cell)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def cell_values(rows, extra: Optional[Iterable] = None) -> list[float]:
    """All numeric cell values across ``rows`` (list-of-list or list-of-dict),
    plus any ``extra`` known totals (e.g. result row_count, profiled cardinalities)."""
    out: list[float] = []
    for r in (rows or []):
        cells = r.values() if isinstance(r, dict) else r
        for c in cells:
            v = _to_float(c)
            if v is not None:
                out.append(v)
    for e in (extra or []):
        v = _to_float(e)
        if v is not None:
            out.append(v)
    return out


def _grounds(n: Numeral, cell: float) -> bool:
    """Does result ``cell`` support numeral ``n``? Compared on absolute value so a
    "loss of 2.4M" grounds against a -2.4M cell. Two acceptors:

    * **rounding window** — the half-unit implied by the displayed precision, so
      "2M" grounds a 2.45M cell (1 sig fig) but "2.49M" needs ~2.49M (3 sig figs);
    * **2 % relative tolerance** — absorbs benign LLM rounding/abbreviation.

    The 1e6-scale bug ("2.49M" vs a 2.49 cell) clears neither and is flagged."""
    target = abs(n.value)
    c = abs(cell)
    half = 0.5 * (10.0 ** (-n.decimals)) * n.multiplier
    if (target - half) <= c <= (target + half):
        return True
    denom = c if c else 1.0
    return abs(target - c) / denom <= 0.02


def verify_finding(finding: str, rows, extra: Optional[Iterable] = None) -> GroundingResult:
    """Verify that every magnitude-bearing numeral in ``finding`` is grounded in a
    real cell of ``rows``. Returns which tokens (if any) are ungrounded."""
    cells = cell_values(rows, extra)
    ungrounded: list[str] = []
    checked = 0
    for n in extract_numerals(finding):
        if not n.enforce:
            continue
        checked += 1
        if not any(_grounds(n, c) for c in cells):
            ungrounded.append(n.text)
    return GroundingResult(grounded=not ungrounded, ungrounded=ungrounded, checked=checked)


def ground_numerals(finding: str, rows, extra: Optional[Iterable] = None) -> list[dict]:
    """Per-numeral grounding map for the "show the receipt" UI.

    Where :func:`verify_finding` returns only a pass/fail verdict, this returns one
    record *per numeral* in ``finding`` so a UI can make each number clickable and
    show exactly which result cell backs it. Reuses the same extraction + matching
    logic, so the verdict here is consistent with the guard that gates the finding.

    Each record::

        {"text": "2.49M",          # the token as written
         "value": 2_490_000.0,     # magnitude-expanded value
         "enforce": True,          # was grounding required for this token?
         "grounded": True,         # for enforced tokens: backed by a real cell?
         "matched_cell": 2_490_000.0}  # the first cell that grounds it, else None

    Non-enforced tokens (percentages, ranks, small counts, calendar years) carry
    ``enforce=False`` / ``grounded=True`` / ``matched_cell=None`` — they are shown as
    "derived, not enforced" rather than flagged, mirroring the conservative policy
    in :func:`extract_numerals`."""
    cells = cell_values(rows, extra)
    out: list[dict] = []
    for n in extract_numerals(finding):
        matched: Optional[float] = None
        grounded = True
        if n.enforce:
            matched = next((c for c in cells if _grounds(n, c)), None)
            grounded = matched is not None
        out.append({
            "text": n.text,
            "value": n.value,
            "enforce": n.enforce,
            "grounded": grounded,
            "matched_cell": matched,
        })
    return out


def numeric_cells_block(rows, limit: int = 40) -> str:
    """A compact, de-duplicated list of the actual numeric result values, for a
    corrective re-grounding prompt. Preserves natural magnitude, sorted descending."""
    seen: list[float] = []
    for v in cell_values(rows):
        if v not in seen:
            seen.append(v)
    seen.sort(key=lambda x: abs(x), reverse=True)
    shown = seen[:limit]
    parts = []
    for v in shown:
        parts.append(str(int(v)) if float(v).is_integer() else f"{v:g}")
    out = ", ".join(parts) if parts else "(no numeric values in the result)"
    if len(seen) > limit:
        out += f", … (+{len(seen) - limit} more)"
    return out
