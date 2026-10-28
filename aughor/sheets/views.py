"""A sheet read as its views lay it out (Arc SH, SH-3): groups with their totals, a board, a calendar, and the rows a
rule marks.

**Every count here is the grid's count.** A group, a lane, a day and a rule are each read through the one reading of a
filter (`projection.where_sql`) with one more condition — the group's value, the lane's, the day, the rule's own
conditions — so a board's lane holds exactly the rows the grid shows when filtered to that value. That is SH-3's
falsifier, and the tests hold it.

**Withheld is said.** A grouping with more groups than are listed says how many it did not list; a board says which
values the view's filter left out, with their rows; a calendar says how many rows have no date and so are on no day.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from aughor.sheets import kinds, projection
from aughor.sheets.imports import ident
from aughor.sheets.model import Column, Condition, Sheet, View

#: The most groups one grouping lists, the largest first; the rest are counted.
MAX_GROUPS = 50
#: Rows shown under each group's head until it is opened further.
GROUP_ROWS = 3
#: Cards shown in each lane of a board until it is opened further.
LANE_CARDS = 20

#: The kinds a board's lanes can be (each lane one value; moving a card sets it).
BOARD_KINDS = (kinds.CHOICE, kinds.YESNO)
#: The kinds a calendar places rows by.
CALENDAR_KINDS = (kinds.DATE, kinds.DATETIME)
#: The colours a rule may mark its rows with.
TONES = ("amber", "red", "green", "blue", "violet")


class ViewRefused(ValueError):
    """A view or a rule that cannot be laid out as asked, in a sentence a person can act on."""


def _column(sheet: Sheet, ref: str, what: str) -> Column:
    c = sheet.column(ref)
    if c is None:
        raise ViewRefused(f"{what} names {ref!r}, which is not a column of {sheet.name}")
    return c


def _counted_by(sheet: Sheet, ref: str, what: str) -> Column:
    """A column a figure is counted by — never one a model writes (SH-5)."""
    from aughor.sheets.model_columns import counting_refusal
    c = _column(sheet, ref, what)
    why = counting_refusal(c, what)
    if why:
        raise ViewRefused(why)
    return c


def check_view(sheet: Sheet, view: View) -> None:
    """Refuse a view whose layout names a column it cannot use: a board needs a choice or yes/no column, a calendar a
    date column. Its filter is read too, as every view's is."""
    projection.where_sql(sheet, view.filter, view.search)
    if view.kind == "board":
        if not view.group:
            raise ViewRefused("a board needs the column its lanes are — a choice or a yes/no column")
        c = _column(sheet, view.group, "the board")
        if c.kind not in BOARD_KINDS:
            raise ViewRefused(f"{c.name} is {kinds.LABELS.get(c.kind, c.kind)}; a board's lanes are a choice or a "
                              "yes/no column")
    elif view.kind == "calendar":
        if not view.date:
            raise ViewRefused("a calendar needs the date column its rows are placed by")
        c = _column(sheet, view.date, "the calendar")
        if c.kind not in CALENDAR_KINDS:
            raise ViewRefused(f"{c.name} is {kinds.LABELS.get(c.kind, c.kind)}; a calendar places rows by a date")
    elif view.group:
        _counted_by(sheet, view.group, "a grouping")
    for ref in view.card:
        _column(sheet, ref, "the card")


def check_rule(sheet: Sheet, conditions: list[Condition]) -> None:
    if not conditions:
        raise ViewRefused("a rule needs at least one condition")
    if any(c.op in ("marked", "not_marked") for c in conditions):
        raise ViewRefused("a rule is made of conditions on columns, not of other rules")
    for cond in conditions:
        _counted_by(sheet, cond.column, "a rule")
    projection.where_sql(sheet, conditions)


# ── counts ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _count(cur, sheet: Sheet, conditions: list[Condition], search: str = "") -> Optional[int]:
    try:
        where, params = projection.where_sql(sheet, conditions, search)
    except projection.FilterRefused:
        return None
    return int(cur.execute(f"SELECT COUNT(*) FROM {ident(sheet.table)} WHERE {where}", params).fetchone()[0])


def view_rows(sheet: Sheet, views: list[View], org: str = "") -> dict[str, Optional[int]]:
    """How many rows each view shows — None for a view whose filter no longer reads (a column it named is gone)."""
    cur = projection.cursor(org)
    try:
        return {v.id: _count(cur, sheet, v.filter, v.search) for v in views}
    finally:
        cur.close()


def rule_rows(sheet: Sheet, org: str = "") -> dict[str, Optional[int]]:
    """How many rows each rule marks."""
    if not sheet.rules:
        return {}
    cur = projection.cursor(org)
    try:
        return {r.id: _count(cur, sheet, [Condition(column="", op="marked", value=r.id)]) for r in sheet.rules}
    finally:
        cur.close()


def marks(sheet: Sheet, rows: set[int], org: str = "") -> dict[str, list[str]]:
    """The rules marking each of these rows: row → rule ids, for the rows any rule marks."""
    if not sheet.rules or not rows:
        return {}
    out: dict[str, list[str]] = {}
    cur = projection.cursor(org)
    try:
        listed = ", ".join(str(int(r)) for r in sorted(rows))
        for rule in sheet.rules:
            try:
                where, params = projection.where_sql(sheet, [Condition(column="", op="marked", value=rule.id)])
            except projection.FilterRefused as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "a rule whose conditions no longer read marks no row; its count reads empty",
                         counter="sheets.rule_unread")
                continue
            for (r,) in cur.execute(f"SELECT _row FROM {ident(sheet.table)} WHERE _row IN ({listed}) AND {where}",
                                    params).fetchall():
                out.setdefault(str(int(r)), []).append(rule.id)
    finally:
        cur.close()
    return out


# ── groups ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _names(sheet: Sheet) -> str:
    return ", ".join(ident(c.name) for c in sheet.columns)


def _total_exprs(sheet: Sheet) -> tuple[list[str], list[tuple[str, str]]]:
    """The totals the grid's foot shows, for the columns a group's head totals: numbers and money (sum, average),
    dates (earliest, latest), yes/no (how many say yes)."""
    exprs: list[str] = []
    keys: list[tuple[str, str]] = []
    for c in sheet.columns:
        col = ident(c.name)
        if c.kind in (kinds.NUMBER, kinds.MONEY):
            exprs += [f"COUNT({col})", f"SUM({col})", f"AVG({col})"]
            keys += [(c.id, "filled"), (c.id, "sum"), (c.id, "average")]
        elif c.kind in (kinds.DATE, kinds.DATETIME):
            exprs += [f"COUNT({col})", f"MIN({col})", f"MAX({col})"]
            keys += [(c.id, "filled"), (c.id, "earliest"), (c.id, "latest")]
        elif c.kind == kinds.YESNO:
            exprs += [f"COUNT({col})", f"COUNT(*) FILTER (WHERE {col})"]
            keys += [(c.id, "filled"), (c.id, "yes")]
    return exprs, keys


def groups(sheet: Sheet, *, conditions: list[Condition], search: str = "", sort: Optional[list[dict]] = None,
           group: str, per_group: int = GROUP_ROWS, org: str = "") -> dict:
    """The view's rows grouped by a column, the largest group first: each group's value, how many rows it holds, its
    totals over its own rows, and its first rows in the view's order."""
    g = _counted_by(sheet, group, "a grouping")
    where, params = projection.where_sql(sheet, conditions, search)
    table, col = ident(sheet.table), ident(g.name)
    per_group = max(0, min(int(per_group), 50))
    cur = projection.cursor(org)
    try:
        total = int(cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
        overall = projection.totals(sheet, where, params, cur)
        n_groups = int(cur.execute(f"SELECT COUNT(*) FROM (SELECT {col} FROM {table} WHERE {where} GROUP BY 1)",
                                   params).fetchone()[0])
        # the CTE's own names start with two underscores, so no sheet's column can be mistaken for them
        top = (f"SELECT {col} AS __gv, COUNT(*) AS __gn FROM {table} WHERE {where} GROUP BY 1 "
               f"ORDER BY __gn DESC, __gv NULLS LAST LIMIT {MAX_GROUPS}")
        listed = cur.execute(top, params).fetchall()
        sums: dict[Any, dict] = {}
        exprs, keys = _total_exprs(sheet)
        if exprs and listed:
            got = cur.execute(
                f"WITH top AS ({top}) SELECT t.{col}, {', '.join(exprs)} FROM {table} t JOIN top "
                f"ON t.{col} IS NOT DISTINCT FROM top.__gv WHERE {where} GROUP BY 1", [*params, *params]).fetchall()
            for row in got:
                one: dict[str, dict] = {}
                for (cid, what), v in zip(keys, row[1:]):
                    if what == "average" and v is not None:
                        v = round(float(v), 4)
                    one.setdefault(cid, {})[what] = projection.jsonable(v)
                sums[projection.jsonable(row[0])] = one
        shown: dict[Any, list] = {}
        if per_group and listed:
            order = projection.order_sql(sheet, sort or [])
            got = cur.execute(
                f"WITH top AS ({top}) SELECT * EXCLUDE (__n) FROM (SELECT t._row, {', '.join(f't.{ident(c.name)}' for c in sheet.columns)}, "
                f"ROW_NUMBER() OVER (PARTITION BY t.{col} ORDER BY {order}) AS __n FROM {table} t JOIN top "
                f"ON t.{col} IS NOT DISTINCT FROM top.__gv WHERE {where}) WHERE __n <= {per_group} ORDER BY __n",
                [*params, *params]).fetchall()
            at = 1 + next(i for i, c in enumerate(sheet.columns) if c.id == g.id)
            for r in got:
                shown.setdefault(projection.jsonable(r[at]), []).append([projection.jsonable(v) for v in r])
    finally:
        cur.close()
    out = []
    for value, n in listed:
        v = projection.jsonable(value)
        out.append({"value": v, "rows": int(n), "totals": sums.get(v, {}),
                    "shown": shown.get(v, [])})
    return {"group": g.id, "total": total, "totals": overall, "groups": out, "groups_total": n_groups,
            "groups_not_listed": max(0, n_groups - len(out)), "columns": [c.id for c in sheet.columns]}


# ── a board ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _lane_order(c: Column, seen: list[Any]) -> list[Any]:
    if c.kind == kinds.YESNO:
        first = [True, False]
    else:
        first = list(c.choices)
    rest = sorted((v for v in seen if v not in first and v is not None), key=str)
    return [*first, *rest, *([None] if None in seen else [])]


def board(sheet: Sheet, *, conditions: list[Condition], search: str = "", sort: Optional[list[dict]] = None,
          column: str, per_lane: int = LANE_CARDS, org: str = "") -> dict:
    """The view's rows as lanes by a choice or yes/no column: each lane's rows and its first cards in the view's order.
    A value the view's filter leaves out is not a lane; it is listed with its rows in the whole sheet. A choice no row
    holds yet is an empty lane, so a card can be moved into it."""
    c = _column(sheet, column, "the board")
    if c.kind not in BOARD_KINDS:
        raise ViewRefused(f"{c.name} is {kinds.LABELS.get(c.kind, c.kind)}; a board's lanes are a choice or a yes/no "
                          "column")
    where, params = projection.where_sql(sheet, conditions, search)
    table, col = ident(sheet.table), ident(c.name)
    per_lane = max(0, min(int(per_lane), 100))
    cur = projection.cursor(org)
    try:
        total = int(cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
        in_view = {projection.jsonable(v): int(n) for v, n in cur.execute(
            f"SELECT {col}, COUNT(*) FROM {table} WHERE {where} GROUP BY 1", params).fetchall()}
        in_sheet = {projection.jsonable(v): int(n) for v, n in cur.execute(
            f"SELECT {col}, COUNT(*) FROM {table} GROUP BY 1").fetchall()}
        cards: dict[Any, list] = {}
        if per_lane and in_view:
            order = projection.order_sql(sheet, sort or [])
            got = cur.execute(
                f"SELECT * EXCLUDE (__n) FROM (SELECT _row, {_names(sheet)}, ROW_NUMBER() OVER (PARTITION BY {col} "
                f"ORDER BY {order}) AS __n FROM {table} WHERE {where}) WHERE __n <= {per_lane} ORDER BY __n",
                params).fetchall()
            at = 1 + next(i for i, x in enumerate(sheet.columns) if x.id == c.id)
            for r in got:
                cards.setdefault(projection.jsonable(r[at]), []).append([projection.jsonable(v) for v in r])
    finally:
        cur.close()
    lanes, not_shown = [], []
    for v in _lane_order(c, list({*in_view, *in_sheet})):
        if in_view.get(v):
            lanes.append({"value": v, "rows": in_view[v], "cards": cards.get(v, [])})
        elif in_sheet.get(v):
            not_shown.append({"value": v, "rows": in_sheet[v]})
        elif v is not None:
            lanes.append({"value": v, "rows": 0, "cards": []})
    return {"column": c.id, "total": total, "lanes": lanes, "not_shown": not_shown,
            "columns": [x.id for x in sheet.columns], "movable": c.role == "stored"}


# ── a calendar ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _month_bounds(month: str) -> tuple[date, date]:
    try:
        y, m = (int(x) for x in month.split("-")[:2])
        first = date(y, m, 1)
    except (ValueError, TypeError):
        raise ViewRefused(f"{month!r} is not a month; it is written 2018-09") from None
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return first, nxt


def calendar(sheet: Sheet, *, conditions: list[Condition], search: str = "", column: str, month: str = "",
             org: str = "") -> dict:
    """The view's rows placed by a date column, one month at a time: how many fall on each day, the month's rows, and
    how many rows have no date and so are on no day. Without a month asked for, the month where the rows end: the
    latest month holding at least one in a hundred of the view's dated rows, so a straggler months past the rest (one
    Olist order estimated for November 2018, after 2,001 in September) does not open an empty calendar."""
    c = _column(sheet, column, "the calendar")
    if c.kind not in CALENDAR_KINDS:
        raise ViewRefused(f"{c.name} is {kinds.LABELS.get(c.kind, c.kind)}; a calendar places rows by a date")
    where, params = projection.where_sql(sheet, conditions, search)
    table, day = ident(sheet.table), f"CAST({ident(c.name)} AS DATE)"
    cur = projection.cursor(org)
    try:
        total, undated, earliest, latest = cur.execute(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE {ident(c.name)} IS NULL), MIN({day}), MAX({day}) FROM {table} "
            f"WHERE {where}", params).fetchone()
        months = cur.execute(f"SELECT strftime({day}, '%Y-%m') AS m, COUNT(*) FROM {table} WHERE ({where}) AND "
                             f"{day} IS NOT NULL GROUP BY 1 ORDER BY 1 DESC", params).fetchall()
        dated = sum(int(n) for _, n in months)
        where_rows_end = next((m for m, n in months if int(n) * 100 >= dated), None) or (
            months[0][0] if months else date.today().strftime("%Y-%m"))
        first, nxt = _month_bounds(month or where_rows_end)
        days = cur.execute(f"SELECT {day} AS d, COUNT(*) FROM {table} WHERE ({where}) AND {day} >= ? AND {day} < ? "
                           "GROUP BY 1 ORDER BY 1", [*params, first, nxt]).fetchall()
    finally:
        cur.close()
    return {"column": c.id, "month": first.strftime("%Y-%m"), "where_rows_end": where_rows_end,
            "total": int(total), "undated": int(undated),
            "earliest": projection.jsonable(earliest), "latest": projection.jsonable(latest),
            "days": [{"day": d.isoformat(), "rows": int(n)} for d, n in days],
            "month_rows": sum(int(n) for _, n in days)}
