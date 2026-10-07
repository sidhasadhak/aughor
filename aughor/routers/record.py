"""The Record's doors (the 2027 study §G and §K; phase 1, P1-3) — claims read as they stand or
as they stood on a date, decisions listed and declared, outcomes booked.

Reads only what the kernel ledger holds (`aughor/record/`): no second store, no model. Under
identity, a claim or decision is visible only when its connection is in the caller's org, the
same rule the receipt door applies; an unscoped entry (no connection) is visible to its org's
callers like any organisation-wide fact.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.security.authz import connection_owner_guard, get_principal

# Router-level, so a door added here later is covered without anyone remembering to (DATA-06): a
# connection a request names must be the caller's. `_visible` below still filters what a list returns.
router = APIRouter(tags=["record"], dependencies=[Depends(connection_owner_guard)])


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
    """Who is acting — the signed-in person, else the one the request acts for (`authz.acting_person`).
    Every ``by`` a body still carries is ignored: a name typed into a form is not who is signed in."""
    from aughor.security.authz import acting_person
    return acting_person(principal)


def _named(name: str) -> str:
    """A person a form NAMES as someone else — the owner an inquiry is handed to — kept as
    ``person:<name>`` so it never reads as a signed-in ``user:``. Not who acted: that is `_who`."""
    name = (name or "").strip()
    if not name:
        return ""
    return name if ":" in name else f"person:{name}"


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
    try:
        from aughor.record.receipt_lines import told_about
        view["told"], view["told_note"] = told_about(c)
    except Exception as exc:  # noqa: BLE001 — the claim reads without the line, and says the line is missing
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the departures citing a claim's answer could not be read", counter="record.claim_told")
        view["told"], view["told_note"] = [], "the departures ledger could not be read just now"
    return view


@router.get("/record/claims/{claim_id}/versions")
def get_record_claim_versions(claim_id: str) -> list[dict]:
    """Every version of the claim this id belongs to, newest first — the restatements with their
    text kept."""
    c = C.get(claim_id)
    if c is None or not _visible(c.about.key if c.about.kind == "connection" else ""):
        raise HTTPException(status_code=404, detail="No such claim")
    return [_claim_view(v) for v in C.versions(c.key)]


class SaidRequest(BaseModel):
    connection_id: str
    text: str = Field(min_length=1, max_length=600)   # what the person said, as they said it
    about: str = Field(default="", max_length=200)    # the analysis or finding it answers
    asked: str = Field(default="", max_length=600)    # the question it answers, as Home asked it
    by: str = ""                                      # ignored: the person signed in answers


@router.post("/record/claims/said", status_code=201)
def book_record_said(req: SaidRequest, principal=Depends(get_principal)) -> dict:
    """What a person told the platform, booked as theirs: kind and tier ``said``, dated, authored
    by the person — Home's "A question for you". One answer per person per item; answering again
    restates it, the earlier answer kept. Before this door a ``said`` claim came only from a filed
    Slack reply (CB-8); a sentence typed into the product had nowhere to go."""
    if not _visible(req.connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    who = _who(principal)
    if not who:  # only outside a request: the API binds who every request acts for
        raise HTTPException(status_code=422, detail="nobody is signed in to this request — a said claim is a person's")
    claim = C.Claim(kind="said", tier="said", author=who, author_kind="person",
                    about=C.About(kind="connection", key=req.connection_id),
                    statement=C.Statement(text=req.text.strip()),
                    as_of=_dt.date.today().isoformat(),
                    extra={"answers": req.asked.strip(), "about_ref": req.about.strip(), "surface": "home"})
    key = C.claim_key("said", req.connection_id, req.about.strip() or "-", who)
    try:
        cid = C.restate(key, claim, conn_id=req.connection_id) if C.latest(key) else \
            C.book(claim, key=key, conn_id=req.connection_id)
    except C.ClaimRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    booked = C.get(cid)
    return _claim_view(booked) if booked else {"id": cid}


@router.get("/record/you")
def read_record_you(by: str = "", principal=Depends(get_principal)) -> dict:
    """Between you and the platform: what became of the entries the person reading wrote — the
    one signed in (``by`` is ignored: a page reads its own reader's record, never a name it sends).
    Resolved here so a page never has to guess whether its reader is a `user:` or a `person:`."""
    who = _who(principal)
    if not who:
        return {"principal": "", "n": 0, "by_kind": {}, "restated": 0, "hypotheses": {},
                "predictions": {"scored": 0, "inside": 0, "coverage_observed": None, "by_method": []},
                "note": "nobody is signed in to this request, so there is no record to read"}
    from aughor.routers.ledger import read_principal_record
    return read_principal_record(who)


class MarkWrongRequest(BaseModel):
    corrected: str = ""            # what is true instead; a hypothesis needs only the reason
    why: str = ""
    by: str = ""                   # ignored: the person signed in marks it


@router.post("/record/claims/{claim_id}/wrong", status_code=201)
def mark_record_claim_wrong(claim_id: str, req: MarkWrongRequest, principal=Depends(get_principal)) -> dict:
    """A person marks a claim wrong, with the corrected statement. The claim is restated — the
    wrong version kept — every inquiry that established it wakes and every decision that relied
    on it reopens. Returns the new version with what it set in motion."""
    c = C.get(claim_id)
    if c is None or not _visible(c.about.key if c.about.kind == "connection" else ""):
        raise HTTPException(status_code=404, detail="No such claim")
    try:
        out = C.mark_wrong(claim_id, by=_who(principal), corrected=req.corrected, why=req.why)
    except C.ClaimRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**get_record_claim(out["claim_id"]), "superseded": out["superseded"],
            "woke_inquiries": out.get("woke_inquiries", []), "reopened_decisions": out.get("reopened_decisions", [])}


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
    decided_by: str = ""           # ignored: the person signed in declares it, and is recorded as deciding
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
    measured_by: str = ""          # ignored: the person signed in books it


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
    # what replaced the claim it stood on, when its ground moved and nobody has answered yet
    moved = C.get(d.reopened_by) if d.reopened_by else None
    view["reopened_by_claim"] = moved.model_dump() if moved is not None else None
    return view


@router.post("/record/decisions", status_code=201)
def declare_record_decision(req: DeclareDecisionRequest, principal=Depends(get_principal)) -> dict:
    """Declare a decision taken elsewhere, in its own words. The expectation, when given, is
    booked as a prediction claim at the same moment; the review date is proposed from the
    connection's settling lag when none is given."""
    from aughor.record.byproducts import declare_decision
    if req.connection_id and not _visible(req.connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    # The person declaring it. A typed `decided_by` used to WIN over the sign-in, so anyone could book a
    # decision in the CEO's name; who else stood behind it goes in `owner` / `approvers`, as named people.
    who = _who(principal)
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


class AmendDecisionRequest(BaseModel):
    option: str = ""               # an option that was on the table
    dissent: Optional[DissentIn] = None
    by: str = ""                   # ignored: the person signed in amends it


class StandsRequest(BaseModel):
    why: str
    by: str = ""                   # ignored: the person signed in answers it


@router.post("/record/decisions/{decision_id}/amend", status_code=201)
def amend_record_decision(decision_id: str, req: AmendDecisionRequest, principal=Depends(get_principal)) -> dict:
    """Add an option or a dissent to a decision already booked — a new version, the addition dated
    and named. What was chosen does not change here."""
    d = D.get_decision(decision_id)
    if d is None or not _visible(d.connection_id):
        raise HTTPException(status_code=404, detail="No such decision")
    try:
        amended = D.amend_decision(decision_id, by=_who(principal), option=req.option,
                                   dissent_who=req.dissent.who if req.dissent else "",
                                   dissent_why=req.dissent.why if req.dissent else "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return get_record_decision(amended.id)


@router.post("/record/decisions/{decision_id}/stands", status_code=201)
def settle_record_decision_reopening(decision_id: str, req: StandsRequest, principal=Depends(get_principal)) -> dict:
    """A person answers a reopened decision: it stands on what replaced the claim, and why."""
    d = D.get_decision(decision_id)
    if d is None or not _visible(d.connection_id):
        raise HTTPException(status_code=404, detail="No such decision")
    try:
        settled = D.settle_reopening(decision_id, by=_who(principal), why=req.why)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return get_record_decision(settled.id)


# ── inquiries ──────────────────────────────────────────────────────────────────────────────

class CloseInquiryRequest(BaseModel):
    closed_as: str                 # answered | overtaken | abandoned
    lessons: list[dict] = Field(default_factory=list)   # [{believed, turned_out}]


def _as_it_stands(ids: list[str]) -> list[tuple[str, C.Claim]]:
    """Each cited claim as it stands NOW — the latest version under its key — once per claim, in
    the order cited, with the id it was cited by. A record cites a claim as it was recorded; a
    page that reads the record shows what is held today and says when that has changed."""
    seen: set[str] = set()
    out: list[tuple[str, C.Claim]] = []
    for cid in ids:
        cited = C.get(cid)
        if cited is None:
            continue
        current = C.latest(cited.key) or cited
        if current.key in seen:
            continue
        seen.add(current.key)
        out.append((cid, current))
    return out


def _inquiry_view(q) -> dict:
    from aughor.record.inquiry import run_verdict
    view = q.model_dump()
    view["hypothesis_claims"] = [_claim_view(c) for _, c in _as_it_stands(q.hypotheses)]
    view["established_claims"] = [{**_claim_view(c), "cited_as": cid, "restated_since": c.id != cid}
                                  for cid, c in _as_it_stands(q.claims)]
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
    from aughor.record.inquiry import get_inquiry, keep_proposed_run
    q = get_inquiry(inquiry_id)
    if q is None or not _visible(q.connection_id):
        raise HTTPException(status_code=404, detail="No such inquiry")
    return _inquiry_view(keep_proposed_run(q))


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


class HypothesisRequest(BaseModel):
    text: str
    by: str = ""                   # ignored: the person signed in names it


class HandToRequest(BaseModel):
    owner: str = ""                # "" takes the name off
    by: str = ""                   # ignored: the person signed in hands it over


class NextCheckRequest(BaseModel):
    on: str = ""                   # ISO day; "" clears it
    waiting_for: str = ""
    by: str = ""                   # ignored: the person signed in sets it


def _inquiry_or_404(inquiry_id: str):
    from aughor.record.inquiry import get_inquiry
    q = get_inquiry(inquiry_id)
    if q is None or not _visible(q.connection_id):
        raise HTTPException(status_code=404, detail="No such inquiry")
    return q


@router.post("/record/inquiries/{inquiry_id}/hypothesis", status_code=201)
def add_record_inquiry_hypothesis(inquiry_id: str, req: HypothesisRequest, principal=Depends(get_principal)) -> dict:
    """A person's hypothesis, named — booked as a claim at tier ``said``, open until a run tests
    it. When the Record already holds one like it as refuted on this connection, the answer says
    which, beside it."""
    from aughor.record.inquiry import InquiryRefused, add_hypothesis
    q = _inquiry_or_404(inquiry_id)
    try:
        booked, note = add_hypothesis(q, text=req.text, by=_who(principal))
    except (InquiryRefused, C.ClaimRefused) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**_inquiry_view(booked), "resembles_refuted": note or None}


@router.post("/record/inquiries/{inquiry_id}/owner")
def hand_record_inquiry(inquiry_id: str, req: HandToRequest, principal=Depends(get_principal)) -> dict:
    """Name the person answerable for an inquiry, or take the name off. Nothing is sent."""
    from aughor.record.inquiry import InquiryRefused, hand_to
    q = _inquiry_or_404(inquiry_id)
    owner = _named(req.owner)
    try:
        return _inquiry_view(hand_to(q, owner=owner, by=_who(principal)))
    except InquiryRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/record/inquiries/{inquiry_id}/next-check")
def set_record_inquiry_next_check(inquiry_id: str, req: NextCheckRequest, principal=Depends(get_principal)) -> dict:
    """Set the day an inquiry wakes without being asked, or clear it."""
    from aughor.record.inquiry import InquiryRefused, set_next_check
    q = _inquiry_or_404(inquiry_id)
    try:
        return _inquiry_view(set_next_check(q, on=req.on, by=_who(principal), waiting_for=req.waiting_for))
    except InquiryRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── scenarios and calibration ──────────────────────────────────────────────────────────────

class AssumptionIn(BaseModel):
    variable: str
    value: Optional[float] = None
    by: str = ""                   # ignored: an assumption is the signed-in person's who states it
    text: str = ""
    unit: str = ""
    low: Optional[float] = None
    high: Optional[float] = None


class ScenarioRequest(BaseModel):
    method: str                                  # identity | declared | history | intervention
    metric: str
    settles_on: str = ""                         # defaults to the decision's review date
    direction: str = ""
    unit: str = ""
    formula: str = ""                            # identity
    inputs: dict[str, float] = Field(default_factory=dict)
    varied: list[str] = Field(default_factory=list)
    assumption: Optional[AssumptionIn] = None    # declared
    spec: Optional[dict] = None                  # history: the measurable definition; resolved from the governed metric when absent
    like: str = ""                               # intervention: the question past decisions asked; defaults to this decision's
    action_id: str = ""                          # intervention: the declared action past decisions ran
    limits: list[str] = Field(default_factory=list)
    question: str = ""
    by: str = ""                                 # ignored: the person signed in projects


@router.post("/record/decisions/{decision_id}/scenario", status_code=201)
def book_record_scenario(decision_id: str, req: ScenarioRequest, principal=Depends(get_principal)) -> dict:
    """Project under one method of the ladder (identity · declared · history · intervention) FOR a
    decision, and book the prediction with its method, band and what it must say; the scenario is
    a ledger entry inside the decision. A method the ladder does not have is refused by name, and
    one that projects nothing — too few past cases, a metric with no measurable definition — is
    refused with that reason."""
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
            proj = S.declared(variable=a.variable, value=a.value, by=who, text=a.text, unit=a.unit or req.unit,
                              connection_id=d.connection_id, low=a.low, high=a.high)
        elif req.method == "history":
            spec = req.spec or _metric_spec(req.metric, d.connection_id)
            if not spec:
                raise HTTPException(status_code=422, detail=(
                    f"the history method reads the metric's own past, and {req.metric!r} has no approved definition "
                    "that can be measured on this connection — approve one under Definitions, or use another method"))
            from aughor.db.measure import run_sql_for
            proj = S.history(spec, run_sql_for(d.connection_id, internal=True))
            req.spec = spec
        elif req.method == "intervention":
            proj = S.intervention(metric=req.metric, connection_id=d.connection_id, action_id=req.action_id,
                                  like=req.like or d.question, unit=req.unit)
        else:
            raise HTTPException(status_code=422, detail=f"no method named {req.method!r}; the ladder has {', '.join(S.METHODS)}")
        settles_on = req.settles_on or d.review_on
        pid = S.predict(metric=req.metric, projection=proj, settles_on=settles_on, author=who or "unidentified",
                        connection_id=d.connection_id, direction=req.direction, spec=req.spec, for_ref=decision_id)
    except (S.FormulaRefused, C.ClaimRefused, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    assumptions = [S.Assumption(variable=req.assumption.variable, value=req.assumption.value, by=who,
                                text=req.assumption.text, claim=proj.claim)] if req.assumption else []
    scenario = S.book_scenario(S.Scenario(for_kind="decision", for_id=decision_id, question=req.question,
                                          assumptions=assumptions, predictions=[pid], limits=req.limits,
                                          methods=[req.method], connection_id=d.connection_id))
    return {"scenario": scenario.model_dump(), "projection": proj.model_dump(),
            "prediction": (C.get(pid).model_dump() if C.get(pid) else None)}


def _metric_spec(metric: str, connection_id: str) -> Optional[dict]:
    from aughor.record.mission import spec_for_metric
    return spec_for_metric(metric, connection_id)


@router.get("/record/decisions/{decision_id}/cases")
def list_record_decision_cases(decision_id: str, metric: str = "") -> dict:
    """What the intervention method would read for this decision: the past decisions on this
    install that asked the same question, each with its measured effect — and how many are the
    least an effect is read from. A read: nothing is projected or booked."""
    from aughor.record import scenario as S
    d = D.get_decision(decision_id)
    if d is None or not _visible(d.connection_id):
        raise HTTPException(status_code=404, detail="No such decision")
    cases = [c for c in S.intervention_cases(metric=metric, connection_id=d.connection_id, like=d.question)
             if c["decision"] != d.id]
    return {"cases": cases, "needed": S.INTERVENTION_MIN_CASES,
            "measurable": bool(_metric_spec(metric, d.connection_id)) if metric else None}


@router.get("/record/decisions/{decision_id}/scenarios")
def list_record_scenarios(decision_id: str) -> dict:
    """The scenarios booked FOR a decision, oldest first, with the predictions made under them as
    they stand now — so a scored prediction reads as scored. A read: nothing is projected here."""
    from aughor.record import scenario as S
    d = D.get_decision(decision_id)
    if d is None or not _visible(d.connection_id):
        raise HTTPException(status_code=404, detail="No such decision")
    # booked FOR the decision as it stood then; an outcome, an amendment or a reopening has since
    # given it a new version, and the scenarios are still its own
    found = {s.id: s for vid in (D.version_ids(decision_id) or [decision_id]) for s in S.scenarios_for(vid)}
    scenarios = sorted(found.values(), key=lambda s: s.recorded_at)
    wanted = [pid for s in scenarios for pid in s.predictions]
    if d.expectation_claim:
        wanted.append(d.expectation_claim)
    predictions: list[dict] = []
    for pid in dict.fromkeys(wanted):
        first = C.get(pid)
        current = (C.latest(first.key) or first) if first is not None else None
        if current is not None:
            predictions.append({**_claim_view(current), "booked_as": pid})
    return {"scenarios": [s.model_dump() for s in scenarios], "predictions": predictions}


@router.get("/record/calibration")
def record_calibration(connection_id: Optional[str] = None) -> list[dict]:
    """Interval coverage by method, metric and author over scored predictions — counted."""
    from aughor.record.scenario import calibration
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    return calibration(conn_id=connection_id)


# ── set aside: "not now" on what waits on a person (the Now page) ──────────────────────────

class SetAsideRequest(BaseModel):
    kind: str                      # decision | inquiry | departure | approval
    ref: str                       # the item's id as the page holds it
    until: str                     # ISO day it returns on
    why: str
    title: str = ""                # the row as it reads, kept so the list can say what was set aside
    by: str = ""                   # ignored: the person signed in sets it aside


class RestoreRequest(BaseModel):
    kind: str
    ref: str                       # the stable name the listing gives
    by: str = ""                   # ignored: the person signed in restores it


def _set_aside_view(s: dict) -> bool:
    return _visible(str(s.get("connection_id") or ""))


@router.get("/record/set-aside")
def list_record_set_aside() -> dict:
    """What a person set aside on Now: ``active`` items are off the list until their day;
    ``returned`` ones are back — their day came, or the record behind them changed — with why."""
    from aughor.record.set_aside import listing
    out = listing()
    return {**out, "active": [s for s in out["active"] if _set_aside_view(s)],
            "returned": [s for s in out["returned"] if _set_aside_view(s)]}


@router.post("/record/set-aside", status_code=201)
def set_record_item_aside(req: SetAsideRequest, principal=Depends(get_principal)) -> dict:
    """Set one waiting item aside until a day, with why. Nothing about the item itself is written:
    a review set aside is still due on its own page."""
    from aughor.record.set_aside import ITEM_KINDS, SetAsideRefused, record_of, set_aside
    # a caller may only set aside what they can see — checked before anything is written
    there = record_of(req.kind, req.ref) if req.kind in ITEM_KINDS else None
    if there is not None and not _visible(there["connection_id"]):
        raise HTTPException(status_code=404, detail="No such item")
    try:
        return set_aside(item_kind=req.kind, ref=req.ref, until=req.until, why=req.why, title=req.title,
                         by=_who(principal)).model_dump()
    except SetAsideRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/record/set-aside/restore")
def restore_record_item(req: RestoreRequest, principal=Depends(get_principal)) -> dict:
    """Bring a set-aside item back before its day."""
    from aughor.record.set_aside import SetAsideRefused, restore
    try:
        return restore(item_kind=req.kind, ref=req.ref, by=_who(principal)).model_dump()
    except SetAsideRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── the week by duty (Operations) ──────────────────────────────────────────────────────────

@router.get("/record/duties")
def record_duties(connection_id: Optional[str] = None, since: str = "") -> dict:
    """What each of the seven duties booked since a moment (default: this week's Monday), how much
    of it is warranted, how its runs ended by type and what a warranted entry cost — a fold over
    the ledger, with what is not attributed said."""
    from aughor.record.duties import week_by_duty
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    return week_by_duty(since=since, conn_id=connection_id)


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
    written_by: str = ""           # ignored: the person signed in writes it


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


@router.get("/record/missions/{mission_id}/reports/{report_id}")
def get_record_mission_past_report(mission_id: str, report_id: str) -> dict:
    """One booked report of this mission, in full, as it was written on its day."""
    from aughor.record import mission as M
    m = M.get_mission(mission_id)
    if m is None or not all(_visible(c) for c in m.scope.connections):
        raise HTTPException(status_code=404, detail="No such mission")
    current = M.latest(m.key) or m
    report = M.get_report(report_id) if report_id in current.review.reports else None
    if report is None:
        raise HTTPException(status_code=404, detail="No such report of this mission")
    return {"booked": True, "report": report}


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
