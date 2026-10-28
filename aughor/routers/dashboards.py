"""A person's dashboards in the Briefing — list, read, start, keep, go back, retire, draft, move
(Arc CT, CT-7 to CT-10; ROADMAP §3.50).

**One route calls a model** — ``POST /cockpits/draft``, when a person names an area and asks for
a draft. Every other route reads what was kept, or keeps what a person wrote, and calls none.

A dashboard is the asker's own (``aughor/dashboards/home.py``): the person comes from the request,
never from a parameter, so no route here can read or change someone else's. Every connection a
route names is checked by the router's guard, which is why the connection is a query parameter
on every route, the writes included.

Every write goes through ``aughor.dashboards.versions``, so it goes through the validator and is
kept with the person's name. A refusal is an HTTP error that carries the validator's own
sentences; it is never a 200 with nothing kept.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from aughor.security.authz import connection_owner_guard

router = APIRouter(tags=["cockpit"], dependencies=[Depends(connection_owner_guard)])

#: What a kept-or-not outcome is to a caller over HTTP.
_STATUS_CODE = {"refused": 422, "not_checked": 503, "failed": 500}


class KeepRequest(BaseModel):
    spec: Any
    note: str = ""
    #: Arc OC-4 — pin a dashboard holding pieces to the ontology release in force now, the spec unchanged or not.
    repin: bool = False


class RestoreRequest(BaseModel):
    version: int


class RetireRequest(BaseModel):
    note: str = ""


class DraftRequest(BaseModel):
    area: str
    schema_name: Optional[str] = None


class MoveRequest(BaseModel):
    canvas_id: str


class QueryRequest(BaseModel):
    """Arc AP-7 — a person's own query, how it is shown, and — when it changes a card of theirs — the card it replaces."""
    sql: str
    shown: dict[str, Any] = {}
    title: str = ""
    replaces: str = ""
    #: Arc AP-8 — the dashboard's values the query reads as ``{{name}}``, as the page holds them now: name →
    #: ``{"kind", "value"}``. Each is bound by the engine, never pasted into the statement.
    values: dict[str, dict[str, Any]] = {}


class AskRequest(BaseModel):
    words: str
    schema_name: Optional[str] = None


class PublishRequest(BaseModel):
    """Who the dashboard is published to: groups and roles, each by kind and id or name."""
    to: list[dict[str, Any]]


class QuestionKeepRequest(BaseModel):
    """A question kept on a dashboard (PENDING 54): its words, how often it is asked, and the Data Canvas answer it
    starts from, when it is kept from one."""
    question: str
    rhythm: str = "weekly"
    schema_name: Optional[str] = None
    first_run: str = ""


class QuestionRhythmRequest(BaseModel):
    rhythm: str


def _home(request: Request, connection_id: str, cockpit_id: str):
    from aughor.dashboards.home import Home, person_of, valid_id
    if not connection_id:
        raise HTTPException(status_code=422, detail="connection_id is required")
    if not valid_id(cockpit_id):
        raise HTTPException(status_code=404, detail="No such dashboard")
    return Home(connection_id, person_of(request), cockpit_id)


def _approved_by(request: Request) -> str:
    """Who approves a version: the person signed in, else the one this request acts for. It was the
    home's owner, which without a sign-in is nobody in particular and wrote the bare word "person"."""
    from aughor.security.authz import acting_person, caller, get_principal
    return acting_person(get_principal(request)) or f"user:{caller()}"


def _answer(kept, **more) -> dict:
    code = _STATUS_CODE.get(kept.status)
    if code:
        raise HTTPException(status_code=code, detail=kept.as_dict())
    return {**kept.as_dict(), **more}


def _day(value: Optional[str], what: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{what} is an ISO day, e.g. 2026-08-17")


def _as_read(card, connection_id: str) -> dict:
    """A card as a dashboard draws it: the card, whose it is, the record it was made from, and —
    for a card made from a metric — the metric's unit and the range that unit states, read by
    the same reader the Briefing's figures are (`business_profile/validate.stated_range`)."""
    from aughor.business_profile.validate import stated_range
    from aughor.dashboards import cards
    from aughor.dashboards.propose import made_from
    from aughor.semantic.metrics import get_metric

    made = made_from(card)
    out = {**card.model_dump(), "own": card.scope == cards.OWN, "made_from": made[0] if made else "",
           "unit": "", "stated_range": None}
    if made and made[0] == "metric":
        metric = get_metric(made[1], connection_id=connection_id)
        unit = str(getattr(metric, "unit", "") or "")
        if unit:
            kind, lo, hi = stated_range(unit)
            out.update(unit=unit, stated_range={"kind": kind, "lo": lo, "hi": hi})
    return out


def _layout_order(connection_id: str, owner: str) -> list[str]:
    """The card ids in the order the person arranged them in the Briefing before dashboards had
    names: top to bottom, then left to right."""
    from aughor.cards.store import get_layout
    layout = get_layout(connection_id, owner) or {}
    placed = [(float((v or {}).get("y", 0) or 0), float((v or {}).get("x", 0) or 0), k)
              for k, v in layout.items() if isinstance(v, dict)]
    return [k for _, _, k in sorted(placed)]


@router.get("/dashboards")
def list_dashboards(request: Request, connection_id: str) -> dict:
    """The asker's dashboards on this connection, the cards they may place, and the canvas
    dashboards waiting to be moved here. No model call, and nothing is written."""
    from aughor.dashboards import cards, versions
    from aughor.dashboards.home import FIRST, Home, person_of
    owner = person_of(request)
    home = Home(connection_id, owner, FIRST)
    return {
        "person": owner,
        "cockpits": versions.of_person(connection_id, owner),
        "shared_cards": len(cards.shared(connection_id)),
        "own_cards": len(cards.own(home)),
        "from_canvases": versions.canvas_dashboards(connection_id),
    }


@router.get("/dashboards/audiences")
def audiences(request: Request, connection_id: str) -> dict:
    """The groups the asker belongs to and the roles they hold: who they may publish a dashboard to
    (the canvas, B5). Declared before the dashboard-by-id read, which would take the word for an id."""
    from aughor.dashboards import sharing
    from aughor.dashboards.home import person_of
    return sharing.audience_of(person_of(request))


@router.get("/dashboards/shared")
def shared_dashboards(request: Request, connection_id: str) -> dict:
    """The dashboards others published to a group the asker is in or a role they hold."""
    from aughor.dashboards import sharing
    from aughor.dashboards.home import person_of
    return {"cockpits": sharing.shared_with(connection_id, person_of(request))}


@router.get("/dashboards/shared/{owner}/{cockpit_id}")
def read_shared_dashboard(request: Request, owner: str, cockpit_id: str, connection_id: str,
                        preset: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
                        workspace_id: Optional[str] = None) -> dict:
    """A published dashboard as it stands, for a reader it reaches: read-only, for the reader's own
    period; a card the reader may not read stands and says so."""
    from aughor.dashboards import cards, host, images, sharing
    from aughor.dashboards.home import person_of
    from aughor.kernel.flags import flag_enabled
    from aughor.routers.investigations import resolve_currency_symbol
    try:
        got = sharing.read_shared(connection_id, owner, cockpit_id, reader=person_of(request))
    except sharing.Refused as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    home, kept = got["home"], got["cockpit"]
    ranges_on = flag_enabled("briefing.ranges")
    block, why = host.range_state(connection_id, preset if ranges_on else None,
                                  start=_day(start, "start") if ranges_on else None,
                                  end=_day(end, "end") if ranges_on else None, workspace_id=workspace_id)
    if block is None:
        raise HTTPException(status_code=422, detail=why)
    return {
        **home.as_params(),
        "cockpit": kept,
        "cards": [_as_read(c, connection_id) for c in cards.cards_of(home)],
        "range": block,
        "ranges_on": ranges_on,
        "currency_symbol": resolve_currency_symbol(connection_id, None),
        "images": images.stamps_for(connection_id, kept.get("spec")),
        "published_by": kept.get("published_by") or "",
        "published_to": kept.get("published_to") or [],
        **_pinned(connection_id, kept),
    }


@router.post("/dashboards/shared/{owner}/{cockpit_id}/copy")
def copy_shared_dashboard(request: Request, owner: str, cockpit_id: str, connection_id: str) -> dict:
    """Start a dashboard of the asker's own from a published one: the publisher's cards copied into
    theirs, the spec kept as the new dashboard's first version. The publisher's is untouched."""
    from aughor.dashboards import sharing
    from aughor.dashboards.home import person_of
    try:
        out = sharing.copy_for(connection_id, owner, cockpit_id, reader=person_of(request),
                               approved_by=_approved_by(request))
    except sharing.Refused as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _answer(out["kept"], cockpit_id=out["cockpit_id"], title=out["title"])


@router.get("/dashboards/from-object")
def propose_from_object(entity: str, connection_id: str, schema_name: Optional[str] = None) -> dict:
    """What a dashboard started from ``entity`` is offered (2026-10-10): its categories as filters, its numbers as
    figures, a chart of its objects per day, a table of them and the actions declared on them — each measured through
    the object door, with a preview. Nothing is kept and no model is asked; the person ticks what they want and keeps
    it as any new dashboard is kept. Registered before ``/cockpits/{cockpit_id}``, which would otherwise take its path."""
    from aughor.dashboards import from_object
    from aughor.routers.ontology import served_ontology_graph
    from aughor.semantic.object_query import ObjectQueryRefused
    graph = served_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="No ontology is built for this connection yet.")
    try:
        with from_object.reader(connection_id, schema_name, graph) as run:
            proposal = from_object.propose(graph, entity, run)
    except ObjectQueryRefused as exc:
        raise HTTPException(status_code=422, detail={"refused": exc.reason, "available": exc.available})
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"The warehouse did not answer: {exc}")
    return {"connection_id": connection_id, "schema_name": graph.schema_name, **proposal}


@router.get("/dashboards/shapes")
def suggested_shapes(connection_id: str, schema_name: Optional[str] = None) -> dict:
    """Arc AP-5 — what each object suggests a dashboard be: the shape that fits it best, with a short line of why, read
    from the served ontology alone — no warehouse read, no model. Registered before ``/cockpits/{cockpit_id}``."""
    from aughor.dashboards import shapes
    from aughor.routers.ontology import served_ontology_graph
    graph = served_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="No ontology is built for this connection yet.")
    out = []
    for entity in graph.entities.values():
        sig = shapes.signals(graph, entity)
        best = shapes.offered(sig)[0]
        out.append({"entity": entity.api_name, "type_id": entity.id, "name": sig["name"], **best})
    return {"connection_id": connection_id, "schema_name": graph.schema_name, "objects": out}


def _read_query(connection_id: str, req: QueryRequest) -> dict:
    """Arc AP-7 — a person's query read as a card would show it: its typed columns and first rows, how long it took, and
    the card as shown — or each thing that stops it, as sentences. Nothing is kept here."""
    from aughor.dashboards import pieces, queries
    from aughor.db.connection import open_connection_for
    sql = (req.sql or "").strip()
    if not sql:
        return {"refused": ["Write a query first."]}
    try:
        shown = queries.Shown.model_validate(req.shown or {"as": "table"})
    except Exception as e:
        return {"refused": [f"How the card is shown cannot be read: {e}"]}
    # Arc AP-8 — the dashboard's values it reads, bound: refused when one holds nothing
    run_sql, params = sql, None
    if queries.params_of(sql):
        try:
            run_sql, params = queries.bind(sql, req.values)
        except queries.Refused as e:
            return {"refused": [str(e)]}
    try:
        db = open_connection_for(connection_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Connection not found: {e}")
    try:
        tables = queries.tables_of(sql, queries.dialect_of(db))
        try:
            graph = pieces.served_graph(connection_id)
        except Exception:
            graph = None
        refusal = queries.policy_refusal(graph, tables)
        if refusal:
            return {"refused": [refusal], "tables": tables}
        seconds = queries.time_limit(connection_id)
        probe = queries.probe(db, run_sql, seconds=seconds, params=params)
        if probe["error"]:
            return {"refused": [probe["error"]], "tables": tables}
        columns = probe["columns"]
        shown = queries.normalized(shown, columns)
        problems = queries.check(shown, columns)
        out = {"columns": columns, "rows": probe["rows"][:queries.PREVIEW_ROWS],
               "more": probe["truncated"] or len(probe["rows"]) > queries.PREVIEW_ROWS,
               "duration_ms": probe["duration_ms"], "caveats": probe["caveats"], "tables": tables, "setup": shown.said(),
               "reads": queries.params_of(sql)}
        if problems:
            return {**out, "refused": problems}
        ran = queries.run(db, run_sql, shown, columns, seconds=seconds, params=params)
        if ran["error"]:
            return {**out, "refused": [ran["error"]]}
        return {**out, "refused": [], "shown": ran["shown"]}
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "dashboard query: connection close failed after a preview", counter="cockpit.query_close")


@router.post("/dashboards/queries/preview")
def preview_query(connection_id: str, req: QueryRequest) -> dict:
    """Arc AP-7 — run a person's own query as the builder would keep it, and say what it returns and how it would be
    shown — or what stops it. Nothing is kept. It runs through the connection's own door, read-only, stopped after the
    connection's time limit. Registered before ``/cockpits/{cockpit_id}``."""
    return {"connection_id": connection_id, **_read_query(connection_id, req)}


@router.post("/dashboards/queries", status_code=201)
def keep_query(request: Request, connection_id: str, req: QueryRequest) -> dict:
    """Arc AP-7 — keep a person's own query as a card of theirs, as it is to be shown. The query is run first and the
    setup checked against what it returns; a refusal says why and keeps nothing. A change to a card of theirs is a new
    card, and the one it replaces is superseded, never deleted — so a dashboard's earlier versions still read their own."""
    from aughor.dashboards import cards
    from aughor.dashboards.home import FIRST, Home, person_of
    from aughor.cards import doors
    from aughor.cards.models import StoredCard
    from aughor.cards.store import get_card, upsert_card
    home = Home(connection_id, person_of(request), FIRST)
    old = None
    if req.replaces:
        old = get_card(req.replaces)
        if old is None or (old.scope, old.scope_ref) != (cards.OWN, home.owner) or old.connection_id != connection_id:
            raise HTTPException(status_code=422, detail={"refused": ["Only a card of your own on this connection is changed here."]})
    read = _read_query(connection_id, req)
    if read.get("refused"):
        raise HTTPException(status_code=422, detail={"refused": read["refused"]})
    setup = read["setup"]
    card = StoredCard(connection_id=connection_id, source="authored", kind="kpi" if setup["as"] == "figure" else "chart",
                         title=doors.clip_title(req.title or "", old.title if old else "Your own query"),
                         sql=req.sql.strip(), render={"shown": setup, "columns": read["columns"]})
    try:
        saved = cards.place(home, card)
    except cards.Refused as e:
        raise HTTPException(status_code=422, detail={"refused": [str(e)]})
    if old is not None:
        upsert_card(old.model_copy(update={"provenance": old.provenance.model_copy(update={"superseded_by": saved.id})}))
    return {"card": _as_read(saved, connection_id), "preview": read}


@router.post("/dashboards/questions", status_code=201)
def keep_question(body: QuestionKeepRequest, connection_id: str) -> dict:
    """Keep a question for a dashboard: its automation, asked on its rhythm (weekly by default) or only when asked.
    Nothing is asked now — the first answer comes on its schedule, or is the Data Canvas answer it starts from."""
    from aughor.dashboards import questions
    try:
        return questions.keep(connection_id=connection_id, question=body.question, rhythm=body.rhythm,
                              schema=body.schema_name, first_run=body.first_run)
    except questions.QuestionRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dashboards/questions/cost")
def question_cost(connection_id: str) -> dict:
    """What one answer costs on this connection, from this install's own metered runs — said before a question is kept.
    Registered before the read below, which would otherwise take "cost" for a question's id."""
    from aughor.record.inquiry import run_cost_estimate
    return run_cost_estimate(connection_id)


@router.get("/dashboards/questions/{automation_id}")
def read_question(automation_id: str, first: str = "") -> dict:
    """A question as a dashboard shows it — its latest answer in full and every answer in a line. No model call."""
    from aughor.dashboards import questions
    try:
        return questions.read(automation_id, first=first)
    except questions.QuestionRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/dashboards/questions/{automation_id}/ask")
def ask_question_now(automation_id: str) -> dict:
    """Ask it now: a full agent run, through the gates its schedule uses. A person's click, never a page's load."""
    from aughor.dashboards import questions
    try:
        return questions.ask_now(automation_id)
    except questions.QuestionRefused as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/dashboards/questions/{automation_id}/rhythm")
def set_question_rhythm(automation_id: str, body: QuestionRhythmRequest) -> dict:
    from aughor.dashboards import questions
    try:
        return questions.set_rhythm(automation_id, body.rhythm)
    except questions.QuestionRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dashboards/{cockpit_id}")
def read_dashboard(request: Request, cockpit_id: str, connection_id: str, preset: Optional[str] = None,
                 start: Optional[str] = None, end: Optional[str] = None,
                 workspace_id: Optional[str] = None) -> dict:
    """One of the asker's dashboards as it stands: its newest version with its spec, every card
    it may place (theirs and the connection's), the range it is read for, and its history."""
    from aughor.dashboards import cards, host, images, versions
    from aughor.kernel.flags import flag_enabled
    from aughor.routers.investigations import resolve_currency_symbol
    home = _home(request, connection_id, cockpit_id)
    kept = versions.latest(home)
    if kept is None:
        raise HTTPException(status_code=404, detail="No such dashboard")
    ranges_on = flag_enabled("briefing.ranges")
    if (preset or start or end) and not ranges_on:
        raise HTTPException(status_code=404, detail="a dashboard for a date range needs the 'briefing.ranges' flag")
    block, why = host.range_state(connection_id, preset, start=_day(start, "start"), end=_day(end, "end"),
                                  workspace_id=workspace_id)
    if block is None:
        raise HTTPException(status_code=422, detail=why)
    held = cards.cards_of(home)
    withheld = cards.not_offered(home, held, kept.get("cards") or [])
    return {
        **home.as_params(),
        "cockpit": kept,
        "cards": [{**_as_read(c, connection_id), "not_offered": withheld.get(c.id, "")} for c in held],
        "range": block,
        "ranges_on": ranges_on,
        "history": versions.history(home),
        "currency_symbol": resolve_currency_symbol(connection_id, None),
        # What the spec's images are, from the volume's own rows; one the dashboard may not show says why.
        "images": images.stamps_for(connection_id, kept.get("spec")),
        **_pinned(connection_id, kept),
    }


def _pinned(connection_id: str, kept: dict) -> dict:
    """Arc OC-4 — for a dashboard holding pieces bound to the ontology: the release it was composed against, the one in
    force, and every change between them that touches what its pieces read. Nothing at all for one without them."""
    from aughor.dashboards.pieces import since
    said = since(connection_id, kept.get("spec"), str(kept.get("ontology_release") or ""))
    return {"ontology": said} if said is not None else {}


@router.post("/dashboards/images")
async def upload_image(request: Request, connection_id: str, file: UploadFile) -> dict:
    """Take an image into this connection's dashboard volume — PNG, JPEG, GIF, WebP or SVG, up to
    5 MB, read from its bytes — to be placed on a dashboard by the object id this answers with.
    By hand only: no model uploads an image."""
    from aughor.dashboards import images
    data = await file.read()
    try:
        return images.put_image(connection_id, file.filename or "image", data, file.content_type or "",
                                uploaded_by=_approved_by(request))
    except images.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/dashboards/images/{object_id}")
def read_image(request: Request, object_id: str, connection_id: str) -> Response:
    """An image a dashboard on this connection places, as bytes, with the reader's own access."""
    from aughor.dashboards import images
    try:
        data, content_type = images.read_image(connection_id, object_id)
    except images.Refused as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    headers = {"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=3600"}
    if content_type == "image/svg+xml":
        # Drawn in an <img>, nothing in it runs; opened on its own, this says the same.
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return Response(content=data, media_type=content_type, headers=headers)


@router.put("/dashboards/{cockpit_id}")
def keep_dashboard(request: Request, cockpit_id: str, connection_id: str, req: KeepRequest) -> dict:
    """Keep a spec the person wrote — a card moved, a section renamed — as the dashboard's next
    version, or a refusal with the reasons."""
    from aughor.dashboards import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.keep(home, req.spec, approved_by=_approved_by(request),
                                 source="a person's own hand", note=req.note, written_by_model=False,
                                 repin=req.repin),
                   cockpit_id=home.cockpit_id)


@router.post("/dashboards/start")
def start_first(request: Request, connection_id: str) -> dict:
    """Start "My dashboard" from the cards pinned in the Briefing before dashboards had names, in the
    order the person arranged them. Written by code, kept like any other spec."""
    from aughor.dashboards import cards, compose, versions
    from aughor.dashboards.home import FIRST
    home = _home(request, connection_id, FIRST)
    if versions.latest(home) is not None:
        raise HTTPException(status_code=409, detail={
            "status": "refused", "kept": False, "version": None, "artifact_id": "",
            "sentences": ['You already have "My dashboard". Its history is kept; go back to a version from there.']})
    held = cards.cards_of(home)
    if not held:
        raise HTTPException(status_code=422, detail={
            "status": "refused", "kept": False, "version": None, "artifact_id": "",
            "sentences": ["There are no pinned cards to start from. Name an area to draft a dashboard instead."]})
    spec = compose.default_spec("My dashboard", held, order=_layout_order(connection_id, home.owner))
    return _answer(versions.keep(home, spec, approved_by=_approved_by(request),
                                 source="started from the cards pinned in the Briefing",
                                 written_by_model=False),
                   cockpit_id=home.cockpit_id)


@router.post("/dashboards/draft")
def draft_dashboard(request: Request, connection_id: str, req: DraftRequest) -> dict:
    """⚑ Spends model calls. Draft a new dashboard for the area the person named: one short
    model run with the drafting tool alone. What comes back is a proposal to keep or not, or
    the reasons none was drafted — never a dashboard changed."""
    from aughor.dashboards.ask import draft_for_area
    from aughor.dashboards.home import person_of
    return draft_for_area(connection_id, person_of(request), req.area, schema=req.schema_name)


@router.post("/dashboards/move")
def move_dashboard(request: Request, connection_id: str, req: MoveRequest) -> dict:
    """Move a canvas's dashboard to the asker's Briefing. One act: the cards it places become
    theirs, its spec their dashboard's first version, and the canvas's is retired with a note."""
    from aughor.dashboards.home import person_of
    from aughor.dashboards.move import move_from_canvas
    out = move_from_canvas(req.canvas_id, connection_id=connection_id, owner=person_of(request))
    if not out["moved"]:
        raise HTTPException(status_code=422, detail=out)
    return out


@router.post("/dashboards/{cockpit_id}/ask")
def ask_dashboard(request: Request, cockpit_id: str, connection_id: str, req: AskRequest) -> dict:
    """⚑ Spends model calls. A change to one of the asker's dashboards, asked for in words — add a
    finding, move or resize an element, take a note off, share it with a team. One short model
    run with the drafting tool alone; what comes back is a proposal to keep or not."""
    from aughor.dashboards.ask import edit_in_words
    from aughor.dashboards.home import person_of
    home = _home(request, connection_id, cockpit_id)
    return edit_in_words(connection_id, person_of(request), home.cockpit_id, req.words, schema=req.schema_name)


@router.post("/dashboards/{cockpit_id}/publish")
def publish_dashboard(request: Request, cockpit_id: str, connection_id: str, req: PublishRequest) -> dict:
    """Publish the dashboard as it stands to groups the asker belongs to and roles they may publish
    to. A version, under their name; a reader sees it under "Shared with you"."""
    from aughor.dashboards import sharing, versions
    from aughor.dashboards.home import person_of
    home = _home(request, connection_id, cockpit_id)
    targets: list[dict] = []
    for raw in req.to:
        hit, why = sharing.may_publish_to(person_of(request), raw)
        if hit is None:
            raise HTTPException(status_code=422, detail={"status": "refused", "kept": False, "version": None,
                                                         "artifact_id": "", "sentences": [why]})
        if hit not in targets:
            targets.append(hit)
    if not targets:
        raise HTTPException(status_code=422, detail={"status": "refused", "kept": False, "version": None,
                                                     "artifact_id": "", "sentences": ["Name a group or a role to publish to."]})
    return _answer(versions.publish(home, targets, approved_by=_approved_by(request)), cockpit_id=home.cockpit_id)


@router.post("/dashboards/{cockpit_id}/unpublish")
def unpublish_dashboard(request: Request, cockpit_id: str, connection_id: str) -> dict:
    """Stop sharing a dashboard. A version too: its history says when it reached whom."""
    from aughor.dashboards import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.publish(home, [], approved_by=_approved_by(request)), cockpit_id=home.cockpit_id)


@router.post("/dashboards/{cockpit_id}/restore")
def restore_dashboard(request: Request, cockpit_id: str, connection_id: str, req: RestoreRequest) -> dict:
    """Go back to an earlier version. It is kept again as the newest, checked against the
    cards as they are today."""
    from aughor.dashboards import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.restore(home, req.version, approved_by=_approved_by(request)),
                   cockpit_id=home.cockpit_id)


@router.post("/dashboards/{cockpit_id}/retire")
def retire_dashboard(request: Request, cockpit_id: str, connection_id: str, req: RetireRequest) -> dict:
    """Retire a dashboard. Its history stays."""
    from aughor.dashboards import versions
    home = _home(request, connection_id, cockpit_id)
    return _answer(versions.retire(home, approved_by=_approved_by(request), note=req.note),
                   cockpit_id=home.cockpit_id)
