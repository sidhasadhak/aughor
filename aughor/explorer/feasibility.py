"""Phase-8 feasibility predicates — don't propose what the schema can't honestly answer.

Extracted from the explorer/agent.py god-file (K4 code-health split). Two
deterministic, high-precision gates that keep the question generator and the SQL
repair loop honest:

  angle feasibility — is_temporal_angle / angle_feasible: drop a coverage angle
    when the domain lacks the column class it needs (a date for trend/cohort, a
    channel for channel_mix), so the generator can't invent an `invoice_date` or
    an `'Unknown' AS signup_source` to satisfy it.

  temporal-SQL shape — has_temporal_sql / has_vacuous_temporal: catch a repair
    that silently DE-TEMPORALISES a time-based question, or fakes the time
    computation with a vacuous DATE_DIFF(x, x) that is always 0 — a temporal
    *shape* answering nothing. Deterministic on purpose (an LLM rated that drift
    faithful; cf. 5ba0fbe).

All four are pure regex/substring predicates. See the Phase-8 feasibility gates
(#1) in the explorer.
"""
from __future__ import annotations

import re

# Coverage angles that inherently require a date/timestamp (aging, over-time, cohorts).
# Offering one on a domain with NO real timestamp forces the generator to invent a date
# column — the `invoice_date`-on-a-dateless-`invoices`-table hallucination. Substring-matched
# so checklist wording can vary. See _phase8 temporal-feasibility gate (#1).
_TEMPORAL_ANGLE_RE = re.compile(
    r"(trend|season|retention|lifecycle|cohort|churn|aging|recency|lead.?time|"
    r"growth|velocity|momentum|over.?time|time.?series|tenure)",
    re.I,
)


def is_temporal_angle(angle: str) -> bool:
    """True when a coverage angle inherently needs a date/timestamp column."""
    return bool(_TEMPORAL_ANGLE_RE.search(angle or ""))


# Coverage angles that need a SPECIFIC KIND of column. Offering one when the
# domain has no matching column forces the generator to invent the dimension —
# the `'Unknown' AS signup_source` channel hallucination. Substring-matched on
# both the angle name (keys) and the available column names (patterns), so
# checklist/column wording can vary. See _phase8 column-feasibility gate (#1).
_ANGLE_REQUIRED_COLS: dict[str, "re.Pattern[str]"] = {
    "channel_mix":          re.compile(r"channel|source|medium|utm|referr|acqui", re.I),
    "attribution":          re.compile(r"channel|source|medium|utm|referr|attribut|touchpoint|campaign", re.I),
    "campaign_roi":         re.compile(r"campaign|utm|ad_|adset|spend|budget|cost", re.I),
    "conversion":           re.compile(r"conver|funnel|stage|status|step|visit|session|signup|lead", re.I),
    "experiments":          re.compile(r"experiment|variant|\bab_|test_group|bucket|treatment|cohort_group", re.I),
    "payment_behavior":     re.compile(r"payment|pay_|tender|method|installment|card|gateway|wallet", re.I),
    "refund_rate":          re.compile(r"refund|return|chargeback|cancel|reversal|dispute", re.I),
    "receivables":          re.compile(r"invoice|due|outstanding|receivable|balance|paid|payment_date|aging", re.I),
    "supplier_performance": re.compile(r"supplier|vendor|partner|on_time|delay|fulfil|deliver", re.I),
    "inventory_health":     re.compile(r"invent|stock|sku|quantity|on_hand|reorder|warehouse|backorder", re.I),
    "lead_times":           re.compile(r"lead.?time|deliver|ship|fulfil|expected|actual.?date|dispatch", re.I),
    "fulfillment":          re.compile(r"fulfil|ship|deliver|dispatch|status|tracking|warehouse", re.I),
}


def angle_feasible(angle: str, columns: "set[str]") -> bool:
    """True unless the angle needs a column class entirely absent from the domain.

    Conservative: an angle with no specific column requirement is always feasible,
    and a present-but-oddly-named column is matched by the broad patterns — so a
    false drop (skipping a real angle) is rare, and far cheaper than a fabrication."""
    pat = _ANGLE_REQUIRED_COLS.get((angle or "").lower())
    if pat is None:
        return True
    return any(pat.search(c) for c in columns)


# SQL that computes OVER TIME — a date/time function, INTERVAL, or a date literal. Used to
# catch a repair that silently DE-TEMPORALISES a time-based question (the invoice case: invoice
# AGE via DATE_DIFF on a date + a date-range filter, "repaired" into a plain payment-delay
# column). Deterministic and high-precision — no LLM judgement (an LLM rated that drift faithful).
_TEMPORAL_SQL_RE = re.compile(
    r"\b(date_?diff|datediff|date_?trunc|date_?part|date_?add|date_?sub|extract|strftime|"
    r"julian_?day|current_date|current_timestamp|interval)\b"
    r"|'\d{4}-\d{2}-\d{2}",   # a date literal like '2025-05-17'
    re.I,
)


def has_temporal_sql(sql: str) -> bool:
    """True when SQL computes over time (date/time function, INTERVAL, or a date literal)."""
    return bool(_TEMPORAL_SQL_RE.search(sql or ""))


# A date-difference whose two date operands are IDENTICAL — DATE_DIFF(CURRENT_DATE,
# CURRENT_DATE) or DATE_DIFF(x.c, x.c) — is always 0. A repair on a dateless table that
# can't find a real date column sometimes fakes the time computation this way, keeping a
# temporal *shape* while answering nothing (so has_temporal_sql alone won't flag it). The
# operand class excludes parens, so nested-call operands simply don't match (no false flag).
_VACUOUS_DATEDIFF_RE = re.compile(
    r"date_?diff\s*\(\s*(?:'[^']*'\s*,\s*)?(?P<a>[^,()]+?)\s*,\s*(?P<b>[^,()]+?)\s*\)",
    re.I,
)


def has_vacuous_temporal(sql: str) -> bool:
    """True when a date-difference compares a value to itself → a constant-0 'time' metric."""
    for m in _VACUOUS_DATEDIFF_RE.finditer(sql or ""):
        a = re.sub(r"\s+", "", m.group("a")).lower()
        b = re.sub(r"\s+", "", m.group("b")).lower()
        if a == b:
            return True
    return False
