"""A metric's statement, written by the model from the definition in the editor (2026-09-26).

The user: *"Lets have the feature to generate SQL query for metric inside the Metric tab and
right at the SQL statement input box.. the generated text should be based on the metric in
question."* One door, ONE model call per click, the platform's own SQL writer
(`sql.writer.SqlWriter`: the schema as the connection renders it, dialect rules per execution
mode) framed for a governed metric: one statement, one row, one column named after the metric,
no grouping, no limit, no date filter — the range cut is the platform's (`metric_statement`).

What comes back is CHECKED, never rewritten: a grouped, limited or multi-column query is
refused with the reason and the model's text is returned for the person to see; a bare
aggregate is wrapped over the definition's table exactly as the value path always has
(:func:`metric_statement.as_statement`), which is the platform's rule, not a rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.semantic.metric_statement import as_statement, final_select, is_statement


@dataclass
class MetricBrief:
    """What the editor knows about the metric — the framing the model writes from."""
    name: str
    label: str = ""
    definition: str = ""
    unit: str = ""
    tables: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    wrong_usage: list[str] = field(default_factory=list)


def framing(brief: MetricBrief) -> tuple[str, str]:
    """``(question, extra_context)`` for the writer: the metric in question, every field the
    editor holds, and the rules that make the answer a metric's statement."""
    title = brief.label.strip() or brief.name
    question = f"The value of the metric '{title}'" + (f": {brief.definition.strip()}" if brief.definition.strip() else "")
    lines = [
        "You are writing the SQL STATEMENT that DEFINES one governed metric — not answering a question about it.",
        f"METRIC: {title} (column name: {brief.name})" + (f" — unit: {brief.unit.strip()}" if brief.unit.strip() else ""),
        f"DEFINITION: {brief.definition.strip() or '(none written — read the label)'}",
        "FILTERS THAT ARE PART OF THE DEFINITION (apply every one): "
        + ("; ".join(f.strip() for f in brief.filters if f.strip()) or "none"),
        "TABLES THE DEFINITION NAMES: " + (", ".join(t.strip() for t in brief.tables if t.strip()) or "none — choose from the SCHEMA"),
    ]
    dims = [d.strip() for d in brief.dimensions if d.strip()]
    if dims:
        lines.append(f"DIMENSIONS IT MAY LATER BE SLICED BY (do NOT group by them): {', '.join(dims)}")
    wrong = [w.strip() for w in brief.wrong_usage if w.strip()]
    if wrong:
        lines.append("READINGS THAT ARE WRONG (the statement must not compute these): " + " | ".join(wrong))
    lines += [
        "RULES FOR THIS STATEMENT:",
        "1. Exactly ONE SELECT statement; CTEs (WITH ...) are allowed.",
        f"2. It returns exactly ONE row with ONE column named {brief.name}: the metric's value over the whole history.",
        "3. No GROUP BY, no ORDER BY, no LIMIT, and no date or time filter — the platform cuts the statement to a date range itself.",
        "4. A ratio of aggregates is SUM(numerator) / NULLIF(SUM(denominator), 0), never AVG of a row-level ratio.",
        "5. Use only tables and columns that appear in the SCHEMA, with their exact names.",
    ]
    return question, "\n".join(lines)


def check(sql: Optional[str], name: str, dialect: str = "duckdb") -> tuple[Optional[str], str]:
    """``(statement, "")`` when the model's text is a metric's statement, else ``(None, why)``.
    An expression is reported as such — the caller decides whether the definition names a
    table to wrap it over."""
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        return None, "the model returned no SQL"
    if not is_statement(text):
        return None, "the model wrote an expression, not a statement"
    try:
        import sqlglot
        tree = sqlglot.parse_one(text, read=dialect)
    except Exception:  # noqa: BLE001
        return None, "the model's statement does not parse"
    sel = final_select(tree)
    if sel is None:
        return None, "the model's outer query is not a SELECT"
    if sel.args.get("group") is not None:
        return None, "it groups rows — a metric's statement returns one row"
    if sel.args.get("limit") is not None:
        return None, "it limits rows — a metric's statement returns one row and needs no limit"
    n = len(list(sel.expressions or []))
    if n != 1:
        return None, f"it selects {n} columns — one column, {name}, is the metric's value"
    return text, ""


def write_statement(brief: MetricBrief, db: Any, *, writer: Any = None) -> dict:
    """One model call: the writer's SQL for ``brief`` over ``db``'s schema, checked. Returns
    ``{"sql", "refused", "raw", "note", "model"}`` — ``sql`` empty when refused, with
    ``refused`` saying why and ``raw`` the model's text."""
    if writer is None:
        from aughor.sql.writer import SqlWriter
        writer = SqlWriter(db)
    question, context = framing(brief)
    raw = str(writer.write(question, extra_context=context) or "")
    dialect = str(getattr(db, "dialect", "duckdb") or "duckdb")
    statement, why = check(raw, brief.name, dialect)
    note = ""
    tables = [t.strip() for t in brief.tables if t.strip()]
    if statement is None and why.startswith("the model wrote an expression") and tables:
        statement = as_statement(raw.strip().rstrip(";"), tables, brief.filters, brief.name)
        why = ""
        note = (f"the model wrote an expression; wrapped over {tables[0]} with the definition's "
                "filters, as the value path runs it")
    model = ""
    try:
        from aughor.llm.provider import get_provider
        model = str(get_provider("coder").model or "")
    except Exception as exc:  # noqa: BLE001 — the receipt's model name is not worth failing the write
        from aughor.kernel.errors import tolerate
        tolerate(exc, "metric_author.model_name", counter="metrics.generate_sql")
    return {"sql": statement or "", "refused": why, "raw": raw, "note": note, "model": model}
