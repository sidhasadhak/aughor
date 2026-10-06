"""The measured metrics in reading order (ROADMAP §6 item 43(d)) — sales at the top, profit at
the bottom, each industry's own order within. The table used to read in approval order."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as N

from aughor.briefing import reading_order as RO

PACKS = Path(__file__).resolve().parents[2] / "packs"

#: theLook's twelve approved metrics, in the order they were approved (read 2026-10-06).
THELOOK = [("revenue", "Revenue"), ("units_sold", "Units Sold"), ("return_rate", "Return rate"),
           ("gross_margin_percentage", "Gross Margin Percentage"),
           ("average_order_value_aov", "Average Order Value (AOV)"),
           ("session_to_purchase_conversion_rate", "Session-to-Purchase Conversion Rate"),
           ("gross_margin_rate", "Gross Margin Rate"),
           ("average_ship_to_delivery_lead_time", "Average Ship-to-Delivery Lead Time"),
           ("item_return_rate", "Item Return Rate"), ("repeat_purchase_rate", "Repeat Purchase Rate"),
           ("inventory_sell_through_rate", "Inventory Sell-Through Rate"),
           ("net_merchandise_revenue", "Net Merchandise Revenue")]


def _metrics(pairs):
    return [N(name=a, label=b) for a, b in pairs]


def _retail():
    return json.loads((PACKS / "retail" / "industry.json").read_text(encoding="utf-8"))["reading_order"]


def test_thelook_reads_sales_first_and_its_leakage_and_operations_last():
    got = [m.label for m in RO.ordered(_metrics(THELOOK), _retail())]
    assert got == ["Revenue", "Net Merchandise Revenue", "Units Sold", "Average Order Value (AOV)",
                   "Session-to-Purchase Conversion Rate", "Repeat Purchase Rate",
                   "Inventory Sell-Through Rate", "Gross Margin Percentage", "Gross Margin Rate",
                   "Return rate", "Item Return Rate", "Average Ship-to-Delivery Lead Time"]


def test_with_no_industry_the_words_place_profit_last_and_an_unknown_name_in_the_middle():
    got = [m.name for m in RO.ordered(_metrics([
        ("net_profit", ""), ("widgets_flux", ""), ("gross_margin", ""), ("orders", ""), ("revenue", "")]))]
    assert got == ["revenue", "orders", "widgets_flux", "gross_margin", "net_profit"]


def test_an_industry_declared_kind_wins_over_the_words():
    """"Return on ad spend" reads as a return (profit) by its words; retail declares it a rate."""
    ms = _metrics([("roas", "Return on Ad Spend"), ("net_profit", "Net Profit"), ("aov", "AOV")])
    assert RO.kind_by_words("roas", "Return on Ad Spend") == "profit"
    assert [m.name for m in RO.ordered(ms, _retail())] == ["aov", "roas", "net_profit"]


def test_the_longest_name_that_matches_decides_the_entry():
    order = [{"metric": "Revenue", "kind": "sales"}, {"metric": "Units", "kind": "volume"},
             {"metric": "Net Revenue", "aliases": ["net merchandise revenue"], "kind": "sales"}]
    assert RO._declared(order, "net_merchandise_revenue", "")[1] == 2
    assert RO._declared(order, "revenue", "")[1] == 0


def test_a_short_word_matches_whole_words_only():
    assert RO.kind_by_words("carrier_count") == "volume"     # not "arr" → sales
    assert RO.kind_by_words("roadside_visits") == "volume"   # not "roa" → profit


def test_every_shipped_industry_order_names_a_known_kind():
    """Read from disk: a mistyped kind would sit silently in the middle of the table."""
    files = sorted(PACKS.glob("*/industry.json"))
    assert files
    for f in files:
        order = json.loads(f.read_text(encoding="utf-8")).get("reading_order")
        assert order, f"{f.parent.name} declares no reading order"
        for e in order:
            assert e["kind"] in RO.KINDS and e["metric"], (f.parent.name, e)


def test_the_cap_keeps_the_headline_end(monkeypatch):
    """The measured table and the predictions cap ONE list: the reading-ordered one."""
    from aughor.briefing import ranges as R

    approved = [N(name=f"cost_{i}", label="", status="approved", connection="c1") for i in range(R.MAX_METRICS)]
    approved.append(N(name="revenue", label="Revenue", status="approved", connection="c1"))
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None: approved)
    monkeypatch.setattr(RO, "industry_order", lambda conn_id: [])
    got = R.governed_metrics("c1")
    assert got[0].name == "revenue" and len(got[:R.MAX_METRICS]) == R.MAX_METRICS
