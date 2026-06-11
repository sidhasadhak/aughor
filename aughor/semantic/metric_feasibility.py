"""Metric-feasibility gate — don't narrate a VERDICT from a metric the connection can't support.

A separate class from grain (additivity): a question asks about profitability / efficiency, the
connection has no cost / margin / conversion data, and the platform FABRICATES the metric (a 0%
margin "we are not losing money" on cost-less TPC-H; a meaningless "cost per record" efficiency
on a marketing table with no conversions) and then asserts a confident verdict from it.

This deterministic gate flags the mismatch from the SCHEMA so the answer can caveat the verdict
instead of asserting a fabricated one. High-precision and conservative: it only fires when the
question clearly needs a metric AND the required column CLASS is entirely absent — a present-but-
oddly-named column is matched by the broad patterns, so a false flag is rare.
"""
from __future__ import annotations

import re
from typing import Optional

# Questions that REQUIRE cost/margin to answer (profitability).
_PROFIT_Q = re.compile(
    r"\b(profit|profitab|unprofitab|margin|losing money|loss[- ]?making|bottom[- ]?line|"
    r"net income|markup|are we (?:making|losing))\b", re.I)
# Questions that REQUIRE a cost AND an outcome to answer (efficiency / return).
_EFFICIENCY_Q = re.compile(r"\b(roi|roas|efficien\w*|cost[ _]per|return on|payback|cac|ltv)\b", re.I)

# Column classes that make each metric computable.
_COST_COL = re.compile(r"(cost|cogs|expense|spend|margin|profit|cogs_usd)", re.I)
_OUTCOME_COL = re.compile(r"(conver|revenue|sales?|order|purchase|transaction|signup|lead|booking|gmv)", re.I)
_SPEND_COL = re.compile(r"(spend|cost|budget|ad_?spend|investment)", re.I)


def unsupported_metric_gap(question: str, columns) -> "Optional[str]":
    """Return a one-line reason when *question* needs a metric the schema can't support, else None.

    ``columns`` may be an iterable of column names or a schema-text string. Never raises."""
    try:
        q = question or ""
        if isinstance(columns, str):
            cols = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", columns))
        else:
            cols = {str(c) for c in (columns or [])}
        if not q.strip():
            return None
        has_cost = any(_COST_COL.search(c) for c in cols)
        if _PROFIT_Q.search(q) and not has_cost:
            return ("profitability/margin question, but this connection has no cost, COGS, margin, or "
                    "profit column — profit cannot be computed; report what IS measurable (revenue, "
                    "volume) and do NOT infer or fabricate a margin/profit verdict")
        if _EFFICIENCY_Q.search(q):
            has_spend = any(_SPEND_COL.search(c) for c in cols)
            has_outcome = any(_OUTCOME_COL.search(c) for c in cols)
            if not (has_spend and has_outcome):
                missing = "spend/cost" if not has_spend else "an outcome (conversions/revenue)"
                return (f"efficiency/return question, but this connection lacks {missing} to compute it "
                        f"— do NOT assert an efficiency verdict from a proxy like cost-per-row")
        return None
    except Exception:
        return None
