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


def _declared(order: Sequence[dict], name: str, label: str) -> tuple[Optional[str], Optional[int]]:
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
    return (kind if kind in _RANK else None), best[1]


T = TypeVar("T")


def ordered(metrics: Iterable[T], industry_order: Sequence[dict] = ()) -> list[T]:
    """``metrics`` in reading order. Each item needs ``name`` and ``label`` attributes (a
    governed metric). Stable: equal keys keep their incoming order."""
    items = list(metrics)

    def key(pair: tuple[int, T]) -> tuple:
        i, m = pair
        name, label = getattr(m, "name", "") or "", getattr(m, "label", "") or ""
        kind, pos = _declared(industry_order, name, label)
        kind = kind or kind_by_words(name, label)
        rank = _RANK[kind] if kind else _UNPLACED
        return (rank, pos if pos is not None else len(industry_order), i)

    return [m for _, m in sorted(enumerate(items), key=key)]


def industry_order(connection_id: str) -> list[dict]:
    """The `reading_order` of the industry this connection reads, or [] when none is known.
    Best-effort: a profile that cannot be read leaves the words to place every metric."""
    try:
        from aughor.business_profile.metric_kb import industry_scope, match_industry
        scope = industry_scope(connection_id)
        if not scope:
            return []
        kb = match_industry(scope) or {}
        return [e for e in (kb.get("reading_order") or []) if isinstance(e, dict)]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "reading order falls back to the words in each metric's name",
                 counter="briefing.reading_order")
        return []
