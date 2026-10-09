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
from contextlib import contextmanager
from contextvars import ContextVar
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


# ── Declared filters: the rows a governed formula is over ─────────────────────
#
# `check_metric_enforcement` above compares formula text, so a statement computing
# `SUM(sale_price)` over every row read "used" against a revenue declared over
# `status <> 'Cancelled'`. The formula is half the definition. These build the other
# half as plain rules for `sql.metric_filter_guard`, which the executor applies to a
# statement a model wrote — the platform side may not import this package, so the rules
# cross the boundary as dicts.

#: The question the statements now executing are in answer to. A ContextVar so the
#: phase queries' worker threads (which copy the context) and concurrent turns each
#: read their own.
_QUESTION: ContextVar[str] = ContextVar("enforcement_question", default="")

#: Arc OC-3 — rules the run itself declared once its intake had read them: a keyed metric the question frame resolved
#: is computed over the rows its statement keeps and the objects the question's rules chose, and the question's words
#: alone cannot say which objects those are. A list HELD for the run (`answering`, `holding`) and filled in place
#: (`declare`), so a step that runs after the intake in a copy of the run's context reads what the intake declared.
#: None outside a run: there is nowhere to declare to.
_DECLARED: ContextVar[Optional[list]] = ContextVar("enforcement_declared", default=None)


@contextmanager
def answering(question: str):
    """Everything executed inside is in answer to ``question``."""
    token = _QUESTION.set(question or "")
    held = _DECLARED.set([])
    try:
        yield
    finally:
        _DECLARED.reset(held)
        _QUESTION.reset(token)


def holding(rules: Optional[list] = None) -> None:
    """Hold the run's declared rules in the CURRENT context — for a run whose every step executes in one copied
    context it then discards (the deep graph's stream, `routers.investigations._investigation_stream`). ``rules``
    are ones the run declared before (a resumed run's intake does not run again)."""
    _DECLARED.set(list(rules or ()))


def declare(rules: list) -> bool:
    """The run's declared rules, from here on. False when no run holds any — nothing is declared then."""
    held = _DECLARED.get()
    if held is None:
        return False
    held[:] = list(rules or ())
    return True


def _reach(question: str, metric) -> int:
    """How much of the question this metric's own words account for — what decides
    between two metrics the question names at once ("net merchandise revenue" is also a
    question containing "revenue")."""
    q = (question or "").lower()
    name = (getattr(metric, "name", "") or "").lower()
    label = (getattr(metric, "label", "") or "").lower()
    spoken = name.replace("_", " ")
    found = [len(t) for t in (name, spoken, label) if t and t in q]
    words = [w for w in re.findall(r"[a-z]+", label) if len(w) >= 4]
    if words and all(w in q for w in words):
        found.append(sum(len(w) for w in words))
    return max(found, default=0)


def person_words(question: str) -> str:
    """The question as a person asked it: a scheduled run's generated block (its observation
    window, the previous report it quotes) removed, so "returns" in a quoted report is never
    read as the person asking for returns to be excluded."""
    try:
        from aughor.automations.temporal import ask_of
        return ask_of(question or "")
    except Exception:  # noqa: BLE001 — the raw question is the honest fallback
        return question or ""


def declared_filter_rules(question: str, metrics: list, dialect: str = "duckdb") -> list[dict]:
    """``[{"metric", "formula", "tables", "filters"}]`` for each metric whose declared
    filter a statement answering ``question`` must carry.

    Three conditions, each a refusal to guess: the metric is APPROVED (a person stands
    behind the filter — a draft's is a proposal), the question TARGETS it (``COUNT(id)``
    is a declared formula, and counting a table is not thereby asking for units sold),
    and it declares a table and a filter (there is something to put somewhere).

    A metric stored as a one-measure statement is read for its measure, its table and its
    WHERE (`sql.metric_filter_guard.measure_of`); the ``filters`` field and the statement's
    own conditions are one list, each said once.

    Two targeted metrics with ONE formula over ONE table and different filters — revenue
    and net merchandise revenue are both ``SUM(sale_price)`` over order lines — cannot both
    own a statement's ``SUM(sale_price)``. The one whose words account for more of the
    question does; a tie makes no rule, and the statement runs as its author wrote it."""
    from aughor.sql.metric_filter_guard import measure_of, same_condition, same_formula

    found: list[tuple[int, dict]] = []
    for m in metrics or []:
        if (getattr(m, "status", "") or "") != "approved" or not _targets(question, m):
            continue
        measure = measure_of(getattr(m, "sql", "") or "", dialect)
        if measure is None:
            continue
        tables = measure["tables"] or [
            str(t).strip() for t in (getattr(m, "tables", None) or []) if str(t).strip()]
        filters: list[str] = []
        for f in [*(getattr(m, "filters", None) or []), *measure["filters"]]:
            f = str(f).strip()
            if f and not any(same_condition(f, kept, dialect) for kept in filters):
                filters.append(f)
        if not tables or not filters:
            continue
        # `asked` travels with the rule so the guard can tell a population the QUESTION chose
        # ("revenue excluding returns") from one the writer borrowed from a sibling metric —
        # the person's words only, never a scheduled run's generated context block.
        found.append((_reach(question, m), {"metric": m.name, "formula": measure["formula"],
                                            "tables": tables, "filters": filters,
                                            "asked": person_words(question)}))

    def _rivals(a: dict, b: dict) -> bool:
        return (same_formula(a["formula"], b["formula"], dialect)
                and {t.lower() for t in a["tables"]} & {t.lower() for t in b["tables"]}
                and not (len(a["filters"]) == len(b["filters"])
                         and all(any(same_condition(x, y, dialect) for y in b["filters"])
                                 for x in a["filters"])))

    out: list[dict] = []
    for reach, rule in found:
        others = [(r, o) for r, o in found if o is not rule and _rivals(rule, o)]
        if any(r >= reach for r, _ in others):
            continue                            # out-reached, or tied: no rule from this one
        if not any(o["metric"] == rule["metric"] and same_formula(o["formula"], rule["formula"], dialect)
                   and {t.lower() for t in o["tables"]} == {t.lower() for t in rule["tables"]}
                   for o in out):
            out.append(rule)
    return out


def declared_filter_notes(sql: str, connection_id: str, dialect: str = "duckdb") -> list[str]:
    """What a person's own SQL is told when it measures a declared metric over that metric's table
    without the metric's filter — one sentence per measure, never a rewrite.

    A statement run from the SQL Editor met no guard: `SELECT SUM(sale_price) FROM order_items`
    quietly counted cancelled lines and read as revenue (2026-10-02). The agent's guard adds the
    filter, because the agent answers a question that asked for the metric; a person's statement
    asked for nothing but itself, so it runs as written and is told what it is not. Unlike the
    agent's rules, every approved metric is read — there is no question to say which is meant —
    and metrics that share one formula over one table are named together, each with its filter.
    Empty when the statement deals with each filter (applies it, or cuts or filters by its column)
    and on any failure to read the catalogue or the statement."""
    if not (sql or "").strip() or not connection_id:
        return []
    try:
        from aughor.semantic.metrics import list_metrics
        from aughor.sql.metric_filter_guard import (
            enforce_metric_filters, measure_of, same_condition, same_formula,
        )
        missed: list[dict] = []
        for m in list_metrics(connection_id=connection_id) or []:
            if (getattr(m, "status", "") or "") != "approved":
                continue
            measure = measure_of(getattr(m, "sql", "") or "", dialect)
            if measure is None:
                continue
            tables = measure["tables"] or [str(t).strip() for t in (getattr(m, "tables", None) or []) if str(t).strip()]
            filters: list[str] = []
            for f in [*(getattr(m, "filters", None) or []), *measure["filters"]]:
                f = str(f).strip()
                if f and not any(same_condition(f, kept, dialect) for kept in filters):
                    filters.append(f)
            if not tables or not filters:
                continue
            rule = {"metric": m.name, "formula": measure["formula"], "tables": tables, "filters": filters}
            _, applied = enforce_metric_filters(sql, [rule], dialect)
            if applied:
                missed.append({**rule, "label": str(getattr(m, "label", "") or m.name),
                               "table": applied[0]["table"]})
        notes: list[str] = []
        while missed:
            first = missed.pop(0)
            group = [first] + [o for o in missed if same_formula(o["formula"], first["formula"], dialect)
                               and o["table"].lower() == first["table"].lower()]
            missed = [o for o in missed if o not in group]
            what = f"{first['formula']} over {first['table']}"
            if len(group) == 1:
                notes.append(f"declared filter: {what} is the declared metric {first['label']}, which keeps "
                             f"{' AND '.join(first['filters'])} — this statement does not, so its figure is "
                             f"not {first['label']}. It ran as written.")
            else:
                named = " and ".join(f"{g['label']} ({' AND '.join(g['filters'])})" for g in group)
                none = "neither filter" if len(group) == 2 else "none of their filters"
                notes.append(f"declared filter: {what} is declared as {named} — this statement applies "
                             f"{none}, so its figure is {'neither' if len(group) == 2 else 'none of them'}. "
                             "It ran as written.")
        return notes
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "declared-filter notes are best-effort; the statement's result stands without them",
                 counter="metric.declared_filter_notes")
        return []


def rules_for_statement(connection_id: str, question: Optional[str] = None,
                        dialect: str = "duckdb") -> Optional[list]:
    """The declared-filter rules for a statement about to run on ``connection_id`` — for
    ``question``, or for the one bound by :func:`answering`. ``dialect`` is the engine's:
    a stored metric statement is written for it. ``None`` when there is no question or no
    connection (nothing to enforce, and the executor then leaves the statement exactly as
    written) and on any failure to read the catalogue. The rules the run itself declared (`declare`) ride after the
    question's, whatever the question's words target."""
    declared = list(_DECLARED.get() or ())
    asked = question if question else _QUESTION.get()
    if not asked or not connection_id:
        return declared or None
    try:
        from aughor.semantic.metrics import list_metrics
        return (declared_filter_rules(asked, list_metrics(connection_id=connection_id),
                                      dialect or "duckdb") + declared) or None
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "declared-filter rules are best-effort; the statement runs as written",
                 counter="metric.declared_filter_rules")
        return declared or None
