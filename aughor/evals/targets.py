"""Targets — the callable seams a suite measures.

A target turns an ``EvalCase`` into an ``EvalObservation``: run the thing, report
what happened. Injected into the runner, so the same replication and attribution
machinery measures a SQL replay, ``/ask``, a headless investigation or a brief
without knowing which it is holding.

``reference_target`` is the honest default and the one the harness gate uses: it
replays the case's own SQL with **no model involved**, so a run measures the
runner and the scorer rather than a model's mood. Model-backed targets then
produce a *measurement* rather than a pass/fail — which is the distinction the
ratchet's model-less history could not express.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from aughor.evals.evaluator import EvalCase, EvalObservation
from aughor.trust import Scope


def _observe(conn: Any, sql: str, *, label: str = "eval") -> EvalObservation:
    """Execute and describe. Errors are captured, never raised — an erroring
    case is a datum, not a reason to abandon the suite."""
    t0 = time.monotonic()
    try:
        result = conn.execute(label, sql)
    except Exception as exc:
        return EvalObservation(sql=sql, error=f"{type(exc).__name__}: {exc}",
                               meta={"ms": round((time.monotonic() - t0) * 1000, 2)})
    return EvalObservation(
        sql=sql,
        columns=list(getattr(result, "columns", None) or []),
        rows=list(getattr(result, "rows", None) or []),
        row_count=int(getattr(result, "row_count", 0) or 0),
        error=getattr(result, "error", "") or "",
        caveats=list(getattr(result, "caveats", None) or []),
        meta={"ms": round((time.monotonic() - t0) * 1000, 2)},
    )


def reference_target(conn: Any, *, dialect: str = "duckdb",
                     table_cols: Optional[dict] = None) -> Callable[[EvalCase], EvalObservation]:
    """Replay the case's own ``artifact`` SQL. No model.

    This is what makes the harness gate meaningful: replaying known-correct SQL
    must score ~1.0, and any shortfall is a defect in the runner or the scorer,
    with no model variance to hide behind.
    """
    def target(case: EvalCase) -> EvalObservation:
        case.scope = Scope(conn=conn, dialect=dialect)
        if table_cols and not case.table_cols:
            case.table_cols = table_cols
        return _observe(conn, case.artifact, label="eval.reference")
    return target


def sql_generator_target(conn: Any, generate: Callable[[str], str], *,
                         dialect: str = "duckdb",
                         table_cols: Optional[dict] = None
                         ) -> Callable[[EvalCase], EvalObservation]:
    """Generate SQL from the case's question, then execute it.

    ``generate`` is injected rather than imported so the caller decides what is
    under test — the real writer, a pinned model, or a stub — and so a suite can
    run with no model at all.
    """
    def target(case: EvalCase) -> EvalObservation:
        case.scope = Scope(conn=conn, dialect=dialect, question=case.question)
        if table_cols and not case.table_cols:
            case.table_cols = table_cols
        try:
            sql = generate(case.question)
        except Exception as exc:
            return EvalObservation(error=f"generation failed: {type(exc).__name__}: {exc}")
        obs = _observe(conn, sql, label="eval.generated")
        obs.meta["generated"] = True
        return obs
    return target


def ask_target(connection_id: str, *, depth: str = "quick",
               schema_name: Optional[str] = None
               ) -> Callable[[EvalCase], EvalObservation]:
    """Drive the real ``/ask`` path in-process via ``build_ask_stream``.

    ``request=None`` is documented and verified safe on that seam — nothing on
    the path dereferences it. The SSE frames are folded back into an observation
    so the same evaluators apply to a full product answer as to a bare SQL
    replay.
    """
    def target(case: EvalCase) -> EvalObservation:
        import asyncio
        import json

        from aughor.routers.investigations import AskRequest, build_ask_stream

        req = AskRequest(question=case.question, connection_id=connection_id,
                         depth=depth, schema_name=schema_name)

        async def _drain() -> dict:
            seen: dict = {"sql": "", "columns": [], "rows": [], "headline": "", "error": ""}
            async for frame in build_ask_stream(req, None):
                if not frame.startswith("data: "):
                    continue
                try:
                    payload = json.loads(frame[6:])
                except Exception as exc:
                    # Every frame the ask path emits is JSON, so a malformed one
                    # means the stream shape changed under us — silently skipping
                    # would show up later as an observation mysteriously missing
                    # its rows.
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "ask target: unparseable SSE frame skipped",
                             counter="evals.target.frame")
                    continue
                kind = payload.get("type")
                if kind == "sql":
                    seen["sql"] = payload.get("sql", "")
                elif kind == "columns":
                    seen["columns"] = payload.get("columns", []) or []
                elif kind == "rows":
                    seen["rows"] = payload.get("rows", []) or []
                elif kind == "headline":
                    seen["headline"] = payload.get("headline", "")
                elif kind == "error":
                    seen["error"] = payload.get("message", "")
            return seen

        try:
            seen = asyncio.run(_drain())
        except Exception as exc:
            return EvalObservation(error=f"{type(exc).__name__}: {exc}")

        conn = None
        try:
            from aughor.db.connection import open_connection_for
            conn = open_connection_for(connection_id)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "ask target: connection unavailable; probe guards will skip",
                     counter="evals.target.conn")
        case.scope = Scope(conn=conn, dialect=getattr(conn, "dialect", "duckdb"),
                           question=case.question)
        return EvalObservation(
            sql=seen["sql"], columns=seen["columns"], rows=seen["rows"],
            row_count=len(seen["rows"]), error=seen["error"],
            narrative=seen["headline"], meta={"door": "ask", "depth": depth})
    return target


# ── correctness checkers ──────────────────────────────────────────────────────

def reference_checker(conn: Any) -> Callable[[EvalCase, EvalObservation], Optional[bool]]:
    """Did the observation carry the expected reference result?

    Reuses ``user_agents.quality.results_match`` — the one execution-grounded
    comparator already trusted in this codebase (order-insensitive,
    float-normalised, tolerant of extra columns so a richer-but-correct answer
    still passes). Returns None when a case declares no expectation, which the
    runner counts separately rather than scoring as a miss.
    """
    from aughor.user_agents.quality import results_match

    def check(case: EvalCase, obs: EvalObservation) -> Optional[bool]:
        expected = case.expected or {}
        candidates = [expected.get("reference_sql")] + list(expected.get("accept_sql") or [])
        candidates = [s for s in candidates if s]
        if not candidates:
            return None
        if obs.error:
            return False
        for ref_sql in candidates:
            ref = _observe(conn, ref_sql, label="eval.expected")
            if ref.error:
                continue
            if results_match(ref.rows, obs.rows):
                return True
        return False
    return check
