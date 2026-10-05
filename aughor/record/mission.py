"""The Mission — a standing objective a person gives the platform (the 2027 study §J and §G;
phase 5, P5-1), and the report it is judged by (P5-2).

A mission says what to achieve and what not to damage: an objective (a metric, a direction, a
target, by when), constraints (metrics or promises that must not be damaged, each with its limit),
a scope, an OWNER who is a person, a budget (interruptions a week, spend a month, an authority
ceiling per action kind), what it watches, and a review cadence. It never stops until a person
retires it, and it is judged by whether the objective moved against its own baseline and at what
cost — never by activity.

Three laws, at the door:

1. **People write missions; a model never does** — the rule the organisation's ontology follows.
   A mission whose author is an agent or the system is refused, not stored as "proposed".
2. **A mission without an owner does not run.** It may be written as a proposal with no owner; it
   cannot be made active until a person owns it, and the loop reads only active missions.
3. **Charged for every interruption.** A departure that bears on a mission carries the mission on
   its ledger row (``checks["mission"]``) and counts against the mission's own interruptions a
   week, out of its owner's attention budget; once spent, the next one is held and listed — the
   same hold the attention budget already records (`govern/attention.py`).

Kernel artifact kinds ``mission`` and ``mission_report`` — no new store. The loop reads a mission
in three places: triage's first term (:func:`bearing`: a message about the objective's metric, a
constraint's metric or a watched thing bears on it), the authority ladder's ceiling
(:func:`ceiling_for`: the lowest ceiling an active mission on the scope set for the action), and
the inquiry door (``opened_by = mission:<id>``).

The report (:func:`compose_report`) is composed from fields by code, no model: the objective
against the baseline the metric's own history predicts (method 3, `record/scenario.history`) FIRST,
then whether each constraint held, what it watched, what it opened, what it decided and what became
of it, what it cost (interruptions used of its budget, actions by level, demotions), and lessons.
"Nine findings, one decision, no measurable effect yet" is a valid report, and the headline says so.
A spend nobody has priced is said as unpriced, never shown as zero.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

KIND = "mission"
REPORT_KIND = "mission_report"

State = Literal["proposed", "active", "paused", "met", "retired"]
STATES: tuple[str, ...] = ("proposed", "active", "paused", "met", "retired")
#: Review cadences and the days each covers.
CADENCE_DAYS: dict[str, int] = {"weekly": 7, "monthly": 30, "quarterly": 91}
#: Interruptions a week a mission may cause when its author set no other number (§J's example).
DEFAULT_INTERRUPTIONS_PER_WEEK = 3
#: The authority ceiling a mission sets for an action it does not name: the gate's default.
DEFAULT_CEILING = 3
#: How the bearing term reads: the objective's metric, a constraint's, a watched thing's label.
BEARING_OBJECTIVE, BEARING_CONSTRAINT, BEARING_WATCH = 1.0, 0.7, 0.5


class Objective(BaseModel):
    metric: str                          # the governed metric's name or label
    direction: str = ""                  # up | down | hold
    target: Optional[float] = None
    unit: str = ""
    by_when: str = ""                    # ISO date
    spec: Optional[dict] = None          # the measurable definition (metric_sql · metric_table · date_column · window_days)
    text: str = ""                       # the line as written: "<the metric> ≥ 41%, rolling 4 weeks"


class Constraint(BaseModel):
    metric: str                          # a metric, or a promise's name
    kind: str = "metric"                 # metric | promise
    limit: Optional[float] = None
    bound: str = "at_least"              # at_least | at_most
    unit: str = ""
    spec: Optional[dict] = None
    text: str = ""


class Scope(BaseModel):
    domain: str = ""
    segment: str = ""
    connections: list[str] = Field(default_factory=list)


class Budget(BaseModel):
    interruptions_per_week: int = DEFAULT_INTERRUPTIONS_PER_WEEK
    spend_per_month: Optional[float] = None
    spend_unit: str = ""
    #: action id → the highest level it may act at under this mission; "*" for every declared action.
    authority_ceiling: dict[str, int] = Field(default_factory=dict)


class Watch(BaseModel):
    kind: str                            # monitor | promise | claim | card
    ref: str
    label: str = ""


class Review(BaseModel):
    cadence: str = "monthly"             # weekly | monthly | quarterly
    next_report_on: str = ""             # ISO date
    last_report: str = ""                # the latest report artifact's id
    reports: list[str] = Field(default_factory=list)


class Mission(BaseModel):
    name: str
    objective: Objective
    constraints: list[Constraint] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    owner: str = ""                      # a person principal (user:<id>); "" is said, and the mission does not run
    budget: Budget = Field(default_factory=Budget)
    watches: list[Watch] = Field(default_factory=list)
    review: Review = Field(default_factory=Review)
    state: str = "proposed"
    written_by: str = ""                 # the person who wrote it
    opened_at: str = ""
    history: list[dict] = Field(default_factory=list)     # {at, by, from, to, why}
    extra: dict[str, Any] = Field(default_factory=dict)
    # read-only, filled by the ledger
    id: str = ""
    key: str = ""
    version: int = 0
    recorded_at: str = ""
    superseded_by: str = ""


class MissionRefused(ValueError):
    """The door said no, and why."""


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def mission_key(name: str, connection_id: str = "") -> str:
    slug = "-".join("".join(ch if ch.isalnum() else " " for ch in (name or "").lower()).split())[:80]
    return f"mission:{connection_id or 'org'}:{slug or 'mission'}"


def _from(art: dict) -> Mission:
    m = Mission.model_validate(dict(art.get("payload") or {}))
    m.id = str(art.get("id") or "")
    m.key = str(art.get("natural_key") or "")
    m.version = int(art.get("version") or 0)
    m.recorded_at = str(art.get("created_at") or "")
    m.superseded_by = str(art.get("superseded_by") or "")
    return m


def _book(m: Mission, *, lineage: Optional[list] = None) -> Mission:
    data = m.model_dump()
    for read_only in ("id", "key", "version", "recorded_at", "superseded_by"):
        data.pop(read_only, None)
    conn = m.scope.connections[0] if len(m.scope.connections) == 1 else None
    aid = _ledger().artifact_write(KIND, m.key or mission_key(m.name, conn or ""), data, conn_id=conn,
                                   lineage=list(lineage or []))
    art = _ledger().artifact_by_id(aid)
    return _from(art) if art else m


# ── the door ───────────────────────────────────────────────────────────────────────────────

def _is_person(who: str, kind: str) -> bool:
    who = (who or "").strip()
    if not who or kind != "person":
        return False
    return not (who.startswith("agent:") or who.startswith("system") or who == "model")


def write_mission(m: Mission, *, by: str, by_kind: str = "person") -> Mission:
    """A person writes a mission (or edits it: a new version under the same key, the old kept).
    Refuses one written by an agent or the system, one with no objective metric, a cadence the
    report cannot keep, a ceiling off the ladder, or an owner who is not a person."""
    if not _is_person(by, by_kind):
        raise MissionRefused("people write missions; a model never does — the author is a person, named")
    if not (m.name or "").strip():
        raise MissionRefused("a mission has a name")
    if not (m.objective.metric or "").strip():
        raise MissionRefused("a mission's objective names the metric it is about")
    if m.objective.direction and m.objective.direction not in ("up", "down", "hold"):
        raise MissionRefused("an objective's direction is up, down or hold")
    if m.review.cadence not in CADENCE_DAYS:
        raise MissionRefused(f"a review cadence is one of {', '.join(CADENCE_DAYS)}")
    for action_id, level in (m.budget.authority_ceiling or {}).items():
        if not isinstance(level, int) or level < 0 or level > 5:
            raise MissionRefused(f"the authority ceiling for {action_id!r} is a level L0–L5")
    if m.budget.interruptions_per_week < 0:
        raise MissionRefused("interruptions a week is a count")
    if m.owner and not _is_person(m.owner, "person"):
        raise MissionRefused("a mission's owner is a person — an agent cannot own one")
    for c in m.constraints:
        if c.bound not in ("at_least", "at_most"):
            raise MissionRefused("a constraint's bound is at_least or at_most")
    if m.state not in STATES:
        raise MissionRefused(f"a mission's state is one of {', '.join(STATES)}")
    if m.state == "active" and not m.owner:
        raise MissionRefused("a mission without an owner does not run — it stays proposed until a person owns it")
    conn = m.scope.connections[0] if len(m.scope.connections) == 1 else ""
    m.key = m.key or mission_key(m.name, conn)
    prior = latest(m.key)
    now = _now().isoformat()
    m.written_by = m.written_by or by
    m.opened_at = (prior.opened_at if prior else "") or m.opened_at or now
    if prior is not None:
        m.history = list(prior.history) + [{"at": now, "by": by, "from": prior.state, "to": m.state, "why": "edited"}]
        m.review.reports = m.review.reports or list(prior.review.reports)
        m.review.last_report = m.review.last_report or prior.review.last_report
    if not m.objective.spec:
        m.objective.spec = spec_for_metric(m.objective.metric, conn)
    for c in m.constraints:
        if c.kind == "metric" and not c.spec:
            c.spec = spec_for_metric(c.metric, conn)
    if not m.review.next_report_on:
        m.review.next_report_on = (_now() + _dt.timedelta(days=CADENCE_DAYS[m.review.cadence])).date().isoformat()
    return _book(m, lineage=[("owned_by", m.owner, "a person")] if m.owner else [])


def set_state(mission_id: str, state: str, *, by: str, why: str = "") -> Mission:
    """A person activates, pauses, retires a mission or marks it met. Activation without an owner
    is refused — a mission without an owner does not run."""
    if state not in STATES:
        raise MissionRefused(f"a mission's state is one of {', '.join(STATES)}")
    if not _is_person(by, "person"):
        raise MissionRefused("a person changes a mission's state")
    m = get_mission(mission_id)
    if m is None:
        raise MissionRefused(f"no mission {mission_id!r}")
    m = latest(m.key) or m
    if state == "active" and not m.owner:
        raise MissionRefused("a mission without an owner does not run — name an owner before activating it")
    now = _now().isoformat()
    m.history = list(m.history) + [{"at": now, "by": by, "from": m.state, "to": state, "why": (why or "")[:400]}]
    m.state = state
    return _book(m, lineage=[("state", state, (why or "")[:200])])


# ── reading ────────────────────────────────────────────────────────────────────────────────

def get_mission(mission_id: str) -> Optional[Mission]:
    art = _ledger().artifact_by_id(mission_id)
    return _from(art) if art and art.get("kind") == KIND else None


def latest(key: str) -> Optional[Mission]:
    art = _ledger().artifact_latest(key)
    return _from(art) if art and art.get("kind") == KIND else None


def list_missions(*, conn_id: Optional[str] = None, state: Optional[str] = None, owner: Optional[str] = None,
                  limit: int = 200) -> list[Mission]:
    """Current missions, newest first. A mission scoped to several connections (or to none, the
    organisation's) is listed for every connection asked about."""
    out = []
    for art in _ledger().artifacts_of_kind(KIND, limit=max(limit * 4, 200)):
        m = _from(art)
        if conn_id and m.scope.connections and conn_id not in m.scope.connections:
            continue
        if state and m.state != state:
            continue
        if owner and m.owner != owner:
            continue
        out.append(m)
        if len(out) >= limit:
            break
    return out


def active_missions(conn_id: Optional[str] = None) -> list[Mission]:
    return [m for m in list_missions(conn_id=conn_id, state="active", limit=500) if m.owner]


# ── what the loop reads ────────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in (text or "").lower()).split())


def _names(x) -> set[str]:
    out = set()
    for raw in x:
        n = _norm(raw)
        if n:
            out.add(n)
            out.add(n.replace(" ", "_"))
    return out


def bearing(connection_id: str, *, metric: str = "", text: str = "", about: str = "") -> dict:
    """Triage's first term, read from the missions people wrote: 1.0 when the message is about an
    active mission's objective metric, 0.7 a constraint's, 0.5 a watched thing; 0 when no active
    mission bears on it — and when none exists, which the dict says. ``about`` is the gate's
    ``metric:<label>``; ``text`` is the message, matched on whole metric names only."""
    missions = active_missions(connection_id or None)
    if not missions:
        return {"score": 0.0, "missions": [], "why": "no active mission with an owner bears on this"}
    label = _norm(about.split(":", 1)[1] if about.startswith("metric:") else about)
    probes = {p for p in (_norm(metric), label) if p}
    body = f" {_norm(text)} "
    best, hits = 0.0, []
    for m in missions:
        score = 0.0
        if _names([m.objective.metric]) & probes or any(f" {n} " in body for n in _names([m.objective.metric]) if len(n) > 3):
            score = BEARING_OBJECTIVE
        elif any(_names([c.metric]) & probes or any(f" {n} " in body for n in _names([c.metric]) if len(n) > 3)
                 for c in m.constraints):
            score = BEARING_CONSTRAINT
        elif any(_names([w.label or w.ref]) & probes or any(f" {n} " in body for n in _names([w.label or w.ref]) if len(n) > 3)
                 for w in m.watches):
            score = BEARING_WATCH
        if score:
            hits.append({"mission": m.id, "name": m.name, "owner": m.owner, "score": score,
                         "interruptions_per_week": m.budget.interruptions_per_week})
            best = max(best, score)
    hits.sort(key=lambda h: -h["score"])
    why = (f"bears on {hits[0]['name']} ({'objective' if best == BEARING_OBJECTIVE else 'constraint' if best == BEARING_CONSTRAINT else 'a watch'})"
           if hits else f"no active mission among {len(missions)} bears on this")
    return {"score": best, "missions": hits, "why": why}


def interruptions_this_week(mission_id: str, now: Optional[_dt.datetime] = None) -> int:
    """Unattended departures that DEPARTED this week bearing on this mission — the charge."""
    from aughor.govern.attention import week_start
    from aughor.govern.departure_store import count_departed_bearing
    return count_departed_bearing(mission_id, since=week_start(now))


def charge(hits: list[dict], now: Optional[_dt.datetime] = None) -> dict:
    """Whether the missions a departure bears on still have an interruption left this week:
    ``{"allowed", "spent": [...], "used": {...}}``. The departure's own row is the count."""
    spent, used = [], {}
    for h in hits or []:
        n = interruptions_this_week(str(h.get("mission") or ""), now)
        used[str(h.get("mission") or "")] = n
        if n >= int(h.get("interruptions_per_week") or 0):
            spent.append(h)
    return {"allowed": not spent, "spent": spent, "used": used}


def ceiling_for(action_id: str, scope: str) -> Optional[int]:
    """The lowest authority ceiling an active mission on this scope set for the action (by its id
    or for every action, "*"); None when no mission names it — the ladder is then bounded only by
    the record and the irreversibility rule."""
    levels = []
    for m in active_missions(scope or None):
        c = m.budget.authority_ceiling or {}
        if action_id in c:
            levels.append(int(c[action_id]))
        elif "*" in c:
            levels.append(int(c["*"]))
    return min(levels) if levels else None


def spec_for_metric(metric: str, connection_id: str = "") -> Optional[dict]:
    """The measurable definition of a governed metric, in the review's shape (`playbook/outcomes.
    measurement_sql`): its approved SQL expression over its first table, cut by its time column.
    None when no governed metric of that name exists or it cannot be measured on one table — the
    report then says the objective is not measurable rather than guessing."""
    name = (metric or "").strip()
    if not name:
        return None
    try:
        from aughor.semantic.metrics import get_metric, list_metrics
        m = get_metric(name, connection_id=connection_id or None) or get_metric(name)
        if m is None:
            target = _norm(name)
            m = next((x for x in list_metrics(connection_id=connection_id or None)
                      if _norm(x.label) == target or _norm(x.name) == target), None)
    except Exception as exc:  # noqa: BLE001 — an unreadable metric store is "not measurable", said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the governed metric could not be read for a mission's objective", counter="mission.spec")
        return None
    if m is None or not (m.sql or "").strip() or not m.tables:
        return None
    table = m.tables[0]
    date_col = f"{table}.{m.time_column}" if m.time_column and "." not in m.time_column else (m.time_column or "")
    return {"metric_label": m.label or m.name, "metric_name": m.name, "metric_sql": m.sql, "metric_table": table,
            "date_column": date_col, "window_days": 30, "unit": m.unit or ""}


# ── the report ─────────────────────────────────────────────────────────────────────────────

def _measure(spec: Optional[dict], run_sql, *, end_day: _dt.date, days: int) -> dict:
    """The objective (or a constraint) measured over the report's window and against the metric's
    own history (method 3) — or why it could not be."""
    if not spec:
        return {"measurable": False, "note": "no measurable definition: the metric is not a governed metric with "
                                             "an approved statement over one table, or none of that name exists"}
    from aughor.playbook.outcomes import measure_spec
    from aughor.record.scenario import history
    s = {**spec, "window_days": days}
    actual, label, why = measure_spec(s, run_sql, end_day=end_day)
    out: dict[str, Any] = {"measurable": True, "window": label, "actual": actual, "note": why}
    if actual is None:
        return out
    try:
        p = history(s, run_sql, end_day=end_day)
    except Exception as exc:  # noqa: BLE001 — a baseline that cannot be read is a note, never a number
        p = None
        out["baseline_note"] = f"history baseline failed: {str(exc)[:160]}"
    if p is not None and p.value is not None:
        out.update({"baseline": p.value, "baseline_low": p.low, "baseline_high": p.high,
                    "baseline_n": int((p.backtest or {}).get("n") or 0), "backtest": dict(p.backtest or {}),
                    "effect": round(actual - p.value, 6), "method": "history",
                    "against_baseline": ("inside" if p.low <= actual <= p.high else "above" if actual > p.high else "below"),
                    "baseline_note": " · ".join(p.must_say)})
    elif p is not None:
        out["baseline_note"] = p.note or "no history baseline"
    return out


def _objective_verdict(obj: Objective, measured: dict) -> tuple[str, str]:
    """``(verdict, why)``: moved · unmoved · against · cannot_tell — the movement is judged against
    the baseline's own band (inside it is noise, not movement), the target against the actual."""
    actual, base = measured.get("actual"), measured.get("baseline")
    if actual is None:
        return "cannot_tell", measured.get("note") or "the objective could not be measured this period"
    if base is None:
        return "cannot_tell", "measured, but no baseline could be drawn from the metric's own history: " + str(measured.get("baseline_note") or "")
    where = measured.get("against_baseline")
    if where == "inside":
        return "unmoved", (f"{actual:.4g} sits inside what the metric's own history predicted "
                           f"({measured['baseline_low']:.4g} to {measured['baseline_high']:.4g}): no movement past the noise")
    wanted = {"up": "above", "down": "below"}.get(obj.direction or "", "")
    if not wanted:
        return "moved", f"{actual:.4g} is {where} the history band ({measured['baseline_low']:.4g} to {measured['baseline_high']:.4g}); the objective named no direction"
    if where == wanted:
        met = ""
        if obj.target is not None:
            met = " and the target is met" if ((obj.direction == "up" and actual >= obj.target) or (obj.direction == "down" and actual <= obj.target)) else f" and the target {obj.target:g} is not yet met"
        return "moved", f"{actual:.4g} is {where} the history band, the direction the mission wants{met}"
    return "against", f"{actual:.4g} is {where} the history band — the wrong way for an objective that wants {obj.direction}"


def _constraint_held(c: Constraint, measured: dict) -> tuple[Optional[bool], str]:
    actual = measured.get("actual")
    if actual is None or c.limit is None:
        return None, "cannot tell: " + (measured.get("note") or "no limit stated" if c.limit is None else "")
    held = actual >= c.limit if c.bound == "at_least" else actual <= c.limit
    return held, f"{actual:.4g} {'≥' if c.bound == 'at_least' else '≤'} {c.limit:g}: {'held' if held else 'broken'}"


def _tolerated(fn, default, label: str):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — a report line that cannot be read says so, never a crash
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"the mission report could not read its {label}", counter="mission.report")
        return default


def compose_report(m: Mission, *, run_sql_for, now: Optional[_dt.datetime] = None) -> dict:
    """The report, composed from fields by code — the objective against baseline first."""
    now = now or _now()
    days = CADENCE_DAYS.get(m.review.cadence, 30)
    end_day = now.date() - _dt.timedelta(days=1)
    since = (now - _dt.timedelta(days=days)).isoformat()
    conn = m.scope.connections[0] if m.scope.connections else ""
    run_sql = None
    if conn:
        try:
            run_sql = run_sql_for(conn, internal=True)
        except Exception as exc:  # noqa: BLE001
            run_sql = None
            conn_note = f"the connection could not be opened: {str(exc)[:160]}"
        else:
            conn_note = ""
    else:
        conn_note = "the mission names no connection; nothing can be measured"

    def measured(spec):
        if run_sql is None:
            return {"measurable": False, "note": conn_note}
        return _measure(spec, run_sql, end_day=end_day, days=days)

    objective = measured(m.objective.spec)
    verdict, why = _objective_verdict(m.objective, objective)
    constraints = []
    for c in m.constraints:
        mc = measured(c.spec) if c.kind == "metric" else {"measurable": False, "note": "a promise is read from its own record"}
        held, note = _constraint_held(c, mc)
        constraints.append({"metric": c.metric, "kind": c.kind, "limit": c.limit, "bound": c.bound, "held": held, "note": note,
                            "actual": mc.get("actual"), "window": mc.get("window", "")})

    from aughor.record import decisions as D
    from aughor.record import inquiry as I
    tag = f"mission:{m.id}"
    inquiries = _tolerated(lambda: [q for q in I.list_inquiries(limit=2000)
                                    if q.opened_by == tag or q.extra.get("mission") in (m.id, m.key)], [], "inquiries")
    by_state: dict[str, int] = {}
    for q in inquiries:
        by_state[q.state] = by_state.get(q.state, 0) + 1
    lessons = [lesson.model_dump() for q in inquiries for lesson in q.lessons]
    decisions = _tolerated(lambda: [d for d in D.list_decisions(limit=2000) if d.objective in (m.id, m.key)], [], "decisions")
    decided = []
    for d in decisions:
        o = D.outcome_by_id(d.outcome) if d.outcome else None
        decided.append({"decision": d.id, "question": d.question[:160], "chosen": d.chosen, "decided_at": d.decided_at[:10],
                        "review_on": d.review_on, "outcome": (o.verdict if o else "not yet reviewed"),
                        "against_expectation": (o.against_expectation if o else "")})
    outcomes = [x["outcome"] for x in decided if x["outcome"] != "not yet reviewed"]

    watches = []
    for w in m.watches:
        row = {"kind": w.kind, "ref": w.ref, "label": w.label}
        if w.kind == "monitor":
            def _alerts(ref=w.ref):
                from aughor.monitors.store import get_alerts
                return [a for a in get_alerts(monitor_id=ref, limit=200) if str(getattr(a, "triggered_at", "") or "") >= since]
            fired = _tolerated(_alerts, None, "monitor alerts")
            row["state"] = "unreadable" if fired is None else (f"fired {len(fired)} time{'s' if len(fired) != 1 else ''} this period" if fired else "quiet this period")
        elif w.kind == "claim":
            from aughor.record import claims as C
            c = _tolerated(lambda ref=w.ref: C.get(ref), None, "claim")
            row["state"] = (f"{c.state or c.status}" + (" · restated since" if c and c.superseded_by else "")) if c else "no such claim"
        else:
            row["state"] = "read from its own record"
        watches.append(row)

    from aughor.govern.departure_store import count_departed_bearing, held_bearing
    interruptions = _tolerated(lambda: count_departed_bearing(m.id, since=since), 0, "interruptions")
    held = _tolerated(lambda: held_bearing(m.id, since=since), [], "held departures")
    budgeted = m.budget.interruptions_per_week * max(1, round(days / 7))
    actions_by_level: dict[str, int] = {}
    demotions = []
    if conn:
        from aughor.actions.authority import DEMOTION_KIND
        from aughor.kernel.ledger import Ledger
        led = Ledger.default()
        for art in _tolerated(lambda: led.artifacts_of_kind("action", conn_id=conn, limit=2000), [], "actions"):
            p = dict(art.get("payload") or {})
            if str(art.get("created_at") or "") < since or p.get("status") != "executed":
                continue
            if p.get("decision") and p["decision"] not in {d.id for d in decisions}:
                continue
            level = f"L{4 if p.get('grant_id') else 3}"
            actions_by_level[level] = actions_by_level.get(level, 0) + 1
        for art in _tolerated(lambda: led.artifacts_of_kind(DEMOTION_KIND, conn_id=conn, limit=200), [], "demotions"):
            if str(art.get("created_at") or "") >= since:
                p = dict(art.get("payload") or {})
                demotions.append({"action_id": p.get("action_id"), "why": str(p.get("why") or "")[:200], "at": str(art.get("created_at") or "")[:10]})
    spend = ({"amount": None, "unit": m.budget.spend_unit, "note": "not counted: no spend is attributed to a mission yet; "
                                                                   "the budget is stated, the charge is not"}
             if m.budget.spend_per_month is not None else {"amount": None, "note": "no spend budget stated"})

    moved_line = {"moved": "the objective moved against its baseline", "unmoved": "the objective did not move past its baseline's noise",
                  "against": "the objective moved the wrong way", "cannot_tell": "the objective could not be judged"}[verdict]
    findings = sum(len(q.claims) for q in inquiries)
    headline = (f"{moved_line} — {why}. {len(inquiries)} inquir{'y' if len(inquiries) == 1 else 'ies'}, {findings} "
                f"finding{'s' if findings != 1 else ''}, {len(decisions)} decision{'s' if len(decisions) != 1 else ''}"
                + (f", outcomes: {', '.join(outcomes)}" if outcomes else ", no measurable effect yet")
                + f"; {interruptions} of {budgeted} interruptions used.")
    period = {"from": (end_day - _dt.timedelta(days=days - 1)).isoformat(), "to": end_day.isoformat(), "days": days,
              "cadence": m.review.cadence}
    return {"mission": m.id, "key": m.key, "name": m.name, "owner": m.owner, "state": m.state, "period": period,
            "headline": headline,
            "objective": {**m.objective.model_dump(exclude={"spec"}), **objective, "verdict": verdict, "why": why},
            "constraints": constraints, "watches": watches,
            "opened": {"inquiries": len(inquiries), "by_state": by_state, "ids": [q.id for q in inquiries][:50]},
            "decided": decided,
            "cost": {"interruptions": interruptions, "interruptions_budgeted": budgeted, "held": len(held),
                     "actions_by_level": actions_by_level, "demotions": demotions, "spend": spend},
            "lessons": lessons, "composed_at": now.isoformat(), "composed_by": "code: composed from fields; no model"}


def book_report(m: Mission, report: dict) -> tuple[str, Mission]:
    """Book the report as a ledger entry and advance the mission's review: last report, next date."""
    end = str((report.get("period") or {}).get("to") or _now().date().isoformat())
    key = f"{REPORT_KIND}:{m.key}:{end}"
    rid = _ledger().artifact_write(REPORT_KIND, key, report,
                                   conn_id=(m.scope.connections[0] if len(m.scope.connections) == 1 else None),
                                   lineage=[("reports_on", m.id, report.get("objective", {}).get("verdict", ""))])
    current = latest(m.key) or m
    current.review.last_report = rid
    current.review.reports = list(current.review.reports) + [rid]
    current.review.next_report_on = (_dt.date.fromisoformat(end) + _dt.timedelta(days=CADENCE_DAYS.get(m.review.cadence, 30) + 1)).isoformat()
    current.extra["last_report_headline"] = str(report.get("headline") or "")[:400]
    return rid, _book(current, lineage=[("reported", rid, end)])


def get_report(report_id: str) -> Optional[dict]:
    art = _ledger().artifact_by_id(report_id)
    if not art or art.get("kind") != REPORT_KIND:
        return None
    return {**dict(art.get("payload") or {}), "id": str(art.get("id") or ""), "recorded_at": str(art.get("created_at") or "")}


def reports_for(m: Mission) -> list[dict]:
    out = []
    for rid in reversed(m.review.reports):
        r = get_report(rid)
        if r:
            out.append(r)
    return out


def due_reports(now: Optional[_dt.datetime] = None) -> list[Mission]:
    """Active missions whose report date has come."""
    today = (now or _now()).date().isoformat()
    return [m for m in active_missions() if m.review.next_report_on and m.review.next_report_on <= today]


def deliver_report(m: Mission, report: dict, report_id: str, *, now: Optional[_dt.datetime] = None) -> dict:
    """The report to its owner, where they already are, through the departure gate (the review
    question's own door, `playbook/review_delivery.py`). A person with no channel bound is said."""
    now = now or _now()
    if not m.owner:
        return {"door": "none", "status": "nobody", "note": "no owner to deliver to"}
    try:
        from aughor.org.context import current_org_id
        from aughor.rbac.routing import route
        org = current_org_id()
        destinations = route(f"mission:{m.key}", org_id=org, owner=m.owner)
        channel = next((d for d in destinations if d.channel_trigger_id), None)
        if channel is None:
            return {"door": "none", "status": "not_sent",
                    "note": f"{m.owner} has no channel bound; the report waits on the mission page and the Now page"}
        from aughor.notifications.store import get_trigger
        trigger = get_trigger(channel.channel_trigger_id)
        if trigger is None:
            return {"door": "channel", "status": "not_sent", "target": channel.channel_trigger_id,
                    "note": f"the channel {channel.channel_trigger_id!r} bound to {m.owner} no longer exists"}
        from aughor.govern.departure import Measurement, gate_departure
        from aughor.notifications.executor import fire_action
        from aughor.notifications.models import ActionPayload
        obj = report.get("objective") or {}
        values = [float(v) for v in (obj.get("baseline"), obj.get("actual")) if v is not None]
        conn = m.scope.connections[0] if m.scope.connections else ""
        verdict = gate_departure(
            kind="mission_report", org_id=org, conn_id=conn, text=str(report.get("headline") or ""),
            target=trigger.id, actor=f"mission:{m.id}", source_kind="mission", source_id=m.id, source_name=m.name,
            about=f"metric:{m.objective.metric}", origin="unattended",
            measurement=Measurement(source=f"the mission report of {m.name}", values=values,
                                    measured_at=now.isoformat(), definition=m.objective.metric) if values else None,
            declared_definition=m.objective.metric, dated_records=not values)
        if verdict.held:
            return {"door": "channel", "status": "held", "target": trigger.id, "departure_id": verdict.record_id,
                    "note": verdict.reason_sentence()}
        log = fire_action(trigger, ActionPayload(
            investigation_id=f"mission:{m.id}", rec_index=0, recommendation=str(report.get("headline") or ""),
            metric_name=m.objective.metric, headline=f"Mission report: {m.name}", trigger_id=trigger.id,
            triggered_at=now.isoformat(), delivery_key=f"mission_report:{report_id}",
            context={"mission": m.id, "report": report_id, "owner": m.owner, "receipt": verdict.receipt,
                     "receipt_line": verdict.receipt_line()}))
        status = getattr(log, "status", "") or "unknown"
        return {"door": "channel", "status": "sent" if status == "ok" else status, "target": trigger.id,
                "departure_id": verdict.record_id, "to": m.owner,
                "note": "" if status == "ok" else str(getattr(log, "error", "") or "")}
    except Exception as exc:  # noqa: BLE001 — the report stands booked; its delivery is said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the mission report could not be delivered", counter="mission.deliver")
        return {"door": "channel", "status": "failed", "note": str(exc)[:200]}


def report_now(m: Mission, *, run_sql_for, now: Optional[_dt.datetime] = None, deliver: bool = True) -> dict:
    """Compose, book and (by default) deliver one report — the heartbeat's call and the door's."""
    report = compose_report(m, run_sql_for=run_sql_for, now=now)
    rid, updated = book_report(m, report)
    delivery = deliver_report(updated, report, rid, now=now) if deliver else {"door": "none", "status": "not_requested"}
    _ledger().emit("mission.reported", {"mission": m.id, "report": rid, "verdict": report["objective"]["verdict"],
                                        "delivery": delivery.get("status")},
                   conn_id=(m.scope.connections[0] if len(m.scope.connections) == 1 else None))
    return {"report_id": rid, "report": report, "delivery": delivery, "mission": updated.model_dump()}


def report_due_missions(*, run_sql_for, now: Optional[_dt.datetime] = None) -> list[dict]:
    """Every active mission whose report date has come: composed, booked, delivered."""
    return [report_now(m, run_sql_for=run_sql_for, now=now) for m in due_reports(now)]
