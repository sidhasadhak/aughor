"""HB-6 — the hub-wide map: every automation on one screen.

Trigger, destinations, grant, owner, last run, cost, probation state — assembled from
stores that all exist (the automations library, the standing grants, the departures
ledger, the session log, HB-1's router). Agent Ops' Map answers this per agent; this
module answers it hub-wide. A READ, NEVER A BUILD: every source below is a store read
or a fold over one — no probe fires, no graph builds, no model is called.

Cost is a FLOOR, deliberately. There is no per-automation usage axis: a tick's own job
meters ~0 because the deep path mints an inner investigation job where the tokens land
(aughor/runners/investigation.py records this precisely). What IS attributable is the
session log's per-trace fold over the traces this automation caused — each run's
`trace_id` plus each step's `investigation_id` (an investigation's trace is its id,
verbatim). `unpriced_calls`/`calls_without_usage` ride along so a $0.00 never reads as
free when it means "nobody published a rate" — the fleet screen's discipline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

#: How far back the cost/activity fold looks, and how much session log it may scan.
WINDOW_DAYS = 7
SESSION_SCAN = 4000


def _window_start(now: Optional[datetime] = None) -> str:
    t = (now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(a) -> str:
    """One word for the switch column: live | muted | expired | disabled."""
    from aughor.automations.models import now_iso_z
    now = now_iso_z()
    if not a.enabled:
        return "disabled"
    if a.expires_at and a.expires_at <= now:
        return "expired"
    if a.paused_until and a.paused_until > now:
        return "muted"
    return "live"


def _destinations(a) -> list[dict]:
    """Where each effect lands. Static targets read straight off the config; a routed
    notify (`route_about`) is resolved through HB-1's `route()` — the one resolver the
    engine itself dispatches with, so the map cannot drift from the send."""
    from aughor.kernel.errors import tolerate
    out: list[dict] = []
    for e in a.effects:
        row: dict = {"kind": e.kind, "target": e.target()}
        about = str(e.config.get("route_about") or "") if e.kind == "notify" else ""
        if about:
            row["routed_about"] = about
            row["target"] = about
            try:
                from aughor.automations.engine import route_destinations
                row["resolved"] = [d.to_dict() for d in route_destinations(about, a)]
            except Exception as exc:
                tolerate(exc, "hub map could not resolve a routed destination",
                         counter="hub.map_route")
                row["resolved"] = []
        elif e.kind == "notify" and e.config.get("trigger_id"):
            try:
                from aughor.notifications.store import get_trigger
                trg = get_trigger(str(e.config["trigger_id"]))
                if trg is not None:
                    row["label"] = trg.name
                    row["channel"] = trg.channel
                    row["type"] = trg.type
            except Exception as exc:
                tolerate(exc, "hub map could not read a trigger row",
                         counter="hub.map_trigger")
        elif e.kind == "slack_post":
            row["channel"] = str(e.config.get("channel") or "")
        out.append(row)
    return out


def _monitor_destinations(monitor) -> list[dict]:
    """Where a monitor's alerts go: in-app, or the Notifications trigger its channel names."""
    channel = (monitor.notification_channel or "in_app").strip()
    if channel == "in_app":
        return [{"kind": "in_app", "target": ""}]
    row: dict = {"kind": "notify", "target": channel}
    try:
        from aughor.notifications.store import get_trigger
        trg = get_trigger(channel)
        if trg is not None:
            row.update({"label": trg.name, "channel": trg.channel, "type": trg.type})
        else:
            row["missing"] = True        # names no trigger, so nothing is sent
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "hub map could not read a trigger row", counter="hub.map_trigger")
    return [row]


def _monitors(conn_id: str) -> list[tuple]:
    """Every monitor as ``(virtual automation, monitor)``. Monitors run through the engine as virtual automations and
    are never rows of the automations store, so the map listed none of them (ROADMAP §3.26). Disabled ones are listed
    too, and read *disabled*."""
    try:
        from aughor.automations.adopt import monitor_as_automation
        from aughor.monitors.store import list_monitors
        return [(monitor_as_automation(m), m) for m in list_monitors(conn_id=conn_id or None)]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "hub map could not read the monitors", counter="hub.map_monitors")
        return []


#: Arc TC, TC-5 — the failure-rate window, in days counting today, and the most a caller may ask.
FAILURE_WINDOW_DAYS = 7
FAILURE_WINDOW_MAX = 90


def _readable_ids(autos: list) -> tuple[set[str], str]:
    """The nodes whose runs this reader may see, and why the rest may not.

    The same two rules the automations and monitors lists apply: the connection is in the
    reader's organisation (DATA-06; every connection when identity is off), and the node is in
    the active workspace — owned by it, or on one of its connections (`scoped_to_workspace`). A
    check that cannot run fails closed and says so, rather than reading every node as allowed."""
    try:
        from aughor.metastore import scoped_to_workspace
        from aughor.security.authz import org_visible_conn_ids
        visible = org_visible_conn_ids()
        in_org = [a for a in autos if visible is None or not a.conn_id or a.conn_id in visible]
        return {a.id for a in scoped_to_workspace(in_org, key="conn_id")}, ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "hub map could not check who may see each node's runs; none is shown",
                 counter="hub.map_failure_permission")
        return set(), "who may see these runs could not be checked"


def _failure_label(failed: int, ran: int) -> str:
    pct = 100.0 * failed / ran
    if 0 < pct < 1:
        return "under 1% failed"
    return f"{round(pct)}% failed"


def failure_rates(autos: list, conn_id: str = "",
                  window_days: int = FAILURE_WINDOW_DAYS) -> tuple[dict[str, dict], dict]:
    """Arc TC, TC-5 — each node's failure rate over the window, from its run records.

    Three answers kept apart, because each means something different to the reader:
    *measured* (n runs, f failed); *no runs* — nothing ran in the window, which is not 0%; and
    *not permitted* — the reader may not see this node's runs, so no count is given, and the node
    stays on the map saying so rather than leaving it.
    """
    from aughor.automations.store import failure_counts_since

    days = max(1, min(int(window_days or FAILURE_WINDOW_DAYS), FAILURE_WINDOW_MAX))
    # The UTC day, as every run's `started_at` is written — a local date shifts the floor a day.
    since = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    readable, why_not = _readable_ids(autos)
    counts = failure_counts_since(since, conn_id=conn_id or None)
    out: dict[str, dict] = {}
    for a in autos:
        if a.id not in readable:
            out[a.id] = {"state": "not_permitted", "window_days": days, "label": "not permitted",
                         **({"why": why_not} if why_not else {})}
            continue
        c = counts.get(a.id) or {"ran": 0, "failed": 0, "gated": 0}
        if not c["ran"]:
            out[a.id] = {"state": "no_runs", "window_days": days, "ran": 0, "failed": 0,
                         "rate": None, "gated": c["gated"], "label": "no runs"}
            continue
        out[a.id] = {"state": "measured", "window_days": days, "ran": c["ran"],
                     "failed": c["failed"], "rate": round(c["failed"] / c["ran"], 4),
                     "gated": c["gated"], "label": _failure_label(c["failed"], c["ran"])}
    return out, {"days": days, "since": since}


def hub_map(conn_id: str = "", window_days: int = FAILURE_WINDOW_DAYS) -> dict:
    """The map. One row per automation and per monitor, every column the roadmap names, and each row's failure rate
    over ``window_days`` (Arc TC, TC-5)."""
    from aughor.automations.models import now_iso_z
    from aughor.automations.store import get_runs, last_run, list_automations
    from aughor.govern.departure import GRADUATION_MIN_MARKED, GRADUATION_PRECISION
    from aughor.govern.departure_store import precision_for
    from aughor.org.context import current_org_id

    autos = [(a, None) for a in list_automations(conn_id=conn_id or None)] + _monitors(conn_id)
    since = _window_start()

    # One pass over the standing grants: which chains earned unattended sends.
    from aughor.actions.grants import list_grants
    grants_by_auto: dict[str, list[dict]] = {}
    for g in list_grants(conn_id or None):
        if g.owner_kind != "automation":
            continue
        grants_by_auto.setdefault(g.owner_id, []).append({
            "id": g.id, "action_id": g.action_id, "target_arg": g.target_arg,
            "target_value": g.target_value, "use_count": g.use_count,
            "last_used_at": g.last_used_at,
        })

    # One pass over the runs that DID something (fired/error/paused — the rows that can
    # carry effects and spend; `not_fired` probes are SQL, and at 1,440/day per schedule
    # they would bury everything else, which is the store's own documented trap).
    runs = [r for r in get_runs(conn_id=conn_id or None, limit=500,
                                outcomes=["fired", "error", "paused"])
            if r.started_at >= since]
    traces_by_auto: dict[str, set[str]] = {}
    invs_by_auto: dict[str, set[str]] = {}
    runs_by_auto: dict[str, int] = {}
    for r in runs:
        runs_by_auto[r.automation_id] = runs_by_auto.get(r.automation_id, 0) + 1
        t = traces_by_auto.setdefault(r.automation_id, set())
        if r.trace_id:
            t.add(r.trace_id)
        for eo in r.effects:
            if eo.investigation_id:
                t.add(eo.investigation_id)
                invs_by_auto.setdefault(r.automation_id, set()).add(eo.investigation_id)

    # One fold over the session log for every trace those runs caused.
    from aughor.obs.session_log import recent_sessions
    by_trace = {s["trace_id"]: s
                for s in recent_sessions(org_id=current_org_id(), limit=SESSION_SCAN,
                                         scan=SESSION_SCAN, since=since)}

    rows: list[dict] = []
    for a, monitor in autos:
        cost = {"window_days": WINDOW_DAYS, "runs": runs_by_auto.get(a.id, 0),
                "deep_runs": len(invs_by_auto.get(a.id, ())),
                "total_tokens": 0, "cost_usd": 0.0,
                "unpriced_calls": 0, "calls_without_usage": 0, "floor": True}
        for t in traces_by_auto.get(a.id, ()):
            s = by_trace.get(t)
            if not s:
                continue
            cost["total_tokens"] += int(s.get("total_tokens") or 0)
            cost["cost_usd"] += float(s.get("cost_usd") or 0.0)
            cost["unpriced_calls"] += int(s.get("unpriced_calls") or 0)
            cost["calls_without_usage"] += int(s.get("calls_without_usage") or 0)
        cost["cost_usd"] = round(cost["cost_usd"], 6)

        prec = precision_for(a.id)
        last = {"at": a.last_run_at, "status": a.last_status}
        if monitor is not None:
            # A virtual row carries no last run of its own; the engine records each tick under its id.
            r = last_run(a.id)
            last = {"at": r.started_at, "status": r.outcome} if r else {"at": None, "status": None}
        rows.append({
            "id": a.id, "kind": "monitor" if monitor is not None else "automation",
            "conn_id": a.conn_id, "name": a.name,
            "description": a.description, "enabled": a.enabled, "state": _state(a),
            "trigger": [c.describe() for c in a.conditions],
            "destinations": _monitor_destinations(monitor) if monitor is not None else _destinations(a),
            "grants": grants_by_auto.get(a.id, []),
            "owner": {"declared_by": a.declared_by, "agent_id": a.agent_id},
            "last_run": last,
            "cost": cost,
            "probation": {"on": a.probation, "marked": prec["marked"],
                          "counts": prec["counts"], "unlanded": prec["unlanded"],
                          "precision": prec["precision"],
                          "graduates_at": {"min_marked": GRADUATION_MIN_MARKED,
                                           "precision": GRADUATION_PRECISION}},
            "exposed_as_tool": a.exposed_as_tool,
        })

    out = {
        "rows": rows, "window_days": WINDOW_DAYS, "generated_at": now_iso_z(),
        "totals": {
            "automations": sum(1 for r in rows if r["kind"] == "automation"),
            "monitors": sum(1 for r in rows if r["kind"] == "monitor"),
            "live": sum(1 for r in rows if r["state"] == "live"),
            "probation": sum(1 for r in rows if r["probation"]["on"]),
        },
    }
    rates, window = failure_rates([a for a, _ in autos], conn_id=conn_id, window_days=window_days)
    for r in rows:
        r["failure_rate"] = rates[r["id"]]
    out["failure_window"] = window
    return out
