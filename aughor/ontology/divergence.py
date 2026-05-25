"""
M12c — Metric divergence detection.

Checks whether hypothesis SQL queries compute key metrics using formulas that
diverge from the canonical definitions stored in the ontology.  Returns warning
strings that are injected into unresolved_tensions before synthesis so the
narrator can surface them in the report's risks section.

Design goals:
  - Deterministic (no LLM)
  - Best-effort — false negatives are OK; false positives must be rare
  - One warning per (hypothesis, metric) pair at most
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.ontology.models import OntologyGraph


# ── Internal helpers ──────────────────────────────────────────────────────────

# Captures the first aggregate function call in a formula, e.g.
#   SUM(total_amount)         → sum, total_amount
#   COUNT(DISTINCT order_id)  → count, order_id
#   AVG(discount_rate)        → avg, discount_rate
_AGG_RE = re.compile(
    r"\b(sum|count|avg|min|max)\s*\(\s*(?:distinct\s+)?([^\)]+?)\s*\)",
    re.IGNORECASE,
)

# Metric-name keywords that indicate a query is computing that metric
_METRIC_ALIAS_RE = re.compile(r"\bAS\s+[`\"']?(\w+)[`\"']?", re.IGNORECASE)


def _extract_agg(formula: str) -> Optional[tuple[str, str]]:
    """Return (agg_func, column) from a formula's first aggregate, or None."""
    m = _AGG_RE.search(formula)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip().lower()


def _query_computes_metric_wrongly(sql: str, metric_id: str, display_name: str, formula_sql: str) -> bool:
    """
    Return True if the SQL appears to be measuring this metric but uses the wrong formula.

    Approach:
    1. Check that the SQL plausibly targets this metric (metric name in alias or SELECT).
    2. Check that the canonical aggregate is NOT present in the SQL.
    """
    sql_lower = sql.lower()
    name_tokens = {metric_id.lower(), display_name.lower().replace(" ", "_")}
    # Grab all column aliases from this SQL
    aliases = {m.group(1).lower() for m in _METRIC_ALIAS_RE.finditer(sql_lower)}
    # Also check if metric words appear as bare tokens in the SQL
    name_in_sql = any(
        re.search(rf"\b{re.escape(tok)}\b", sql_lower) for tok in name_tokens
    )
    metric_seems_targeted = bool(aliases & name_tokens) or name_in_sql

    if not metric_seems_targeted:
        return False

    canonical = _extract_agg(formula_sql)
    if not canonical:
        return False  # can't compare without a canonical aggregate

    agg_func, col = canonical
    # Check whether the canonical aggregate (e.g. sum(total_amount)) is in the SQL
    pattern = rf"\b{re.escape(agg_func)}\s*\(\s*(?:distinct\s+)?[`\"']?{re.escape(col)}[`\"']?\s*\)"
    canonical_present = bool(re.search(pattern, sql_lower, re.IGNORECASE))

    return not canonical_present


# ── Public API ────────────────────────────────────────────────────────────────

def check_metric_consistency(
    hypotheses: list,
    query_history: list,
    ontology: Optional[OntologyGraph],
) -> list[str]:
    """
    Compare hypothesis SQL against canonical metric formulas in the ontology.

    Returns a list of warning strings (empty if everything is consistent or
    the ontology has no metrics).  One warning per (hypothesis, metric) pair.
    """
    if not ontology or not ontology.metrics:
        return []

    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()  # (hyp_id, metric_id) pairs already warned

    for metric_id, metric in ontology.metrics.items():
        if not metric.formula_sql:
            continue

        # Hypothesis descriptions / findings that mention this metric
        name_tokens = {metric_id.lower(), metric.display_name.lower()}
        relevant_hyps = [
            h for h in hypotheses
            if any(
                tok in (h.description or "").lower() or tok in (h.key_finding or "").lower()
                for tok in name_tokens
            )
        ]

        for hyp in relevant_hyps:
            key = (hyp.id, metric_id)
            if key in seen:
                continue

            hyp_results = [
                r for r in query_history
                if r.hypothesis_id == hyp.id and not r.error
            ]
            for qr in hyp_results:
                if _query_computes_metric_wrongly(qr.sql, metric_id, metric.display_name, metric.formula_sql):
                    warnings.append(
                        f"Metric divergence [{metric.display_name}]: "
                        f"{hyp.id} appears to compute '{metric.display_name}' with a formula "
                        f"that differs from the canonical definition "
                        f"({metric.formula_sql}). "
                        f"Verify this finding against the ontology before stating the metric value."
                    )
                    seen.add(key)
                    break  # one warning per hypothesis per metric is enough

    return warnings
