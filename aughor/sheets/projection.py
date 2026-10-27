"""The table people read: a sheet's source with its changes applied, in one DuckDB file per organisation (Arc SH).

**Only the API process writes it**, under a lock per organisation, and every reader gets a cursor of the same database
(the Workspace's own sharing primitive, ``connectors/file/local_upload.py``): DuckDB keeps a cursor's reads consistent
while a change is written beside it.

**It is rebuilt whenever it is missing or in doubt.** Each sheet's table is stamped (``projection.marks.json``) with the
definition version and the edit-layer mark it was built at. A process that opens the projection for the first time, or
finds a stamp that does not match, rebuilds that sheet from its source and its changes; a table that belongs to no sheet
is dropped. A change that fails half-way rolls back and rebuilds.

**A change rebuilds only the rows it touched**, by the same code that builds a whole sheet — a row is its source row
(``source.parquet``, by ``_row``) unless it was removed, plus a row added, with the cells people set over it. So the table
as changed and a fresh rebuild come from one definition of a row, and ``check`` compares them: the oracle the Grist
study proposed, and SH-1's falsifier.

**Derived columns follow what they read.** A computed column is an expression over the sheet's own columns; a looked-up
column reads another sheet through a link; a total sums or counts another sheet's rows per key (SH-7). All are
re-derived after every change to the sheet, and to every sheet they read. A link reads the other sheet's stored
columns only, so derivations never go round in a circle.
"""
from __future__ import annotations

import csv
import io
import json
import math
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Optional

import duckdb

from aughor.sheets import files, kinds
from aughor.sheets.imports import ident
from aughor.sheets.model import Column, Condition, Sheet

#: org → the projection's root connection. Nothing executes on it: every reader takes a cursor of it, and the one
#: writer cursor (``_WRITERS``) is used only under the organisation's lock.
_DBS: dict[str, duckdb.DuckDBPyConnection] = {}
_WRITERS: dict[str, duckdb.DuckDBPyConnection] = {}
_LOCKS: dict[str, threading.RLock] = {}
_READY: set[str] = set()
_GLOBAL = threading.Lock()

#: The most rows one page of a grid reads.
MAX_PAGE = 2000


def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id() or "default"


def _lock(org: str) -> threading.RLock:
    with _GLOBAL:
        return _LOCKS.setdefault(org, threading.RLock())


def _open(org: str) -> None:
    with _GLOBAL:
        if org not in _DBS:
            path = files.projection_path(org)
            path.parent.mkdir(parents=True, exist_ok=True)
            root = duckdb.connect(str(path))
            _DBS[org] = root
            _WRITERS[org] = root.cursor()


def database(org: str = "") -> duckdb.DuckDBPyConnection:
    """The organisation's writer cursor, the projection opened once per process and reconciled with the stores the
    first time. Used only under the organisation's lock (`_lock`)."""
    org = org or _org()
    _open(org)
    if org not in _READY:
        with _lock(org):
            if org not in _READY:
                reconcile(org)
                _READY.add(org)
    return _WRITERS[org]


def reset() -> None:
    """Close every projection this process holds (a test's fresh state directory; a restore)."""
    with _GLOBAL:
        for con in [*_WRITERS.values(), *_DBS.values()]:
            try:
                con.close()
            except Exception as exc:  # noqa: BLE001 — closing a database this process is done with
                from aughor.kernel.errors import tolerate
                tolerate(exc, "closing a projection this process is done with", counter="sheets.projection_close")
        _DBS.clear()
        _WRITERS.clear()
        _READY.clear()


# ── stamps ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _marks_path(org: str) -> Path:
    return files.root(org) / "projection.marks.json"


def _read_marks(org: str) -> dict:
    try:
        return json.loads(_marks_path(org).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_marks(org: str, marks: dict) -> None:
    path = _marks_path(org)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(marks, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _stamp(sheet: Sheet, org: str) -> dict:
    from aughor.actions.overlay import sheet_mark
    return {"def": sheet.version, "values": sheet_mark(sheet.id, org), "table": sheet.table}


def _restamp(sheets: Iterable[Sheet], org: str) -> None:
    marks = _read_marks(org)
    for s in sheets:
        marks[s.id] = _stamp(s, org)
    _write_marks(org, marks)


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main' AND NOT temporary").fetchall()}


def reconcile(org: str = "") -> list[str]:
    """Rebuild every sheet whose table is missing or stamped at another version, and drop every table no sheet owns.
    Returns the ids rebuilt."""
    from aughor.sheets.model import list_sheets
    org = org or _org()
    _open(org)
    con = _WRITERS[org]
    sheets = list_sheets(org_id=org)
    marks = _read_marks(org)
    present = _tables(con)
    rebuilt: list[Sheet] = []
    for s in sheets:
        if s.table not in present or marks.get(s.id) != _stamp(s, org):
            _build(con, s, org)
            rebuilt.append(s)
    owned = {s.table for s in sheets}
    for t in present - owned:
        con.execute(f"DROP TABLE IF EXISTS {ident(t)}")
    ids = {s.id for s in rebuilt}
    for s in sheets:
        if s.id not in ids and _reads(s) & ids:
            _derive(con, s, org)
    if rebuilt or set(marks) - {s.id for s in sheets}:
        _write_marks(org, {s.id: _stamp(s, org) for s in sheets})
    return [s.id for s in rebuilt]


# ── building ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _type(c: Column) -> str:
    return kinds.duck_type(c.kind, integer=c.integer)


def _source_columns(path: Path, con) -> set[str]:
    if not path.exists():
        return set()
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()}


def _row_select(con, sheet: Sheet, org: str, rows: Optional[set[int]] = None) -> tuple[str, list]:
    """The SELECT that yields the sheet's rows as they stand — source rows not removed, rows added — with every column
    typed and the derived ones empty (filled by `_derive`), the cells people set applied by `_apply_cells`. ``rows``
    narrows it to those row numbers (a change's)."""
    from aughor.actions.overlay import SHEET_ROW, sheet_values
    edits = [e for e in sheet_values(sheet.id, org) if e.kind == SHEET_ROW]
    removed = {int(e.row_key) for e in edits if e.body == "removed"}
    added = {int(e.row_key) for e in edits if e.body == "added"}
    src = files.source_parquet(sheet.id, org)
    have = _source_columns(src, con)
    cols = []
    for c in sheet.columns:
        typ = _type(c)
        if c.role == "stored" and c.id in have:
            cols.append(f"CAST(s.{ident(c.id)} AS {typ}) AS {ident(c.name)}")
        else:
            cols.append(f"CAST(NULL AS {typ}) AS {ident(c.name)}")
    selects = []
    params: list = []
    keep = "TRUE"
    if rows is not None:
        keep = f"s._row IN ({', '.join(str(int(r)) for r in rows) or 'NULL'})"
    if removed:
        keep += f" AND s._row NOT IN ({', '.join(str(r) for r in sorted(removed))})"
    if src.exists():
        selects.append(f"SELECT CAST(s._row AS BIGINT) AS _row, {', '.join(cols)} FROM "
                       f"read_parquet('{src.as_posix()}') s WHERE {keep}")
    new_rows = sorted(r for r in added - removed if rows is None or r in rows)
    if new_rows:
        blank = ", ".join(f"CAST(NULL AS {_type(c)}) AS {ident(c.name)}" for c in sheet.columns)
        selects.append(f"SELECT CAST(r AS BIGINT) AS _row{', ' + blank if blank else ''} FROM "
                       f"unnest([{', '.join(str(r) for r in new_rows)}]) t(r)")
    if not selects:
        empty = ", ".join(f"CAST(NULL AS {_type(c)}) AS {ident(c.name)}" for c in sheet.columns)
        selects.append(f"SELECT CAST(NULL AS BIGINT) AS _row{', ' + empty if empty else ''} WHERE FALSE")
    return " UNION ALL ".join(selects), params


def _apply_cells(con, sheet: Sheet, org: str, target: str, rows: Optional[set[int]] = None) -> None:
    """Set over ``target`` the cells people set — each stored column's edits, typed by its kind."""
    from aughor.actions.overlay import SHEET_CELL, sheet_values
    cells = [e for e in sheet_values(sheet.id, org) if e.kind == SHEET_CELL
             and (rows is None or int(e.row_key) in rows)]
    if not cells:
        return
    by_id = {c.id: c for c in sheet.columns if c.role == "stored"}
    con.execute("CREATE OR REPLACE TEMP TABLE _cells (r BIGINT, col VARCHAR, val VARCHAR)")
    con.executemany("INSERT INTO _cells VALUES (?, ?, ?)",
                    [(int(e.row_key), e.column, _cell_text(e.body)) for e in cells if e.column in by_id])
    for cid in sorted({e.column for e in cells if e.column in by_id}):
        c = by_id[cid]
        con.execute(f"UPDATE {target} SET {ident(c.name)} = TRY_CAST(x.val AS {_type(c)}) FROM _cells x "
                    f"WHERE x.col = ? AND {target}._row = x.r", [cid])
    con.execute("DROP TABLE IF EXISTS _cells")


def _cell_text(body: str) -> Optional[str]:
    try:
        value = json.loads(body)
    except ValueError:
        return body
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build(con, sheet: Sheet, org: str, *, target: str = "") -> None:
    """Build a sheet's whole table — into ``target`` (a check's scratch table) or its own."""
    name = target or ident(sheet.table)
    select, params = _row_select(con, sheet, org)
    con.execute(f"CREATE OR REPLACE {'TEMP ' if target else ''}TABLE {name} AS {select}", params)
    _apply_cells(con, sheet, org, name)
    _derive(con, sheet, org, target=name)


def _derive(con, sheet: Sheet, org: str, *, target: str = "") -> None:
    """Re-derive a sheet's looked-up, total and computed columns, in that order (a computed column may read the other
    two). A column that reads a sheet that is no longer there is left empty."""
    from aughor.sheets.model import get
    name = target or ident(sheet.table)
    others: dict[str, Optional[Sheet]] = {}

    def other(sid: str) -> Optional[Sheet]:
        if sid not in others:
            others[sid] = get(sid, org_id=org)
        return others[sid]

    for c in sheet.columns:
        if c.role == "lookup":
            via = sheet.column(c.via)
            o = other(via.link.sheet) if via and via.link else None
            okey = o.column(via.link.column) if o and via and via.link else None
            oval = o.column(c.of) if o else None
            con.execute(f"UPDATE {name} SET {ident(c.name)} = NULL")
            if via and o and okey and oval:
                con.execute(
                    f"UPDATE {name} SET {ident(c.name)} = TRY_CAST(x.v AS {_type(c)}) FROM ("
                    f"SELECT CAST({ident(okey.name)} AS VARCHAR) AS k, "
                    f"CASE WHEN COUNT(*) = 1 THEN ANY_VALUE({ident(oval.name)}) END AS v "
                    f"FROM {ident(o.table)} WHERE {ident(okey.name)} IS NOT NULL GROUP BY 1) x "
                    f"WHERE CAST({name}.{ident(via.name)} AS VARCHAR) = x.k")
        elif c.role == "total":
            o = other(c.sheet)
            okey = o.column(c.key) if o else None
            oval = o.column(c.of) if o and c.of else None
            mine = sheet.column(c.by)
            con.execute(f"UPDATE {name} SET {ident(c.name)} = {'0' if c.how == 'count' else 'NULL'}")
            if o and okey and mine and (oval or c.how == "count"):
                agg = aggregate(c.how, oval)
                con.execute(
                    f"UPDATE {name} SET {ident(c.name)} = TRY_CAST(x.v AS {_type(c)}) FROM ("
                    f"SELECT CAST({ident(okey.name)} AS VARCHAR) AS k, {agg} AS v FROM {ident(o.table)} "
                    f"WHERE {ident(okey.name)} IS NOT NULL GROUP BY 1) x "
                    f"WHERE CAST({name}.{ident(mine.name)} AS VARCHAR) = x.k")
    for c in sheet.columns:
        if c.role == "computed" and c.expression:
            con.execute(f"UPDATE {name} SET {ident(c.name)} = TRY(CAST(({c.expression}) AS {_type(c)}))")


def aggregate(how: str, of: Optional[Column]) -> str:
    v = ident(of.name) if of else "*"
    return {"sum": f"SUM({v})", "count": "COUNT(*)", "average": f"AVG({v})", "min": f"MIN({v})",
            "max": f"MAX({v})", "earliest": f"MIN({v})", "latest": f"MAX({v})"}.get(how, f"SUM({v})")


def _reads(sheet: Sheet) -> set[str]:
    """The sheets this sheet's derived columns read."""
    out: set[str] = set()
    for c in sheet.columns:
        if c.role == "lookup":
            via = sheet.column(c.via)
            if via and via.link:
                out.add(via.link.sheet)
        elif c.role == "total" and c.sheet:
            out.add(c.sheet)
    return out


def dependents(sheet_id: str, org: str = "") -> list[Sheet]:
    from aughor.sheets.model import list_sheets
    return [s for s in list_sheets(org_id=org or _org()) if s.id != sheet_id and sheet_id in _reads(s)]


def rebuild(sheet: Sheet, org: str = "") -> None:
    """Build a sheet's table again from its source and its changes, then what reads it."""
    org = org or _org()
    con = database(org)
    with _lock(org):
        _build(con, sheet, org)
        deps = dependents(sheet.id, org)
        for d in deps:
            _derive(con, d, org)
        _restamp([sheet, *deps], org)


def apply(sheet: Sheet, rows: Iterable[int], org: str = "") -> None:
    """A change to some of a sheet's rows: those rows built again from source and changes, in one transaction, then
    the derived columns of the sheet and of what reads it. Anything that fails rolls back and rebuilds the sheet."""
    org = org or _org()
    con = database(org)
    touched = {int(r) for r in rows}
    with _lock(org):
        if ident(sheet.table).strip('"') not in _tables(con):
            return rebuild(sheet, org)
        try:
            con.execute("BEGIN TRANSACTION")
            table = ident(sheet.table)
            con.execute(f"DELETE FROM {table} WHERE _row IN ({', '.join(str(r) for r in sorted(touched)) or 'NULL'})")
            select, params = _row_select(con, sheet, org, rows=touched)
            con.execute(f"INSERT INTO {table} {select}", params)
            _apply_cells(con, sheet, org, table, rows=touched)
            _derive(con, sheet, org)
            deps = dependents(sheet.id, org)
            for d in deps:
                _derive(con, d, org)
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except duckdb.Error as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "no transaction was left to roll back; the sheet is rebuilt whole",
                         counter="sheets.apply_rollback")
            return rebuild(sheet, org)
        _restamp([sheet, *deps], org)


def drop(sheet: Sheet, org: str = "") -> None:
    """A removed sheet's table goes; what read it is re-derived (and reads empty, said by its column)."""
    org = org or _org()
    con = database(org)
    with _lock(org):
        con.execute(f"DROP TABLE IF EXISTS {ident(sheet.table)}")
        for d in dependents(sheet.id, org):
            _derive(con, d, org)
        marks = _read_marks(org)
        marks.pop(sheet.id, None)
        _write_marks(org, marks)


def rename(sheet: Sheet, old_table: str, org: str = "") -> None:
    org = org or _org()
    con = database(org)
    with _lock(org):
        if old_table != sheet.table:
            con.execute(f"DROP TABLE IF EXISTS {ident(old_table)}")
    rebuild(sheet, org)


def check(sheet: Sheet, org: str = "") -> dict:
    """The oracle: the table as it stands against a fresh rebuild from source and changes. ``same`` is the falsifier of
    SH-1 — a table that differs from its own rebuild is a projection that has drifted from its record."""
    org = org or _org()
    con = database(org)
    with _lock(org):
        scratch = '"_check_rebuild"'
        _build(con, sheet, org, target=scratch)
        table = ident(sheet.table)
        only_table = con.execute(f"SELECT COUNT(*) FROM (SELECT * FROM {table} EXCEPT ALL SELECT * FROM {scratch})"
                                 ).fetchone()[0]
        only_rebuild = con.execute(f"SELECT COUNT(*) FROM (SELECT * FROM {scratch} EXCEPT ALL SELECT * FROM {table})"
                                   ).fetchone()[0]
        rows = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        con.execute(f"DROP TABLE IF EXISTS {scratch}")
    return {"same": only_table == 0 and only_rebuild == 0, "rows": int(rows),
            "only_in_table": int(only_table), "only_in_rebuild": int(only_rebuild)}


# ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def cursor(org: str = ""):
    """A reader's own cursor of the projection — consistent while a change is written beside it."""
    org = org or _org()
    database(org)
    with _GLOBAL:
        return _DBS[org].cursor()


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


_OPS = {"is": "=", "is_not": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "before": "<", "after": ">"}


class FilterRefused(ValueError):
    """A filter that names no column of the sheet, or a value its column's kind cannot hold."""


def where_sql(sheet: Sheet, conditions: list[Condition], search: str = "") -> tuple[str, list]:
    """A view's filter and a search as SQL with its parameters — the one reading of a view the grid, the totals, the CSV
    and the chat's grounding all use, so a view counts the same rows wherever it is read."""
    parts: list[str] = []
    params: list = []
    for cond in conditions or []:
        if cond.op in ("marked", "not_marked"):
            # the rows a declared rule marks (SH-3): the rule's own conditions, read the same way
            rule = next((r for r in sheet.rules if r.id == cond.value), None)
            if rule is None:
                raise FilterRefused(f"the filter names a rule {cond.value!r} that {sheet.name} does not have")
            if any(x.op in ("marked", "not_marked") for x in rule.conditions):
                raise FilterRefused("a rule is made of conditions on columns, not of other rules")
            sub, sub_params = where_sql(sheet, rule.conditions)
            parts.append(f"{'' if cond.op == 'marked' else 'NOT '}COALESCE(({sub}), FALSE)")
            params.extend(sub_params)
            continue
        c = sheet.column(cond.column)
        if c is None:
            raise FilterRefused(f"the filter names {cond.column!r}, which is not a column of {sheet.name}")
        col = ident(c.name)
        op = cond.op
        if op == "empty":
            parts.append(f"{col} IS NULL" + (" OR CAST(" + col + " AS VARCHAR) = ''" if c.kind == "text" else ""))
            continue
        if op == "not_empty":
            parts.append(f"{col} IS NOT NULL")
            continue
        if op in ("contains", "not_contains"):
            parts.append(f"CAST({col} AS VARCHAR) {'NOT ' if op == 'not_contains' else ''}ILIKE ?")
            params.append(f"%{cond.value}%")
            continue
        if op in ("in", "not_in"):
            values = cond.value if isinstance(cond.value, list) else [cond.value]
            if not values:
                parts.append("FALSE" if op == "in" else "TRUE")
                continue
            typed = [_typed(c, v) for v in values]
            parts.append(f"{col} {'NOT ' if op == 'not_in' else ''}IN ({', '.join('?' for _ in typed)})"
                         + (f" OR {col} IS NULL" if op == "not_in" else ""))
            params.extend(typed)
            continue
        if op == "on":
            # one calendar day, for a date or a date and time alike — a calendar's day holds these rows
            if c.kind not in (kinds.DATE, kinds.DATETIME):
                raise FilterRefused(f"{c.name} is not a date, so it has no day to be on")
            try:
                day = kinds.parse(kinds.DATE, cond.value, column=c.name)
            except kinds.ValueRefused as exc:
                raise FilterRefused(str(exc)) from None
            parts.append(f"CAST({col} AS DATE) = ?")
            params.append(date.fromisoformat(day) if day else None)
            continue
        sql_op = _OPS.get(op)
        if sql_op is None:
            raise FilterRefused(f"{op!r} is not a way to filter")
        parts.append(f"{col} {sql_op} ?")
        params.append(_typed(c, cond.value))
    if search and search.strip():
        texts = [f"COALESCE(CAST({ident(c.name)} AS VARCHAR), '')" for c in sheet.columns]
        if texts:
            parts.append(f"concat_ws(' ', {', '.join(texts)}) ILIKE ?")
            params.append(f"%{search.strip()}%")
    return (" AND ".join(f"({p})" for p in parts) or "TRUE"), params


def _typed(c: Column, value: Any) -> Any:
    try:
        parsed = kinds.parse(c.kind, value, integer=c.integer, column=c.name)
    except kinds.ValueRefused as exc:
        raise FilterRefused(str(exc)) from None
    if c.kind == kinds.DATE and parsed:
        return date.fromisoformat(parsed)
    if c.kind == kinds.DATETIME and parsed:
        return datetime.fromisoformat(parsed)
    if c.kind == kinds.MONEY and parsed is not None:
        return Decimal(parsed)
    return parsed


def order_sql(sheet: Sheet, sort: list[dict], group: str = "") -> str:
    terms = []
    if group:
        g = sheet.column(group)
        if g:
            terms.append(f"{ident(g.name)} NULLS LAST")
    for s in sort or []:
        c = sheet.column(str(s.get("column") or ""))
        if c:
            terms.append(f"{ident(c.name)} {'DESC' if s.get('desc') else 'ASC'} NULLS LAST")
    terms.append("_row")
    return ", ".join(terms)


def totals(sheet: Sheet, where: str, params: list, cur) -> dict:
    """Per column, over the rows a view shows: how many are filled; the sum and average of numbers and money; the
    earliest and latest of dates; how many say yes; how many different values text holds."""
    exprs: list[str] = []
    keys: list[tuple[str, str]] = []
    for c in sheet.columns:
        col = ident(c.name)
        exprs.append(f"COUNT({col})")
        keys.append((c.id, "filled"))
        if c.kind in (kinds.NUMBER, kinds.MONEY):
            exprs += [f"SUM({col})", f"AVG({col})", f"MIN({col})", f"MAX({col})"]
            keys += [(c.id, "sum"), (c.id, "average"), (c.id, "min"), (c.id, "max")]
        elif c.kind in (kinds.DATE, kinds.DATETIME):
            exprs += [f"MIN({col})", f"MAX({col})"]
            keys += [(c.id, "earliest"), (c.id, "latest")]
        elif c.kind == kinds.YESNO:
            exprs.append(f"COUNT(*) FILTER (WHERE {col})")
            keys.append((c.id, "yes"))
        else:
            exprs.append(f"COUNT(DISTINCT {col})")
            keys.append((c.id, "distinct"))
    if not exprs:
        return {}
    row = cur.execute(f"SELECT {', '.join(exprs)} FROM {ident(sheet.table)} WHERE {where}", params).fetchone()
    out: dict[str, dict] = {}
    for (cid, what), v in zip(keys, row):
        if what == "average" and v is not None:
            v = round(float(v), 4)
        out.setdefault(cid, {})[what] = jsonable(v)
    return out


def read_rows(sheet: Sheet, *, conditions: Optional[list[Condition]] = None, sort: Optional[list[dict]] = None,
              search: str = "", group: str = "", offset: int = 0, limit: int = 200, org: str = "") -> dict:
    """One page of a view of a sheet: its rows (each with its ``_row``), how many rows the view holds, its totals, and —
    grouped — each group's value and count."""
    cur = cursor(org)
    try:
        where, params = where_sql(sheet, conditions or [], search)
        table = ident(sheet.table)
        total = int(cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
        names = ", ".join(ident(c.name) for c in sheet.columns)
        limit = max(1, min(int(limit or 200), MAX_PAGE))
        rows = cur.execute(f"SELECT _row{', ' + names if names else ''} FROM {table} WHERE {where} "
                           f"ORDER BY {order_sql(sheet, sort or [], group)} LIMIT ? OFFSET ?",
                           [*params, limit, max(0, int(offset or 0))]).fetchall()
        groups = []
        g = sheet.column(group) if group else None
        if g:
            groups = [{"value": jsonable(v), "rows": int(n)} for v, n in cur.execute(
                f"SELECT {ident(g.name)}, COUNT(*) FROM {table} WHERE {where} GROUP BY 1 ORDER BY 1 NULLS LAST",
                params).fetchall()]
        return {"rows": [[jsonable(v) for v in r] for r in rows], "total": total, "offset": int(offset or 0),
                "totals": totals(sheet, where, params, cur), "groups": groups}
    finally:
        cur.close()


def read_row(sheet: Sheet, row: int, org: str = "") -> Optional[dict]:
    """One row, by its number: column id → value. None when the sheet holds no such row."""
    cur = cursor(org)
    try:
        names = ", ".join(ident(c.name) for c in sheet.columns)
        got = cur.execute(f"SELECT {names or '1'} FROM {ident(sheet.table)} WHERE _row = ?", [int(row)]).fetchone()
        if got is None:
            return None
        return {c.id: jsonable(v) for c, v in zip(sheet.columns, got)}
    finally:
        cur.close()


def count(sheet: Sheet, org: str = "") -> int:
    cur = cursor(org)
    try:
        return int(cur.execute(f"SELECT COUNT(*) FROM {ident(sheet.table)}").fetchone()[0])
    except duckdb.Error:
        return 0
    finally:
        cur.close()


def to_csv(sheet: Sheet, *, conditions: Optional[list[Condition]] = None, sort: Optional[list[dict]] = None,
           search: str = "", hidden: Iterable[str] = (), org: str = "") -> str:
    """A view of a sheet as CSV — its columns but the hidden ones, its rows in its order."""
    hide = set(hidden)
    shown = [c for c in sheet.columns if c.id not in hide]
    cur = cursor(org)
    try:
        where, params = where_sql(sheet, conditions or [], search)
        rows = cur.execute(f"SELECT {', '.join(ident(c.name) for c in shown) or '1'} FROM {ident(sheet.table)} "
                           f"WHERE {where} ORDER BY {order_sql(sheet, sort or [])}", params).fetchall()
    finally:
        cur.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([c.name for c in shown])
    for r in rows:
        w.writerow(["" if v is None else jsonable(v) for v in r])
    return out.getvalue()
