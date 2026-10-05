"""Phase 6 of the 2027 study (§P, §W) — what a pack may ship before an install measured it, and
the rule every such number is held to.

A pack is data over one kernel: object types, links, processes and promises as claims to be
measured on connect (`ontology_map.py`), metric statements, plays with base rates, watches with
prior normal ranges, scenario and mission templates, golden questions. Nothing in a pack is code,
and a pack cannot add a store, a screen type or a code path. Two rules this module holds:

- **A prior carries the installs it was measured on, or says none.** A monitor's band or a play's
  base rate that states a number with neither ``measured_on`` nor ``unmeasured: true`` is refused by
  the static gate (`packs/validate.py`), because a range nobody measured anywhere would read as
  normal the day a connection is made. An unmeasured prior is shown as such — never as a range.
- **A template names what the kernel has.** A scenario template's method is one the ladder has
  (`record/scenario.METHODS`) and an identity names its formula; a mission template's cadence is
  one the report keeps (`record/mission.CADENCE_DAYS`) and its objective names a metric. A template
  is a declaration a person confirms; it never becomes a mission or a prediction on its own.
"""
from __future__ import annotations

from typing import Any

from aughor.packs.models import Pack

_PRIOR_RULE = "a prior carries the installs or datasets it was measured on (measured_on), or says none (unmeasured: true)"


def prior_problems(pack: Pack) -> list[str]:
    """Every way a pack's priors and templates fall short of the two rules — empty when none do."""
    from aughor.record.mission import CADENCE_DAYS
    from aughor.record.scenario import METHODS
    out: list[str] = []
    for m in pack.monitors:
        where = f"monitor {m.id or m.metric!r}"
        if not (m.metric or "").strip():
            out.append(f"{where}: names no metric")
        if (m.low is not None or m.high is not None) and not m.provenance_declared:
            out.append(f"{where}: states a band and {_PRIOR_RULE}")
        if m.low is not None and m.high is not None and m.low > m.high:
            out.append(f"{where}: low {m.low} is above high {m.high}")
        if m.unmeasured and m.measured_on:
            out.append(f"{where}: says unmeasured and names where it was measured — one or the other")
    for p in pack.playbooks:
        where = f"play {p.id or p.trigger_metric!r}"
        if p.base_rate is not None:
            if not (0.0 <= float(p.base_rate) <= 1.0):
                out.append(f"{where}: a base rate is a share, 0 to 1")
            if not (p.measured_on or p.unmeasured):
                out.append(f"{where}: states a base rate and {_PRIOR_RULE}")
            if p.measured_on and p.base_rate_n <= 0:
                out.append(f"{where}: a measured base rate carries the count it rests on (base_rate_n)")
    for s in pack.scenarios:
        where = f"scenario template {s.id!r}"
        if s.method not in METHODS:
            out.append(f"{where}: method {s.method!r} is not on the ladder ({', '.join(METHODS)})")
        if s.method == "identity" and not (s.formula or "").strip():
            out.append(f"{where}: an identity names its formula")
        if s.method == "intervention" and not (s.like or s.action_id):
            out.append(f"{where}: an intervention names the kind of decision (like, or action_id)")
        if s.for_kind not in ("decision", "mission", "inquiry"):
            out.append(f"{where}: for_kind is decision, mission or inquiry")
    for t in pack.missions:
        where = f"mission template {t.id!r}"
        if not str((t.objective or {}).get("metric") or "").strip():
            out.append(f"{where}: its objective names a metric")
        direction = str((t.objective or {}).get("direction") or "")
        if direction and direction not in ("up", "down", "hold"):
            out.append(f"{where}: an objective's direction is up, down or hold")
        if t.cadence not in CADENCE_DAYS:
            out.append(f"{where}: cadence {t.cadence!r} is not one the report keeps ({', '.join(CADENCE_DAYS)})")
        for c in t.constraints:
            if not str((c or {}).get("metric") or "").strip():
                out.append(f"{where}: a constraint names a metric")
            if str((c or {}).get("bound") or "at_least") not in ("at_least", "at_most"):
                out.append(f"{where}: a constraint's bound is at_least or at_most")
    return out


def monitor_priors(pack: Pack) -> list[dict[str, Any]]:
    """A pack's watches with their prior ranges, each saying where the band was measured — or that it
    was not, in which case no band is shown."""
    out = []
    for m in pack.monitors:
        row: dict[str, Any] = {"pack": pack.id, "id": m.id or m.metric, "metric": m.metric, "unit": m.unit,
                               "description": m.description, "note": m.note, "sources": list(m.sources)}
        if m.measured_on:
            row.update({"low": m.low, "high": m.high, "measured_on": list(m.measured_on),
                        "status": f"prior range measured on {', '.join(m.measured_on)}; proposed for confirmation, not armed"})
        else:
            row.update({"low": None, "high": None, "measured_on": [],
                        "status": "unmeasured prior: the pack names the watch and no band — a band is learned here or nowhere"})
        out.append(row)
    return out


def mission_templates(pack: Pack) -> list[dict[str, Any]]:
    """A pack's mission templates as bodies a person writes a mission from (POST /record/missions)."""
    out = []
    for t in pack.missions:
        obj = dict(t.objective or {})
        out.append({"pack": pack.id, "id": t.id, "name": t.name, "description": t.description, "cadence": t.cadence,
                    "body": {"name": t.name, "objective": {"metric": str(obj.get("metric") or ""), "direction": str(obj.get("direction") or ""),
                                                           "target": obj.get("target"), "unit": str(obj.get("unit") or ""), "text": str(obj.get("text") or "")},
                             "constraints": [{"metric": str(c.get("metric") or ""), "kind": str(c.get("kind") or "metric"),
                                              "bound": str(c.get("bound") or "at_least"), "limit": c.get("limit"),
                                              "unit": str(c.get("unit") or ""), "text": str(c.get("text") or "")} for c in t.constraints],
                             "watches": [dict(w) for w in t.watches], "cadence": t.cadence, "state": "proposed"},
                    "note": "a template; a person writes the mission, names its owner and activates it — a model never does"})
    return out


def scenario_templates(pack: Pack) -> list[dict[str, Any]]:
    return [{"pack": pack.id, **s.model_dump()} for s in pack.scenarios]


def base_rates(pack: Pack) -> list[dict[str, Any]]:
    """The plays that ship a base rate, each with where it was measured — or saying none."""
    out = []
    for p in pack.playbooks:
        if p.base_rate is None and not p.unmeasured:
            continue
        out.append({"pack": pack.id, "play": p.id, "trigger_metric": p.trigger_metric, "base_rate": p.base_rate,
                    "n": p.base_rate_n, "measured_on": list(p.measured_on),
                    "status": (f"measured on {', '.join(p.measured_on)} over {p.base_rate_n} cases" if p.measured_on
                               else "unmeasured: the pack ships the play and no rate")})
    return out
