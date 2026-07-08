"""Cross-source federated planner (Rec 2, Stage 3): decompose → validate → execute.

A question that spans two databases can't be one SQL. This grounds each connection's schema, asks the
model ONCE for a structured plan — a grounded sub-query per source plus the join keys — validates the
plan deterministically (each sub-query executes and outputs its declared join key), then executes it
through the batched-foreach engine (Stages 1–2b).

Plan-then-execute (PromptQL), deterministic-first: the LLM only produces the *plan*; deterministic
guards validate it and the engine does the join. One LLM call, everything after it is code — so the
result is inspectable (the plan + per-source SQL are returned) and repeatable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

from aughor.platform.contracts.execution import QueryResult

logger = logging.getLogger(__name__)


class FederatedSide(BaseModel):
    sql: str = Field(description="A single SELECT grounded ONLY in this source's schema; it MUST output the join-key column.")
    join_key: str = Field(description="The output column name of this sub-query to join on.")


class FederatedPlan(BaseModel):
    left: FederatedSide = Field(description="Sub-query for the FIRST (driver) source.")
    right: FederatedSide = Field(description="Sub-query for the SECOND source.")
    how: Literal["inner", "left"] = Field(default="inner", description="Join type from the driver's perspective.")
    rationale: str = Field(default="", description="One sentence: what each side contributes and why the keys link.")


@dataclass
class FederatedAnswer:
    result: QueryResult
    plan: Optional[FederatedPlan]
    issues: list[str]


_PLAN_SYS = (
    "You plan a query that spans TWO separate databases that CANNOT be joined in one SQL statement. "
    "You are given the schema of a LEFT (driver) source and a RIGHT source. Produce a plan:\n"
    "- left.sql: a single SELECT grounded ONLY in the LEFT schema, selecting the columns the user wants "
    "from that side PLUS the join-key column.\n"
    "- right.sql: a single SELECT grounded ONLY in the RIGHT schema, selecting the columns wanted from "
    "that side PLUS its join-key column.\n"
    "- left.join_key / right.join_key: the OUTPUT column name on each side that links the two (the same "
    "real-world entity). They need not be identically named.\n"
    "- how: 'inner' (only matched rows) or 'left' (keep all driver rows).\n"
    "Rules: each sub-query references ONLY its own schema's tables (no cross-database references); each "
    "MUST select its join key; push filters and aggregations into the sub-queries. Return only the plan."
)


def plan_federated(question: str, left_conn_id: str, right_conn_id: str) -> FederatedPlan:
    """One LLM call: ground both schemas, return a structured two-source plan."""
    from aughor.db.connection import open_connection_for
    from aughor.llm.provider import get_provider

    left_schema = open_connection_for(left_conn_id).get_schema()
    right_schema = open_connection_for(right_conn_id).get_schema()
    user = (
        f"Question: {question}\n\n"
        f"=== LEFT (driver) source schema ===\n{left_schema}\n\n"
        f"=== RIGHT source schema ===\n{right_schema}\n\n"
        f"Produce the two-source plan."
    )
    return get_provider("coder").complete(system=_PLAN_SYS, user=user, response_model=FederatedPlan)


def _columns_of(conn, sql: str) -> Optional[list[str]]:
    """The output columns of ``sql`` (as a derived table), or None if it can't be introspected."""
    try:
        res = conn.execute("__fed_cols__", f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS _t LIMIT 0")
        return list(res.columns) if not res.error else None
    except Exception:
        return None


def validate_plan(plan: FederatedPlan, left_conn_id: str, right_conn_id: str) -> list[str]:
    """Deterministic pre-execution checks: each sub-query executes and outputs its declared join key."""
    from aughor.db.connection import open_connection_for

    issues: list[str] = []
    for side, cid, label in ((plan.left, left_conn_id, "left"), (plan.right, right_conn_id, "right")):
        if not (side.sql or "").strip():
            issues.append(f"{label} sub-query is empty")
            continue
        if not (side.join_key or "").strip():
            issues.append(f"{label} join_key is empty")
            continue
        try:
            conn = open_connection_for(cid)
        except Exception as exc:
            issues.append(f"{label} connection unavailable: {str(exc)[:80]}")
            continue
        cols = _columns_of(conn, side.sql)
        if cols is None:
            issues.append(f"{label} sub-query did not execute (must target only this source's tables)")
        elif side.join_key not in cols:
            issues.append(
                f"{label} join key {side.join_key!r} is not an output column "
                f"({', '.join(cols) or 'none'})"
            )
    return issues


def answer_federated(
    question: str, left_conn_id: str, right_conn_id: str, *, reconcile: bool = False,
) -> FederatedAnswer:
    """Full plan-then-execute: plan (LLM) → validate (deterministic) → execute (batched-foreach engine)."""
    from aughor.connectors.remote_join import cross_source_join

    try:
        plan = plan_federated(question, left_conn_id, right_conn_id)
    except Exception as exc:  # noqa: BLE001 — a planning failure is an answer, not a 500
        logger.warning("federated planner: planning failed: %s", exc)
        return FederatedAnswer(_error_result(f"planning failed: {str(exc)[:120]}"), None, ["planning failed"])

    # Gate the LLM-generated sub-queries through the same safety checker the Query Builder uses —
    # the plan is model-written SQL, so it must not skip the audit/injection/read-only gate.
    from aughor.db.connection import gate_user_sql
    for cid, side_sql, label in ((left_conn_id, plan.left.sql, "left"), (right_conn_id, plan.right.sql, "right")):
        blocked = gate_user_sql(cid, "federated_planner", side_sql)
        if blocked is not None:
            return FederatedAnswer(
                _error_result(f"{label} sub-query blocked by safety gate: {blocked.error}"),
                plan, [f"{label} sub-query blocked by safety gate"])

    issues = validate_plan(plan, left_conn_id, right_conn_id)
    if issues:
        return FederatedAnswer(_error_result("plan failed validation: " + "; ".join(issues)), plan, issues)

    from aughor.stats import bump
    bump("federation.planner.executed")
    result = cross_source_join(
        left_conn_id, plan.left.sql, plan.left.join_key,
        right_conn_id, plan.right.join_key,
        right_sql=plan.right.sql, how=plan.how, reconcile=reconcile,
    )
    return FederatedAnswer(result, plan, [])


def _error_result(msg: str) -> QueryResult:
    return QueryResult(hypothesis_id="__federated__", sql="", columns=[], rows=[], row_count=0, error=msg)
