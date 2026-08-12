"""Security — audit log, query budgets, SQL safety check.

DATA-06 note for everything below: these routes read a store that spans tenants.
The audit log carries ``sql_full`` — the complete text of every statement an org
has run — so an unscoped read is a disclosure of another tenant's questions, not
merely of metadata. Scoping lives here at the route (where the principal is
reliable) and in the store's own predicate; ``_tenant()`` returns ``None`` in
localhost/identity-off mode, which is what keeps single-user behaviour identical.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel


def _budget_owner_guard(request: Request) -> None:
    """Object-level authz for the by-connection budget routes: a budget is a
    per-connection setting, so its tenant is the connection's org."""
    from aughor.security.authz import check_owner, get_principal
    if (cid := request.path_params.get("connection_id")):
        check_owner("connection", cid, get_principal(request))


router = APIRouter(tags=["security"], dependencies=[Depends(_budget_owner_guard)])


def _tenant() -> str | None:
    """The org to scope a cross-tenant store read to (``authz.tenant_scope``), or
    ``None`` for no filter — identity off, the single-tenant local posture."""
    from aughor.security.authz import tenant_scope
    return tenant_scope()


@router.get("/security/audit")
def get_audit_log(
    request: Request,
    limit: int = 100,
    connection_id: str | None = None,
    verdict: str | None = None,
    label: str | None = None,
):
    """Recent audit log entries for the CALLER'S org. Filter by connection_id, verdict
    and/or label (the surface that issued the SQL, e.g. ``query_workbench`` — the
    history rail's filter).

    An explicit cross-org ``connection_id`` is a 403 rather than an empty list: with the
    tenant filter alone the answer would be indistinguishable from "that connection ran
    nothing", and a probe that cannot tell the two apart is still an information channel.
    """
    from aughor.security.audit import AuditLogger
    from aughor.security.authz import check_owner, get_principal
    if connection_id:
        check_owner("connection", connection_id, get_principal(request))
    return {"records": AuditLogger.recent(limit=limit, connection_id=connection_id,
                                          verdict=verdict, label=label,
                                          org_id=_tenant())}


@router.get("/security/audit/stats")
def get_audit_stats(request: Request, connection_id: str | None = None):
    """Aggregate audit stats (totals, blocked count, PII redactions) for the caller's org."""
    from aughor.security.audit import AuditLogger
    from aughor.security.authz import check_owner, get_principal
    if connection_id:
        check_owner("connection", connection_id, get_principal(request))
    return AuditLogger.stats(connection_id=connection_id, org_id=_tenant())


@router.get("/security/budget")
def list_budgets(request: Request):
    """Non-default per-connection query budgets, scoped to the caller's org.

    The budget registry is keyed by connection id with no tenant column of its own, so
    the scope comes from the connections the caller can see — the same resolution every
    other conn-keyed store uses (``org_visible_conn_ids`` returns ``None``, i.e. no
    filter, in localhost mode)."""
    from aughor.security.authz import org_visible_conn_ids
    from aughor.security.sandbox import list_budgets as _list
    budgets = _list()
    visible = org_visible_conn_ids()
    if visible is not None:
        budgets = {cid: b for cid, b in budgets.items() if cid in visible}
    return {"budgets": budgets}


@router.get("/security/budget/{connection_id}")
def get_budget(connection_id: str):
    """Return the active QueryBudget for a connection (org-checked by the router guard)."""
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
    """Override the QueryBudget for a connection (org-checked by the router guard)."""
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
