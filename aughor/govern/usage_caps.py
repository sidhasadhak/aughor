"""Wave G4 — org and per-user usage caps, with algebra that is honest about overlap.

**This is not the fourth "budget".** Three already exist and each governs something else:
``security.sandbox.QueryBudget`` bounds ONE query's rows and wall time,
``llm.context_budget`` bounds how many tokens a prompt may carry, and
``evals.experiments.estimate_requests`` bounds how many requests a grid may spend. None of
them answers "has this org spent more than it is allowed this week", which is what a cap
is. The word is overloaded; the concepts are not, so this module says *cap* throughout and
never touches the other three.

**The algebra, and why it is two rules rather than one.**

*Most-permissive WITHIN a scope.* Two caps on the same subject and metric are two
statements about the same allowance, and the larger one is the operator's most recent
intent about how much that subject may use. Taking the smaller would mean an operator who
raised a limit has to hunt for the old row before the raise takes effect.

*Most-restrictive ACROSS scopes.* An org cap and a user cap are statements about
*different* things — the pool, and one person's share of it. Both hold simultaneously, so
the binding constraint is whichever is breached first. Taking the permissive reading here
would let one user exhaust the org pool because their personal cap was generous.

Getting these backwards in either direction is a real outage or a real overspend, which is
why they are separate functions with separate tests rather than one clever comparator.

**Enforcement never claws back in-flight work.** :func:`check` is a PRE-FLIGHT question —
"may this start" — and there is deliberately no abort path. Killing a running
investigation because a cap tipped mid-run destroys work the user already paid for, and
leaves a partial artifact whose provenance says it completed. A cap that is breached stops
the NEXT thing.

**A breach is a typed, named refusal.** ``budget_exceeded`` joins the R4 error tail with
the metric, the limit, the observed value and the window, so a caller can say *"this org
has used 1,043 of 1,000 calls in the last 24h"* rather than failing opaquely. Same rule as
G2's clearance block: withhold the work, never the reason.

Deterministic and pure — :func:`evaluate` takes caps and a usage reading. Reading actual
usage is :mod:`aughor.obs.usage`'s job and the store's; keeping them apart is what makes
the algebra testable without a Ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

#: What a cap can be expressed in. Mirrors the columns G3a's rollup already produces, so a
#: cap is always checkable against a real number rather than an estimated one.
METRICS: tuple[str, ...] = ("calls", "total_tokens", "cost_usd")

#: Who a cap applies to. Ordered coarse → fine; `across` scopes all bind at once.
SCOPES: tuple[str, ...] = ("org", "user")

#: What happens on breach. `alert` records and proceeds; `block` refuses the next start.
ACTIONS: tuple[str, ...] = ("alert", "block")

CapAction = Literal["alert", "block"]


@dataclass(frozen=True)
class UsageCap:
    """One allowance: this subject may use this much of this metric per window."""

    scope: str                  # "org" | "user"
    subject: str                # the org id or user id ("*" = any subject in the scope)
    metric: str                 # one of METRICS
    limit: float
    window_hours: int = 24
    action: CapAction = "alert"

    def applies_to(self, *, org_id: str, user_id: str) -> bool:
        if self.scope == "org":
            return self.subject in ("*", org_id)
        if self.scope == "user":
            # A per-user cap with subject "*" is the common case: "nobody may exceed X".
            return self.subject in ("*", user_id) and bool(user_id)
        return False

    def to_dict(self) -> dict:
        return {"scope": self.scope, "subject": self.subject, "metric": self.metric,
                "limit": self.limit, "window_hours": self.window_hours,
                "action": self.action}


@dataclass
class Breach:
    """One cap that the observed usage exceeds."""

    cap: UsageCap
    observed: float

    @property
    def over_by(self) -> float:
        return round(self.observed - self.cap.limit, 6)

    def describe(self) -> str:
        return (f"{self.cap.scope} {self.cap.subject} used {self.observed:g} "
                f"{self.cap.metric} against a limit of {self.cap.limit:g} "
                f"per {self.cap.window_hours}h")

    def to_dict(self) -> dict:
        return {**self.cap.to_dict(), "observed": self.observed,
                "over_by": self.over_by, "detail": self.describe()}


@dataclass
class CapDecision:
    """May the next unit of work start, and what did the caps say?"""

    allowed: bool = True
    blocked_by: Optional[Breach] = None
    alerts: list[Breach] = field(default_factory=list)
    considered: int = 0

    @property
    def reason(self) -> str:
        """The user-facing sentence. Names the number, never just 'quota exceeded'."""
        if self.allowed or self.blocked_by is None:
            return ""
        b = self.blocked_by
        return (f"Usage cap reached: {b.describe()}. This request was not started; "
                f"work already running is unaffected.")

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "considered": self.considered,
                "blocked_by": self.blocked_by.to_dict() if self.blocked_by else None,
                "alerts": [a.to_dict() for a in self.alerts],
                "reason": self.reason,
                "error_class": None if self.allowed else "budget_exceeded"}


def effective_limit(caps: Iterable[UsageCap]) -> Optional[float]:
    """MOST-PERMISSIVE within one scope+metric: the largest limit stated.

    Two rows about the same subject and metric are two statements about one allowance, and
    the larger is the operator's latest intent. Taking the smaller would mean raising a
    limit does nothing until somebody finds and deletes the old row.
    """
    limits = [c.limit for c in caps]
    return max(limits) if limits else None


def _binding_caps(
    caps: Iterable[UsageCap], *, org_id: str, user_id: str,
) -> dict[tuple[str, str], UsageCap]:
    """Collapse to one cap per (scope, metric) using the within-scope rule."""
    buckets: dict[tuple[str, str], list[UsageCap]] = {}
    for cap in caps:
        if cap.metric not in METRICS or cap.scope not in SCOPES:
            continue
        if not cap.applies_to(org_id=org_id, user_id=user_id):
            continue
        buckets.setdefault((cap.scope, cap.metric), []).append(cap)

    out: dict[tuple[str, str], UsageCap] = {}
    for key, group in buckets.items():
        winner = max(group, key=lambda c: c.limit)
        # A `block` anywhere in the group survives the merge: the permissive rule is about
        # HOW MUCH is allowed, never about whether a breach is enforced. Merging two caps
        # into a larger allowance that silently downgrades to `alert` would turn raising a
        # limit into disabling the gate.
        action: CapAction = "block" if any(c.action == "block" for c in group) else "alert"
        out[key] = UsageCap(scope=winner.scope, subject=winner.subject,
                            metric=winner.metric, limit=winner.limit,
                            window_hours=winner.window_hours, action=action)
    return out


def evaluate(
    caps: Iterable[UsageCap],
    usage: dict[str, float],
    *,
    org_id: str = "default",
    user_id: str = "",
) -> CapDecision:
    """Decide whether the next unit of work may start.

    ``usage`` maps a metric name to the subject's observed value in the cap's window.

    MOST-RESTRICTIVE ACROSS scopes: every applicable scope binds at once, and the first
    `block` breach found (org before user, coarse before fine) is the one reported — so
    the message names the pool that is actually exhausted rather than an incidental
    personal limit.
    """
    binding = _binding_caps(caps, org_id=org_id, user_id=user_id)
    decision = CapDecision(considered=len(binding))

    for scope in SCOPES:                      # coarse → fine
        for metric in METRICS:
            cap = binding.get((scope, metric))
            if cap is None:
                continue
            observed = float(usage.get(metric, 0) or 0)
            if observed <= cap.limit:
                continue
            breach = Breach(cap=cap, observed=observed)
            if cap.action == "block" and decision.blocked_by is None:
                decision.allowed = False
                decision.blocked_by = breach
            else:
                decision.alerts.append(breach)
    return decision


def enabled() -> bool:
    """Whether cap enforcement is live. Off ⇒ every decision allows.

    Read at call time so a test's ``monkeypatch.setenv`` is never a no-op.
    """
    from aughor.kernel.flags import flag_enabled

    return flag_enabled("govern.usage_caps")


def check(
    *,
    org_id: str = "default",
    user_id: str = "",
    caps: Optional[Iterable[UsageCap]] = None,
    scan: int = 5000,
) -> CapDecision:
    """Store-backed pre-flight check: read the caps and the usage, then :func:`evaluate`.

    Returns an unconditional allow when the flag is off, so a caller can wire this in
    front of expensive work unconditionally and the off state costs one boolean.
    """
    if not enabled():
        return CapDecision(allowed=True)

    from aughor.govern.cap_store import list_caps

    resolved = list(caps) if caps is not None else list_caps(org_id=org_id)
    if not resolved:
        return CapDecision(allowed=True)

    windows = {c.window_hours for c in resolved} or {24}
    usage = observed_usage(org_id=org_id, user_id=user_id,
                           window_hours=max(windows), scan=scan)
    return evaluate(resolved, usage, org_id=org_id, user_id=user_id)


def observed_usage(
    *, org_id: str = "default", user_id: str = "", window_hours: int = 24,
    scan: int = 5000,
) -> dict[str, float]:
    """The subject's usage over the window, in the metrics a cap can name.

    Reads G3a's rollup rather than re-deriving from the Ledger, so a cap is measured by
    the same code the usage page shows. Two readers of one number is how a cap and a
    dashboard come to disagree about whether a limit was hit.
    """
    from datetime import datetime, timedelta, timezone

    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import LLM_CALL
    from aughor.obs.usage import rollup

    rows = Ledger.default().session_events(kind=LLM_CALL, org_id=org_id, limit=scan) or []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(window_hours)))
              ).isoformat()
    # The session-events timestamp column is `at` — reading a key that does not
    # exist made every row fall outside the window, so no cap could ever trip.
    in_window = [r for r in rows if str(r.get("at") or "") >= cutoff]
    if user_id:
        in_window = [r for r in in_window if str(r.get("user_id") or "") == user_id]

    report = rollup(in_window, axes=("org_id",))
    totals = {"calls": 0.0, "total_tokens": 0.0, "cost_usd": 0.0}
    for row in report.rows:
        totals["calls"] += row.calls
        totals["total_tokens"] += row.total_tokens
        totals["cost_usd"] += row.cost_usd
    return totals
