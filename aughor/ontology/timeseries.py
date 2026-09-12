"""ON-5 — timeseries properties: an object's latest value, and the history behind it (ROADMAP §3.15, amended
2026-09-11).

ON-1b let a person bind a second source to an object type and say what kind it is: `static`, one row per object, or
`timeseries`, many rows per object over a time column. Only the static kind was read. This module is what makes the
timeseries kind mean something — the "processes" half of the arc's definition, the part of a business that is not a
noun but a thing that keeps happening: a price that changes, a shipment that moves, a ticket that is reopened.

**The reduction.** A timeseries binding is read as ONE row per object — the object's LATEST row by the binding's
time column — so it joins exactly like a static binding and can neither multiply nor invent objects. Each property
on that row is built from a DECLARATION (`aughor.ontology.window_measures`), not from hand-written window SQL:
`semiadditive: last`, partitioned by the object's key and ordered by the time column, which is O5's claim that a
reading must be collapsed by taking one row per period rather than summed across time. Instantiating the
declaration is the point — a latest value written by hand is indistinguishable from a wrong one.

Three things are decided here rather than left to the query that reads it:

* **A reading with no time has no place in time.** Rows whose time column is NULL are excluded from the reduction,
  so "the latest" cannot be a row that never said when.
* **The latest row is ONE row.** The window's ordering carries the time column and then every column the binding
  supplies, so rows tied on time are still totally ordered and every property comes from the same row. Ordering on
  time alone would let two properties of "the latest reading" come from two different rows, which is the kind of
  wrong number nothing downstream could catch.
* **History is the same source, unreduced** (`history_sql`): the readings behind the latest one, newest first, for
  ONE object — what an object page shows under the value so a person can see the value move.
"""
from __future__ import annotations

from typing import Optional

from aughor.ontology.bindings import binding_from, column_of
from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import Binding
from aughor.ontology.window_measures import compile_measure, from_declaration

#: How many readings behind the latest one an object page shows.
HISTORY_ROWS = 12
#: The alias the reduction reads its rows under — the binding's source, or the framed readings when the binding
#: declares a frame, so every expression built for the reduction is written the same way either way.
SOURCE = "tsrc"
#: The alias the RAW readings are read under, beneath a frame. Only a framed binding has this second layer.
READINGS = "tread"


def latest_columns(binding: Binding) -> list[str]:
    """The source columns the reduction carries, in declaration order and without repeats: the column behind every
    property the binding supplies, plus its time column — so "when this was measured" is on the row even when no
    property is supplied from it. The key is not among them; it is what the reduction joins on.

    A FRAME property is not among them either: its column does not exist in the source, it is computed by the
    frame layer under the name of the property itself."""
    out: list[str] = []
    supplied = [name for name in binding.properties if name not in binding.frames]
    for column in [column_of(binding, name) for name in supplied] + [binding.time_column]:
        if not column or column.lower() == (binding.key or "").lower():
            continue
        if column.lower() not in {c.lower() for c in out}:
            out.append(column)
    return out


def reduced_columns(binding: Binding) -> list[str]:
    """Everything ONE reduced row carries: the source columns, then each frame under its property's own name.
    What `latest_from` selects, and what a reader of that row asks for."""
    return [*latest_columns(binding), *binding.frames]


def _ordering(binding: Binding, alias: str) -> str:
    """The reduction's ordering, qualified by the alias the expression is written against."""
    return ", ".join(f"{alias}.{quote_ident(c)}" for c in latest_order(binding))


def latest_order(binding: Binding) -> list[str]:
    """What "latest" is ordered by: the time column, and then every column the reduction carries. The tail is not
    decoration — it is what makes the last row ONE row when two readings share an instant."""
    order: list[str] = []
    for column in [binding.time_column, *latest_columns(binding)]:
        if column and column.lower() not in {c.lower() for c in order}:
            order.append(column)
    return order


def latest_declaration(binding: Binding, column: str) -> dict:
    """The stored declaration ON-5 instantiates for ONE timeseries property: its value on the object's latest row,
    as a semiadditive `last` over the binding's time column, partitioned by the object's key."""
    return {"expression": f"{SOURCE}.{quote_ident(column)}",
            "order_by": _ordering(binding, SOURCE),
            "range": "current", "semiadditive": "last",
            "partition_by": [f"{SOURCE}.{quote_ident(binding.key)}"]}


def frame_declaration(binding: Binding, name: str) -> dict:
    """The declaration ONE frame property instantiates, over the RAW readings — the inner of the two window
    layers.

    Window functions do not nest, which is the whole reason there are two: this one computes the frame on every
    reading (the trailing average as of that row, the running total to that row, the value N readings back), and
    the outer reduction then takes its value on the object's latest row. Doing it in one layer would mean asking
    for the last value of a window of a window, which SQL cannot express — and hand-writing it as a correlated
    subquery per property is exactly the "written by hand is indistinguishable from wrong" this arc refuses."""
    frame = binding.frames[name]
    column = f"{READINGS}.{quote_ident(frame.column)}"
    # LAG takes a VALUE; an aggregate around it would be stripped by the compiler anyway, so it is refused at
    # declaration time rather than silently dropped here.
    expression = column if frame.offset else f"{frame.agg.upper()}({column})"
    return {"expression": expression, "order_by": _ordering(binding, READINGS),
            "range": frame.range, "window": frame.window, "offset": frame.offset,
            "partition_by": [f"{READINGS}.{quote_ident(binding.key)}"]}


def frame_note(binding: Binding, name: str) -> str:
    """What a frame property is, in the declaration's own words — for the property's description and a plan line."""
    from_declaration(frame_declaration(binding, name))          # raises unless the declaration compiles
    frame = binding.frames[name]
    return (f"{frame.describe()}, per {binding.key}, ordered by {', '.join(latest_order(binding))} — "
            f"read at the object's latest reading")


def latest_note(binding: Binding) -> str:
    """What the reduction did, for a plan line, a caveat or a receipt. Read off the declaration the SQL is built
    from — including the ordering, so nobody has to guess how a tie was broken."""
    columns = latest_columns(binding)
    if not columns:
        return f"reduced to each object's latest row by {binding.time_column}"
    from_declaration(latest_declaration(binding, columns[0]))       # raises unless the declaration compiles
    return (f"reduced to each object's latest row by {binding.time_column} — one row per {binding.key}, every "
            f"property its LAST value ordered by {', '.join(latest_order(binding))}, never summed across time")


def latest_from(binding: Binding, alias: str, *, key_equals: Optional[str] = None) -> str:
    """The aliased FROM fragment that reads a timeseries binding as ONE row per object: its key, and every column
    the reduction carries at its latest value. ``key_equals`` is an already-typed literal that narrows the source
    to one object first — the same reduction over one partition, which is how an object page reads its own row.

    Returns "" when the binding names no source, no key or no time column, the way `binding_from` returns "" —
    every caller checks `binding_problem` first, which refuses exactly those."""
    columns = latest_columns(binding)
    if not (binding_from(binding, SOURCE) and binding.key and binding.time_column and columns):
        return ""
    select = [f"{SOURCE}.{quote_ident(binding.key)} AS {quote_ident(binding.key)}"]
    for column in [*columns, *binding.frames]:
        select.append(f"{compile_measure(from_declaration(latest_declaration(binding, column)))} "
                      f"AS {quote_ident(column)}")
    return f"(SELECT DISTINCT {', '.join(select)} FROM {_rows(binding, key_equals)}) AS {alias}"


def _rows(binding: Binding, key_equals: Optional[str]) -> str:
    """What the reduction reduces: the binding's readings, and — when it declares frames — those readings with
    each frame computed on every one of them.

    The narrowing to one object and the "a reading with no time has no place in time" rule both live HERE, on the
    innermost layer, so a frame is computed over exactly the readings the reduction will reduce. Narrowing above
    the frame layer instead would compute a trailing average over every object's readings and then throw all but
    one away — the same shape of error as a window with no PARTITION BY, and just as invisible in the answer."""
    def where(alias: str) -> str:
        clause = f"{alias}.{quote_ident(binding.time_column)} IS NOT NULL"
        if key_equals is not None:
            clause += f" AND {alias}.{quote_ident(binding.key)} = {key_equals}"
        return clause

    if not binding.frames:
        return f"{binding_from(binding, SOURCE)} WHERE {where(SOURCE)}"
    carried = [f"{READINGS}.{quote_ident(c)} AS {quote_ident(c)}"
               for c in [binding.key, *latest_columns(binding)]]
    framed = [f"{compile_measure(from_declaration(frame_declaration(binding, name)))} AS {quote_ident(name)}"
              for name in binding.frames]
    return (f"(SELECT {', '.join([*carried, *framed])} FROM {binding_from(binding, READINGS)} "
            f"WHERE {where(READINGS)}) AS {SOURCE}")


def history_sql(binding: Binding, key_equals: str, limit: int = HISTORY_ROWS) -> str:
    """The readings behind one object's latest value, newest first — the same source, unreduced. ``key_equals`` is
    an already-typed literal for the object's key.

    Ordered by the REVERSE of the reduction's own ordering, not by time alone, so the first row it returns IS the
    row `latest_from` reduces to — which is what lets a page read "and before that" off the second row rather
    than running a second, differently-tied query for it."""
    columns = latest_columns(binding)
    if not (columns and binding.key and binding.time_column):
        return ""
    newest_first = ", ".join(f"{SOURCE}.{quote_ident(c)} DESC" for c in latest_order(binding))
    return (f"SELECT {', '.join(f'{SOURCE}.{quote_ident(c)}' for c in columns)} "
            f"FROM {binding_from(binding, SOURCE)} "
            f"WHERE {SOURCE}.{quote_ident(binding.key)} = {key_equals} "
            f"AND {SOURCE}.{quote_ident(binding.time_column)} IS NOT NULL "
            f"ORDER BY {newest_first} LIMIT {int(limit)}")
