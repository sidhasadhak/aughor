"""The Record's doors (the 2027 study §G and §K; phase 1, P1-3) — claims read as they stand or
as they stood on a date, decisions listed and declared, outcomes booked.

Reads only what the kernel ledger holds (`aughor/record/`): no second store, no model. Under
identity, a claim or decision is visible only when its connection is in the caller's org, the
same rule the receipt door applies; an unscoped entry (no connection) is visible to its org's
callers like any organisation-wide fact.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.security.authz import get_principal

router = APIRouter(tags=["record"])


def _visible(conn_id: str) -> bool:
    from aughor.security.authz import org_visible_conn_ids
    visible = org_visible_conn_ids()
    return visible is None or not conn_id or conn_id in visible


def _claim_view(c: C.Claim) -> dict:
    """The claim with its confidence COUNTED on read (P1-4): a hit rate with its n, the count
    alone below the threshold, or nothing — with why — when no class counts this kind yet."""
    from aughor.record.confidence import why_uncounted, with_confidence
    seen = with_confidence(c)
    view = seen.model_dump()
    if seen.confidence is None:
        view["confidence_note"] = why_uncounted(c)
    return view


def _decision_view(d: D.Decision) -> dict:
    return d.model_dump()


def _who(principal) -> str:
    for attr in ("user_id", "email", "id", "sub", "name"):
        v = getattr(principal, attr, "") if principal is not None else ""
        if v:
            return f"user:{v}"
    return ""


# ── claims ─────────────────────────────────────────────────────────────────────────────────

@router.get("/record/claims")
def list_record_claims(kind: Optional[str] = None, about_kind: Optional[str] = None,
                       about_key: Optional[str] = None, connection_id: Optional[str] = None,
                       state: Optional[str] = None, as_of: Optional[str] = None,
                       limit: int = 100) -> list[dict]:
    """Current claims, newest first — or, with ``as_of`` (an ISO date), each claim as it stood on
    that day (belief as a view, not a second store)."""
    filters: dict[str, Any] = dict(kind=kind, about_kind=about_kind, about_key=about_key,
                                   conn_id=connection_id, state=state, limit=max(1, min(int(limit), 1000)))
    try:
        rows = C.as_recorded(as_of, **filters) if as_of else C.list_claims(**filters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return [_claim_view(c) for c in rows if _visible(c.about.key if c.about.kind == "connection" else "")]


@router.get("/record/claims/{claim_id}")
def get_record_claim(claim_id: str) -> dict:
    c = C.get(claim_id)
    if c is None or not _visible(c.about.key if c.about.kind == "connection" else ""):
        raise HTTPException(status_code=404, detail="No such claim")
    view = _claim_view(c)
    view["relied_on_by"] = C.relied_on_by(claim_id)
    return view


@router.get("/record/claims/{claim_id}/versions")
def get_record_claim_versions(claim_id: str) -> list[dict]:
    """Every version of the claim this id belongs to, newest first — the restatements with their
    text kept."""
    c = C.get(claim_id)
    if c is None or not _visible(c.about.key if c.about.kind == "connection" else ""):
        raise HTTPException(status_code=404, detail="No such claim")
    return [_claim_view(v) for v in C.versions(c.key)]


# ── decisions ──────────────────────────────────────────────────────────────────────────────

class ExpectationIn(BaseModel):
    metric: str
    direction: str = ""            # up | down | hold
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None
    unit: str = ""                 # "%" for a relative change, else the metric's own
    coverage: float = 0.8
    settles_on: str = ""
    text: str = ""


class DissentIn(BaseModel):
    who: str
    why: str


class DeclareDecisionRequest(BaseModel):
    question: str
    chosen: str
    options: list[str] = Field(default_factory=list)
    owner: str = ""
    approvers: list[str] = Field(default_factory=list)
    dissent: list[DissentIn] = Field(default_factory=list)
    relied_on: list[str] = Field(default_factory=list)   # claim ids
    objective: str = ""
    connection_id: str = ""
    decided_at: str = ""
    decided_by: str = ""           # defaults to the identified caller
    review_on: str = ""            # defaults to the proposed date (30 days + the settling lag)
    expectation: Optional[ExpectationIn] = None
    note: str = ""


class OutcomeIn(BaseModel):
    measured_on: str
    actual: Optional[float] = None
    baseline: Optional[float] = None
    effect_value: Optional[float] = None
    effect_low: Optional[float] = None
    effect_high: Optional[float] = None
    method: str = ""
    verdict: str = "cannot_tell"
    why: str = ""
    against_expectation: str = ""
    writes_back: list[str] = Field(default_factory=list)


@router.get("/record/decisions")
def list_record_decisions(connection_id: Optional[str] = None, due: bool = False,
                          limit: int = 100) -> list[dict]:
    """Decisions, newest first; ``due`` keeps those whose review date has come and that carry no
    outcome yet."""
    limit = max(1, min(int(limit), 1000))
    rows = D.due_for_review() if due else D.list_decisions(conn_id=connection_id, limit=limit)
    if due and connection_id:
        rows = [d for d in rows if d.connection_id == connection_id]
    return [_decision_view(d) for d in rows[:limit] if _visible(d.connection_id)]


@router.get("/record/decisions/{decision_id}")
def get_record_decision(decision_id: str) -> dict:
    d = D.get_decision(decision_id)
    if d is None or not _visible(d.connection_id):
        raise HTTPException(status_code=404, detail="No such decision")
    view = _decision_view(d)
    view["relied_on_claims"] = [c.model_dump() for c in (C.get(cid) for cid in d.relied_on) if c is not None]
    view["expectation"] = (C.get(d.expectation_claim).model_dump() if d.expectation_claim and C.get(d.expectation_claim) else None)
    o = D.outcome_by_id(d.outcome) if d.outcome else D.get_outcome(decision_id)
    view["outcome_record"] = o.model_dump() if o is not None else None
    return view


@router.post("/record/decisions", status_code=201)
def declare_record_decision(req: DeclareDecisionRequest, principal=Depends(get_principal)) -> dict:
    """Declare a decision taken elsewhere, in its own words. The expectation, when given, is
    booked as a prediction claim at the same moment; the review date is proposed from the
    connection's settling lag when none is given."""
    from aughor.record.byproducts import declare_decision
    if req.connection_id and not _visible(req.connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    who = req.decided_by or _who(principal)
    try:
        did = declare_decision(
            question=req.question, chosen=req.chosen, options=req.options, owner=req.owner,
            approvers=req.approvers, dissent=[d.model_dump() for d in req.dissent], relied_on=req.relied_on,
            objective=req.objective, connection_id=req.connection_id, decided_at=req.decided_at,
            decided_by=who, review_on=req.review_on,
            expectation=req.expectation.model_dump() if req.expectation else None, note=req.note)
    except (ValueError, C.ClaimRefused) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return get_record_decision(did)


# ── inquiries ──────────────────────────────────────────────────────────────────────────────

class CloseInquiryRequest(BaseModel):
    closed_as: str                 # answered | overtaken | abandoned
    lessons: list[dict] = Field(default_factory=list)   # [{believed, turned_out}]


def _inquiry_view(q) -> dict:
    from aughor.record.inquiry import run_verdict
    view = q.model_dump()
    view["hypothesis_claims"] = [c.model_dump() for c in (C.get(cid) for cid in q.hypotheses) if c is not None]
    view["run_verdicts"] = [run_verdict(r.run) or {"run": r.run, "verdict": r.verdict, "why": r.why} for r in q.runs]
    return view


@router.get("/record/inquiries")
def list_record_inquiries(connection_id: Optional[str] = None, state: Optional[str] = None,
                          due: bool = False, limit: int = 100) -> list[dict]:
    """Inquiries, newest first; ``state`` is open · waiting · closed; ``due`` keeps the waiting ones
    whose check date has come."""
    from aughor.record import inquiry as I
    limit = max(1, min(int(limit), 1000))
    rows = I.due() if due else I.list_inquiries(conn_id=connection_id, state=state, limit=limit)
    if due and connection_id:
        rows = [q for q in rows if q.connection_id == connection_id]
    return [q.model_dump() for q in rows[:limit] if _visible(q.connection_id)]


@router.get("/record/inquiries/verdicts")
def record_run_verdicts(connection_id: Optional[str] = None) -> dict:
    """How runs ended, by typed verdict — the share that was a failure said as what it was."""
    from aughor.record.inquiry import verdict_tallies
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    return verdict_tallies(conn_id=connection_id)


@router.get("/record/inquiries/{inquiry_id}")
def get_record_inquiry(inquiry_id: str) -> dict:
    from aughor.record.inquiry import get_inquiry
    q = get_inquiry(inquiry_id)
    if q is None or not _visible(q.connection_id):
        raise HTTPException(status_code=404, detail="No such inquiry")
    return _inquiry_view(q)


@router.post("/record/inquiries/{inquiry_id}/propose")
def propose_record_inquiry_run(inquiry_id: str) -> dict:
    """The run this inquiry waits for, proposed with what it costs on this install and what its
    result could change (the study §H); recomputed now and kept on the inquiry. Spends no model."""
    from aughor.record.inquiry import get_inquiry, propose_run, _book
    q = get_inquiry(inquiry_id)
    if q is None or not _visible(q.connection_id):
        raise HTTPException(status_code=404, detail="No such inquiry")
    q.extra["proposed_run"] = propose_run(q)
    return _inquiry_view(_book(q))


@router.post("/record/inquiries/{inquiry_id}/close")
def close_record_inquiry(inquiry_id: str, req: CloseInquiryRequest, principal=Depends(get_principal)) -> dict:
    """A person closes an inquiry — answered, overtaken or abandoned — with what was believed at
    the start and turned out wrong."""
    from aughor.record.inquiry import Lesson, close_inquiry, get_inquiry
    q = get_inquiry(inquiry_id)
    if q is None or not _visible(q.connection_id):
        raise HTTPException(status_code=404, detail="No such inquiry")
    try:
        closed = close_inquiry(q, closed_as=req.closed_as, lessons=[Lesson(**lesson) for lesson in req.lessons],
                               by=_who(principal) or "unidentified")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _inquiry_view(closed)


# ── scenarios and calibration ──────────────────────────────────────────────────────────────

class AssumptionIn(BaseModel):
    variable: str
    value: Optional[float] = None
    by: str = ""
    text: str = ""
    unit: str = ""
    low: Optional[float] = None
    high: Optional[float] = None


class ScenarioRequest(BaseModel):
    method: str                                  # identity | declared | history
    metric: str
    settles_on: str = ""                         # defaults to the decision's review date
    direction: str = ""
    unit: str = ""
    formula: str = ""                            # identity
    inputs: dict[str, float] = Field(default_factory=dict)
    varied: list[str] = Field(default_factory=list)
    assumption: Optional[AssumptionIn] = None    # declared
    spec: Optional[dict] = None                  # history: the measurable definition
    limits: list[str] = Field(default_factory=list)
    question: str = ""


@router.post("/record/decisions/{decision_id}/scenario", status_code=201)
def book_record_scenario(decision_id: str, req: ScenarioRequest, principal=Depends(get_principal)) -> dict:
    """Project under one method of the ladder (identity · declared · history) FOR a decision, and
    book the prediction with its method, band and what it must say; the scenario is a ledger
    entry inside the decision. A method the ladder does not have yet is refused by name."""
    from aughor.record import scenario as S
    d = D.get_decision(decision_id)
    if d is None or not _visible(d.connection_id):
        raise HTTPException(status_code=404, detail="No such decision")
    who = _who(principal)
    try:
        if req.method == "identity":
            proj = S.identity(req.formula, req.inputs, unit=req.unit, varied=req.varied)
        elif req.method == "declared":
            if req.assumption is None:
                raise HTTPException(status_code=422, detail="a declared method takes an assumption")
            a = req.assumption
            proj = S.declared(variable=a.variable, value=a.value, by=a.by or who, text=a.text, unit=a.unit or req.unit,
                              connection_id=d.connection_id, low=a.low, high=a.high)
        elif req.method == "history":
            if not req.spec:
                raise HTTPException(status_code=422, detail="the history method takes the metric's measurable spec")
            from aughor.db.measure import run_sql_for
            proj = S.history(req.spec, run_sql_for(d.connection_id, internal=True))
        else:
            raise HTTPException(status_code=422, detail=f"no method named {req.method!r}; the ladder has {', '.join(S.METHODS)}")
        settles_on = req.settles_on or d.review_on
        pid = S.predict(metric=req.metric, projection=proj, settles_on=settles_on, author=who or "unidentified",
                        connection_id=d.connection_id, direction=req.direction, spec=req.spec, for_ref=decision_id)
    except (S.FormulaRefused, C.ClaimRefused, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    assumptions = [S.Assumption(variable=req.assumption.variable, value=req.assumption.value, by=req.assumption.by or who,
                                text=req.assumption.text, claim=proj.claim)] if req.assumption else []
    scenario = S.book_scenario(S.Scenario(for_kind="decision", for_id=decision_id, question=req.question,
                                          assumptions=assumptions, predictions=[pid], limits=req.limits,
                                          methods=[req.method], connection_id=d.connection_id))
    return {"scenario": scenario.model_dump(), "projection": proj.model_dump(),
            "prediction": (C.get(pid).model_dump() if C.get(pid) else None)}


@router.get("/record/calibration")
def record_calibration(connection_id: Optional[str] = None) -> list[dict]:
    """Interval coverage by method, metric and author over scored predictions — counted."""
    from aughor.record.scenario import calibration
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    return calibration(conn_id=connection_id)


# ── corrections (phase 5) ──────────────────────────────────────────────────────────────────

@router.get("/record/corrections")
def record_corrections(connection_id: Optional[str] = None, kind: Optional[str] = None, limit: int = 100) -> dict:
    """What the platform was wrong about, as a first-class view: restatements, refuted hypotheses,
    missed moves, predictions outside their interval, decisions worse than expected — each with what
    was believed and what replaced it, counted by kind."""
    from aughor.record.corrections import corrections
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    try:
        out = corrections(conn_id=connection_id, kind=kind, limit=max(1, min(int(limit), 500)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    out["entries"] = [e for e in out["entries"] if _visible(str(e.get("connection_id") or ""))]
    return out


# ── missions (phase 5) ─────────────────────────────────────────────────────────────────────

class ObjectiveIn(BaseModel):
    metric: str
    direction: str = ""            # up | down | hold
    target: Optional[float] = None
    unit: str = ""
    by_when: str = ""
    spec: Optional[dict] = None    # the measurable definition; resolved from the governed metric when absent
    text: str = ""


class ConstraintIn(BaseModel):
    metric: str
    kind: str = "metric"           # metric | promise
    limit: Optional[float] = None
    bound: str = "at_least"        # at_least | at_most
    unit: str = ""
    spec: Optional[dict] = None
    text: str = ""


class BudgetIn(BaseModel):
    interruptions_per_week: int = 3
    spend_per_month: Optional[float] = None
    spend_unit: str = ""
    authority_ceiling: dict[str, int] = Field(default_factory=dict)   # action id (or "*") → L0–L5


class WatchIn(BaseModel):
    kind: str                      # monitor | promise | claim | card
    ref: str
    label: str = ""


class MissionRequest(BaseModel):
    name: str
    objective: ObjectiveIn
    constraints: list[ConstraintIn] = Field(default_factory=list)
    domain: str = ""
    segment: str = ""
    connections: list[str] = Field(default_factory=list)
    owner: str = ""                # a person; defaults to the identified caller
    budget: BudgetIn = Field(default_factory=BudgetIn)
    watches: list[WatchIn] = Field(default_factory=list)
    cadence: str = "monthly"       # weekly | monthly | quarterly
    state: str = "proposed"        # proposed | active (active needs an owner)
    key: str = ""                  # to edit an existing mission (a new version, the old kept)


class MissionStateRequest(BaseModel):
    state: str                     # proposed | active | paused | met | retired
    why: str = ""


def _mission_view(m) -> dict:
    from aughor.record.mission import interruptions_this_week
    view = m.model_dump()
    view["interruptions_this_week"] = interruptions_this_week(m.id) if m.state == "active" else 0
    view["runs"] = bool(m.owner and m.state == "active")
    if not view["runs"]:
        view["runs_note"] = ("a mission without an owner does not run" if not m.owner
                             else f"a {m.state} mission is not read by the loop")
    return view


@router.get("/record/missions")
def list_record_missions(connection_id: Optional[str] = None, state: Optional[str] = None,
                         owner: Optional[str] = None, limit: int = 100) -> list[dict]:
    """The missions people wrote, newest first — each with whether it runs and what it has cost this week."""
    from aughor.record.mission import list_missions
    rows = list_missions(conn_id=connection_id, state=state, owner=owner, limit=max(1, min(int(limit), 500)))
    return [_mission_view(m) for m in rows if all(_visible(c) for c in m.scope.connections)]


@router.post("/record/missions", status_code=201)
def write_record_mission(req: MissionRequest, principal=Depends(get_principal)) -> dict:
    """A person writes a mission — what to achieve, what not to damage, its scope, owner, budget,
    ceiling and cadence. A model never does: the author is the identified caller."""
    from aughor.record import mission as M
    for c in req.connections:
        if not _visible(c):
            raise HTTPException(status_code=404, detail="No such connection")
    who = _who(principal)
    m = M.Mission(
        name=req.name, objective=M.Objective(**req.objective.model_dump()),
        constraints=[M.Constraint(**c.model_dump()) for c in req.constraints],
        scope=M.Scope(domain=req.domain, segment=req.segment, connections=list(req.connections)),
        owner=req.owner or who, budget=M.Budget(**req.budget.model_dump()),
        watches=[M.Watch(**w.model_dump()) for w in req.watches],
        review=M.Review(cadence=req.cadence), state=req.state, key=req.key)
    try:
        booked = M.write_mission(m, by=who or "unidentified", by_kind="person" if who else "unidentified")
    except M.MissionRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _mission_view(booked)


@router.get("/record/missions/templates")
def list_record_mission_templates(connection_id: Optional[str] = None, schema_name: Optional[str] = None,
                                  pack_id: str = "") -> dict:
    """The mission templates the packs bound to a connection ship (phase 6) — or one named pack's —
    each as a body a person writes a mission from. A template never becomes a mission on its own."""
    from aughor.packs.ontology_map import bound_pack_ids, load_pack_by_id
    from aughor.packs.priors import mission_templates
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    pids = [pack_id] if pack_id else (bound_pack_ids(connection_id, schema_name) if connection_id else [])
    out: list[dict] = []
    for pid in pids:
        pack = load_pack_by_id(pid)
        if pack is not None:
            out += mission_templates(pack)
    return {"templates": out, "packs": pids,
            "note": ("" if pids else "no pack is bound to this connection and none was named; name a pack_id to read its templates")}


@router.get("/record/missions/{mission_id}")
def get_record_mission(mission_id: str) -> dict:
    """The mission as it stands — its latest version, whichever version's id was asked for — with
    its reports, newest first."""
    from aughor.record.mission import get_mission, latest, reports_for
    m = get_mission(mission_id)
    if m is None or not all(_visible(c) for c in m.scope.connections):
        raise HTTPException(status_code=404, detail="No such mission")
    current = latest(m.key) or m
    view = _mission_view(current)
    view["requested_version"] = m.version
    view["reports"] = [{"id": r["id"], "period": r.get("period"), "headline": r.get("headline"),
                        "verdict": (r.get("objective") or {}).get("verdict")} for r in reports_for(current)]
    return view


@router.post("/record/missions/{mission_id}/state")
def set_record_mission_state(mission_id: str, req: MissionStateRequest, principal=Depends(get_principal)) -> dict:
    """A person activates, pauses, retires a mission or marks it met; activation needs an owner."""
    from aughor.record import mission as M
    m = M.get_mission(mission_id)
    if m is None or not all(_visible(c) for c in m.scope.connections):
        raise HTTPException(status_code=404, detail="No such mission")
    try:
        return _mission_view(M.set_state(mission_id, req.state, by=_who(principal) or "unidentified", why=req.why))
    except M.MissionRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/record/missions/{mission_id}/act", status_code=201)
def act_record_mission(mission_id: str, principal=Depends(get_principal)) -> dict:
    """The L5 agent's turn, now (the close-out, C6): among the connection's declared actions at L5,
    choose by the measured effect on the objective and run one — or say why none was chosen."""
    from aughor.actions.autonomy import act_for_mission
    from aughor.record import mission as M
    m = M.get_mission(mission_id)
    if m is None or not all(_visible(c) for c in m.scope.connections):
        raise HTTPException(status_code=404, detail="No such mission")
    return act_for_mission(M.latest(m.key) or m)


@router.get("/record/missions/{mission_id}/report")
def get_record_mission_report(mission_id: str, compose: bool = False) -> dict:
    """The latest booked report — or, with ``compose``, the report as it would read now, composed
    from fields and NOT booked (a preview; the booked one is the heartbeat's or the POST's)."""
    from aughor.record import mission as M
    m = M.get_mission(mission_id)
    if m is None or not all(_visible(c) for c in m.scope.connections):
        raise HTTPException(status_code=404, detail="No such mission")
    current = M.latest(m.key) or m
    if compose:
        from aughor.db.measure import run_sql_for
        return {"booked": False, "report": M.compose_report(current, run_sql_for=run_sql_for)}
    latest_report = M.get_report(current.review.last_report) if current.review.last_report else None
    if latest_report is None:
        return {"booked": False, "report": None,
                "note": f"no report yet; the first is due {current.review.next_report_on or 'when the mission is active'}"}
    return {"booked": True, "report": latest_report}


@router.post("/record/missions/{mission_id}/report", status_code=201)
def post_record_mission_report(mission_id: str, deliver: bool = True, principal=Depends(get_principal)) -> dict:
    """Report now: composed, booked and delivered to the owner through the gate."""
    from aughor.db.measure import run_sql_for
    from aughor.record import mission as M
    m = M.get_mission(mission_id)
    if m is None or not all(_visible(c) for c in m.scope.connections):
        raise HTTPException(status_code=404, detail="No such mission")
    return M.report_now(M.latest(m.key) or m, run_sql_for=run_sql_for, deliver=deliver)


@router.post("/record/decisions/{decision_id}/outcome", status_code=201)
def book_record_outcome(decision_id: str, req: OutcomeIn, principal=Depends(get_principal)) -> dict:
    """Book what became of a decision: the actual against the expectation and against the
    baseline, with a verdict and why. The decision is restated carrying the outcome."""
    d = D.get_decision(decision_id)
    if d is None or not _visible(d.connection_id):
        raise HTTPException(status_code=404, detail="No such decision")
    if req.verdict not in ("as_expected", "better", "worse", "cannot_tell"):
        raise HTTPException(status_code=422, detail="verdict is one of as_expected · better · worse · cannot_tell")
    try:
        oid = D.book_outcome(D.Outcome(
            of=decision_id, measured_on=req.measured_on, actual=req.actual, baseline=req.baseline,
            effect=D.Effect(value=req.effect_value, low=req.effect_low, high=req.effect_high, method=req.method),
            verdict=req.verdict, why=req.why, against_expectation=req.against_expectation,
            writes_back=req.writes_back, measured_by=_who(principal) or "unidentified"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    latest = D.latest_decision(d.source)
    return {"outcome_id": oid, "decision": _decision_view(latest) if latest else None}
