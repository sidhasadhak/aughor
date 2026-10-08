"""The measured metrics in reading order (ROADMAP §6 item 43(d)) — sales at the top, profit at
the bottom, each industry's own order within. The table used to read in approval order."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as N

import pytest

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


def _pack(name="retail"):
    return json.loads((PACKS / name / "industry.json").read_text(encoding="utf-8"))


def _retail():
    return _pack()["reading_order"]


def test_thelook_reads_as_an_income_statement_then_what_drives_it():
    """The user, 2026-10-08: e-commerce reads like a profit and loss statement — gross sales, what
    comes off them, net sales, gross profit — and the figures that drive it after."""
    pack = _pack()
    got = [m.label for m in RO.ordered(_metrics(THELOOK), pack["reading_order"], pack["statement"])]
    assert got == ["Revenue", "Return rate", "Item Return Rate", "Net Merchandise Revenue",
                   "Gross Margin Percentage", "Gross Margin Rate", "Units Sold", "Average Order Value (AOV)",
                   "Session-to-Purchase Conversion Rate", "Repeat Purchase Rate",
                   "Inventory Sell-Through Rate", "Average Ship-to-Delivery Lead Time"]
    lines = [RO.line_of(m.name, m.label, pack["reading_order"], pack["statement"])
             for m in RO.ordered(_metrics(THELOOK), pack["reading_order"], pack["statement"])]
    assert lines[:6] == ["gross_sales", "deductions", "deductions", "net_sales", "gross_profit", "gross_profit"]


def test_a_statement_places_the_lines_no_metric_names_by_their_words():
    """A connection with costs and profit reads them where the statement puts them."""
    pack = _pack()
    ms = _metrics([("net_profit", "Net Profit"), ("orders", "Orders"), ("shipping_cost", "Shipping Cost"),
                   ("cogs", "COGS"), ("widgets_flux", ""), ("marketing_spend", "Marketing Spend"),
                   ("opex", "Operating Expenses"), ("gross_sales", "Gross Sales")])
    got = [m.name for m in RO.ordered(ms, pack["reading_order"], pack["statement"])]
    # an unplaced metric sits after the statement, before the figures that drive it
    assert got == ["gross_sales", "cogs", "shipping_cost", "marketing_spend", "opex", "net_profit",
                   "widgets_flux", "orders"]
    assert RO.line_by_words("roas", "Return on Ad Spend") == "marketing"
    assert RO.line_by_words("return_rate") == "deductions"
    assert RO.line_by_words("lead", "Average Ship-to-Delivery Lead Time") == "operations"


def test_without_a_statement_a_metric_carries_no_line_and_the_backbone_is_unchanged():
    assert RO.line_of("revenue", "Revenue", _retail(), ()) is None
    assert [m.name for m in RO.ordered(_metrics([("net_profit", ""), ("revenue", "")]))] == ["revenue", "net_profit"]


def test_with_no_industry_the_words_place_profit_last_and_an_unknown_name_in_the_middle():
    got = [m.name for m in RO.ordered(_metrics([
        ("net_profit", ""), ("widgets_flux", ""), ("gross_margin", ""), ("orders", ""), ("revenue", "")]))]
    assert got == ["revenue", "orders", "widgets_flux", "gross_margin", "net_profit"]


def test_an_industry_declared_kind_wins_over_the_words():
    """"Return on ad spend" reads as a return (profit) by the backbone's words; an industry that
    declares it a rate reads it as one."""
    order = [{"metric": "AOV", "kind": "rate"}, {"metric": "ROAS", "aliases": ["return on ad spend"], "kind": "rate"}]
    ms = _metrics([("roas", "Return on Ad Spend"), ("net_profit", "Net Profit"), ("aov", "AOV")])
    assert RO.kind_by_words("roas", "Return on Ad Spend") == "profit"
    assert [m.name for m in RO.ordered(ms, order)] == ["aov", "roas", "net_profit"]


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
        pack = json.loads(f.read_text(encoding="utf-8"))
        order, statement = pack.get("reading_order"), pack.get("statement")
        assert order, f"{f.parent.name} declares no reading order"
        lines = [RO.line_id(x) for x in statement or []]
        if statement:
            assert all(line in RO.STATEMENT_LINES for line in lines), (f.parent.name, statement)
        for e in order:
            assert e["kind"] in (lines or RO.KINDS) and e["metric"], (f.parent.name, e)


def test_the_cap_keeps_the_headline_end(monkeypatch):
    """The measured table and the predictions cap ONE list: the reading-ordered one."""
    from aughor.briefing import ranges as R

    approved = [N(name=f"cost_{i}", label="", status="approved", connection="c1") for i in range(R.MAX_METRICS)]
    approved.append(N(name="revenue", label="Revenue", status="approved", connection="c1"))
    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda connection_id=None, **k: approved)
    monkeypatch.setattr(RO, "industry_reading", lambda conn_id: ([], []))
    got = R.governed_metrics("c1")
    assert got[0].name == "revenue" and len(got[:R.MAX_METRICS]) == R.MAX_METRICS


# ── every industry's income statement (2026-10-08: SaaS, manufacturing, logistics, airline, delivery) ──

STATEMENT_PACKS = sorted(f.parent.name for f in PACKS.glob("*/industry.json")
                         if json.loads(f.read_text(encoding="utf-8")).get("statement"))


def test_every_industry_with_a_reading_order_reads_as_an_income_statement():
    with_order = sorted(f.parent.name for f in PACKS.glob("*/industry.json")
                        if json.loads(f.read_text(encoding="utf-8")).get("reading_order"))
    assert STATEMENT_PACKS == with_order == ["airline", "food-delivery", "logistics", "manufacturing", "retail", "saas"]


@pytest.mark.parametrize("pack", STATEMENT_PACKS)
def test_a_statement_runs_revenue_to_profit_then_what_drives_it(pack):
    """Revenue first, profit before the drivers, and every metric the pack knows on one of its lines."""
    d = _pack(pack)
    lines = [RO.line_id(x) for x in d["statement"]]
    assert lines[0] == "gross_sales" and "profit" in lines
    assert lines.index("profit") < min(lines.index(x) for x in ("volume", "rate", "operations") if x in lines)
    for m in d.get("metrics", []):
        assert RO.line_of(m["name"], m["name"], d["reading_order"], d["statement"]), (pack, m["name"])


@pytest.mark.parametrize("pack, names, lines", [
    ("saas", ["Operating Income", "Customers", "MRR", "Net Revenue Retention", "R&D Spend", "Hosting Cost",
              "Sales and Marketing Spend", "Gross Margin"],
     ["gross_sales", "cogs", "gross_profit", "marketing", "rd", "profit", "volume", "rate"]),
    ("manufacturing", ["Units Produced", "Operating Income", "Material Cost", "Net Sales", "SG&A", "Scrap Rate"],
     ["net_sales", "cogs", "opex", "profit", "volume", "rate"]),
    ("logistics", ["Cost per Mile", "Operating Ratio", "Fuel Surcharge Revenue", "Driver Wages", "Loads",
                   "On-Time Delivery Rate"],
     ["gross_sales", "cogs", "profit", "volume", "rate", "operations"]),
    ("airline", ["CASM", "Passengers", "Fuel Cost", "Passenger Revenue", "Operating Income", "On-Time Performance",
                 "Yield (Passenger Revenue per RPK/RPM)"],
     ["gross_sales", "cogs", "profit", "volume", "rate", "rate", "operations"]),
    ("food-delivery", ["Orders", "Courier Cost", "Gross Order Value", "Adjusted EBITDA", "Take Rate", "Revenue",
                       "Contribution per Order"],
     ["gross_sales", "net_sales", "fulfilment", "contribution", "profit", "volume", "rate"]),
])
def test_each_industry_reads_its_own_statement(pack, names, lines):
    d = _pack(pack)
    got = RO.ordered(_metrics([(n.lower().replace(" ", "_"), n) for n in names]), d["reading_order"], d["statement"])
    assert [RO.line_of(m.name, m.label, d["reading_order"], d["statement"]) for m in got] == lines


def test_an_industry_names_its_own_lines():
    assert RO.line_label("cogs", _pack("saas")["statement"]) == "Cost of revenue (hosting, support)"
    assert RO.line_label("cogs", _pack("retail")["statement"]) == "Cost of goods sold"
    assert RO.line_label("rd") == "Research and development"


@pytest.mark.parametrize("name, line", [
    ("Net Revenue Retention", "rate"),          # a rate before "net revenue" makes it net sales
    ("Cost per Mile", "rate"), ("CASM", "rate"),  # a unit figure before "cost" makes it a cost
    ("Fuel Surcharge Revenue", "gross_sales"),  # revenue before "fuel" makes it a cost
    ("R&D Spend", "rd"), ("Hosting Cost", "cogs"), ("Driver Wages", "cogs"),
    ("Courier Cost", "fulfilment"), ("Operating Ratio", "profit"), ("G&A Expense", "opex"),
])
def test_the_words_place_a_metric_no_industry_names(name, line):
    """With no declaration to lean on, a metric's own words put it on its line."""
    assert RO.line_by_words(name.lower().replace(" ", "_"), name) == line
