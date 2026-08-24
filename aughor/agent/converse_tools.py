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

`answer_question` is the inversion at full scale — Wave 5's closing step. The entire
quick-answer pipeline, the SAME `answer_core` the `/ask` fast path streams from, offered
as one tool: the model chooses WHEN to run it, and everything about HOW stays inside.
One body with two callers is what makes the tool/direct parity invariant hold by
construction instead of by vigilance.

Descriptions are the routing policy (P3): there is no intent classifier, so the wording
here is the entire basis on which the model picks. They are written for a reader who
must choose between them, not for documentation.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from pydantic import BaseModel

from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 20

#: What a tool reports while it runs — ``(frame_type, payload)``, the same vocabulary
#: ``answer_core`` already emits. A no-op by default so the tool set stays usable from
#: a plain sync caller; a streaming caller supplies one and the pipeline's own frames
#: reach the user instead of being computed and discarded.
Emit = Callable[[str, dict], None]


def _noop_emit(frame_type: str, payload: dict) -> None:
    return None


def _connection(connection_id: str):
    from aughor.db.connection import open_connection_for
    return open_connection_for(connection_id)


def run_sql(connection_id: str, args: dict, *, emit: Optional[Emit] = None,
            user_question: str = "", canvas_id: Optional[str] = None) -> dict:
    """Execute one query through the guard battery and report what the guards did.

    Returns the rows AND the receipts together, because a number without the guard
    record is exactly the thing this product exists not to hand people. A caveat the
    executor detected but could not repair rides `caveats` — a query that ran without
    error can still be silently wrong, and the model must see that to say so.

    When the tool runs inside a streamed turn (``emit`` bound), a successful query is
    ALSO surfaced the way the core surfaces its own — ``sql`` / ``columns`` / ``rows``
    frames and a Trust Receipt. Until 2026-08-14 only ``answer_question`` did that;
    a turn the model chose to serve with the primitive rendered as prose alone,
    with no SQL frame, no rows and ``has_receipt: false`` — the smarter route was
    the one with no visible receipt, exactly the asymmetry `_stream_converse` says
    it will not build. (Found by the Superstore accuracy suite: a CORRECT "3.96
    days" answer scored wrong because the observation was empty.)
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
    out = {
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
    if result.error:
        out["repair"] = route_error(result.error, sql, getattr(conn, "dialect", "") or "")
    elif emit is not None:
        _surface_primitive_answer(emit, connection_id, sql, result, out["guard_receipts"],
                                  user_question=user_question, canvas_id=canvas_id)
    return out


def _surface_primitive_answer(emit: Emit, connection_id: str, sql: str, result: Any,
                              guard_receipts: list, *, user_question: str = "",
                              canvas_id: Optional[str] = None) -> None:
    """The core's own frame shapes (`emit("sql"|"columns"|"rows"|"receipt_id"|"done")`),
    re-issued for a primitive `run_sql` answer, plus its Trust Receipt. Best-effort:
    a receipt failure never fails the query the model already has."""
    emit("sql", {"sql": sql})
    emit("columns", {"columns": list(result.columns or [])})
    emit("rows", {"rows": list(result.rows or [])[:10000]})
    try:
        import uuid

        from aughor.routers.investigations import write_answer_receipt
        inv_id = uuid.uuid4().hex[:12]
        guards = [("flagged" if r.get("action") not in ("passed", "ok", None) else "passed",
                   f"guard:{r.get('guard', '?')}", str(r.get("detail") or ""))
                  for r in guard_receipts if isinstance(r, dict) and r.get("guard")]
        written = write_answer_receipt(
            kind="chat_answer", natural_key=f"chat:{connection_id}:{inv_id}",
            question=user_question or "", sqls=[sql], headline=user_question or sql,
            schema="", connection_id=connection_id, canvas_id=canvas_id or "",
            guard_edges=guards,
            payload_extra={"row_count": int(result.row_count or 0), "body": "converse.run_sql"},
        )
        if written.get("receipt_id"):
            emit("receipt_id", {"receipt_id": written["receipt_id"]})
        # The wrapper harvests inv_id/has_receipt from an inner `done` (see
        # `_stream_converse._forward`) — the same pair the answer_question route
        # yields, so "Why this number" hangs off a real row either way.
        emit("done", {"inv_id": inv_id, "has_receipt": True})
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "converse run_sql: Trust Receipt is best-effort; the frames already streamed",
                 counter="converse.run_sql.receipt")


# The compiled answer path routes a failed query by error CLASS and names the fix
# (tools/error_classifier.py); until 2026-08-14 the converse tool loop got the raw
# driver string. Same classifier, one more consumer — plus what WrenAI's SDK
# taught: the error names the NEXT TOOL, and says whether retrying is worth it.
_NEXT_TOOL: dict = {
    "parser":   ("run_sql", "Fix the syntax and call run_sql again."),
    "binder":   ("describe_table",
                 "Call describe_table on the table you meant (or list_tables if unsure) "
                 "to get the exact column names, then call run_sql again — never invent a name."),
    "semantic": ("run_sql", "Cast explicitly and call run_sql again."),
    "runtime":  ("run_sql", "Guard the expression (NULLIF, bounds) and call run_sql again."),
}


def route_error(error: str, sql: str = "", dialect: str = "") -> dict:
    """A repair instruction the model can act on, not a driver string to decode.

    ``retryable`` is False when the model cannot fix it by rewriting SQL — a
    guard BLOCK (the statement is disallowed, not wrong) or a warehouse fault
    (connection / permission / timeout). Retrying those burns budget; the model
    should tell the user instead. Everything else names the class, the specific
    diagnosis when a pattern matches, and the next tool to call.
    """
    from aughor.tools.error_classifier import (
        classify_error_type, classify_sql_error, error_class_guidance,
    )
    e = (error or "").lower()
    if error.lstrip().startswith("[BLOCKED]"):
        return {"retryable": False, "kind": "blocked",
                "instruction": ("This statement is disallowed by the read-only guard, not "
                                "mistyped — rewriting it will not help. Tell the user what "
                                "was refused and why.")}
    if any(k in e for k in ("connection", "could not connect", "permission denied",
                            "authentication", "timeout", "timed out", "unavailable")):
        return {"retryable": False, "kind": "warehouse",
                "instruction": ("The warehouse could not run this (connection, permission "
                                "or timeout), so a rewrite will not help. Report the "
                                "failure to the user rather than retrying.")}
    cls = classify_error_type(error, sql, dialect)
    kind = str(cls.value)
    next_tool, step = _NEXT_TOOL.get(kind, ("run_sql", "Re-examine the query and call run_sql again."))
    diagnosis = ""
    try:
        diagnosis = classify_sql_error(error, sql, dialect) or ""
    except Exception:
        diagnosis = ""
    return {
        "retryable": True, "kind": kind, "next_tool": next_tool,
        "instruction": " ".join(x for x in (error_class_guidance(cls), diagnosis, step) if x),
    }


def _receipt_dict(receipt: Any) -> dict:
    if isinstance(receipt, dict):
        return receipt
    return {k: getattr(receipt, k) for k in ("guard", "action", "detail")
            if hasattr(receipt, k)}


def answer_question(connection_id: str, args: dict, *, emit: Optional[Emit] = None,
                    session_id: str = "", canvas_id: Optional[str] = None,
                    user_question: str = "") -> dict:
    """Run the WHOLE quick-answer pipeline for one natural-language question.

    This is Wave 5's point: the tool calls the same ``answer_core`` the `/ask` fast
    path streams from — schema linking, governed metrics, grounded generation, the
    guard battery, execution and repair — reading the turn's terminal state as its
    return value. One body, two callers, so the tool's answer and the direct path's
    answer agree BY CONSTRUCTION; the parity test exists to keep it that way, not to
    make it true.

    ``emit`` is the pipeline's live frame channel. Defaulted to a no-op so a plain
    caller sees only the terminal state, but a STREAMING caller passes the real one:
    the SQL, the rows and the guard receipts then reach the user as they are produced,
    exactly as they do on the fast path. Not forwarding them would mean rebuilding the
    same frames from this dict at a second emission site — a copy guaranteed to drift.

    ``session_id`` / ``canvas_id`` / ``user_question`` are the TURN'S IDENTITY, not the
    tool's. The core persists a history row, and without these it would file the
    model's rephrased sub-question against no session at all — a turn the user could
    not find again. ``user_question`` labels the row with what the person actually
    asked, while the pipeline still runs on the model's framing.

    The headline is the answer, so rows deliberately do not ride along — ``columns``
    and ``row_count`` preview the result's shape without spending the context window
    the rest of the conversation needs. ``history`` is empty on purpose: the converse
    loop's own transcript is the conversation; the pipeline gets each question fresh.
    An infrastructure failure inside the core RAISES (that is its documented
    contract), and the tool loop already reports a raising tool body to the model as a
    failed step — a deliberate outcome such as ``query_failed`` comes back as a value
    with its error alongside.
    """
    from aughor.routers.investigations import answer_core

    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "no question supplied"}

    result = answer_core(question, connection_id, [], emit=emit or _noop_emit,
                         session_id=session_id, canvas_id=canvas_id,
                         persist_question=user_question or question)
    out = {
        "outcome": result.outcome,
        "headline": result.headline,
        "sql": result.sql,
        "columns": list(result.columns or []),
        "row_count": result.row_count,
        "caveats": list(result.caveats or []),
        "guard_receipts": [_receipt_dict(r) for r in (result.guard_receipts or [])],
    }
    if result.error:
        out["error"] = result.error
        # The pipeline already spent its own automatic repair on this question, so
        # "ask answer_question again" is the one route that cannot help. Point the
        # model at the primitives instead — the same class/next-tool routing run_sql
        # uses, with the retry target rewritten.
        repair = route_error(result.error, result.sql or "", "")
        if repair.get("retryable"):
            repair["instruction"] = (
                "answer_question already tried an automatic repair and still failed, so do "
                "not call it again with the same question. " + repair["instruction"]
                + " Frame the query yourself against the real columns and call run_sql, "
                "or ask the user a clarifying question if the request itself is ambiguous."
            )
        out["repair"] = repair
    return out


def deep_analysis(connection_id: str, args: dict, *, emit: Optional[Emit] = None,
                  session_id: str = "", canvas_id: Optional[str] = None) -> dict:
    """Run the deep analysis as the ANALYST LOOP, inline (CA-3).

    The conversation reaching for depth — and since CA-3 the depth IS a conversation:
    the analyst loop (`agent/analyst.py`) runs the phase library as tools under the
    deep step budget, streams its phases through this turn's own frame channel, and
    ends in a real synthesized report. What CI-4 background-submitted as the phase
    script now happens in the turn the user is watching, which is the whole thesis —
    the user watches the analyst slice; the report is the summary of what they watched.

    Capability-checked here as a VALUE rather than left to a silent downgrade: a tool
    named deep_analysis that quietly served a quick answer would be the tool lying
    about itself.
    """
    from aughor.licensing import Capability, has_capability

    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "no question supplied"}
    if not has_capability(Capability.DEEP_ANALYSIS, conn_id=connection_id):
        return {"status": "unavailable",
                "reason": "deep analysis is not included in this connection's plan"}

    # The custom-agent refusal gate survives the CI-4→CA-3 body swap: an agent that may
    # not investigate is refused BEFORE any work starts, with the authored sentence.
    try:
        from aughor.custom_agents.context import current_agent
        from aughor.runners import InvestigationRequest, refusal_for
        _agent = current_agent()
        refusal = refusal_for(InvestigationRequest(
            question=question, connection_id=connection_id,
            agent_id=_agent.id if _agent is not None else None))
        if refusal:
            return {"status": "refused", "reason": refusal}
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the custom-agent refusal pre-check is best-effort; the ask path "
                      "raises its own refusals", counter="converse.deep_refusal_check")

    from aughor.agent.analyst import run_analyst

    result = run_analyst(
        connection_id, question,
        session_id=session_id, canvas_id=canvas_id,
        emit=emit, purpose="converse_deep",
    )
    out: dict = {
        "status": "completed" if (result.report or result.answer) else "inconclusive",
        "stop_reason": result.stop_reason,
        "steps": len(result.steps),
    }
    if result.investigation_id:
        out["investigation_id"] = result.investigation_id
    if result.report:
        out["headline"] = result.report.get("headline")
        out["confidence"] = result.report.get("confidence")
        out["executive_summary"] = str(result.report.get("executive_summary") or "")[:1200]
        out["note"] = ("the full report already streamed to the user — summarize its "
                       "conclusion in your answer; do not re-derive it")
    elif result.answer:
        out["conclusion"] = result.answer
    return out


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
_QUESTION_PARAMS = {
    "type": "object",
    "properties": {"question": {
        "type": "string",
        "description": "The analytical question, in plain language, as the user asked it.",
    }},
    "required": ["question"],
}


def converse_tools(connection_id: str, *, emit: Optional[Emit] = None,
                   session_id: str = "", canvas_id: Optional[str] = None,
                   user_question: str = "") -> list[ToolSpec]:
    """The tool set for one connection.

    Bound to the connection by closure rather than taking it as a model-supplied
    argument: the model should not be able to name a connection it was not given, and a
    tool that cannot express the wrong connection cannot be talked into it.

    The turn's identity (``emit``, ``session_id``, ``canvas_id``, ``user_question``)
    binds the same way and for the same reason. It is context the CALLER owns and the
    model must not be able to state: a tool that could name its own session could file
    a turn into someone else's history. Every one of them is optional, so the tool set
    stays constructible from a bare sync caller.

    The four core tools here are the warehouse; the appended platform roster (CI-2)
    is everything else the product knows — findings, the briefing, the knowledge
    graph, monitors, packs, the platform itself — as reads with the same binding
    rule. One list, because the model routes over one list.
    """
    from aughor.agent.delegate_tool import delegation_tools
    from aughor.agent.platform_tools import platform_tools

    return [
        ToolSpec(
            name="answer_question",
            description=(
                "Answer a complete analytical question in the user's own words. The "
                "full guarded answer pipeline runs — metric grounding, SQL generation, "
                "execution, automatic repair, the guard battery — and returns the "
                "grounded headline conclusion plus the SQL it ran, the guard receipts "
                "and any caveats. Use this when the user asks a whole question and you "
                "have not already framed the query; use run_sql when you have exact SQL "
                "you want executed."
            ),
            parameters=_QUESTION_PARAMS,
            run=lambda a: answer_question(connection_id, a, emit=emit,
                                          session_id=session_id, canvas_id=canvas_id,
                                          user_question=user_question),
        ),
        ToolSpec(
            name="run_sql",
            description=(
                "Run one SELECT against this warehouse and get back the rows plus the "
                "guard receipts — what the safety checks did to your query. Use this "
                "for a specific query you have already framed yourself; a complete "
                "analytical question belongs to answer_question. Read `caveats`: a "
                "query can succeed and still be misleading, and you must say so when "
                "it is."
            ),
            parameters=_SQL_PARAMS,
            run=lambda a: run_sql(connection_id, a, emit=emit,
                                  user_question=user_question, canvas_id=canvas_id),
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
        ToolSpec(
            name="deep_analysis",
            description=(
                "Run Aughor's multi-step deep analysis for one question, live in this "
                "turn: the analyst loop slices the data (baseline, decomposition, "
                "cross-sections, its own SQL), streams each phase to the user as it "
                "lands, and ends in a full synthesized report with a confidence "
                "verdict. For open-ended why / root-cause / driver questions that one "
                "query cannot answer, and only with the user's clear intent: it runs "
                "for minutes and spends real budget. The report streams to the user "
                "directly — your job afterwards is to state its conclusion, not to "
                "re-derive it."
            ),
            parameters=_QUESTION_PARAMS,
            run=lambda a: deep_analysis(connection_id, a, emit=emit,
                                        session_id=session_id, canvas_id=canvas_id),
        ),
    ] + platform_tools(connection_id, session_id=session_id) + delegation_tools(
        connection_id, emit=emit, session_id=session_id)


class _Regrounded(BaseModel):
    """The re-grounded answer. A shape, because the transport asks for shapes: the
    provider validates a ``response_model`` and has no plain-text surface."""
    answer: str


#: Cells kept for grounding. A turn can run several queries; the check only needs
#: enough real values to match against, and an unbounded accumulation would hold a
#: whole result set in memory for the length of the turn.
_GROUND_CELL_CAP = 5000


def ground_answer_numbers(answer: str, rows: list, *, question: str = "",
                          provider=None) -> tuple:
    """Hold the turn's PROSE to the rows the turn actually executed.

    The loop's final text is whatever the model typed. Every other number the user
    sees this turn — the chart, the table, the receipt — comes from a result set, but
    the sentence above them did not, and nothing compared the two. Observed live: a
    question about flights per route answered with a tidy markdown table of 108 / 96 /
    84 / 72 / 60 while the chart beside it, drawn from the same 84 rows, showed nothing
    of the sort. A confident wrong number is worse than the error it replaced.

    So: every magnitude-bearing numeral in the answer must appear in a real cell
    (:func:`verify_finding` — the same guard the explorer已 uses on findings, with its
    rounding window and 2% tolerance). If any does not, the model gets ONE chance to
    rewrite using only the values it was actually given, exactly as the explorer's
    phase 8 does. If the rewrite still cannot be grounded, the prose is replaced rather
    than shipped: the chart and table are already on screen and they are correct, so
    saying "I could not ground these" costs the user nothing and a fabricated table
    costs them their trust.

    Returns ``(answer, guard_receipt | None)``. Fail-open by construction: no rows, no
    enforced numerals, or a provider that raises all leave the answer untouched — this
    guard may only ever remove a false claim, never invent a failure.
    """
    from aughor.explorer.grounding import (
        numeric_cells_block, ungrounded_label_values, verify_finding,
    )

    text = (answer or "").strip()
    cells = list(rows or [])[:_GROUND_CELL_CAP]
    if not text or not cells:
        return answer, None

    # Two questions, because one alone misses this failure. `verify_finding` catches a
    # magnitude blown by orders of magnitude ("$3T") but exempts small counts by design;
    # the pair check catches a small count attached to a row that says otherwise. The
    # live table of 108 / 96 / 84 was invisible to the first and obvious to the second.
    def _offenders(candidate: str) -> list:
        return list(verify_finding(candidate, cells).ungrounded) + \
            ungrounded_label_values(candidate, cells)

    offending = _offenders(text)
    if not offending:
        return answer, None

    bad = ", ".join(offending[:5])
    logger.info("converse: answer carried ungrounded number(s) %s; re-grounding", bad)

    try:
        from aughor.llm.provider import get_provider
        p = provider or get_provider("coder")
        rewritten = (p.complete(
            response_model=_Regrounded,
            system=(
                "Your previous answer contained a number that does NOT appear in the "
                "data — a fabricated magnitude. Rewrite the answer using ONLY values "
                "from the list you are given. Copy each value exactly; never scale it "
                "or add a magnitude suffix (K/M/B) it does not already have. If a "
                "number cannot be supported by the list, drop it and describe the "
                "pattern qualitatively. Keep the answer's format and length."
            ),
            user=(
                f"QUESTION: {question}\n\n"
                f"EXACT RESULT VALUES YOU MAY CITE:\n{numeric_cells_block(cells)}\n\n"
                f"YOUR PREVIOUS (UNGROUNDED) ANSWER:\n{text}\n\n"
                f"Ungrounded number(s) to remove or fix: {bad}\n"
                "Rewrite it grounded strictly in the exact values above."
            ),
        ).answer or "").strip()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "answer re-grounding is best-effort; the unsupported claim is "
                      "still withheld below", counter="converse.reground")
        rewritten = ""

    if rewritten and not _offenders(rewritten):
        return rewritten, {
            "guard": "numeric grounding",
            "action": "rewrote the answer",
            "detail": f"number(s) not present in the result: {bad}",
            "before": text[:500],
            "after": rewritten[:500],
        }

    # Still unsupported. The result is on screen and correct; the sentence about it is
    # not, so it does not ship.
    # The rejected figures do NOT get repeated here. They are in the guard receipt,
    # where they are labelled as what was thrown out; restating them in the answer puts
    # the fabricated number back on screen in the one place a skimming reader will take
    # for the result.
    withheld = (
        "I could not ground this answer in the query result — the figures the model "
        "wrote do not appear in the rows it read. The result below is what the query "
        "actually returned; ask again and I can read it back directly."
    )
    return withheld, {
        "guard": "numeric grounding",
        "action": "withheld the answer",
        "detail": f"number(s) not present in the result: {bad}",
        "before": text[:500],
        "after": withheld[:500],
    }


def converse_available() -> bool:
    """Whether the converse body may serve a turn (`ask.converse`, EXPERIMENT, off).

    Read at CALL time, never at import: a module-level read makes the flag unflippable
    in a running process and silently turns `monkeypatch.setenv` into a no-op — the trap
    that once had tests spending the real LLM budget.
    """
    from aughor.kernel.flags import flag_enabled
    return flag_enabled("ask.converse")


def converse(connection_id: str, question: str, *, extra_context: Optional[str] = None,
             provider=None, max_steps: Optional[int] = None,
             on_step=None, tool_emit: Optional[Emit] = None,
             session_id: str = "", canvas_id: Optional[str] = None):
    """Answer one question as a conversation rather than a compiled query spec.

    The whole body in one place: state-not-instructions prompt, the connection's tools,
    the loop. Returns the :class:`LoopResult` so the caller sees the STEPS as well as
    the answer — the route receipt Wave 6 measures is built from those, and an answer
    with no record of how it was reached is the thing the receipts exist to prevent.

    Two channels a STREAMING caller supplies and a sync one does not. ``on_step`` fires
    as each step is recorded — the turn's progress, and its cancellation checkpoint.
    ``tool_emit`` is handed to the tools, so a pipeline running inside a tool streams
    its own frames rather than computing them into silence. Both default to None: a
    caller that only wants the answer gets exactly the code path it got before.
    """
    from aughor.agent.tool_loop import run_tool_loop
    from aughor.llm.provider import get_provider

    return run_tool_loop(
        provider or get_provider("coder"),
        converse_system_prompt(connection_id, extra_context, question=question),
        question,
        converse_tools(connection_id, emit=tool_emit, session_id=session_id,
                       canvas_id=canvas_id, user_question=question),
        max_steps=max_steps,
        on_step=on_step,
    )


def converse_system_prompt(connection_id: str, extra: Optional[str] = None,
                           question: str = "") -> str:
    """State, not instructions (the plan's rule for this prompt).

    It says what is true — who the assistant is, what latitude it has, what the tools
    guarantee, what to do when a guard fires — and does not script the conversation.
    The tool descriptions carry the routing; repeating it here would be a second,
    drifting copy of the policy.

    CI-3 widened the identity from "you answer questions about warehouse X" to the
    platform-wide analyst, and made the latitude explicit in BOTH directions: general
    knowledge and reasoning are granted (the old prompt's silence read as prohibition,
    and the mechanical feel CI-0 measured was partly that silence), while data claims
    are bound to tool results in the same breath. The stated-gap line survives verbatim
    — it was right before this wave and stays right after it. Clarifying in prose is
    granted rather than scripted: the chip gate remains the structured path, but a
    conversation that may only clarify through a widget is not a conversation.

    The org-context line is the same block `/ask` prepends (CI-2): the reader's
    DECLARED identity — industry, reporting currency, fiscal year — describing the
    organization using Aughor, never the data under analysis (the first line already
    names that). Empty for an unconfigured org, so that prompt is unchanged.
    """
    org_note = ""
    try:
        from aughor.orgsettings import org_context
        org_note = org_context(reading="this conversation").rstrip("\n")
    except Exception as org_exc:
        from aughor.kernel.errors import tolerate
        tolerate(org_exc, "org context is additive; the conversation stands without it",
                 counter="converse.org_context")
    lines = [
        "You are Aughor's analyst — the conversation over the whole platform: the "
        f"connected data warehouse '{connection_id}' and everything Aughor has "
        "established around it (findings, briefings, the knowledge graph, monitors, "
        "packs, governed metrics).",
        *(["", org_note] if org_note else []),
        "",
        "General knowledge and reasoning are yours: explain concepts, compare "
        "approaches, discuss business context, connect what the user asks to what the "
        "platform knows. Claims about THIS organization's data are different — they "
        "come from tool results, never from memory or plausibility. A number you did "
        "not just read from a tool result is a number you do not state.",
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
        "",
        "When the question itself is ambiguous, asking a short clarifying question in "
        "plain prose is a complete and welcome turn — better than answering a question "
        "the user did not ask.",
    ]
    # VA-2 — the delegation roster. Appended as STATE ("these agents exist, here is what
    # each is for"), like everything else in this prompt, and omitted entirely when the
    # workspace has no agents: a roster of nobody is not a capability, and describing a
    # tool the model cannot usefully call is how a turn gets wasted on a refusal.
    try:
        from aughor.agent.delegate_tool import delegation_targets, roster_block
        block = roster_block(delegation_targets())
        if block:
            lines += ["", block]
    except Exception:                       # never let the roster break the prompt
        logger.debug("delegation roster unavailable", exc_info=True)
    # VA-1 deliverable 4 — rung 0 of the disclosure ladder. Both existing rungs are TOOLS,
    # so both need the model to already suspect a pack might help; measured on the ledger it
    # never did (0 `list_packs` and 0 `read_pack` in 2,672 recorded tool calls, while
    # `run_sql` shows 55 — so the tools are recorded, and simply were not being reached
    # for). Named, not pasted: the deliverable's own risk note is prompt bloat, and a pack
    # body is ~1,500 tokens against tens for a pointer. Empty unless something matches.
    if question:
        try:
            from aughor.packs.disclosure import disclosure_block
            block = disclosure_block(question, connection_id)
            if block:
                lines += ["", block]
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "pack disclosure is additive; the conversation stands without it",
                     counter="converse.pack_disclosure")
    if extra:
        lines += ["", extra]
    return "\n".join(lines)
