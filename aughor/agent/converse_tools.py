"""The tools a converse turn may choose — each one a guarded pipeline, not a capability.

This is where the plan's central inversion is actually enforced. The model decides
which tool the conversation needs; it never decides whether the SQL is safe, whether
the join is sound, or whether the number can be trusted. Those judgements live inside
the bodies, unchanged, and a tool call is simply a new caller of machinery that already
existed.

`run_sql` is the one that proves it. It executes through `execute_guarded` — the same
chokepoint every other path uses — and returns `{result, guard_receipts}` so the model
narrates what the guards ACTUALLY did rather than reconstructing a plausible story. The
collector that makes this possible shipped in #279 with no consumer; this is it.

Descriptions are the routing policy (P3): there is no intent classifier, so the wording
here is the entire basis on which the model picks. They are written for a reader who
must choose between them, not for documentation.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 20


def _connection(connection_id: str):
    from aughor.db.connection import open_connection_for
    return open_connection_for(connection_id)


def run_sql(connection_id: str, args: dict) -> dict:
    """Execute one query through the guard battery and report what the guards did.

    Returns the rows AND the receipts together, because a number without the guard
    record is exactly the thing this product exists not to hand people. A caveat the
    executor detected but could not repair rides `caveats` — a query that ran without
    error can still be silently wrong, and the model must see that to say so.
    """
    from aughor.kernel.registries.execution_hooks import collect_guard_receipts
    from aughor.sql.executor import execute_guarded

    sql = str(args.get("sql") or "").strip()
    if not sql:
        return {"error": "no sql supplied"}

    conn = _connection(connection_id)
    with collect_guard_receipts() as receipts:
        result = execute_guarded(conn, sql, query_id="converse")

    rows = list(result.rows or [])
    return {
        "columns": list(result.columns or []),
        # Truncated on purpose: the model reasons about a shape, and a 10k-row answer
        # spends the context window that the rest of the conversation needs.
        "rows": rows[:_MAX_PREVIEW_ROWS],
        "row_count": result.row_count,
        "truncated": len(rows) > _MAX_PREVIEW_ROWS,
        "error": result.error,
        "caveats": list(result.caveats or []),
        "guard_receipts": [_receipt_dict(r) for r in receipts],
    }


def _receipt_dict(receipt: Any) -> dict:
    if isinstance(receipt, dict):
        return receipt
    return {k: getattr(receipt, k) for k in ("guard", "action", "detail")
            if hasattr(receipt, k)}


def list_tables(connection_id: str, args: dict) -> dict:
    """The schema as a manifest — progressive disclosure, per the plan's Layer 3 table."""
    conn = _connection(connection_id)
    return {"schema": conn.get_schema()}


def describe_table(connection_id: str, args: dict) -> dict:
    """One table's columns. Kept separate from `list_tables` so the manifest stays cheap
    and detail is paid for only when the model asks."""
    from aughor.db.schema_render import parse_schema_tables

    name = str(args.get("table") or "").strip()
    if not name:
        return {"error": "no table supplied"}

    tables = parse_schema_tables(_connection(connection_id).get_schema())
    bare = name.rsplit(".", 1)[-1].lower()
    for table, columns in tables.items():
        if table.lower() == name.lower() or table.rsplit(".", 1)[-1].lower() == bare:
            return {"table": table, "columns": columns}
    # A named table that is not there is an ANSWER, not an error (P2): the model asked
    # about something that does not exist, and the near-misses are what let it recover
    # rather than guess a column list.
    return {"table": name, "error": "no such table",
            "available": sorted(tables)[:40]}


_SQL_PARAMS = {
    "type": "object",
    "properties": {"sql": {"type": "string", "description": "One SELECT statement."}},
    "required": ["sql"],
}
_TABLE_PARAMS = {
    "type": "object",
    "properties": {"table": {"type": "string", "description": "Table name."}},
    "required": ["table"],
}


def converse_tools(connection_id: str) -> list[ToolSpec]:
    """The tool set for one connection.

    Bound to the connection by closure rather than taking it as a model-supplied
    argument: the model should not be able to name a connection it was not given, and a
    tool that cannot express the wrong connection cannot be talked into it.
    """
    return [
        ToolSpec(
            name="run_sql",
            description=(
                "Run one SELECT against this warehouse and get back the rows plus the "
                "guard receipts — what the safety checks did to your query. Prefer this "
                "for any question that needs real numbers. Read `caveats`: a query can "
                "succeed and still be misleading, and you must say so when it is."
            ),
            parameters=_SQL_PARAMS,
            run=lambda a: run_sql(connection_id, a),
        ),
        ToolSpec(
            name="list_tables",
            description=(
                "List the tables available, with their columns. Call this before writing "
                "SQL against a warehouse you have not inspected in this conversation."
            ),
            parameters={"type": "object", "properties": {}},
            run=lambda a: list_tables(connection_id, a),
        ),
        ToolSpec(
            name="describe_table",
            description=(
                "Inspect ONE table in detail when the manifest is not enough — exact "
                "column names, types and sample values."
            ),
            parameters=_TABLE_PARAMS,
            run=lambda a: describe_table(connection_id, a),
        ),
    ]


def converse_available() -> bool:
    """Whether the converse body may serve a turn (`ask.converse`, EXPERIMENT, off).

    Read at CALL time, never at import: a module-level read makes the flag unflippable
    in a running process and silently turns `monkeypatch.setenv` into a no-op — the trap
    that once had tests spending the real LLM budget.
    """
    from aughor.kernel.flags import flag_enabled
    return flag_enabled("ask.converse")


def converse(connection_id: str, question: str, *, extra_context: Optional[str] = None,
             provider=None, max_steps: Optional[int] = None):
    """Answer one question as a conversation rather than a compiled query spec.

    The whole body in one place: state-not-instructions prompt, the connection's tools,
    the loop. Returns the :class:`LoopResult` so the caller sees the STEPS as well as
    the answer — the route receipt Wave 6 measures is built from those, and an answer
    with no record of how it was reached is the thing the receipts exist to prevent.
    """
    from aughor.agent.tool_loop import run_tool_loop
    from aughor.llm.provider import get_provider

    return run_tool_loop(
        provider or get_provider("coder"),
        converse_system_prompt(connection_id, extra_context),
        question,
        converse_tools(connection_id),
        max_steps=max_steps,
    )


def converse_system_prompt(connection_id: str, extra: Optional[str] = None) -> str:
    """State, not instructions (the plan's rule for this prompt).

    It says what is true — which warehouse, what the tools guarantee, what to do when a
    guard fires — and does not script the conversation. The tool descriptions carry the
    routing; repeating it here would be a second, drifting copy of the policy.
    """
    lines = [
        f"You are answering questions about the data warehouse '{connection_id}'.",
        "",
        "Every query you run goes through a guard battery before it executes. The "
        "receipts come back with the rows: when a guard changed or flagged something, "
        "say so in your answer, in your own words, using what the receipt actually "
        "says. Never describe a check you were not told fired.",
        "",
        "If a result carries caveats, the number may be misleading even though the "
        "query succeeded — report the caveat alongside the number, not instead of it.",
        "",
        "If you cannot answer from the data, say what is missing. A stated gap is worth "
        "more than a plausible number.",
    ]
    if extra:
        lines += ["", extra]
    return "\n".join(lines)
