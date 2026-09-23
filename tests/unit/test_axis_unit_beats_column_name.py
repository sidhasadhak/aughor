"""A currency symbol on an axis is a claim about what the numbers ARE.

From a real report, 2026-09-23. Its own headline was *"No cost optimisation target found:
metric is item count, every dimension splits proportionally"*, and its executive summary
said plainly that intake recorded `SUM(cost)` while the executed definition was
`COUNT(id)`. Every chart in it then drew that count as **$36.3K**, because the column was
named `total_cost_of_goods_sold_cogs` and `isMoneyColumn` reads the NAME.

So the charts contradicted the finding they were illustrating — and the column's unit was
not a way out, because only a `currency:` unit was ever read. Declaring `count` produced
byte-identical SVG.

The rule these pin is the one `orgsettings.resolve_currency` applies one layer up: a
declaration outranks an inference from a name, because nothing converts and a wrong symbol
is a wrong figure. The name guess is kept for columns that declare nothing, which is most
of them.

These run the REAL SSR bundle, so they also fail on a stale one.
"""
from __future__ import annotations

import shutil as _shutil
from pathlib import Path as _Path

import pytest

_BUNDLE = _Path(__file__).resolve().parents[2] / "aughor" / "export" / "chart_ssr.bundle.mjs"
_ssr = pytest.mark.skipif(not _shutil.which("node") or not _BUNDLE.exists(),
                          reason="chart SSR needs node + chart_ssr.bundle.mjs")

COLS = ["product_category", "total_cost_of_goods_sold_cogs"]
ROWS = [["Intimates", 36294], ["Jeans", 34602], ["Dresses", 14568]]


def _svg(units=None, symbol="$"):
    from aughor.export.echarts import render_chart_svg
    return render_chart_svg(COLS, ROWS, "bar", "COGS by Product Category",
                            units=units, money_symbol=symbol) or ""


def _has_currency(svg: str) -> bool:
    return any(sym in svg for sym in ("$", "€", "£", "¥"))


@_ssr
@pytest.mark.parametrize("unit", ["count", "items", "rows", "units"])
def test_a_declared_NON_currency_unit_strips_the_money_symbol(unit):
    """The defect, as a test. A money-NAMED column holding a count must not render as money
    once the count is declared — whatever the name reads like."""
    assert not _has_currency(_svg({COLS[1]: unit})), f"unit {unit!r} must beat the name"


@_ssr
def test_a_column_that_declares_NOTHING_keeps_the_name_guess():
    """The guard against over-correcting. Most columns declare no unit, and a money-named
    one should still render as money — removing the guess would strip the symbol from every
    genuine revenue chart in the product."""
    assert _has_currency(_svg(None))


@_ssr
@pytest.mark.parametrize("code,symbol", [("USD", "$"), ("EUR", "€")])
def test_a_declared_CURRENCY_still_names_its_own_symbol(code, symbol):
    """`currency:` is a declaration too, and the more specific one: it says which money,
    not merely that it is money."""
    assert symbol in _svg({COLS[1]: f"currency:{code}"})


@_ssr
def test_the_axis_title_keeps_COGS_as_an_acronym():
    """`cogs` was missing from the abbreviation list, so the axis read "Total Cost Of Goods
    Sold Cogs" — a term of art title-cased into a word. Whole-word only, and entries that
    are also English words (mom, wow, asp) stay OUT however common they are as shorthand."""
    svg = _svg({COLS[1]: "count"})
    assert "Sold COGS" in svg and "Sold Cogs" not in svg


# ── the date axis follows the series' grain ──────────────────────────────────────

def _x_labels(col: str, dates: list[str]) -> list[str]:
    import re
    from aughor.export.echarts import render_chart_svg
    svg = render_chart_svg([col, "n"], [[d, 1300] for d in dates], "line", "t") or ""
    return re.findall(r'>([A-Z][a-z]{2} \d{1,4}|\d{4})<', svg)


@_ssr
def test_a_WEEKLY_series_is_not_labelled_by_month():
    """From the same report: 14 weekly points rendered 13 ticks carrying 3 distinct labels
    — "Oct 2023" x4, "Nov 2023" x4, "Dec 2023" x5 — because this axis hardcoded "%b %Y".
    No point on that chart could be identified."""
    weeks = [f"2023-{m:02d}-{d:02d}" for m, d in
             [(10, 1), (10, 8), (10, 15), (10, 22), (10, 29), (11, 5), (11, 12),
              (11, 19), (11, 26), (12, 3), (12, 10), (12, 17), (12, 24), (12, 31)]]
    got = _x_labels("week", weeks)
    assert len(set(got)) > 8, f"a weekly series needs distinguishable ticks, got {sorted(set(got))}"


@_ssr
def test_a_MONTHLY_series_still_reads_by_month():
    """The guard against over-correcting: month grain was never the broken case."""
    got = _x_labels("month", [f"2023-{m:02d}-01" for m in range(1, 13)])
    assert any(lbl.endswith("2023") for lbl in got), got


@_ssr
def test_a_series_crossing_a_YEAR_keeps_the_year():
    """What the old constant was protecting — a bare month is ambiguous across a boundary.
    The instinct was right and applied at the wrong altitude: it fixed the ambiguous case
    by making every case ambiguous."""
    spanning = [f"{y}-{m:02d}-01" for y in (2022, 2023) for m in (1, 4, 7, 10)]
    got = _x_labels("month", spanning)
    assert any("2022" in lbl for lbl in got) and any("2023" in lbl for lbl in got), got
