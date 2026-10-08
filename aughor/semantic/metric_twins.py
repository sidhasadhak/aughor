"""A metric that measures exactly what an approved one already does (the user, 2026-10-08: "Why
should we have duplicates?").

theLook carried two pairs: Return rate and Item Return Rate — returned items over all items, one of
them written with ``SAFE_DIVIDE`` — and Gross Margin Percentage and Gross Margin Rate, the same margin
over the same join. Drafts come from several proposers (the industry pack, the profile's north stars,
the Explorer, Ask), each naming a measure its own way, and the only check was on the NAME. So both of
each pair were approved, a card was made of each, and the Executive Cockpit showed the return rate
three times.

Two definitions are one measure when they read the same tables and give the same figure — or the same
figure times a hundred, a share written as a percent — in every one of the last months that has rows.
The figures are measured, never the SQL text compared: ``SAFE_DIVIDE(a, b)`` and ``a / NULLIF(b, 0)``
differ as text and not as numbers, and two different measures agreeing to nine places month after
month is not a coincidence a business has. One statement per definition; no model call.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Optional

#: The complete months read, newest last.
TWIN_MONTHS = 6
#: The fewest months both must have figures in before they are called one measure.
MIN_AGREEING = 3
#: A share written as a fraction or as a percent is the same measure.
_SCALES = (1.0, 100.0, 0.01)


def _months(today: date, n: int = TWIN_MONTHS) -> list:
    """The ``n`` complete calendar months before ``today``'s, oldest first, as windows."""
    from aughor.semantic.metric_time import Window

    out = []
    end = today.replace(day=1)
    for i in range(n):
        start = (end - timedelta(days=1)).replace(day=1)
        out.append(Window(f"m{i}", start, end, as_of=today))
        end = start
    return out[::-1]


def _tables(m: Any) -> frozenset:
    from aughor.semantic import metric_time as mt
    return frozenset(mt.bare_name(t) for t in mt.tables_read(m))


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def agree(mine: list, theirs: list) -> bool:
    """Every month both read gives one figure (at one scale), and there are enough of them."""
    pairs = [(a, b) for a, b in zip(mine, theirs) if a is not None and b is not None]
    if len(pairs) < MIN_AGREEING:
        return False
    return any(all(_same(a * k, b) for a, b in pairs) for k in _SCALES)


def _figures(m: Any, windows: list, run_sql: Callable[[str], tuple], dialect: str) -> tuple[Optional[list], str]:
    from aughor.briefing.ranges import read_value
    from aughor.semantic import metric_time as mt

    if not mt.declared(m):
        return None, "its dates are not set"
    rows, why = mt.run_measure(m, windows, run_sql, dialect=dialect)
    if why:
        return None, why
    got = {r["window"]: r for r in rows}
    return [read_value(got.get(w.label)) for w in windows], ""


def candidates(m: Any, approved: list) -> list:
    """The approved definitions that read exactly the tables ``m`` reads — the only ones it can be
    one measure with. None means nothing needs measuring."""
    tables = _tables(m)
    return [a for a in approved if a.name != m.name and tables and _tables(a) == tables]


NO_TWIN = {"twin": None, "months": 0, "checked": True, "why": ""}


def twin_of(m: Any, approved: list, *, run_sql: Callable[[str], tuple], dialect: str, today: date) -> dict:
    """The approved definition ``m`` measures exactly, if any: ``{"twin", "months", "checked", "why"}``.

    ``twin`` is ``{"name", "label"}`` or None. ``checked`` is False — with ``why`` — when ``m``'s own
    figures could not be read: not known is said, never taken for "no twin"."""
    candidates_ = candidates(m, approved)
    if not candidates_:
        return dict(NO_TWIN)
    windows = _months(today)
    mine, why = _figures(m, windows, run_sql, dialect)
    if mine is None:
        return {"twin": None, "months": 0, "checked": False, "why": why}
    for a in candidates_:
        theirs, _ = _figures(a, windows, run_sql, dialect)
        if theirs is not None and agree(mine, theirs):
            months = sum(1 for x, y in zip(mine, theirs) if x is not None and y is not None)
            return {"twin": {"name": a.name, "label": a.label or a.name}, "months": months,
                    "checked": True, "why": ""}
    return dict(NO_TWIN)


def said(m: Any, verdict: dict) -> str:
    """The refusal, in words a person approving can act on."""
    twin = verdict["twin"]
    return (f"{m.label or m.name} measures exactly what {twin['label']} measures — the same figure in "
            f"each of the last {verdict['months']} months, from the same tables. {twin['label']} is "
            "already approved: open it instead, or approve this anyway if the two are meant to differ")
