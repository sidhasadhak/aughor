"""What a person does to a sheet — make one, change its values and columns, undo, remove it (Arc SH, SH-1 and SH-2).

Every act is ONE change with its own id: the edits it wrote to the edit layer and the definition version it kept carry
the same id, so undo and redo take it back whole. Each is recorded under the person who made it (``by``); one the
assistant proposed carries ``origin`` ``proposal:<id>`` and is recorded as proposed by the assistant and applied by the
person — a model never changes a sheet on its own.

**Undo is the changes' own history.** Undoing a change writes a new change that puts back what it replaced, with
``origin`` ``undo:<id>``; redoing writes the reverse of that. Nothing is deleted to undo, and a change that someone has
changed over since is refused, naming who, rather than undone over their work.

**Putting back is one value's own history.** Undo takes back a person's latest change, whole. `put_back` reaches any change
anyone made, down to one cell or one row, and touches nothing else: a new change with ``origin`` ``put_back:<id>``, every
value it replaces kept in the history. The source file is never written; a sheet's values are its source with these
changes over it.
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


def _taken_tables() -> set[str]:
    return {s.table for s in model.list_sheets()}


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
        raise Conflict(stale_words(sheet, exc, by), exc.current) from None
    if choices_added:
        for column_id, values in choices_added.items():
            col = sheet.column(column_id)
            col.choices = [*col.choices, *dict.fromkeys(values)]
        model.save(sheet, what="new choices: " + ", ".join(dict.fromkeys(v for vs in choices_added.values() for v in vs))[:200],
                   by=by, origin=origin, change_id=cid)
    projection.apply(sheet, rows)
    return {"change_id": cid, "cells": _cells_after(sheet, written)}


class Conflict(Refused):
    """A change made against a version someone has changed since."""

    def __init__(self, message: str, current: int):
        super().__init__(message)
        self.current = current


def stale_words(sheet: Sheet, exc: EditConflict, by: str, *, undoing: bool = False) -> str:
    """A change refused because a cell was changed after it was read, as a person says it — who changed which cell, and
    when (SH-8): "ana changed order_status in row 12 at 18:01 UTC, after you read it, so your change was not made." A
    change of the asker's own since this page read the cell — another window, an undo — is said as theirs."""
    from aughor.sheets.sharing import person_name
    col = sheet.column(exc.column) if exc.column else None
    cell = f"{col.name if col else 'a value'} in row {exc.row}" if exc.row is not None else "a value"
    when = ""
    if exc.at:
        day, _, clock = exc.at.replace("T", " ").partition(" ")
        when = f" at {clock[:5]} UTC" + ("" if day == model.now()[:10] else f" on {day}")
    if not exc.by:
        # no change to the cell on record: the version this page sent is not one the cell has had — never "someone"
        return (f"Nobody has changed {cell}, and this page sent a version it never had, so "
                f"{'this cannot be undone over it' if undoing else 'your change was not made'}. The grid now shows it "
                "as it stands; change it again if you still mean to.")
    if undoing:
        who = "You" if exc.by == by else person_name(exc.by)
        return f"{who} changed {cell}{when} since, so this cannot be undone over it; change the cell instead."
    if exc.by == by:
        return (f"You changed {cell}{when}, after this page read it, so this change was not made. The grid now shows "
                "that value; change it again if you still mean to.")
    who = person_name(exc.by)
    return (f"{who} changed {cell}{when}, after you read it, so your change was not made. The grid now shows "
            f"{who}'s value; change it again if you still mean to.")


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
    """A new name for a sheet. Its table keeps the name it was made with: a sheet's name is free and its table is what
    everything else reads, so every card and statement that names it goes on reading it, and a new sheet of the old name
    takes a table of its own rather than this one's readers."""
    name = " ".join((name or "").split())[:80]
    if not name or name == sheet.name:
        return sheet
    old = sheet.name
    sheet.name = name
    model.save(sheet, what=f"renamed from {old}", by=by, change_id=cid or change_id())
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
            entry["what"] = row["note"] or f"{entry['values']} value{'s' if entry['values'] != 1 else ''} changed"
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


def _holds(definition: Sheet) -> dict:
    """What a version of a sheet's definition holds — its name, columns, views, rules and source — without the record of
    who kept it, when, and as which version."""
    return definition.model_dump(exclude={"version", "state", "change"})


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
            # Undone only where the sheet's definition is still what this change left: putting back the version before
            # it then loses nothing. That holds after newer changes that were themselves undone — so undo steps back
            # through several changes in a row, and redo forward again — and fails after a change still standing over
            # it, which this would silently discard. Compared by what a definition holds, never by which version is
            # newest: an undo is a newer version that holds an older definition (two renames undone in a row were
            # refused at the second, "undo that first", when the first had been).
            if mine[0] != 0 and _holds(versions[0]) != _holds(versions[mine[0]]):
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
        raise Refused(stale_words(sheet, exc, by, undoing=True)) from None
    if definition is not None:
        restored = Sheet(**definition.model_dump(exclude={"version", "state", "change"}))
        restored = model.save(restored, what=what, by=by, origin=origin, change_id=cid)
        if restored.table != sheet.table:
            # a version kept before a rename stopped moving the table
            projection.rename(restored, sheet.table)
        else:
            projection.rebuild(restored)
        sheet = restored
    elif rows_touched:
        projection.apply(sheet, rows_touched)
    return {"change_id": cid, "removed": False, "sheet": sheet}


# ── a cell's and a row's story ───────────────────────────────────────────────────────────────────────────────────────

def row_title(sheet: Sheet, values: dict) -> str:
    """What a row is called: its key's value, or its first text column's."""
    first = sheet.column(sheet.key) if sheet.key else None
    first = first or next((c for c in sheet.columns if c.kind in ("text", "email", "link")), None)
    v = values.get(first.id) if first else None
    return "" if v is None else str(v)


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
    current = next((e["version"] for e in events), 0)
    return {"row": row, "column": c.id, "came_from": _came_from(sheet, c, row), "events": events, "version": current,
            "changed": bool(events) and events[0]["event"] == "set"}


def _came_from(sheet: Sheet, c: Column, row: int) -> str:
    if c.role == "computed":
        return f"computed from {c.expression}"
    if c.role == "lookup":
        return "read from another sheet through a link"
    if c.role == "total":
        return "a total of another sheet's rows"
    return origin_of_row(sheet, row) if c.source or row > sheet.source.rows else "a column added in the sheet"


# ── what changed, value by value, and putting one back ───────────────────────────────────────────────────────────────

#: How many of a change's edits the history reads at once, how many lines it shows of each, and the most one change lists.
CHANGE_READ = 200
LINES_SHOWN = 5
LINES_MAX = 1000
#: The most changes one reading of a row's or a cell's story covers.
STORY_READ = 2000


def _edits_of(rows: list[dict]) -> list[tuple[dict, dict]]:
    """Each value a change touched, once, as (its last write, its first): a change can write one value twice, and what
    it replaced is what stood before the first."""
    last: dict[str, dict] = {}
    first: dict[str, dict] = {}
    for h in rows:             # newest first
        last.setdefault(h["edit_id"], h)
        first[h["edit_id"]] = h
    return [(last[k], first[k]) for k in last]


def _added_by(edits: list[tuple[dict, dict]]) -> set[str]:
    """The rows a change brought into being."""
    return {last["row_key"] for last, first in edits if not last["column"] and last["body"] == "added" and not first["previous"]}


def _same_value(a: Any, b: Any) -> bool:
    if a in (None, "") or b in (None, ""):
        return a in (None, "") and b in (None, "")
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a).replace("T", " ") == str(b).replace("T", " ")


def _was_there(sheet: Sheet, row: int, state: str) -> bool:
    """Whether a row stands, given its row edit's state: "added", "removed", or none — what its source says."""
    return state == "added" or (not state and row <= sheet.source.rows)


def _lines(sheet: Sheet, changes_edits: dict[str, list[tuple[dict, dict]]], *, shown: int) -> dict[str, list[dict]]:
    """Changes' edits as lines a person reads: which cell or row, what it held before and after, what it holds now, and
    whether it can be put back. A row a change added is one line, the values it came with inside it."""
    picked: dict[str, list[tuple[dict, dict]]] = {}
    came_with: dict[str, dict[str, dict]] = {}
    for cid, edits in changes_edits.items():
        added = _added_by(edits)
        came_with[cid] = {r: {} for r in added}
        for last, _ in edits:
            if last["column"] and last["row_key"] in added and last["event"] == "set":
                came_with[cid][last["row_key"]][last["column"]] = value_of(last["body"])
        picked[cid] = [e for e in edits if not e[0]["column"] or e[0]["row_key"] not in added][:shown]
    rows = {int(last["row_key"]) for edits in picked.values() for last, _ in edits}
    standing = projection.rows_by_number(sheet, rows)
    source = projection.source_rows(sheet, rows)
    versions = overlay.sheet_versions(sheet.id, rows, with_rows=True)
    out: dict[str, list[dict]] = {}
    for cid, edits in picked.items():
        out[cid] = []
        for last, first in edits:
            row = int(last["row_key"])
            column = last["column"]
            line: dict[str, Any] = {"row": row, "column": column, "current": versions.get((row, column), 0),
                                    "stands": versions.get((row, column), 0) == int(last["version"]), "blocked": ""}
            now = standing.get(row)
            line["title"] = row_title(sheet, now or source.get(row) or {})
            if not column:
                state = last["body"] if last["event"] == "set" else ""
                before, after = _was_there(sheet, row, first["previous"]), _was_there(sheet, row, state)
                written = {(c.name if (c := sheet.column(k)) else k): v
                           for k, v in came_with[cid].get(last["row_key"], {}).items() if v is not None}
                line.update(kind="row", name="", what="added" if after and not before else "removed" if before and not after
                            else "", values=written, same=(now is not None) == before)
            else:
                c = sheet.column(column)
                held = (source.get(row) or {}).get(column)
                was = value_of(first["previous"]) if first["previous"] else held
                line.update(kind="cell", name=c.name if c else "a column since removed", what="set", **{"from": was},
                            to=value_of(last["body"]) if last["event"] == "set" else held,
                            now=(now or {}).get(column), same=now is not None and _same_value((now or {}).get(column), was))
                if c is None or c.role != "stored":
                    line["blocked"] = "its column has since been removed"
                elif now is None:
                    line["blocked"] = f"row {row:,} has since been removed; put the row back first"
            out[cid].append(line)
    return out


def _count_words(lines: list[dict]) -> str:
    """What a change of many lines did, counted as a person would: "3 rows removed", "12 values changed"."""
    def many(n: int, one: str) -> str:
        return f"{n:,} {one}{'s' if n != 1 else ''}"
    cells = sum(1 for ln in lines if ln["kind"] == "cell")
    added = sum(1 for ln in lines if ln["kind"] == "row" and ln["what"] == "added")
    removed = sum(1 for ln in lines if ln["kind"] == "row" and ln["what"] == "removed")
    said = [f"{many(added, 'row')} added" if added else "", f"{many(removed, 'row')} removed" if removed else "",
            f"{many(cells, 'value')} changed" if cells else ""]
    return ", ".join(w for w in said if w)


def history(sheet: Sheet, *, row: Optional[int] = None, column: str = "", limit: int = 100) -> dict:
    """What changed, newest first, value by value: every change to the sheet with the first of its lines — or, given a
    row or a cell, that row's or cell's whole story, from where it came from to what it holds now."""
    if row is None:
        rows = changes(sheet, limit=limit + 1)
        more, rows = len(rows) > limit, rows[:limit]
        read = overlay.sheet_change_edits(sheet.id, [c["id"] for c in rows if c["values"]], per_change=CHANGE_READ)
        edits = {cid: _edits_of(got) for cid, got in read.items()}
        lines = _lines(sheet, edits, shown=LINES_SHOWN)
        for c in rows:
            got = edits.get(c["id"], [])
            added = _added_by(got)
            total = sum(1 for last, _ in got if not last["column"] or last["row_key"] not in added)
            whole = len(read.get(c["id"], [])) < CHANGE_READ
            if not whole:
                total = overlay.sheet_change_lines(sheet.id, c["id"])
            c.update(lines=lines.get(c["id"], []), lines_total=total)
            # the words a change's own lines earn, once all of them are in hand; what a person or a model said stands
            if whole and total <= LINES_SHOWN and got and not c["definition"] and not got[0][0]["note"]:
                c["what"] = _count_words(c["lines"]) or c["what"]
        return {"changes": rows, "more": more, "scope": None}
    c = None
    if column:
        c = sheet.column(column)
        if c is None:
            raise Refused(f"{sheet.name} has no column {column!r}")
    raw = overlay.sheet_history(sheet.id, row=row, column=column, limit=STORY_READ)
    grouped: dict[str, list[dict]] = {}
    for h in raw:
        grouped.setdefault(h["change_id"], []).append(h)
    edits = {cid: _edits_of(got) for cid, got in grouped.items()}
    lines = _lines(sheet, edits, shown=STORY_READ)
    rows = [{"id": cid, "what": got[0]["note"] or "", "by": got[0]["actor"], "at": got[0]["at"], "origin": got[0]["origin"],
             "values": len(got), "definition": 0, "lines": lines[cid], "lines_total": len(lines[cid])}
            for cid, got in grouped.items()][:limit]
    now = projection.rows_by_number(sheet, {row}).get(row)
    values = now or projection.source_rows(sheet, {row}).get(row) or {}
    return {"changes": rows, "more": len(grouped) > limit,
            "scope": {"row": row, "column": column, "name": c.name if c else "", "title": row_title(sheet, values),
                      "removed": now is None, "now": (now or {}).get(column) if column else None,
                      "came_from": _came_from(sheet, c, row) if c else origin_of_row(sheet, row)}}


def change_lines(sheet: Sheet, change: str) -> dict:
    """All of one change's lines, up to `LINES_MAX`, for a person who asked to see them all."""
    edits = _edits_of(overlay.sheet_history(sheet.id, change_id=change, limit=LINES_MAX * 20))
    if not edits:
        raise Refused("this change holds no values, or is no longer in the sheet's history")
    return {"lines": _lines(sheet, {change: edits}, shown=LINES_MAX)[change], "total": overlay.sheet_change_lines(sheet.id, change)}


def _brief(value: Any) -> str:
    if value in (None, ""):
        return "empty"
    words = str(value)
    return words if len(words) <= 40 else f"{words[:39]}…"


def _put_back_edit(sheet: Sheet, last: dict, first: dict, *, expected: int) -> SheetEdit:
    """The edit that returns one value to what ``first`` replaced — and only that value."""
    row = int(last["row_key"])
    if not last["column"]:
        if _was_there(sheet, row, first["previous"]):
            if row <= sheet.source.rows and first["previous"] != "added":
                return SheetEdit(kind=SHEET_ROW, row=row, withdraw=True, expected_version=expected)
            return SheetEdit(kind=SHEET_ROW, row=row, body="added", expected_version=expected)
        # a row taken out stays superseded with its values, as any removed row does: putting it back brings them too
        return SheetEdit(kind=SHEET_ROW, row=row, body="removed", expected_version=expected)
    if not first["previous"]:
        return SheetEdit(kind=SHEET_CELL, row=row, column=last["column"], withdraw=True, expected_version=expected)
    return SheetEdit(kind=SHEET_CELL, row=row, column=last["column"], body=first["previous"], expected_version=expected)


def put_back(sheet: Sheet, *, change: str, by: str, row: Optional[int] = None, column: str = "",
             current: Optional[int] = None) -> dict:
    """Return what a change touched to what it replaced, leaving every other value exactly as it stands: one cell or one
    row of it (``row``, with ``column`` for a cell), or the whole change.

    **One value** goes back whatever has happened to it since, because the person is looking at it and asked for that
    state: ``current``, the version they read, refuses it when someone has changed it after they read it. **A whole
    change** goes back only where it still stands: a value changed since is someone's newer decision, so it is left alone
    and named. Either way this is a new change in the history, undone like any other."""
    edits = _edits_of(overlay.sheet_history(sheet.id, change_id=change, limit=1_000_000))
    if not edits:
        raise Refused("this change holds no values to put back, or is no longer in the sheet's history")
    added = _added_by(edits)
    if row is not None:
        edits = [e for e in edits if int(e[0]["row_key"]) == int(row) and e[0]["column"] == column]
        if not edits:
            raise Refused(f"this change did not touch {'that cell' if column else 'that row'}")
    else:
        edits = [e for e in edits if not e[0]["column"] or e[0]["row_key"] not in added]
    rows = {int(last["row_key"]) for last, _ in edits}
    versions = overlay.sheet_versions(sheet.id, rows, with_rows=True)
    present = _rows_present(sheet, rows)
    writes: list[SheetEdit] = []
    left: list[dict] = []
    choices: dict[str, list[str]] = {}
    for last, first in edits:
        r, col = int(last["row_key"]), last["column"]
        at = versions.get((r, col), 0)
        c = sheet.column(col) if col else None
        gone = bool(col) and (c is None or c.role != "stored" or r not in present)
        if row is not None and gone:
            raise Refused(f"its column has since been removed, so {'this' if c is None else c.name} cannot be put back"
                          if c is None or c.role != "stored" else f"row {r:,} has since been removed; put the row back first")
        if row is None and (gone or at != int(last["version"])):
            newest = next(iter(overlay.sheet_history(sheet.id, row=r, column=col, limit=1)), None) if not gone else None
            left.append({"row": r, "column": col, "name": c.name if c else "", "by": newest["actor"] if newest else "",
                         "at": newest["at"] if newest else ""})
            continue
        if c is not None and c.kind == kinds.CHOICE and first["previous"]:
            value = value_of(first["previous"])
            if value is not None and value not in c.choices:
                choices.setdefault(c.id, []).append(value)
        writes.append(_put_back_edit(sheet, last, first, expected=at if row is None or current is None else int(current)))
    if not writes:
        raise Refused("every value of this change has been changed since, so there is nothing of it to put back")
    if row is not None:
        last, first = edits[0]
        if column:
            held = (projection.source_rows(sheet, {int(row)}).get(int(row)) or {}).get(column)
            what = (f"{sheet.column(column).name} in row {int(row):,} put back to "
                    f"{_brief(value_of(first['previous']) if first['previous'] else held)}")
        else:
            what = f"row {int(row):,} {'put back' if _was_there(sheet, int(row), first['previous']) else 'taken out'}"
    else:
        what = f"{len(writes):,} value{'s' if len(writes) != 1 else ''} put back"
    cid = change_id()
    try:
        written = overlay.save_sheet_change(sheet.id, writes, change_id=cid, actor=by, origin=f"put_back:{change}",
                                            note=what[:200])
    except EditConflict as exc:
        raise Conflict(stale_words(sheet, exc, by), exc.current) from None
    if not written:
        raise Refused("it already holds that")
    if choices:
        for column_id, values in choices.items():
            col = sheet.column(column_id)
            col.choices = [*col.choices, *dict.fromkeys(values)]
        model.save(sheet, what=what, by=by, origin=f"put_back:{change}", change_id=cid)
    projection.apply(sheet, {w.row for w in writes})
    # a column's name is said as it is spelled
    said = what if row is not None and column else what[0].upper() + what[1:]
    if left:
        said += f"; {len(left):,} changed since left as {'they are' if len(left) != 1 else 'it is'}"
    return {"change_id": cid, "put_back": len(written), "left": left, "said": said}
