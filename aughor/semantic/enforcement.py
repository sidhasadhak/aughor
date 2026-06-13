"""B-7 — metric enforcement: did the AI USE the governed formula, or improvise?

UNIFY registered the canonical metric and the pipeline injects it ("use these
EXACT formulas"). But "told to" isn't "did" — the model can still re-derive
revenue its own way. This module makes the outcome VERIFIABLE and MEASURABLE:
for each registered metric a question targets, it decides whether the generated
SQL actually used the governed formula or drifted to a non-governed computation.

The verdict feeds two things: the chat answer's Trust Receipt (a `metric_used`
edge the user can see, vs a `metric_drift` warning) and a `metric.enforcement`
journal event (so the enforcement RATE — % of metric-bearing answers that used
the governed formula — becomes a real, queryable number, not an aspiration).

High-precision by design: it only judges a metric the question actually targets,
and only flags `used` when the formula's normalized signature is present — so a
genuinely different (correct) query is never mislabelled a drift.
"""
from __future__ import annotations

import re
from typing import Optional

_WS = re.compile(r"\s+")


def _norm(sql: str) -> str:
    """Whitespace-collapsed, lowercased — so `SUM( total_amount )` matches
    `sum(total_amount)`. Not a parser; a robust signature match."""
    return _WS.sub("", (sql or "").lower())


def _targets(question: str, metric) -> bool:
    """Does the question target this metric? Name, label, or any label word
    (so 'average order value' matches the `aov` metric labelled that)."""
    q = (question or "").lower()
    name = (getattr(metric, "name", "") or "").lower()
    label = (getattr(metric, "label", "") or "").lower()
    if name and name in q:
        return True
    if label and label in q:
        return True
    # label words ≥4 chars (avoid 'of'/'the'); all-present = a phrase match
    words = [w for w in re.findall(r"[a-z]+", label) if len(w) >= 4]
    return bool(words) and all(w in q for w in words)


def _wrong_columns(metric) -> list[str]:
    """Column names the metric's wrong_usage_examples warn against (e.g.
    line_total for order-grain revenue) — a positive drift signal."""
    cols: list[str] = []
    for ex in (getattr(metric, "wrong_usage_examples", []) or []):
        cols.extend(c.lower() for c in re.findall(r"\b([a-z_][a-z0-9_]{2,})\b", ex)
                    if c.lower() not in ("the", "and", "use", "for", "not", "sum", "avg"))
    return cols


def _collapse_by_metric(verdicts: list[dict]) -> list[dict]:
    """One verdict per metric NAME, ``used`` winning over ``drift``.

    A KPI can carry several governed grains under the same name (e.g. ``aov`` over
    ``orders`` = ``AVG(total_amount)`` vs over ``order_items`` =
    ``SUM(final_price_usd*quantity)/NULLIF(COUNT(DISTINCT order_id),0)``). A query
    matches at most one grain, so the others would each emit a spurious ``drift``.
    Crediting the metric ``used`` when ANY grain matched is the correct verdict —
    the answer DID use a governed formula — and it also yields exactly one verdict
    per name (so the Trust Receipt can't render two badges with the same key).
    First-seen order is preserved; the winning verdict keeps its own formula/detail."""
    chosen: dict[str, dict] = {}
    order: list[str] = []
    for v in verdicts:
        name = v["metric"]
        if name not in chosen:
            order.append(name)
            chosen[name] = v
        elif chosen[name]["status"] != "used" and v["status"] == "used":
            chosen[name] = v  # a matching grain beats an earlier drift
    return [chosen[n] for n in order]


def check_metric_enforcement(question: str, sql: str, metrics: list) -> list[dict]:
    """Per targeted metric: {metric, status: 'used'|'drift', formula, detail}.
    Untargeted metrics are omitted (n/a for enforcement). Returns [] when no
    governed metric is relevant — the honest 'nothing to enforce' case.

    No SQL to judge → no verdict (NOT a drift): enforcing against an empty string
    would flag every targeted metric as 'drift' for the wrong reason.

    Several metrics can share a name (different governed grains of one KPI). They
    are all evaluated, then collapsed to one verdict per name (used > drift) so a
    query matching any grain reads 'used', not a false 'drift' from the grains it
    didn't match."""
    s = _norm(sql)
    if not s:
        return []
    out: list[dict] = []
    for m in metrics or []:
        if not _targets(question, m):
            continue
        formula = _norm(getattr(m, "sql", ""))
        if formula and formula in s:
            out.append({"metric": m.name, "status": "used",
                        "formula": m.sql, "detail": "answer used the governed formula"})
            continue
        # Targeted but the governed formula isn't present → drift. Enrich with a
        # named wrong-form if one is visible in the SQL (e.g. line_total grain).
        wrong = next((c for c in _wrong_columns(m) if c and c in s and c not in formula), None)
        detail = (f"used a non-governed form (references {wrong})" if wrong
                  else "did not use the governed formula")
        out.append({"metric": m.name, "status": "drift", "formula": m.sql, "detail": detail})
    return _collapse_by_metric(out)


def drift_count(verdicts: list[dict]) -> int:
    """How many targeted metrics drifted from their governed formula."""
    return sum(1 for v in (verdicts or []) if v.get("status") == "drift")


def corrective_directive(verdicts: list[dict]) -> str:
    """B-7 hard gate — a pointed instruction for ONE corrective regenerate pass.

    Names each *drifted* metric's governed formula verbatim and the wrong form that
    was detected, so the re-generation can't repeat the same improvisation. Empty
    string when nothing drifted (the caller skips the regenerate entirely)."""
    drifts = [v for v in (verdicts or []) if v.get("status") == "drift"]
    if not drifts:
        return ""
    lines = [
        "\nGOVERNED-METRIC ENFORCEMENT — your previous SQL drifted from the approved "
        "definition. You MUST fix this:",
    ]
    for v in drifts:
        detail = v.get("detail") or "did not use the governed formula"
        lines.append(
            f"  • {v['metric']}: {detail}. Recompute it with this EXACT expression, "
            f"verbatim — do NOT re-derive it: {v['formula']}"
        )
    lines.append(
        "Rewrite the SQL so every metric above uses its governed expression exactly "
        "as written.\n"
    )
    return "\n".join(lines)


# Well-known KPI concepts → a canonical metric slug. High-precision (only
# unambiguous business KPIs) so "propose to define" never fires on chatter. Each
# (phrase, slug); longer phrases first so "average order value" wins over "value".
_KPI_TERMS: list[tuple[str, str]] = [
    ("average order value", "aov"),
    ("conversion rate", "conversion_rate"),
    ("retention rate", "retention_rate"),
    ("churn rate", "churn_rate"),
    ("gross margin", "gross_margin"),
    ("profit margin", "profit_margin"),
    ("lifetime value", "ltv"),
    ("customer lifetime value", "ltv"),
    ("repeat purchase rate", "repeat_purchase_rate"),
    ("revenue", "revenue"),
    ("churn", "churn_rate"),
    ("retention", "retention_rate"),
    ("conversion", "conversion_rate"),
    ("arpu", "arpu"),
    ("aov", "aov"),
    ("ltv", "ltv"),
    ("clv", "ltv"),
]


def propose_undefined_metrics(question: str, metrics: list) -> list[dict]:
    """B-7 propose-to-define — KPI concepts the question names that NO registered
    metric governs. Each is a candidate the user can define so it becomes enforceable.

    High-precision: only well-known KPI phrases, and only when no governed metric
    already covers the concept (by name, slug, or label) — so a governed KPI is never
    re-proposed. Returns ``[{slug, phrase}]`` (one per slug), or ``[]``."""
    q = (question or "").lower()
    if not q:
        return []

    def _covered(slug: str, phrase: str) -> bool:
        # Is THIS concept already governed? Match the metric to the slug/phrase only —
        # NOT to the whole question (a governed metric named elsewhere in the question
        # must not suppress an unrelated ungoverned KPI also mentioned).
        for m in metrics or []:
            name = (getattr(m, "name", "") or "").lower()
            label = (getattr(m, "label", "") or "").lower()
            if slug == name or phrase == name or (label and (phrase in label or label in phrase)):
                return True
        return False

    out: list[dict] = []
    seen: set[str] = set()
    for phrase, slug in _KPI_TERMS:
        if phrase in q and slug not in seen and not _covered(slug, phrase):
            seen.add(slug)
            out.append({"slug": slug, "phrase": phrase})
    return out


def enforce_gate(question: str, sql: str, metrics: list, regenerate) -> str:
    """B-7 hard gate. If `sql` drifted from a governed formula `question` targets,
    call ``regenerate(directive)`` ONCE with a pointed corrective directive and keep
    the rewrite only if it reduces drift. Fail-safe — returns the original SQL when
    nothing drifted, when there's nothing to enforce, or when the rewrite isn't
    strictly better — so the gate can never replace a query with a worse one.

    ``regenerate`` takes the corrective-directive string and returns SQL (or None);
    the caller owns the LLM, so this stays pure + unit-testable."""
    if not sql or not metrics:
        return sql
    verdicts = check_metric_enforcement(question, sql, metrics)
    directive = corrective_directive(verdicts)
    if not directive:                       # used (or nothing targeted) → leave as-is
        return sql
    try:
        sql2 = regenerate(directive)
    except Exception:
        return sql
    if sql2 and drift_count(check_metric_enforcement(question, sql2, metrics)) < drift_count(verdicts):
        return sql2
    return sql


def enforcement_summary(verdicts: list[dict]) -> Optional[dict]:
    """Roll verdicts into one enforcement record for the journal. None when there
    was nothing to enforce."""
    if not verdicts:
        return None
    used = [v["metric"] for v in verdicts if v["status"] == "used"]
    drift = [v["metric"] for v in verdicts if v["status"] == "drift"]
    return {"targeted": len(verdicts), "used": used, "drift": drift,
            "enforced": len(drift) == 0}
