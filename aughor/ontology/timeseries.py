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
from aughor.ontology.window_measures import compile_measure, describe, from_declaration

#: How many readings behind the latest one an object page shows.
HISTORY_ROWS = 12
#: The alias the reduction reads the binding's own source under.
SOURCE = "tsrc"


def latest_columns(binding: Binding) -> list[str]:
    """The source columns the reduction carries, in declaration order and without repeats: the column behind every
    property the binding supplies, plus its time column — so "when this was measured" is on the row even when no
    property is supplied from it. The key is not among them; it is what the reduction joins on."""
    out: list[str] = []
    for column in [column_of(binding, name) for name in binding.properties] + [binding.time_column]:
        if not column or column.lower() == (binding.key or "").lower():
            continue
        if column.lower() not in {c.lower() for c in out}:
            out.append(column)
    return out


def latest_declaration(binding: Binding, column: str) -> dict:
    """The stored declaration ON-5 instantiates for ONE timeseries property: its value on the object's latest row,
    as a semiadditive `last` over the binding's time column, partitioned by the object's key. The ordering carries
    every supplied column after the time column so the row it lands on is one row (see the module docstring)."""
    order = [binding.time_column, *latest_columns(binding)]
    seen: list[str] = []
    for c in order:
        if c and c.lower() not in {s.lower() for s in seen}:
            seen.append(c)
    return {"expression": f"{SOURCE}.{quote_ident(column)}",
            "order_by": ", ".join(f"{SOURCE}.{quote_ident(c)}" for c in seen),
            "range": "current", "semiadditive": "last",
            "partition_by": [f"{SOURCE}.{quote_ident(binding.key)}"]}


def latest_note(binding: Binding) -> str:
    """What the reduction did, for a plan line, a caveat or a receipt — the declaration's own words."""
    columns = latest_columns(binding)
    if not columns:
        return f"reduced to each object's latest row by {binding.time_column}"
    said = describe(from_declaration(latest_declaration(binding, columns[0])))
    return (f"reduced to each object's latest row by {binding.time_column}, one row per {binding.key} — "
            f"every property read as {said}")


def latest_from(binding: Binding, alias: str, *, key_equals: Optional[str] = None) -> str:
    """The aliased FROM fragment that reads a timeseries binding as ONE row per object: its key, and every column
    the reduction carries at its latest value. ``key_equals`` is an already-typed literal that narrows the source
    to one object first — the same reduction over one partition, which is how an object page reads its own row.

    Returns "" when the binding names no source, no key or no time column, the way `binding_from` returns "" —
    every caller checks `binding_problem` first, which refuses exactly those."""
    source = binding_from(binding, SOURCE)
    columns = latest_columns(binding)
    if not (source and binding.key and binding.time_column and columns):
        return ""
    select = [f"{SOURCE}.{quote_ident(binding.key)} AS {quote_ident(binding.key)}"]
    for column in columns:
        select.append(f"{compile_measure(from_declaration(latest_declaration(binding, column)))} "
                      f"AS {quote_ident(column)}")
    where = f"{SOURCE}.{quote_ident(binding.time_column)} IS NOT NULL"
    if key_equals is not None:
        where += f" AND {SOURCE}.{quote_ident(binding.key)} = {key_equals}"
    return f"(SELECT DISTINCT {', '.join(select)} FROM {source} WHERE {where}) AS {alias}"


def history_sql(binding: Binding, key_equals: str, limit: int = HISTORY_ROWS) -> str:
    """The readings behind one object's latest value, newest first — the same source, unreduced. ``key_equals`` is
    an already-typed literal for the object's key."""
    columns = latest_columns(binding)
    if not (columns and binding.key and binding.time_column):
        return ""
    return (f"SELECT {', '.join(f'{SOURCE}.{quote_ident(c)}' for c in columns)} "
            f"FROM {binding_from(binding, SOURCE)} "
            f"WHERE {SOURCE}.{quote_ident(binding.key)} = {key_equals} "
            f"AND {SOURCE}.{quote_ident(binding.time_column)} IS NOT NULL "
            f"ORDER BY {SOURCE}.{quote_ident(binding.time_column)} DESC LIMIT {int(limit)}")
