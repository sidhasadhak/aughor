"""Wave G3 — usage attribution over the session log's LLM calls.

**What was already there, and what actually had to be built.** The program scoped G3 as
"J8's ``llm.*`` counters rolled up per org/user/feature". Measuring first found that the
counters were the wrong source and mostly already superseded: only four ``llm.*`` counters
exist and they cover repair/salvage, while :func:`aughor.llm.provider._record_llm_call`
already mirrors *every* model call into the session log with provider, model and token
counts in real columns. The rollup problem was solved at the data layer. The reporting
problem was not — there is no usage surface, and :func:`session_log.model_usage` groups by
model alone, with no cost and no feature dimension.

**Which axes are real, measured rather than assumed.** On 273 recorded calls:

    provider  100%     model  100%     role (feature)  100%     org_id  100%
    user_id     0%     conn_id  0%     agent_id          0%     tokens   90%

That measurement moved the design twice. Reading the *source* for ``role=`` suggested the
feature axis was empty — twelve call sites pass ``role=""`` — but the *data* says it is
fully populated (``coder`` 262, ``fast`` 8, ``narrator`` 3), because the role is resolved
at runtime from the model tier and never appears as a literal. Grep the data, not the
source. Conversely ``user_id``/``conn_id`` looked available (they are real columns on
every event) and are empty in practice, because identity comes from the ambient trace and
there is no principal in local mode.

**Wave H2 re-measured ``agent_id`` before adding it as an axis, and the 0% turned out to
mean something different from the other two.** ``user_id``/``conn_id`` are 0% because
nothing populates them; ``agent_id`` is 0% because on that corpus nobody had ever asked
*as* an agent — the write path (persona contextvar → :func:`aughor.telemetry.trace_identity`
→ every session event) was already complete. So H2 is a reporting change: the column was
being written and simply could not be grouped by. The distinction matters for reading this
table later — a 0% that means "never exercised" becomes populated by USE, and a 0% that
means "never written" only ever changes by a code edit.

So this module reports the axes that carry information and is **loud about the ones that
do not**: every rollup returns an ``unattributed`` count per axis rather than folding
blanks into a group that then reads as a real cohort. A usage page whose largest row is
``""`` has taught its reader nothing and looks broken; one that says "142 calls could not
be attributed to a user" has said something true and actionable.

**Cost is declared, never inferred.** Prices live in :data:`PRICES` with the date they were
taken. A model with no declared price contributes ``None`` to cost and increments
``unpriced_calls`` — it is never silently zero. This is the same discipline
``model_usage`` already applies to ``calls_without_usage``, and for the same reason: a
missing input that rounds to zero makes every aggregate above it quietly wrong, and the
number that is wrong is the one somebody will put in a budget.

Deterministic, read-only, no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from aughor.obs.session_log import LLM_CALL

#: The axes a caller may group by. Each maps to how one session-log row yields its value.
#:
#: ``agent_id`` is the USER-DEFINED persona a call ran as (Wave H2), read from the same
#: ambient contextvar :func:`aughor.telemetry.trace_identity` already stamps onto every
#: session event — the write path predates this axis, which is why adding it is a reporting
#: change and not a plumbing one. It is **not** the fleet charter id that
#: ``kernel/jobs.py`` resolves per job kind (scout/analyst/watcher): those name what KIND of
#: platform work ran, this names WHOSE persona asked, and grouping spend by one while
#: labelling it the other would misattribute every number on the page.
AXES: dict[str, Any] = {
    "provider": lambda e: e.get("provider") or "",
    "model": lambda e: e.get("model") or "",
    "feature": lambda e: ((e.get("payload") or {}).get("role") or ""),
    "org_id": lambda e: e.get("org_id") or "",
    "user_id": lambda e: e.get("user_id") or "",
    "conn_id": lambda e: e.get("conn_id") or "",
    "agent_id": lambda e: e.get("agent_id") or "",
}

DEFAULT_AXES: tuple[str, ...] = ("provider", "model")


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens, with the date the figure was taken.

    ``as_of`` is not decoration. A price table with no date is a claim that cannot be
    audited or refreshed, and provider pricing moves; a reader deciding whether to trust a
    cost figure needs to know how old the rate behind it is.
    """

    input_per_1m: float
    output_per_1m: float
    as_of: str


#: Declared prices, keyed by ``(provider, model-prefix)``; the LONGEST matching prefix
#: wins so a family rate can be overridden per model. Deliberately small — an entry here
#: is a claim about money, and a guessed one is worse than an absent one, which at least
#: reports itself as unpriced.
PRICES: dict[tuple[str, str], Price] = {
    # OpenRouter ':free' models are the platform's working tier and genuinely bill $0.
    # Encoded explicitly rather than left unpriced, because "free" is a fact here, not a
    # gap — see the 1,000 requests/day free allowance the transport plane is built around.
    ("openrouter", ":free"): Price(0.0, 0.0, "2026-07-28"),
}


def price_for(provider: str, model: str) -> Optional[Price]:
    """The declared price for a model, or ``None`` when nothing declares one.

    ``:free`` is matched as a SUFFIX because that is how OpenRouter spells the free tier
    (``nvidia/nemotron-3-ultra-550b-a55b:free``); everything else matches by prefix.
    """
    p = (provider or "").strip().lower()
    m = (model or "").strip().lower()
    if (p, ":free") in PRICES and m.endswith(":free"):
        return PRICES[(p, ":free")]
    best: Optional[tuple[int, Price]] = None
    for (pp, prefix), price in PRICES.items():
        if pp == p and prefix != ":free" and m.startswith(prefix):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), price)
    return best[1] if best else None


@dataclass
class UsageRow:
    """One group's usage. Every "missing" is counted, never folded into a zero."""

    key: dict[str, str] = field(default_factory=dict)
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls_without_usage: int = 0      # backend reported no usage — tokens are UNKNOWN, not 0
    unpriced_calls: int = 0           # no declared price — cost is UNKNOWN, not 0
    cost_usd: float = 0.0             # the priced portion only
    total_ms: float = 0.0

    @property
    def cost_is_complete(self) -> bool:
        """Whether ``cost_usd`` accounts for every call in this group."""
        return self.unpriced_calls == 0 and self.calls_without_usage == 0

    def to_dict(self) -> dict:
        return {
            **self.key,
            "calls": self.calls, "failures": self.failures,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "calls_without_usage": self.calls_without_usage,
            "unpriced_calls": self.unpriced_calls,
            "cost_usd": round(self.cost_usd, 6),
            "cost_is_complete": self.cost_is_complete,
            "mean_ms": round(self.total_ms / self.calls, 1) if self.calls else 0.0,
            "failure_rate": round(self.failures / self.calls, 3) if self.calls else 0.0,
        }


@dataclass
class UsageReport:
    """The rollup plus what it could not attribute — both halves, always."""

    axes: tuple[str, ...]
    rows: list[UsageRow] = field(default_factory=list)
    total_calls: int = 0
    #: axis → how many calls carried no value for it. The honest half of the report.
    unattributed: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"axes": list(self.axes), "total_calls": self.total_calls,
                "rows": [r.to_dict() for r in self.rows],
                "unattributed": dict(self.unattributed),
                "coverage": {
                    axis: (round(1 - n / self.total_calls, 3) if self.total_calls else 0.0)
                    for axis, n in self.unattributed.items()},
                }


def rollup(
    events: Iterable[dict],
    *,
    axes: Sequence[str] = DEFAULT_AXES,
) -> UsageReport:
    """Group already-read session-log events. Pure — the read is the caller's half.

    Unknown axis names raise rather than being ignored: silently dropping an axis would
    return a report that answers a different question than the one asked, which is the
    failure mode a usage page can least afford.
    """
    bad = [a for a in axes if a not in AXES]
    if bad:
        raise ValueError(f"unknown usage axis/axes {bad} — known: {sorted(AXES)}")

    groups: dict[tuple, UsageRow] = {}
    unattributed = {a: 0 for a in axes}
    total = 0

    for e in events:
        total += 1
        key_values = []
        for axis in axes:
            v = str(AXES[axis](e) or "")
            if not v:
                unattributed[axis] += 1
                v = "(unattributed)"
            key_values.append(v)
        row = groups.setdefault(tuple(key_values),
                                UsageRow(key=dict(zip(axes, key_values))))
        row.calls += 1
        if e.get("ok") is False:
            row.failures += 1
        row.total_ms += float(e.get("duration_ms") or 0.0)

        if e.get("total_tokens") is None:
            # Unknown, not zero — several backends omit usage entirely.
            row.calls_without_usage += 1
            continue
        pt = int(e.get("prompt_tokens") or 0)
        ct = int(e.get("completion_tokens") or 0)
        row.prompt_tokens += pt
        row.completion_tokens += ct
        row.total_tokens += int(e.get("total_tokens") or 0)

        price = price_for(str(e.get("provider") or ""), str(e.get("model") or ""))
        if price is None:
            row.unpriced_calls += 1
        else:
            row.cost_usd += (pt / 1_000_000.0) * price.input_per_1m
            row.cost_usd += (ct / 1_000_000.0) * price.output_per_1m

    return UsageReport(
        axes=tuple(axes), total_calls=total, unattributed=unattributed,
        rows=sorted(groups.values(), key=lambda r: r.calls, reverse=True))


def usage_report(
    *,
    axes: Sequence[str] = DEFAULT_AXES,
    org_id: Optional[str] = None,
    scan: int = 5000,
) -> UsageReport:
    """Read the session log and roll it up — the store-backed convenience wrapper."""
    from aughor.kernel.ledger import Ledger

    rows = Ledger.default().session_events(kind=LLM_CALL, org_id=org_id, limit=scan)
    return rollup(rows, axes=axes)


#: Copy-pasteable cost SQL against our own session log, for an operator who would rather
#: query than call an endpoint. Kept beside the code that computes the same numbers so the
#: two cannot drift apart unnoticed — the aughor_ops connection reads this table directly,
#: and an agent writing its own SQL against it needs the column names to be real.
COST_SQL = """
-- Tokens and calls by model, newest 30 days. `total_tokens IS NULL` means the backend
-- reported no usage: count those separately rather than treating them as zero.
SELECT provider,
       model,
       COUNT(*)                                          AS calls,
       SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END)           AS failures,
       SUM(COALESCE(prompt_tokens, 0))                   AS prompt_tokens,
       SUM(COALESCE(completion_tokens, 0))               AS completion_tokens,
       SUM(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END) AS calls_without_usage,
       ROUND(AVG(duration_ms), 1)                        AS mean_ms
FROM   session_events
WHERE  kind = 'llm_call'
  AND  created_at >= datetime('now', '-30 days')
GROUP  BY provider, model
ORDER  BY calls DESC;
""".strip()
