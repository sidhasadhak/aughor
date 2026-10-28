"""Make a dashboard from a sheet (Arc SH, SH-6 — its first piece).

The platform proposes the cards a sheet holds: how many rows it has, the sum of each money column, the rows per value
of its choice columns, the rows over time by its first date, and a table of the rows. Each card is a query of the
person's own on the Sheets connection (Arc AP-7's card), and each is run on the sheet as it stands before it is
offered, so what is offered is what the card will show. The person ticks what they want; the cards and the dashboard
are kept through the dashboards' own doors, so a card made here is any other card.

**A card here never settles.** It runs its query each time it is read, and what it reads is the table people edit —
the projection a grid edit changes — never a copy. With a view on screen, every card reads the view's rows: its filter
written into the query as the grid reads it (`chat.where_text`), so a card and the grid count the same rows.

Nothing here calls a model and nothing is written; keeping is the dashboards' to do.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.sheets import kinds, model
from aughor.sheets.imports import ident
from aughor.sheets.model import Sheet, View

#: The most money columns summed, and choice columns counted, in one proposal.
MAX_SUMS = 2
MAX_BARS = 2
#: The columns a proposed table lists.
TABLE_COLUMNS = 6
#: The values of a bar a piece's preview names.
PREVIEW_VALUES = 3


def rows_noun(name: str) -> str:
    """What a sheet's rows are called, from its name — the same reading its first view's name takes ("All orders")."""
    last = (name.split() or ["rows"])[-1].lower()
    return last if last.endswith("s") and len(last) > 2 else "rows"


def source_sql(sheet: Sheet, view: Optional[View]) -> tuple[str, str]:
    """The statement every card reads — the sheet's table, narrowed to the view's rows when the view has a filter — and
    the filter as written."""
    from aughor.sheets.chat import where_text
    where = where_text(sheet, view.filter, view.search) if view and (view.filter or view.search) else ""
    return f"SELECT * FROM {ident(sheet.table)}" + (f" WHERE {where}" if where else ""), where


def _pieces(sheet: Sheet, view: Optional[View]) -> list[dict]:
    noun = rows_noun(sheet.name)
    # SH-5: a column a model writes is never a card's figure
    shown_cols = [c for c in sheet.columns if not (view and c.id in view.hidden) and not c.hidden
                  and c.model_writes is None]
    dates = [c for c in shown_cols if c.kind in (kinds.DATE, kinds.DATETIME)]
    out: list[dict] = [{"key": "rows", "title": noun.capitalize(), "kind": "figure", "size": "small",
                        "why": f"how many {noun} {'the view shows' if view and view.filter else 'the sheet holds'}",
                        "shown": {"as": "figure", "series": [{"column": "", "agg": "count"}], "label": noun.capitalize()}}]
    for c in [c for c in shown_cols if c.kind == kinds.MONEY][:MAX_SUMS]:
        out.append({"key": f"sum-{c.id}", "title": c.name, "kind": "figure", "size": "small", "column": c.id,
                    "currency": c.currency, "why": f"the sum of {c.name}",
                    "shown": {"as": "figure", "series": [{"column": c.name, "agg": "sum"}], "label": c.name}})
    for c in [c for c in shown_cols if c.kind in (kinds.CHOICE, kinds.YESNO)][:MAX_BARS]:
        out.append({"key": f"by-{c.id}", "title": f"{noun.capitalize()} by {c.name}", "kind": "bar", "size": "wide",
                    "column": c.id, "why": f"how many {noun} hold each value of {c.name}",
                    "shown": {"as": "bar", "x": c.name, "series": [{"column": "", "agg": "count"}]}})
    if dates:
        c = dates[0]
        out.append({"key": f"over-{c.id}", "title": f"{noun.capitalize()} by month of {c.name}", "kind": "line",
                    "size": "wide", "column": c.id, "why": f"how many {noun} fall in each month, by {c.name}",
                    "shown": {"as": "line", "x": c.name, "bucket": "month", "series": [{"column": "", "agg": "count"}]}})
    table_cols = [c.name for c in shown_cols][:TABLE_COLUMNS]
    newest = {"sort": dates[0].name, "descending": True} if dates and dates[0].name in table_cols else {}
    out.append({"key": "table", "title": sheet.name if not (view and view.filter) else f"{sheet.name} · {view.name}",
                "kind": "table", "size": "full", "why": f"the {noun} themselves" + (", newest first" if newest else ""),
                "shown": {"as": "table", "columns": table_cols, **newest}})
    return out


def _preview(shaped: Any, piece: dict) -> dict:
    """What a piece shows, in a few values the person reads before ticking it."""
    if not isinstance(shaped, dict):
        return {}
    if shaped.get("as") == "figure":
        return {"value": shaped.get("value")}
    if shaped.get("as") == "table":
        return {"rows": len(shaped.get("rows") or []), "more": bool(shaped.get("more"))}
    points = [p for p in shaped.get("points") or [] if p.get("v") is not None]
    if piece["kind"] == "bar":
        top = sorted(points, key=lambda p: -(p.get("v") or 0))[:PREVIEW_VALUES]
        return {"values": [{"x": p.get("x"), "v": p.get("v")} for p in top], "of": len(points)}
    xs = [p.get("x") for p in points if p.get("x") is not None]
    return {"points": len(points), "first": min(xs, default=None), "last": max(xs, default=None),
            "most": max((p.get("v") or 0 for p in points), default=None)}


def _rows(sheet: Sheet, view: Optional[View]) -> int:
    """How many rows every card reads — the grid's own count of the view's rows, on the sheet's table."""
    from aughor.sheets import projection
    where, params = projection.where_sql(sheet, view.filter, view.search) if view else ("TRUE", [])
    cur = projection.cursor()
    try:
        return int(cur.execute(f"SELECT COUNT(*) FROM {ident(sheet.table)} WHERE {where}", params).fetchone()[0])
    finally:
        cur.close()


def propose(sheet: Sheet, view: Optional[View] = None) -> dict:
    """The cards offered for a dashboard made from this sheet — or from the view on screen — each run once on the
    sheet as it stands: what it would show, or why it cannot. Nothing is kept."""
    from aughor.dashboards import queries
    from aughor.db.connection import open_connection_for
    sql, where = source_sql(sheet, view)
    db = open_connection_for(model.SHEETS_CONNECTION)
    seconds = queries.time_limit(model.SHEETS_CONNECTION)
    probe = queries.probe(db, sql, seconds=seconds)
    if probe["error"]:
        return {"refused": [probe["error"]], "pieces": []}
    columns = probe["columns"]
    rows = _rows(sheet, view)
    pieces = []
    for piece in _pieces(sheet, view):
        shown = queries.normalized(queries.Shown.model_validate(piece["shown"]), columns)
        problems = queries.check(shown, columns)
        if not problems:
            ran = queries.run(db, sql, shown, columns, seconds=seconds)
            problems = [ran["error"]] if ran["error"] else []
        piece = {**piece, "shown": shown.said()}
        if problems:
            pieces.append({**piece, "refused": problems})
        else:
            pieces.append({**piece, "preview": _preview(ran["shown"], piece)})
    filtered = bool(view and (view.filter or view.search))
    return {"sheet": sheet.id, "title": f"{sheet.name} · {view.name}" if filtered else sheet.name,
            "connection_id": model.SHEETS_CONNECTION, "sql": sql, "where": where, "rows": rows,
            "view": view.name if filtered else "", "pieces": pieces}
