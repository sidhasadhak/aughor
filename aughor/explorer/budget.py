"""Exploration spend is a budget, set where the organisation wants it (exploration principles §7, 2026-10-08).

Decision 3 (the user): both — a budget per ORGANISATION per month and per CONNECTION per month; where
both are set, the tighter holds. It governs what the platform spends on its own initiative — the
continuous loop's runs and the questions a dataset's layer starts — and, since 2026-10-08 (the user:
"any cap on your own Start"), a person's own run too: it is capped at what is left of the month, and when
nothing is left it is refused with the reason unless the person says to run it anyway — a choice recorded
under their name (`person_run`). When a budget is spent the platform says so, on the dataset's maturity and
in the Explorer's status, and holds the run rather than stopping silently.

Spend is measured, never estimated: the model tokens each exploration job recorded on its kernel job
row (`jobs.metrics.total_tokens`, flushed by the heartbeat), this calendar month (UTC). Tokens, because
that is the unit the run's own budget is in and the one every model reports; a price is not known for
every model, and an unpriced one would read as free.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

#: The job kinds that spend for exploration: the explorer's runs, the birth rite that builds the
#: intelligence a first run reads, and the model-written explanation of a watched figure's move.
SPENDING_KINDS = ["exploration", "profile", "explain_move"]


def month_start(now: Optional[datetime] = None) -> str:
    """The first instant of this month, in the ledger's own ISO form (`kernel.ledger._now`)."""
    now = now or datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()


def spent(conn_id: Optional[str] = None, *, now: Optional[datetime] = None, jobs: Optional[list] = None) -> int:
    """Model tokens exploration spent this month — on one connection, or on all of them."""
    if jobs is None:
        from aughor.kernel.ledger import Ledger
        jobs = Ledger.default().jobs_where(kinds=SPENDING_KINDS, conn_id=conn_id,
                                           since=month_start(now), limit=100_000)
    total = 0
    for j in jobs:
        m = j.get("metrics") if isinstance(j.get("metrics"), dict) else {}
        n = m.get("total_tokens")
        if isinstance(n, (int, float)) and not isinstance(n, bool):
            total += int(n)          # a row whose metrics never flushed counts nothing, as it spent nothing measured
    return total


def _limit(v) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def limits(conn_id: str) -> tuple[Optional[int], Optional[int]]:
    """``(organisation's monthly tokens, this connection's)`` — None where none is set."""
    org = conn = None
    try:
        from aughor.orgsettings import load_org_settings
        org = _limit(getattr(load_org_settings(), "exploration_monthly_tokens", None))
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "org settings unreadable; no organisation budget applied", counter="explorer.budget.org")
    try:
        from aughor.db.registry import get_connection_settings
        conn = _limit(get_connection_settings(conn_id).get("exploration_monthly_tokens"))
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "connection settings unreadable; no connection budget applied", counter="explorer.budget.conn")
    return org, conn


def standing(conn_id: str, *, now: Optional[datetime] = None) -> dict:
    """The connection's exploration budget this month: each limit, what it has spent, what is left
    under the tighter, which one holds, and the sentence a person reads."""
    org_limit, conn_limit = limits(conn_id)
    org_spent = spent(None, now=now) if org_limit else None
    conn_spent = spent(conn_id, now=now)
    left: dict[str, int] = {}
    if org_limit:
        left["organisation"] = org_limit - (org_spent or 0)
    if conn_limit:
        left["connection"] = conn_limit - conn_spent
    holder = min(left, key=lambda k: left[k]) if left else None
    remaining = left[holder] if holder else None
    if holder is None:
        sentence = f"no monthly exploration budget is set · {conn_spent:,} tokens spent this month"
    elif remaining <= 0:
        lim = org_limit if holder == "organisation" else conn_limit
        sentence = (f"the {holder}'s monthly exploration budget of {lim:,} tokens is spent — the platform "
                    "explores nothing more on its own this month, and a person's Start asks first")
    else:
        lim = org_limit if holder == "organisation" else conn_limit
        sentence = f"{remaining:,} of the {holder}'s {lim:,} monthly tokens left"
    return {"organisation": {"limit": org_limit, "spent": org_spent},
            "connection": {"limit": conn_limit, "spent": conn_spent},
            "remaining": remaining, "held_by": holder, "spent_out": remaining is not None and remaining <= 0,
            "sentence": sentence, "month_start": month_start(now)}


class BudgetSpent(Exception):
    """A person's run refused because the month's exploration budget is spent — said with the standing, so
    the screen can ask whether to run it anyway."""

    def __init__(self, standing: dict):
        super().__init__(standing.get("sentence") or "the monthly exploration budget is spent")
        self.standing = standing

    def detail(self) -> dict:
        return {"reason": "budget_spent", "message": str(self), "budget": self.standing,
                "hint": "run it anyway to spend past the budget — the choice is recorded under your name"}


def person_run(conn_id: str, *, run_anyway: bool = False, by: str = "", what: str = "exploration") -> Optional[int]:
    """The token cap of a run a PERSON starts: what is left of the month under the tighter budget, or None
    when no budget is set. When nothing is left, raises ``BudgetSpent`` — unless ``run_anyway``, when the
    run goes at its agent's own budget and the choice is recorded (`exploration.budget_override`)."""
    st = standing(conn_id)
    if st["remaining"] is None:
        return None
    if not st["spent_out"]:
        return max(1, int(st["remaining"]))
    if not run_anyway:
        raise BudgetSpent(st)
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("exploration.budget_override",
                              {"connection_id": conn_id, "by": by, "what": what, "budget": st["sentence"]},
                              conn_id=conn_id)
    except Exception as exc:  # noqa: BLE001 — the person's choice stands; the record is what failed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a budget override could not be recorded", counter="explorer.budget_override",
                 conn_id=conn_id)
    return None
