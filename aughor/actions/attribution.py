"""Arc TC, TC-2 — every change says what made it: the run an edit or a declared action was made through, its trace, and
what that run cost.

Before this the edit layer recorded who, never which run: an edit an automation made read "by automation:<id>" and could
not be joined to the run that made it, nor to what that run spent. The run is ambient — `telemetry.bind_run`, bound where
runs start (the ask door, `run_automation`, the kernel's job runner) beside the trace `bind_trace` already pins — so
nothing threads a run id through a caller. With flag `actions.run_attribution` on, three existing records stamp it:

- an edit's history row (`overlay_edit_history`: ``run_id``, ``run_kind``, ``trace_id``);
- every action-audit row (`govern.actions.audit`, the ``action.approval`` events — its ``trace_id`` column was already
  stamped from the ambient trace; the run is new);
- a declared action's ledger entry (`actions.authority.book_action`).

No new store and no new audit sink: each is a column or a payload key on a record that exists. A change made outside any
run is recorded as such (``run_kind`` ``none``) and read "by a person, outside any run"; a row from before the stamp
(``run_kind`` empty) reads "which run made it was not recorded" — never "outside any run", which it may not have been.

:func:`object_timeline` reads one object's edits and actions, oldest first, each with who or what made it, through which
run, and that run's model cost from the session log when the run was metered — "not metered" said, never a zero.
"""
from __future__ import annotations

from typing import Optional

FLAG = "actions.run_attribution"
#: The stored ``run_kind`` of a change recorded with no run in force. Empty means the run was not recorded at all.
OUTSIDE = "none"
#: How a run's kind reads in a sentence.
KIND_WORDS = {"chat": "a question asked", "automation": "an automation", "monitor": "a monitor",
              "agent": "an agent's work"}
#: An actor whose principal head names a machine, not a person.
_MACHINE_HEADS = frozenset({"agent", "automation", "monitor", "service", "mcp", "system"})
#: How many of an object's edit-history rows and how many of a connection's action entries a timeline reads.
EDIT_CAP = 1000
ACTION_CAP = 2000
#: The most session-log events read to cost one run (a deep run measured 1,140).
COST_SCAN = 5000


def enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def ambient() -> dict:
    """The run and trace in force now: ``{run_id, run_kind, trace_id}``, ``run_kind`` ``none`` outside any run."""
    from aughor import telemetry
    run_id, kind = telemetry.current_run()
    return {"run_id": run_id or "", "run_kind": (kind or "") if run_id else OUTSIDE,
            "trace_id": telemetry.current_trace_id() or ""}


def stamp() -> dict:
    """What a record adds with the flag on — :func:`ambient` — and ``{}`` with it off, so a record written with it off is
    the record written before. Never raises: an unreadable run is left unrecorded (and reads so), never invented."""
    try:
        return ambient() if enabled() else {}
    except Exception as exc:  # noqa: BLE001 — attribution must never break the change it attributes
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the run in force could not be read; the change is recorded without it",
                 counter="actions.run_attribution")
        return {}


def _who(actor: str) -> str:
    a = (actor or "").strip()
    if not a:
        return "someone the record does not name"
    head, sep, _ = a.partition(":")
    if a == "system" or (sep and head in _MACHINE_HEADS):
        return a
    return "a person"


def describe(row: dict) -> dict:
    """How one stamped record reads: ``run`` (``{id, kind, trace_id}`` or None), ``run_recorded``, ``run_said`` (the run
    as a phrase) and ``said`` (who or what made it, through which run)."""
    kind = str(row.get("run_kind") or "")
    run_id = str(row.get("run_id") or "")
    run = ({"id": run_id, "kind": kind, "trace_id": str(row.get("trace_id") or "")}
           if kind and kind != OUTSIDE and run_id else None)
    if run is not None:
        phrase = f"through {KIND_WORDS.get(kind, kind)} (run {run_id[:8]})"
    elif kind:
        phrase = "outside any run"
    else:
        phrase = "which run made it was not recorded"
    return {"run": run, "run_recorded": bool(kind), "run_said": phrase,
            "said": f"by {_who(str(row.get('actor') or ''))}, {phrase}"}


# ── a run's cost ─────────────────────────────────────────────────────────────────────

def _not_metered(why: str) -> dict:
    return {"metered": False, "model_calls": None, "tokens": None, "usd": None, "said": f"not metered: {why}"}


def run_cost(run: dict, *, org_id: Optional[str] = None) -> dict:
    """What a run's model calls cost, folded from the session log with the arithmetic the trace index uses
    (`obs.usage.rollup` → `cost_of_call`). A run the log holds nothing for is "not metered", never zero; an unpriced call
    is counted beside the dollars, never added as zero; a nested run whose calls cannot be told apart from the run that
    started it is costed as the trace it shared, and says so."""
    trace, run_id = str(run.get("trace_id") or ""), str(run.get("id") or "")
    if not trace:
        return _not_metered("no trace was kept for this run")
    from aughor.kernel.ledger import Ledger
    from aughor.obs import session_log
    events = Ledger.default().session_events(trace_id=trace, org_id=org_id, limit=COST_SCAN, ascending=True)
    if not events:
        days = session_log.keep_days()
        return _not_metered("the session log holds nothing for this run"
                            + (f" (it keeps {days} days)" if days else ""))
    of = "run"
    if run_id and run_id != trace:
        own = [e for e in events if e.get("job_id") == run_id]
        if own:
            events = own
        else:
            of = "trace"
    from aughor.obs.usage import rollup
    calls = [e for e in events if e.get("kind") == session_log.LLM_CALL]
    rows = rollup(calls, axes=()).rows if calls else []
    row = rows[0] if rows else None
    n = row.calls if row else 0
    priced = (n - row.unpriced_calls - row.calls_without_usage) if row else 0
    usd = round(row.cost_usd, 6) if row and priced else None
    out = {"metered": True, "of": of, "model_calls": n, "tokens": row.total_tokens if row else 0, "usd": usd,
           "unpriced_calls": row.unpriced_calls if row else 0,
           "calls_without_usage": row.calls_without_usage if row else 0}
    shared = " — the trace it shared with the run that started it" if of == "trace" else ""
    if not n:
        out["said"] = f"no model call in its {len(events)} recorded events{shared}"
    elif usd is None:
        out["said"] = f"{n} model call{'s' if n != 1 else ''}, none priced{shared}"
    elif priced < n:
        out["said"] = (f"at least ${usd:.4f} over {n} model calls — {n - priced} without a price or a token count"
                       f"{shared}")
    else:
        out["said"] = f"${usd:.4f} over {n} model call{'s' if n != 1 else ''}{shared}"
    return out


# ── one object's timeline ────────────────────────────────────────────────────────────

def _word(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _moment(at: str):
    """When a change was recorded, comparable across the two records: an edit written before the stamp is to the second,
    a stamped one and an action entry to the microsecond. An unreadable time sorts first rather than raising."""
    from datetime import datetime, timezone
    try:
        moment = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _names_object(payload: dict, object_type: str, row_key: str) -> bool:
    """Whether an action entry acted on the object: an object parameter, or an edit it made, is ``<entity>:<key>``."""
    want = _word(object_type)
    refs = list((payload.get("params") or {}).values())
    refs += [e.get("object", "") for e in ((payload.get("outcome") or {}).get("edits") or []) if isinstance(e, dict)]
    for ref in refs:
        typ, sep, key = str(ref).partition(":")
        if sep and _word(typ) == want and key.strip() == str(row_key):
            return True
    return False


def object_timeline(connection_id: str, object_type: str, row_key: str, *, org_id: Optional[str] = None) -> dict:
    """Every edit and declared action on one object, oldest first: who or what made it, through which run, and what
    that run cost. Read from the edit layer's history and the action ledger — the records that exist; no walker."""
    from aughor.actions.authority import ACTION_KIND
    from aughor.actions.overlay import edit_history
    from aughor.kernel.ledger import Ledger
    edits = edit_history(connection_id, object_type=object_type, row_key=row_key, org_id=org_id, limit=EDIT_CAP)
    entries: list[dict] = []
    for r in edits:
        entries.append({"what": "edit", "at": r["at"], "event": r["event"], "object_type": r["object_type"],
                        "row_key": r["row_key"], "table": r["table"], "column": r["column"], "body": r["body"],
                        "previous": r["previous"], "note": r["note"], "version": r["version"], "actor": r["actor"],
                        "origin": r["origin"], **describe(r)})
    arts = Ledger.default().artifacts_of_kind(ACTION_KIND, conn_id=connection_id or None, org_id=org_id,
                                              limit=ACTION_CAP)
    for art in arts:
        p = art.get("payload") if isinstance(art.get("payload"), dict) else {}
        if p.get("kind") == "write" or not _names_object(p, object_type, row_key):
            continue
        entries.append({"what": "action", "at": str(p.get("at") or art.get("created_at") or ""),
                        "action_id": p.get("action_id", ""), "status": p.get("status", ""),
                        "object_type": object_type, "row_key": str(row_key), "table": "", "column": "",
                        "actor": p.get("actor", ""),
                        "verification": (p.get("verification") or {}).get("status", ""),
                        "entry": str(art.get("id") or ""), **describe(p)})
    costs: dict = {}
    for e in entries:
        run = e.get("run")
        if run is not None:
            key = (run["id"], run["trace_id"])
            if key not in costs:
                costs[key] = run_cost(run, org_id=org_id)
            run["cost"] = costs[key]
    entries.sort(key=lambda e: (_moment(e["at"]), int(e.get("version") or 0)))
    out: dict = {"connection_id": connection_id, "object_type": object_type, "row_key": str(row_key),
                 "timeline": entries,
                 "read": {"edits": len(edits), "actions": sum(1 for e in entries if e["what"] == "action"),
                          "action_entries_scanned": len(arts)}}
    capped = []
    if len(edits) >= EDIT_CAP:
        capped.append(f"only the newest {EDIT_CAP} edits on this object were read")
    if len(arts) >= ACTION_CAP:
        capped.append(f"only the newest {ACTION_CAP} actions on this connection were searched for it")
    if capped:
        out["note"] = "; ".join(capped)
    return out
