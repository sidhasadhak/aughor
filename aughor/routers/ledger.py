"""The ledger API — the published contract for outside agents and other tools (the 2027 study §Q;
phase 7, P7-1 to P7-5). Under ``/ledger/v1``:

- the contract (`kernel/contract.py`) and the event catalogue (`kernel/events.py`);
- post a claim with its warrant — the one door, where the claims' laws are enforced and an outside
  author's claim is refused without a warrant at all; read claims as recorded on a date; what was
  restated since a cursor; subscriptions to events out;
- the journal by kind from a cursor; the ledger exported as JSON lines, so adopting is not a trap;
- a principal's track record — what became of its entries;
- the method interface (`record/methods.py`); aggregate priors (`packs/aggregates.py`);
- service principals, minted by a person.

Visibility is the Record's own rule: a connection-scoped entry is visible when the connection is in
the caller's organisation. A service principal is held to the organisation's agent policy by the
app-wide gate (`rbac/agent_gate.py`); its route levels are declared in `mcp/policy.ROUTE_LEVELS`.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from aughor.record import claims as C
from aughor.security.authz import connection_owner_guard, get_principal

# Router-level (DATA-06): a connection a request names must be the caller's, on every door here.
router = APIRouter(prefix="/ledger/v1", tags=["ledger"], dependencies=[Depends(connection_owner_guard)])

#: What the export carries by default — every kind the Record writes.
EXPORT_KINDS: tuple[str, ...] = ("claim", "decision", "outcome", "inquiry", "run_verdict", "scenario", "action",
                                 "authority_graduation", "authority_demotion", "authority_l5", "authority_ceiling",
                                 "mission", "mission_report", "missed_move", "method", "ledger_subscription", "set_aside",
                                 "briefing_delivery")


def _visible(conn_id: str) -> bool:
    from aughor.security.authz import org_visible_conn_ids
    visible = org_visible_conn_ids()
    return visible is None or not conn_id or conn_id in visible


def _author(principal) -> tuple[str, str]:
    """``(author, author_kind)``: a service principal is an agent under its own name; a person is a
    person; with identity off, the person the request acts for (`authz.acting_person`). The body's
    ``author`` used to stand in there, as an agent — so any client could post under any name."""
    from aughor.security.authz import acting_person
    from aughor.security.service_principals import is_service
    if principal is not None and is_service(principal):
        return str(principal.user_id), "agent"
    for attr in ("user_id", "email", "id", "sub", "name"):
        v = getattr(principal, attr, "") if principal is not None else ""
        if v:
            v = str(v)
            return (v if ":" in v else f"user:{v}"), "person"
    who = acting_person(None)
    return (who, "person") if who else ("unidentified", "agent")


# ── the contract and the catalogue ─────────────────────────────────────────────────────────

@router.get("/contract")
def read_contract() -> dict:
    """The agent contract, as the code enforces it."""
    from aughor.kernel.contract import contract
    return contract()


@router.get("/events/catalogue")
def read_event_catalogue() -> dict:
    from aughor.kernel.events import SUBSCRIBABLE, catalogue
    return {"kinds": catalogue(), "subscribable": list(SUBSCRIBABLE)}


@router.get("/events")
def read_events(kind: Optional[str] = None, since_seq: Optional[int] = None, connection_id: Optional[str] = None,
                limit: int = 200) -> dict:
    """The journal, newest first, by kind from a cursor — the pull side of events out."""
    from aughor.kernel.events import is_catalogued
    from aughor.kernel.ledger import Ledger
    from aughor.org.context import current_org_id
    if kind and not is_catalogued(kind):
        raise HTTPException(status_code=422, detail=f"no event kind named {kind!r}; read /ledger/v1/events/catalogue")
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    rows = Ledger.default().events(kind=kind, conn_id=connection_id, since_seq=since_seq, org_id=current_org_id(),
                                   limit=max(1, min(int(limit), 1000)))
    rows = [r for r in rows if _visible(str(r.get("conn_id") or ""))]
    return {"events": rows, "cursor": max((int(r["seq"]) for r in rows), default=since_seq or 0)}


# ── claims ─────────────────────────────────────────────────────────────────────────────────

class AboutIn(BaseModel):
    kind: str = "connection"
    key: str = ""


class StatementIn(BaseModel):
    text: str
    metric: str = ""
    value: Optional[float] = None
    unit: str = ""
    range_start: str = ""
    range_end: str = ""
    object_set: str = ""


class WarrantIn(BaseModel):
    kind: str
    ref: str
    detail: str = ""
    reproducible: Optional[bool] = None
    why_not: str = ""


class ClaimIn(BaseModel):
    kind: str
    statement: StatementIn
    tier: str = "said"
    about: AboutIn = Field(default_factory=AboutIn)
    status: str = "Provisional"
    as_of: str = ""
    valid_from: str = ""
    valid_until: str = ""
    warrants: list[WarrantIn] = Field(default_factory=list)
    falsifier: str = ""
    next_check: str = ""
    owner: str = ""
    definition_version: str = ""
    state: str = ""
    natural_key: str = ""          # to restate the same claim later; the author's own
    author: str = ""               # ignored: the author is the principal, else who the request acts for
    extra: dict[str, Any] = Field(default_factory=dict)


def _claim_view(c: C.Claim) -> dict:
    from aughor.record.confidence import why_uncounted, with_confidence
    seen = with_confidence(c)
    view = seen.model_dump()
    if seen.confidence is None:
        view["confidence_note"] = why_uncounted(c)
    return view


@router.post("/claims", status_code=201)
def post_claim(req: ClaimIn, principal=Depends(get_principal)) -> dict:
    """Post a claim with its warrant. The claims' three laws are enforced at the door, plus the
    API's own: a claim that names no warrant at all is refused. The author is the principal; a
    natural key is the author's own and cannot restate another author's claim."""
    from aughor.kernel.contract import API_LAW
    from aughor.security.service_principals import allowed_connection, is_service
    author, author_kind = _author(principal)
    if not req.warrants:
        raise HTTPException(status_code=422, detail={"code": "CLAIM_REFUSED", "why": API_LAW})
    conn = req.about.key if req.about.kind == "connection" else ""
    if conn and not _visible(conn):
        raise HTTPException(status_code=404, detail="No such connection")
    if conn and principal is not None and is_service(principal) and not allowed_connection(author.split(":", 1)[1], conn):
        raise HTTPException(status_code=403, detail={"code": "AGENT_CONNECTION_DENIED",
                                                    "why": f"{author} was minted without {conn!r} among its connections"})
    key = C.claim_key("api", author, req.natural_key or uuid.uuid4().hex[:12])
    prior = C.latest(key)
    if prior is not None and prior.author != author:
        raise HTTPException(status_code=403, detail={"code": "CLAIM_REFUSED", "why": "a natural key restates its own author's claim only"})
    try:
        claim = C.Claim(kind=req.kind, about=C.About(kind=req.about.kind, key=req.about.key),
                        statement=C.Statement(**req.statement.model_dump()), tier=req.tier, status=req.status,
                        as_of=req.as_of or _today(), valid_from=req.valid_from, valid_until=req.valid_until,
                        warrants=[C.Warrant(**w.model_dump()) for w in req.warrants], falsifier=req.falsifier,
                        next_check=req.next_check, owner=req.owner, author=author, author_kind=author_kind,
                        definition_version=req.definition_version, state=req.state,
                        extra={**req.extra, "posted_via": "ledger_api"})
        cid = C.book(claim, key=key, conn_id=conn or None)
    except (C.ClaimRefused, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "CLAIM_REFUSED", "why": str(exc)})
    view = _claim_view(C.get(cid))
    view["restated"] = prior is not None
    return view


def _today() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


@router.get("/claims")
def read_claims(kind: Optional[str] = None, connection_id: Optional[str] = None, author: Optional[str] = None,
                state: Optional[str] = None, as_of: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Claims as they stand, or — with ``as_of`` — as they stood on that day."""
    filters: dict[str, Any] = dict(kind=kind, conn_id=connection_id, state=state, limit=max(1, min(int(limit), 1000)))
    try:
        rows = C.as_recorded(as_of, **filters) if as_of else C.list_claims(**filters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if author:
        rows = [c for c in rows if c.author == author]
    return [_claim_view(c) for c in rows if _visible(c.about.key if c.about.kind == "connection" else "")]


@router.get("/claims/{claim_id}")
def read_claim(claim_id: str) -> dict:
    c = C.get(claim_id)
    if c is None or not _visible(c.about.key if c.about.kind == "connection" else ""):
        raise HTTPException(status_code=404, detail="No such claim")
    view = _claim_view(c)
    view["relied_on_by"] = C.relied_on_by(claim_id)
    return view


@router.get("/claims/{claim_id}/versions")
def read_claim_versions(claim_id: str) -> list[dict]:
    c = C.get(claim_id)
    if c is None or not _visible(c.about.key if c.about.kind == "connection" else ""):
        raise HTTPException(status_code=404, detail="No such claim")
    return [_claim_view(v) for v in C.versions(c.key)]


@router.get("/restatements")
def read_restatements(since: str = "", connection_id: Optional[str] = None, limit: int = 200) -> dict:
    """Every claim restated since ``since`` (an ISO moment), oldest first, with what it replaced —
    the pull side of a subscription, and the cursor a tool that missed a delivery reads from."""
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    cutoff = C._as_dt(since) if since else None
    if since and cutoff is None:
        raise HTTPException(status_code=422, detail=f"unreadable moment {since!r}")
    rows = []
    for c in C.list_claims(conn_id=connection_id, limit=max(limit * 4, 400)):
        if not c.supersedes or not _visible(c.about.key if c.about.kind == "connection" else ""):
            continue
        at = C._as_dt(c.recorded_at)
        if cutoff is not None and (at is None or at <= cutoff):
            continue
        prior = C.get(c.supersedes)
        rows.append({"claim": _claim_view(c), "replaced": prior.statement.text if prior else "", "supersedes": c.supersedes,
                     "recorded_at": c.recorded_at})
    rows.sort(key=lambda r: r["recorded_at"])
    rows = rows[:max(1, min(int(limit), 1000))]
    return {"restatements": rows, "cursor": rows[-1]["recorded_at"] if rows else (since or "")}


# ── subscriptions ──────────────────────────────────────────────────────────────────────────

class SubscriptionIn(BaseModel):
    url: str
    kinds: list[str]
    connection_id: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    note: str = ""


@router.post("/subscriptions", status_code=201)
def post_subscription(req: SubscriptionIn, principal=Depends(get_principal)) -> dict:
    from aughor.record import subscriptions as S
    if req.connection_id and not _visible(req.connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    who, _ = _author(principal)
    try:
        return S.public(S.subscribe(url=req.url, kinds=req.kinds, by=who, connection_id=req.connection_id,
                                    headers=req.headers, note=req.note))
    except S.SubscriptionRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/subscriptions")
def read_subscriptions(active: bool = True) -> dict:
    from aughor.record import subscriptions as S
    rows = [S.public(s) for s in S.list_subscriptions(active_only=active) if _visible(s.connection_id)]
    return {"subscriptions": rows}


@router.delete("/subscriptions/{subscription_id}")
def delete_subscription(subscription_id: str, principal=Depends(get_principal)) -> dict:
    """Withdraw a subscription — restated inactive, never deleted."""
    from aughor.record import subscriptions as S
    who, _ = _author(principal)
    try:
        return S.public(S.withdraw(subscription_id, by=who))
    except S.SubscriptionRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── export ─────────────────────────────────────────────────────────────────────────────────

def export_lines(kinds: list[str], connection_id: Optional[str], limit: int):
    from aughor.kernel.ledger import Ledger
    for art in Ledger.default().artifacts_of_kind(kinds, conn_id=connection_id, limit=limit):
        if not _visible(str(art.get("conn_id") or "")):
            continue
        row = {k: art.get(k) for k in ("kind", "id", "natural_key", "version", "created_at", "conn_id", "superseded_by")}
        row["payload"] = art.get("payload")
        yield json.dumps(row, default=str) + "\n"


@router.get("/export")
def export_ledger(kinds: Optional[str] = None, connection_id: Optional[str] = None, limit: int = 20000):
    """The ledger as JSON lines — every current entry of the kinds asked (default: every kind the
    Record writes), so adopting the platform is not a trap."""
    if connection_id and not _visible(connection_id):
        raise HTTPException(status_code=404, detail="No such connection")
    wanted = [k.strip() for k in (kinds or "").split(",") if k.strip()] or list(EXPORT_KINDS)
    return StreamingResponse(export_lines(wanted, connection_id, max(1, min(int(limit), 200000))),
                             media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=aughor-ledger.jsonl"})


# ── a principal's record ───────────────────────────────────────────────────────────────────

@router.get("/principals/{principal}/record")
def read_principal_record(principal: str) -> dict:
    """What became of a principal's entries — a count, never an opinion: claims by kind, how many
    were restated, hypotheses by state, predictions scored and inside their band."""
    from aughor.record.scenario import calibration
    mine = [c for c in C.list_claims(limit=5000) if c.author == principal and _visible(c.about.key if c.about.kind == "connection" else "")]
    by_kind: dict[str, int] = {}
    hyps: dict[str, int] = {}
    restated = 0
    for c in mine:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        restated += c.version > 1
        if c.kind == "hypothesis":
            hyps[c.state or "open"] = hyps.get(c.state or "open", 0) + 1
    preds = [g for g in calibration() if g["author"] == principal]
    n_pred = sum(g["n"] for g in preds)
    inside = sum(g["inside"] for g in preds)
    return {"principal": principal, "n": len(mine), "by_kind": by_kind, "restated": restated,
            "hypotheses": hyps, "predictions": {"scored": n_pred, "inside": inside,
                                                 "coverage_observed": round(inside / n_pred, 3) if n_pred else None,
                                                 "by_method": preds},
            "note": ("no entries by this principal" if not mine else
                     "counts of what became of its entries; a hit rate is shown by its reference class on each claim")}


# ── service principals ─────────────────────────────────────────────────────────────────────

class ServicePrincipalIn(BaseModel):
    name: str
    note: str = ""
    connections: list[str] = Field(default_factory=list)


@router.post("/principals/service", status_code=201)
def mint_service_principal(req: ServicePrincipalIn, principal=Depends(get_principal)) -> dict:
    """A person mints a service principal; the key is in this response and nowhere else."""
    from aughor.org.context import current_org_id
    from aughor.security import service_principals as SP
    who, kind = _author(principal)
    if kind != "person" and principal is not None:
        raise HTTPException(status_code=403, detail="a person mints a service principal; an agent or a service cannot")
    for c in req.connections:
        if not _visible(c):
            raise HTTPException(status_code=404, detail=f"No such connection {c!r}")
    try:
        record, key = SP.mint(req.name, org_id=current_org_id(), by=who, note=req.note, connections=req.connections)
    except SP.ServicePrincipalRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**record, "key": key, "present_as": {SP.NAME_HEADER: req.name, SP.KEY_HEADER: "the key — shown once"}}


@router.get("/principals/service")
def list_service_principals() -> dict:
    from aughor.org.context import current_org_id
    from aughor.security import service_principals as SP
    return {"principals": SP.list_principals(org_id=current_org_id())}


@router.delete("/principals/service/{name}")
def revoke_service_principal(name: str, why: str = "", principal=Depends(get_principal)) -> dict:
    from aughor.security import service_principals as SP
    who, kind = _author(principal)
    if kind != "person" and principal is not None:
        raise HTTPException(status_code=403, detail="a person revokes a service principal")
    try:
        return SP.revoke(name, by=who, why=why)
    except SP.ServicePrincipalRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── the method interface ───────────────────────────────────────────────────────────────────

class BacktestIn(BaseModel):
    n: int = 0
    metric: str = ""
    mae: Optional[float] = None
    mape: Optional[float] = None
    coverage_stated: Optional[float] = None
    coverage_observed: Optional[float] = None
    measured_on: list[str] = Field(default_factory=list)
    note: str = ""


class AdapterIn(BaseModel):
    kind: str = "mcp"
    server_id: str
    tool: str


class MethodIn(BaseModel):
    name: str
    kind: str
    backtest: BacktestIn
    adapter: AdapterIn
    tier: str = "mined"
    inputs: list[str] = Field(default_factory=list)
    note: str = ""


@router.get("/methods")
def read_methods(active: bool = True) -> dict:
    from aughor.record import methods as M
    from aughor.record.scenario import METHODS
    return {"builtin": list(METHODS), "registered": [m.model_dump() for m in M.list_methods(active_only=active)],
            "rule": "a registered method carries its backtest and runs as a foreign MCP tool; nothing runs inside the process"}


@router.post("/methods", status_code=201)
def register_method(req: MethodIn, principal=Depends(get_principal)) -> dict:
    from aughor.record import methods as M
    who, _ = _author(principal)
    try:
        m = M.register(M.Method(name=req.name, kind=req.kind, backtest=M.Backtest(**req.backtest.model_dump()),
                                adapter=M.Adapter(**req.adapter.model_dump()), tier=req.tier, inputs=req.inputs, note=req.note), by=who)
    except M.MethodRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return m.model_dump()


@router.delete("/methods/{name}")
def withdraw_method(name: str, principal=Depends(get_principal)) -> dict:
    from aughor.record import methods as M
    who, _ = _author(principal)
    try:
        return M.withdraw(name, by=who).model_dump()
    except M.MethodRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── aggregate priors ───────────────────────────────────────────────────────────────────────

@router.get("/aggregates")
def read_aggregates() -> dict:
    """This install's aggregate, computed locally — readable here whether or not sharing is on."""
    from aughor.packs import aggregates as AG
    return {**AG.compute(), "sharing": AG.sharing_enabled(), "flag": AG.FLAG}


@router.post("/aggregates/export")
def export_aggregates() -> dict:
    """The document that may leave — refused until a person turned sharing on."""
    from aughor.packs import aggregates as AG
    try:
        return AG.export()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
