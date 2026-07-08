"""Cross-source federated planner (Rec 2, Stage 3): decompose → validate → execute.

A question that spans two-or-more databases can't be one SQL. This grounds every connection's schema,
asks the model ONCE for a structured plan — an ordered list of steps, each a grounded sub-query on one
source plus the key that links it to the result assembled so far — validates the plan deterministically
(each sub-query executes and outputs its key; each link key is a real column of the assembled result),
then folds the steps through the batched-foreach engine (Stages 1–2b).

Plan-then-execute (PromptQL), deterministic-first: the LLM only produces the *plan*; deterministic
guards validate it and the engine does the joins. One LLM call, everything after is code — so the
result is inspectable (the plan + per-source SQL are returned) and repeatable. The planner also chooses
the step ORDER, so it picks which source drives (driver auto-selection) and how the sources chain.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

from aughor.platform.contracts.execution import QueryResult

logger = logging.getLogger(__name__)

_DRIVER_CAP = 50_000   # rows read from the driver sub-query (via execute_bounded)


class FederatedStep(BaseModel):
    source: int = Field(description="Index into the provided connection list of the source this sub-query runs on.")
    sql: str = Field(description="A single SELECT grounded ONLY in this source's schema; it MUST output the join key.")
    join_key: str = Field(description="This sub-query's OUTPUT column that links it to the assembled result.")
    left_key: str = Field(default="", description="Column in the ALREADY-ASSEMBLED result to join on. Empty for the FIRST (driver) step.")
    how: Literal["inner", "left"] = Field(default="inner", description="Join type onto the assembled result (ignored for the driver).")


class FederatedPlan(BaseModel):
    steps: list[FederatedStep] = Field(description="Ordered steps. steps[0] is the driver (no left_key); each later step joins its source onto the assembled result.")
    rationale: str = Field(default="", description="One sentence: how the sources chain and why the keys link.")


@dataclass
class FederatedAnswer:
    result: QueryResult
    plan: Optional[FederatedPlan]
    issues: list[str]


_PLAN_SYS = (
    "You plan a query that spans MULTIPLE separate databases that CANNOT be joined in one SQL statement. "
    "You are given each source's schema, labelled by its index [0], [1], .... Produce an ordered list of "
    "steps that assemble the answer:\n"
    "- The FIRST step is the DRIVER: `source` (which database), `sql` (a single SELECT grounded ONLY in that "
    "source, selecting the wanted columns PLUS any key needed to link further sources), `join_key` (an output "
    "column later steps can link to), and leave `left_key` empty.\n"
    "- Each LATER step joins one more source onto the result assembled so far: `source`, `sql` (grounded ONLY "
    "in THAT source, selecting its wanted columns PLUS its link key), `join_key` (that sub-query's link column), "
    "`left_key` (a column ALREADY present in the assembled result), and `how` ('inner' or 'left').\n"
    "Rules: each sub-query references ONLY its own source's tables (no cross-database references); each MUST "
    "select its join_key; choose the driver and order to keep intermediate results small; push filters and "
    "aggregations into the sub-queries. Return only the plan."
)


def plan_federated(question: str, conn_ids: list[str]) -> FederatedPlan:
    """One LLM call: ground every source's schema, return an ordered multi-source plan."""
    from aughor.db.connection import open_connection_for
    from aughor.llm.provider import get_provider

    schemas = []
    for i, cid in enumerate(conn_ids):
        schemas.append(f"=== source [{i}] schema ===\n{open_connection_for(cid).get_schema()}")
    user = (
        f"Question: {question}\n\n" + "\n\n".join(schemas) +
        f"\n\nProduce the multi-source plan over sources [0]..[{len(conn_ids) - 1}]."
    )
    return get_provider("coder").complete(system=_PLAN_SYS, user=user, response_model=FederatedPlan)


def _columns_of(conn, sql: str) -> Optional[list[str]]:
    """The output columns of ``sql`` (as a derived table), or None if it can't be introspected."""
    try:
        res = conn.execute("__fed_cols__", f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS _t LIMIT 0")
        return list(res.columns) if not res.error else None
    except Exception:
        return None


def validate_plan(plan: FederatedPlan, conn_ids: list[str]) -> list[str]:
    """Deterministic pre-execution checks: sources in range, each sub-query outputs its join key, and
    each non-driver step's left_key is a real column of the result assembled up to that point."""
    from aughor.db.connection import open_connection_for

    issues: list[str] = []
    if not plan.steps:
        return ["plan has no steps"]
    n = len(conn_ids)
    assembled: Optional[list[str]] = None
    for i, step in enumerate(plan.steps):
        if not (0 <= step.source < n):
            issues.append(f"step {i}: source index {step.source} out of range (have {n})")
            continue
        if not (step.sql or "").strip():
            issues.append(f"step {i}: sql is empty")
            continue
        if not (step.join_key or "").strip():
            issues.append(f"step {i}: join_key is empty")
            continue
        cols = _columns_of(open_connection_for(conn_ids[step.source]), step.sql)
        if cols is None:
            issues.append(f"step {i}: sub-query did not execute (must target only source [{step.source}])")
            continue
        if step.join_key not in cols:
            issues.append(f"step {i}: join key {step.join_key!r} is not an output column ({', '.join(cols) or 'none'})")
        if i == 0:
            if (step.left_key or "").strip():
                issues.append("step 0 (driver) must not have a left_key")
            assembled = list(cols)
        else:
            if not (step.left_key or "").strip():
                issues.append(f"step {i}: left_key is empty (needed to join onto the assembled result)")
            elif assembled is not None and step.left_key not in assembled:
                issues.append(f"step {i}: left_key {step.left_key!r} is not in the assembled result so far ({', '.join(assembled) or 'none'})")
            if assembled is not None:
                assembled = assembled + list(cols)   # the join appends this source's columns
    return issues


def answer_federated(question: str, conn_ids: list[str], *, reconcile: bool = False) -> FederatedAnswer:
    """Full plan-then-execute: plan (LLM) → gate + validate (deterministic) → fold the steps (engine)."""
    from aughor.connectors.remote_join import batched_foreach_join
    from aughor.db.connection import gate_user_sql, open_connection_for

    try:
        plan = plan_federated(question, conn_ids)
    except Exception as exc:  # noqa: BLE001 — a planning failure is an answer, not a 500
        logger.warning("federated planner: planning failed: %s", exc)
        return FederatedAnswer(_error_result(f"planning failed: {str(exc)[:120]}"), None, ["planning failed"])

    if not plan.steps:
        return FederatedAnswer(_error_result("plan has no steps"), plan, ["plan has no steps"])

    # Gate every LLM-written sub-query through the same safety checker the Query Builder uses.
    for i, step in enumerate(plan.steps):
        if 0 <= step.source < len(conn_ids):
            blocked = gate_user_sql(conn_ids[step.source], "federated_planner", step.sql)
            if blocked is not None:
                return FederatedAnswer(
                    _error_result(f"step {i} sub-query blocked by safety gate: {blocked.error}"),
                    plan, [f"step {i} sub-query blocked by safety gate"])

    issues = validate_plan(plan, conn_ids)
    if issues:
        return FederatedAnswer(_error_result("plan failed validation: " + "; ".join(issues)), plan, issues)

    # Fold the steps: execute the driver, then join each subsequent source onto the assembled result.
    driver = plan.steps[0]
    result = open_connection_for(conn_ids[driver.source]).execute_bounded("__fed_driver__", driver.sql, _DRIVER_CAP)
    if result.error:
        return FederatedAnswer(result, plan, [f"driver sub-query failed: {result.error}"])
    for i, step in enumerate(plan.steps[1:], start=1):
        conn = open_connection_for(conn_ids[step.source])
        result = batched_foreach_join(
            result, step.left_key, conn, step.join_key,
            right_sql=step.sql, how=step.how, reconcile=reconcile)
        if result.error:
            return FederatedAnswer(result, plan, [f"step {i} join failed: {result.error}"])

    from aughor.stats import bump
    bump("federation.planner.executed")
    return FederatedAnswer(result, plan, [])


def _error_result(msg: str) -> QueryResult:
    return QueryResult(hypothesis_id="__federated__", sql="", columns=[], rows=[], row_count=0, error=msg)
