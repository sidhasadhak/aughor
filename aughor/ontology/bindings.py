"""ON-1b — bindings: each property knows its source (ROADMAP §3.15, amended 2026-09-11).

An object type's first binding is its backing (ON-1): the table or keyed SELECT whose rows ARE its objects. A
further binding is another table or keyed SELECT joined to the object on its key, supplying properties the backing
does not carry — an order's payment method from `payments`, a customer's tier from `customer_profiles` — so an
object that spans tables no longer needs a hand-written SELECT to be complete. Its kind is `static` (one row per
object), `timeseries` (many rows per object over a time column) or — ON-7 — `detail` (many rows per object with no
clock: an order's lines), which supplies exactly the rollups it declares, each computed per object before the join
(`aughor.ontology.parts`).

Whether one holds is MEASURED here, the ON-0a way, never assumed:

* a **static** binding is verified when its key is unique over its keyed rows AND reaches objects that exist — only
  then can a LEFT JOIN on it neither multiply nor invent objects, so only then does anything read it;
* a **timeseries** binding is verified when its key reaches objects that exist; it is read as each object's
  LATEST row by its time column (ON-5, `aughor.ontology.timeseries`), which is one row per object again, so it
  joins under the same law as a static one.

Either way the counts are kept: the binding's rows, its keyed rows and distinct keys, the objects it was counted
against, how many of those it covers, and the keys that reach no object.

A person sets a binding through the overrides tree (`PUT /ontology/entities/{id}/bindings/{name}`): its source is
read for its columns before anything is written (`bind_binding`), and the overlay rebuilds it at read time from what
that check recorded, without a database in hand (`declared_bindings`). The builder PROPOSES a binding wherever another
type's table carries this type's key and the data proves it one row per object (`propose_bindings`); a proposal lives
on `proposed_bindings`, which no query, page or answer reads.

Every column a binding supplies carries the data type the warehouse reports for it in that very source
(`describe_with`), and the role, unit and description of the column it reads: the table's own column for a table
binding, and for a keyed SELECT the source column a pass-through projection names (`select_lineage`). A computed or
cast column keeps the type it was reported with and borrows no meaning it does not have.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from aughor.ontology.backing import object_from
from aughor.ontology.cardinality import quote_ident, quote_table
from aughor.ontology.display import key_of
from aughor.ontology.models import Backing, Binding, EntityProperty, Frame, OntologyEntity, OntologyGraph, Rollup
from aughor.ontology.window_measures import RANGES

logger = logging.getLogger(__name__)

#: A binding's name — what a person, the panel and the plan call it: snake_case, bounded.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
#: A column or property name as a binding spells it.
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: A table identifier, optionally qualified. It is interpolated into a probe, so anything else is refused rather than
#: escaped — the overrides store's rule for a table a person names.
_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")
_SELECT = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
#: The same three shapes, public — a declaration (ON-7, `aughor.ontology.declared`) is held to the identical rule.
COLUMN_PATTERN, TABLE_PATTERN, SELECT_PATTERN = _COLUMN, _TABLE, _SELECT
#: Tables the builder asks the data about for one type — a wide schema must not turn a measurement into a crawl.
MAX_CANDIDATES = 8
#: What a count of one binding records, on the model and on a bind entry.
_MEASURED = ("rows", "non_null", "distinct", "objects", "covered", "orphans", "verified", "note")

#: `describe(from_fragment)` → ``({column: data type}, error)``: the columns a binding's source reports.
Describe = Callable[[str], "tuple[dict[str, str], Optional[str]]"]


def bare(table: Optional[str]) -> str:
    return (table or "").strip().strip('"').rsplit(".", 1)[-1]


def _title(name: str) -> str:
    return " ".join(w.capitalize() for w in str(name).replace("-", "_").split("_") if w)


def binding_from(binding: Binding, alias: str) -> str:
    """The aliased FROM fragment a binding is read through — its keyed SELECT as a subquery, else its table — or ""
    when it names neither."""
    sql = (binding.sql or "").strip().rstrip(";").strip()
    if sql:
        return f"({sql}) AS {alias}"
    return f"{quote_table(binding.table)} AS {alias}" if binding.table else ""


def primary_name(entity: OntologyEntity) -> str:
    """The first binding's name, as the panel lists it: the backing table's bare name, or ``query``."""
    b = entity.backing
    if b is not None and b.kind == "query" and b.sql:
        return "query"
    return bare((b.table if b is not None else None) or (entity.source_tables[0] if entity.source_tables else ""))


def column_of(binding: Binding, name: str) -> str:
    """The binding's column that property ``name`` is read from."""
    return binding.columns.get(name) or name


def property_binding(entity: OntologyEntity, name: str) -> Optional[Binding]:
    """The further binding that supplies property ``name`` — None when the backing supplies it, or nothing does."""
    low = (name or "").strip().lower()
    if not low or any(k.lower() == low for k in entity.properties or {}):
        return None
    return next((b for b in entity.bindings or [] if any(k.lower() == low for k in b.properties)), None)


def binding_problem(entity: OntologyEntity, binding: Binding) -> str:
    """Why a binding's properties may not be read, or "" when they may — one law for the compiler and the object
    page, as `link_problem` is one law for links."""
    if binding.kind == "detail" and not binding.rollups:
        return (f"{binding.name} on {entity.id} is a detail binding with no rollup — its rows are many per "
                f"{entity.id} with no clock, so nothing of it is read at the object's grain until a rollup is declared")
    if binding.kind == "timeseries" and not binding.time_column:
        return (f"{binding.name} on {entity.id} is a timeseries binding with no time column — its properties are "
                "read as the object's LATEST value (ON-5), and without a time column there is no latest")
    if binding.verified is None:
        return (f"binding {binding.name} on {entity.id} is unmeasured ({binding.note or 'never counted'}) — whether "
                f"{binding.key} holds one row per {entity.id} has not been counted, and an uncounted binding is never "
                "joined (POST /ontology/measure counts it without a model call)")
    if binding.verified is False:
        return (f"binding {binding.name} on {entity.id} is refuted by measurement ({binding.note}) — only a binding "
                f"measured one row per {entity.id} is joined")
    if not (key_of(entity) and binding.key and binding_from(binding, "b")):
        return f"binding {binding.name} on {entity.id} has no key or no source to join on"
    return ""


# ── measurement ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BindingMeasurement:
    entity_id: str
    name: str
    kind: str
    rows: Optional[int] = None
    non_null: Optional[int] = None
    distinct: Optional[int] = None
    objects: Optional[int] = None
    covered: Optional[int] = None
    orphans: Optional[int] = None
    verified: Optional[bool] = None
    note: str = ""

    def counts(self) -> dict:
        return {k: getattr(self, k) for k in _MEASURED}

    def stamp(self, binding: Binding) -> None:
        for k, v in self.counts().items():
            setattr(binding, k, v)


def verdict(kind: str, key: str, entity_id: str, rows: Optional[int], non_null: Optional[int],
            distinct: Optional[int], objects: Optional[int], covered: Optional[int],
            orphans: Optional[int]) -> tuple[Optional[bool], str]:
    """Whether counted keys make a binding hold, and the evidence in words. None when anything went uncounted."""
    if rows is None or non_null is None or distinct is None or objects is None or covered is None or orphans is None:
        return None, "not measurable"
    reach = (f"covers {covered:,} of {objects:,} {entity_id} objects"
             + (f"; {orphans:,} of its keys reach no {entity_id}" if orphans else ""))
    if not non_null:
        return False, f"{key}: none of its {rows:,} rows carries a key"
    if kind in ("timeseries", "detail"):
        detail = f"{key}: {non_null:,} keyed rows over {distinct:,} keys; {reach}"
    elif distinct != non_null:
        return False, f"{key}: {distinct:,} distinct over {non_null:,} keyed rows — NOT one row per {entity_id}; {reach}"
    else:
        detail = f"{key}: {distinct:,} distinct over {non_null:,} keyed rows; {reach}"
    if not covered:
        return False, f"{detail} — its key reaches no {entity_id}"
    return True, detail


def measure_binding(db: Any, entity: OntologyEntity, binding: Binding) -> BindingMeasurement:
    """Count one binding against the objects it binds to, in one probe. A probe that fails leaves it unmeasured,
    never refuted."""
    m = BindingMeasurement(entity_id=entity.id, name=binding.name, kind=binding.kind)
    object_key = key_of(entity)
    source, objects = binding_from(binding, "b"), object_from(entity, "o")
    if not (source and objects and object_key and binding.key):
        m.note = "no source, no object rows or no key to count"
        return m
    bk, ok = quote_ident(binding.key), quote_ident(object_key)
    sql = (f"WITH bound_keys AS (SELECT b.{bk} AS k FROM {source}), "
           f"object_keys AS (SELECT DISTINCT o.{ok} AS k FROM {objects} WHERE o.{ok} IS NOT NULL) "
           "SELECT (SELECT COUNT(*) FROM bound_keys), (SELECT COUNT(k) FROM bound_keys), "
           "(SELECT COUNT(DISTINCT k) FROM bound_keys), (SELECT COUNT(*) FROM object_keys), "
           "(SELECT COUNT(*) FROM object_keys WHERE k IN (SELECT k FROM bound_keys WHERE k IS NOT NULL)), "
           "(SELECT COUNT(DISTINCT k) FROM bound_keys WHERE k IS NOT NULL AND k NOT IN (SELECT k FROM object_keys))")
    try:
        result = db.execute("__binding_probe__", sql)
    except Exception as exc:  # noqa: BLE001 — an unprobeable binding is unmeasured, not refuted
        m.note = f"probe raised: {exc}"[:200]
        return m
    if getattr(result, "error", None) or not getattr(result, "rows", None):
        m.note = f"probe failed: {getattr(result, 'error', '') or 'no rows'}"[:200]
        return m
    try:
        m.rows, m.non_null, m.distinct, m.objects, m.covered, m.orphans = (int(v) for v in result.rows[0][:6])
    except (TypeError, ValueError):
        m.note = "probe returned an unreadable row"
        return m
    m.verified, m.note = verdict(binding.kind, binding.key, entity.id, m.rows, m.non_null, m.distinct,
                                 m.objects, m.covered, m.orphans)
    return m


@dataclass
class BindingReport:
    #: The bindings a person set, counted.
    measurements: list[BindingMeasurement] = field(default_factory=list)
    #: Every candidate the builder asked the data about; the verified ones became proposals.
    proposals: list[BindingMeasurement] = field(default_factory=list)
    overrides_measured: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        def label(m: BindingMeasurement) -> str:
            return f"{m.entity_id}.{m.name}"
        return {"bindings": len(self.measurements),
                "verified": [label(m) for m in self.measurements if m.verified is True],
                "refuted": [{"binding": label(m), "note": m.note} for m in self.measurements if m.verified is False],
                "unmeasurable": [label(m) for m in self.measurements if m.verified is None],
                "proposed": [{"binding": label(m), "note": m.note} for m in self.proposals if m.verified is True],
                "candidates_not_proposed": sum(1 for m in self.proposals if m.verified is not True),
                "overrides_measured": list(self.overrides_measured)}


# ── properties: what a binding supplies, and what it may not take ───────────────────────────

def taken_names(graph: Optional[OntologyGraph], entity: OntologyEntity, bindings: list[Binding]) -> dict[str, str]:
    """Every name a further binding's property may not take on this type, lowered → what already holds it: the
    backing's properties, the properties of ``bindings``, and the names of the links the type sits on — a path
    segment names one thing."""
    taken = {k.lower(): f"{entity.id} already has the property {k}" for k in entity.properties or {}}
    for b in bindings:
        for k in b.properties:
            taken.setdefault(k.lower(), f"{entity.id} already reads {k} from the binding {b.name}")
    for r in (graph.relationships.values() if graph is not None else ()):
        if entity.id in (r.from_entity, r.to_entity):
            for n in (r.api_name, r.reverse_api_name, r.business_name()):
                if n:
                    taken.setdefault(n.lower(), f"{entity.id} has a link named {n}")
    return taken


def _table_owner(graph: Optional[OntologyGraph], table: Optional[str]) -> Optional[OntologyEntity]:
    if graph is None or not table:
        return None
    want = table.strip().lower()
    exact = [e for e in graph.entities.values() if any(t.lower() == want for t in e.source_tables)]
    if exact:
        return exact[0]
    loose = [e for e in graph.entities.values() if any(bare(t).lower() == bare(want).lower() for t in e.source_tables)]
    return loose[0] if len(loose) == 1 else None


def _profiles_of(graph: Optional[OntologyGraph], table: Optional[str]) -> dict[str, EntityProperty]:
    """``{column (lowered): profile}`` the builder took of ``table``, through the type the graph reads from it."""
    owner = _table_owner(graph, table)
    return {k.lower(): p for k, p in ((owner.properties or {}) if owner is not None else {}).items()}


def select_lineage(sql: Optional[str], graph: Optional[OntologyGraph]) -> dict[str, tuple[str, str]]:
    """``{output column (lowered): (table, column)}`` for the columns a keyed SELECT passes through unchanged: a bare
    column, renamed or not, of a table in the SELECT's own FROM or JOINs — or every profiled column of the one table a
    star reads (``*`` over a single table, or ``t.*``). Nothing else is traced. An expression, a cast, a column of a
    subquery or a CTE, a star over several tables, or an unqualified name more than one of its tables carries has no
    single source column, so it is left out rather than guessed; an unparseable SELECT traces nothing."""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(sql or "", read="duckdb")
    except Exception:  # noqa: BLE001 — a SELECT we cannot read borrows no profile; its reported types still stand
        return {}
    if not isinstance(tree, exp.Select):
        return {}
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: dict[str, str] = {}
    for tb in tree.find_all(exp.Table):
        clause = tb.parent
        if not isinstance(clause, (exp.From, exp.Join)) or clause.parent is not tree:
            continue                       # a subquery's or a CTE body's table, not one this SELECT reads directly
        if not tb.db and tb.name.lower() in ctes:
            continue                       # a CTE, which no builder profiled
        tables[(tb.alias_or_name or tb.name).lower()] = ".".join(part for part in (tb.catalog, tb.db, tb.name) if part)

    out: dict[str, tuple[str, str]] = {}
    for projection in tree.expressions:
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        qualifier = (inner.table or "").lower() if isinstance(inner, exp.Column) else ""
        if isinstance(inner, exp.Star) or (isinstance(inner, exp.Column) and isinstance(inner.this, exp.Star)):
            if qualifier:
                starred = [tables[qualifier]] if qualifier in tables else []
            else:
                starred = list(tables.values()) if len(tables) == 1 else []
            for table in starred:
                for column, profile in _profiles_of(graph, table).items():
                    out.setdefault(column, (table, profile.name))
            continue
        if not isinstance(inner, exp.Column) or not inner.name:
            continue
        if qualifier:
            table = tables.get(qualifier)
        elif len(tables) == 1:
            table = next(iter(tables.values()))
        else:
            holding = [t for t in tables.values() if inner.name.lower() in _profiles_of(graph, t)]
            table = holding[0] if len(holding) == 1 else None
        if table:
            out[projection.alias_or_name.lower()] = (table, inner.name)
    return out


def column_profiles(graph: Optional[OntologyGraph], table: Optional[str], columns: dict[str, str],
                    sql: Optional[str] = None) -> dict[str, EntityProperty]:
    """``{column: its profile}`` for a binding's columns (``columns`` is ``{column: the data type the warehouse
    reported}``).

    The DATA TYPE is the reported one whenever the warehouse reported one — it is the authority on what the column is
    in this source, a cast or an expression included. The ROLE, unit and description are the profile the builder took
    of the column read: the table's own column for a table binding, and for a keyed SELECT the source column a
    pass-through projection names (`select_lineage`). A computed column borrows no role, so its reported type alone
    decides what the compiler will do with it; a column nothing typed stays untyped, and the compiler will not add it
    up."""
    own = _profiles_of(graph, table) if table else {}
    traced = select_lineage(sql, graph) if not table and (sql or "").strip() else {}
    out: dict[str, EntityProperty] = {}
    for col, data_type in columns.items():
        name = str(col)
        if table:
            profile = own.get(name.lower())
        else:
            source = traced.get(name.lower())
            profile = _profiles_of(graph, source[0]).get(source[1].lower()) if source else None
        if profile is None:
            prop = EntityProperty(name=name, display_name=_title(name))
        else:
            same = profile.name.lower() == name.lower()
            prop = profile.model_copy(update={"name": name,
                                              "display_name": (profile.display_name or _title(name)) if same
                                              else _title(name)})
        reported = str(data_type or "").strip()
        out[name] = prop.model_copy(update={"data_type": reported}) if reported else prop
    return out


def supply(columns: dict[str, EntityProperty], key: str, taken: dict[str, str],
           mapping: Optional[dict[str, str]] = None, *,
           strict: bool = False) -> tuple[dict[str, EntityProperty], dict[str, str], dict[str, str], str]:
    """``(properties, renamed, skipped, problem)`` for a binding over ``columns`` (``{column: profile}``) — ``renamed``
    is ``{property: column}`` for each property whose name differs from its column.

    With no ``mapping`` every column but the key is supplied under its own name, and a name the type already uses is
    skipped with the reason — a binding adds properties, it never shadows one. A ``mapping`` (``{property: column}``)
    supplies exactly those, renamed; with ``strict`` (a person binding it now) a name it cannot take, or a column the
    source lacks, is a problem rather than a skip, because they asked for it by name."""
    by_lower = {str(c).lower(): str(c) for c in columns}
    properties: dict[str, EntityProperty] = {}
    renamed: dict[str, str] = {}
    skipped: dict[str, str] = {}
    wanted = dict(mapping) if mapping else {c: c for c in columns if str(c).lower() != key.lower()}
    for prop, col in wanted.items():
        prop, col = str(prop).strip(), str(col).strip()
        actual = by_lower.get(col.lower())
        clash = prop.lower() in taken or any(p.lower() == prop.lower() for p in properties)
        if not _COLUMN.match(prop):
            why = f"'{prop}' is not a property name — letters, digits and underscores"
        elif actual is None:
            why = f"the source has no column '{col}'"
        elif actual.lower() == key.lower():
            why = f"'{actual}' is the binding's key — it holds the object's key, not a property"
        elif clash:
            why = taken.get(prop.lower()) or f"'{prop}' is supplied twice"
            why += "" if mapping else " — name it in `properties` to bind it"
        else:
            why = ""
        if why:
            if strict and mapping:
                return {}, {}, {}, why
            skipped[actual or col] = why
            continue
        profile = columns[actual]
        properties[prop] = profile.model_copy(update={
            "name": prop, "is_primary_key": False,
            "display_name": (profile.display_name or _title(prop)) if prop == actual else _title(prop)})
        if prop != actual:
            renamed[prop] = actual
    return properties, renamed, skipped, ""


# ── frames over a timeseries binding's readings (ON-5) ──────────────────────────────

#: What a frame may do to the readings inside it.
AGGS: tuple[str, ...] = ("sum", "avg", "min", "max", "count")


def frame_problem(name: str, raw: Any) -> str:
    """Why a declared frame cannot be read as written, or "" — its shape only; its column is the warehouse's to
    confirm. Refusals are sentences because a frame is declared by a person, and a frame that quietly did
    something else would be indistinguishable from one that worked."""
    if not _COLUMN.match(name or ""):
        return f"'{name}' is not a property name — letters, digits and underscores"
    if not isinstance(raw, dict):
        return f"frame '{name}' is a mapping with `column`, and a `range` over the readings"
    if not _COLUMN.match(str(raw.get("column") or "").strip()):
        return f"frame '{name}' names the binding's column it reads in `column`"
    offset, window = raw.get("offset"), raw.get("window")
    if offset is not None:
        # A reading N back is one row, not a span: it uses neither an aggregate nor a window, and saying so is
        # better than accepting words the compiler would then ignore.
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 1:
            return f"frame '{name}' counts readings BACK in `offset` — a whole number of at least 1"
        if raw.get("agg"):
            return (f"frame '{name}' declares both `offset` and `agg` — a reading N back is a VALUE, not an "
                    f"aggregate; drop one")
        if window is not None:
            return f"frame '{name}' declares both `offset` and `window` — a reading N back spans no window"
        return ""
    range_ = str(raw.get("range") or "trailing")
    if range_ not in RANGES:
        return f"frame '{name}' has an unknown range {range_!r} — known: {', '.join(RANGES)}"
    if str(raw.get("agg") or "avg") not in AGGS:
        return f"frame '{name}' has an unknown agg {raw.get('agg')!r} — known: {', '.join(AGGS)}"
    if range_ in ("trailing", "leading") and not (isinstance(window, int) and not isinstance(window, bool)
                                                  and window >= 1):
        return f"frame '{name}' is {range_} and needs `window` — how many readings, including this one"
    if range_ not in ("trailing", "leading") and window is not None:
        return f"frame '{name}' is {range_}, which spans no fixed number of readings — drop `window`"
    return ""


def normalized_frame(raw: dict) -> dict:
    """One frame as the overrides tree stores it: trimmed, the parts its shape does not use dropped. Idempotent.

    A frame with an `offset` reads ONE row, so it carries no aggregate and no window and its range is `current` —
    which is what `compile_measure` does with a LAG whatever the range says."""
    column = str(raw.get("column") or "").strip()
    if raw.get("offset") is not None:
        return {"column": column, "range": "current", "offset": int(raw["offset"])}
    out: dict = {"column": column, "range": str(raw.get("range") or "trailing"),
                 "agg": str(raw.get("agg") or "avg")}
    if out["range"] in ("trailing", "leading"):
        out["window"] = int(raw["window"])
    return out


def frame_properties(frames: dict, columns: dict[str, EntityProperty], taken: dict[str, str],
                     supplied: dict[str, EntityProperty]) -> tuple[dict[str, Frame], dict[str, EntityProperty], str]:
    """``(frames, properties, problem)`` — a frame becomes a property of the type like any other, computed in the
    reduction rather than read from a column.

    What it borrows is what it can TRACE: a frame over one known column keeps that column's type and unit, because
    the average of a price in EUR is a price in EUR — the one exception is `count`, which counts readings and is a
    number of nothing. Nothing is inferred beyond that (ON-1b's law for a computed column), and the description is
    the frame in the declaration's own words rather than a name someone has to decode."""
    by_lower = {str(c).lower(): str(c) for c in columns}
    out: dict[str, Frame] = {}
    properties: dict[str, EntityProperty] = {}
    for name, raw in frames.items():
        name = str(name).strip()
        frame = Frame(**normalized_frame(raw))
        actual = by_lower.get(frame.column.lower())
        if actual is None:
            return {}, {}, (f"frame '{name}' reads '{frame.column}', which its source does not have — its "
                            f"columns: {', '.join(sorted(by_lower.values()))[:200]}")
        frame = frame.model_copy(update={"column": actual})
        if name.lower() in taken:
            return {}, {}, f"frame '{name}': {taken[name.lower()]}"
        if any(p.lower() == name.lower() for p in {**supplied, **properties}):
            return {}, {}, f"frame '{name}' is already supplied by this binding as a column — name it differently"
        profile = columns[actual]
        base = (EntityProperty(name=name) if frame.agg == "count" and not frame.offset
                else profile.model_copy(update={"unit": profile.unit}))
        properties[name] = base.model_copy(update={
            "name": name, "display_name": _title(name), "is_primary_key": False, "is_derived": True,
            "semantic_type": "measure", "description": frame.describe()})
        out[name] = frame
    return out, properties, ""


# ── rollups over a detail binding's rows (ON-7) ─────────────────────────────────────────────

#: What a rollup may do to the rows inside an object's partition.
ROLLUP_AGGS: tuple[str, ...] = ("sum", "avg", "min", "max", "count")


def rollup_problem(name: str, raw: Any) -> str:
    """Why a declared rollup cannot be read as written, or "" — its shape only; its column is the warehouse's to
    confirm. Refusals are sentences, for the same reason a frame's are."""
    if not _COLUMN.match(name or ""):
        return f"'{name}' is not a property name — letters, digits and underscores"
    if not isinstance(raw, dict):
        return f"rollup '{name}' is a mapping with `column`, and an `agg` over the object's rows"
    if not _COLUMN.match(str(raw.get("column") or "").strip()):
        return f"rollup '{name}' names the binding's column it reads in `column`"
    if str(raw.get("agg") or "sum") not in ROLLUP_AGGS:
        return f"rollup '{name}' has an unknown agg {raw.get('agg')!r} — known: {', '.join(ROLLUP_AGGS)}"
    return ""


def normalized_rollup(raw: dict) -> dict:
    """One rollup as the overrides tree stores it. Idempotent."""
    return {"column": str(raw.get("column") or "").strip(), "agg": str(raw.get("agg") or "sum")}


def rollup_properties(rollups: dict, columns: dict[str, EntityProperty], taken: dict[str, str],
                      part: str) -> tuple[dict[str, Rollup], dict[str, EntityProperty], str]:
    """``(rollups, properties, problem)`` — each rollup becomes a property of the type like any other, computed in
    the pre-aggregation rather than read from a column. It borrows what it can trace: the rolled-up column's type
    and unit (the sum of a quantity is a quantity; `count` counts rows and is a number of nothing) and nothing
    more, ON-1b's law for a computed column."""
    by_lower = {str(c).lower(): str(c) for c in columns}
    out: dict[str, Rollup] = {}
    properties: dict[str, EntityProperty] = {}
    for name, raw in rollups.items():
        name = str(name).strip()
        rollup = Rollup(**normalized_rollup(raw))
        actual = by_lower.get(rollup.column.lower())
        if actual is None:
            return {}, {}, (f"rollup '{name}' reads '{rollup.column}', which its source does not have — its "
                            f"columns: {', '.join(sorted(by_lower.values()))[:200]}")
        rollup = rollup.model_copy(update={"column": actual})
        if name.lower() in taken:
            return {}, {}, f"rollup '{name}': {taken[name.lower()]}"
        if any(p.lower() == name.lower() for p in properties):
            return {}, {}, f"rollup '{name}' is declared twice"
        profile = columns[actual]
        base = EntityProperty(name=name) if rollup.agg == "count" else profile.model_copy(update={"unit": profile.unit})
        properties[name] = base.model_copy(update={
            "name": name, "display_name": _title(name), "is_primary_key": False, "is_derived": True,
            "semantic_type": "measure", "description": rollup.describe(part)})
        out[name] = rollup
    return out, properties, ""


# ── a person's binding: its spec, its bind against the warehouse, its rebuild at read time ──

def spec_problem(name: str, spec: Any) -> str:
    """Why a binding spec cannot be bound as written, or "" — its shape only; its columns are the warehouse's to
    confirm."""
    if not NAME_PATTERN.match(name or ""):
        return "a binding name is snake_case: a lowercase letter, then lowercase letters, digits or underscores"
    if not isinstance(spec, dict):
        return "a binding is a mapping with `table` or `sql`, and `key`"
    table, sql = str(spec.get("table") or "").strip(), str(spec.get("sql") or "").strip()
    if bool(table) == bool(sql):
        return "a binding reads exactly one of `table` or `sql`"
    if table and not _TABLE.match(table):
        return f"{table!r} is not a table identifier"
    if sql and (not _SELECT.match(sql) or ";" in sql.rstrip().rstrip(";")):
        return "a binding's `sql` is one SELECT"
    if not _COLUMN.match(str(spec.get("key") or "").strip()):
        return "a binding names the column that holds the object's key in `key`"
    kind = spec.get("kind") or "static"
    if kind not in ("static", "timeseries", "detail"):
        return "a binding's kind is static, timeseries or detail"
    time_column = str(spec.get("time_column") or "").strip()
    if kind == "timeseries" and not _COLUMN.match(time_column):
        return "a timeseries binding names its `time_column`"
    if kind != "timeseries" and time_column:
        return f"a {kind} binding has no time column — `time_column` belongs to a timeseries binding"
    rollups = spec.get("rollups")
    if kind == "detail":
        # ON-7 — many rows per object with no clock: its columns are NOT properties of the object, so it supplies
        # exactly what its rollups declare, and nothing else may be asked of it.
        if spec.get("properties"):
            return ("a detail binding's columns are many per object, so none is a property of it — declare what is "
                    "rolled up in `rollups` ({name: {column, agg}}) instead of `properties`")
        if spec.get("frames"):
            return "frames read a timeseries binding's readings over time — a detail binding declares `rollups`"
        if not isinstance(rollups, dict) or not rollups:
            return "a detail binding declares at least one rollup in `rollups` — {name: {column, agg}}"
        for rollup_name, raw in rollups.items():
            problem = rollup_problem(str(rollup_name), raw)
            if problem:
                return problem
    elif rollups:
        return f"`rollups` roll up a detail binding's rows — a {kind} binding supplies its columns as they are"
    mapping = spec.get("properties")
    if mapping is not None and (not isinstance(mapping, dict)
                                or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())):
        return "`properties` maps a property name to one of the binding's columns"
    frames = spec.get("frames")
    if frames is not None:
        if not isinstance(frames, dict):
            return "`frames` maps a property name to a frame over the binding's readings"
        if frames and kind != "timeseries":
            return ("a frame reads the readings of a timeseries binding — a static binding holds one row per "
                    "object, and a frame over one row is that row")
        for frame_name, raw in frames.items():
            problem = frame_problem(str(frame_name), raw)
            if problem:
                return problem
    return ""


def normalized_spec(spec: dict) -> dict:
    """The spec as the overrides tree stores it: trimmed, the empty parts dropped. Idempotent."""
    out: dict = {"kind": spec.get("kind") or "static", "key": str(spec.get("key") or "").strip()}
    table, sql = str(spec.get("table") or "").strip(), str(spec.get("sql") or "").strip()
    if table:
        out["table"] = table
    else:
        out["sql"] = sql.rstrip().rstrip(";").strip()
    time_column = str(spec.get("time_column") or "").strip()
    if time_column:
        out["time_column"] = time_column
    mapping = spec.get("properties")
    if isinstance(mapping, dict) and mapping:
        out["properties"] = {str(k).strip(): str(v).strip() for k, v in mapping.items()}
    frames = spec.get("frames")
    if isinstance(frames, dict) and frames:
        out["frames"] = {str(k).strip(): normalized_frame(v) for k, v in frames.items()}
    rollups = spec.get("rollups")
    if isinstance(rollups, dict) and rollups:
        out["rollups"] = {str(k).strip(): normalized_rollup(v) for k, v in rollups.items()}
    return out


def binding_spec(binding: Binding) -> dict:
    """The part of a binding a person edits — its source, key, kind, time column and property names — never its
    measurement: what the overrides tree stores, what the export writes, and what binding a proposal sends."""
    spec: dict = {"kind": binding.kind, "key": binding.key}
    if binding.reads == "query":
        spec["sql"] = binding.sql or ""
    else:
        spec["table"] = binding.table or ""
    if binding.time_column:
        spec["time_column"] = binding.time_column
    if binding.columns and binding.kind != "detail":
        spec["properties"] = {name: column_of(binding, name) for name in binding.properties
                              if name not in binding.frames}
    if binding.frames:
        spec["frames"] = {name: normalized_frame(f.model_dump()) for name, f in binding.frames.items()}
    if binding.rollups:
        spec["rollups"] = {name: normalized_rollup(r.model_dump()) for name, r in binding.rollups.items()}
    return spec


def describe_with(db: Any) -> Describe:
    """``describe(from_fragment)`` over an open connection: the columns a binding's source reports, each with the data
    type the warehouse reports for it — read through the connection's typed result channel on a ``LIMIT 0`` statement,
    so no row is fetched and the security gate still sees it — or ``""`` for every column where a connector reports no
    types. ``({}, error)`` when the source cannot be read."""
    def describe(source: str) -> tuple[dict[str, str], Optional[str]]:
        sql = f"SELECT * FROM {source} LIMIT 0"
        typed = getattr(db, "execute_typed", None)
        result, payload = typed("binding_columns", sql) if callable(typed) else (db.execute("binding_columns", sql), None)
        if getattr(result, "error", None):
            return {}, result.error
        names = [str(c) for c in (result.columns or [])]
        types = [str(t or "") for t in ((payload or {}).get("types") or [])]
        aligned = len(types) == len(names)             # positional, so a mismatched list types nothing
        return {n: (types[i] if aligned else "") for i, n in enumerate(names)}, None
    return describe


def bind_binding(entity: OntologyEntity, name: str, spec: Any, graph: Optional[OntologyGraph],
                 describe: Describe) -> dict:
    """The bind entry for one binding a person set on ``entity`` (the served type): the spec's shape, then its source
    read for columns — the key and the time column must be among them, and every property it supplies must be free
    on the type. ALWAYS returns an entry, ``bound`` False with the reason when anything fails; nothing is counted
    here (`measure_binding` is)."""
    problem = spec_problem(name, spec)
    if problem:
        return {"bound": False, "note": problem}
    spec = normalized_spec(spec)
    if name == primary_name(entity).lower():
        return {"bound": False, "note": f"'{name}' names {entity.id}'s backing, its first binding", "spec": spec}
    backing_table = (entity.backing.table if entity.backing is not None else None) or ""
    if spec.get("table") and backing_table and spec["table"].lower() == backing_table.lower():
        return {"bound": False, "note": f"{spec['table']} already backs {entity.id} — its columns are its properties",
                "spec": spec}
    try:
        columns, error = describe(binding_from(Binding(name=name, table=spec.get("table"), sql=spec.get("sql")), "b"))
    except Exception as exc:  # noqa: BLE001 — an unreadable source does not bind, and says why
        columns, error = {}, f"{type(exc).__name__}: {exc}"
    if error or not columns:
        return {"bound": False, "note": f"its source could not be read: {error or 'no columns'}"[:300], "spec": spec}
    by_lower = {str(c).lower(): str(c) for c in columns}
    listed = ", ".join(sorted(by_lower.values()))[:300]
    key = by_lower.get(spec["key"].lower())
    if key is None:
        return {"bound": False, "spec": spec,
                "note": f"its source has no column '{spec['key']}' to hold the {entity.id} key — its columns: {listed}"}
    spec["key"] = key
    if spec.get("time_column"):
        time_column = by_lower.get(spec["time_column"].lower())
        if time_column is None:
            return {"bound": False, "spec": spec,
                    "note": f"its source has no time column '{spec['time_column']}' — its columns: {listed}"}
        spec["time_column"] = time_column
    others = [b for b in entity.bindings or [] if b.name != name]
    reported = {str(c): str(t or "") for c, t in columns.items()}
    if spec["kind"] == "detail":
        # ON-7 — its columns are many per object, so it supplies exactly its rollups, each traced to a column.
        rollups, rolled, problem = rollup_properties(spec["rollups"],
                                                     column_profiles(graph, spec.get("table"), columns, spec.get("sql")),
                                                     taken_names(graph, entity, others), name)
        if problem:
            return {"bound": False, "note": problem, "spec": spec}
        return {"bound": True, "note": "", "spec": spec, "columns": reported,
                "supplies": {n: r.describe(name) for n, r in rollups.items()}, "skipped": {}}
    properties, renamed, skipped, problem = supply(column_profiles(graph, spec.get("table"), columns, spec.get("sql")),
                                                   key, taken_names(graph, entity, others), spec.get("properties"),
                                                   strict=True)
    if problem:
        return {"bound": False, "note": problem, "spec": spec}
    # A binding may supply nothing BUT frames — "the trailing average of a price" is a property the source has no
    # column for, and demanding a pass-through column beside it would be arbitrary.
    profiles = column_profiles(graph, spec.get("table"), columns, spec.get("sql"))
    frames, framed, problem = frame_properties(spec.get("frames") or {}, profiles,
                                               taken_names(graph, entity, others), properties)
    if problem:
        return {"bound": False, "note": problem, "spec": spec}
    if not (properties or framed):
        return {"bound": False, "spec": spec,
                "note": "it would supply no property" + (f" — every column's name is taken on {entity.id} "
                                                         f"({', '.join(sorted(skipped))}); name them in `properties`"
                                                         if skipped else "")}
    return {"bound": True, "note": "", "spec": spec, "columns": reported,
            "supplies": {**{p: renamed.get(p, p) for p in properties},
                         **{name: f.describe() for name, f in frames.items()}}, "skipped": skipped}


def binding_block(entries: dict) -> dict:
    """The override binding entry every binding on one type shares: ``bound`` only when each of them bound."""
    unbound = [f"{name}: {e.get('note') or 'not bound'}" for name, e in entries.items() if e.get("bound") is not True]
    return {"bound": not unbound, "note": "; ".join(unbound), "entries": entries}


def declared_bindings(entity: OntologyEntity, specs: Any, block: Any,
                      graph: Optional[OntologyGraph]) -> tuple[list[Binding], list[str]]:
    """The bindings a person set on ``entity``, rebuilt from their specs and what their bind and their count
    recorded — no database. ``(bindings, skipped)``: a binding whose entry never bound, or whose spec changed since,
    is skipped with the reason and reaches no reader. Built in declaration order, each binding's properties taken
    before the next binding's, and never reading ``entity.bindings`` — so applying the overlay twice builds the
    same thing."""
    entries = block.get("entries") if isinstance(block, dict) else None
    entries = entries if isinstance(entries, dict) else {}
    out: list[Binding] = []
    skipped: list[str] = []
    for name, raw in (specs.items() if isinstance(specs, dict) else []):
        problem = spec_problem(name, raw)
        if problem:
            skipped.append(f"{name}: {problem}")
            continue
        spec, entry = normalized_spec(raw), entries.get(name) or {}
        if entry.get("bound") is not True or entry.get("spec") != spec:
            skipped.append(f"{name}: {entry.get('note') or 'not bound against the warehouse since it was written'}")
            continue
        columns = entry.get("columns") if isinstance(entry.get("columns"), dict) else {}
        profiles = column_profiles(graph, spec.get("table"), columns, spec.get("sql"))
        taken = taken_names(graph, entity, out)
        if spec["kind"] == "detail":
            rollups, rolled, rollup_problem_note = rollup_properties(spec.get("rollups") or {}, profiles, taken, name)
            if rollup_problem_note:
                skipped.append(f"{name}: {rollup_problem_note}")
                continue
            binding = Binding(name=name, kind="detail", table=spec.get("table"), sql=spec.get("sql"),
                              key=spec["key"], properties=rolled, rollups=rollups, source="human",
                              note="bound; not yet measured")
            measured = entry.get("measured") if isinstance(entry.get("measured"), dict) else {}
            if measured.get("spec") == spec:
                for k in _MEASURED:
                    setattr(binding, k, measured.get(k) if k != "note" else str(measured.get(k) or ""))
            out.append(binding)
            continue
        properties, renamed, lost, _ = supply(profiles, spec["key"], taken, spec.get("properties"))
        frames, framed, frame_problem_note = frame_properties(spec.get("frames") or {}, profiles, taken, properties)
        if frame_problem_note:
            skipped.append(f"{name}: {frame_problem_note}")
            continue
        binding = Binding(name=name, kind=spec["kind"], table=spec.get("table"), sql=spec.get("sql"), key=spec["key"],
                          time_column=spec.get("time_column", ""), properties={**properties, **framed},
                          columns=renamed, frames=frames,
                          skipped=lost, source="human", note="bound; not yet measured")
        measured = entry.get("measured") if isinstance(entry.get("measured"), dict) else {}
        if measured.get("spec") == spec:
            for k in _MEASURED:
                setattr(binding, k, measured.get(k) if k != "note" else str(measured.get(k) or ""))
        out.append(binding)
    return out, skipped


def measure_override_bindings(connection_id: str, schema_name: Optional[str], db: Any, graph: OntologyGraph,
                              report: Optional[BindingReport] = None) -> BindingReport:
    """Count every binding a person set in the overrides tree against the objects it binds to, and record the counts
    on its entry for the spec they were taken on, so the overlay carries them at read time. Counted over the backing
    the same override sets, when it sets one. Best-effort; an unreadable tree measures nothing."""
    report = report if report is not None else BindingReport()
    try:
        from aughor.ontology.overrides import load_overrides, save_override
        overrides = load_overrides(connection_id, schema_name or "default")
    except Exception:  # noqa: BLE001
        return report
    for ov in overrides:
        specs = ov.fields.get("bindings") if ov.target_kind == "entity" else None
        entity = graph.entities.get(ov.target_id)
        if not isinstance(specs, dict) or not specs or entity is None:
            continue
        backing = ov.fields.get("backing")
        if isinstance(backing, dict):
            entity = entity.model_copy(update={"backing": Backing(**{k: v for k, v in backing.items()
                                                                     if k in Backing.model_fields})})
        block = dict(ov.binding.get("bindings") or {})
        entries = dict(block.get("entries") or {})
        built, _ = declared_bindings(entity, specs, block, graph)
        for binding in built:
            m = measure_binding(db, entity, binding)
            entries[binding.name] = {**entries[binding.name],
                                     "measured": {"spec": entries[binding.name]["spec"], **m.counts()}}
            report.measurements.append(m)
            report.overrides_measured.append(f"{entity.id}.{binding.name}")
        if not built:
            continue
        ov.binding["bindings"] = binding_block(entries)
        try:
            save_override(connection_id, schema_name or "default", ov)
        except Exception as exc:  # noqa: BLE001
            logger.debug("binding measurement not saved for %s: %s", ov.target_id, exc)
    return report


# ── proposals: another type's table carries this type's key ────────────────────────────────

def _free_name(table: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", bare(table).lower()).strip("_")[:72] or "binding"
    base = base if base[0].isalpha() else f"t_{base}"
    name, n = base, 2
    while name in used:
        name, n = f"{base}_{n}", n + 1
    return name


def propose_bindings(graph: OntologyGraph, db: Any) -> list[BindingMeasurement]:
    """Propose a static binding wherever another type's table carries a type's key and the data proves it one row
    per object — the builder's half of ON-1b. Only a type whose own key was measured unique is proposed for; each
    candidate is counted, and the verified ones replace the type's `proposed_bindings`. Every candidate's
    measurement is returned, so a report can say how many were asked about and not proposed."""
    asked: list[BindingMeasurement] = []
    for entity in sorted(graph.entities.values(), key=lambda e: e.id):
        entity.proposed_bindings = []
        key, backing = key_of(entity), entity.backing
        if not key or backing is None or backing.verified is not True:
            continue
        mine = {bare(t).lower() for t in entity.source_tables} | ({bare(backing.table).lower()} if backing.table else set())
        taken = taken_names(graph, entity, [])
        used = {primary_name(entity).lower()}
        candidates = []
        for other in sorted(graph.entities.values(), key=lambda e: e.id):
            b = other.backing
            if other is entity or b is None or b.kind != "table" or not b.table or bare(b.table).lower() in mine:
                continue
            column = next((c for c in other.properties or {} if c.lower() == key.lower()), None)
            if column is not None:
                candidates.append((other, b.table, column))
        for other, table, column in candidates[:MAX_CANDIDATES]:
            properties, renamed, skipped, _ = supply(dict(other.properties or {}), column, taken)
            name = _free_name(table, used)
            binding = Binding(name=name, kind="static", table=table, key=column, properties=properties,
                              columns=renamed, skipped=skipped, source="proposed")
            m = measure_binding(db, entity, binding)
            m.stamp(binding)
            asked.append(m)
            if m.verified is True and properties:
                entity.proposed_bindings.append(binding)
                used.add(name)
            elif m.covered and m.non_null and m.distinct is not None and m.distinct != m.non_null:
                # ON-7 — the key repeats: many rows per object, no clock — a PART. Proposed as a detail binding
                # with the one rollup the data can vouch for, how many rows each object has; a person adds the rest.
                part_key = key_of(other) or column
                rollups, rolled, problem = rollup_properties({f"{name}_count": {"column": part_key, "agg": "count"}},
                                                             dict(other.properties or {}), taken, name)
                if problem:
                    continue
                part = Binding(name=name, kind="detail", table=table, key=column, properties=rolled, rollups=rollups,
                               source="proposed")
                md = measure_binding(db, entity, part)
                md.stamp(part)
                asked.append(md)
                if md.verified is True:
                    entity.proposed_bindings.append(part)
                    used.add(name)
    proposed = [f"{m.entity_id}.{m.name}" for m in asked if m.verified is True]
    if proposed:
        logger.info("[ontology:%s] bindings proposed: %s", graph.connection_id, proposed)
    return asked
