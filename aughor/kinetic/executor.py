"""Wave K2 — the ONE governed executor for declared KineticActions.

Every declared action runs through :func:`execute_kinetic_action`, and only through it. The
pipeline is deterministic and side-effect-free until the very last step:

    coerce params → evaluate submission criteria → graduated-approval gate → dispatch → audit

Ordering is load-bearing. Submission criteria run BEFORE the approval gate: a criterion failure
means "this action is invalid as requested", which is more fundamental than "needs approval", and
its AUTHORED message is the product — shown verbatim to the human and (in K4) the model, never
paraphrased. No side effect happens on any rejection: dispatch is the last step and runs only when
every gate passed. Approval reuses the existing graduated dial (`govern.actions.guard`), passing the
action's DECLARED risk (a dynamic action isn't in the static `_RISK` registry).

Dispatch is injectable. The default handler fully wires ``notify``/``webhook`` (a self-contained,
SSRF-guarded POST); ``trigger_investigation`` (K4), ``annotate`` (the K3 overlay ledger) and
``query`` (read-query wiring) are clean seams that raise until their PR lands. A caller (a test, the
K4 agent) may inject its own dispatcher.

RBAC is enforced at the HTTP boundary (the route's policy permission via ``enforce_rbac``), not here,
so the executor stays callable headlessly by the agent inside an already-authorised request.
"""
from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field
from typing import Callable, Optional

from aughor.ontology.models import KineticAction, SideEffect

# ── result + errors ──────────────────────────────────────────────────────────────

_Status = str  # "executed" | "criterion_failed" | "approval_required" | "invalid_params"
#              | "dispatch_error" | "not_found" | "disabled"


@dataclass
class KineticResult:
    status: _Status
    ok: bool
    action_id: str = ""
    message: str = ""                       # authored criterion message / approval hint / error
    outcome: dict = field(default_factory=dict)   # dispatch result, when executed
    detail: dict = field(default_factory=dict)    # structured extras (e.g. the 428 body)
    granted_by: str = ""                    # A4: the standing-grant id that auto-allowed this run ('' otherwise)

    def http_status(self) -> int:
        return {
            "executed": 200, "criterion_failed": 422, "invalid_params": 422,
            "approval_required": 428, "not_found": 404, "disabled": 404,
            "dispatch_error": 502,
        }.get(self.status, 400)


class ParamError(ValueError):
    """A parameter is missing or cannot be coerced to its declared type."""


class CriterionError(ValueError):
    """A submission criterion expression is not a safe, evaluable predicate."""


class KineticDispatchError(RuntimeError):
    """A dispatch handler is not available (a seam not yet wired) or failed."""


# ── safe submission-criterion evaluator ──────────────────────────────────────────
# A restricted predicate language over the action's parameters — comparisons, boolean
# logic, membership, and literals only. NEVER `eval`: the expr comes from an authored
# YAML file, so arbitrary code (calls, attribute access, subscripts, comprehensions)
# must be structurally impossible, not merely discouraged.

_CMP = {
    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}


def _eval(node: ast.AST, params: dict):
    if isinstance(node, ast.Expression):
        return _eval(node.body, params)
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, params) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, params)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, params)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, params)
            fn = _CMP.get(type(op))
            if fn is None:
                raise CriterionError(f"operator not allowed: {type(op).__name__}")
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id in params:
            return params[node.id]
        raise CriterionError(f"unknown parameter in criterion: '{node.id}'")
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_eval(e, params) for e in node.elts]
    raise CriterionError(f"expression not allowed in a criterion: {type(node).__name__}")


def evaluate_predicate(expr: str, params: dict) -> bool:
    """True/False for a submission-criterion predicate over ``params``. Raises
    :class:`CriterionError` on anything outside the restricted grammar (fail-closed)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CriterionError(f"criterion is not a valid expression: {e}") from e
    return bool(_eval(tree, params))


# ── parameter coercion ───────────────────────────────────────────────────────────

def _cast(value, data_type: str):
    d = (data_type or "VARCHAR").upper()
    try:
        if d in ("INTEGER", "INT", "BIGINT", "SMALLINT"):
            return int(value)
        if d in ("NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL"):
            return float(value)
        if d in ("BOOLEAN", "BOOL"):
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
    except (ValueError, TypeError) as e:
        raise ParamError(f"parameter cannot be cast to {d}: {value!r}") from e
    return str(value)


def coerce_params(action: KineticAction, raw: dict) -> dict:
    """Coerce raw params (strings from HTTP/agent) to each param's declared type, filling
    declared defaults and rejecting a missing required param. Extra keys are ignored — an
    action only ever sees its declared parameters."""
    raw = raw or {}
    out: dict = {}
    for p in action.params:
        present = p.name in raw and raw[p.name] not in (None, "")
        if not present:
            if p.required and p.default_value is None:
                raise ParamError(f"missing required parameter '{p.name}'")
            if p.default_value is None:
                continue
            out[p.name] = _cast(p.default_value, p.data_type)
        else:
            out[p.name] = _cast(raw[p.name], p.data_type)
    return out


# ── dispatch (injectable; the default wires webhook/notify, seams the rest) ───────

Dispatch = Callable[[KineticAction, dict, str], dict]   # (action, coerced_params, scope/conn_id) -> outcome


def _dispatch_webhook(se: SideEffect, action: KineticAction, params: dict) -> dict:
    """A self-contained, SSRF-guarded POST — reuses the ActionHub URL guard so a declared
    webhook can never reach a private/internal target."""
    url = (se.config or {}).get("url", "")
    from aughor.util.url_guard import is_safe_webhook_url
    if not url or not is_safe_webhook_url(url):
        raise KineticDispatchError("webhook url missing or blocked by the SSRF guard")
    import httpx
    body = {"action": action.id, "kind": se.kind, "params": params,
            "config": {k: v for k, v in (se.config or {}).items() if k != "url"}}
    resp = httpx.post(url, json=body, timeout=10.0,
                      headers=(se.config or {}).get("headers") or {})
    return {"kind": se.kind, "http_status": resp.status_code, "ok": resp.is_success}


def _dispatch_annotate(action: KineticAction, params: dict, scope: str) -> dict:
    """Write a human overlay edit to the K3 ledger — an annotation/correction merged onto reads,
    never a source mutation. The action's parameters carry the target + body."""
    from aughor.kinetic.overlay import OverlayEdit, save_edit
    if not params.get("table") or not params.get("body"):
        raise KineticDispatchError("annotate requires 'table' and 'body' parameters")
    edit = save_edit(OverlayEdit(
        connection_id=scope, table=str(params["table"]),
        column=str(params.get("column", "")), row_key=str(params.get("row_key", "")),
        key_column=str(params.get("key_column", "")),
        kind=str(params.get("kind", "annotation")), body=str(params["body"]), source="user"))
    return {"annotation": edit.target(), "id": edit.id}


def default_dispatch(action: KineticAction, params: dict, scope: str = "") -> dict:
    """The wired-in dispatcher. ``notify``/``webhook`` and ``annotate`` fire now; the rest are
    seams that raise with the PR that will wire them, so a caller sees a clear signal not a no-op."""
    if action.kind == "side_effect":
        results = []
        for se in action.side_effects:
            if se.kind in ("notify", "webhook"):
                results.append(_dispatch_webhook(se, action, params))
            elif se.kind == "trigger_investigation":
                raise KineticDispatchError(
                    "trigger_investigation dispatch is wired in K4 — inject a dispatcher to use it now")
            else:
                raise KineticDispatchError(f"unknown side effect kind: {se.kind}")
        return {"side_effects": results}
    if action.kind == "annotate":
        return _dispatch_annotate(action, params, scope)
    if action.kind == "query":
        raise KineticDispatchError("query dispatch requires read-query wiring (K2b)")
    raise KineticDispatchError(f"unknown action kind: {action.kind}")


# ── the executor ─────────────────────────────────────────────────────────────────

_RISK = {"read_only": "READ_ONLY", "low": "LOW", "high": "HIGH"}


def _risk_of(action: KineticAction):
    from aughor.govern.actions import ActionRisk
    return getattr(ActionRisk, _RISK.get(action.risk, "HIGH"))


def execute_kinetic_action(
    action: KineticAction,
    params: dict,
    *,
    actor: str = "",
    scope: str = "",
    dispatch: Optional[Dispatch] = None,
    approved: bool = False,
) -> KineticResult:
    """Run one declared action through the full governed pipeline. ``scope`` is the connection
    id (the grain the approval allowlist is keyed on). Returns a :class:`KineticResult`; never
    raises for an expected outcome (criterion failure, approval required, bad params) — those are
    statuses, so the agent (K4) can read the authored message and revise.

    ``approved`` (A4) marks that a human accepted this run (``inbox.accept_proposal``) — the accept
    IS the graduated-approval act, so the approval gate is skipped. It is BYPASS-APPROVAL-ONLY: the
    submission criteria at step 2 have already run, so an accepted proposal can never push a value the
    criteria reject. A standing grant (``kinetic/grants.py``) does the same for an UNATTENDED run —
    consulted only when ``automations.proposals`` is on, so this path is byte-identical otherwise."""
    from aughor.govern import actions as govern

    gov_action = f"kinetic.{action.id}"
    risk = _risk_of(action)

    # 1 — coerce params (side-effect-free)
    try:
        coerced = coerce_params(action, params)
    except ParamError as e:
        govern.audit(gov_action, scope, "invalid_params", actor=actor, detail=str(e), risk=risk)
        return KineticResult("invalid_params", False, action.id, message=str(e))

    # 2 — submission criteria, BEFORE the approval gate. Authored message returned verbatim.
    #     Neither a human accept nor a standing grant bypasses this: they pre-approve WHO may run,
    #     never WHAT values pass.
    for crit in action.submission_criteria:
        try:
            passed = evaluate_predicate(crit.expr, coerced)
        except CriterionError as e:
            # An unevaluable criterion fails closed — the action does NOT run.
            govern.audit(gov_action, scope, "criterion_error", actor=actor,
                         detail=f"{crit.expr}: {e}", risk=risk)
            return KineticResult("criterion_failed", False, action.id, message=crit.message,
                                 detail={"reason": "criterion_error", "expr": crit.expr})
        if not passed:
            govern.audit(gov_action, scope, "criterion_failed", actor=actor,
                         detail=crit.expr, risk=risk)
            return KineticResult("criterion_failed", False, action.id, message=crit.message,
                                 detail={"expr": crit.expr})

    # 3 — approval. A human accept (approved) or a matching standing grant satisfies it; otherwise
    #     the graduated-approval gate decides (and may 428). Every path is audited with WHY it ran.
    from fastapi import HTTPException
    from aughor.kinetic.grants import standing_grant_id
    grant_id = ""
    if approved:
        govern.audit(gov_action, scope, "approved", actor=actor, detail="human accept", risk=risk)
    elif (grant_id := standing_grant_id(action, coerced, scope)):
        govern.audit(gov_action, scope, "auto", actor=actor,
                     detail=f"standing grant {grant_id}", risk=risk)
    else:
        try:
            govern.guard(gov_action, scope, actor=actor, risk=risk)
        except HTTPException as e:
            body = e.detail if isinstance(e.detail, dict) else {"hint": str(e.detail)}
            return KineticResult("approval_required", False, action.id,
                                 message=body.get("hint", "approval required"), detail=body)

    # 3b — parallel safety (Wave R5). THE checkpoint, and it sits here rather than at each
    #      fan-out on purpose: a helper every fan-out must remember to call is one the
    #      fifth fan-out forgets. A concurrent region declares itself
    #      (`parallel_safety.fanout`), and the dangerous operation asks. So a fan-out added
    #      next year is covered without touching that module, and a new action defaults to
    #      not-dispatchable. Outside a fan-out this is a no-op, so every existing path is
    #      byte-identical.
    #
    #      Refused BEFORE step 4 — the only step that can cause a side effect — and after
    #      the criteria and the approval gate, so a refusal can never be mistaken for
    #      either of those verdicts.
    try:
        from aughor.kernel.parallel_safety import assert_dispatchable

        assert_dispatchable(action, name=f"kinetic.{action.id}")
    except ImportError:
        pass
    except Exception as e:
        govern.audit(gov_action, scope, "parallel_refused", actor=actor, detail=str(e), risk=risk)
        return KineticResult("parallel_refused", False, action.id, message=str(e))

    # 4 — dispatch (the ONLY step that can cause a side effect; reached only after every gate)
    try:
        outcome = (dispatch or default_dispatch)(action, coerced, scope)
    except KineticDispatchError as e:
        govern.audit(gov_action, scope, "dispatch_error", actor=actor, detail=str(e), risk=risk)
        return KineticResult("dispatch_error", False, action.id, message=str(e))

    # 5 — audit the completed run
    govern.audit(gov_action, scope, "executed", actor=actor, detail=action.kind, risk=risk)
    return KineticResult("executed", True, action.id, outcome=outcome, granted_by=grant_id)
