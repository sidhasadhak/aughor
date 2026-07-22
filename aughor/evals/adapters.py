"""Thin adapters from the guards' real return shapes to one ``EvalScore``.

The guard battery grew organically and speaks six shapes. Rather than rewrite ~25
proven guards to fit a protocol — which would risk the correctness that makes
them worth using — each shape gets a small adapter. Every guard below is reached
through one of these with **zero changes to the guard itself**.

  S1 ``list[Finding]``      → :class:`ListFindingEvaluator`
  S2 ``str | None`` (hint)  → :class:`HintEvaluator` (also ``list[str]``)
  S3 ``Finding | None``     → :class:`OptionalFindingEvaluator`
  S4 ``bool`` / ``set``     → :class:`PredicateEvaluator`
  S6 ``(ok, reason)``       → :class:`OkReasonEvaluator`

S5 (``(sql, receipt)`` repairs) has no adapter on purpose. Its only real
candidate, ``safety.preflight_repair``, can invoke ``SqlWriter.fix`` and
therefore **call the LLM** — a "deterministic" evaluator that quietly makes a
model call would corrupt every baseline in this arc. ``lifecycle_guard`` is
deterministic but needs intake-phase rules that an ``EvalCase`` does not carry.
Both are documented exclusions, not oversights.

Guard convention honoured throughout: **no finding means pass**. Guards are
positive-only and high-precision — they are built never to flag a correct query
— so an empty result is a clean bill, and an exception is a skip rather than a
failure.
"""
from __future__ import annotations

from dataclasses import fields as _dc_fields
from dataclasses import is_dataclass
from typing import Any, Callable, Optional

from aughor.evals.evaluator import EvalCase, EvalObservation, EvalScore, sql_of
from aughor.trust import WARN, Check


def _detail_of(finding: Any) -> dict:
    """A JSON-safe detail dict for a finding, whatever its class.

    Prefers the finding's own ``to_dict`` (only ``TrustFinding`` has one), then
    dataclass fields, then ``vars``. Sets are listified — ``composite_key`` uses
    set-valued fields, which are not JSON-serialisable.
    """
    to_dict = getattr(finding, "to_dict", None)
    if callable(to_dict):
        try:
            return {k: _jsonable(v) for k, v in to_dict().items()}
        except Exception as exc:
            # The method exists but blew up — unexpected, so say so rather than
            # silently degrading to a shape the caller cannot distinguish.
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"{type(finding).__name__}.to_dict failed; using field reflection",
                     counter="evals.detail_of")
    if is_dataclass(finding):
        return {f.name: _jsonable(getattr(finding, f.name, None)) for f in _dc_fields(finding)}
    try:
        return {k: _jsonable(v) for k, v in vars(finding).items()}
    except TypeError:
        return {"value": _jsonable(finding)}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _text_of(finding: Any) -> str:
    """Human-readable text for a finding. The guards expose this under three
    different names depending on vintage; try each before falling back."""
    for attr in ("to_prompt_text", "caveat"):
        fn = getattr(finding, attr, None)
        if callable(fn):
            try:
                text = fn()
                if text:
                    return str(text)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, f"{type(finding).__name__}.{attr}() failed; trying the next form",
                         counter="evals.text_of")
    for attr in ("message", "reason", "detail"):
        val = getattr(finding, attr, None)
        if isinstance(val, str) and val:
            return val
    return str(finding)


class _Base:
    """Shared plumbing: identity, and the pass/fail → EvalScore shaping."""

    def __init__(self, name: str, fn: Callable, *, severity: str = WARN,
                 requires: tuple[str, ...] = ("sql",), deterministic: bool = True):
        self.name = name
        self.fn = fn
        self.severity = severity
        self.requires = requires
        self.deterministic = deterministic

    def _score(self, checks: list[Check], *, detail: Optional[dict] = None) -> EvalScore:
        passed = not checks
        return EvalScore(
            evaluator=self.name, passed=passed, value=1.0 if passed else 0.0,
            checks=tuple(checks),
            rationale="" if passed else checks[0].reason,
            detail=detail or {},
        )

    def _skip(self, why: str) -> EvalScore:
        return EvalScore(evaluator=self.name, passed=True, value=0.0,
                         skipped=True, rationale=why)


class ListFindingEvaluator(_Base):
    """S1 — ``fn(...) -> list[Finding]``. One Check per finding."""

    def __init__(self, name: str, fn: Callable, *, args: Callable, **kw):
        super().__init__(name, fn, **kw)
        self._args = args      # (case, obs) -> (args_tuple, kwargs_dict)

    def evaluate(self, case: EvalCase, obs: EvalObservation) -> EvalScore:
        a, kw = self._args(case, obs)
        findings = self.fn(*a, **kw) or []
        checks = [
            Check(name=self.name, ok=False, severity=self.severity,
                  reason=_text_of(f), detail=_detail_of(f))
            for f in findings
        ]
        return self._score(checks, detail={"finding_count": len(findings)})


class HintEvaluator(_Base):
    """S2 — ``fn(...) -> str | None`` (or ``list[str]``). A hint means a defect."""

    def __init__(self, name: str, fn: Callable, *, args: Callable, **kw):
        super().__init__(name, fn, **kw)
        self._args = args

    def evaluate(self, case: EvalCase, obs: EvalObservation) -> EvalScore:
        a, kw = self._args(case, obs)
        out = self.fn(*a, **kw)
        hints = [h for h in (out if isinstance(out, (list, tuple)) else [out]) if h]
        checks = [
            Check(name=self.name, ok=False, severity=self.severity, reason=str(h))
            for h in hints
        ]
        return self._score(checks)


class OptionalFindingEvaluator(_Base):
    """S3 — ``fn(...) -> Finding | None``."""

    def __init__(self, name: str, fn: Callable, *, args: Callable, **kw):
        super().__init__(name, fn, **kw)
        self._args = args

    def evaluate(self, case: EvalCase, obs: EvalObservation) -> EvalScore:
        a, kw = self._args(case, obs)
        finding = self.fn(*a, **kw)
        checks = ([] if finding is None else
                  [Check(name=self.name, ok=False, severity=self.severity,
                         reason=_text_of(finding), detail=_detail_of(finding))])
        return self._score(checks)


class PredicateEvaluator(_Base):
    """S4 — ``fn(...) -> bool`` (or a non-empty collection). Truthy = a defect.

    Inverted relative to the others because these guards answer "is this
    dangerous?" rather than "what is wrong with it?".
    """

    def __init__(self, name: str, fn: Callable, *, args: Callable,
                 reason: str = "", **kw):
        super().__init__(name, fn, **kw)
        self._args = args
        self._reason = reason

    def evaluate(self, case: EvalCase, obs: EvalObservation) -> EvalScore:
        a, kw = self._args(case, obs)
        out = self.fn(*a, **kw)
        if not out:
            return self._score([])
        detail = {} if isinstance(out, bool) else {"value": _jsonable(out)}
        reason = self._reason or f"{self.name} flagged this statement"
        if detail:
            reason = f"{reason}: {detail['value']}"
        return self._score(
            [Check(name=self.name, ok=False, severity=self.severity,
                   reason=reason, detail=detail)])


class OkReasonEvaluator(_Base):
    """S6 — ``fn(...) -> (ok: bool, reason: str)``."""

    def __init__(self, name: str, fn: Callable, *, args: Callable, **kw):
        super().__init__(name, fn, **kw)
        self._args = args

    def evaluate(self, case: EvalCase, obs: EvalObservation) -> EvalScore:
        a, kw = self._args(case, obs)
        ok, reason = self.fn(*a, **kw)
        checks = ([] if ok else
                  [Check(name=self.name, ok=False, severity=self.severity,
                         reason=str(reason or ""))])
        return self._score(checks)


# ── argument builders ─────────────────────────────────────────────────────────
# Each says how one guard family wants to be called. Kept here (not in builtins)
# so registration stays a one-line table.

def sql_only(case: EvalCase, obs: EvalObservation):
    return (sql_of(case, obs),), {}


def sql_dialect(case: EvalCase, obs: EvalObservation):
    return (sql_of(case, obs),), {"dialect": case.scope.dialect}


def sql_tablecols_dialect(case: EvalCase, obs: EvalObservation):
    """The ``fanout`` family. ``table_cols`` is optional there — the guards
    degrade rather than fail — so a case without it still gets checked."""
    cols = {k: list(v) for k, v in (case.table_cols or {}).items()} or None
    return (sql_of(case, obs),), {"table_cols": cols, "dialect": case.scope.dialect}


def conn_sql(case: EvalCase, obs: EvalObservation):
    return (case.scope.conn, sql_of(case, obs)), {}
