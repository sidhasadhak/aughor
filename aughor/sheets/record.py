"""A row opened as a record: every field and where it came from, its linked rows, its history, its comments (SH-2).

A comment is a **said claim in the Record**, as a Google comment on a decision already is (``record/google_comments``):
booked at tier ``said`` in its author's name, about the sheet's row, and readable by whoever can read the row. It is a
statement a person made, never a value of the sheet and never counted in one.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from aughor.actions import overlay
from aughor.sheets import model, projection, service
from aughor.sheets.imports import ident
from aughor.sheets.model import Sheet

#: The most rows of another sheet a record lists as linked to it.
MAX_LINKED = 5


def row_ref(sheet_id: str, row: int) -> str:
    """What a comment is about: one row of one sheet."""
    return f"sheet:{sheet_id}/row:{int(row)}"


def _parts(sheet: Sheet, column: model.Column, values: dict, other: Sheet) -> Optional[int]:
    """How many of the other sheet's rows a total adds up for this row — None when it cannot be read."""
    mine = sheet.column(column.by)
    okey = other.column(column.key)
    if not mine or not okey or values.get(mine.id) is None:
        return 0 if mine and okey else None
    cur = projection.cursor()
    try:
        return int(cur.execute(f"SELECT COUNT(*) FROM {ident(other.table)} WHERE CAST({ident(okey.name)} AS VARCHAR) = ?",
                               [str(values[mine.id])]).fetchone()[0])
    finally:
        cur.close()


def _source_line(sheet: Sheet, column: model.Column, row: int, edits: dict, values: dict) -> str:
    e = edits.get((row, column.id))
    if e is not None:
        who = (e.actor or "someone").removeprefix("user:")
        return f"set by {who}, {str(e.created_at)[:16].replace('T', ' ')} UTC"
    if column.role == "computed":
        return f"computed: {column.expression}"
    if column.role == "lookup":
        via = sheet.column(column.via)
        other = model.get(via.link.sheet) if via and via.link else None
        return f"via {other.name}" if other else "via a sheet that was removed"
    if column.role == "total":
        other = model.get(column.sheet)
        if other is None:
            return "a total of a sheet that was removed"
        n = _parts(sheet, column, values, other)
        of = other.column(column.of) if column.of else None
        if n is None:
            return f"{column.how} of {other.name}"
        if n == 0:
            return f"no row of {other.name} has this row's key" + ("" if column.how == "count" else ", so it is empty")
        rows = f"{n:,} row{'s' if n != 1 else ''} of {other.name}"
        return rows if column.how == "count" or of is None else f"{column.how} of {of.name} over {rows}"
    if row <= sheet.source.rows and column.source:
        return f"file row {row:,}" if sheet.source.kind == "file" else f"kept row {row:,}"
    return "typed in" if row > sheet.source.rows else "a column added in the sheet"


def _kinds(sheet: Sheet) -> list[dict]:
    """The kinds of the columns a linked row lists, so it is shown as its own sheet shows it."""
    return [{"kind": o.kind, "currency": o.currency} for o in sheet.columns][:8]


def _title(sheet: Sheet, values: dict) -> str:
    """What a row is called when it is opened: its key's value, or its first text column's."""
    first = sheet.column(sheet.key) if sheet.key else None
    first = first or next((c for c in sheet.columns if c.kind in ("text", "email", "link")), None)
    v = values.get(first.id) if first else None
    return "" if v is None else str(v)


def _linked(sheet: Sheet, values: dict) -> list[dict]:
    """The rows of other sheets this row links to, and the rows of other sheets that link to it."""
    out: list[dict] = []
    cur = projection.cursor()
    try:
        for c in sheet.columns:
            if c.kind != "link" or not c.link or values.get(c.id) is None:
                continue
            other = model.get(c.link.sheet)
            okey = other.column(c.link.column) if other else None
            if not other or not okey:
                continue
            got = cur.execute(f"SELECT _row, * EXCLUDE (_row) FROM {ident(other.table)} WHERE "
                              f"CAST({ident(okey.name)} AS VARCHAR) = ? LIMIT {MAX_LINKED}",
                              [str(values[c.id])]).fetchall()
            out.append({"sheet": other.id, "name": other.name, "through": c.name, "direction": "to",
                        "columns": [o.name for o in other.columns][:8], "kinds": _kinds(other),
                        "rows": [{"row": int(r[0]), "values": [projection.jsonable(v) for v in r[1:9]]} for r in got],
                        "count": len(got)})
        for other in model.list_sheets():
            if other.id == sheet.id:
                continue
            for c in other.columns:
                if c.kind != "link" or not c.link or c.link.sheet != sheet.id:
                    continue
                mine = sheet.column(c.link.column)
                if not mine or values.get(mine.id) is None:
                    continue
                where = f"CAST({ident(c.name)} AS VARCHAR) = ?"
                n = int(cur.execute(f"SELECT COUNT(*) FROM {ident(other.table)} WHERE {where}",
                                    [str(values[mine.id])]).fetchone()[0])
                got = cur.execute(f"SELECT _row, * EXCLUDE (_row) FROM {ident(other.table)} WHERE {where} "
                                  f"ORDER BY _row LIMIT {MAX_LINKED}", [str(values[mine.id])]).fetchall()
                out.append({"sheet": other.id, "name": other.name, "through": c.name, "direction": "from",
                            "columns": [o.name for o in other.columns][:8], "kinds": _kinds(other),
                            "rows": [{"row": int(r[0]), "values": [projection.jsonable(v) for v in r[1:9]]}
                                     for r in got], "count": n})
    finally:
        cur.close()
    return out


def record(sheet: Sheet, row: int) -> Optional[dict]:
    """The row as a record, with the rules that mark it (SH-3), or None when the sheet holds no such row."""
    values = projection.read_row(sheet, row)
    if values is None:
        return None
    edits = {(int(e.row_key), e.column): e for e in overlay.sheet_values(sheet.id) if e.kind == overlay.SHEET_CELL}
    fields = [{"column": c.id, "name": c.name, "kind": c.kind, "role": c.role, "value": values.get(c.id),
               "source": _source_line(sheet, c, row, edits, values), "description": c.description}
              for c in sheet.columns]
    names = {c.id: c.name for c in sheet.columns}
    history = [{"event": h["event"], "column": names.get(h["column"], h["column"]) if h["column"] else "",
                "value": service.value_of(h["body"]) if h["event"] == "set" else None,
                "previous": service.value_of(h["previous"]) if h["previous"] else None,
                "by": h["actor"], "at": h["at"], "origin": h["origin"]}
               for h in overlay.sheet_history(sheet.id, row=row, limit=200)]
    from aughor.sheets import views
    marked = set(views.marks(sheet, {row}).get(str(row), []))
    return {"row": row, "title": _title(sheet, values), "came_from": service.origin_of_row(sheet, row),
            "fields": fields, "linked": _linked(sheet, values), "history": history, "comments": comments(sheet, row),
            "marks": [{"id": r.id, "name": r.name, "tone": r.tone} for r in sheet.rules if r.id in marked]}


def comments(sheet: Sheet, row: int) -> list[dict]:
    from aughor.record import claims
    ref = row_ref(sheet.id, row)
    found = claims.list_claims(kind="said", about_kind="object", about_key=ref, conn_id=model.SHEETS_CONNECTION,
                               limit=200)
    return sorted([{"id": c.id if hasattr(c, "id") else "", "text": c.statement.text, "by": c.author,
                    "at": str(c.extra.get("at") or c.as_of)} for c in found], key=lambda x: x["at"])


def comment(sheet: Sheet, row: int, text: str, *, by: str) -> dict:
    """Keep a person's comment on a row, as a said claim in their name."""
    from aughor.record import claims
    words = " ".join((text or "").split())[:2000]
    if not words:
        raise service.Refused("a comment needs words")
    if projection.read_row(sheet, row) is None:
        raise service.Refused(f"{sheet.name} has no row {row}")
    ref = row_ref(sheet.id, row)
    at = model.now()
    said_id = hashlib.sha1(f"{by}|{at}|{words}".encode()).hexdigest()[:12]
    claim = claims.Claim(
        kind="said", tier="said", about=claims.About(kind="object", key=ref),
        statement=claims.Statement(text=words),
        status="Provisional", as_of=at[:10],
        warrants=[claims.said_warrant("conversation", f"{ref}/comment:{said_id}", words, shared=True,
                                      detail=f"said on row {row} of the sheet {sheet.name}")],
        author=by, author_kind="person", state="open",
        extra={"writer": "sheets", "sheet": sheet.id, "row": int(row), "at": at},
    )
    claims.book(claim, key=claims.claim_key("said", "sheet", sheet.id, str(int(row)), said_id),
                conn_id=model.SHEETS_CONNECTION)
    return {"text": words, "by": by, "at": at}
