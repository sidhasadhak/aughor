"""Security — audit log, query budgets, SQL safety check."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["security"])


@router.get("/security/audit")
def get_audit_log(
    limit: int = 100,
    connection_id: str | None = None,
    verdict: str | None = None,
):
    """Recent audit log entries. Filter by connection_id and/or verdict."""
    from aughor.security.audit import AuditLogger
    return {"records": AuditLogger.recent(limit=limit, connection_id=connection_id, verdict=verdict)}


@router.get("/security/audit/stats")
def get_audit_stats(connection_id: str | None = None):
    """Aggregate audit stats (totals, blocked count, PII redactions)."""
    from aughor.security.audit import AuditLogger
    return AuditLogger.stats(connection_id=connection_id)


@router.get("/security/budget")
def list_budgets():
    """List all non-default per-connection query budgets."""
    from aughor.security.sandbox import list_budgets as _list
    return {"budgets": _list()}


@router.get("/security/budget/{connection_id}")
def get_budget(connection_id: str):
    """Return the active QueryBudget for a connection."""
    from aughor.security.sandbox import get_budget as _get, DEFAULT_BUDGET
    b = _get(connection_id)
    return {
        "connection_id": connection_id,
        "max_rows":     b.max_rows,
        "warn_time_ms": b.warn_time_ms,
        "max_time_ms":  b.max_time_ms,
        "is_default":   b is DEFAULT_BUDGET,
    }


class _BudgetUpdate(BaseModel):
    max_rows:     int   | None = None
    warn_time_ms: float | None = None
    max_time_ms:  float | None = None


@router.put("/security/budget/{connection_id}")
def update_budget(connection_id: str, body: _BudgetUpdate):
    """Override the QueryBudget for a connection."""
    from aughor.security.sandbox import get_budget as _get, set_budget, QueryBudget
    current = _get(connection_id)
    updated = QueryBudget(
        max_rows     = body.max_rows     if body.max_rows     is not None else current.max_rows,
        warn_time_ms = body.warn_time_ms if body.warn_time_ms is not None else current.warn_time_ms,
        max_time_ms  = body.max_time_ms  if body.max_time_ms  is not None else current.max_time_ms,
    )
    set_budget(connection_id, updated)
    return {"connection_id": connection_id, "budget": vars(updated)}


@router.post("/security/check")
def check_sql_safety(body: dict):
    """Dry-run safety check on a SQL string without executing it."""
    from aughor.security.safety import SafetyChecker
    sql = body.get("sql", "")
    if not sql:
        raise HTTPException(status_code=400, detail="sql field required")
    result = SafetyChecker.check(sql)
    return {"verdict": result.verdict, "reason": result.reason, "score": result.score}
