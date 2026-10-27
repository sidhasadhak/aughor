"""The chat beside a sheet — answers through a query on the sheet, and changes it proposes (Arc SH, SH-4).

**An answer is a query on the Sheets connection, with its receipt.** The question goes through the one ask door with
the sheet as the object on screen (``AskFocus`` kind ``sheet``): its table, its columns with their kinds, and the view
on screen as the very filter the grid reads (``projection.where_sql``) — written out as SQL, with the grid's own count of
its rows. So "how many of these" counts the rows the grid shows, which is SH-4's falsifier.

**A model proposes; a person applies.** Asked for a change — a view, a computed column, a Yes/No column, a link, a
total — the model calls ONE tool, bound to the sheet. Every change it proposes is checked and counted by code before the
person sees it: a filter is read and its rows counted, an expression is parsed against an allowlist and run against the
sheet, a link counts its matches and misses. What the person reads is the platform's counts, never the model's. They
apply all of it or part, as one change that can be undone; each part is recorded as proposed by the assistant and
applied by them.

**A file dropped into the chat becomes one proposal for a sheet** — its name, its kinds (only kinds every value
fits), a few views, a column for people to tick — created only when the person says so; undo removes it whole.

No model writes a value of the sheet. A proposal holds no figure the platform did not count.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Optional

import duckdb
import sqlglot
from sqlglot import exp

from aughor.sheets import imports, kinds, model, projection, service
from aughor.sheets.imports import ident
from aughor.sheets.model import Column, Condition, Rule, Sheet, View

#: The ledger's kind for a staged proposal.
PROPOSAL_KIND = "sheet_proposal"

#: Steps the model may take: the options, a proposal, and repairs.
MAX_STEPS = 5
MAX_WORDS = 600
#: A proposal holds at most this many changes.
MAX_CHANGES = 6

CHANGE_TYPES = ("view", "computed_column", "column", "link", "total", "rule")


# ── grounding ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return f"TIMESTAMP '{value.isoformat(sep=' ')}'"
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def where_text(sheet: Sheet, conditions: list[Condition], search: str = "") -> str:
    """A view's filter as SQL text with its values written in — the grid's own `where_sql`, so the two cannot differ."""
    where, params = projection.where_sql(sheet, conditions, search)
    parts = where.split("?")
    if len(parts) - 1 != len(params):
        raise ValueError("the filter's values do not match its placeholders")
    out = parts[0]
    for value, rest in zip(params, parts[1:]):
        out += _literal(value) + rest
    return out


def _column_line(c: Column, sheet: Sheet) -> dict:
    line: dict[str, Any] = {"name": c.name, "kind": kinds.LABELS.get(c.kind, c.kind)}
    if c.description:
        line["description"] = c.description
    if c.kind == kinds.CHOICE and c.choices:
        line["values"] = c.choices[:12]
    if c.kind == kinds.MONEY:
        line["currency"] = c.currency or "not confirmed — say amounts plainly"
    if c.kind == kinds.DATE:
        line["compare"] = "by calendar day — never against a timestamp's time of day"
    if c.model_writes is not None:
        line["written_by_a_model"] = ("each value is a model's reading, not a fact: never count by it, never total it, "
                                      "and never state its values as findings; empty means not filled yet")
    if c.role == "computed":
        line["computed_from"] = c.expression
    elif c.role == "lookup":
        via = sheet.column(c.via)
        other = model.get(via.link.sheet) if via and via.link else None
        line["read_from"] = f"{other.name if other else 'a removed sheet'} through {via.name if via else '?'}"
    elif c.role == "total":
        other = model.get(c.sheet)
        line["total"] = f"{c.how} of {other.name if other else 'a removed sheet'} rows per {sheet.column(c.by).name}"
    if c.kind == kinds.LINK and c.link:
        other = model.get(c.link.sheet)
        line["links_to"] = other.name if other else "a removed sheet"
    return line


def how_to_answer(sheet: Sheet) -> list[str]:
    """How a question asked beside a sheet is answered — the mockup's answers (a count of what was asked of its whole;
    the rows themselves on the grid), said to the conversation, which otherwise answers as an analyst would anywhere:
    a breakdown nobody asked for, a chart, no count of the rows asked about (live, trace d77fd873)."""
    from aughor.sheets.dashboard import rows_noun
    noun = rows_noun(sheet.name)
    return [
        "The person is looking at this sheet's grid; answer as the sheet would, in one or two sentences.",
        f"Asked which {noun}, or to show, find or list some (\"which {noun} have…\", \"the ones that…\"): call "
        "show_rows with them as the grid's filter, and nothing else — no query of your own first, no breakdown. It "
        "counts them as the grid does and puts them under your answer, to open in the grid. Say how many there are "
        f"of what whole (\"312 of 4,800 {noun} have no due date.\") — never list the rows or their ids.",
        "Asked how many: lead with the number and its whole, and the share where it helps.",
        "Break the rows down only when asked by or per something: run_sql for the groups and — when the rows broken "
        "down are some of the sheet's, not all — show_rows for them too, so the answer opens on how many of what whole. "
        "Give every group the query returned, or say how many you left out. Name what stands out only from what a "
        "query returned.",
        f"Query the table {sheet.table} on this connection with run_sql — answer_question does not know the sheet. "
        "Quote every column name in double quotes. Compare a Date column by day; never compare it with a timestamp.",
    ]


def explain_sheet(ref: str) -> dict:
    """The sheet on screen as the conversation is handed it (``ref`` is ``<sheet id>`` or ``<sheet id>:<view id>``):
    the table to query, its columns, and the view's filter as SQL with the grid's own count of its rows."""
    from aughor import sheets
    sheet_id, _, view_id = (ref or "").partition(":")
    if not sheets.on(sheets.CHAT):
        return {"found": False, "kind": "sheet", "id": ref, "summary": "The chat beside a sheet is off."}
    sheet = model.get(sheet_id)
    if sheet is None:
        return {"found": False, "kind": "sheet", "id": ref, "summary": f"No sheet {sheet_id!r} is kept here."}
    from aughor.sheets.sharing import NotShared, readable
    try:
        readable(sheet)
    except NotShared as exc:
        return {"found": False, "kind": "sheet", "id": ref, "summary": str(exc)}
    view = next((v for v in sheet.views if v.id == view_id), None)
    total = projection.count(sheet)
    out: dict[str, Any] = {
        "found": True, "kind": "sheet", "id": ref, "name": sheet.name, "table": sheet.table, "rows": total,
        # before the columns: the conversation is handed this capped, and a wide sheet's columns must not cut it off
        "how_to_answer": how_to_answer(sheet),
        "columns": [_column_line(c, sheet) for c in sheet.columns],
    }
    if view is not None and (view.filter or view.search):
        where = where_text(sheet, view.filter, view.search)
        shown = projection.read_rows(sheet, conditions=view.filter, search=view.search, limit=1)["total"]
        out["view"] = {"name": view.name, "where": where, "rows": shown,
                       "rule": (f'When the person says "these", "this view" or "the ones shown", they mean the '
                                f"{shown:,} rows WHERE {where}; add that condition to every query about them.")}
    elif view is not None:
        out["view"] = {"name": view.name, "where": "TRUE", "rows": total}
    out["summary"] = (f"The sheet {sheet.name} (table {sheet.table}, {total:,} rows, {len(sheet.columns)} columns)"
                      + (f", open on the view {view.name} ({out['view']['rows']:,} rows)" if view else "") + ".")
    return out


# ── checking a proposed change ───────────────────────────────────────────────────────────────────────────────────────

#: The functions a computed column may call — scalar, of the row's own values; nothing that reads a file, a table, the
#: environment or another row.
FUNCTIONS = frozenset({
    "abs", "round", "ceil", "ceiling", "floor", "greatest", "least", "coalesce", "ifnull", "nullif", "if", "iif",
    "lower", "upper", "length", "trim", "ltrim", "rtrim", "concat", "concat_ws", "substr", "substring", "replace",
    "left", "right", "strpos", "contains", "starts_with", "ends_with", "regexp_matches", "lpad", "rpad",
    "date_diff", "datediff", "date_sub", "date_add", "date_trunc", "date_part", "datepart", "extract", "year",
    "month", "day", "dayofweek", "week", "quarter", "strftime", "strptime", "to_date", "make_date", "last_day",
    "current_date", "today", "age", "epoch", "sign", "sqrt", "pow", "power", "ln", "log", "exp", "mod",
    "cast", "try_cast", "case", "currentdate", "dateadd", "datesub", "datetrunc", "datediff", "strtodate",
    "timetostr", "strtotime", "tsordstodate", "length", "concatws", "stuff", "nullif", "greatest", "least",
})

_ALLOWED_NODES = (exp.Column, exp.Identifier, exp.Literal, exp.Boolean, exp.Null, exp.Paren, exp.Neg, exp.Not,
                  exp.And, exp.Or, exp.Binary, exp.Case, exp.If, exp.Cast, exp.TryCast, exp.DataType,
                  exp.Interval, exp.Var, exp.Between, exp.In, exp.Is, exp.Tuple, exp.Unary, exp.DataTypeParam)


class ChangeRefused(ValueError):
    """Why a proposed change cannot be offered, in a sentence the model can repair from."""


def check_expression(sheet: Sheet, expression: str) -> str:
    """A computed column's expression, refused unless it is a scalar over the sheet's own columns: parsed, every node
    on an allowlist, every column one the sheet has. Returned as DuckDB writes it."""
    text = (expression or "").strip()
    if not text or len(text) > 2000:
        raise ChangeRefused("a computed column needs an expression of at most 2,000 characters")
    try:
        tree = sqlglot.parse_one(text, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise ChangeRefused(f"the expression does not parse: {str(exc).splitlines()[0][:200]}") from None
    names = {c.name.lower() for c in sheet.columns}
    for node in tree.walk():
        if isinstance(node, exp.Column):
            if node.table or node.name.lower() not in names:
                raise ChangeRefused(f"{node.sql()} is not a column of {sheet.name}; its columns are "
                                    + ", ".join(c.name for c in sheet.columns))
            continue
        if isinstance(node, exp.Func):
            fname = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if fname not in FUNCTIONS and fname.replace("_", "") not in FUNCTIONS:
                raise ChangeRefused(f"{fname} is not a function a computed column may call")
            continue
        if not isinstance(node, _ALLOWED_NODES):
            raise ChangeRefused(f"{type(node).__name__} is not allowed in a computed column — an expression over the "
                                "row's own values only")
    return tree.sql(dialect="duckdb")


def _kind_of_type(duck: str) -> tuple[str, bool]:
    t = duck.upper()
    if t in ("BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT", "UINTEGER"):
        return kinds.NUMBER, True
    if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
        return kinds.NUMBER, False
    if t == "DATE":
        return kinds.DATE, False
    if t.startswith("TIMESTAMP"):
        return kinds.DATETIME, False
    if t == "BOOLEAN":
        return kinds.YESNO, False
    return kinds.TEXT, False


def _conditions(sheet: Sheet, raw: list) -> list[Condition]:
    out = []
    for c in raw or []:
        if not isinstance(c, dict):
            raise ChangeRefused("each filter condition is {column, op, value}")
        col = sheet.column(str(c.get("column") or ""))
        if col is None:
            raise ChangeRefused(f"{c.get('column')!r} is not a column of {sheet.name}")
        out.append(Condition(column=col.id, op=str(c.get("op") or "is"), value=c.get("value")))
    return out


def check_change(sheet: Sheet, change: dict, cur) -> dict:
    """One proposed change, checked and counted against the sheet: what the person will read about it."""
    kind = str(change.get("type") or "")
    if kind not in CHANGE_TYPES:
        raise ChangeRefused(f"{kind!r} is not a change; the changes are {', '.join(CHANGE_TYPES)}")
    name = " ".join(str(change.get("name") or "").split())[:80]
    if kind == "view":
        conds = _conditions(sheet, change.get("filter") or [])
        sort = []
        for s in change.get("sort") or []:
            col = sheet.column(str((s or {}).get("column") or ""))
            if col is None:
                raise ChangeRefused(f"the sort names {s!r}, which is not a column of {sheet.name}")
            sort.append({"column": col.id, "desc": bool(s.get("desc"))})
        hidden = [sheet.column(h).id for h in (change.get("hidden") or []) if sheet.column(h)]
        try:
            where, params = projection.where_sql(sheet, conds)
        except projection.FilterRefused as exc:
            raise ChangeRefused(str(exc)) from None
        rows = int(cur.execute(f"SELECT COUNT(*) FROM {ident(sheet.table)} WHERE {where}", params).fetchone()[0])
        if not name:
            raise ChangeRefused("a view needs a name")
        return {"type": "view", "name": name, "filter": [c.model_dump() for c in conds], "sort": sort,
                "hidden": hidden, "rows": rows, "where": where_text(sheet, conds),
                "said": f"View {name} — {rows:,} rows"}
    if kind == "computed_column":
        expr = check_expression(sheet, str(change.get("expression") or ""))
        if not name:
            raise ChangeRefused("a computed column needs a name")
        if sheet.column(name):
            raise ChangeRefused(f"{sheet.name} already has a column {name}")
        try:
            typ = cur.execute(f"SELECT typeof(({expr})) FROM {ident(sheet.table)} LIMIT 1").fetchone()
            filled, total = cur.execute(f"SELECT COUNT(TRY(({expr}))), COUNT(*) FROM {ident(sheet.table)}").fetchone()
        except duckdb.Error as exc:
            raise ChangeRefused(f"the expression does not run on {sheet.name}: {str(exc).splitlines()[0][:200]}") \
                from None
        k, integer = _kind_of_type(typ[0] if typ else "VARCHAR")
        return {"type": "computed_column", "name": name, "expression": expr, "kind": k, "integer": integer,
                "filled": int(filled), "rows": int(total),
                "said": f"Column {name} — computed from {expr}, no model; {int(filled):,} of {int(total):,} rows "
                        "have a value"}
    if kind == "column":
        col_kind = str(change.get("kind") or kinds.TEXT)
        if col_kind not in kinds.KINDS or col_kind == kinds.LINK:
            raise ChangeRefused(f"{col_kind!r} is not a kind for a new column")
        if not name:
            raise ChangeRefused("a column needs a name")
        if sheet.column(name):
            raise ChangeRefused(f"{sheet.name} already has a column {name}")
        return {"type": "column", "name": name, "kind": col_kind,
                "description": str(change.get("description") or "")[:300],
                "said": f"Column {name} — {kinds.LABELS[col_kind]}, empty, for people to fill"}
    from aughor import sheets
    if kind == "rule":
        return _check_rule(sheet, change, name, cur)
    if not sheets.on(sheets.COMBINE):
        raise ChangeRefused("combining sheets is off here, so a link or a total cannot be proposed")
    from aughor.sheets import combine
    other = _named_sheet(str(change.get("other") or ""))
    if kind == "link":
        try:
            seen = combine.link_preview(sheet, str(change.get("column") or ""), other.id,
                                        str(change.get("other_column") or ""))
        except service.Refused as exc:
            raise ChangeRefused(str(exc)) from None
        bring = [other.column(b).id for b in (change.get("bring") or []) if other.column(b)]
        if bring and seen["other_repeats"]:
            raise ChangeRefused(f"keys repeat in {other.name}; bring nothing, or propose a total instead")
        return {"type": "link", "column": seen["column"], "other": other.id, "other_name": other.name,
                "other_column": seen["other_column"], "bring": bring, "matched": seen["matched"],
                "missed": seen["missed"], "empty": seen["empty"],
                "said": f"Link {sheet.column(seen['column']).name} → {other.name}: {seen['matched']:,} of "
                        f"{seen['rows']:,} rows match, {seen['missed']:,} miss"}
    try:
        how = str(change.get("how") or "sum")
        of = other.column(str(change.get("of") or ""))
        seen = combine.total_preview(sheet, str(change.get("by_column") or ""), other.id,
                                     str(change.get("other_key") or ""), how, of.id if of else "")
    except service.Refused as exc:
        raise ChangeRefused(str(exc)) from None
    return {"type": "total", "name": name or f"{how} of {other.name}", "by_column": sheet.column(
        str(change.get("by_column"))).id, "other": other.id, "other_name": other.name,
        "other_key": other.column(str(change.get("other_key"))).id, "how": how, "of": of.id if of else "",
        "rows_with": seen["rows_with"], "rows_without": seen["rows_without"],
        "said": f"Column {name or how} — the {how} of {other.name} per row; {seen['rows_with']:,} rows have some, "
                f"{seen['rows_without']:,} have none and show empty"}


def _check_rule(sheet: Sheet, change: dict, name: str, cur) -> dict:
    """A rule (SH-3) — a name and conditions as a view's filter writes them — counted as the grid counts the rows it
    marks: a row its conditions cannot read (an empty date) is not marked."""
    from aughor import sheets
    from aughor.sheets.views import TONES, ViewRefused, check_rule
    if not sheets.on(sheets.VIEWS):
        raise ChangeRefused("rules are off here, so no row can be marked; propose a view instead")
    conds = _conditions(sheet, change.get("conditions") or change.get("filter") or [])
    try:
        check_rule(sheet, conds)
        where, params = projection.where_sql(sheet, conds)
    except (ViewRefused, projection.FilterRefused) as exc:
        raise ChangeRefused(str(exc)) from None
    if not name:
        raise ChangeRefused("a rule needs a name — what the rows it marks have in common")
    if any(r.name.lower() == name.lower() for r in sheet.rules):
        raise ChangeRefused(f"{sheet.name} already has a rule called {name}")
    tone = str(change.get("tone") or "amber")
    if tone not in TONES:
        raise ChangeRefused(f"{tone!r} is not a mark's colour; it is one of {', '.join(TONES)}")
    rows = int(cur.execute(f"SELECT COUNT(*) FROM {ident(sheet.table)} WHERE COALESCE(({where}), FALSE)",
                           params).fetchone()[0])
    return {"type": "rule", "name": name, "conditions": [c.model_dump() for c in conds], "tone": tone, "rows": rows,
            "where": where_text(sheet, conds), "said": f"Rule {name} — marks {rows:,} rows"}


def _applied_from(sheet_id: str) -> Sheet:
    """The other sheet a link or a total being applied reads — still there, and one the person applying it may read:
    whoever applies a proposal may not be who asked for it."""
    from aughor.sheets.sharing import readable
    other = model.get(sheet_id)
    if other is None:
        raise service.Refused("the sheet this would read from is gone")
    return readable(other)


def _named_sheet(ref: str) -> Sheet:
    s = model.get(ref) if model.valid_id(ref) else None
    if s is None:
        low = ref.strip().lower()
        s = next((x for x in model.list_sheets() if x.name.lower() == low or x.table == low), None)
    if s is None:
        raise ChangeRefused(f"there is no sheet {ref!r}; the sheets are "
                            + ", ".join(x.name for x in model.list_sheets()))
    return s


# ── proposals ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id() or "default"


def _key(proposal_id: str) -> str:
    return f"{PROPOSAL_KIND}:{_org()}:{proposal_id}"


def _stage(body: dict) -> dict:
    from aughor.kernel.ledger import Ledger
    pid = uuid.uuid4().hex[:12]
    body = {**body, "id": pid, "state": "staged", "staged_at": model.now()}
    Ledger.default().artifact_write(PROPOSAL_KIND, _key(pid), body, conn_id=model.SHEETS_CONNECTION)
    return body


def proposal(proposal_id: str) -> Optional[dict]:
    if not re.fullmatch(r"[0-9a-f]{12}", proposal_id or ""):
        return None
    from aughor.kernel.ledger import Ledger
    art = Ledger.default().artifact_latest(_key(proposal_id))
    return dict(art["payload"]) if art and isinstance(art.get("payload"), dict) else None


def _record_applied(p: dict, picks: list[int], by: str, change_id: str) -> None:
    from aughor.kernel.ledger import Ledger
    Ledger.default().artifact_write(PROPOSAL_KIND, _key(p["id"]),
                                    {**p, "state": "applied", "applied": picks, "applied_by": by,
                                     "applied_at": model.now(), "change_id": change_id},
                                    conn_id=model.SHEETS_CONNECTION)


SYSTEM = (
    "You propose changes to ONE sheet a person is looking at, exactly as they ask in words, and nothing else. "
    "Call propose_sheet_changes with op options first: it returns the sheet's columns with their kinds and a few values, "
    "its views, how many rows it holds, the date its newest row is from, and the other sheets. Then call it ONCE with "
    "op propose and the changes: a view (a name, a filter of {column, op, value} conditions, a sort), a "
    "computed_column (a name and a DuckDB expression over this sheet's columns, each column name in double quotes — "
    "for a date, compare by day and use a date from the data, not today, when the data is old), a column (a name and "
    "a kind, empty, for people to fill — Yes/No is yesno), a link (this sheet's column to another sheet's key, and the "
    "columns to bring), or a total (another sheet's rows per key: sum, count, average, min, max, earliest, latest). "
    "A rule marks the rows that need attention: a name and conditions written as a view's filter is; it is "
    "proposed only when rules are on. "
    "Filter ops are is, is_not, in, not_in, contains, gt, gte, lt, lte, before, after, empty, not_empty. The platform "
    "checks and counts every change before the person sees it; state no figure yourself. When a change is refused, "
    "repair it and propose again. When the proposal is staged, stop."
)


def _options(sheet: Sheet, cur) -> dict:
    sample = {}
    for c in sheet.columns[:40]:
        got = cur.execute(f"SELECT DISTINCT {ident(c.name)} FROM {ident(sheet.table)} WHERE {ident(c.name)} IS NOT NULL "
                          "LIMIT 4").fetchall()
        sample[c.name] = [projection.jsonable(r[0]) for r in got]
    newest = {}
    for c in sheet.columns:
        if c.kind in (kinds.DATE, kinds.DATETIME):
            v = cur.execute(f"SELECT MAX({ident(c.name)}) FROM {ident(sheet.table)}").fetchone()[0]
            newest[c.name] = projection.jsonable(v)
    return {"sheet": sheet.name, "rows": projection.count(sheet),
            "columns": [{**_column_line(c, sheet), "some_values": sample.get(c.name, [])} for c in sheet.columns],
            "views": [{"name": v.name, "where": where_text(sheet, v.filter, v.search) if v.filter or v.search
                       else "TRUE"} for v in sheet.views],
            "newest_dates": newest,
            "other_sheets": [{"name": o.name, "columns": [c.name for c in o.stored()]}
                             for o in model.list_sheets() if o.id != sheet.id][:20]}


def _tool(sheet: Sheet, words: str, by: str, staged: list) -> Any:
    from aughor.agent.tool_loop import ToolSpec

    def run(args: dict) -> dict:
        op = str((args or {}).get("op") or "")
        cur = projection.cursor()
        try:
            if op == "options":
                return _options(sheet, cur)
            if op != "propose":
                return {"refused": ["op is options or propose"]}
            changes = list((args or {}).get("changes") or [])[:MAX_CHANGES]
            if not changes:
                return {"refused": ["a proposal holds at least one change"]}
            checked, refused = [], []
            for i, ch in enumerate(changes):
                try:
                    checked.append(check_change(sheet, ch if isinstance(ch, dict) else {}, cur))
                except ChangeRefused as exc:
                    refused.append(f"change {i + 1}: {exc}")
            if refused:
                return {"staged": False, "refused": refused}
            p = _stage({"sheet": sheet.id, "sheet_version": sheet.version, "words": words, "asked_by": by,
                        "changes": checked})
            staged.append(p)
            return {"staged": True, "proposal_id": p["id"], "summary": [c["said"] for c in checked]}
        finally:
            cur.close()

    return ToolSpec(
        name="propose_sheet_changes",
        description=("Propose changes to the sheet on screen. op options: its columns, views and the other sheets. "
                     "op propose: changes, a list of {type: view|computed_column|column|link|total|rule, ...}; each is "
                     "checked and counted by the platform before the person sees it, and nothing changes until they "
                     "apply it."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["options", "propose"]},
            "changes": {"type": "array", "items": {"type": "object"}}}, "required": ["op"]},
        run=run)


def propose(sheet: Sheet, words: str, *, by: str, provider: Any = None) -> dict:
    """Run the model once for a change a person asks for in words. What comes back is a staged proposal — every
    change in it checked and counted — or the reasons none was staged, as sentences."""
    from aughor.agent.tool_loop import run_tool_loop
    words = " ".join((words or "").split())[:MAX_WORDS]
    if not words:
        return {"staged": False, "sentences": ["Say what to change — a view, a column, a link to another sheet."]}
    if provider is None:
        from aughor.agent.converse_tools import binding_calls_tools
        if not binding_calls_tools():
            return {"staged": False, "sentences": ["The model this install proposes with cannot call tools, so it "
                                                   "cannot propose a change. Choose one that can in the model "
                                                   "settings."]}
        from aughor.llm.provider import get_provider
        provider = get_provider("coder")
    staged: list[dict] = []
    tool = _tool(sheet, words, by, staged)
    results: list[dict] = []

    def run(args: dict) -> dict:
        out = tool.run(args)
        if (args or {}).get("op") == "propose":
            results.append(out)
        return out

    from aughor.agent.tool_loop import ToolSpec
    result = run_tool_loop(provider, SYSTEM, f'Of the sheet "{sheet.name}", the person asks: {words}',
                           [ToolSpec(name=tool.name, description=tool.description, parameters=tool.parameters,
                                     run=run)],
                           max_steps=MAX_STEPS, conn_id=model.SHEETS_CONNECTION, site="sheets.propose")
    if staged:
        return {"staged": True, "proposal": staged[-1], "rounds": len(results)}
    refused = list((results[-1] if results else {}).get("refused") or [])
    said = (result.answer or "").strip()
    if said and not re.search(r"\d", said):
        refused = [said[:400], *refused]
    return {"staged": False, "sentences": refused or ["The model proposed no change for this, and gave no reason."],
            "rounds": len(results)}


def apply(proposal_id: str, picks: Optional[list[int]], *, by: str) -> dict:
    """Apply a proposal — all of it, or the changes picked — as ONE change to the sheet, each part recorded as proposed
    by the assistant and applied by ``by``. Every change is checked again against the sheet as it stands."""
    p = proposal(proposal_id)
    if p is None or p.get("state") != "staged":
        raise service.Refused("that proposal is not waiting to be applied")
    if p.get("new_sheet"):
        return apply_new_sheet(p, picks, by=by)
    sheet = model.get(p["sheet"])
    if sheet is None:
        raise service.Refused("the sheet this was proposed for is gone")
    chosen = list(range(len(p["changes"]))) if picks is None else sorted({int(i) for i in picks})
    if not chosen or any(i < 0 or i >= len(p["changes"]) for i in chosen):
        raise service.Refused("pick at least one of the proposal's changes")
    cur = projection.cursor()
    try:
        rechecked = []
        for i in chosen:
            ch = dict(p["changes"][i])
            again = _as_request(sheet, ch)
            try:
                rechecked.append(check_change(sheet, again, cur))
            except ChangeRefused as exc:
                raise service.Refused(f"{ch.get('said', 'a change')} no longer holds: {exc}") from None
    finally:
        cur.close()
    cid = service.change_id()
    origin = f"proposal:{p['id']}"
    said = []
    for ch in rechecked:
        _apply_one(sheet, ch)
        said.append(ch["said"].split(" — ")[0])
    model.save(sheet, what="; ".join(said)[:300], by=by, origin=origin, change_id=cid)
    projection.rebuild(sheet)
    _record_applied(p, chosen, by, cid)
    return {"change_id": cid, "applied": chosen, "sheet": sheet.id}


def _as_request(sheet: Sheet, ch: dict) -> dict:
    """A checked change, back in the shape `check_change` reads, so it is checked again as it is applied."""
    if ch["type"] == "view":
        return {"type": "view", "name": ch["name"], "filter": [{"column": c["column"], "op": c["op"],
                                                               "value": c.get("value")} for c in ch["filter"]],
                "sort": ch["sort"], "hidden": ch["hidden"]}
    if ch["type"] == "link":
        return {"type": "link", "column": ch["column"], "other": ch["other"], "other_column": ch["other_column"],
                "bring": ch["bring"]}
    if ch["type"] == "total":
        return {"type": "total", "name": ch["name"], "by_column": ch["by_column"], "other": ch["other"],
                "other_key": ch["other_key"], "how": ch["how"], "of": ch["of"]}
    if ch["type"] == "rule":
        return {"type": "rule", "name": ch["name"], "tone": ch["tone"],
                "conditions": [{"column": c["column"], "op": c["op"], "value": c.get("value")} for c in ch["conditions"]]}
    return dict(ch)


def _apply_one(sheet: Sheet, ch: dict) -> None:
    """Fold one checked change into the sheet's definition (kept by the caller, as one version)."""
    t = ch["type"]
    if t == "view":
        view = View(id=uuid.uuid4().hex[:8], name=ch["name"], filter=[Condition(**c) for c in ch["filter"]],
                    sort=ch["sort"], hidden=ch["hidden"], made_by="the assistant")
        taken = {v.name.lower() for v in sheet.views}
        base, n = view.name, 2
        while view.name.lower() in taken:
            view.name, n = f"{base} {n}", n + 1
        sheet.views.append(view)
    elif t == "computed_column":
        sheet.columns.append(Column(id=sheet.new_column_id(), name=service.unique_name(ch["name"], sheet),
                                    kind=ch["kind"], integer=ch["integer"], role="computed",
                                    expression=ch["expression"], made_by="the assistant",
                                    description=f"computed from {ch['expression']}"))
    elif t == "column":
        sheet.columns.append(Column(id=sheet.new_column_id(), name=service.unique_name(ch["name"], sheet),
                                    kind=ch["kind"], description=ch.get("description", ""),
                                    made_by="the assistant"))
    elif t == "link":
        from aughor.sheets.model import Link
        other = _applied_from(ch["other"])
        mine = sheet.column(ch["column"])
        mine.kind = kinds.LINK
        mine.link = Link(sheet=other.id, column=ch["other_column"], matched=ch["matched"], missed=ch["missed"])
        for ref in ch["bring"]:
            oc = other.column(ref)
            sheet.columns.append(Column(id=sheet.new_column_id(), name=service.unique_name(oc.name, sheet),
                                        kind=oc.kind, integer=oc.integer, currency=oc.currency, role="lookup",
                                        via=mine.id, of=oc.id, made_by="the assistant",
                                        description=f"{oc.name} of {other.name}, read through {mine.name}"))
    elif t == "total":
        from aughor.sheets.combine import total_kind
        other = _applied_from(ch["other"])
        of = other.column(ch["of"]) if ch["of"] else None
        k, integer, currency = total_kind(ch["how"], of)
        sheet.columns.append(Column(id=sheet.new_column_id(), name=service.unique_name(ch["name"], sheet), kind=k,
                                    integer=integer, currency=currency, role="total", sheet=other.id,
                                    key=ch["other_key"], by=ch["by_column"], how=ch["how"], of=ch["of"],
                                    made_by="the assistant",
                                    description=f"the {ch['how']} of {other.name} rows per row"))
    elif t == "rule":
        name, n = ch["name"], 2
        while any(r.name.lower() == name.lower() for r in sheet.rules):
            name, n = f"{ch['name']} {n}", n + 1
        sheet.rules.append(Rule(id=uuid.uuid4().hex[:8], name=name, tone=ch["tone"], made_by="the assistant",
                                conditions=[Condition(**c) for c in ch["conditions"]]))


# ── a sheet from a file dropped into the chat ────────────────────────────────────────────────────────────────────────

def propose_new_sheet(token: str, words: str, *, by: str, upload: Optional[dict] = None,
                      provider: Any = None, describe_fn: Optional[Callable] = None) -> dict:
    """A file dropped into the chat, as ONE proposal for a sheet: the name, the kinds (only kinds every value fits —
    the import's own reading), and the views and columns the model proposes for what the person says it is for, each
    checked and counted against the file's rows typed as proposed. Nothing is made until the person creates it."""
    from aughor.sheets import files
    path = files.staged(token)
    if path is None:
        return {"staged": False, "sentences": ["That file is no longer here; drop it again."]}
    tab = imports.tabs(path)[0] if path.suffix.lower() == ".xlsx" else ""
    described = (describe_fn or imports.describe)(path, tab)
    kinds_chosen = {c["name"]: c["suggested"] for c in described["columns"]}
    stem = re.sub(r"[_\-]+", " ", path.stem).strip()
    draft = Sheet(id="0000000000", name=stem.title()[:80] or "New sheet", table="_proposed",
                  columns=[Column(id=f"c{i + 1}", name=c["name"], kind=c["suggested"], integer=c["integer"],
                                  choices=[v for v, _ in c["values"]]) for i, c in enumerate(described["columns"])])
    con, raw_cols = imports.open_file(path, tab)
    staged: list[dict] = []
    try:
        selects = ", ".join(f"{kinds.cast_sql(c.kind, ident(c.name), integer=c.integer)} AS {ident(c.name)}"
                            for c in draft.columns)
        con.execute(f'CREATE TABLE "_proposed" AS SELECT _row, {selects} FROM raw')
        checker = con.cursor()

        def run(args: dict) -> dict:
            op = str((args or {}).get("op") or "")
            if op == "options":
                out = _options_for(draft, checker, described)
                return out
            if op != "propose":
                return {"refused": ["op is options or propose"]}
            name = " ".join(str(args.get("name") or draft.name).split())[:80]
            checked, refused = [], []
            for i, ch in enumerate(list(args.get("changes") or [])[:MAX_CHANGES]):
                if isinstance(ch, dict) and ch.get("type") in ("link", "total"):
                    refused.append(f"change {i + 1}: a new sheet is linked once it is made, not before")
                    continue
                try:
                    checked.append(check_change(draft, ch if isinstance(ch, dict) else {}, checker))
                except ChangeRefused as exc:
                    refused.append(f"change {i + 1}: {exc}")
            if refused:
                return {"staged": False, "refused": refused}
            p = _stage({"new_sheet": True, "token": token, "upload": upload or {}, "name": name,
                        "kinds": kinds_chosen, "rows": described["rows"], "file": path.name,
                        "columns": [{"name": c["name"], "kind": c["suggested"], "filled": c["filled"],
                                     "empty": c["empty"], "note": c["note"]} for c in described["columns"]],
                        "words": words, "asked_by": by, "changes": checked})
            staged.append(p)
            return {"staged": True, "proposal_id": p["id"], "summary": [c["said"] for c in checked]}

        from aughor.agent.tool_loop import ToolSpec, run_tool_loop
        if provider is None:
            from aughor.agent.converse_tools import binding_calls_tools
            if not binding_calls_tools():
                run({"op": "propose", "name": draft.name, "changes": []})
            else:
                from aughor.llm.provider import get_provider
                provider = get_provider("coder")
        if provider is not None:
            spec = ToolSpec(name="propose_sheet", description=(
                "Propose the sheet a dropped file becomes. op options: its columns, their kinds and values. op "
                "propose: a name and changes — views, computed columns, columns for people to fill, a rule for the rows "
                "that need attention — each checked and counted on the file's rows before the person sees it."),
                parameters={"type": "object", "properties": {
                    "op": {"type": "string", "enum": ["options", "propose"]}, "name": {"type": "string"},
                    "changes": {"type": "array", "items": {"type": "object"}}}, "required": ["op"]},
                run=run)
            run_tool_loop(provider, SYSTEM_NEW, f"The person dropped {path.name} and says: "
                          f"{' '.join((words or 'make this a sheet').split())[:MAX_WORDS]}", [spec],
                          max_steps=MAX_STEPS, conn_id=model.SHEETS_CONNECTION, site="sheets.propose_new")
        if not staged:
            run({"op": "propose", "name": draft.name, "changes": []})
    finally:
        con.close()
    return {"staged": True, "proposal": staged[-1]}


SYSTEM_NEW = (
    "A person dropped a file to become a sheet, and said what it is for. Call propose_sheet with op options first, then "
    "ONCE with op propose: a short name for the sheet in their words, and a few changes that serve what they said — "
    "views (a name, a filter of {column, op, value}, a sort), a computed_column (a DuckDB expression over the "
    "columns, each name in double quotes), a column for people to fill (Yes/No is yesno), and a rule for the rows "
    "that need attention (a name and conditions written as a filter is; only when rules are on). The kinds are already read "
    "from the file; never change them. State no figure; the platform counts every change. Repair what is refused."
)


def _options_for(draft: Sheet, cur, described: dict) -> dict:
    cols = []
    for c, d in zip(draft.columns, described["columns"]):
        got = cur.execute(f"SELECT DISTINCT {ident(c.name)} FROM \"_proposed\" WHERE {ident(c.name)} IS NOT NULL "
                          "LIMIT 4").fetchall()
        cols.append({"name": c.name, "kind": kinds.LABELS[c.kind], "some_values": [projection.jsonable(r[0])
                                                                                   for r in got],
                     "empty": d["empty"]})
    return {"rows": described["rows"], "columns": cols}


def apply_new_sheet(p: dict, picks: Optional[list[int]], *, by: str) -> dict:
    """Create the proposed sheet with the changes picked, as one change: undo removes it whole."""
    chosen = list(range(len(p["changes"]))) if picks is None else sorted({int(i) for i in picks})
    cid = service.change_id()
    origin = f"proposal:{p['id']}"
    sheet = service.create_from_file(p["token"], name=p["name"], by=by, chosen=p["kinds"],
                                     upload=p.get("upload") or None, origin=origin, cid=cid)
    cur = projection.cursor()
    try:
        rechecked = [check_change(sheet, _as_request_new(sheet, dict(p["changes"][i])), cur) for i in chosen]
    except ChangeRefused as exc:
        service.remove(sheet, by=by, what="removed: a proposed change no longer held", cid=cid)
        raise service.Refused(f"the sheet was not made: {exc}") from None
    finally:
        cur.close()
    if rechecked:
        for ch in rechecked:
            _apply_one(sheet, ch)
        _fold_into_first_version(sheet, by=by, origin=origin, cid=cid)
    from aughor.sheets import files
    files.unstage(p["token"])
    _record_applied(p, chosen, by, cid)
    return {"change_id": cid, "applied": chosen, "sheet": sheet.id}


def _as_request_new(sheet: Sheet, ch: dict) -> dict:
    """A change checked against the proposed table, re-addressed to the sheet as made (column ids differ)."""
    req = _as_request(sheet, ch)
    draft_ids = {f"c{i + 1}": c.name for i, c in enumerate(sheet.columns)}
    if ch["type"] == "rule":
        req["conditions"] = [{**c, "column": draft_ids.get(c["column"], c["column"])} for c in req["conditions"]]
    if ch["type"] == "view":
        req["filter"] = [{**c, "column": draft_ids.get(c["column"], c["column"])} for c in req["filter"]]
        req["sort"] = [{**s, "column": draft_ids.get(s["column"], s["column"])} for s in req["sort"]]
        req["hidden"] = [draft_ids.get(h, h) for h in req["hidden"]]
    return req


def _fold_into_first_version(sheet: Sheet, *, by: str, origin: str, cid: str) -> None:
    """The proposed views and columns are kept in the same change as the sheet's making, so undo removes it whole."""
    model.save(sheet, what=f"made from {sheet.source.file}, as the assistant proposed", by=by, origin=origin,
               change_id=cid)
    projection.rebuild(sheet)
