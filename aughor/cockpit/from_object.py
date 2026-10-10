"""Starting a cockpit from an object (2026-10-10; the screen the user approved, design-mockups/cockpit-from-object.html).

A person picks an object — on the Ontology tab, or under New cockpit — and is offered a cockpit made of what that
object holds: its categories as filters, its numbers as figures, its date as a chart of objects per day, and its
objects as a table with a detail and the actions declared on it. Every offer is read from the served ontology and
measured through the object door before it is made. A category with one value, or too many to filter by, is not
offered; nor is a property the reader may not read, or a number the compiler refuses. Nothing a guess would put there
is offered.

No model is asked and nothing is kept here: the person ticks what they want, and the web keeps it as their own first
version (`web/lib/cockpit/start.ts`). The three pieces it adds — a filter column, a figure and a chart — read through
`POST /objects/query` like every other object read, so a row policy and a masked property hold on them as they do
everywhere else.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any, Callable, Iterator, Optional

FLAG = "ontology.object_cockpits"
#: The most filters offered: the object's own categories first, then one read through a link.
MAX_FILTERS = 4
#: A category is a filter when it holds at least two values and at most this many.
MAX_FILTER_VALUES = 30
#: The values a filter's preview shows.
PREVIEW_VALUES = 6
MAX_TABLE_COLUMNS = 6
CHART_DAYS = 30
#: The to-one links whose categories are measured — a bound on the one query that measures them all.
MAX_LINKS_READ = 3

_CATEGORY = frozenset({"dimension", "flag", "ordinal"})
_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "INR", "CNY", "CHF", "AUD", "CAD", "SEK", "NOK", "DKK"})

#: One object query in, its result out: columns, rows and the caveats the door said. A refusal is raised as the
#: compiler's own `ObjectQueryRefused`; a query that failed in the warehouse as `RuntimeError`, with why.
Run = Callable[[dict], tuple[list[str], list[list[Any]], list[str]]]


def plural(word: str) -> str:
    """"Order" → "Orders", "Category" → "Categories": the count's label."""
    w = (word or "").strip()
    if not w:
        return w
    if w.endswith("y") and not w.lower().endswith(("ay", "ey", "oy", "uy")):
        return w[:-1] + "ies"
    return w + ("es" if w.endswith(("s", "x", "z", "ch", "sh")) else "s")


def _label(p: Any) -> str:
    return p.display_name or p.name.replace("_", " ").capitalize()


def _is_temporal(p: Any) -> bool:
    from aughor.semantic.object_query import is_temporal
    return is_temporal(p)


def _is_category(p: Any) -> bool:
    if p.is_primary_key or p.is_foreign_key or _is_temporal(p):
        return False
    return (p.semantic_type or "") in _CATEGORY or "BOOL" in (p.data_type or "").upper()


def _is_money(p: Any) -> bool:
    return "currency" in (p.value_interpretation or "").lower() or (p.unit or "").upper() in _CURRENCIES


def _readable(entity: Any, name: str) -> bool:
    from aughor.ontology.security import masked
    return masked(entity, name) is None


def _number(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def window_end(last: Optional[date], today: date) -> date:
    """Where a chart's window ends (exclusive): today, so the last day drawn is the last whole one — or the day after
    the last one the objects hold, when they stop before today, so an old dataset is not drawn as empty days."""
    return min(today, last + timedelta(days=1)) if last is not None else today


def _measured(run: Run, object_type: str, measures: list[dict]) -> tuple[dict[str, Any], list[str]]:
    """Each measure's value over every object, by name — in one query, or one by one when the compiler refuses the
    batch, so one refused measure does not take the others with it. A refused one is left out."""
    from aughor.semantic.object_query import ObjectQueryRefused
    try:
        cols, rows, said = run({"object_type": object_type, "measures": measures})
        row = rows[0] if rows else []
        return dict(zip(cols, row)), said
    except ObjectQueryRefused:
        if len(measures) == 1:
            return {}, []
    out: dict[str, Any] = {}
    said: list[str] = []
    for m in measures:
        got, s = _measured(run, object_type, [m])
        out.update(got)
        said += s
    return out, said


def _entity_of(graph: Any, name: str) -> str:
    """The id of the object type ``name`` resolves to, or "" when it names none here — an action on no object here
    is not offered, whatever it names."""
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        return find_object_type(graph, name).id
    except ObjectQueryRefused:
        return ""


def propose(graph: Any, entity_name: str, run: Run, *, today: Optional[date] = None) -> dict:
    """What a cockpit started from ``entity_name`` is offered, each piece with a preview read through ``run``."""
    from aughor.ontology.security import rows_said
    from aughor.semantic.object_query import find_object_type, find_property, link_problem, object_links

    entity = find_object_type(graph, entity_name)
    name = entity.display_name or entity.api_name
    caveats: list[str] = []

    def say(lines: list[str]) -> None:
        for line in lines:
            if line and line not in caveats:
                caveats.append(line)

    # ── the categories: the object's own, then those read through a to-one link ──
    own = [(n, p) for n, p in (entity.properties or {}).items() if _is_category(p) and _readable(entity, n)]
    taken = {n.lower() for n, _ in own}
    linked: list[tuple[str, Any, Any]] = []
    for h in [h for h in object_links(graph, entity) if h.to_one and not link_problem(h)][:MAX_LINKS_READ]:
        if h.target.backing is not None and h.target.backing.kind == "platform":
            continue
        for n, p in (h.target.properties or {}).items():
            if _is_category(p) and n.lower() not in taken and _readable(h.target, n):
                linked.append((f"{h.name}.{n}", p, h.target))
    paths = [n for n, _ in own] + [path for path, _, _ in linked]
    time = entity.created_at_col or ""
    tp = find_property(entity, time) if time else None
    dated = tp is not None and _is_temporal(tp) and _readable(entity, time)
    counted, said = _measured(run, entity.api_name, [{"name": "n", "agg": "count"}] + [
        {"name": f"d{i}", "agg": "count_distinct", "path": path} for i, path in enumerate(paths)]
        + ([{"name": "t", "agg": "max", "path": time}] if dated else []))
    say(said)
    if "n" not in counted:
        # the count of the objects is what every other offer is measured against; the compiler said why it cannot be
        run({"object_type": entity.api_name, "measures": [{"name": "n", "agg": "count"}]})
    total = _number(counted.get("n"))

    def fits(i: int) -> bool:
        # a filter groups: at least two values, few enough to read down a column, and each held by two objects or
        # more on average — one that picks out single objects is a lookup, not a filter
        d = _number(counted.get(f"d{i}"))
        return d is not None and 2 <= d <= MAX_FILTER_VALUES and (total is None or d <= total / 2)

    chosen_own = [(n, p) for i, (n, p) in enumerate(own) if fits(i)]
    chosen_linked = next(((path, p, target) for j, (path, p, target) in enumerate(linked) if fits(len(own) + j)), None)
    picked: list[dict] = [{"path": n, "label": _label(p), "via": ""} for n, p in chosen_own]
    if chosen_linked:
        path, p, target = chosen_linked
        picked.insert(1, {"path": path, "label": f"{target.display_name or target.api_name} {_label(p).lower()}",
                          "via": target.display_name or target.api_name})
    filters = []
    for f in picked[:MAX_FILTERS]:
        _, rows, said = run({"object_type": entity.api_name, "measures": [{"name": "n", "agg": "count"}],
                             "by": [f["path"]], "order_by": "n", "descending": True, "limit": PREVIEW_VALUES})
        say(said)
        filters.append({**f, "values": [[r[0], _number(r[1])] for r in rows]})

    # ── the figures: how many, a money figure, and the average of a count each object holds ──
    figures = [{"label": plural(name), "agg": "count", "path": "", "format": "number"}]
    numbers = [(n, p) for n, p in (entity.properties or {}).items() if _readable(entity, n)]
    for binding in entity.bindings or []:
        numbers += [(n, p) for n, p in binding.properties.items() if _readable(entity, n)]
    money = next(((n, p) for n, p in numbers if (p.semantic_type or "") == "measure" and _is_money(p)), None)
    if money:
        # money adds up over things that happen (an object with a date) and is not profiled per unit; a price per
        # unit, or the price of a thing that simply exists, is averaged — its sum means nothing
        adds = dated and (money[1].measure_grain or "") != "per_unit"
        figures.append({"label": _label(money[1]) if adds else f"Average {_label(money[1]).lower()}",
                        "agg": "sum" if adds else "avg", "path": money[0], "format": "money"})
    ordinal = next(((n, p) for n, p in numbers if (p.semantic_type or "") == "ordinal" and not p.is_primary_key), None)
    if ordinal:
        figures.append({"label": f"Average {_label(ordinal[1]).lower()}", "agg": "avg", "path": ordinal[0],
                        "format": "number"})
    values, said = _measured(run, entity.api_name, [
        {"name": f"f{i}", "agg": f["agg"], "path": f["path"]} for i, f in enumerate(figures)])
    say(said)
    figures = [{**f, "value": _number(values[f"f{i}"])} for i, f in enumerate(figures) if f"f{i}" in values]

    # ── the chart: the objects per day over the last whole days the objects hold ──
    chart = None
    if dated:
        end = window_end(_day(counted.get("t")), today or date.today())
        start = end - timedelta(days=CHART_DAYS)
        _, rows, said = run({"object_type": entity.api_name, "measures": [{"name": "n", "agg": "count"}],
                             "time": time, "grain": "day", "start": start.isoformat(), "end": end.isoformat()})
        say(said)
        by_day = {str(r[0])[:10]: _number(r[1]) or 0 for r in rows}
        chart = {"time": time, "label": f"{plural(name)} per day", "days": CHART_DAYS, "end": end.isoformat(),
                 "bars": [by_day.get((start + timedelta(days=i)).isoformat(), 0) for i in range(CHART_DAYS)]}

    # ── the table: what the filters and figures read, the date first after the first category ──
    columns: list[str] = []
    for path in ([f["path"] for f in filters if not f["via"]][:1] + ([time] if chart else [])
                 + [f["path"] for f in figures if f["path"]] + [f["path"] for f in filters if f["via"]]
                 + [f["path"] for f in filters if not f["via"]][1:]):
        if path and path not in columns:
            columns.append(path)
    columns = columns[:MAX_TABLE_COLUMNS]
    # a column is named as its property is — never as a figure that aggregates it ("Average …" is not a column)
    labels = {f["path"]: f["label"] for f in filters}
    for path in columns:
        p = find_property(entity, path) if path not in labels else None
        if p is not None:
            labels[path] = _label(p)

    # ── the actions declared on it ──
    actions = [{"id": a.id, "label": a.display_name or a.id.replace("_", " ")} for a in graph.declared_actions()
               if _entity_of(graph, a.entity or a.object_type) == entity.id]

    say([rows_said(entity) or ""])
    return {"entity": entity.api_name, "type_id": entity.id, "name": name, "title": plural(name),
            "total": total, "filters": filters, "figures": figures, "chart": chart,
            "table": {"columns": columns, "labels": [labels.get(c, c.replace("_", " ")) for c in columns]},
            "actions": actions, "caveats": caveats}


@contextmanager
def reader(connection_id: str, schema_name: Optional[str], graph: Any) -> Iterator[Run]:
    """A `Run` over the connection, scoped to the schema the served graph was built for: the object door's compiler,
    the accepted edits read as properties, and the guard battery — the read `POST /objects/query` makes."""
    from aughor.actions.overlay import accepted_object_edits
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.routers.ontology import resolve_effective_schema
    from aughor.semantic.object_query import compile_object_query, keyed_metrics_for
    from aughor.sql.executor import execute_guarded

    db = open_connection_for_with_schema(connection_id,
                                         graph.schema_name or resolve_effective_schema(connection_id, schema_name))
    overlay = accepted_object_edits(connection_id)
    metrics = keyed_metrics_for(connection_id, graph.schema_name)

    def run(query: dict) -> tuple[list[str], list[list[Any]], list[str]]:
        compiled = compile_object_query(query, graph, dialect=getattr(db, "dialect", "") or "duckdb",
                                        overlay=overlay, metrics=metrics)
        result = execute_guarded(db, compiled.sql, query_id="cockpit.from_object")
        if result.error:
            raise RuntimeError(result.error)
        return (list(result.columns or []) or list(compiled.columns), list(result.rows or []),
                list(compiled.caveats) + list(result.caveats or []))
    try:
        yield run
    finally:
        db.close()
