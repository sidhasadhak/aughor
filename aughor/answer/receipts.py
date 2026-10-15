"""The reader's words for a guard receipt.

A receipt is written by the mechanism that intervened — ``{"guard": "preflight_repair", "action":
"repaired_sql", "detail": "fixed (binder)"}`` — and the web has named each mechanism for the
reader since B2 (`web/components/GuardReceiptChain.tsx`: "SQL repaired before execution",
"repaired the SQL"). The export printed the raw fields instead: ``extra_filter_replan —
replanned_queries — Revenue change by platform…`` under a "Checks" heading on the page (CP-4's
"the PDF shows every field", 2f8ad418's export, 2026-10-15). One vocabulary, held here for every
Python door and in the TSX for the web; `tests/unit/test_guard_receipt_vocabulary.py` holds the
two equal, so a guard named on one surface is named the same on the other.
"""
from __future__ import annotations

#: What the reader gains from each guard — the backend names the mechanism, the surface names
#: the outcome. An unknown guard falls back to its id, spaced, so a new guard is visible before
#: this map learns its name.
GUARD_LABEL: dict[str, str] = {
    "fanout_defan": "Join over-count prevented",
    "preflight_repair": "SQL repaired before execution",
    "sql_repair": "SQL repaired after its first run",
    "sql_lint": "Query quality issues fixed",
    "headline_grounding": "Headline re-grounded in the returned rows",
    "narration_inversion": "Universal claim qualified",
    "measure_grain": "Wrong-grain total flagged",
    "id_arithmetic": "Untrustworthy magnitude flagged",
    "e1_trust_checks": "Trust checks added a caution",
    "concentration_pareto": "Chart switched to Pareto for a concentration question",
    "fanout_replan": "Queries re-planned around a join fan-out",
    "fanout_detected": "Join over-count flagged",
    "extra_filter_replan": "Queries re-planned around a filter the metric does not declare",
    "ambiguity_probe": "The question's readings were probed",
    "count_star_entity_grain": "Row count checked against the entity asked for",
    "repair_recheck": "A repair was re-checked before adoption",
    "time_order": "Timestamps that run backwards flagged",
    "day_window": "A period's last day read whole",
    "declared_filter": "The metric's declared filter applied",
}

#: The action as a verb phrase — the sub-line under the label.
ACTION_VERB: dict[str, str] = {
    "rewrote_sql": "rewrote the SQL",
    "repaired_sql": "repaired the SQL",
    "rewrote_headline": "rewrote the headline",
    "caveated_headline": "added a caution to the headline",
    "overrode_chart": "overrode the chart choice",
    "replanned_queries": "sent the plan back for correction",
    "hinted": "returned a repair hint to the model",
    "caveated": "carried a caveat instead of asserting",
    "flagged": "flagged it — no provable rewrite exists",
    "kept_original": "kept the original query",
}

#: How much of a receipt's detail a page line carries.
_DETAIL_CHARS = 240


def receipt_sentence(receipt: dict) -> str:
    """One receipt as the reader's line: what the check did for them, how, and the detail the
    guard recorded — never the raw field names."""
    guard = str(receipt.get("guard") or "").strip()
    action = str(receipt.get("action") or "").strip()
    detail = " ".join(str(receipt.get("detail") or "").split())
    label = GUARD_LABEL.get(guard) or guard.replace("_", " ") or "A check ran"
    verb = ACTION_VERB.get(action) or action.replace("_", " ")
    line = f"{label} — {verb}" if verb else label
    if detail:
        line += f": {detail[:_DETAIL_CHARS]}" + ("…" if len(detail) > _DETAIL_CHARS else "")
    return line
