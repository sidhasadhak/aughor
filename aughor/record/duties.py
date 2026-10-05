"""The week by duty (the 2027 study §V, screen 8) — a fold, never a store.

Operations shows the work, and the row is a duty, not an agent's name: what each of the seven
duties (`kernel/contract.DUTIES`) booked since a moment, how much of it stands on something, how
its runs ended by type, and what a warranted entry cost. Every count is a ledger entry read back
by the duty that books its kind — a claim by its kind, an execution as Operate's, a departure as
Deliver's, a run's typed verdict as Inquire's. Nothing here is a model's opinion and nothing is
kept: ask twice and the ledger is read twice.

What is not attributed is said. Only a run carries a metered cost on its Trust Receipt, and a
run is Inquire's, so only Inquire has a cost per warranted entry; the other duties say why not.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.kernel.contract import DUTIES, duty_for

#: A verdict that is not a failure. Everything else a run can end in is one, by type.
ANSWERED = "answered"

#: How a departure that did not leave is typed on this page: by the hold the gate recorded.
_HELD_PREFIX = "held"


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def week_start() -> str:
    """The same Monday the attention budget counts from — one week, said once."""
    from aughor.govern.attention import week_start as _week_start
    return _week_start()


def _blank(duty: dict) -> dict[str, Any]:
    return {"duty": duty["duty"], "today": duty["today"], "books": list(duty["books"]),
            "runs": None, "entries": 0, "warranted": 0, "failures": {}, "failed": 0,
            "cost": {"tokens": None, "llm_calls": None, "per_warranted": None,
                     "note": "not metered for this duty: only a run carries a cost on its receipt"}}


def _fail(row: dict, kind: str, n: int = 1) -> None:
    row["failures"][kind] = row["failures"].get(kind, 0) + n
    row["failed"] += n


def week_by_duty(*, since: str = "", conn_id: Optional[str] = None) -> dict:
    """One row per duty since ``since`` (default: this week's Monday), optionally for one connection."""
    from aughor.actions.authority import ACTION_KIND
    from aughor.govern import departure_store
    from aughor.record import claims as C
    from aughor.record.inquiry import RUN_VERDICT_KIND

    since = since or week_start()
    rows = {d["duty"]: _blank(d) for d in DUTIES}
    led = _ledger()

    # Claims, by the duty that books their kind. Warranted: every tier above `said` — it stands on
    # a run, a person's approval or declaration, or a computation, not only on having been said.
    for c in C.list_claims(conn_id=conn_id, limit=5000):
        if (c.recorded_at or "") < since:
            continue
        row = rows.get(duty_for(c.kind))
        if row is None:
            continue
        row["entries"] += 1
        row["warranted"] += c.tier != "said"

    # Runs and how they ended — Inquire's. A run with a receipt is metered; one without is counted
    # as not metered rather than as zero.
    inquire = rows["Inquire"]
    inquire["runs"] = 0
    tokens = llm_calls = metered = 0
    for art in led.artifacts_of_kind(RUN_VERDICT_KIND, conn_id=conn_id, limit=5000):
        if str(art.get("created_at") or "") < since:
            continue
        payload = dict(art.get("payload") or {})
        inquire["runs"] += 1
        verdict = str(payload.get("verdict") or "tool_failed")
        if verdict != ANSWERED:
            _fail(inquire, verdict)
        conn = str(art.get("conn_id") or "")
        receipt = None
        for prefix in ("ada", "chat"):
            receipt = led.receipt(f"{prefix}:{conn}:{payload.get('run')}") if conn else None
            if receipt:
                break
        cost = (receipt or {}).get("cost") or {}
        if cost:
            metered += 1
            tokens += int(cost.get("total_tokens") or 0)
            llm_calls += int(cost.get("llm_calls") or 0)
    if inquire["runs"]:
        unmetered = inquire["runs"] - metered
        inquire["cost"] = {
            "tokens": tokens if metered else None, "llm_calls": llm_calls if metered else None,
            "per_warranted": (round(tokens / inquire["warranted"]) if metered and inquire["warranted"] else None),
            "note": ("in tokens, from each run's receipt" if metered and not unmetered
                     else f"in tokens, from {metered} of {inquire['runs']} runs' receipts; the rest carry none" if metered
                     else "no run this period carries a receipt, so none is metered")}
    else:
        inquire["cost"]["note"] = "no run this period"

    # Executions — Operate's. Warranted: the declared verification read passed.
    operate = rows["Operate"]
    for art in led.artifacts_of_kind(ACTION_KIND, conn_id=conn_id, limit=5000):
        if str(art.get("created_at") or "") < since:
            continue
        status = str(((art.get("payload") or {}).get("verification") or {}).get("status") or "not_declared")
        operate["entries"] += 1
        if status == "passed":
            operate["warranted"] += 1
        elif status == "failed":
            _fail(operate, "verification_failed")
        elif status == "unavailable":
            _fail(operate, "verification_unavailable")

    # Departures — Deliver's. Warranted: it passed the gate and left; a hold is typed by its state.
    # The departure ledger is the organisation's, so a connection's page says it is not narrowed.
    deliver = rows["Deliver"]
    by_state = departure_store.summary_counts(since).get("by_state") or {}
    for state, n in by_state.items():
        deliver["entries"] += int(n)
        if state == "departed":
            deliver["warranted"] += int(n)
        elif str(state).startswith(_HELD_PREFIX):
            _fail(deliver, str(state), int(n))
    if conn_id:
        deliver["scope_note"] = "every connection: a departure is counted for the organisation"

    failures: dict[str, int] = {}
    for row in rows.values():
        for kind, n in row["failures"].items():
            failures[kind] = failures.get(kind, 0) + n
    return {"since": since, "connection_id": conn_id or "", "duties": [rows[d["duty"]] for d in DUTIES],
            "failures_by_type": failures,
            "note": ("every count is a ledger entry read back by the duty that books its kind; warranted means a tier "
                     "above `said` for a claim, a passed verification for an execution, a send that left for a "
                     "departure; a duty with 0 booked nothing in the period")}
