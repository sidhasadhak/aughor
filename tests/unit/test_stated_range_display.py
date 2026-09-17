"""A metric's figures read at the scale its unit/range text states — on the KPI tiles and in the Briefing's moves.

`business_profile/validate.py::stated_range` reads a metric's `unit_or_range` as the (kind, lo, hi) the value audit
holds it to. The display layer read the same text with regexes of its own (measured 2026-09-17 on `7562c75e`):

- `web/components/brief/metricFormat.ts` held any text containing "ratio" to 0..1, so an inventory turnover of 5
  ('ratio (units sold per unit avg. inventory)') and a net review ratio of -0.2 ('ratio -1 to 1') never showed; it
  read "0-1000" as "0-100", so a $404 AOV ('ratio 0-1000 (USD per order)') never showed; and it read the airline
  package's 'ratio 0..1 (0..100%)' as a percent, so a 0.82 load factor showed "0.8%".
- `aughor/knowledge/metric_moves.py` phrased a move as a percent whenever the name or unit said percent, ratio,
  rate, margin, sentiment or share, multiplying anything up to 1.5 by 100: a 'ratio 0..∞' turnover moving 4 → 6
  read "from 4% to 6%", and a 'percent 0-100' defect rate moving 1.2 → 2.2 read "from 120% to 2%".

GET /business-profile now ships the reading beside the text (`stated_range` on each north-star metric), the tiles
format by it, and the moves read it: a figure is a percent exactly when its text states a 0..1 or 0..100 rate.
The web suite (`web/components/brief/metricFormat.test.ts`) formats every range the packages ship by the reading in
`statedRanges.fixture.json`; the test below holds that file to what the route ships.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from aughor.business_profile.validate import stated_range
from aughor.knowledge.metric_moves import Move, build_move_finding
from tests.unit.test_sane_range_reading import SHIPPED

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "components" / "brief" / "statedRanges.fixture.json"

#: Unit strings the live deployment's profiles carry (the profile ledger and data/business_profile_*.json, read-only,
#: 2026-09-17), with the metric each belongs to — the shapes the display misread, and the rates it read right.
LIVE = [
    ("Inventory Turnover (by product-month)", "ratio (units sold per unit avg. inventory)"),
    ("Inventory Turnover (by SKU)", "ratio (units sold / avg units in stock)"),
    ("Average Order Value (AOV)", "ratio 0-1000 (USD per order)"),
    ("Net Review Ratio", "ratio -1 to 1 (healthy: >0.2)"),
    ("Defect Rate", "percent 0-100 (measured ≈ 2.2)"),
    ("Average Popularity by Genre", "score 0-100 (measured ≈ 48.16)"),
    ("Marketing ROAS by Channel", "ratio 0-∞ (measured ≈ 5.27)"),
    ("Average CSAT Score", "1-5 scale (measured ≈ 4.08)"),
    ("Average Track Duration Trend", "minutes (1-10) (measured ≈ 4.25)"),
    ("Item Return Rate", "ratio 0-1 (measured ≈ 0.26)"),
    ("Top Product Revenue Share", "ratio 0-1, typically 0.20-0.50 for a 6-product catalog (measured ≈ 0.17)"),
    ("Average Order Value (AOV)", "EUR (positive magnitude) (measured ≈ 404.11)"),
]

#: Every (metric, text) the display is measured over: each range a package ships, then the live shapes.
MEASURED = [(metric, text) for _, metric, _, text in SHIPPED] + LIVE


def _reading(text: str) -> dict:
    kind, lo, hi = stated_range(text)
    return {"kind": kind, "lo": lo, "hi": hi}


# ── The route ships the reading ──────────────────────────────────────────────────────────────────────────────


def test_the_profile_route_ships_each_metrics_reading_beside_its_text(tmp_path, monkeypatch):
    from aughor.business_profile import store
    from aughor.routers.profile import get_business_profile

    monkeypatch.setattr(store, "_DATA_DIR", tmp_path / "profiles")
    metrics = [{"name": metric, "unit_or_range": text, "value_sql": "SELECT 1"} for metric, text in MEASURED]
    metrics.append({"name": "Unit never stated", "value_sql": "SELECT 1"})
    store._family().put("conn", {"profile": {"industry": "Retail", "north_star_metrics": metrics}})

    served = get_business_profile("conn", None)["profile"]["north_star_metrics"]

    assert [m.get("stated_range") for m in served] == [_reading(text) for _, text in MEASURED] + [_reading("")]


def test_the_web_suite_formats_by_the_readings_the_route_ships():
    """The fixture is the route's output for every measured text — regenerate it, never hand-edit it:
    AUGHOR_WRITE_STATED_RANGES=1 uv run pytest tests/unit/test_stated_range_display.py -k web_suite"""
    readings = {text: _reading(text) for _, text in MEASURED}
    if os.environ.get("AUGHOR_WRITE_STATED_RANGES"):
        FIXTURE.write_text(json.dumps(readings, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    assert FIXTURE.is_file(), f"{FIXTURE} is missing — see this test's docstring"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == readings, (
        "statedRanges.fixture.json is not what GET /business-profile ships — regenerate it (see this test's docstring)")


# ── A move is phrased at the scale its text states ───────────────────────────────────────────────────────────


def _phrased(name: str, text: str, start: float, end: float, currency: str = "USD") -> tuple[str, str]:
    finding = build_move_finding(name, text, Move(start=start, end=end, rel=(end - start) / abs(start),
                                                  direction="up" if end >= start else "down", points=6), currency)
    phrase = re.search(r" has (?:risen|fallen) from (\S+) to (\S+) \(", finding["finding"])
    assert phrase, finding["finding"]
    return phrase.group(1), phrase.group(2)


def _figure(token: str) -> float:
    return float(token.lstrip("$€£¥₹").rstrip("%").replace(",", ""))


@pytest.mark.parametrize("name, text", MEASURED, ids=[f"{m}: {t[:40]}" for m, t in MEASURED])
def test_a_move_is_a_percent_exactly_when_its_text_states_a_rate(name, text):
    kind = stated_range(text)[0]
    if kind == "ratio01":
        assert _phrased(name, text, 0.25, 0.35) == ("25%", "35%")
    elif kind == "pct100":
        assert _phrased(name, text, 25.0, 35.0) == ("25%", "35%")
    else:
        start, end = _phrased(name, text, 4.0, 6.0)
        assert not start.endswith("%") and not end.endswith("%"), (start, end)
        assert (_figure(start), _figure(end)) == (4.0, 6.0)


def test_the_live_misreads_are_phrased_at_their_scale():
    assert _phrased("Inventory Turnover (by product-month)", "ratio (units sold per unit avg. inventory)", 4.0, 6.5) \
        == ("4", "6.5")
    assert _phrased("Net Review Ratio", "ratio -1 to 1 (healthy: >0.2)", 0.2, 0.35) == ("0.2", "0.35")
    assert _phrased("Defect Rate", "percent 0-100 (measured ≈ 2.2)", 1.2, 2.2) == ("1%", "2%")
    assert _phrased("Average Order Value (AOV)", "ratio 0-1000 (USD per order)", 404.11, 458.61, "EUR") \
        == ("€404", "€459")
    assert _phrased("Load Factor", "ratio 0..1 (0..100%); industry-typical 0.75–0.90.", 0.78, 0.86) == ("78%", "86%")


def test_a_return_on_spend_is_neither_a_percent_nor_money():
    # "Spend" and "Revenue" in a name read as money; the unit says ratio and names no currency.
    assert _phrased("ROAS (Return on Ad Spend) by Channel", "ratio 0..∞ (typical 1–10x)", 4.0, 6.0) == ("4", "6")
    assert _phrased("Net Revenue Retention (NRR / NDR)", "ratio, typically 0.8..1.4", 1.1, 1.25) == ("1.1", "1.25")


def test_a_unit_is_read_where_the_text_states_it_not_from_its_commentary():
    block_hours, hours = next((m, t) for _, m, _, t in SHIPPED if "Block Hours" in m)
    mrr = next(t for _, m, _, t in SHIPPED if m.startswith("Monthly / Annual"))
    # "Any value > 24 is impossible" closes the hours unit; it is prose, not a currency.
    assert _phrased(block_hours, hours, 11.2, 12.4) == ("11.2", "12.4")
    # …while a unit that says "currency" without naming one still reads as the business's money.
    assert _phrased("Monthly / Annual Recurring Revenue (MRR / ARR)", mrr, 2_847_126.0, 3_100_000.0, "EUR") \
        == ("€2,847,126", "€3,100,000")


def test_a_rate_series_on_the_other_scale_still_reads_as_its_percent():
    # A 0..1 rate whose chart_sql came out on 0..100 was phrased "45%" before the reading and still is.
    assert _phrased("Repeat Purchase Rate", "ratio 0-1", 45.0, 52.0) == ("45%", "52%")
