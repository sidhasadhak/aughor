"""The platform's number-formatting AUTHORITY — one precision policy, one place.

Aughor quotes its own grounded numbers verbatim: the explorer copies a value out of a real
result cell, the narrator copies it out of the finding, and the frontend copies it out of the
prose ("never invent a number"). That chain is what makes the numbers trustworthy — and it is
also why a single raw ``float64`` repr entering at the top surfaces, unchanged, in a headline:

    verdict: "…mature-rated content … is 43.959061407888164%."

Rounding at the render boundary alone cannot fix that, because by then the digits are part of
a sentence the model wrote. So the policy is applied at BOTH ends:

* **Prevent** — :func:`rows_for_prompt` rounds every cell on the way INTO an LLM prompt, so the
  model never sees 17 significant digits and cannot copy them.
* **Guarantee** — :func:`round_long_decimals` collapses over-long runs in prose on the way OUT
  (at every persist/response boundary), so a number that slips through is still corrected.

THE POLICY (mirror it in ``web/lib/format.ts`` if you change it here):

    |v| >= 1   →  2 decimal places      43.959061407888164 → 43.96      (percent, currency, counts)
    |v| <  1   →  6 decimal places      0.20829576194770064 → 0.208296  (small rates survive)
    exact ints →  no decimal point      39.99999999998568   → 40

Only runs of 4+ fractional digits are touched, so a deliberate "3.14" or "$1.50" is left alone.
Everything here is deterministic, idempotent, and safe on None/empty — a formatter must never be
the thing that raises.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

__all__ = [
    "round_number",
    "round_cell",
    "round_long_decimals",
    "unify_percent_fractions",
    "rows_for_prompt",
]

# A decimal run long enough to be float noise rather than an intended precision.
_LONG_DECIMAL_RE = re.compile(r"-?\d+\.\d{4,}")
# A pure-numeric STRING with a long decimal run — DuckDB hands DECIMAL columns back as
# Decimal or str, which a float-only check misses ('711231.2900000175' stayed raw).
_NUMERIC_STR_RE = re.compile(r"-?\d+\.\d{4,}")


def _apply_policy(v: float) -> float | int:
    """THE precision rule. Returns an int when the result is whole, so 40.0 renders as '40'."""
    r = round(v, 2) if abs(v) >= 1 else round(v, 6)
    return int(r) if r == int(r) else r


def round_number(v: Any) -> Any:
    """Round ONE value, returning a *number* (not a string) when it is numeric.

    Use where the value stays structured — a row tuple headed for a prompt, a JSON payload.
    Bools, text, None and non-numeric strings pass through untouched (a bool is not a number
    for our purposes: ``isinstance(True, int)`` would otherwise mangle it)."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        # NaN/±inf have no meaningful rounding — hand them back as-is.
        if v != v or v in (float("inf"), float("-inf")):
            return v
        return _apply_policy(v)
    if isinstance(v, str) and _NUMERIC_STR_RE.fullmatch(v.strip()):
        return _apply_policy(float(v.strip()))
    return v


def round_cell(v: Any) -> str:
    """Round ONE value to its DISPLAY STRING — for a rendered table cell or a text table."""
    return str(round_number(v))


def round_long_decimals(text: str) -> str:
    """Collapse over-long decimal runs embedded in PROSE, so a report never ships a raw
    17-significant-digit float in a headline/narrative. Surrounding text, already-short
    numbers, and $/%/comma grouping are untouched."""
    if not text:
        return text
    return _LONG_DECIMAL_RE.sub(lambda m: str(_apply_policy(float(m.group(0)))), text)


# An explicit percent in prose — the NUMBER before a "%" ("20.8%", "5 %"). The lookbehind keeps it
# from matching a digit inside a larger token.
_EXPLICIT_PCT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")
# A bare decimal fraction ("0.208", ".208") NOT already a percent, currency, or percentage-points, and
# not a fragment of a larger number (the lookbehind excludes a preceding word char / dot / $).
_BARE_FRACTION_RE = re.compile(r"(?<![\w.$])(0?\.\d+)(?!\s*%)(?!\s*pp\b)")


def unify_percent_fractions(text: str) -> str:
    """Normalize a percentage written BOTH ways in the same prose — an explicit "20.8%" AND its bare
    fraction "0.208" — to the percent form, so one value never reads as two. SELF-GROUNDED: a fraction
    is rewritten only when its ×100 value is ALSO present in the text as an explicit percent, reusing
    that twin's exact number string — so an unrelated sub-1 number (a correlation 0.82, a p-value 0.05,
    a $0.50 price) is never touched. The caller gates on the metric being a percentage; this adds a
    second, textual guard."""
    if not text or "%" not in text:
        return text
    # Both regexes capture only well-formed decimal literals, so float() can't raise here.
    pct_str: dict[float, str] = {}
    for m in _EXPLICIT_PCT_RE.finditer(text):
        pct_str.setdefault(round(float(m.group(1)), 1), m.group(1))
    if not pct_str:
        return text

    def _sub(m):
        frac = m.group(1)
        v = float(frac)
        if 0 < v < 1:
            twin = pct_str.get(round(v * 100, 1))
            if twin is not None:
                return f"{twin}%"
        return frac

    return _BARE_FRACTION_RE.sub(_sub, text)


def rows_for_prompt(rows: Any, limit: int = 20) -> str:
    """Serialize result rows for an LLM prompt with the precision policy already applied.

    THE PREVENTION SEAM. Replaces the ``"\\n".join(str(r) for r in rows[:20])`` idiom, which fed
    raw ``float64`` reprs straight into the prompt — and the interpret prompts then *require* the
    model to quote a number that appears in the result, so it faithfully copied all 17 digits into
    a finding that was persisted and later narrated. Rounding here means the long form never
    exists downstream.

    The rendered shape is deliberately unchanged (a tuple repr per line) — only the digits are
    shorter — so prompts stay byte-comparable apart from the fix."""
    if not rows:
        return ""
    out: list[str] = []
    for r in list(rows)[:limit]:
        if isinstance(r, dict):
            out.append(str({k: round_number(v) for k, v in r.items()}))
        elif isinstance(r, (list, tuple)):
            vals = [round_number(c) for c in r]
            out.append(str(vals) if isinstance(r, list) else str(tuple(vals)))
        else:
            out.append(str(round_number(r)))
    return "\n".join(out)
