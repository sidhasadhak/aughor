"""Scoped, windowed budget governance — the control plane's spend gate (Invariant #2).

PLATFORM_ARCHITECTURE.md §4: the control plane resolves *who · what catalog · which
scoped credential · **what budget*** and hands compute a capability. Until now the
"budget" was only ever **per-run**: the Job Kernel kills a single run that blows its
token/time cap (``kernel/jobs.py`` ``_over_budget``). Nothing capped the *cumulative*
spend of an Org or an agent across many runs — an org could burn unbounded tokens a
run at a time and never trip the per-run gate. This module is the missing seam.

The design follows the same control-plane grammar as the rest of the platform:

  • **Reconcile-on-read** (like grants): spend is *derived* by summing the metered
    token counts already flushed onto job rows (``kernel/metering.py`` →
    ``jobs.metrics.total_tokens``). There is **no new write path** and no double-entry
    ledger to keep consistent — the job rows are the source of truth.
  • **Incidents are derived, not stored.** ``status`` is a pure function of (policy,
    spent), so raising a limit *automatically* clears a breach (the
    "raise-budget-clears-incident" property) with no acknowledged/dismissed state to
    reconcile. (A persisted-incident table — for ack/dismiss memory — is a later step.)
  • **Tokens, not money.** We cap the signal we meter *exactly* (tokens); a dollar cap
    needs a per-model price table that drifts and is deliberately deferred (mirrors the
    metering module's "honest compute, not money" contract).
  • **Fail-open and opt-in.** Any resolution error never blocks a run, and with **no
    policy set the gate is a no-op** — existing behaviour is byte-identical until an
    operator configures a cap.

The gate is consulted at the **submit chokepoint** (``JobKernel.submit``) — Paperclip's
"block before checkout, not mid-flight" — so the whole fleet flows through one seam.

Scopes (v1): ``"org"`` (scope_id = org id) and ``"agent"`` (scope_id = charter id,
summed within the current Org). Windows: ``"calendar_month"`` (UTC) and ``"lifetime"``.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from aughor.org.context import current_org_id

if TYPE_CHECKING:
    from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)

_POLICY_STORE = "budget_policies"

ScopeType = str  # "org" | "agent"
Window = str     # "calendar_month" | "lifetime"

# Reconcile-on-read scans recent job rows. A high cap so a busy month is summed in
# full; a materialised monthly rollup is the documented follow-up (the on-read
# aggregation does not scale to very high job volumes — Paperclip's own caveat).
_RECONCILE_LIMIT = 5000


def _ledger() -> "Ledger":
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


# ── policy model + store ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetPolicy:
    """A cumulative spend cap on one scope over one window. ``limit_tokens`` is the
    hard ceiling; ``warn_percent`` is the soft threshold for surfacing a warning."""

    scope_type: ScopeType
    scope_id: str
    limit_tokens: int
    window: Window = "calendar_month"
    warn_percent: int = 80
    hard_stop: bool = True
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _key(scope_type: str, scope_id: str) -> str:
    return f"{scope_type}:{scope_id}"


def _policy_from_row(row: dict) -> Optional[BudgetPolicy]:
    if not isinstance(row, dict) or "limit_tokens" not in row:
        return None
    try:
        return BudgetPolicy(
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            limit_tokens=int(row["limit_tokens"]),
            window=str(row.get("window") or "calendar_month"),
            warn_percent=int(row.get("warn_percent", 80)),
            hard_stop=bool(row.get("hard_stop", True)),
            active=bool(row.get("active", True)),
        )
    except (TypeError, ValueError):
        return None


def get_policy(scope_type: str, scope_id: str, *, ledger: Optional["Ledger"] = None) -> Optional[BudgetPolicy]:
    """The configured policy for a scope, or ``None`` (unbounded)."""
    led = ledger or _ledger()
    try:
        return _policy_from_row(led.kv_get(_POLICY_STORE, _key(scope_type, scope_id), {}) or {})
    except Exception:
        return None


def set_policy(
    scope_type: str,
    scope_id: str,
    *,
    limit_tokens: int,
    window: Window = "calendar_month",
    warn_percent: int = 80,
    hard_stop: bool = True,
    active: bool = True,
    ledger: Optional["Ledger"] = None,
) -> BudgetPolicy:
    """Persist a budget policy for a scope. Returns the stored policy."""
    pol = BudgetPolicy(
        scope_type=scope_type, scope_id=scope_id, limit_tokens=int(limit_tokens),
        window=window, warn_percent=int(warn_percent), hard_stop=bool(hard_stop),
        active=bool(active),
    )
    (ledger or _ledger()).kv_put(_POLICY_STORE, _key(scope_type, scope_id), pol.to_dict())
    return pol


def delete_policy(scope_type: str, scope_id: str, *, ledger: Optional["Ledger"] = None) -> None:
    """Remove a policy (back to unbounded). Implemented as a write of an empty row so
    it works on a plain kv store without a delete primitive."""
    (ledger or _ledger()).kv_put(_POLICY_STORE, _key(scope_type, scope_id), {})


# ── spend (reconcile-on-read from the metered job rows) ───────────────────────


def _window_start(window: str) -> Optional[datetime]:
    """Inclusive lower bound for a window, or ``None`` for lifetime (no bound)."""
    if window == "lifetime":
        return None
    now = datetime.now(timezone.utc)
    # calendar_month (default): first instant of the current UTC month.
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _job_time(job: dict) -> Optional[datetime]:
    raw = job.get("finished_at") or job.get("started_at") or job.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _job_in_scope(job: dict, scope_type: str, scope_id: str, org_id: str) -> bool:
    if scope_type == "org":
        return (job.get("org_id") or "default") == scope_id
    if scope_type == "agent":
        # An agent's spend is its kind's runs within the current Org.
        if (job.get("org_id") or "default") != org_id:
            return False
        from aughor.kernel.agents import charter_for_kind
        return charter_for_kind(job.get("kind")).id == scope_id
    return False


def spend_tokens(
    scope_type: str,
    scope_id: str,
    *,
    window: Window = "calendar_month",
    org_id: Optional[str] = None,
    ledger: Optional["Ledger"] = None,
) -> int:
    """Cumulative ``total_tokens`` for a scope in a window, summed from job rows.

    Reconcile-on-read: job rows already carry per-run metered metrics; nothing else
    needs to be true for this to be correct. ``org_id`` scopes the *agent* case (it
    defaults to the current tenant); the *org* case is self-scoped by ``scope_id``."""
    led = ledger or _ledger()
    oid = org_id or current_org_id()
    start = _window_start(window)
    total = 0
    try:
        rows = led.jobs_where(limit=_RECONCILE_LIMIT)
    except Exception:
        return 0
    for job in rows:
        m = job.get("metrics")
        if not isinstance(m, dict):
            continue  # no flushed metrics → contributes nothing
        if not _job_in_scope(job, scope_type, scope_id, oid):
            continue
        if start is not None:
            t = _job_time(job)
            if t is not None and t < start:
                continue  # outside the window (unparseable time counts — never under-cap)
        tok = m.get("total_tokens")
        if isinstance(tok, (int, float)):  # guard, not try/except — no silent swallow
            total += int(tok)
    return total


# ── status (derived incident) + the preflight gate ───────────────────────────


@dataclass(frozen=True)
class BudgetStatus:
    scope_type: str
    scope_id: str
    window: str
    spent_tokens: int
    limit_tokens: Optional[int]   # None = unbounded (no policy)
    percent: Optional[float]      # None = unbounded
    state: str                    # "unbounded" | "ok" | "warning" | "hard_stop"
    hard_stop: bool

    def to_dict(self) -> dict:
        return asdict(self)


def status(scope_type: str, scope_id: str, *, ledger: Optional["Ledger"] = None,
           org_id: Optional[str] = None) -> BudgetStatus:
    """The derived budget state for a scope. With no policy → ``unbounded`` (spend is
    still reported, over the default monthly window, for display)."""
    led = ledger or _ledger()
    pol = get_policy(scope_type, scope_id, ledger=led)
    if pol is None or not pol.active:
        spent = spend_tokens(scope_type, scope_id, ledger=led, org_id=org_id)
        return BudgetStatus(scope_type, scope_id, "calendar_month", spent, None, None,
                            "unbounded", hard_stop=False)
    spent = spend_tokens(scope_type, scope_id, window=pol.window, ledger=led, org_id=org_id)
    limit = pol.limit_tokens
    percent = round(100.0 * spent / limit, 1) if limit > 0 else None
    warn_at = (limit * pol.warn_percent) / 100.0
    if pol.hard_stop and spent >= limit:
        state = "hard_stop"
    elif spent >= warn_at:
        state = "warning"
    else:
        state = "ok"
    return BudgetStatus(scope_type, scope_id, pol.window, spent, limit, percent, state,
                        hard_stop=pol.hard_stop)


def block_reason(scope_type: str, scope_id: str, *, ledger: Optional["Ledger"] = None,
                 org_id: Optional[str] = None) -> Optional[str]:
    """The hard-stop reason for a scope, or ``None`` if it may proceed. Fail-open: any
    resolution error returns ``None`` (a budget read must never wedge the fleet)."""
    try:
        st = status(scope_type, scope_id, ledger=ledger, org_id=org_id)
    except Exception:
        return None
    if st.state == "hard_stop":
        return (f"{scope_type} '{scope_id}' over budget "
                f"({st.spent_tokens:,} / {st.limit_tokens:,} tokens this {st.window})")
    return None


def preflight_block_for_kind(kind: Optional[str], *, ledger: Optional["Ledger"] = None) -> Optional[str]:
    """The submit-time gate: would a run of ``kind`` exceed a hard cap on its Org or its
    agent scope? Returns the first blocking reason, or ``None``. Best-effort/fail-open.

    Checked in this order: Org cap (the broadest authority) then the agent's own cap."""
    led = ledger or _ledger()
    oid = current_org_id()
    org_block = block_reason("org", oid, ledger=led, org_id=oid)
    if org_block:
        return org_block
    try:
        from aughor.kernel.agents import charter_for_kind
        agent_id = charter_for_kind(kind).id
    except Exception:
        return None
    return block_reason("agent", agent_id, ledger=led, org_id=oid)
