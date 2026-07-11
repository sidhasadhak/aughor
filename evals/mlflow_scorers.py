"""Deterministic MLflow scorers for Aughor evals — no LLM judges.

The house guards expressed inside ``mlflow.genai.evaluate``'s harness (the
A1-P2 deliverable of docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md):

- ``make_execution_accuracy(db)`` — the golden-reference comparator
  (``evals.sql_accuracy.score_single``, multi-reference aware) as a 0..1 scorer.
- ``trust_verify`` — the Trust plane's full SQL guard battery
  (``aughor.trust.verify``: read-only gate, E1 footguns, preflight checks) as a
  pass/fail scorer. The deterministic-guards-as-scorers principle: an answer
  that only a mutation or a footgun query could produce scores 0 regardless of
  how accurate its numbers look.
- ``exec_success`` — the generated SQL executed without error.

Requires the ``observability`` extra (mlflow-skinny). Import this module only
from eval harnesses — the app's runtime paths must not depend on mlflow.
"""
from __future__ import annotations

from typing import Any

from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer


def make_execution_accuracy(db) -> Any:
    """The execution-accuracy scorer, bound to an open eval DB connection.

    Bound as a closure because the comparator must re-execute the reference and
    the generated SQL on the same engine the predict_fn used.
    """
    from evals.sql_accuracy import score_single

    @scorer(name="execution_accuracy")
    def execution_accuracy(inputs: dict, outputs: dict) -> Feedback:
        record = (inputs or {}).get("record") or {}
        sql = ((outputs or {}).get("sql") or "").strip()
        if not sql:
            return Feedback(value=0.0, rationale="no SQL generated")
        detail = score_single(db, record, sql)
        rationale = detail.get("error") or (
            f"overall={detail.get('overall', 0.0):.2f} "
            f"matched_reference={detail.get('matched_reference', 0)} "
            f"of {detail.get('num_references', 1)}"
        )
        return Feedback(value=float(detail.get("overall", 0.0)), rationale=rationale)

    return execution_accuracy


@scorer(name="trust_verify")
def trust_verify(inputs: dict, outputs: dict) -> Feedback:
    """The Trust-plane guard battery as a pass/fail scorer (deterministic, no LLM)."""
    sql = ((outputs or {}).get("sql") or "").strip()
    if not sql:
        return Feedback(value=False, rationale="no SQL generated")
    from aughor.trust import Scope, verify
    record = (inputs or {}).get("record") or {}
    verdict = verify(
        sql,
        Scope(schema=record.get("schema") or None,
              dialect=record.get("dialect") or "duckdb"),
        kind="sql",
    )
    return Feedback(value=bool(verdict.ok),
                    rationale=(verdict.reason or "all checks passed"))


@scorer(name="exec_success")
def exec_success(outputs: dict) -> Feedback:
    """The generated SQL executed without a hard error."""
    out = outputs or {}
    return Feedback(value=bool(out.get("ok")),
                    rationale=out.get("error") or "executed")
