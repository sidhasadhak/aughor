"""Arc OC-3 — one contract: the stores that carry meaning, keyed to the ontology's ids (ROADMAP §3.56).

The study that opened Arc OC found meaning kept in about nine stores keyed to tables and columns — the metric registry,
the glossary, the vocabulary, trusted queries, column config, monitors, cards, automation triggers and the Record. The
ontology names the business; those stores did not point at it, so a release could only guess what a change touched,
and nothing could read an approved metric as *the* measure of an entity's objects.

This module starts with the store that already half-carries the key: a metric's grain names its table. For each metric
it proposes the entity it measures — from the grain's table, else the one entity its tables (or its statement's FROM)
are backed by — and says why, or why none could be chosen. A proposal is never stored and nothing reads it as the
metric's meaning: a person confirms the entity through `PUT /metrics/{name}/entity`, and only then is the metric keyed
(`MetricDefinition.entity`). `keyed_counts` is the census's reading of how far every store is keyed — the arc's OC-3
receipt is that share moving from its baseline of zero.
"""
from __future__ import annotations

from typing import Any


def _bare(table: str) -> str:
    return str(table or "").strip().strip("`\"").lower().rsplit(".", 1)[-1]


def _grain_table(m: Any) -> str:
    """The table a metric's grain names — `order_items.created_at` and `thelook.order_items.created_at` both name
    `order_items`; a bare column names none."""
    parts = [p for p in str(getattr(m, "time_column", "") or "").strip().split(".") if p]
    return _bare(parts[-2]) if len(parts) >= 2 else ""


def _grain_column(m: Any) -> str:
    parts = [p for p in str(getattr(m, "time_column", "") or "").strip().split(".") if p]
    return parts[-1] if parts else ""


def _parsed(sql: str, dialect: Any):
    import sqlglot
    try:
        return sqlglot.parse_one(sql or "", read=dialect)
    except Exception:  # noqa: BLE001 — an expression-only metric (`COUNT(id)`) is not a statement
        return None


def statement_tables(sql: str) -> set[str]:
    """The tables a metric's statement reads, by parsing it — CTE names are not tables. Empty when it does not parse.
    Backticked names parse as BigQuery; anything else as the default dialect."""
    from sqlglot import exp
    tree = _parsed(sql, "bigquery") or _parsed(sql, None)
    if tree is None:
        return set()
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {_bare(t.name) for t in tree.find_all(exp.Table)
            if t.name and not (not t.args.get("db") and t.name.lower() in ctes)}


def _entity_of(graph: Any, table: str) -> str:
    if not table:
        return ""
    for t, eid in (graph.table_to_entity or {}).items():
        if _bare(t) == table:
            return eid
    for eid, e in graph.entities.items():
        if any(_bare(s) == table for s in e.source_tables):
            return eid
    return ""


def propose_metric_entity(m: Any, graph: Any) -> dict:
    """``{entity, property, why, candidates}`` — the entity a metric measures, as its own declaration says it: the
    grain's table first (the table a range filters, so the objects that are counted), else the one entity every table
    it names — or its statement reads — is backed by. ``entity`` is "" when none can be chosen, with why."""
    if graph is None:
        return {"entity": "", "property": "", "why": "no ontology is built for this scope", "candidates": []}
    grain = _grain_table(m)
    entity = _entity_of(graph, grain)
    if entity:
        column = _grain_column(m)
        prop = column if column in (graph.entities[entity].properties or {}) else ""
        return {"entity": entity, "property": prop, "candidates": [entity],
                "why": f"its grain, {m.time_column}, is a date of {entity}'s table {grain}"}
    tables = {_bare(t) for t in (getattr(m, "tables", None) or []) if t} or statement_tables(getattr(m, "sql", ""))
    backed = sorted({e for e in (_entity_of(graph, t) for t in tables) if e})
    if len(backed) == 1:
        source = "the table it names" if getattr(m, "tables", None) else "the table its statement reads"
        column = _grain_column(m)
        prop = column if column in (graph.entities[backed[0]].properties or {}) else ""
        return {"entity": backed[0], "property": prop, "candidates": backed,
                "why": f"{source} ({', '.join(sorted(tables))}) backs {backed[0]}"
                       + (f", and its grain {column} is one of its dates" if prop else "; it names no dated grain")}
    if backed:
        return {"entity": "", "property": "", "candidates": backed,
                "why": f"its tables back {len(backed)} entities ({', '.join(backed)}) and its grain names none of "
                       "them — a person says which one it measures"}
    return {"entity": "", "property": "", "candidates": [],
            "why": "none of its tables backs an entity on this scope" if tables else "it names no table"}


def metric_keys(connection_id: str, schema_name: str, graph: Any) -> list[dict]:
    """Every metric that applies to the scope, with its confirmed entity, the proposal and why."""
    from aughor.semantic.metrics import list_metrics
    out = []
    for m in list_metrics(connection_id=connection_id, schema_name=schema_name):
        proposal = propose_metric_entity(m, graph)
        out.append({"name": m.name, "label": m.label, "status": m.status, "entity": m.entity or "",
                    "confirmed_by": m.entity_confirmed_by or "", "proposal": proposal,
                    "agrees": bool(m.entity) and m.entity == proposal["entity"]})
    return out


# ── the vocabulary: words people use, keyed to what they name ────────────────────────────────────────────────────────
#
# A vocabulary entry (`ontology.vocabulary.Synonym`) named a table, `table.column`, a metric or a term — the ontology's
# entities and properties it could not name, though they are what a person means by "late orders" or "sales value".
# An entry may now name an ENTITY (`Order`) or a PROPERTY (`Order.status`); the readers that work in tables and columns
# — the schema linker, the SQL writer's synonym block — read it through `subject_columns`, at the moment they read it,
# so a re-pointed binding moves the entry with it. Table and column entries are proposed a key the way a metric is
# (`propose_synonym_key`): never stored until a person confirms it (`PUT /ontology/vocabulary/key`).

ONTOLOGY_KINDS = ("entity", "property")


def _entity_named(graph: Any, name: str) -> Any:
    want = str(name or "").strip().lower()
    return next((e for e in graph.entities.values() if want in (e.id.lower(), str(e.api_name or "").lower())), None)


def subject_columns(graph: Any, kind: str, subject: str) -> Any:
    """``(table, column)`` an entity or property entry is read from on ``graph`` — column "" for an entity — or None
    when the graph cannot say: no graph, an unknown entity or property, a query backing (a SELECT has no table)."""
    if graph is None or kind not in ONTOLOGY_KINDS:
        return None
    entity_name, _, prop = str(subject or "").partition(".") if kind == "property" else (subject, "", "")
    e = _entity_named(graph, entity_name)
    if e is None:
        return None
    b = e.backing
    if b is not None and b.kind == "query":
        return None
    table = (b.table if b is not None and b.table else "") or (e.source_tables[0] if e.source_tables else "")
    if kind == "entity":
        return (table, "") if table else None
    from aughor.ontology.bindings import column_of, property_binding
    bound = property_binding(e, prop)
    if bound is not None:
        return (bound.table, column_of(bound, prop)) if getattr(bound, "table", "") else None
    hit = next((k for k in (e.properties or {}) if k.lower() == prop.strip().lower()), None)
    return (table, hit) if hit and table else None


def propose_synonym_key(kind: str, subject: str, graph: Any) -> dict:
    """``{kind, subject, why}`` — the entity or property a table or column entry names on ``graph``, or kind "" with
    why none: the one entity a table backs, and the property of it that reads the column."""
    if kind in ONTOLOGY_KINDS:
        return {"kind": kind, "subject": subject, "why": "keyed"}
    if graph is None:
        return {"kind": "", "subject": "", "why": "no ontology is built for this scope"}
    if kind == "table":
        entity = _entity_of(graph, _bare(subject))
        return ({"kind": "entity", "subject": entity, "why": f"its table, {_bare(subject)}, backs {entity}"} if entity
                else {"kind": "", "subject": "", "why": f"no entity is backed by {_bare(subject)}"})
    if kind == "column":
        table, _, column = str(subject).rpartition(".")
        entity = _entity_of(graph, _bare(table))
        if not entity:
            return {"kind": "", "subject": "", "why": f"no entity is backed by {_bare(table) or 'its table'}"}
        e = graph.entities[entity]
        name = next((k for k in (e.properties or {}) if k.lower() == column.lower()), None)
        if name is None:
            from aughor.ontology.bindings import column_of
            name = next((p for b in e.bindings or [] if _bare(b.table) == _bare(table)
                         for p in b.properties if column_of(b, p).lower() == column.lower()), None)
        return ({"kind": "property", "subject": f"{entity}.{name}", "why": f"{entity} reads {column} as {name}"} if name
                else {"kind": "", "subject": "", "why": f"{entity} has no property that reads {column}"})
    return {"kind": "", "subject": "", "why": f"a {kind} is not a table or a column — nothing to key it to"}


def vocabulary_keys(connection_id: str, graph: Any) -> list[dict]:
    """Every vocabulary entry on the connection that names a table, a column, an entity or a property — keyed or with
    the key it is proposed, and the table and column a keyed one reads now."""
    from aughor.ontology.vocabulary import synonyms_for
    out = []
    for s in synonyms_for(connection_id):
        if s.subject_kind not in ("table", "column", *ONTOLOGY_KINDS):
            continue
        keyed = s.subject_kind in ONTOLOGY_KINDS
        reads = subject_columns(graph, s.subject_kind, s.subject_id) if keyed else None
        out.append({**s.to_dict(), "keyed": keyed, "proposal": propose_synonym_key(s.subject_kind, s.subject_id, graph),
                    "reads": {"table": reads[0], "column": reads[1]} if reads else None})
    return out


def entity_table(connection_id: str, entity: str) -> str:
    """The table an entity's objects are read from on the connection's served ontology — what a trigger keyed to the
    entity probes. "" when the entity is unknown or backed by a query (a SELECT has no table version to watch)."""
    from aughor.routers.ontology import served_ontology_graph
    graph = served_ontology_graph(connection_id, None)
    if graph is None:
        return ""
    want = str(entity or "").strip().lower()
    e = next((x for x in graph.entities.values() if want in (x.id.lower(), x.api_name.lower())), None)
    if e is None:
        return ""
    b = e.backing
    if b is not None and b.kind == "query":
        return ""
    return (b.table if b is not None and b.table else "") or (e.source_tables[0] if e.source_tables else "")


def keyed_counts() -> dict:
    """How far each store that carries meaning is keyed to the ontology — the census's `keyed` section. A store that
    cannot be read is said, never counted as zero."""
    out: dict[str, Any] = {}
    try:
        from aughor.semantic.metrics import list_metrics
        metrics = [m for m in list_metrics() if m.status != "deprecated"]
        out["metrics"] = {"of": len(metrics), "n": sum(1 for m in metrics if m.entity)}
    except Exception as exc:  # noqa: BLE001
        out["metrics"] = None
        out.setdefault("unread", {})["metrics"] = str(exc)[:200]
    try:
        from aughor.ontology.vocabulary import connections_with_synonyms, synonyms_for
        named = [x for c in connections_with_synonyms() for x in synonyms_for(c)
                 if x.subject_kind in ("table", "column", *ONTOLOGY_KINDS)]
        out["vocabulary"] = {"of": len(named), "n": sum(1 for x in named if x.subject_kind in ONTOLOGY_KINDS)}
    except Exception as exc:  # noqa: BLE001
        out["vocabulary"] = None
        out.setdefault("unread", {})["vocabulary"] = str(exc)[:200]
    try:
        from aughor.automations.store import list_automations
        watches = [c for a in list_automations() for c in a.conditions if c.kind in ("source_change", "entity_appears")]
        out["triggers"] = {"of": len(watches), "n": sum(1 for c in watches if c.config.get("entity"))}
    except Exception as exc:  # noqa: BLE001
        out["triggers"] = None
        out.setdefault("unread", {})["triggers"] = str(exc)[:200]
    return out
