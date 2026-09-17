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


def hub_map(conn_id: str = "") -> dict:
    """The map. One row per automation, every column the roadmap names."""
    from aughor.automations.models import now_iso_z
    from aughor.automations.store import get_runs, list_automations
    from aughor.govern.departure import GRADUATION_MIN_MARKED, GRADUATION_PRECISION
    from aughor.govern.departure_store import precision_for
    from aughor.org.context import current_org_id

    autos = list_automations(conn_id=conn_id or None)
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
    for a in autos:
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
        rows.append({
            "id": a.id, "conn_id": a.conn_id, "name": a.name,
            "description": a.description, "enabled": a.enabled, "state": _state(a),
            "trigger": [c.describe() for c in a.conditions],
            "destinations": _destinations(a),
            "grants": grants_by_auto.get(a.id, []),
            "owner": {"declared_by": a.declared_by, "agent_id": a.agent_id},
            "last_run": {"at": a.last_run_at, "status": a.last_status},
            "cost": cost,
            "probation": {"on": a.probation, "marked": prec["marked"],
                          "counts": prec["counts"], "unlanded": prec["unlanded"],
                          "precision": prec["precision"],
                          "graduates_at": {"min_marked": GRADUATION_MIN_MARKED,
                                           "precision": GRADUATION_PRECISION}},
            "exposed_as_tool": a.exposed_as_tool,
        })

    return {
        "rows": rows, "window_days": WINDOW_DAYS, "generated_at": now_iso_z(),
        "totals": {
            "automations": len(rows),
            "live": sum(1 for r in rows if r["state"] == "live"),
            "probation": sum(1 for r in rows if r["probation"]["on"]),
        },
    }
