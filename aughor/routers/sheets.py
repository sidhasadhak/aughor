"""Spreadsheets — the sheets people make, edit, combine and chat with (Arc SH, ROADMAP §3.64).

Each wave behind its own flag, off by default; off, its routes answer 404 and nothing is written:

- ``sheets.core`` (SH-1): the home (the sheets, and the Workspace files to start one from), making a sheet from a
  file, from nothing or from a query's rows, reading its rows a page at a time with their totals, CSV, the oracle,
  removing it;
- ``sheets.grid`` (SH-2): setting cells, adding and removing rows and columns, views, the history, undo and redo, a
  cell's story, a row as a record with its comments;
- ``sheets.chat`` (SH-4) and ``sheets.combine`` (SH-7) add their own routes below;
- ``sheets.sharing`` (SH-8): who a sheet is shared with, read and changed. Every route here asks the sheet's sharing
  what the person may do first (`_sheet`) — read, change, or (its maker) reshare and remove — whatever the flag says,
  so a sheet shared with chosen people is refused to anyone else with a 403 that says it exists and who to ask.

No route here calls a model but the chat's. Every write is recorded under the person the request acts for — never a
name a client sends — and a refusal is an HTTP error carrying its sentence, never a 200 with nothing done.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/sheets", tags=["sheets"])


def _on(flag: str = "sheets.core") -> None:
    from aughor import sheets
    if not sheets.on(flag):
        raise HTTPException(status_code=404, detail=f"this needs the '{flag}' flag"
                            + ("" if flag == "sheets.core" else " (and 'sheets.core')"))


def _who(request: Request) -> str:
    from aughor.security.authz import acting_person, get_principal
    return acting_person(get_principal(request))


#: The access ladder's words for what a route asks of a sheet (SH-8): reading it, changing it, and — with
#: ``sheets.sharing`` on — what only its maker does, changing who it is shared with and removing it.
VIEW, EDIT, OWN = "view", "edit", "own"


def _sheet(sheet_id: str, request: Optional[Request] = None, need: str = VIEW):
    """The sheet, when the person asking may do what the route asks of it: 404 when there is none, 403 — saying it
    exists, and who to ask — when it is not shared with them, or not to change."""
    from aughor.sheets import model, sharing
    sheet = model.get(sheet_id)
    if sheet is None:
        raise HTTPException(status_code=404, detail="No such sheet")
    try:
        sharing.require(sheet, _who(request) if request is not None else sharing.acting(), need)
    except sharing.NotShared as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    return sheet


def _refused(exc: Exception) -> HTTPException:
    from aughor.sheets.service import Conflict
    from aughor.sheets.sharing import NotShared
    if isinstance(exc, Conflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, NotShared):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _summary(sheet, reader: str = "") -> dict:
    """A sheet as its home lists it. With ``sheets.sharing`` on — or for a sheet already shared with chosen people —
    it also says what the reader may do (``access``) and how many people and groups it is shared with; a sheet not
    shared with the reader is listed by its name and maker only, everything else ``None``, and says so."""
    from aughor import sheets
    from aughor.sheets import projection, sharing
    told = sheet.sharing == "chosen" or sheets.on(sheets.SHARING)
    got = sharing.level_of(sheet, reader) if told else None
    if got is not None and not got.level:
        return {"id": sheet.id, "name": sheet.name, "table": sheet.table, "rows": None, "columns": None,
                "came_from": None, "source": None, "last_change": None, "created_by": sheet.created_by,
                "created_at": sheet.created_at, "version": sheet.version, "shared_with": sheet.sharing,
                "shares": len(sheet.shared_with), "access": "", "withheld": sharing.refusal(sheet, got, VIEW)}
    src = sheet.source
    if src.kind == "file":
        came = f"from {src.file}" + (f", tab {src.tab}" if src.tab else "")
    elif src.kind == "rows":
        came = "kept from a query's rows"
    else:
        came = "made blank"
    out = {"id": sheet.id, "name": sheet.name, "table": sheet.table, "rows": projection.count(sheet),
           "columns": len(sheet.columns), "came_from": came, "source": src.model_dump(),
           "last_change": sheet.change.model_dump(), "created_by": sheet.created_by, "created_at": sheet.created_at,
           "version": sheet.version, "shared_with": "workspace"}
    if got is not None:
        out.update({"shared_with": sheet.sharing, "shares": len(sheet.shared_with), "access": got.level})
    return out


def _definition(sheet, reader: str) -> dict:
    """A sheet as the person reading it sees it: its columns, the views they see — every shared view and their own
    own — how many rows each view shows, its rules and the rows each marks."""
    from aughor.sheets import views as _views
    out = _summary(sheet, reader)
    seen = sheet.views_for(reader)
    out.update({"columns": [c.model_dump() for c in sheet.columns], "views": [v.model_dump() for v in seen],
                "key": sheet.key, "rules": [r.model_dump() for r in sheet.rules],
                "view_rows": _views.view_rows(sheet, seen), "rule_rows": _views.rule_rows(sheet), "me": reader})
    return out


# ── SH-1 — the sheets and their home ────────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_sheets(request: Request) -> dict:
    """The organisation's sheets, newest change first, and the Workspace files a sheet can be made from — with who is
    asking, so a change of theirs reads as theirs."""
    _on()
    from aughor.sheets import files, model
    sheets = sorted(model.list_sheets(), key=lambda s: s.change.at or s.created_at, reverse=True)
    me = _who(request)
    return {"sheets": [_summary(s, me) for s in sheets], "uploads": files.uploaded_files(), "shared_with": "workspace",
            "me": me}


def _described(token: str, name: str, size: int) -> dict:
    from aughor.sheets import files, imports
    path = files.staged(token)
    try:
        if path.suffix.lower() == ".xlsx":
            tabs = imports.tabs(path)
            described = [{"tab": t, **imports.describe(path, t)} for t in tabs]
        else:
            described = [{"tab": "", **imports.describe(path)}]
    except imports.ImportRefused as exc:
        files.unstage(token)
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"token": token, "file": name, "size": size, "tabs": described}


@router.post("/files")
def stage_file(file: UploadFile = File(...)) -> dict:
    """A file a person brought, read as written: per tab (an Excel workbook has several), its rows, and per column the
    kinds every value fits. Nothing is made until the person creates the sheet."""
    _on()
    import shutil
    from aughor.routers.connections import stage_upload
    from aughor.sheets import files
    tmp_dir, tmp_path = stage_upload(file)
    try:
        token = files.stage(tmp_path, tmp_path.name)
        size = tmp_path.stat().st_size
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return _described(token, tmp_path.name, size)


class UploadedFile(BaseModel):
    schema_name: str
    file: str


@router.post("/files/uploaded")
def stage_uploaded(req: UploadedFile) -> dict:
    """A file already uploaded to the Workspace, read as written — copied, so the Workspace's own file stays as it was."""
    _on()
    from aughor.sheets import files
    path = files.upload_path(req.schema_name, req.file)
    if path is None:
        raise HTTPException(status_code=404, detail="No such uploaded file")
    token = files.stage(path, path.name)
    return {**_described(token, path.name, path.stat().st_size), "upload": {"schema": req.schema_name,
                                                                           "file": req.file}}


class TabPlan(BaseModel):
    tab: str = ""
    name: str
    kinds: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)


class CreateRequest(BaseModel):
    #: ``file`` (a staged file, one sheet per tab named), ``blank`` or ``rows`` (a query's, kept).
    source: str = "file"
    token: str = ""
    tabs: list[TabPlan] = Field(default_factory=list)
    upload: dict[str, str] = Field(default_factory=dict)
    name: str = ""
    columns: list[dict[str, Any]] = Field(default_factory=list)
    connection_id: str = ""
    schema_name: str = ""
    sql: str = ""


@router.post("")
def create(req: CreateRequest, request: Request) -> dict:
    """Make a sheet — or, from an Excel workbook, one sheet per tab, each named."""
    _on()
    from aughor.sheets import files, service
    who = _who(request)
    made = []
    try:
        if req.source == "file":
            if not req.tabs:
                raise service.Refused("name the sheet to make from the file")
            cid = service.change_id()
            for plan in req.tabs:
                made.append(service.create_from_file(req.token, name=plan.name, by=who, tab=plan.tab,
                                                     chosen=plan.kinds, descriptions=plan.descriptions,
                                                     upload=req.upload or None,
                                                     cid=cid if len(req.tabs) == 1 else ""))
            files.unstage(req.token)
        elif req.source == "blank":
            made.append(service.create_blank(name=req.name, by=who, columns=req.columns or None))
        elif req.source == "rows":
            made.append(service.create_from_rows(name=req.name, by=who, connection_id=req.connection_id,
                                                 sql=req.sql, schema_name=req.schema_name))
        else:
            raise service.Refused(f"{req.source!r} is not a way to make a sheet; it is file, blank or rows")
    except service.Refused as exc:
        raise _refused(exc) from None
    return {"sheets": [_definition(s, who) for s in made]}


@router.get("/{sheet_id}")
def read(sheet_id: str, request: Request) -> dict:
    _on()
    return _definition(_sheet(sheet_id, request, VIEW), _who(request))


@router.delete("/{sheet_id}")
def remove(sheet_id: str, request: Request) -> dict:
    """Remove a sheet: its tombstone first, then its table, its values and their history, and its files."""
    _on()
    from aughor import sheets
    from aughor.sheets import service
    sheet = _sheet(sheet_id, request, OWN if sheets.on(sheets.SHARING) else EDIT)
    service.remove(sheet, by=_who(request))
    return {"removed": sheet.id, "name": sheet.name}


def _view_args(sheet, view: str, filter_json: str, sort_json: str, search: str, reader: str) -> dict:
    from aughor.sheets.model import Condition
    chosen = next((v for v in sheet.views_for(reader) if v.id == view), None) if view else None
    try:
        conditions = [Condition(**c) for c in json.loads(filter_json)] if filter_json else (
            chosen.filter if chosen else [])
        sort = json.loads(sort_json) if sort_json else (chosen.sort if chosen else [])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"the filter or sort could not be read: {exc}") from None
    return {"conditions": conditions, "sort": sort,
            "search": search if search else (chosen.search if chosen else ""),
            "hidden": chosen.hidden if chosen else []}


def _changed(sheet, on_page: set[int]) -> dict[str, dict[str, dict]]:
    """For the cells on a page people have set: who set them, when, and at which version."""
    from aughor.actions import overlay
    changed: dict[str, dict[str, dict]] = {}
    for e in overlay.sheet_values(sheet.id):
        if e.kind == overlay.SHEET_CELL and int(e.row_key) in on_page:
            changed.setdefault(e.row_key, {})[e.column] = {"by": e.actor, "at": e.created_at, "version": e.version,
                                                          "origin": e.origin}
    return changed


def _versions(sheet, on_page: set[int]) -> dict[str, dict[str, int]]:
    """The version each cell on a page stands at — set, or put back by an undo — the one a change to it must name. A
    cell an undo put back holds no edit (it is not in ``changed``) but keeps its version."""
    from aughor.actions import overlay
    out: dict[str, dict[str, int]] = {}
    for (row, column), version in overlay.sheet_versions(sheet.id, on_page).items():
        out.setdefault(str(row), {})[column] = version
    return out


@router.get("/{sheet_id}/rows")
def rows(sheet_id: str, request: Request, view: str = "", filter: str = "", sort: str = "", search: str = "",
         group: str = "", offset: int = 0, limit: int = 200) -> dict:
    """One page of a view of a sheet — its rows, how many the view holds, its totals over those rows, its groups when
    grouped — and, for the cells on the page people have set, who set them, when, and at which version; with
    ``sheets.views`` on, the rules marking each row on it."""
    _on()
    from aughor import sheets
    from aughor.sheets import projection
    from aughor.sheets import views as _views
    sheet = _sheet(sheet_id, request, VIEW)
    args = _view_args(sheet, view, filter, sort, search, _who(request))
    try:
        page = projection.read_rows(sheet, conditions=args["conditions"], sort=args["sort"], search=args["search"],
                                    group=group, offset=offset, limit=limit)
    except projection.FilterRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    on_page = {int(r[0]) for r in page["rows"]}
    page["changed"] = _changed(sheet, on_page)
    page["versions"] = _versions(sheet, on_page)
    page["columns"] = [c.id for c in sheet.columns]
    page["source_rows"] = sheet.source.rows
    if sheets.on(sheets.VIEWS):
        page["marks"] = _views.marks(sheet, on_page)
    return page


@router.get("/{sheet_id}/csv")
def csv(sheet_id: str, request: Request, view: str = "", filter: str = "", sort: str = "", search: str = "") -> Response:
    _on()
    from aughor.sheets import projection
    sheet = _sheet(sheet_id, request, VIEW)
    args = _view_args(sheet, view, filter, sort, search, _who(request))
    text = projection.to_csv(sheet, conditions=args["conditions"], sort=args["sort"], search=args["search"],
                             hidden=args["hidden"])
    return Response(content=text, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{sheet.table}.csv"'})


@router.get("/{sheet_id}/check")
def check(sheet_id: str, request: Request) -> dict:
    """The oracle: the sheet's table as it stands against a fresh rebuild from its source and its changes."""
    _on()
    from aughor.sheets import projection
    return projection.check(_sheet(sheet_id, request, VIEW))


# ── SH-2 — the grid ─────────────────────────────────────────────────────────────────────────────────────────────────

class CellsRequest(BaseModel):
    #: Each ``{row, column, value, version}`` — ``version`` the one read (0 for a cell never set).
    cells: list[dict[str, Any]]


@router.patch("/{sheet_id}/cells")
def set_cells(sheet_id: str, req: CellsRequest, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    try:
        return service.set_cells(_sheet(sheet_id, request, EDIT), req.cells, by=_who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


class RowRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@router.post("/{sheet_id}/rows")
def add_row(sheet_id: str, req: RowRequest, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    try:
        return service.add_row(_sheet(sheet_id, request, EDIT), req.values, by=_who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


class RemoveRowsRequest(BaseModel):
    rows: list[int]


@router.post("/{sheet_id}/rows/remove")
def remove_rows(sheet_id: str, req: RemoveRowsRequest, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    try:
        return service.remove_rows(_sheet(sheet_id, request, EDIT), req.rows, by=_who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


class ColumnRequest(BaseModel):
    name: str
    kind: str = "text"
    description: str = ""
    #: SH-5 — a column a model writes: ``{instruction, reads: [column ids]}`` (needs ``sheets.model_columns``)
    model: Optional[dict[str, Any]] = None


@router.post("/{sheet_id}/columns")
def add_column(sheet_id: str, req: ColumnRequest, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    if req.model is not None:
        _on("sheets.model_columns")
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        if req.model is not None:
            from aughor.sheets import model_columns
            kept = model_columns.add(sheet, name=req.name, instruction=str(req.model.get("instruction") or ""),
                                     reads=[str(r) for r in req.model.get("reads") or []], by=_who(request))
            return _definition(kept, _who(request))
        return _definition(service.add_column(sheet, name=req.name, kind=req.kind, by=_who(request),
                                              description=req.description), _who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


# ── SH-5 — a column a model writes, filled for a view's rows ────────────────────────────────────────────────────────

class FillRequest(BaseModel):
    #: The view whose rows are filled, and the filter, sort and search on screen (each read as the grid reads them).
    view: str = ""
    filter: list[dict[str, Any]] = Field(default_factory=list)
    sort: list[dict[str, Any]] = Field(default_factory=list)
    search: str = ""


def _fill_args(sheet, req: FillRequest, request: Request) -> dict:
    return _view_args(sheet, req.view, json.dumps(req.filter) if req.filter else "",
                      json.dumps(req.sort) if req.sort else "", req.search, _who(request))


@router.post("/{sheet_id}/columns/{column_id}/fill/preview")
def fill_preview(sheet_id: str, column_id: str, req: FillRequest, request: Request) -> dict:
    """What filling the column for the view's rows would do, before it runs: the rows it takes (at most 200), the model
    calls (25 rows a call), and what they cost — or that the model's price is not set. No model is called."""
    _on("sheets.model_columns")
    from aughor.sheets import model_columns, projection, service
    sheet = _sheet(sheet_id, request, EDIT)
    args = _fill_args(sheet, req, request)
    try:
        return model_columns.plan(sheet, column_id, conditions=args["conditions"], sort=args["sort"],
                                  search=args["search"])
    except (service.Refused, projection.FilterRefused) as exc:
        raise _refused(exc) from None


@router.post("/{sheet_id}/columns/{column_id}/fill")
def fill_column(sheet_id: str, column_id: str, req: FillRequest, request: Request) -> dict:
    """Fill the column for the view's rows not filled yet — at most 200, 25 a call — as one change kept under the
    person signed in, said as written by a model. This route calls a model."""
    _on("sheets.model_columns")
    from aughor.sheets import model_columns, projection, service
    sheet = _sheet(sheet_id, request, EDIT)
    args = _fill_args(sheet, req, request)
    try:
        return model_columns.fill(sheet, column_id, conditions=args["conditions"], sort=args["sort"],
                                  search=args["search"], by=_who(request))
    except (service.Refused, projection.FilterRefused) as exc:
        raise _refused(exc) from None


class ColumnUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[str] = None
    hidden: Optional[bool] = None
    #: move the column in front of this one ("" to the end)
    before: Optional[str] = None


@router.patch("/{sheet_id}/columns/{column_id}")
def update_column(sheet_id: str, column_id: str, req: ColumnUpdate, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return _definition(service.update_column(sheet, column_id, by=_who(request), name=req.name,
                                                 description=req.description, kind=req.kind, hidden=req.hidden,
                                                 before=req.before),
                           _who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


@router.delete("/{sheet_id}/columns/{column_id}")
def remove_column(sheet_id: str, column_id: str, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return _definition(service.remove_column(sheet, column_id, by=_who(request)), _who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


class RenameRequest(BaseModel):
    name: str


@router.patch("/{sheet_id}")
def rename(sheet_id: str, req: RenameRequest, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    return _definition(service.rename(_sheet(sheet_id, request, EDIT), req.name, by=_who(request)), _who(request))


class ViewRequest(BaseModel):
    view: dict[str, Any]


@router.put("/{sheet_id}/views")
def save_view(sheet_id: str, req: ViewRequest, request: Request) -> dict:
    """Keep a view — a filter, a sort, hidden columns — shared with everyone who reads the sheet. With
    ``sheets.views`` (SH-3) a view may also be grouped with its totals, a board or a calendar, and kept to its maker."""
    _on("sheets.grid")
    from aughor import sheets
    from aughor.sheets import projection, service
    from aughor.sheets.model import View
    try:
        view = View(**req.view)
        if not sheets.on(sheets.VIEWS) and (view.kind != "grid" or view.group or view.date or view.card
                                            or not view.shared):
            raise HTTPException(status_code=404, detail="a grouped, board, calendar or unshared view needs the "
                                "'sheets.views' flag")
        return _definition(service.save_view(_sheet(sheet_id, request, EDIT), view, by=_who(request)), _who(request))
    except (service.Refused, projection.FilterRefused, ValueError) as exc:
        raise _refused(exc) from None


@router.delete("/{sheet_id}/views/{view_id}")
def remove_view(sheet_id: str, view_id: str, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return _definition(service.remove_view(sheet, view_id, by=_who(request)), _who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


@router.get("/{sheet_id}/changes")
def changes(sheet_id: str, request: Request) -> dict:
    """Every change to the sheet, newest first — and what undo and redo would take back for the person asking."""
    _on("sheets.grid")
    from aughor.sheets import service
    sheet = _sheet(sheet_id, request, VIEW)
    done, undone = service.stacks(sheet, _who(request))
    # the toolbar's undo never offers the sheet's own making: that would remove it
    undoable = done[-1] if done and not service.made_it(sheet, done[-1]["id"]) else None
    return {"changes": service.changes(sheet), "can_undo": undoable["what"] if undoable else "",
            "can_redo": undone[-1]["what"] if undone else ""}


@router.post("/{sheet_id}/undo")
def undo(sheet_id: str, request: Request, removing: bool = False) -> dict:
    """Take back the person's latest change, whole. ``removing`` is said only to undo the change that made the sheet —
    which removes it."""
    _on("sheets.grid")
    from aughor.sheets import service
    try:
        out = service.undo(_sheet(sheet_id, request, EDIT), by=_who(request), removing=removing)
    except service.Refused as exc:
        raise _refused(exc) from None
    return {"change_id": out["change_id"], "removed": out["removed"]}


@router.post("/{sheet_id}/redo")
def redo(sheet_id: str, request: Request) -> dict:
    _on("sheets.grid")
    from aughor.sheets import service
    try:
        out = service.redo(_sheet(sheet_id, request, EDIT), by=_who(request))
    except service.Refused as exc:
        raise _refused(exc) from None
    return {"change_id": out["change_id"], "removed": out["removed"]}


@router.get("/{sheet_id}/cells/{row}/{column_id}")
def cell(sheet_id: str, row: int, column_id: str, request: Request) -> dict:
    """A cell's story: where its value came from, and every change to it since."""
    _on()
    from aughor.sheets import service
    try:
        return service.cell_history(_sheet(sheet_id, request, VIEW), row, column_id)
    except service.Refused as exc:
        raise _refused(exc) from None


@router.get("/{sheet_id}/records/{row}")
def record(sheet_id: str, row: int, request: Request) -> dict:
    """A row as a record: every field and where it came from, its linked rows, its history, its comments — and, with
    ``sheets.views`` on, the rules that mark it."""
    _on()
    from aughor import sheets
    from aughor.sheets import record as _record
    got = _record.record(_sheet(sheet_id, request, VIEW), row, marked_by_rules=sheets.on(sheets.VIEWS))
    if got is None:
        raise HTTPException(status_code=404, detail="No such row")
    return got


class CommentRequest(BaseModel):
    text: str


@router.post("/{sheet_id}/records/{row}/comments")
def comment(sheet_id: str, row: int, req: CommentRequest, request: Request) -> dict:
    """A comment on a row — a said claim in the Record, in the name of the person signed in."""
    _on("sheets.grid")
    from aughor.sheets import record as _record
    from aughor.sheets import service
    try:
        return _record.comment(_sheet(sheet_id, request, VIEW), row, req.text, by=_who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


# ── SH-3 — views: groups with their totals, a board, a calendar, rules ──────────────────────────────────────────────

@router.get("/{sheet_id}/groups")
def groups(sheet_id: str, request: Request, group: str, view: str = "", filter: str = "", sort: str = "",
           search: str = "", per_group: int = 3) -> dict:
    """The view's rows grouped by a column, the largest group first, each with its first rows — and, with
    ``sheets.views`` on, each group's totals over its own rows."""
    _on()
    from aughor import sheets
    from aughor.sheets import projection
    from aughor.sheets import views as _views
    sheet = _sheet(sheet_id, request, VIEW)
    args = _view_args(sheet, view, filter, sort, search, _who(request))
    try:
        out = _views.groups(sheet, conditions=args["conditions"], search=args["search"], sort=args["sort"],
                            group=group, per_group=per_group, with_totals=sheets.on(sheets.VIEWS))
    except (projection.FilterRefused, _views.ViewRefused) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    on_page = {int(r[0]) for g in out["groups"] for r in g["shown"]}
    out["changed"] = _changed(sheet, on_page)
    out["versions"] = _versions(sheet, on_page)
    if sheets.on(sheets.VIEWS):
        out["marks"] = _views.marks(sheet, on_page)
    return out


@router.get("/{sheet_id}/board")
def board(sheet_id: str, request: Request, column: str, view: str = "", filter: str = "", sort: str = "",
          search: str = "", per_lane: int = 20) -> dict:
    """The view's rows as a board: a lane per value of a choice or yes/no column, each with its rows and first cards;
    the values the view's filter leaves out, listed with their rows."""
    _on("sheets.views")
    from aughor.sheets import projection
    from aughor.sheets import views as _views
    sheet = _sheet(sheet_id, request, VIEW)
    args = _view_args(sheet, view, filter, sort, search, _who(request))
    try:
        out = _views.board(sheet, conditions=args["conditions"], search=args["search"], sort=args["sort"],
                           column=column, per_lane=per_lane)
    except (projection.FilterRefused, _views.ViewRefused) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    on_board = {int(r[0]) for lane in out["lanes"] for r in lane["cards"]}
    out["changed"] = _changed(sheet, on_board)
    out["versions"] = _versions(sheet, on_board)
    out["marks"] = _views.marks(sheet, on_board)
    return out


@router.get("/{sheet_id}/calendar")
def calendar(sheet_id: str, request: Request, column: str, month: str = "", view: str = "", filter: str = "",
             search: str = "") -> dict:
    """The view's rows placed by a date column, a month at a time; the rows with no date are counted."""
    _on("sheets.views")
    from aughor.sheets import projection
    from aughor.sheets import views as _views
    sheet = _sheet(sheet_id, request, VIEW)
    args = _view_args(sheet, view, filter, "", search, _who(request))
    try:
        return _views.calendar(sheet, conditions=args["conditions"], search=args["search"], column=column, month=month)
    except (projection.FilterRefused, _views.ViewRefused) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class RuleRequest(BaseModel):
    rule: dict[str, Any]


@router.put("/{sheet_id}/rules")
def save_rule(sheet_id: str, req: RuleRequest, request: Request) -> dict:
    """Keep a rule that marks the rows meeting its conditions — counted as a view with those conditions counts."""
    _on("sheets.views")
    from aughor.sheets import service
    from aughor.sheets.model import Rule
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return _definition(service.save_rule(sheet, Rule(**req.rule), by=_who(request)), _who(request))
    except (service.Refused, ValueError) as exc:
        raise _refused(exc) from None


@router.delete("/{sheet_id}/rules/{rule_id}")
def remove_rule(sheet_id: str, rule_id: str, request: Request) -> dict:
    _on("sheets.views")
    from aughor.sheets import service
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return _definition(service.remove_rule(sheet, rule_id, by=_who(request)), _who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


# ── SH-6 — a sheet everywhere else: first, a dashboard made from it ────────────────────────────────────────────────

@router.get("/{sheet_id}/dashboard")
def dashboard_proposal(sheet_id: str, request: Request, view: str = "") -> dict:
    """The cards a dashboard made from this sheet — or from the view on screen — is offered, each run once on the sheet
    as it stands. Nothing is kept here: the cards and the dashboard are kept through the dashboards' own doors."""
    _on("sheets.everywhere")
    from aughor.sheets import dashboard, projection
    sheet = _sheet(sheet_id, request, VIEW)
    chosen = next((v for v in sheet.views_for(_who(request)) if v.id == view), None) if view else None
    try:
        return dashboard.propose(sheet, chosen)
    except projection.FilterRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


# ── SH-8 — sharing ──────────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/{sheet_id}/sharing")
def read_sharing(sheet_id: str, request: Request) -> dict:
    """Who a sheet is shared with — everyone in the workspace, or each person and group chosen with what they may do —
    what the person asking may do, whether they may change it, and the people and groups they may choose from."""
    _on("sheets.sharing")
    from aughor.sheets import sharing
    return sharing.described(_sheet(sheet_id, request, VIEW), _who(request))


class SharingRequest(BaseModel):
    #: "workspace" — everyone in it reads and edits — or "chosen": only the people and groups below, and the maker
    sharing: str
    #: Each ``{kind: person | group | role, id, level: view | edit}``.
    shared_with: list[dict[str, Any]] = Field(default_factory=list)


@router.put("/{sheet_id}/sharing")
def change_sharing(sheet_id: str, req: SharingRequest, request: Request) -> dict:
    """Share a sheet with everyone in the workspace or with the people and groups chosen, kept as a version of its
    definition. Only its maker may."""
    _on("sheets.sharing")
    from aughor.sheets import service, sharing
    sheet = _sheet(sheet_id, request, OWN)
    try:
        kept = sharing.set_sharing(sheet, req.sharing, req.shared_with, by=_who(request))
    except service.Refused as exc:
        raise _refused(exc) from None
    return sharing.described(kept, _who(request))


# ── SH-7 — combining ────────────────────────────────────────────────────────────────────────────────────────────────

class LinkRequest(BaseModel):
    column: str
    other: str
    other_column: str
    bring: list[str] = Field(default_factory=list)


@router.post("/{sheet_id}/links/preview")
def link_preview(sheet_id: str, req: LinkRequest, request: Request) -> dict:
    """What a link would find — every match and every miss counted — before anything is kept."""
    _on("sheets.combine")
    from aughor.sheets import combine, service
    try:
        return combine.link_preview(_sheet(sheet_id, request, EDIT), req.column, req.other, req.other_column)
    except service.Refused as exc:
        raise _refused(exc) from None


@router.post("/{sheet_id}/links")
def link_keep(sheet_id: str, req: LinkRequest, request: Request) -> dict:
    _on("sheets.combine")
    from aughor.sheets import combine, service
    try:
        return _definition(combine.link_keep(_sheet(sheet_id, request, EDIT), req.column, req.other, req.other_column,
                                             bring=req.bring, by=_who(request)), _who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


class TotalRequest(BaseModel):
    by_column: str
    other: str
    other_key: str
    how: str = "sum"
    of: str = ""
    name: str = ""


@router.post("/{sheet_id}/totals/preview")
def total_preview(sheet_id: str, req: TotalRequest, request: Request) -> dict:
    _on("sheets.combine")
    from aughor.sheets import combine, service
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return combine.total_preview(sheet, req.by_column, req.other, req.other_key, req.how, req.of)
    except service.Refused as exc:
        raise _refused(exc) from None


@router.post("/{sheet_id}/totals")
def total_keep(sheet_id: str, req: TotalRequest, request: Request) -> dict:
    _on("sheets.combine")
    from aughor.sheets import combine, service
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return _definition(combine.total_keep(sheet, req.by_column, req.other, req.other_key, req.how,
                                              req.of, name=req.name, by=_who(request)), _who(request))
    except service.Refused as exc:
        raise _refused(exc) from None


class MergeRequest(BaseModel):
    token: str
    key: str
    tab: str = ""
    basis: str = ""


@router.post("/{sheet_id}/merge/preview")
def merge_preview(sheet_id: str, req: MergeRequest, request: Request) -> dict:
    """A newer file against the sheet: every row it adds and every cell it changes, before it is applied."""
    _on("sheets.combine")
    from aughor.sheets import combine, service
    try:
        return combine.merge_preview(_sheet(sheet_id, request, EDIT), req.token, req.key, req.tab)
    except service.Refused as exc:
        raise _refused(exc) from None


@router.post("/{sheet_id}/merge")
def merge_apply(sheet_id: str, req: MergeRequest, request: Request) -> dict:
    _on("sheets.combine")
    from aughor.sheets import combine, service
    sheet = _sheet(sheet_id, request, EDIT)
    try:
        return combine.merge_apply(sheet, req.token, req.key, basis=req.basis, by=_who(request),
                                   tab=req.tab)
    except service.Refused as exc:
        raise _refused(exc) from None


# ── SH-4 — the chat beside a sheet ──────────────────────────────────────────────────────────────────────────────────

@router.get("/{sheet_id}/grounding")
def grounding(sheet_id: str, request: Request, view: str = "") -> dict:
    """What the chat beside the sheet is handed: the table, its columns, and the view on screen as the grid's own filter
    and count. The panel shows it, so a person can see what an answer was grounded in."""
    _on("sheets.chat")
    from aughor.sheets import chat
    sheet = _sheet(sheet_id, request, VIEW)
    return chat.explain_sheet(f"{sheet.id}:{view}" if view else sheet.id)


class ProposeRequest(BaseModel):
    words: str


@router.post("/{sheet_id}/propose")
def propose(sheet_id: str, req: ProposeRequest, request: Request) -> dict:
    """A change asked for in words, proposed by the model as ONE proposal — every change in it checked and counted.
    This route calls a model. Nothing changes until the person applies it."""
    _on("sheets.chat")
    from aughor.sheets import chat
    return chat.propose(_sheet(sheet_id, request, EDIT), req.words, by=_who(request))


class ProposeNewRequest(BaseModel):
    token: str
    words: str = ""
    upload: dict[str, str] = Field(default_factory=dict)


@router.post("/proposals/new")
def propose_new(req: ProposeNewRequest, request: Request) -> dict:
    """A file dropped into the chat, as one proposal for a sheet. This route calls a model when the install's model can
    call tools; otherwise the proposal holds the file's own reading — its name and kinds — and nothing more."""
    _on("sheets.chat")
    from aughor.sheets import chat, imports
    try:
        return chat.propose_new_sheet(req.token, req.words, by=_who(request), upload=req.upload or None)
    except imports.ImportRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/proposals/{proposal_id}")
def read_proposal(proposal_id: str, request: Request) -> dict:
    _on("sheets.chat")
    from aughor.sheets import chat
    p = chat.proposal(proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="No such proposal")
    if p.get("sheet"):
        _sheet(p["sheet"], request, VIEW)
    return p


class ApplyRequest(BaseModel):
    #: The changes to apply, by their place in the proposal; omitted, all of them.
    picks: Optional[list[int]] = None


@router.post("/proposals/{proposal_id}/apply")
def apply_proposal(proposal_id: str, req: ApplyRequest, request: Request) -> dict:
    """Apply a proposal, all of it or the changes picked, as one change recorded as proposed by the assistant and
    applied by the person signed in."""
    _on("sheets.chat")
    from aughor.sheets import chat, service
    p = chat.proposal(proposal_id)
    if p is not None and p.get("sheet") and not p.get("new_sheet"):
        _sheet(p["sheet"], request, EDIT)
    try:
        return chat.apply(proposal_id, req.picks, by=_who(request))
    except service.Refused as exc:
        raise _refused(exc) from None
