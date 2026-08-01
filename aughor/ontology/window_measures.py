"""Wave O5 — declared window and semiadditive measures.

**What this moves from post-hoc to by-construction.** "YoY growth", "trailing 7 days" and
"balance at month end" are asked constantly and answered today by the model writing window
SQL per question. The guards catch it when that goes wrong — a semiadditive measure summed
across time is exactly the kind of error the additivity guard exists for — but catching a
wrong answer is strictly worse than not being able to express one. A measure DECLARED as
`semiadditive: last` cannot be summed across periods, because the planner instantiates the
declaration rather than asking for SQL.

The vocabulary is the UC metric-view frame algebra, identified as the reference spec in
docs/GENIE_DOCS_TEARDOWN_2026-07-26.md:

    order       the column the window is ordered by (usually a date)
    range       current · cumulative · trailing · leading · all
    window      how many periods, for trailing/leading
    semiadditive  first | last — which row in a period represents it
    offset      periods back, for period-over-period

**Semiadditive is the one that silently corrupts.** An inventory level or an account
balance is additive across products and *not* across time: summing December's daily
balances gives a number with no meaning, and nothing about the result looks wrong. So
``semiadditive`` is not a formatting hint — it is a claim that the time dimension must be
collapsed by taking one row per period, and :func:`compile_measure` refuses to emit a plain
SUM over one.

**This module builds SQL text, not answers.** It is deterministic and takes no model call.
The compiled fragment is validated by the same paths that validate any other formula, and
a declaration that cannot compile raises with the reason rather than falling back to
free-form generation — a silent fallback would make a declared measure indistinguishable
from an undeclared one, which defeats the whole point of declaring it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

#: How the window extends from the current row.
RANGES: tuple[str, ...] = ("current", "cumulative", "trailing", "leading", "all")

#: Which row in a period represents it, for measures that do not sum across time.
SEMIADDITIVE: tuple[str, ...] = ("first", "last")

Range = Literal["current", "cumulative", "trailing", "leading", "all"]


class MeasureDeclarationError(ValueError):
    """A declaration that cannot compile. Raised rather than silently falling back —
    a declared measure that quietly becomes free-form generation is indistinguishable
    from never having declared it."""


@dataclass(frozen=True)
class WindowMeasure:
    """A measure with a declared time frame."""

    expression: str                       # the base aggregate, e.g. "SUM(gmv_eur)"
    order_by: str = ""                    # the ordering column (required unless range=all)
    range: Range = "current"
    window: Optional[int] = None          # periods, for trailing/leading
    semiadditive: Optional[str] = None    # "first" | "last"
    offset: Optional[int] = None          # periods back, for period-over-period
    partition_by: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.expression.strip():
            raise MeasureDeclarationError("a measure needs an expression")
        if self.range not in RANGES:
            raise MeasureDeclarationError(
                f"unknown range {self.range!r} — known: {list(RANGES)}")
        if self.semiadditive is not None and self.semiadditive not in SEMIADDITIVE:
            raise MeasureDeclarationError(
                f"unknown semiadditive {self.semiadditive!r} — known: {list(SEMIADDITIVE)}")
        if self.range in ("trailing", "leading"):
            if not self.window or self.window < 1:
                raise MeasureDeclarationError(
                    f"range={self.range!r} needs a positive `window` (how many periods)")
        if self.range != "all" and not self.order_by.strip():
            # Without an ordering column a window frame is not merely wrong, it is
            # meaningless — "trailing 7" of an unordered set is not a question.
            raise MeasureDeclarationError(
                f"range={self.range!r} needs `order_by` — a frame over an unordered set "
                f"has no meaning")
        if self.offset is not None and self.offset < 0:
            raise MeasureDeclarationError("`offset` counts periods BACK and cannot be negative")

    def to_dict(self) -> dict:
        return {"expression": self.expression, "order_by": self.order_by,
                "range": self.range, "window": self.window,
                "semiadditive": self.semiadditive, "offset": self.offset,
                "partition_by": list(self.partition_by)}


def _frame(m: WindowMeasure) -> str:
    if m.range == "current":
        return "ROWS BETWEEN CURRENT ROW AND CURRENT ROW"
    if m.range == "cumulative":
        return "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW"
    if m.range == "trailing":
        # n periods INCLUDING the current one: "trailing 7 days" means 7 days, not 8.
        return f"ROWS BETWEEN {int(m.window) - 1} PRECEDING AND CURRENT ROW"
    if m.range == "leading":
        return f"ROWS BETWEEN CURRENT ROW AND {int(m.window) - 1} FOLLOWING"
    return "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING"


def _over(m: WindowMeasure) -> str:
    parts = []
    if m.partition_by:
        parts.append("PARTITION BY " + ", ".join(m.partition_by))
    if m.order_by:
        parts.append(f"ORDER BY {m.order_by}")
    parts.append(_frame(m))
    return "OVER (" + " ".join(parts) + ")"


def compile_measure(m: WindowMeasure) -> str:
    """The SQL fragment a declaration instantiates. Deterministic; no model call.

    A semiadditive measure compiles to FIRST_VALUE/LAST_VALUE rather than the declared
    aggregate: the declaration says the time dimension must be collapsed by taking one row
    per period, so emitting the aggregate would produce exactly the silently-meaningless
    number the declaration exists to prevent.
    """
    m.validate()
    if m.semiadditive:
        inner = _strip_aggregate(m.expression)
        fn = "FIRST_VALUE" if m.semiadditive == "first" else "LAST_VALUE"
        # The frame must be explicit for LAST_VALUE: the SQL default
        # (RANGE UNBOUNDED PRECEDING) makes it return the CURRENT row, which is the
        # single most common window-function bug and produces a plausible wrong number.
        over = _over(WindowMeasure(expression=m.expression, order_by=m.order_by,
                                   range="all", partition_by=m.partition_by))
        return f"{fn}({inner}) {over}"
    if m.offset:
        inner = _strip_aggregate(m.expression)
        over = _over(WindowMeasure(expression=m.expression, order_by=m.order_by,
                                   range="all", partition_by=m.partition_by))
        return f"LAG({inner}, {int(m.offset)}) {over}"
    if m.range == "current" and not m.partition_by:
        return m.expression                      # no frame needed; keep the SQL plain
    return f"{m.expression} {_over(m)}"


def _strip_aggregate(expression: str) -> str:
    """``SUM(balance)`` → ``balance``.

    FIRST_VALUE/LAST_VALUE and LAG take a VALUE, not an aggregate; nesting one inside
    produces a SQL error at best and a wrong grain at worst. Deliberately conservative:
    an expression that is not a single recognised aggregate call is passed through
    untouched, because guessing at a complex expression's inner value is how a formula
    silently changes meaning.
    """
    text = expression.strip()
    lowered = text.lower()
    for fn in ("sum(", "avg(", "min(", "max(", "count("):
        if not lowered.startswith(fn):
            continue
        # The trailing ")" must be the one THIS call opened. Checking `endswith(")")` is
        # not enough and the difference is not cosmetic: `SUM(a) / NULLIF(SUM(b), 0)`
        # starts with "sum(" and ends with ")", and a naive strip turns it into
        # `a) / NULLIF(SUM(b), 0` — which nests into runnable SQL computing something
        # else entirely. Caught by the test written for this function's own docstring.
        depth = 0
        for i, ch in enumerate(text):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    # Closed at the very end ⇒ the whole expression is this one call.
                    return text[len(fn):i].strip() if i == len(text) - 1 else text
        return text
    return text


def period_over_period(expression: str, order_by: str, *, offset: int = 1,
                       partition_by: tuple[str, ...] = ()) -> tuple[str, str]:
    """``(current, prior)`` fragments for a period-over-period comparison.

    Returned as a PAIR rather than a ready-made growth expression, because the division is
    where the interesting decisions live — zero denominators, percent versus ratio,
    absolute versus relative — and baking one in would hide them behind a helper.
    """
    current = WindowMeasure(expression=expression, order_by=order_by, range="current",
                            partition_by=partition_by)
    prior = WindowMeasure(expression=expression, order_by=order_by, range="current",
                          offset=offset, partition_by=partition_by)
    return compile_measure(current), compile_measure(prior)


def describe(m: WindowMeasure) -> str:
    """A one-line, reader-facing description for a prompt or a receipt."""
    m.validate()
    if m.semiadditive:
        return (f"{m.expression} taking the {m.semiadditive} value per period "
                f"(ordered by {m.order_by}) — NOT summable across time")
    if m.offset:
        return f"{m.expression} from {m.offset} period(s) earlier (ordered by {m.order_by})"
    if m.range == "trailing":
        return f"{m.expression} over a trailing {m.window} periods (ordered by {m.order_by})"
    if m.range == "leading":
        return f"{m.expression} over the next {m.window} periods (ordered by {m.order_by})"
    if m.range == "cumulative":
        return f"{m.expression} accumulated to date (ordered by {m.order_by})"
    if m.range == "all":
        return f"{m.expression} over the whole partition"
    return m.expression


def from_declaration(raw: dict) -> WindowMeasure:
    """Build a measure from a stored declaration, validating it."""
    m = WindowMeasure(
        expression=str(raw.get("expression") or ""),
        order_by=str(raw.get("order_by") or ""),
        range=str(raw.get("range") or "current"),      # type: ignore[arg-type]
        window=raw.get("window"),
        semiadditive=raw.get("semiadditive"),
        offset=raw.get("offset"),
        partition_by=tuple(raw.get("partition_by") or ()))
    m.validate()
    return m
