"""Columns a model writes (Arc SH, SH-5; flag ``sheets.model_columns``).

A model fills one column of a sheet, row by row, from the columns of each row a person names — the semantic operators'
way (`semops/operators.py`): 25 rows a call, at most 200 rows a fill, on the cheap ``fast`` model — and only the rows
of a view the person picks that are not filled yet, never the whole sheet at once. Before it runs a fill says how many
rows it takes, how many calls, and what they cost, or that the model's price is not set. What it writes is ONE change,
undone whole, kept in the edit layer under the person who ran it with ``origin`` ``model:<fill id>``: the model
proposes each value, and the person who asked for the fill keeps it.

**No model authors a fact** (the arc's §4). The column is marked *written by a model* wherever it is shown, and no
figure is counted from it: the grid's foot counts only how many rows are filled, and no group, rule, dashboard card,
link or total across sheets is made by it (`refuse_counting`). A row the model has not filled says so. New rows wait
for the next fill — a standing yes to fill them as they come is not built.
"""
from __future__ import annotations

import math
import uuid
from typing import Any, Optional

from pydantic import BaseModel

from aughor.sheets import imports, kinds, model, projection
from aughor.sheets.model import Column, Condition, ModelWrites, Sheet
from aughor.sheets.service import Refused

#: Rows a model is handed in one call, and the most one fill takes — the semantic operators' caps.
BATCH = 25
CAP = 200
#: The model tier a fill runs on: these are short per-row judgments.
ROLE = "fast"
#: A cell handed to the model is cut here; a value it writes is cut here.
CELL_CHARS = 1200
VALUE_CHARS = 300


def is_written_by_a_model(c: Optional[Column]) -> bool:
    return c is not None and c.model_writes is not None


def counting_refusal(c: Optional[Column], what: str) -> str:
    """Why a figure is not counted by a column a model writes — ``what`` is the thing that would count (a grouping, a
    rule, a link…) — or "" for any other column. One sentence, said the same wherever it is refused."""
    if not is_written_by_a_model(c):
        return ""
    return (f"{c.name} is written by a model, and nothing is counted from what a model wrote, so {what} by it is not "
            "made")


def refuse_counting(c: Optional[Column], what: str) -> None:
    """`counting_refusal` as a refusal of a change to a sheet."""
    why = counting_refusal(c, what)
    if why:
        raise Refused(why)


def add(sheet: Sheet, *, name: str, instruction: str, reads: list[str], by: str) -> Sheet:
    """Add a column a model writes: what to write for each row, and which of the row's columns it reads."""
    from aughor.sheets import service
    words = " ".join(str(instruction or "").split())
    if not words:
        raise Refused("say what the model writes in the column for each row")
    if len(words) > 500:
        raise Refused("the instruction is longer than 500 characters; say it more briefly")
    read: list[str] = []
    for ref in reads or []:
        c = sheet.column(str(ref))
        if c is None:
            raise Refused(f"{sheet.name} has no column {ref!r} to read")
        if is_written_by_a_model(c):
            raise Refused(f"{c.name} is written by a model; a model column reads what people and files wrote")
        if c.id not in read:
            read.append(c.id)
    if not read:
        raise Refused("choose at least one column the model reads for each row")
    col = Column(id=sheet.new_column_id(), name=service.unique_name(name, sheet), kind=kinds.TEXT,
                 description=f"written by a model: {words}"[:500], model_writes=ModelWrites(instruction=words, reads=read))
    sheet.columns.append(col)
    model.save(sheet, what=f"column {col.name} added, written by a model", by=by, change_id=service.change_id())
    projection.rebuild(sheet)
    return sheet


def _column(sheet: Sheet, ref: str) -> Column:
    c = sheet.column(ref)
    if c is None or not is_written_by_a_model(c):
        raise Refused(f"{sheet.name} has no column {ref!r} that a model writes")
    return c


def _rows(sheet: Sheet, c: Column, conditions: list[Condition], sort: list[dict], search: str) -> tuple[list[int], int, int]:
    """The view's rows the column has no value in, in the view's order, the first ``CAP`` of them — with how many the
    view holds and how many of them are not filled."""
    where, params = projection.where_sql(sheet, conditions, search)
    table, col = imports.ident(sheet.table), imports.ident(c.name)
    cur = projection.cursor()
    try:
        of = int(cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
        empty = f"({where}) AND {col} IS NULL"
        unfilled = int(cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {empty}", params).fetchone()[0])
        order = projection.order_sql(sheet, sort)
        rows = [int(r[0]) for r in cur.execute(
            f"SELECT _row FROM {table} WHERE {empty} ORDER BY {order} LIMIT {CAP}", params).fetchall()]
    finally:
        cur.close()
    return rows, of, unfilled


def _cells(sheet: Sheet, c: Column, rows: list[int]) -> dict[int, list[tuple[str, Any]]]:
    """Each row's cells the column reads, by name."""
    reads = [x for x in (sheet.column(r) for r in c.model_writes.reads) if x is not None]
    out: dict[int, list[tuple[str, Any]]] = {}
    for r in rows:
        values = projection.read_row(sheet, r) or {}
        out[r] = [(x.name, values.get(x.id)) for x in reads]
    return out


def _provider():
    """The model a fill runs on, or ``None`` when none is set up here — said by the plan, refused by a fill."""
    from aughor.llm.provider import get_provider
    try:
        return get_provider(ROLE)
    except Exception as exc:  # noqa: BLE001 — no model set up is an answer the plan says, never a 500
        from aughor.kernel.errors import tolerate
        tolerate(exc, "no model to fill a column with; the fill's plan says so", counter="sheets.model_columns.no_model")
        return None


def _model_of(provider) -> tuple[str, str]:
    return str(getattr(provider, "backend", "") or ""), str(getattr(provider, "_model", "") or "")


def _cost(provider, cells: dict[int, list[tuple[str, Any]]], instruction: str, calls: int) -> tuple[Optional[float], str]:
    """What the fill's calls cost, estimated from what they would send — about four characters a token in, thirty
    tokens a row out — at the model's declared or published price; or ``None`` and why it cannot be said."""
    from aughor.obs.usage import price_for
    backend, name = _model_of(provider)
    price = price_for(backend, name) if name else None
    if price is None:
        return None, (f"the price of {name} is not set here, so the fill's cost is not said" if name
                      else "no model is set up here, so nothing can be filled")
    chars = sum(len(f"{k}: {v}") for row in cells.values() for k, v in row) + calls * (len(instruction) + 900)
    usd = (chars / 4) / 1e6 * price.input_per_1m + (30 * len(cells)) / 1e6 * price.output_per_1m
    return usd, f"about ${usd:,.4f} on {name}"


def plan(sheet: Sheet, column: str, *, conditions: list[Condition], sort: list[dict], search: str = "",
         provider=None) -> dict:
    """What a fill of the view would do, before it runs: the rows it takes, the calls, and what they cost."""
    c = _column(sheet, column)
    rows, of, unfilled = _rows(sheet, c, conditions, sort, search)
    calls = math.ceil(len(rows) / BATCH)
    cells = _cells(sheet, c, rows)
    if provider is None:
        provider = _provider()
    usd, cost = _cost(provider, cells, c.model_writes.instruction, calls)
    return {"column": c.id, "name": c.name, "instruction": c.model_writes.instruction, "rows": len(rows),
            "unfilled": unfilled, "of": of, "calls": calls, "batch": BATCH, "cap": CAP, "model": _model_of(provider)[1],
            "cost_usd": usd, "cost": cost, "said": _said(c, len(rows), unfilled, of, calls, cost)}


def _said(c: Column, rows: int, unfilled: int, of: int, calls: int, cost: str) -> str:
    if not rows:
        return f"Every one of the view's {of:,} rows already has {c.name}; there is nothing to fill."
    more = f" — the first {rows:,} of the {unfilled:,} not filled; fill again for the rest" if unfilled > rows else ""
    return (f"Fills {c.name} for {rows:,} rows{more} ({of:,} in the view): {calls} model call"
            f"{'s' if calls != 1 else ''}, {BATCH} rows a call; {cost}.")


class _Filled(BaseModel):
    row: int
    value: str = ""


class _FillBatch(BaseModel):
    rows: list[_Filled]


_SYSTEM = (
    "You fill ONE column of a spreadsheet, row by row. For each row you are given its number and some of its cells, "
    "and the instruction for the column. Write that row's value as the instruction says: short — a word, a phrase, at "
    "most a sentence. Use only what the row's cells state; never invent. Write \"\" when the cells do not say."
)


def fill(sheet: Sheet, column: str, *, conditions: list[Condition], sort: list[dict], search: str = "", by: str,
         provider=None) -> dict:
    """Fill the column for the view's rows not filled yet, at most ``CAP``, ``BATCH`` rows a call, as ONE change kept
    under ``by`` with ``origin`` ``model:<fill id>``. A call that fails leaves its rows unfilled, and says so; a row the
    model gives nothing for stays unfilled. This calls a model."""
    from aughor.sheets import service
    c = _column(sheet, column)
    rows, of, unfilled = _rows(sheet, c, conditions, sort, search)
    if not rows:
        return {"change_id": "", "filled": 0, "calls": 0, "asked": 0, "left_empty": 0, "failed": 0,
                "unfilled": unfilled, "of": of, "notes": [], "model": ""}
    if provider is None:
        provider = _provider()
    model_name = _model_of(provider)[1]
    if not model_name:
        raise Refused("no model is set up here, so nothing can be filled — choose one in Settings ▸ Models")
    cells = _cells(sheet, c, rows)
    written: dict[int, str] = {}
    notes: list[str] = []
    calls = failed = 0
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        listing = "\n".join(f"[{r}] " + "; ".join(f"{k}: {str(v)[:CELL_CHARS] if v is not None else ''}"
                                                   for k, v in cells[r]) for r in chunk)
        try:
            resp = provider.complete(system=_SYSTEM, response_model=_FillBatch, user=(
                f"The column: {c.name}\nThe instruction: {c.model_writes.instruction}\n\n"
                f"Rows (row number, then its cells):\n{listing}\n\nReturn a value for every row number above."))
            calls += 1
        except Exception as exc:  # noqa: BLE001 — a failed call leaves its rows unfilled, said; never a lost fill
            calls += 1
            failed += len(chunk)
            notes.append(f"rows {chunk[0]}–{chunk[-1]} were not filled: the call failed ({str(exc)[:120]})")
            continue
        asked = set(chunk)
        for got in resp.rows:
            value = " ".join(str(got.value or "").split())[:VALUE_CHARS]
            if got.row in asked and value:
                written[got.row] = value
    left_empty = len(rows) - len(written) - failed       # rows the model gave nothing for
    fill_id = uuid.uuid4().hex[:12]
    change = ""
    if written:
        from aughor.actions import overlay
        versions = overlay.sheet_versions(sheet.id, written)
        out = service.set_cells(sheet, [{"row": r, "column": c.id, "value": v, "version": versions.get((r, c.id), 0)}
                                        for r, v in sorted(written.items())],
                                by=by, origin=f"model:{fill_id}", note=f"written by a model ({model_name or 'unnamed'})")
        change = out["change_id"]
    return {"change_id": change, "filled": len(written), "calls": calls, "asked": len(rows),
            "left_empty": left_empty, "failed": failed, "unfilled": unfilled - len(written), "of": of, "notes": notes,
            "model": model_name}
