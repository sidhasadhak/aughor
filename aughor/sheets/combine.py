"""Combining sheets — a link by a key, a total of another sheet's rows, a newer file merged in (Arc SH, SH-7).

**Every miss is counted before anything is kept.** A link says how many rows matched, how many did not, and how many
had no key; a total says how many rows of the other sheet it counts and how many match no row here; a merge shows every
row it adds and every cell it changes before it is applied. A column that reads through a link shows empty, never zero,
for a row that matched nothing — except a count, where none is zero rows.

**A link reads the other sheet's stored columns only** — imported or typed in, never another link or total — so what
one sheet reads from another never goes round in a circle (``projection.py``).

**A merge never removes.** A row of the sheet the newer file does not hold is counted and kept as it is; a value in the
file that does not read as its column's kind is counted and left as it was. The whole merge is ONE change, undone whole.
"""
from __future__ import annotations

import json
from typing import Optional

from aughor.actions import overlay
from aughor.actions.overlay import SHEET_CELL, SHEET_ROW, SheetEdit
from aughor.sheets import files, imports, kinds, model, projection, service
from aughor.sheets.imports import ident
from aughor.sheets.model import Column, Link, Sheet
from aughor.sheets.service import Refused

#: How many of a preview's changes are listed; every one is counted.
SHOWN = 50


def _other(sheet_id: str) -> Sheet:
    other = model.get(sheet_id)
    if other is None:
        raise Refused("that sheet is not there to combine with")
    return other


def _stored_of(sheet: Sheet, ref: str, what: str) -> Column:
    c = sheet.column(ref)
    if c is None:
        raise Refused(f"{sheet.name} has no column {ref!r}")
    if c.role != "stored":
        raise Refused(f"{c.name} in {sheet.name} is itself read from elsewhere; {what} reads a column kept in the sheet")
    return c


def _repeats(cur, sheet: Sheet, c: Column) -> int:
    return int(cur.execute(f"SELECT COUNT(*) FROM (SELECT {ident(c.name)} FROM {ident(sheet.table)} "
                           f"WHERE {ident(c.name)} IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1)").fetchone()[0])


# ── a link ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def link_preview(sheet: Sheet, column: str, other_id: str, other_column: str) -> dict:
    """What linking ``column`` to another sheet's ``other_column`` would find: the rows that match, the rows that do
    not, the rows with no key, and whether the other sheet holds one row per key — a few of the misses shown."""
    other = _other(other_id)
    if other.id == sheet.id:
        raise Refused("a sheet is linked to another sheet, not to itself")
    mine = _stored_of(sheet, column, "a link")
    theirs = _stored_of(other, other_column, "a link")
    cur = projection.cursor()
    try:
        keys = f"(SELECT DISTINCT CAST({ident(theirs.name)} AS VARCHAR) AS k FROM {ident(other.table)})"
        v = f"CAST(t.{ident(mine.name)} AS VARCHAR)"
        matched, missed, empty = cur.execute(
            f"SELECT COUNT(*) FILTER (WHERE o.k IS NOT NULL), COUNT(*) FILTER (WHERE o.k IS NULL AND {v} IS NOT NULL), "
            f"COUNT(*) FILTER (WHERE {v} IS NULL) FROM {ident(sheet.table)} t LEFT JOIN {keys} o ON {v} = o.k"
        ).fetchone()
        misses = [r[0] for r in cur.execute(
            f"SELECT DISTINCT {v} FROM {ident(sheet.table)} t LEFT JOIN {keys} o ON {v} = o.k "
            f"WHERE o.k IS NULL AND {v} IS NOT NULL LIMIT 5").fetchall()]
        repeats = _repeats(cur, other, theirs)
    finally:
        cur.close()
    return {"sheet": sheet.id, "column": mine.id, "other": other.id, "other_name": other.name,
            "other_column": theirs.id, "rows": int(matched) + int(missed) + int(empty), "matched": int(matched),
            "missed": int(missed), "empty": int(empty), "some_misses": misses, "other_repeats": repeats,
            "can_bring": [{"id": c.id, "name": c.name, "kind": c.kind} for c in other.stored() if c.id != theirs.id]}


def link_keep(sheet: Sheet, column: str, other_id: str, other_column: str, *, bring: list[str], by: str,
              origin: str = "", cid: str = "") -> Sheet:
    """Keep a link, with the other sheet's columns to read through it. Counted again as it is kept; refused when the
    other sheet repeats its key, since a looked-up value needs one row per key there."""
    seen = link_preview(sheet, column, other_id, other_column)
    other = _other(other_id)
    if bring and seen["other_repeats"]:
        raise Refused(f"{seen['other_repeats']:,} values of {other.column(other_column).name} repeat in {other.name}; "
                      "a looked-up column needs one row per key there — total its rows instead")
    mine = sheet.column(column)
    mine.kind = kinds.LINK
    mine.link = Link(sheet=other.id, column=seen["other_column"], matched=seen["matched"], missed=seen["missed"])
    for ref in bring:
        oc = _stored_of(other, ref, "a link")
        sheet.columns.append(Column(id=sheet.new_column_id(), name=service.unique_name(oc.name, sheet), kind=oc.kind,
                                    integer=oc.integer, currency=oc.currency, role="lookup", via=mine.id, of=oc.id,
                                    description=f"{oc.name} of {other.name}, read through {mine.name}"))
    what = f"{mine.name} linked to {other.name}: {seen['matched']:,} matched, {seen['missed']:,} missed"
    model.save(sheet, what=what, by=by, origin=origin, change_id=cid or service.change_id())
    projection.rebuild(sheet)
    return sheet


# ── a total ──────────────────────────────────────────────────────────────────────────────────────────────────────────

HOWS = ("sum", "count", "average", "min", "max", "earliest", "latest")


def total_kind(how: str, of: Optional[Column]) -> tuple[str, bool, str]:
    if how == "count" or of is None:
        return kinds.NUMBER, True, ""
    if how in ("sum", "average"):
        if of.kind not in (kinds.NUMBER, kinds.MONEY):
            raise Refused(f"{of.name} is {kinds.LABELS.get(of.kind, of.kind)}, which cannot be summed or averaged")
        if of.kind == kinds.MONEY and how == "sum":
            return kinds.MONEY, False, of.currency
        return kinds.NUMBER, of.integer and how == "sum", ""
    if how in ("earliest", "latest") and of.kind not in (kinds.DATE, kinds.DATETIME):
        raise Refused(f"earliest and latest are of dates; {of.name} is {kinds.LABELS.get(of.kind, of.kind)}")
    return of.kind, of.integer, of.currency


def total_preview(sheet: Sheet, by_column: str, other_id: str, other_key: str, how: str, of: str = "") -> dict:
    """What totalling another sheet's rows per key would count: how many rows here have rows there, how many have none,
    how many rows there match no row here, and the total over every row it counts."""
    if how not in HOWS:
        raise Refused(f"{how!r} is not a total; it is one of {', '.join(HOWS)}")
    other = _other(other_id)
    mine = _stored_of(sheet, by_column, "a total")
    key = _stored_of(other, other_key, "a total")
    val = _stored_of(other, of, "a total") if of else None
    total_kind(how, val)
    cur = projection.cursor()
    try:
        mk = f"CAST(t.{ident(mine.name)} AS VARCHAR)"
        ok = f"CAST(o.{ident(key.name)} AS VARCHAR)"
        with_rows, without = cur.execute(
            f"SELECT COUNT(*) FILTER (WHERE x.k IS NOT NULL), COUNT(*) FILTER (WHERE x.k IS NULL) "
            f"FROM {ident(sheet.table)} t LEFT JOIN (SELECT DISTINCT {ok} AS k FROM {ident(other.table)} o) x "
            f"ON {mk} = x.k").fetchone()
        counted, orphans = cur.execute(
            f"SELECT COUNT(*) FILTER (WHERE m.k IS NOT NULL), COUNT(*) FILTER (WHERE m.k IS NULL) "
            f"FROM {ident(other.table)} o LEFT JOIN (SELECT DISTINCT {mk} AS k FROM {ident(sheet.table)} t) m "
            f"ON {ok} = m.k").fetchone()
        agg = projection.aggregate(how, val).replace(ident(val.name) if val else "*",
                                                       f"o.{ident(val.name)}" if val else "*")
        grand = cur.execute(f"SELECT {agg} FROM {ident(other.table)} o WHERE {ok} IN "
                            f"(SELECT {mk} FROM {ident(sheet.table)} t)").fetchone()[0]
    finally:
        cur.close()
    return {"rows_with": int(with_rows), "rows_without": int(without), "other_rows_counted": int(counted),
            "other_rows_unmatched": int(orphans), "total": projection.jsonable(grand), "how": how,
            "other_name": other.name}


def total_keep(sheet: Sheet, by_column: str, other_id: str, other_key: str, how: str, of: str = "", *, name: str,
               by: str, origin: str = "", cid: str = "") -> Sheet:
    seen = total_preview(sheet, by_column, other_id, other_key, how, of)
    other = _other(other_id)
    val = other.column(of) if of else None
    kind, integer, currency = total_kind(how, val)
    label = name or (f"{how} of {val.name}" if val else f"{other.name} rows")
    col = Column(id=sheet.new_column_id(), name=service.unique_name(label, sheet), kind=kind, integer=integer,
                 currency=currency, role="total", sheet=other.id, key=other.column(other_key).id,
                 by=sheet.column(by_column).id, how=how, of=val.id if val else "",
                 description=(f"the {how} of {val.name} in {other.name} for this row's {sheet.column(by_column).name}"
                              if val else f"how many rows of {other.name} have this row's "
                              f"{sheet.column(by_column).name}")
                 + (f"; {seen['rows_without']:,} rows have none and show "
                    f"{'0' if how == 'count' else 'empty, never zero'}" if seen["rows_without"] else ""))
    sheet.columns.append(col)
    what = f"{col.name}: {how} of {other.name} per {sheet.column(by_column).name}"
    model.save(sheet, what=what, by=by, origin=origin, change_id=cid or service.change_id())
    projection.rebuild(sheet)
    return sheet


# ── a newer file ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _basis(sheet: Sheet) -> str:
    return f"{sheet.version}:{overlay.sheet_mark(sheet.id)}"


def _merge_plan(sheet: Sheet, token: str, key: str, tab: str = "") -> dict:
    path = files.staged(token)
    if path is None:
        raise Refused("that file is no longer waiting to be merged; bring it again")
    keycol = _stored_of(sheet, key, "a merge")
    con, raw_cols = imports.open_file(path, tab)
    try:
        by_name = {c.lower(): c for c in raw_cols}
        pairs: list[tuple[Column, str]] = []
        for c in sheet.stored():
            raw = by_name.get((c.source or c.name).lower()) or by_name.get(c.name.lower())
            if raw:
                pairs.append((c, raw))
        file_key = next((raw for c, raw in pairs if c.id == keycol.id), None)
        if file_key is None:
            raise Refused(f"the file has no column {keycol.source or keycol.name} to match rows on")
        dup = con.execute(f"SELECT COUNT(*) FROM (SELECT {ident(file_key)} FROM raw WHERE NULLIF(TRIM("
                          f"{ident(file_key)}), '') IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1)").fetchone()[0]
        if dup:
            raise Refused(f"{dup:,} values of {file_key} repeat in the file; a merge matches one row to one row")
        no_key = int(con.execute(f"SELECT COUNT(*) FROM raw WHERE NULLIF(TRIM({ident(file_key)}), '') IS NULL"
                                 ).fetchone()[0])
        cols = [raw for _, raw in pairs]
        file_rows = con.execute(f"SELECT {', '.join(ident(r) for r in cols)} FROM raw WHERE NULLIF(TRIM("
                                f"{ident(file_key)}), '') IS NOT NULL ORDER BY _row").fetchall()
    finally:
        con.close()
    cur = projection.cursor()
    try:
        if _repeats(cur, sheet, keycol):
            raise Refused(f"values of {keycol.name} repeat in {sheet.name}; a merge needs one row per key")
        current = {str(r[0]): (int(r[1]), r[2:]) for r in cur.execute(
            f"SELECT CAST({ident(keycol.name)} AS VARCHAR), _row, {', '.join(ident(c.name) for c, _ in pairs)} "
            f"FROM {ident(sheet.table)} WHERE {ident(keycol.name)} IS NOT NULL").fetchall()}
    finally:
        cur.close()
    changed: list[dict] = []
    added: list[dict] = []
    misfit = 0
    kidx = cols.index(file_key)
    seen_keys: set[str] = set()
    for frow in file_rows:
        try:
            kval = kinds.parse(keycol.kind, frow[kidx], integer=keycol.integer)
        except kinds.ValueRefused:
            misfit += 1
            continue
        kstr = str(kval)
        seen_keys.add(kstr)
        values = {}
        for (c, _raw), text in zip(pairs, frow):
            try:
                values[c.id] = kinds.parse(c.kind, text, integer=c.integer, column=c.name)
            except kinds.ValueRefused:
                misfit += 1
                values[c.id] = _KEEP
        if kstr in current:
            row, now = current[kstr]
            for (c, _raw), old in zip(pairs, now):
                new = values[c.id]
                if new is _KEEP:
                    continue
                if _norm(projection.jsonable(old)) != _norm(new):
                    changed.append({"row": row, "column": c.id, "name": c.name, "old": projection.jsonable(old),
                                    "new": new, "key": kstr})
        else:
            added.append({"key": kstr, "values": {cid: v for cid, v in values.items() if v is not _KEEP}})
    kept = len([k for k in current if k not in seen_keys])
    return {"changed": changed, "added": added, "misfit": misfit, "kept_as_is": kept, "no_key": no_key,
            "file_columns_not_in_sheet": [r for r in raw_cols if r not in cols],
            "sheet_columns_not_in_file": [c.name for c in sheet.stored() if c.id not in {p.id for p, _ in pairs}],
            "key": keycol.id, "file": path.name}


class _Keep:
    """A file value that does not read as its column's kind: the cell is left as it was, and counted."""


_KEEP = _Keep()


def _norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def merge_preview(sheet: Sheet, token: str, key: str, tab: str = "") -> dict:
    """A newer file against the sheet, matched on ``key``: every row it adds and every cell it changes, counted, the
    first of each listed — and the basis the merge must still stand on when it is applied."""
    plan = _merge_plan(sheet, token, key, tab)
    return {"rows_added": len(plan["added"]), "cells_changed": len(plan["changed"]),
            "rows_changed": len({c["row"] for c in plan["changed"]}), "misfit": plan["misfit"],
            "kept_as_is": plan["kept_as_is"], "no_key": plan["no_key"], "changes": plan["changed"][:SHOWN],
            "additions": plan["added"][:20], "file_columns_not_in_sheet": plan["file_columns_not_in_sheet"],
            "sheet_columns_not_in_file": plan["sheet_columns_not_in_file"], "file": plan["file"],
            "basis": _basis(sheet), "token": token, "key": plan["key"]}


def merge_apply(sheet: Sheet, token: str, key: str, *, basis: str, by: str, tab: str = "", origin: str = "") -> dict:
    """Apply a newer file as ONE change — every cell it changes and every row it adds — refused when the sheet has
    changed since the preview the person read."""
    if basis != _basis(sheet):
        raise Refused("the sheet has changed since this preview; preview the file again")
    plan = _merge_plan(sheet, token, key, tab)
    cid = service.change_id()
    edits = [SheetEdit(kind=SHEET_CELL, row=c["row"], column=c["column"], body=json.dumps(c["new"]))
             for c in plan["changed"]]
    rows = {c["row"] for c in plan["changed"]}
    start = service.next_row(sheet)
    for i, a in enumerate(plan["added"]):
        n = start + i
        rows.add(n)
        edits.append(SheetEdit(kind=SHEET_ROW, row=n, body="added", expected_version=0))
        edits += [SheetEdit(kind=SHEET_CELL, row=n, column=cid_, body=json.dumps(v))
                  for cid_, v in a["values"].items() if v is not None]
    note = f"merged {plan['file']}: {len(plan['changed']):,} cells changed, {len(plan['added']):,} rows added"
    if edits:
        try:
            overlay.save_sheet_change(sheet.id, edits, change_id=cid, actor=by, origin=origin or "merge", note=note)
        except overlay.EditConflict as exc:
            raise Refused(f"rows were added while merging — {exc}; preview the file again") from None
    if sheet.key != plan["key"]:
        sheet.key = plan["key"]
        model.save(sheet, what=note, by=by, origin=origin or "merge", change_id=cid)
    if rows:
        projection.apply(sheet, rows)
    files.unstage(token)
    return {"change_id": cid, "cells_changed": len(plan["changed"]), "rows_added": len(plan["added"]),
            "kept_as_is": plan["kept_as_is"], "misfit": plan["misfit"]}
