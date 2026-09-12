"""ON-7 — declared entities and declared links (ROADMAP §3.15, the second movement).

The builder mints one type per profiled table and one link per join it found; before this module nothing else
could put a noun or an edge into the graph. Here a person — or an explorer agent (ON-7b), or a pack — DECLARES:

* an **entity**: its id, display name, description, domain, role, and the source that holds one row per object
  (a table or a keyed SELECT, with the column that is its key). The door reads that source for its columns and
  counts the key's uniqueness before anything is written; both are recorded on the override's `backing` entry,
  so the overlay rebuilds the type at read time with no database in hand (`declared_entity`);
* a **link**: two types, a business verb, and the column on each side that joins them. The door checks both
  columns exist, measures each side's uniqueness (the cardinality, ON-0a's way) and how much of the from-side's
  keys the to-side actually holds, and records it on the override's `link` entry; the overlay rebuilds the
  relationship from that (`declared_relationship`). A declared link is traversable by the compiler exactly when
  a found one is: measured, and not N:N.

Every declaration is a CLAIM with provenance (`origin`: human or model) and a measurement beside it. Nothing
here is believed because it was said; a declared entity whose key repeats reads `verified: False` on its card,
and a declared link whose keys never meet is stored with `value_overlap` 0 and refused by the compiler.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from aughor.ontology.backing import measure_key, object_from
from aughor.ontology.bindings import COLUMN_PATTERN, SELECT_PATTERN, TABLE_PATTERN, column_profiles, taken_names
from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import (
    LINK_NAME_PATTERN,
    Backing,
    OntologyEntity,
    OntologyGraph,
    OntologyRelationship,
    snake_name,
)

logger = logging.getLogger(__name__)

#: A declared type's id: PascalCase, bounded — what every graph already spells its ids in.
ENTITY_ID = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}$")
ROLES = ("reference_data", "business_object", "event", "standalone")
ORIGINS = ("human", "model")
CARDINALITIES = ("1:1", "1:N", "N:1", "N:N")

# ── entities ────────────────────────────────────────────────────────────────────────────────


def entity_spec_problem(spec: Any) -> str:
    """Why an entity cannot be declared as written, or "" — its shape only; its source is the warehouse's."""
    if not isinstance(spec, dict):
        return "an entity is declared as a mapping with `id`, `display_name` and `backing`"
    if not ENTITY_ID.match(str(spec.get("id") or "")):
        return "an entity id is PascalCase — a capital letter, then letters and digits (Order, ReturnLogistics)"
    if not str(spec.get("display_name") or "").strip():
        return "an entity has a display name"
    if spec.get("entity_type") and spec["entity_type"] not in ROLES:
        return f"an entity's role is one of {', '.join(ROLES)}"
    if spec.get("origin") and spec["origin"] not in ORIGINS:
        return f"a declared entity's origin is one of {', '.join(ORIGINS)}"
    backing = spec.get("backing")
    if not isinstance(backing, dict):
        return "an entity names the source that holds one row per object in `backing` — {table | sql, primary_key}"
    table, sql = str(backing.get("table") or "").strip(), str(backing.get("sql") or "").strip()
    if bool(table) == bool(sql):
        return "a backing reads exactly one of `table` or `sql`"
    if table and not TABLE_PATTERN.match(table):
        return f"{table!r} is not a table identifier"
    if sql and (not SELECT_PATTERN.match(sql) or ";" in sql.rstrip().rstrip(";")):
        return "a backing's `sql` is one SELECT"
    if not COLUMN_PATTERN.match(str(backing.get("primary_key") or "").strip()):
        return "a backing names the column that is the object's key in `primary_key`"
    return ""


def entity_fields(spec: dict) -> dict:
    """The override fields a declaration stores — trimmed, the empty parts dropped. Idempotent."""
    backing = spec["backing"]
    table, sql = str(backing.get("table") or "").strip(), str(backing.get("sql") or "").strip()
    stored: dict = {"kind": "table" if table else "query", "primary_key": str(backing["primary_key"]).strip()}
    stored["table" if table else "sql"] = table or sql.rstrip().rstrip(";").strip()
    out: dict = {"declared": True, "display_name": str(spec["display_name"]).strip(),
                 "origin": spec.get("origin") or "human", "backing": stored}
    for field in ("description", "domain"):
        if str(spec.get(field) or "").strip():
            out[field] = str(spec[field]).strip()
    if spec.get("entity_type"):
        out["entity_type"] = spec["entity_type"]
    return out


def measure_declared_backing(db: Any, fields: dict, describe) -> dict:
    """The `backing` entry for a declared entity: its columns as the warehouse reports them, and its key counted.
    ``describe(from_fragment)`` is `bindings.describe_with(db)`. ALWAYS returns an entry; `bound` False with the
    reason when the source cannot be read."""
    backing = Backing(**{k: v for k, v in fields["backing"].items() if k in Backing.model_fields})
    source = object_from(OntologyEntity(id="X", display_name="X", source_tables=[backing.table] if backing.table else [],
                                        identity_key=backing.primary_key, grain_verified=False, backing=backing), "b")
    entry: dict = {"sql": (backing.sql or "").strip(), "primary_key": backing.primary_key, "table": backing.table or ""}
    try:
        columns, error = describe(source)
    except Exception as exc:  # noqa: BLE001 — an unreadable source does not declare, and says why
        columns, error = {}, f"{type(exc).__name__}: {exc}"
    if error or not columns:
        return {**entry, "bound": False, "note": f"its source could not be read: {error or 'no columns'}"[:300]}
    by_lower = {str(c).lower(): str(c) for c in columns}
    key = by_lower.get(backing.primary_key.lower())
    if key is None:
        return {**entry, "bound": False,
                "note": f"its source has no column '{backing.primary_key}' to be the key — its columns: "
                        f"{', '.join(sorted(by_lower.values()))[:300]}"}
    entry["primary_key"] = key
    entry["columns"] = {str(c): str(t or "") for c, t in columns.items()}
    counts, note = measure_key(db, backing.from_clause("b"), key)
    if counts is None:
        entry.update({"bound": True, "note": "", "unique": None, "unique_note": note, "rows": None})
    else:
        rows, non_null, distinct = counts
        unique = non_null > 0 and distinct == non_null
        entry.update({"bound": True, "note": "", "unique": unique, "rows": rows,
                      "unique_note": (f"{key}: {distinct:,} distinct over {non_null:,} keyed rows of {rows:,}"
                                      + ("" if unique else " — NOT one row per object"))})
    return entry


def declared_entity(ov, graph: Optional[OntologyGraph]) -> Optional[OntologyEntity]:
    """The type a declaration override describes, rebuilt from its fields and what its bind recorded — no
    database. None when the declaration never bound (its source could not be read), so an unreadable
    declaration reaches no map, no page and no answer."""
    fields = ov.fields
    entry = ov.binding.get("backing") or {}
    spec = fields.get("backing") if isinstance(fields.get("backing"), dict) else {}
    if not fields.get("declared") or entry.get("bound") is not True or not spec:
        return None
    columns = entry.get("columns") if isinstance(entry.get("columns"), dict) else {}
    table, sql = str(spec.get("table") or "").strip(), str(spec.get("sql") or "").strip()
    key = str(entry.get("primary_key") or spec.get("primary_key") or "").strip()
    unique = entry.get("unique")
    backing = Backing(kind="table" if table else "query", table=table or None, sql=sql or None, primary_key=key,
                      verified=unique, rows=entry.get("rows"),
                      verification_note=str(entry.get("unique_note") or ("declared; key not yet counted" if unique is None else "")))
    properties = column_profiles(graph, table or None, columns, sql or None)
    for name, prop in properties.items():
        if name.lower() == key.lower():
            properties[name] = prop.model_copy(update={"is_primary_key": True, "semantic_type": prop.semantic_type or "key"})
    return OntologyEntity(
        id=ov.target_id, display_name=str(fields.get("display_name") or ov.target_id),
        description=str(fields.get("description") or ""), source_tables=[table] if table else [],
        identity_key=key, grain_verified=unique is True, backing=backing, domain=fields.get("domain") or None,
        entity_type=fields.get("entity_type") or "business_object", origin=fields.get("origin") or "human",
        properties=properties)


def register_entity(graph: OntologyGraph, entity: OntologyEntity) -> None:
    """Put a declared type into the graph's maps, beside the builder's — additive, never displacing a table
    another type already reads."""
    graph.entities[entity.id] = entity
    graph.entity_to_tables[entity.id] = list(entity.source_tables)
    for table in entity.source_tables:
        graph.table_to_entity.setdefault(table, entity.id)
    graph.relationship_index.setdefault(entity.id, [])


def backs_existing_type(graph: OntologyGraph, table: str) -> Optional[OntologyEntity]:
    """The type whose own rows are ``table``'s, if any — a second type over the same table is a duplicate, not a
    business entity; the way to one noun over that table is to rename or absorb the type that has it."""
    want = (table or "").strip().lower()
    bare = want.rsplit(".", 1)[-1]
    for e in graph.entities.values():
        b = e.backing
        own = (b.table if b is not None and b.kind == "table" and b.table else
               (e.source_tables[0] if e.source_tables else "")) or ""
        if own.lower() in (want, bare) or own.lower().rsplit(".", 1)[-1] == bare:
            return e
    return None


# ── links ───────────────────────────────────────────────────────────────────────────────────


def link_spec_problem(spec: Any) -> str:
    """Why a link cannot be declared as written, or "" — its shape only."""
    if not isinstance(spec, dict):
        return "a link is declared as a mapping with `from_entity`, `to_entity`, `name`, `from_column`, `to_column`"
    for field in ("from_entity", "to_entity"):
        if not str(spec.get(field) or "").strip():
            return f"a link names its `{field}`"
    if str(spec["from_entity"]).strip() == str(spec["to_entity"]).strip():
        return "a link joins two different types"
    if not LINK_NAME_PATTERN.match(str(spec.get("name") or "")):
        return "a link's name is its business verb in snake_case (placed_by, ships, belongs_to)"
    if spec.get("reverse_name") and not LINK_NAME_PATTERN.match(str(spec["reverse_name"])):
        return "a link's reverse name is snake_case"
    for field in ("from_column", "to_column"):
        if not COLUMN_PATTERN.match(str(spec.get(field) or "").strip()):
            return f"a link names the column it joins on each side in `{field}`"
    if spec.get("cardinality") and spec["cardinality"] not in CARDINALITIES:
        return f"a link's expected cardinality is one of {', '.join(CARDINALITIES)}, read from → to"
    if spec.get("origin") and spec["origin"] not in ORIGINS:
        return f"a declared link's origin is one of {', '.join(ORIGINS)}"
    return ""


def link_id(spec: dict) -> str:
    return f"{spec['from_entity']}_{spec['name']}_{spec['to_entity']}"


def link_fields(spec: dict) -> dict:
    out = {"declared": True, "from_entity": str(spec["from_entity"]).strip(), "to_entity": str(spec["to_entity"]).strip(),
           "name": str(spec["name"]).strip(), "from_column": str(spec["from_column"]).strip(),
           "to_column": str(spec["to_column"]).strip(), "origin": spec.get("origin") or "human"}
    if spec.get("cardinality"):
        out["cardinality"] = spec["cardinality"]
    if spec.get("reverse_name"):
        out["reverse_name"] = str(spec["reverse_name"]).strip()
    return out


def _has_column(entity: OntologyEntity, column: str) -> Optional[str]:
    low = column.lower()
    return next((k for k in (entity.properties or {}) if k.lower() == low), None)


def reverse_name_of(fields: dict) -> str:
    return fields.get("reverse_name") or f"{snake_name(fields['to_entity'])}_to_{snake_name(fields['from_entity'])}"


def link_problem_on_graph(graph: OntologyGraph, fields: dict) -> str:
    """Why this declaration cannot land on THIS graph, or "": both types exist, both columns are properties of
    their type's backing, the name is free on the from-side and the reverse name on the to-side (a path segment
    names one thing), and no link already joins the same two columns (name that one instead)."""
    a, b = graph.entities.get(fields["from_entity"]), graph.entities.get(fields["to_entity"])
    if a is None or b is None:
        missing = fields["from_entity"] if a is None else fields["to_entity"]
        return f"no object type '{missing}' in this ontology"
    for entity, column, side in ((a, fields["from_column"], "from"), (b, fields["to_column"], "to")):
        if _has_column(entity, column) is None:
            return (f"{entity.id} has no property '{column}' to join on ({side}_column) — its properties: "
                    f"{', '.join(sorted(entity.properties or {}))[:200]}")
    for r in graph.relationships.values():
        same = {r.from_entity, r.to_entity} == {a.id, b.id}
        cols = {(r.from_entity, r.from_col.lower()), (r.to_entity, r.to_col.lower())}
        if same and cols == {(a.id, fields["from_column"].lower()), (b.id, fields["to_column"].lower())}:
            return (f"{r.id} already joins {a.id}.{fields['from_column']} to {b.id}.{fields['to_column']} — name it "
                    f"with PUT /ontology/links/{r.id} instead of declaring a second link")
    name, reverse = fields["name"], reverse_name_of(fields)
    for entity, candidate, what in ((a, name, "name"), (b, reverse, "reverse name")):
        taken = taken_names(graph, entity, list(entity.bindings or []))
        if candidate.lower() in taken:
            return f"the link's {what} '{candidate}': {taken[candidate.lower()]}"
    return ""


def _count_side(db: Any, entity: OntologyEntity, column: str) -> Optional[tuple[int, int, int]]:
    col = quote_ident(_has_column(entity, column) or column)
    sql = f"SELECT COUNT(*), COUNT(o.{col}), COUNT(DISTINCT o.{col}) FROM {object_from(entity, 'o')}"
    try:
        result = db.execute("__link_probe__", sql)
    except Exception as exc:  # noqa: BLE001 — an unprobeable side is unmeasured, not refuted
        logger.debug("link probe raised on %s.%s: %s", entity.id, column, exc)
        return None
    if getattr(result, "error", None) or not getattr(result, "rows", None):
        return None
    try:
        return tuple(int(v) for v in result.rows[0][:3])  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def measure_declared_link(db: Any, graph: OntologyGraph, fields: dict) -> dict:
    """The `link` entry for a declared link: each side counted (rows, keyed rows, distinct keys — a side is "1"
    when its key is unique, ON-0a's law), the label that follows, and how many of the from-side's distinct keys
    the to-side holds. ALWAYS returns an entry; `bound` False when a side cannot be counted."""
    a, b = graph.entities[fields["from_entity"]], graph.entities[fields["to_entity"]]
    fa, tb = _has_column(a, fields["from_column"]) or fields["from_column"], _has_column(b, fields["to_column"]) or fields["to_column"]
    from_table = (a.backing.table if a.backing is not None and a.backing.kind == "table" and a.backing.table
                  else (a.source_tables[0] if a.source_tables else "")) or ""
    to_table = (b.backing.table if b.backing is not None and b.backing.kind == "table" and b.backing.table
                else (b.source_tables[0] if b.source_tables else "")) or ""
    entry: dict = {"from_table": from_table, "to_table": to_table, "from_column": fa, "to_column": tb}
    fc, tc = _count_side(db, a, fa), _count_side(db, b, tb)
    if fc is None or tc is None or not fc[1] or not tc[1]:
        which = [f"{a.id}.{fa}" for _ in [0] if fc is None or not fc[1]] + [f"{b.id}.{tb}" for _ in [0] if tc is None or not tc[1]]
        return {**entry, "bound": False, "measured_cardinality": None, "value_overlap": None,
                "note": f"not measurable: no non-null rows or no probe result on {', '.join(which)}"}
    side = lambda c: "1" if c[1] > 0 and c[2] == c[1] else "N"  # noqa: E731
    label = f"{side(fc)}:{side(tc)}"
    overlap_sql = (f"SELECT COUNT(DISTINCT a.{quote_ident(fa)}) FROM {object_from(a, 'a')} "
                   f"WHERE a.{quote_ident(fa)} IS NOT NULL AND a.{quote_ident(fa)} IN "
                   f"(SELECT b.{quote_ident(tb)} FROM {object_from(b, 'b')} WHERE b.{quote_ident(tb)} IS NOT NULL)")
    overlap: Optional[float] = None
    try:
        result = db.execute("__link_probe__", overlap_sql)
        if not getattr(result, "error", None) and getattr(result, "rows", None):
            overlap = round(int(result.rows[0][0]) / fc[2], 4) if fc[2] else 0.0
    except Exception as exc:  # noqa: BLE001
        logger.debug("link overlap probe raised on %s: %s", fields.get("name"), exc)
    entry.update({"bound": True, "measured_cardinality": label, "value_overlap": overlap,
                  "from_rows": fc[0], "from_non_null": fc[1], "from_distinct": fc[2],
                  "to_rows": tc[0], "to_non_null": tc[1], "to_distinct": tc[2],
                  "note": (f"measured {label}: {a.id}.{fa} {fc[2]:,} distinct over {fc[1]:,} non-null rows "
                           f"({side(fc)}); {b.id}.{tb} {tc[2]:,} distinct over {tc[1]:,} non-null rows ({side(tc)})"
                           + (f"; {overlap:.0%} of {a.id}'s keys are held by {b.id}" if overlap is not None else ""))})
    return entry


def declared_relationship(ov, graph: OntologyGraph) -> Optional[OntologyRelationship]:
    """The relationship a declaration override describes, rebuilt from its fields and its measurement — no
    database. None when either type is not in the graph or the link never bound (a side could not be counted):
    an unmeasured declared link would be refused by the compiler anyway, and a page must not draw an edge the
    data never confirmed."""
    fields, entry = ov.fields, ov.binding.get("link") or {}
    if not fields.get("declared") or entry.get("bound") is not True:
        return None
    a, b = graph.entities.get(fields.get("from_entity", "")), graph.entities.get(fields.get("to_entity", ""))
    if a is None or b is None:
        return None
    measured = entry.get("measured_cardinality") if entry.get("measured_cardinality") in CARDINALITIES else None
    expected = fields.get("cardinality") if fields.get("cardinality") in CARDINALITIES else None
    overlap = entry.get("value_overlap")
    note = ""
    if expected and measured and expected != measured:
        note = f"declared {expected}, measured {measured}"
    return OntologyRelationship(
        id=ov.target_id, from_entity=a.id, to_entity=b.id, verb=fields["name"].replace("_", " "),
        cardinality=measured or expected or "N:N",
        join_sql=f"{entry.get('from_table') or a.api_name}.{entry.get('from_column') or fields['from_column']} = "
                 f"{entry.get('to_table') or b.api_name}.{entry.get('to_column') or fields['to_column']}",
        from_table=str(entry.get("from_table") or ""), from_col=str(entry.get("from_column") or fields["from_column"]),
        to_table=str(entry.get("to_table") or ""), to_col=str(entry.get("to_column") or fields["to_column"]),
        join_confidence="verified" if (overlap or 0) > 0 else "inferred", nullable=False, value_overlap=overlap,
        measured_cardinality=measured, cardinality_note=note or str(entry.get("note") or ""),
        api_name=fields["name"], reverse_api_name=reverse_name_of(fields), name=fields["name"],
        origin=fields.get("origin") or "human")


def register_relationship(graph: OntologyGraph, rel: OntologyRelationship) -> None:
    graph.relationships[rel.id] = rel
    for a, b in ((rel.from_entity, rel.to_entity), (rel.to_entity, rel.from_entity)):
        index = graph.relationship_index.setdefault(a, [])
        if b not in index:
            index.append(b)


def with_declared_entities(graph: OntologyGraph, connection_id: str, schema_name: Optional[str]) -> OntologyGraph:
    """A working COPY of the raw graph with every declared entity registered — for the measure pass, which
    measures the raw cached graph (human overrides are overlaid at read time, never baked into the cache) and
    would otherwise not know a declared type exists when counting the bindings and links declared on it. The
    copy is never saved."""
    work = graph.model_copy(deep=True)
    try:
        from aughor.ontology.overrides import load_overrides
        overrides = load_overrides(connection_id, schema_name or "default")
    except Exception:  # noqa: BLE001
        return work
    for ov in overrides:
        if ov.target_kind == "entity" and ov.fields.get("declared") and ov.target_id not in work.entities:
            entity = declared_entity(ov, work)
            if entity is not None:
                register_entity(work, entity)
    return work


def measure_override_links(connection_id: str, schema_name: Optional[str], db: Any, graph: OntologyGraph) -> list[dict]:
    """Re-measure every declared link in the overrides tree against the objects it joins and record the counts on
    its entry, so the overlay carries them at read time. Best-effort; returns one row per link measured."""
    out: list[dict] = []
    try:
        from aughor.ontology.overrides import load_overrides, save_override
        overrides = load_overrides(connection_id, schema_name or "default")
    except Exception:  # noqa: BLE001
        return out
    for ov in overrides:
        if ov.target_kind != "link" or not ov.fields.get("declared"):
            continue
        if ov.fields.get("from_entity") not in graph.entities or ov.fields.get("to_entity") not in graph.entities:
            continue
        entry = measure_declared_link(db, graph, ov.fields)
        ov.binding["link"] = entry
        try:
            save_override(connection_id, schema_name or "default", ov)
        except Exception as exc:  # noqa: BLE001
            logger.debug("declared link measurement not saved for %s: %s", ov.target_id, exc)
        out.append({"link": ov.target_id, "measured_cardinality": entry.get("measured_cardinality"),
                    "value_overlap": entry.get("value_overlap"), "bound": entry.get("bound"), "note": entry.get("note")})
    return out
