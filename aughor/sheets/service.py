"""What a person does to a sheet — make one, change its values and columns, undo, remove it (Arc SH, SH-1 and SH-2).

Every act is ONE change with its own id: the edits it wrote to the edit layer and the definition version it kept carry
the same id, so undo and redo take it back whole. Each is recorded under the person who made it (``by``); one the
assistant proposed carries ``origin`` ``proposal:<id>`` and is recorded as proposed by the assistant and applied by the
person — a model never changes a sheet on its own.

**Undo is the changes' own history.** Undoing a change writes a new change that puts back what it replaced, with
``origin`` ``undo:<id>``; redoing writes the reverse of that. Nothing is deleted to undo, and a change that someone has
changed over since is refused, naming who, rather than undone over their work.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from aughor.actions import overlay
from aughor.actions.overlay import SHEET_CELL, SHEET_ROW, EditConflict, SheetEdit
from aughor.sheets import files, imports, kinds, model, projection
from aughor.sheets.model import Column, Rule, Sheet, Source, View


class Refused(ValueError):
    """Why a change to a sheet was not made, in a sentence a person can act on."""


def change_id() -> str:
    return uuid.uuid4().hex[:12]


def _taken_tables(but: str = "") -> set[str]:
    return {s.table for s in model.list_sheets() if s.id != but}


def unique_name(name: str, sheet: Sheet, but: str = "") -> str:
    base = " ".join(str(name or "").split())[:80]
    if not base:
        raise Refused("a column needs a name")
    if base == "_row":
        raise Refused("_row is kept for each row's number; choose another name")
    taken = {c.name.lower() for c in sheet.columns if c.id != but}
    candidate, n = base, 2
    while candidate.lower() in taken:
        candidate, n = f"{base} {n}", n + 1
    return candidate


def default_view(name: str) -> View:
    last = (name.split() or ["rows"])[-1].lower()
    return View(id="all", name=f"All {last}" if last.endswith("s") and len(last) > 2 else "All rows")


def _join_workspace() -> None:
    """The Sheets connection joins the workspace the first time a sheet is made: a connection no workspace tracks is
    not in the Catalog (`accessible_catalog_ids`)."""
    try:
        from aughor.workspace.store import join_connection
        join_connection(model.SHEETS_CONNECTION)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "workspace membership of the Sheets connection is repaired at startup",
                 counter="sheets.workspace_join")


# ── making a sheet ───────────────────────────────────────────────────────────────────────────────────────────────────

def _plan_columns(sheet: Sheet, con, raw_cols: list[str], chosen: dict[str, str], descriptions: dict[str, str],
                  currency: str) -> list[dict]:
    fits = imports.measure(con, raw_cols)
    plan = []
    for raw in raw_cols:
        fit = fits[raw]
        kind = chosen.get(raw) or kinds.suggest(raw, fit)
        if kind not in kinds.KINDS or kind == kinds.LINK:
            raise Refused(f"{kind!r} is not a kind a column can be made with; a link is made in Combine")
        if not fit.fits(kind):
            n = fit.misfits.get(kind, 0)
            raise Refused(f"{n:,} value{'s' if n != 1 else ''} in {raw} do not read as {kinds.LABELS[kind]}; "
                          "choose Text, or another kind every value fits")
        col = Column(id=sheet.new_column_id(), name=unique_name(raw, sheet), kind=kind,
                     integer=fit.integer if kind == kinds.NUMBER else False, source=raw,
                     description=(descriptions.get(raw) or "")[:500],
                     currency=currency if kind == kinds.MONEY else "",
                     choices=[v for v, _ in fit.values] if kind == kinds.CHOICE else [])
        sheet.columns.append(col)
        plan.append({"id": col.id, "raw": raw, "kind": kind, "integer": col.integer})
    return plan


def create_from_file(token: str, *, name: str, by: str, tab: str = "", chosen: Optional[dict] = None,
                     descriptions: Optional[dict] = None, upload: Optional[dict] = None, origin: str = "",
                     cid: str = "") -> Sheet:
    """A sheet from a file a person brought (staged under ``token``): its rows typed by the kinds chosen, every value
    named by its file row, the file kept beside it as brought."""
    path = files.staged(token)
    if path is None:
        raise Refused("that file is no longer waiting to become a sheet; bring it again")
    name = " ".join((name or "").split())[:80] or path.stem
    sheet = Sheet(id=model.new_id(), name=name, table=model.table_name(name, _taken_tables()),
                  created_by=by, created_at=model.now())
    con, raw_cols = imports.open_file(path, tab)
    try:
        plan = _plan_columns(sheet, con, raw_cols, chosen or {}, descriptions or {}, imports.currency_for(upload))
        rows = imports.write_source(sheet.id, con, plan)
    except imports.ImportRefused as exc:
        files.remove(sheet.id)
        raise Refused(str(exc)) from None
    except Exception:
        files.remove(sheet.id)
        raise
    finally:
        con.close()
    files.keep_original(sheet.id, path)
    shown = upload.get("file") if upload else path.name
    sheet.source = Source(kind="file", file=shown or path.name, tab=tab, sha256=files.sha256(path), rows=rows,
                          imported_at=model.now(), upload=dict(upload or {}))
    sheet.views = [default_view(name)]
    what = f"made from {sheet.source.file}" + (f", tab {tab}" if tab else "")
    model.save(sheet, what=what, by=by, origin=origin, change_id=cid or change_id())
    projection.rebuild(sheet)
    _join_workspace()
    return sheet


def create_blank(*, name: str, by: str, columns: Optional[list[dict]] = None, origin: str = "", cid: str = "") -> Sheet:
    """A sheet with no rows: a name, and the columns a person names with their kinds."""
    name = " ".join((name or "").split())[:80]
    if not name:
        raise Refused("a sheet needs a name")
    sheet = Sheet(id=model.new_id(), name=name, table=model.table_name(name, _taken_tables()), created_by=by,
                  created_at=model.now(), source=Source(kind="blank", imported_at=model.now()))
    for spec in columns or [{"name": "Name", "kind": kinds.TEXT}]:
        kind = str(spec.get("kind") or kinds.TEXT)
        if kind not in kinds.KINDS or kind == kinds.LINK:
            raise Refused(f"{kind!r} is not a kind a column can be made with")
        sheet.columns.append(Column(id=sheet.new_column_id(), name=unique_name(spec.get("name") or "", sheet),
                                    kind=kind, description=str(spec.get("description") or "")[:500]))
    sheet.views = [default_view(name)]
    model.save(sheet, what="made blank", by=by, origin=origin, change_id=cid or change_id())
    projection.rebuild(sheet)
    _join_workspace()
    return sheet


def create_from_rows(*, name: str, by: str, connection_id: str, sql: str, schema_name: str = "",
                     origin: str = "", cid: str = "") -> Sheet:
    """A query's rows kept as a sheet — run once more through the connection's doors (read-only), frozen as they come
    back, the statement saved beside them. A result larger than `imports.MAX_KEPT_ROWS` keeps that many and says so."""
    if not (sql or "").strip():
        raise Refused("there is no query to keep the rows of")
    if connection_id == model.SHEETS_CONNECTION or not connection_id:
        connection_id = connection_id or model.SHEETS_CONNECTION
    from aughor.db.connection import open_connection_for_with_schema
    db = open_connection_for_with_schema(connection_id, schema_name or None)
    try:
        # typed: the engine's own values, not the strings a result carries ("NULL" for an empty value)
        result, typed = db.execute_typed("sheet-keep", sql, max_rows=imports.MAX_KEPT_ROWS + 1)
    finally:
        try:
            db.close()
        except Exception as exc:  # noqa: BLE001 — the rows are already read
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the rows are read; closing their connection is best-effort", counter="sheets.keep_rows_close")
    if result.error:
        raise Refused(f"the query did not run: {str(result.error).splitlines()[0][:300]}")
    if typed and typed.get("rows") is not None:
        rows = [list(r) for r in typed["rows"]]
    else:
        rows = [[None if v == "NULL" else v for v in r] for r in (result.rows or [])]
    cut = len(rows) > imports.MAX_KEPT_ROWS
    rows = rows[:imports.MAX_KEPT_ROWS]
    name = " ".join((name or "").split())[:80] or "Kept rows"
    sheet = Sheet(id=model.new_id(), name=name, table=model.table_name(name, _taken_tables()), created_by=by,
                  created_at=model.now())
    import duckdb
    con = duckdb.connect(":memory:")
    try:
        raw_cols = imports.rows_to_raw(con, list(result.columns), rows)
        plan = _plan_columns(sheet, con, raw_cols, {}, {},
                             imports.currency_for(None, connection_id=connection_id, schema=schema_name))
        n = imports.write_source(sheet.id, con, plan)
    except imports.ImportRefused as exc:
        files.remove(sheet.id)
        raise Refused(str(exc)) from None
    finally:
        con.close()
    sheet.source = Source(kind="rows", rows=n, imported_at=model.now(), sql=sql[:20_000],
                          connection_id=connection_id, schema_name=schema_name or "",
                          file=f"the first {n:,} rows of a larger result" if cut else "")
    sheet.views = [default_view(name)]
    model.save(sheet, what="kept from a query's rows", by=by, origin=origin, change_id=cid or change_id())
    projection.rebuild(sheet)
    _join_workspace()
    return sheet


def remove(sheet: Sheet, *, by: str, what: str = "removed", cid: str = "") -> None:
    """Remove a sheet: its tombstone FIRST — the archived version that keeps its definition — then its table, its values
    and their history, and its files. A sheet whose tombstone is written stays removed whatever is left behind."""
    model.save(sheet, what=what, by=by, change_id=cid or change_id(), state="archived")
    projection.drop(sheet)
    overlay.purge_sheet(sheet.id)
    files.remove(sheet.id)


# ── values ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _stored(sheet: Sheet, ref: str) -> Column:
    c = sheet.column(ref)
    if c is None:
        raise Refused(f"{sheet.name} has no column {ref!r}")
    if c.role == "computed":
        raise Refused(f"{c.name} is computed from {c.expression}; change the expression instead")
    if c.role == "lookup":
        raise Refused(f"{c.name} is read from another sheet through a link; change it there")
    if c.role == "total":
        raise Refused(f"{c.name} is a total of another sheet's rows; change those rows instead")
    return c


def _rows_present(sheet: Sheet, rows: set[int]) -> set[int]:
    if not rows:
        return set()
    cur = projection.cursor()
    try:
        got = cur.execute(f'SELECT _row FROM {imports.ident(sheet.table)} WHERE _row IN '
                          f'({", ".join(str(int(r)) for r in rows)})').fetchall()
        return {int(r[0]) for r in got}
    finally:
        cur.close()


def set_cells(sheet: Sheet, cells: list[dict], *, by: str, origin: str = "", note: str = "", cid: str = "") -> dict:
    """Set cells — each ``{row, column, value, version}`` (``version``, the one read; omitted, unchecked) — as one
    change. Each value is read as its column's kind first; one that does not read is refused and nothing is set."""
    if not cells:
        raise Refused("there is nothing to set")
    edits: list[SheetEdit] = []
    choices_added: dict[str, list[str]] = {}
    for cell in cells:
        c = _stored(sheet, str(cell.get("column") or ""))
        try:
            value = kinds.parse(c.kind, cell.get("value"), integer=c.integer, column=c.name)
        except kinds.ValueRefused as exc:
            raise Refused(str(exc)) from None
        if c.kind == kinds.CHOICE and value is not None and value not in c.choices:
            choices_added.setdefault(c.id, []).append(value)
        version = cell.get("version")
        edits.append(SheetEdit(kind=SHEET_CELL, row=int(cell["row"]), column=c.id, body=json.dumps(value),
                               expected_version=None if version is None else int(version)))
    rows = {e.row for e in edits}
    missing = rows - _rows_present(sheet, rows)
    if missing:
        raise Refused(f"{sheet.name} has no row {min(missing)}")
    cid = cid or change_id()
    try:
        written = overlay.save_sheet_change(sheet.id, edits, change_id=cid, actor=by, origin=origin, note=note)
    except EditConflict as exc:
        raise Conflict(str(exc), exc.current) from None
    if choices_added:
        for column_id, values in choices_added.items():
            col = sheet.column(column_id)
            col.choices = [*col.choices, *dict.fromkeys(values)]
        model.save(sheet, what="new choices: " + ", ".join(v for vs in choices_added.values() for v in vs)[:200],
                   by=by, origin=origin, change_id=cid)
    projection.apply(sheet, rows)
    return {"change_id": cid, "cells": _cells_after(sheet, written)}


class Conflict(Refused):
    """A change made against a version someone has changed since."""

    def __init__(self, message: str, current: int):
        super().__init__(message)
        self.current = current


def _cells_after(sheet: Sheet, written: list[dict]) -> list[dict]:
    out = []
    by_row: dict[int, Optional[dict]] = {}
    for w in written:
        if w["kind"] != SHEET_CELL:
            continue
        r = w["row"]
        if r not in by_row:
            by_row[r] = projection.read_row(sheet, r)
        values = by_row[r] or {}
        out.append({"row": r, "column": w["column"], "value": values.get(w["column"]), "version": w["version"]})
    return out


def next_row(sheet: Sheet) -> int:
    known = [int(e.row_key) for e in overlay.sheet_values(sheet.id) if e.kind == SHEET_ROW]
    hist = [int(h["row_key"]) for h in overlay.sheet_history(sheet.id, limit=100_000) if not h["column"]]
    return max([sheet.source.rows, *known, *hist]) + 1


def add_row(sheet: Sheet, values: Optional[dict] = None, *, by: str, origin: str = "", cid: str = "") -> dict:
    """Add a row, with the values given (column → value), as one change. The row takes the next number after every
    row the sheet has ever had, so a number is never reused."""
    values = dict(values or {})
    parsed: list[tuple[Column, Any]] = []
    for ref, raw in values.items():
        c = _stored(sheet, ref)
        try:
            parsed.append((c, kinds.parse(c.kind, raw, integer=c.integer, column=c.name)))
        except kinds.ValueRefused as exc:
            raise Refused(str(exc)) from None
    cid = cid or change_id()
    for _attempt in range(5):
        n = next_row(sheet)
        edits = [SheetEdit(kind=SHEET_ROW, row=n, body="added", expected_version=0)]
        edits += [SheetEdit(kind=SHEET_CELL, row=n, column=c.id, body=json.dumps(v)) for c, v in parsed if v is not None]
        try:
            overlay.save_sheet_change(sheet.id, edits, change_id=cid, actor=by, origin=origin)
            break
        except EditConflict as exc:   # someone took that number a moment ago: take the next
            last = exc
    else:
        raise Refused(f"rows were being added too fast to number this one ({last}); add it again")
    projection.apply(sheet, {n})
    return {"change_id": cid, "row": n, "values": projection.read_row(sheet, n)}


def remove_rows(sheet: Sheet, rows: list[int], *, by: str, origin: str = "", cid: str = "") -> dict:
    """Remove rows as one change. A removed row is superseded, never deleted: undo brings it back with its values."""
    wanted = {int(r) for r in rows}
    missing = wanted - _rows_present(sheet, wanted)
    if missing:
        raise Refused(f"{sheet.name} has no row {min(missing)} to remove")
    cid = cid or change_id()
    overlay.save_sheet_change(sheet.id, [SheetEdit(kind=SHEET_ROW, row=r, body="removed") for r in sorted(wanted)],
                              change_id=cid, actor=by, origin=origin)
    projection.apply(sheet, wanted)
    return {"change_id": cid, "rows": sorted(wanted)}


# ── columns and views ────────────────────────────────────────────────────────────────────────────────────────────────

def add_column(sheet: Sheet, *, name: str, kind: str, by: str, description: str = "", origin: str = "",
               cid: str = "", made_by: str = "") -> Sheet:
    if kind not in kinds.KINDS or kind == kinds.LINK:
        raise Refused(f"{kind!r} is not a kind a column can be made with; a link is made in Combine")
    col = Column(id=sheet.new_column_id(), name=unique_name(name, sheet), kind=kind,
                 description=(description or "")[:500], made_by=made_by)
    sheet.columns.append(col)
    model.save(sheet, what=f"column {col.name} added", by=by, origin=origin, change_id=cid or change_id())
    projection.rebuild(sheet)
    return sheet


def update_column(sheet: Sheet, ref: str, *, by: str, name: Optional[str] = None, description: Optional[str] = None,
                  kind: Optional[str] = None, hidden: Optional[bool] = None, before: Optional[str] = None,
                  cid: str = "") -> Sheet:
    """Rename a column, describe it, hide it, change its kind — only to a kind every value it holds reads as — or move
    it: ``before`` names the column it goes in front of, ``""`` the end. A move is the sheet's, as a spreadsheet's
    column order is: everyone who reads the sheet sees it, and undo puts it back."""
    c = sheet.column(ref)
    if c is None:
        raise Refused(f"{sheet.name} has no column {ref!r}")
    said = []
    moved = False
    if before is not None:
        target = sheet.column(before) if before else None
        if before and target is None:
            raise Refused(f"{sheet.name} has no column {before!r} to put {c.name} before")
        if target is None or target.id != c.id:
            rest = [x for x in sheet.columns if x.id != c.id]
            at = rest.index(target) if target is not None else len(rest)
            order = rest[:at] + [c] + rest[at:]
            if [x.id for x in order] != [x.id for x in sheet.columns]:
                sheet.columns = order
                moved = True
                said.append(f"{c.name} moved " + (f"before {target.name}" if target is not None else "to the end"))
    if name is not None and name.strip() and name.strip() != c.name:
        said.append(f"{c.name} renamed {name.strip()}")
        c.name = unique_name(name, sheet, but=c.id)
    if description is not None and description != c.description:
        c.description = description[:500]
        said.append(f"{c.name} described")
    if hidden is not None and hidden != c.hidden:
        c.hidden = bool(hidden)
        said.append(f"{c.name} {'hidden' if hidden else 'shown'}")
    if kind is not None and kind != c.kind:
        if c.role != "stored" or kind == kinds.LINK or kind not in kinds.KINDS:
            raise Refused(f"{c.name}'s kind cannot be changed to {kind!r} here")
        misfit = _misfits_as(sheet, c, kind)
        if misfit:
            raise Refused(f"{misfit:,} value{'s' if misfit != 1 else ''} in {c.name} do not read as "
                          f"{kinds.LABELS[kind]}, so its kind stays {kinds.LABELS[c.kind]}")
        said.append(f"{c.name} is now {kinds.LABELS[kind]}")
        c.kind = kind
        c.integer = kind == kinds.NUMBER and _all_whole(sheet, c)
    if not said:
        return sheet
    model.save(sheet, what="; ".join(said), by=by, change_id=cid or change_id())
    # the table reads its columns by name, in the sheet's order — a move alone changes nothing in it
    if len(said) > 1 or not moved:
        projection.rebuild(sheet)
    return sheet


def _misfits_as(sheet: Sheet, c: Column, kind: str) -> int:
    cur = projection.cursor()
    try:
        col = imports.ident(c.name)
        text = f"CAST({col} AS VARCHAR)"
        fit = cur.execute(f"SELECT {kinds.fit_sql(text)} FROM {imports.ident(sheet.table)}")
        names = [d[0] for d in fit.description]
        row = dict(zip(names, fit.fetchone()))
        return kinds.fit_from_row(row, [], None).misfits.get(kind, 0) if kind != kinds.TEXT else 0
    finally:
        cur.close()


def _all_whole(sheet: Sheet, c: Column) -> bool:
    cur = projection.cursor()
    try:
        col = imports.ident(c.name)
        n = cur.execute(f"SELECT COUNT(*) FROM {imports.ident(sheet.table)} WHERE {col} IS NOT NULL AND NOT "
                        f"regexp_full_match(TRIM(CAST({col} AS VARCHAR)), '-?[0-9]+(\\.0+)?')").fetchone()[0]
        return int(n) == 0
    finally:
        cur.close()


def remove_column(sheet: Sheet, ref: str, *, by: str, cid: str = "") -> Sheet:
    """Take a column off a sheet. Its values stay in the source and the edit layer, so undo brings it back whole."""
    c = sheet.column(ref)
    if c is None:
        raise Refused(f"{sheet.name} has no column {ref!r}")
    users = [o.name for o in sheet.columns if (o.role == "lookup" and o.via == c.id) or (o.role == "total" and o.by == c.id)
             or (o.role == "computed" and f'"{c.name}"' in o.expression)]
    if users:
        raise Refused(f"{', '.join(users)} read{'s' if len(users) == 1 else ''} {c.name}; take "
                      f"{'it' if len(users) == 1 else 'them'} off first")
    sheet.columns = [o for o in sheet.columns if o.id != c.id]
    for v in sheet.views:
        v.filter = [f for f in v.filter if f.column != c.id]
        v.sort = [s for s in v.sort if s.get("column") != c.id]
        v.card = [x for x in v.card if x != c.id]
        if v.group == c.id:
            v.group = ""
            if v.kind == "board":    # a board without its lanes is the grid it was read from
                v.kind = "grid"
        if v.date == c.id:
            v.date, v.kind = "", "grid"
    said = ""
    for r in sheet.rules:
        r.conditions = [x for x in r.conditions if x.column != c.id]
    emptied = [r.name for r in sheet.rules if not r.conditions]
    if emptied:
        # a rule left with no condition would mark every row; it goes with the column it read, and undo brings it back
        sheet.rules = [r for r in sheet.rules if r.conditions]
        said = f"; rule{'s' if len(emptied) != 1 else ''} {', '.join(emptied)} went with it"
    model.save(sheet, what=f"column {c.name} taken off{said}", by=by, change_id=cid or change_id())
    projection.rebuild(sheet)
    return sheet


def _view_words(view: View) -> str:
    """How a view is named in the sheet's history, which everyone who reads the sheet sees: the name of a view its maker
    its maker's, so the history says only that one was kept."""
    return f"view {view.name}" if view.shared else "a view of their own"


def save_view(sheet: Sheet, view: View, *, by: str, origin: str = "", cid: str = "") -> Sheet:
    """Keep a view — a new one, or the next version of one that stands (by id). Its filter and its layout are read
    before it is kept, so a view that names no column, holds a value its column cannot, or lays its rows out by a
    column of the wrong kind is refused. A view kept to oneself is its maker's: no one else sees it or changes it, and a
    shared view is kept to its maker only in its maker's hands, while one other shared view stands."""
    from aughor.sheets.views import ViewRefused, check_view
    try:
        check_view(sheet, view)
    except ViewRefused as exc:
        raise Refused(str(exc)) from None
    view.name = " ".join((view.name or "").split())[:80] or "View"
    view.id = view.id or uuid.uuid4().hex[:8]
    known = {c.id for c in sheet.columns}
    view.hidden = [h for h in view.hidden if h in known]
    replaced = next((i for i, v in enumerate(sheet.views) if v.id == view.id), None)
    if replaced is None:
        view.owner = by
        taken = {v.name.lower() for v in sheet.views_for(by)}
        base, n = view.name, 2
        while view.name.lower() in taken:
            view.name, n = f"{base} {n}", n + 1
        sheet.views.append(view)
    else:
        standing = sheet.views[replaced]
        if not standing.shared and standing.owner != by:
            raise Refused(f"{sheet.name} has no view {view.id!r}")
        view.owner = standing.owner
        if standing.shared and not view.shared:
            if standing.owner != by:
                raise Refused(f"only the person who made {standing.name} can keep it to themselves; keep a copy of "
                              "your own instead")
            if not any(v.shared for v in sheet.views if v.id != view.id):
                raise Refused("a sheet keeps at least one shared view")
        sheet.views[replaced] = view
    model.save(sheet, what=f"{_view_words(view)} {'kept' if replaced is None else 'changed'}", by=by, origin=origin,
               change_id=cid or change_id())
    return sheet


def remove_view(sheet: Sheet, view_id: str, *, by: str, cid: str = "") -> Sheet:
    view = next((v for v in sheet.views_for(by) if v.id == view_id), None)
    if view is None:
        raise Refused(f"{sheet.name} has no view {view_id!r}")
    if view.shared and not any(v.shared for v in sheet.views if v.id != view_id):
        raise Refused("a sheet keeps at least one shared view")
    sheet.views = [v for v in sheet.views if v.id != view_id]
    model.save(sheet, what=f"{_view_words(view)} taken off", by=by, change_id=cid or change_id())
    return sheet


def save_rule(sheet: Sheet, rule: Rule, *, by: str, origin: str = "", cid: str = "") -> Sheet:
    """Keep a rule — new, or the next version of one that stands — after reading its conditions as a view's filter is
    read, so a rule marks exactly the rows a view with those conditions shows."""
    from aughor.sheets.views import TONES, ViewRefused, check_rule
    try:
        check_rule(sheet, rule.conditions)
    except (ViewRefused, projection.FilterRefused) as exc:
        raise Refused(str(exc)) from None
    rule.name = " ".join((rule.name or "").split())[:80]
    if not rule.name:
        raise Refused("a rule needs a name — what the rows it marks have in common")
    if rule.tone not in TONES:
        raise Refused(f"{rule.tone!r} is not a mark's colour; it is one of {', '.join(TONES)}")
    rule.id = rule.id or uuid.uuid4().hex[:8]
    if any(r.name.lower() == rule.name.lower() and r.id != rule.id for r in sheet.rules):
        raise Refused(f"{sheet.name} already has a rule called {rule.name}")
    replaced = next((i for i, r in enumerate(sheet.rules) if r.id == rule.id), None)
    if replaced is None:
        sheet.rules.append(rule)
    else:
        sheet.rules[replaced] = rule
    model.save(sheet, what=f"rule {rule.name} {'kept' if replaced is None else 'changed'}", by=by, origin=origin,
               change_id=cid or change_id())
    return sheet


def remove_rule(sheet: Sheet, rule_id: str, *, by: str, cid: str = "") -> Sheet:
    rule = next((r for r in sheet.rules if r.id == rule_id), None)
    if rule is None:
        raise Refused(f"{sheet.name} has no rule {rule_id!r}")
    def reads(v: View) -> bool:
        return any(f.op in ("marked", "not_marked") and f.value == rule_id for f in v.filter)

    users = [v.name for v in sheet.views if v.shared and reads(v)]
    if users:
        raise Refused(f"the view{'s' if len(users) != 1 else ''} {', '.join(users)} show{'' if len(users) != 1 else 's'} "
                      f"the rows {rule.name} marks; change {'them' if len(users) != 1 else 'it'} first")
    # a view kept to its maker is theirs to change, so the condition on the rule leaves it, said in the history
    own = [v for v in sheet.views if not v.shared and reads(v)]
    for v in own:
        v.filter = [f for f in v.filter if not (f.op in ("marked", "not_marked") and f.value == rule_id)]
    sheet.rules = [r for r in sheet.rules if r.id != rule_id]
    said = f"; {len(own)} view{'s' if len(own) != 1 else ''} of people's own no longer filter by it" if own else ""
    model.save(sheet, what=f"rule {rule.name} taken off{said}", by=by, change_id=cid or change_id())
    return sheet


def rename(sheet: Sheet, name: str, *, by: str, cid: str = "") -> Sheet:
    name = " ".join((name or "").split())[:80]
    if not name or name == sheet.name:
        return sheet
    old_table = sheet.table
    old = sheet.name
    sheet.name = name
    sheet.table = model.table_name(name, _taken_tables(but=sheet.id))
    model.save(sheet, what=f"renamed from {old}", by=by, change_id=cid or change_id())
    projection.rename(sheet, old_table)
    return sheet


# ── the history, undo and redo ───────────────────────────────────────────────────────────────────────────────────────

def changes(sheet: Sheet, *, limit: int = 200) -> list[dict]:
    """Every change to a sheet, newest first, one row each: its id, what it was, who made it, when, what made it, and
    how many values it changed. A change that touched the definition and the values is one row."""
    out: dict[str, dict] = {}
    for version in model.history(sheet.id, limit=limit):
        ch = version.change
        if not ch.id:
            continue
        out.setdefault(ch.id, {"id": ch.id, "what": ch.what, "by": ch.by, "at": ch.at, "origin": ch.origin,
                               "values": 0, "definition": version.version})
    for row in overlay.sheet_changes(sheet.id, limit=limit):
        entry = out.setdefault(row["change_id"], {"id": row["change_id"], "what": "", "by": row["actor"],
                                                  "at": row["at"], "origin": row["origin"], "values": 0,
                                                  "definition": 0})
        entry["values"] = int(row["edits"] or 0)
        if not entry["what"]:
            entry["what"] = f"{entry['values']} value{'s' if entry['values'] != 1 else ''} changed"
        entry["at"] = max(str(entry["at"] or ""), str(row["at"] or ""))
    return sorted(out.values(), key=lambda e: str(e["at"]), reverse=True)[:limit]


def stacks(sheet: Sheet, by: str) -> tuple[list[dict], list[dict]]:
    """This person's done and undone changes, replayed oldest first: (what undo takes back, what redo puts back)."""
    done: list[dict] = []
    undone: list[dict] = []
    for ch in reversed(changes(sheet, limit=1000)):
        if ch["by"] != by:
            continue
        origin = str(ch["origin"] or "")
        if origin.startswith("undo:"):
            target = origin.split(":", 1)[1]
            if done and done[-1]["id"] == target:
                undone.append({**done.pop(), "undo": ch["id"]})
        elif origin.startswith("redo:"):
            target = origin.split(":", 1)[1]
            if undone and undone[-1].get("undo") == target:
                undone.pop()
                done.append(ch)
        else:
            done.append(ch)
            undone.clear()
    return done, undone


def made_it(sheet: Sheet, change_id: str) -> bool:
    """Whether a change is the one that made the sheet — undoing it removes the sheet."""
    versions = model.history(sheet.id, limit=1000)
    return bool(versions) and versions[-1].change.id == change_id


def undo(sheet: Sheet, *, by: str, removing: bool = False) -> dict:
    """Take back this person's latest change to the sheet, whole. Undoing the change that made the sheet removes it, so
    it is done only when asked for by name (``removing`` — the proposal card's "Undo — remove the sheet"), never by the
    toolbar's undo."""
    done, _ = stacks(sheet, by)
    if not done:
        raise Refused("you have made no change to this sheet that can be undone")
    target = done[-1]
    if made_it(sheet, target["id"]) and not removing:
        raise Refused("the last change here made the sheet; undoing it would remove the sheet — remove it from "
                      "Spreadsheets if that is what you mean")
    return _reverse(sheet, target, by=by, origin=f"undo:{target['id']}", what=f"undid: {target['what']}")


def redo(sheet: Sheet, *, by: str) -> dict:
    """Put back the change this person last undid."""
    _, undone = stacks(sheet, by)
    if not undone:
        raise Refused("there is nothing undone to redo")
    target = undone[-1]
    undo_change = next((c for c in changes(sheet, limit=1000) if c["id"] == target["undo"]), None)
    if undo_change is None:
        raise Refused("the undo to take back is no longer in the sheet's history")
    return _reverse(sheet, undo_change, by=by, origin=f"redo:{undo_change['id']}", what=f"redid: {target['what']}")


def _reverse(sheet: Sheet, change: dict, *, by: str, origin: str, what: str) -> dict:
    """A change that puts back what ``change`` replaced — its values and its definition — refused when someone has
    changed over it since."""
    cid = change_id()
    rows_touched: set[int] = set()
    history = overlay.sheet_history(sheet.id, change_id=change["id"], limit=100_000)
    edits: list[SheetEdit] = []
    seen: set[str] = set()
    # the change's last write to each value (newest first), and what stood before its first
    first_previous: dict[str, str] = {}
    for h in reversed(history):
        first_previous.setdefault(h["edit_id"], h["previous"])
    for h in history:
        if h["edit_id"] in seen:
            continue
        seen.add(h["edit_id"])
        previous = first_previous[h["edit_id"]]
        kind = SHEET_ROW if not h["column"] else SHEET_CELL
        row = int(h["row_key"])
        rows_touched.add(row)
        if previous == "":
            edits.append(SheetEdit(kind=kind, row=row, column=h["column"], withdraw=True,
                                   expected_version=int(h["version"])))
        else:
            edits.append(SheetEdit(kind=kind, row=row, column=h["column"], body=previous,
                                   expected_version=int(h["version"])))
    definition = None
    if change.get("definition"):
        versions = model.history(sheet.id, limit=1000)
        # every version the change kept (making a sheet and folding in what was proposed for it is one change)
        mine = [i for i, v in enumerate(versions) if v.change.id == change["id"]]
        if mine:
            if mine[0] != 0:
                newer = versions[0].change
                raise Refused(f"the sheet was changed since — {newer.what} by {newer.by} — so this cannot be undone "
                              "on its own; undo that first")
            before = max(mine) + 1
            definition = versions[before] if before < len(versions) else None
            if definition is None:
                # the change made the sheet: taking it back removes it whole
                remove(sheet, by=by, what=what, cid=cid)
                return {"change_id": cid, "removed": True, "sheet": None}
    try:
        overlay.save_sheet_change(sheet.id, edits, change_id=cid, actor=by, origin=origin, note=what[:200])
    except EditConflict as exc:
        raise Refused(f"a value this change set was changed since — {exc}") from None
    if definition is not None:
        restored = Sheet(**definition.model_dump(exclude={"version", "state", "change"}))
        restored = model.save(restored, what=what, by=by, origin=origin, change_id=cid)
        if restored.table != sheet.table:
            projection.rename(restored, sheet.table)
        else:
            projection.rebuild(restored)
        sheet = restored
    elif rows_touched:
        projection.apply(sheet, rows_touched)
    return {"change_id": cid, "removed": False, "sheet": sheet}


# ── a cell's and a row's story ───────────────────────────────────────────────────────────────────────────────────────

def value_of(body: str) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        return body


def origin_of_row(sheet: Sheet, row: int) -> str:
    if row <= sheet.source.rows and sheet.source.kind == "file":
        return f"imported from {sheet.source.file}, row {row:,}"
    if row <= sheet.source.rows and sheet.source.kind == "rows":
        return f"kept from a query's rows, row {row:,}"
    return "added in the sheet"


def cell_history(sheet: Sheet, row: int, column: str) -> dict:
    """Where a cell's value came from, and every change to it since, newest first."""
    c = sheet.column(column)
    if c is None:
        raise Refused(f"{sheet.name} has no column {column!r}")
    events = [{"event": h["event"], "value": value_of(h["body"]) if h["event"] == "set" else None,
               "previous": value_of(h["previous"]) if h["previous"] else None, "by": h["actor"], "at": h["at"],
               "origin": h["origin"], "version": int(h["version"]), "change_id": h.get("change_id", "")}
              for h in overlay.sheet_history(sheet.id, row=row, column=c.id)]
    if c.role == "computed":
        came = f"computed from {c.expression}"
    elif c.role == "lookup":
        came = "read from another sheet through a link"
    elif c.role == "total":
        came = "a total of another sheet's rows"
    else:
        came = origin_of_row(sheet, row) if c.source or row > sheet.source.rows else "a column added in the sheet"
    current = next((e["version"] for e in events), 0)
    return {"row": row, "column": c.id, "came_from": came, "events": events, "version": current,
            "changed": bool(events) and events[0]["event"] == "set"}
