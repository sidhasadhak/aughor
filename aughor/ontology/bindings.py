"""ON-1b — bindings: each property knows its source (ROADMAP §3.15, amended 2026-09-11).

An object type's first binding is its backing (ON-1): the table or keyed SELECT whose rows ARE its objects. A
further binding is another table or keyed SELECT joined to the object on its key, supplying properties the backing
does not carry — an order's payment method from `payments`, a customer's tier from `customer_profiles` — so an
object that spans tables no longer needs a hand-written SELECT to be complete. Its kind is `static` (one row per
object) or `timeseries` (many rows per object over a time column).

Whether one holds is MEASURED here, the ON-0a way, never assumed:

* a **static** binding is verified when its key is unique over its keyed rows AND reaches objects that exist — only
  then can a LEFT JOIN on it neither multiply nor invent objects, so only then does anything read it;
* a **timeseries** binding is verified when its key reaches objects that exist; its latest value and its history
  are ON-5's, so nothing reads one yet, and every reader says so (`binding_problem`).

Either way the counts are kept: the binding's rows, its keyed rows and distinct keys, the objects it was counted
against, how many of those it covers, and the keys that reach no object.

A person sets a binding through the overrides tree (`PUT /ontology/entities/{id}/bindings/{name}`): its source is
read for its columns before anything is written (`bind_binding`), and the overlay rebuilds it at read time from what
that check recorded, without a database in hand (`declared_bindings`). The builder PROPOSES a binding wherever another
type's table carries this type's key and the data proves it one row per object (`propose_bindings`); a proposal lives
on `proposed_bindings`, which no query, page or answer reads.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from aughor.ontology.backing import object_from
from aughor.ontology.cardinality import quote_ident, quote_table
from aughor.ontology.display import key_of
from aughor.ontology.models import Backing, Binding, EntityProperty, OntologyEntity, OntologyGraph

logger = logging.getLogger(__name__)

#: A binding's name — what a person, the panel and the plan call it: snake_case, bounded.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
#: A column or property name as a binding spells it.
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: A table identifier, optionally qualified. It is interpolated into a probe, so anything else is refused rather than
#: escaped — the overrides store's rule for a table a person names.
_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")
_SELECT = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
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
    if binding.kind == "timeseries":
        return (f"{binding.name} on {entity.id} is a timeseries binding — many rows per {entity.id} over "
                f"{binding.time_column or 'its time column'} — and reading its latest value or its history is "
                "ON-5's, not built yet")
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
    if kind == "timeseries":
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


def column_profiles(graph: Optional[OntologyGraph], table: Optional[str],
                    columns: dict[str, str]) -> dict[str, EntityProperty]:
    """``{column: its profile}`` for a binding's columns: the profile the builder took of the table where a type in
    the graph is read from it (data type, role, unit, description), else the bare column with the data type the
    warehouse reported — which may be empty, and then the compiler will not add it up."""
    owner = _table_owner(graph, table)
    known = {k.lower(): p for k, p in ((owner.properties or {}) if owner is not None else {}).items()}
    out: dict[str, EntityProperty] = {}
    for col, data_type in columns.items():
        profile = known.get(str(col).lower())
        out[str(col)] = profile if profile is not None else EntityProperty(
            name=str(col), display_name=_title(col), data_type=str(data_type or ""))
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
    if kind not in ("static", "timeseries"):
        return "a binding's kind is static or timeseries"
    time_column = str(spec.get("time_column") or "").strip()
    if kind == "timeseries" and not _COLUMN.match(time_column):
        return "a timeseries binding names its `time_column`"
    if kind == "static" and time_column:
        return "a static binding holds one row per object — `time_column` belongs to a timeseries binding"
    mapping = spec.get("properties")
    if mapping is not None and (not isinstance(mapping, dict)
                                or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())):
        return "`properties` maps a property name to one of the binding's columns"
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
    if binding.columns:
        spec["properties"] = {name: column_of(binding, name) for name in binding.properties}
    return spec


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
    properties, renamed, skipped, problem = supply(column_profiles(graph, spec.get("table"), columns), key,
                                                   taken_names(graph, entity, others), spec.get("properties"),
                                                   strict=True)
    if problem:
        return {"bound": False, "note": problem, "spec": spec}
    if not properties:
        return {"bound": False, "spec": spec,
                "note": "it would supply no property" + (f" — every column's name is taken on {entity.id} "
                                                         f"({', '.join(sorted(skipped))}); name them in `properties`"
                                                         if skipped else "")}
    return {"bound": True, "note": "", "spec": spec, "columns": {str(c): str(t or "") for c, t in columns.items()},
            "supplies": {p: renamed.get(p, p) for p in properties}, "skipped": skipped}


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
        properties, renamed, lost, _ = supply(column_profiles(graph, spec.get("table"), columns), spec["key"],
                                              taken_names(graph, entity, out), spec.get("properties"))
        binding = Binding(name=name, kind=spec["kind"], table=spec.get("table"), sql=spec.get("sql"), key=spec["key"],
                          time_column=spec.get("time_column", ""), properties=properties, columns=renamed,
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
    proposed = [f"{m.entity_id}.{m.name}" for m in asked if m.verified is True]
    if proposed:
        logger.info("[ontology:%s] bindings proposed: %s", graph.connection_id, proposed)
    return asked
