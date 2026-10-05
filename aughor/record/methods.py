"""The method interface — a forecaster, estimator or simulator registered with its backtest and
run as a foreign MCP tool, never inside the process (the 2027 study §L and §Q; phase 7, P7-4).

The scenario ladder's first four methods are code in `record/scenario.py`. A fifth and later come
from outside — a vendor's forecaster, a bought estimator, a simulation — and the interface they come
through is a DECLARATION the platform holds, not code it runs:

- **a registered method is a kernel artifact** (kind ``method``): its name, its kind, who declared
  it, the backtest it carries (how many cases, the error, how often its interval held, and where it
  was measured — a method with no backtest is refused, because a projection nobody has scored is a
  guess with a name), the tier a prediction under it takes, and the foreign MCP tool it runs as;
- **it runs through the one door** every foreign tool runs through (`mcpservers/call.py`: the
  server allowlist, the roster, the read-only gate or a person's grant, the outbound cap, the span,
  the audit line). Nothing registered here executes in the platform's process;
- **it answers in the ladder's shape**: a :class:`~aughor.record.scenario.Projection` with its value,
  band and coverage, the method's backtest and what it must say — so a prediction made under it is
  scored by the same tick and counted in the same calibration as the built-in methods'.

`scenario.project` dispatches here for any name that is not built in; an unknown name is still
refused by name.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Optional

from pydantic import BaseModel, Field

KIND = "method"
KINDS: tuple[str, ...] = ("forecaster", "estimator", "simulator")
ADAPTERS: tuple[str, ...] = ("mcp",)


class Backtest(BaseModel):
    n: int = 0
    metric: str = ""                      # the metric it was measured on, when one
    mae: Optional[float] = None
    mape: Optional[float] = None
    coverage_stated: Optional[float] = None
    coverage_observed: Optional[float] = None
    measured_on: list[str] = Field(default_factory=list)   # installs or datasets
    note: str = ""


class Adapter(BaseModel):
    kind: str = "mcp"
    server_id: str = ""
    tool: str = ""


class Method(BaseModel):
    name: str
    kind: str                             # forecaster | estimator | simulator
    declared_by: str = ""
    backtest: Backtest = Field(default_factory=Backtest)
    adapter: Adapter = Field(default_factory=Adapter)
    tier: str = "mined"                   # the tier a prediction under it takes
    inputs: list[str] = Field(default_factory=list)
    note: str = ""
    active: bool = True
    registered_at: str = ""
    withdrawn_at: str = ""
    id: str = ""
    key: str = ""
    version: int = 0


class MethodRefused(ValueError):
    """The door said no, and why."""


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def method_key(name: str) -> str:
    return f"method:{name}"


def _from(art: dict) -> Method:
    m = Method.model_validate(dict(art.get("payload") or {}))
    m.id, m.key, m.version = str(art.get("id") or ""), str(art.get("natural_key") or ""), int(art.get("version") or 0)
    return m


def _book(m: Method) -> Method:
    data = m.model_dump()
    for read_only in ("id", "key", "version"):
        data.pop(read_only, None)
    aid = _ledger().artifact_write(KIND, method_key(m.name), data,
                                   lineage=[("runs_as", f"{m.adapter.server_id}:{m.adapter.tool}", m.adapter.kind)])
    art = _ledger().artifact_by_id(aid)
    return _from(art) if art else m


def builtin_names() -> tuple[str, ...]:
    from aughor.record.scenario import METHODS
    return METHODS


def register(m: Method, *, by: str) -> Method:
    """Register (or re-register: a new version) a method. Refuses a built-in name, an unknown kind,
    an adapter that is not a foreign MCP tool, and — the rule — a method with no backtest."""
    name = (m.name or "").strip()
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        raise MethodRefused("a method's name is letters, digits, '-' or '_'")
    if name in builtin_names():
        raise MethodRefused(f"{name!r} is a built-in method of the ladder; register under another name")
    if m.kind not in KINDS:
        raise MethodRefused(f"a method's kind is one of {', '.join(KINDS)}")
    if m.adapter.kind not in ADAPTERS or not (m.adapter.server_id and m.adapter.tool):
        raise MethodRefused("a method runs as a foreign MCP tool (adapter.kind 'mcp', server_id, tool); nothing runs inside the process")
    bt = m.backtest
    if bt.n <= 0 or not bt.measured_on:
        raise MethodRefused("a method carries its backtest: the cases it was scored on (n > 0) and where (measured_on) — "
                            "a projection nobody has scored is a guess with a name")
    if bt.mae is None and bt.mape is None and bt.coverage_observed is None:
        raise MethodRefused("a backtest states an error (mae or mape) or how often its interval held (coverage_observed)")
    if m.tier not in ("mined", "said"):
        raise MethodRefused("a prediction under a registered method takes tier 'mined' (a reviewed computation) or 'said'")
    if not (by or "").strip():
        raise MethodRefused("a method is registered by a named principal")
    m.name, m.declared_by, m.active = name, m.declared_by or by, True
    m.registered_at = m.registered_at or _now()
    booked = _book(m)
    try:
        _ledger().emit("method.registered", {"method": name, "kind": m.kind, "by": by, "backtest": bt.model_dump()})
    except Exception:  # noqa: BLE001 — the artifact is the authority
        pass
    return booked


def withdraw(name: str, *, by: str) -> Method:
    m = get_method(name, active_only=False)
    if m is None:
        raise MethodRefused(f"no method named {name!r}")
    m.active, m.withdrawn_at = False, _now()
    booked = _book(m)
    try:
        _ledger().emit("method.registered", {"method": name, "kind": m.kind, "by": by, "backtest": m.backtest.model_dump(), "active": False})
    except Exception:  # noqa: BLE001
        pass
    return booked


def get_method(name: str, *, active_only: bool = True) -> Optional[Method]:
    art = _ledger().artifact_latest(method_key(name))
    if not art or art.get("kind") != KIND:
        return None
    m = _from(art)
    return m if (m.active or not active_only) else None


def list_methods(*, active_only: bool = True) -> list[Method]:
    out = [_from(a) for a in _ledger().artifacts_of_kind(KIND, limit=500)]
    return [m for m in out if m.active] if active_only else out


def _json_safe(kw: dict) -> dict:
    out = {}
    for k, v in (kw or {}).items():
        if k in ("run_sql", "run_sql_for"):
            continue
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            continue
        out[k] = v
    return out


def project_registered(name: str, **kw):
    """Run a registered method through the foreign-tool door and read its answer in the ladder's
    shape. A call the door refused, blocked or that failed projects nothing — with the door's own
    word for what happened, so a refusal is never mistaken for a zero."""
    from aughor.record.scenario import Projection
    m = get_method(name)
    if m is None:
        raise ValueError(f"no method named {name!r} on the ladder or registered")
    said = [f"{m.kind} {m.name}, registered by {m.declared_by}; backtest"
            + (f" on {m.backtest.metric}" if m.backtest.metric else "") + f": n={m.backtest.n}"
            + (f", mae {m.backtest.mae}" if m.backtest.mae is not None else "")
            + (f", mape {m.backtest.mape}" if m.backtest.mape is not None else "")
            + (f", interval held {m.backtest.coverage_observed:.0%}" if m.backtest.coverage_observed is not None else "")
            + f"; measured on {', '.join(m.backtest.measured_on)}",
            "ran as a foreign tool through the one door; nothing of it runs inside the platform"]
    from aughor.mcpservers.call import call
    arguments = _json_safe(kw)
    try:
        result = call(m.adapter.server_id, m.adapter.tool, arguments)
    except Exception as exc:  # noqa: BLE001 — the door raises for nothing it can say; say it
        return Projection(method=name, tier=m.tier, backtest=m.backtest.model_dump(), inputs={"arguments": arguments},
                          note=f"the method's tool could not be called: {str(exc)[:160]}", must_say=said)
    status = getattr(result, "status", "failed")
    if status != "executed":
        return Projection(method=name, tier=m.tier, backtest=m.backtest.model_dump(), inputs={"arguments": arguments},
                          note=f"the method's tool was {status}: {getattr(result, 'message', '') or 'no reason given'}", must_say=said)
    try:
        answer = json.loads(getattr(result, "text", "") or "{}")
    except ValueError:
        return Projection(method=name, tier=m.tier, backtest=m.backtest.model_dump(), inputs={"arguments": arguments},
                          note="the method's tool did not answer in the ladder's shape (JSON with value, low, high, coverage)", must_say=said)
    if not isinstance(answer, dict) or answer.get("value") is None:
        return Projection(method=name, tier=m.tier, backtest=m.backtest.model_dump(), inputs={"arguments": arguments},
                          note=f"the method's tool answered without a value: {str(answer)[:120]}", must_say=said)
    value = float(answer["value"])
    low = float(answer["low"]) if answer.get("low") is not None else value
    high = float(answer["high"]) if answer.get("high") is not None else value
    extra_said = [str(s) for s in (answer.get("must_say") or []) if str(s).strip()][:6]
    return Projection(method=name, tier=m.tier, value=value, low=low, high=high,
                      coverage=float(answer["coverage"]) if answer.get("coverage") is not None else m.backtest.coverage_stated,
                      unit=str(answer.get("unit") or kw.get("unit") or ""), backtest=m.backtest.model_dump(),
                      inputs={"arguments": arguments, "tool": f"{m.adapter.server_id}:{m.adapter.tool}"},
                      must_say=said + extra_said)
