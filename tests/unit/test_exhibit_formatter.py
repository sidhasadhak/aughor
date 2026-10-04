"""CP-5 (ROADMAP §3.22) — one reader-facing exhibit formatter, consumed by every door.

Three things are pinned: the RULE (a cell reads as the web's data table reads it — the parity
cases below are the web's own, from `AugTable.tsx` and `lib/format.ts`); the TABLE (three
outcomes, each captioned, whatever is trimmed says so); and the CENSUS — CP-0's two rows,
re-measured on every run by scanning the tree, not a hand-kept list of files: a table for a
reader is built in one place, and an SVG becomes a PNG in one place. CP-5's own falsifier is
"a door has grown its own formatter back"; the Teams door had, the day before this was built.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aughor.answer.exhibit import clean_label, format_cell, reader_table, to_csv

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("column,value,money,expected", [
    ("total", 54496.64009666443, "", "54,496.64"),        # the defect CP-4 named, on every door
    ("orders", 180925, "", "180,925"),
    ("avg_items", 39.97968526236183, "", "39.9797"),      # under 1,000: up to four places
    ("revenue", 54496.64009666443, "$", "$54,496.64"),    # an amount, to the cent
    ("revenue", 359224.3, "€", "€359,224.30"),            # never drops its last zero
    ("amount", "711231.2900000175", "$", "$711,231.29"),  # DuckDB DECIMAL arrives as text
    ("refund_chf", 2380000, "€", "CHF 2,380,000.00"),     # the column's own currency wins
    ("return_rate", 0.1003, "", "10.0%"),                 # a ratio, ×100
    ("pct_change", -60.89, "", "-60.9%"),                 # already a percent
    ("order_year", 2024, "", "2024"),                     # a period key is a label
    ("month", 6, "", "6"),
    ("customer_id", 12345, "", "12345"),                  # an id is not a quantity
    ("week_start", "2025-04-01 00:00:00", "", "2025-04-01"),
    ("region", None, "", "—"),
    ("region", "East", "", "East"),
])
def test_a_cell_reads_as_the_web_table_reads_it(column, value, money, expected):
    assert format_cell(column, value, money_symbol=money) == expected


def test_headers_are_labels():
    assert clean_label("total_revenue") == "Total Revenue"
    assert clean_label("aov_usd") == "AOV USD"


def test_a_table_is_whole_a_captioned_preview_or_a_caption():
    cols = ["region", "total"]
    whole = reader_table(cols, [["East", 54496.64009666443], ["We|st", 9]], max_cols=6,
                         max_rows=10, preview_rows=5, rest="attached as CSV")
    assert whole.markdown == ("| Region | Total |\n| --- | --- |\n| East | 54,496.64 |\n"
                              "| We\\|st | 9 |")
    assert (whole.shown, whole.total, whole.caption) == (2, 2, "")

    long = reader_table(cols, [[f"r{i}", i * 1000] for i in range(60)], max_cols=6,
                        max_rows=10, preview_rows=5, rest="attached as CSV")
    assert long.markdown.count("\n| r") == 5 and "| r4 | 4,000 |" in long.markdown
    assert long.caption == "_Showing 5 of 60 rows — attached as CSV._"

    wide = reader_table([f"c{i}" for i in range(8)], [[1] * 8, [2] * 8], max_cols=6,
                        max_rows=10, preview_rows=5, rest="in the report")
    assert wide.wide and wide.markdown == "_2 rows × 8 columns — in the report._"


def test_the_csv_keeps_values_as_stored():
    assert to_csv(["a", "b"], [[54496.64009666443, None], {"a": "x,y", "b": 1}]) == \
        'a,b\n54496.64009666443,\n"x,y",1'


def test_the_table_door_formats_for_a_caller_that_cannot():
    """`POST /exhibits/table` is `reader_table` with a URL — what the TypeScript bot calls."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import charts

    app = FastAPI()
    app.include_router(charts.router)
    client = TestClient(app)
    grid = {"columns": ["region", "total"], "rows": [["East", 54496.64009666443], ["West", 9]]}
    r = client.post("/exhibits/table", json=grid)
    assert r.status_code == 200
    assert r.json() == {"show": True, "csv": None, "shown": 2, "total": 2,
                        "markdown": "| Region | Total |\n| --- | --- |\n| East | 54,496.64 |\n| West | 9 |"}
    one = client.post("/exhibits/table", json={"columns": ["revenue"], "rows": [[1.2e6]]})
    assert one.json()["show"] is False                    # the sentence already said it
    long = client.post("/exhibits/table", json={**grid, "rows": [["r", i] for i in range(12)]})
    assert long.json()["shown"] == 5 and long.json()["csv"].startswith("region,total\nr,0\n")


# ── CP-0's two rows, re-measured ────────────────────────────────────────────────────────

def _door_sources():
    """Every Python module and every TypeScript source of the Slack bot (tests aside)."""
    yield from (ROOT / "aughor").rglob("*.py")
    yield from (p for p in (ROOT / "bots/slack/src").glob("*.ts") if not p.name.endswith(".test.ts"))


#: A GFM table's rule row, and the join that lays a row's cells out between pipes.
_RULE = re.compile(r"""["']---["']|["']---\|["']""")
_PIPE_JOIN = re.compile(r"""["'] \| ["']|["'] \|["']|["']\| ["']""")
#: Places that build a pipe table NOT for a reader — each with its reason.
_NOT_FOR_A_READER = {
    "aughor/tools/data_catalog.py": "sample rows for the MODEL's prompt (CP-0's own note)",
}
#: An SVG made into a PNG: the Python and TypeScript resvg bindings, and the backends it replaced.
_RASTER = re.compile(r"""^\s*(?:import|from)\s+(?:resvg_py|cairosvg)\b|renderPM\.draw|from ["']@resvg/"""
                     r"""|new Resvg\(""", re.M)


def test_a_table_for_a_reader_is_built_in_one_place():
    builders = {str(p.relative_to(ROOT)) for p in _door_sources()
                if _RULE.search(t := p.read_text(encoding="utf-8")) and _PIPE_JOIN.search(t)}
    assert builders - set(_NOT_FOR_A_READER) == {"aughor/answer/exhibit.py"}


def test_an_svg_becomes_a_png_in_one_place():
    rasterizers = {str(p.relative_to(ROOT)) for p in _door_sources()
                   if _RASTER.search(p.read_text(encoding="utf-8"))}
    assert rasterizers == {"aughor/export/echarts.py"}
