"""The rows a question asked beside a sheet is about, put on the grid (Arc SH, SH-4; flag ``sheets.chat``).

Asked beside a sheet "which orders have no carrier date?", the conversation answered as it would anywhere: a breakdown
by status and a chart, with no count of the rows asked about, and one of the seven groups its own query returned left
out — the one that mattered, two delivered orders with no carrier date (live, trace d77fd873). The mockup answers a
question about rows with how many there are of what whole, and the rows themselves on the grid.

So a question summoned from a sheet gets one more tool, ``show_rows``: a filter in the sheet's own terms — its columns
by name, the grid's own operators — checked, and counted by the grid's own reading of a filter (``projection.where_sql``),
so the count the answer gives is the count the grid will show. Its frame puts a card under the answer that shows the
rows in the grid, or keeps them as a view; nothing is changed until the person does either. The tool is bound to the
sheet on screen by closure, as the conversation's tools are bound to their connection: the model cannot name another.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from aughor.agent.tool_loop import ToolSpec
from aughor.sheets import model, projection
from aughor.sheets.imports import ident
from aughor.sheets.model import Condition, Sheet, View

#: The grid's operators a condition may use, as the filter box offers them; ``marked`` takes a rule's name.
OPS = ("is", "is_not", "in", "not_in", "contains", "not_contains", "gt", "gte", "lt", "lte", "before", "after",
       "on", "empty", "not_empty", "marked", "not_marked")

_OP_WORDS = {"is": "is", "is_not": "is not", "in": "is one of", "not_in": "is none of", "contains": "contains",
             "not_contains": "lacks", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "before": "before",
             "after": "after", "on": "on", "empty": "is empty", "not_empty": "is filled", "marked": "marked",
             "not_marked": "not marked"}

#: The conditions one call may carry.
MAX_CONDITIONS = 8

_PARAMS = {
    "type": "object",
    "properties": {
        "conditions": {
            "type": "array", "maxItems": MAX_CONDITIONS,
            "description": "The rows asked about, as the grid's filter: every condition must hold.",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string", "description": "A column of the sheet, by its name."},
                    "op": {"type": "string", "enum": list(OPS)},
                    "value": {"description": "The value to compare with — a list for in / not_in, a day as "
                                             "YYYY-MM-DD for a date, a rule's name for marked; none for empty."},
                },
                "required": ["column", "op"],
            },
        },
        "within_view": {"type": "boolean",
                        "description": "True when the person means the rows the view on screen shows (\"these\", "
                                       "\"of them\"): its own filter is added to these conditions."},
        "sort": {"type": "object", "description": "How to order the rows, when the question says (\"the oldest\").",
                 "properties": {"column": {"type": "string"}, "descending": {"type": "boolean"}},
                 "required": ["column"]},
        "about": {"type": "string",
                  "description": "What these rows are, in a few words — the name a view of them would take, "
                                 "e.g. \"Orders with no carrier date\"."},
    },
    "required": ["conditions", "about"],
}


class RowsRefused(ValueError):
    """Why the rows asked for cannot be shown, in a sentence the model can repair from."""


def _sheet_and_view(ref: str) -> tuple[Sheet, Optional[View]]:
    sheet_id, _, view_id = (ref or "").partition(":")
    sheet = model.get(sheet_id)
    if sheet is None:
        raise RowsRefused(f"no sheet {sheet_id!r} is kept here")
    return sheet, next((v for v in sheet.views if v.id == view_id), None)


def conditions_of(sheet: Sheet, raw: list) -> list[Condition]:
    """The model's conditions in the grid's own form: each column found by name, each operator the grid's, a rule
    named by its name — refused with what is wrong, never guessed."""
    if not isinstance(raw, list) or not raw:
        raise RowsRefused("say which rows: at least one condition {column, op, value}")
    if len(raw) > MAX_CONDITIONS:
        raise RowsRefused(f"at most {MAX_CONDITIONS} conditions")
    out = []
    for c in raw:
        if not isinstance(c, dict):
            raise RowsRefused("each condition is {column, op, value}")
        op = str(c.get("op") or "")
        if op not in OPS:
            raise RowsRefused(f"{op!r} is not one of the grid's operators: {', '.join(OPS)}")
        value: Any = c.get("value")
        if op in ("marked", "not_marked"):
            rule = next((r for r in sheet.rules if str(value or "").strip().lower() in (r.id, r.name.lower())), None)
            if rule is None:
                raise RowsRefused(f"{sheet.name} has no rule {value!r}"
                                  + (f"; its rules are {', '.join(r.name for r in sheet.rules)}" if sheet.rules else ""))
            out.append(Condition(column="", op=op, value=rule.id))
            continue
        col = sheet.column(str(c.get("column") or ""))
        if col is None:
            raise RowsRefused(f"{c.get('column')!r} is not a column of {sheet.name}; its columns are "
                              + ", ".join(x.name for x in sheet.columns))
        out.append(Condition(column=col.id, op=op, value=None if op in ("empty", "not_empty") else value))
    return out


def said(sheet: Sheet, conditions: list[Condition]) -> str:
    """A filter in words, as the grid's filter box says it: "order_delivered_carrier_date is empty · …"."""
    parts = []
    for c in conditions:
        if c.op in ("marked", "not_marked"):
            rule = next((r for r in sheet.rules if r.id == c.value), None)
            parts.append(f"{_OP_WORDS[c.op]} {rule.name if rule else 'by a rule that was taken off'}")
            continue
        col = sheet.column(c.column)
        name = col.name if col else c.column
        if c.op in ("empty", "not_empty"):
            parts.append(f"{name} {_OP_WORDS[c.op]}")
            continue
        value = ", ".join(str(v) for v in c.value) if isinstance(c.value, list) else str(c.value)
        parts.append(f"{name} {_OP_WORDS.get(c.op, c.op)} {value}")
    return " · ".join(parts)


def _count(sheet: Sheet, conditions: list[Condition], search: str) -> int:
    """How many rows the filter holds — the grid's own reading of a filter, on the sheet's table."""
    where, params = projection.where_sql(sheet, conditions, search)
    cur = projection.cursor()
    try:
        return int(cur.execute(f"SELECT COUNT(*) FROM {ident(sheet.table)} WHERE {where}", params).fetchone()[0])
    finally:
        cur.close()


def show_rows(ref: str, args: dict, *, emit: Optional[Callable[[str, dict], None]] = None) -> dict:
    """The rows asked about, checked and counted as the grid counts them, and put under the answer as a card that
    shows them in the grid — or why they cannot be, for the model to repair."""
    from aughor.sheets.dashboard import rows_noun
    try:
        sheet, view = _sheet_and_view(ref)
        conditions = conditions_of(sheet, (args or {}).get("conditions"))
        within = bool((args or {}).get("within_view")) and view is not None and bool(view.filter or view.search)
        whole = list(view.filter) if within and view else []
        search = view.search if within and view else ""
        sort = []
        raw_sort = (args or {}).get("sort")
        if isinstance(raw_sort, dict) and raw_sort.get("column"):
            col = sheet.column(str(raw_sort["column"]))
            if col is None:
                raise RowsRefused(f"the sort names {raw_sort['column']!r}, which is not a column of {sheet.name}")
            sort = [{"column": col.id, "desc": bool(raw_sort.get("descending"))}]
        try:
            rows = _count(sheet, whole + conditions, search)
            of = _count(sheet, whole, search)
        except projection.FilterRefused as exc:
            raise RowsRefused(str(exc)) from None
    except RowsRefused as exc:
        return {"shown": False, "refused": str(exc)}
    noun = rows_noun(sheet.name)
    about = " ".join(str((args or {}).get("about") or "").split())[:80] or f"{noun.capitalize()} asked about"
    share = round(100 * rows / of, 1) if of else None
    frame = {"sheet": sheet.id, "view": view.id if view else "", "within_view": within,
             "filter": [c.model_dump() for c in whole + conditions], "conditions": [c.model_dump() for c in conditions],
             "sort": sort, "search": search, "about": about,
             "rows": rows, "of": of, "share": share, "said": said(sheet, conditions)}
    if emit is not None:
        emit("sheet_rows", frame)
    whole_words = f"the {of:,} {noun} the view {view.name} shows" if within and view else f"all {of:,} {noun}"
    return {
        "shown": True, "rows": rows, "of": of, "share_percent": share, "noun": noun, "filter_said": frame["said"],
        "out_of": whole_words,
        "on_screen": ("A card under your answer offers to show these rows in the grid and to keep them as a view. "
                      "Say how many there are of what whole; do not list the rows or their ids — the grid shows them."
                      if rows else "No row matches: say so, and what the filter was."),
    }


def sheet_tools(ref: str, *, emit: Optional[Callable[[str, dict], None]] = None) -> list[ToolSpec]:
    """The tools a question summoned from a sheet gets beside the conversation's own — none while the chat beside a
    sheet is off, so every other turn is handed exactly the tools it was."""
    from aughor import sheets
    if not ref or not sheets.on(sheets.CHAT):
        return []
    return [ToolSpec(
        name="show_rows",
        description=(
            "Put the rows a question about this sheet asks for on its grid: which rows, the ones that, show me, find, "
            "list. Give the rows as the grid's filter, by the sheet's column names; the platform checks it, counts "
            "the rows as the grid counts them, and shows the person a card that opens them in the grid or keeps "
            "them as a view. Use it whenever the answer IS a set of rows, instead of listing them, and instead of a "
            "query of your own: its count is the answer."
        ),
        parameters=_PARAMS,
        run=lambda a: show_rows(ref, a, emit=emit),
    )]
