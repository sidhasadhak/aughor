"""The order a connection's measured metrics are read in (ROADMAP §6 item 43(d)).

The user, on the Briefing's measured table: sales at the top, net profit (or its like) at the
bottom, and each industry with an order in which its metrics make most sense together. The
table had been in the order the definitions were approved, which is an accident of history.

Two layers, one key:

* **A kind per metric**, on one backbone every industry shares — sales, volume, averages and
  rates, margin, cost and leakage, operations, profit. An industry DECLARES the kind of the
  metrics it knows (`reading_order` in its `industry.json`); any other metric is placed by the
  words in its name, and one whose name says nothing stays in the middle.
* **Within a kind**, the industry's declared position, then the order of approval — so two
  metrics nothing distinguishes keep the order they had.

The order also decides which metrics a Briefing past its cap measures: the cap keeps the top of
the list, which is now the headline end rather than the oldest approvals.

**An income statement** (the user, 2026-10-08: rank the metrics so they read like a profit and
loss statement, e-commerce first). An industry that declares a `statement` in its
`industry.json` reads in ITS order of statement lines instead of the backbone — gross sales,
discounts and returns, net sales, cost of goods, gross profit, fulfilment, marketing,
contribution, operating expenses, profit, then the figures that drive them — and its
`reading_order` kinds name those lines. Each measured figure then carries its line, so the table
can say which part of the statement it is.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence, TypeVar

#: The backbone, top to bottom. An industry's `reading_order` names one of these per entry.
KINDS: tuple[str, ...] = ("sales", "volume", "rate", "margin", "cost", "operations", "profit")
_RANK = {k: i for i, k in enumerate(KINDS)}
#: Where a metric whose kind nothing names sits: after the rates, before margin.
_UNPLACED = _RANK["rate"] + 0.5

#: Words that place a metric no industry names. Checked in THIS order, because a name often
#: carries two: "Gross Margin Rate" is a margin, "Return rate" a leakage, "Average Ship-to-
#: Delivery Lead Time" an operations figure, "Average Order Value" an average — not an order count.
_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("margin", ("margin",)),
    ("profit", ("profit", "net income", "ebitda", "earnings", "operating income",
                "return on assets", "return on equity", "return on ad spend", "roa", "roe")),
    ("cost", ("cost", "cogs", "expense", "discount", "refund", "return", "returns", "churn",
              "cancellation", "cancel", "charge off", "charge-off", "write off", "delinquen",
              "past due", "noncurrent", "loss", "spend", "cac")),
    ("operations", ("lead time", "delivery time", "transit", "dwell", "cycle time", "downtime",
                    "utilization", "days", "hours")),
    ("rate", ("average", "avg", "aov", "per ", "conversion", "repeat", "retention", "sell through",
              "rate", "ratio", "share", "yield", "frequency", "arpu", "arpa")),
    ("sales", ("revenue", "sales", "gmv", "gross merchandise", "bookings", "arr", "mrr", "turnover")),
    ("volume", ("orders", "order count", "units", "items sold", "transactions", "customers", "users",
                "accounts", "sessions", "visits", "shipments", "passengers", "flights", "volume",
                "count", "number of", "throughput")),
)


#: The lines of an income statement, top to bottom, then what drives it — the words a table shows.
#: An industry's `statement` orders the ones it uses.
STATEMENT_LINES: dict[str, str] = {
    "gross_sales": "Gross sales", "deductions": "Discounts and returns", "net_sales": "Net sales",
    "cogs": "Cost of goods sold", "gross_profit": "Gross profit", "fulfilment": "Fulfilment and payment",
    "marketing": "Marketing", "contribution": "Contribution", "opex": "Operating expenses",
    "profit": "Profit", "volume": "Volume", "rate": "Rates and averages", "operations": "Operations",
}

#: Words that place a metric on a statement line. Checked in THIS order: "Return on Ad Spend" is
#: marketing before "return" makes it a deduction; "Gross Margin Rate" a gross profit before "rate"
#: makes it a ratio; "Net Merchandise Revenue" net sales before "revenue" makes it gross; and a
#: "Ship-to-Delivery Lead Time" an operations figure before "ship" makes it a fulfilment cost.
_STATEMENT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("contribution", ("contribution",)),
    ("gross_profit", ("gross margin", "gross profit", "product margin", "margin")),
    ("profit", ("net profit", "net income", "operating income", "operating profit", "ebitda", "ebit",
                "earnings", "profit")),
    ("net_sales", ("net revenue", "net sales", "net merchandise")),
    ("marketing", ("return on ad spend", "roas", "ad spend", "advertising", "marketing", "cac",
                   "acquisition cost", "cost per acquisition", "cpa", "cpc", "cpm")),
    ("deductions", ("discount", "discounts", "refund", "refunds", "return", "returns", "cancellation",
                    "cancellations", "cancel", "chargeback", "chargebacks", "allowance")),
    ("operations", ("lead time", "delivery time", "transit", "dwell", "cycle time", "downtime",
                    "utilization", "days", "hours")),
    ("fulfilment", ("shipping", "fulfilment", "fulfillment", "freight", "postage", "packaging",
                    "payment fee", "payment fees", "processing fee", "transaction fee", "marketplace fee",
                    "3pl", "warehousing")),
    ("cogs", ("cogs", "cost of goods", "cost of sales", "landed cost", "product cost", "unit cost", "cost")),
    ("opex", ("operating expense", "operating expenses", "opex", "overhead", "salaries", "payroll", "rent",
              "expense", "expenses")),
    ("rate", ("average", "avg", "aov", "per ", "conversion", "repeat", "retention", "sell through",
              "rate", "ratio", "share", "yield", "frequency", "arpu", "arpa", "turnover", "turns")),
    ("gross_sales", ("revenue", "sales", "gmv", "gross merchandise", "bookings")),
    ("volume", ("orders", "order count", "units", "items sold", "transactions", "customers", "users",
                "accounts", "sessions", "visits", "shipments", "volume", "count", "number of")),
)


def _text(*parts: Optional[str]) -> str:
    joined = " ".join(p for p in parts if p)
    return " " + re.sub(r"[_\-/]+", " ", joined.lower()).strip() + " "


def _has(text: str, word: str) -> bool:
    """A whole-word hit, so "arr" is not found in "carrier" nor "roa" in "road"."""
    return re.search(rf"(?<![a-z0-9]){re.escape(word.strip())}(?![a-z0-9])", text) is not None


def kind_by_words(name: str, label: str = "") -> Optional[str]:
    text = _text(name, label)
    for kind, words in _WORDS:
        if any(_has(text, w) for w in words):
            return kind
    return None


def line_by_words(name: str, label: str = "") -> Optional[str]:
    """The statement line a metric's name places it on, or None."""
    text = _text(name, label)
    for line, words in _STATEMENT_WORDS:
        if any(_has(text, w) for w in words):
            return line
    return None


def _declared(order: Sequence[dict], name: str, label: str,
              valid: Optional[dict] = None) -> tuple[Optional[str], Optional[int]]:
    """The industry's kind and position for this metric, when one of its entries names it.
    The LONGEST name that matches wins: "Net Merchandise Revenue" is the net-revenue entry's,
    though the plain "Revenue" entry's name is in it too."""
    text = _text(name, label)
    best: tuple[int, int] | None = None                 # (matched length, position)
    for pos, entry in enumerate(order):
        for n in (entry.get("metric", ""), *(entry.get("aliases") or [])):
            words = _text(n).strip()
            if words and _has(text, words) and (best is None or len(words) > best[0]):
                best = (len(words), pos)
    if best is None:
        return None, None
    kind = order[best[1]].get("kind")
    return (kind if kind in (_RANK if valid is None else valid) else None), best[1]


T = TypeVar("T")


def _lines(statement: Sequence[str]) -> dict[str, int]:
    """An industry's statement as line → rank, keeping only lines the platform knows."""
    known = [line for line in statement if line in STATEMENT_LINES]
    return {line: i for i, line in enumerate(dict.fromkeys(known))}


def line_of(name: str, label: str, industry_order: Sequence[dict] = (),
            statement: Sequence[str] = ()) -> Optional[str]:
    """The statement line a metric reads on — the industry's declared one, else its words — or None
    when the industry declares no statement (or the metric's name places it on no line it has)."""
    lines = _lines(statement)
    if not lines:
        return None
    line, _pos = _declared(industry_order, name, label, lines)
    line = line or line_by_words(name, label)
    return line if line in lines else None


def ordered(metrics: Iterable[T], industry_order: Sequence[dict] = (),
            statement: Sequence[str] = ()) -> list[T]:
    """``metrics`` in reading order. Each item needs ``name`` and ``label`` attributes (a
    governed metric). Stable: equal keys keep their incoming order. With ``statement``, the
    industry's income statement is the order; a metric on no line of it sits after the statement,
    before the figures that drive it."""
    items = list(metrics)
    lines = _lines(statement)
    unplaced = (lines["volume"] - 0.5 if "volume" in lines else float(len(lines))) if lines else _UNPLACED

    def key(pair: tuple[int, T]) -> tuple:
        i, m = pair
        name, label = getattr(m, "name", "") or "", getattr(m, "label", "") or ""
        if lines:
            kind, pos = _declared(industry_order, name, label, lines)
            kind = kind or line_by_words(name, label)
            rank = lines[kind] if kind in lines else unplaced
        else:
            kind, pos = _declared(industry_order, name, label)
            kind = kind or kind_by_words(name, label)
            rank = _RANK[kind] if kind else _UNPLACED
        return (rank, pos if pos is not None else len(industry_order), i)

    return [m for _, m in sorted(enumerate(items), key=key)]


def industry_order(connection_id: str) -> list[dict]:
    """The `reading_order` of the industry this connection reads, or [] when none is known."""
    return industry_reading(connection_id)[0]


def industry_reading(connection_id: str) -> tuple[list[dict], list[str]]:
    """The industry's `reading_order` and its `statement` (its income statement's lines, in order;
    [] when it declares none). Best-effort: a profile that cannot be read leaves the words to place
    every metric."""
    try:
        from aughor.business_profile.metric_kb import industry_scope, match_industry
        scope = industry_scope(connection_id)
        if not scope:
            return [], []
        kb = match_industry(scope) or {}
        return ([e for e in (kb.get("reading_order") or []) if isinstance(e, dict)],
                [str(x) for x in (kb.get("statement") or []) if isinstance(x, str)])
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "reading order falls back to the words in each metric's name",
                 counter="briefing.reading_order")
        return [], []
