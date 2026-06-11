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


def check_metric_enforcement(question: str, sql: str, metrics: list) -> list[dict]:
    """Per targeted metric: {metric, status: 'used'|'drift', formula, detail}.
    Untargeted metrics are omitted (n/a for enforcement). Returns [] when no
    governed metric is relevant — the honest 'nothing to enforce' case."""
    s = _norm(sql)
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
    return out


def enforcement_summary(verdicts: list[dict]) -> Optional[dict]:
    """Roll verdicts into one enforcement record for the journal. None when there
    was nothing to enforce."""
    if not verdicts:
        return None
    used = [v["metric"] for v in verdicts if v["status"] == "used"]
    drift = [v["metric"] for v in verdicts if v["status"] == "drift"]
    return {"targeted": len(verdicts), "used": used, "drift": drift,
            "enforced": len(drift) == 0}
