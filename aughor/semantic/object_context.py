"""ON-3 — what surrounds one object: its metrics, the findings that cite it, the notes on its row, and
the declared actions that take it (ROADMAP §3.15's Standard Object View).

Each panel is MEASURED, never inferred:

* **Metrics** — every verified metric on the object's own type, and on each type it reaches through a
  usable to-many link, compiled by ON-2 with this object as the filter
  (`objects(T).filter(key = this).measure(metric)`): a customer's revenue across its orders is a
  number the compiler vouches for, not a sentence about customers.
* **Findings** — nothing stores which object a finding is about, so citation is read off the SQL: an
  exploration finding or an answer receipt cites this object when its WHERE clause filters the
  object's key — or a column a link joins to that key — by this very value
  (`extract_filter_literals`). A finding about the type in aggregate does not cite the object and is
  never listed as though it did.
* **Notes** — the overlay's row-keyed edits (`table.column#key=value`) on this object's row.
* **Actions** — the governed actions a human declared that are owned by the object's type or carry a
  parameter named for its key, with that parameter PRE-FILLED. Offered here, never run from here:
  acting on objects is ON-4.
"""
from __future__ import annotations

from typing import Any

from aughor.ontology.models import OntologyEntity, OntologyGraph, snake_name
from aughor.semantic.object_instances import ObjectInstance
from aughor.semantic.object_query import (
    ObjectQueryRefused,
    compile_object_query,
    find_object_type,
    link_problem,
    metric_on,
    object_links,
)

_MAX_METRICS = 8
_MAX_FINDINGS = 12
_SCAN_RECEIPTS = 300


def _bare(table: str) -> str:
    return (table or "").strip().strip('"').lower().rsplit(".", 1)[-1]


def _entity_tables(entity: OntologyEntity) -> set[str]:
    names = {_bare(t) for t in entity.source_tables}
    if entity.backing is not None and entity.backing.table:
        names.add(_bare(entity.backing.table))
    return {n for n in names if n}


def _type_word(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _values(instance: ObjectInstance) -> dict[str, Any]:
    return {str(p["name"]).lower(): p["value"] for p in instance.properties}


def identity_columns(graph: OntologyGraph, entity: OntologyEntity, instance: ObjectInstance) -> dict:
    """(bare table, column) → the value that names THIS object in that column: its own key, and every
    column a link from its key joins to (`order_items.order_id` names an Order). A link from a column
    that is not the key would name every object sharing the value, so it names none."""
    out = {(table, instance.key.lower()): instance.pk for table in _entity_tables(entity)}
    for link in object_links(graph, entity):
        if link.local_col.lower() != instance.key.lower() or link_problem(link):
            continue
        for table in _entity_tables(link.target):
            out[(table, link.remote_col.lower())] = instance.pk
    return out


def object_metrics(graph: OntologyGraph, db: Any, entity: OntologyEntity, instance: ObjectInstance,
                   *, dialect: str = "duckdb") -> list[dict]:
    values = _values(instance)
    scopes = [(entity, instance.key, instance.pk, "")]
    for link in object_links(graph, entity):
        if link.to_one or link_problem(link):
            continue
        local = values.get(link.local_col.lower())
        if local is not None:
            scopes.append((link.target, link.remote_col, str(local), link.name))
    out: list[dict] = []
    for target, column, value, via in scopes:
        for metric_id, metric in sorted(graph.metrics.items()):
            if len(out) >= _MAX_METRICS:
                return out
            if not metric.verified or not metric_on(metric, target):
                continue
            row = {"metric": metric_id, "display_name": metric.display_name or metric_id, "unit": metric.unit,
                   "on": target.api_name, "via": via}
            query = {"object_type": target.api_name, "filters": [{"path": column, "value": value}],
                     "measures": [{"name": "value", "metric": metric_id}]}
            try:
                compiled = compile_object_query(query, graph, dialect=dialect, fiscal_start_month=1)
            except ObjectQueryRefused as exc:
                out.append({**row, "refused": exc.reason})
                continue
            result = db.execute("object_metric", compiled.sql)
            if getattr(result, "error", None):
                out.append({**row, "error": str(result.error)[:300], "sql": compiled.sql})
                continue
            first = (result.rows or [[None]])[0]
            out.append({**row, "value": first[0] if first else None, "sql": compiled.sql})
    return out


def object_findings(connection_id: str, schema_name: str, graph: OntologyGraph, entity: OntologyEntity,
                    instance: ObjectInstance) -> list[dict]:
    from aughor.kernel.errors import tolerate
    from aughor.sql.join_guard import extract_filter_literals

    identity = identity_columns(graph, entity, instance)

    def cites(sql: Any) -> str:
        for table, column, literal, op in extract_filter_literals(str(sql or "")):
            want = identity.get((_bare(table), column.lower()))
            if op in ("=", "IN") and want is not None and str(literal) == str(want):
                return f"{_bare(table)}.{column} {op} '{literal}'"
        return ""

    cited: list[dict] = []
    try:
        from aughor.explorer.store import get_findings
        seen: set = set()
        for key in dict.fromkeys([connection_id] + ([f"{connection_id}__{schema_name}"] if schema_name else [])):
            for finding in get_findings(key):
                if finding.get("id") in seen:
                    continue
                seen.add(finding.get("id"))
                matched = cites(finding.get("sql"))
                if matched:
                    cited.append({"kind": "finding", "id": finding.get("id"), "text": finding.get("finding", ""),
                                  "domain": finding.get("domain", ""), "matched": matched})
    except Exception as exc:  # noqa: BLE001
        tolerate(exc, "object page: exploration findings are best-effort", counter="objects.findings_scan")
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.ontology.context_graph_build import RECEIPT_KINDS
        for artifact in Ledger.default().artifacts_of_kind(list(RECEIPT_KINDS), conn_id=connection_id,
                                                           limit=_SCAN_RECEIPTS):
            payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
            matched = cites(payload.get("sql"))
            if matched:
                cited.append({"kind": "answer", "id": artifact.get("id"),
                              "text": payload.get("headline") or payload.get("question", ""),
                              "question": payload.get("question", ""), "at": artifact.get("created_at"),
                              "matched": matched})
    except Exception as exc:  # noqa: BLE001
        tolerate(exc, "object page: answer receipts are best-effort", counter="objects.receipts_scan")
    return cited[:_MAX_FINDINGS]


def object_notes(connection_id: str, entity: OntologyEntity, instance: ObjectInstance) -> list[dict]:
    from aughor.kernel.errors import tolerate
    try:
        from aughor.actions.overlay import edits_for_connection
        from aughor.org.context import current_org_id
        tables = _entity_tables(entity)
        out = []
        for edit in edits_for_connection(connection_id, current_org_id() or ""):
            # ON-4 — a property edit is shown as the object's property, with its provenance, not as a note.
            if _bare(edit.table) not in tables or not edit.row_key or edit.kind == "property":
                continue
            if (edit.key_column or edit.column).lower() == instance.key.lower() and str(edit.row_key) == instance.pk:
                out.append({"column": edit.column, "kind": edit.kind, "body": edit.body, "source": edit.source,
                            "at": edit.created_at})
        return out
    except Exception as exc:  # noqa: BLE001
        tolerate(exc, "object page: overlay notes are best-effort", counter="objects.notes_scan")
        return []


def object_actions(graph: OntologyGraph, entity: OntologyEntity, instance: ObjectInstance) -> list[dict]:
    names = {instance.key.lower(), f"{entity.api_name}_id", f"{snake_name(entity.id)}_id", f"{entity.api_name}_key"}
    words = (_type_word(entity.api_name), _type_word(entity.id))
    out = []
    for action in graph.declared_actions():
        owned = (action.entity or "").lower() in (entity.id.lower(), entity.api_name.lower()) or (
            bool(action.object_type) and _type_word(action.object_type) in words)
        params, prefilled = [], []
        for param in action.params:
            value = param.default_value
            if param.kind == "object":
                # ON-4 — an object parameter of this object's type takes this very object.
                if _type_word(param.object_type) in words:
                    value = f"{param.object_type}:{instance.pk}"
                    prefilled.append(param.name)
            elif param.name.lower() in names:
                value = instance.pk
                prefilled.append(param.name)
            params.append({"name": param.name, "display_name": param.display_name or param.name,
                           "data_type": param.data_type, "required": param.required,
                           "description": param.description, "value": value,
                           "kind": param.kind, "object_type": param.object_type})
        if not owned and not prefilled:
            continue
        out.append({"id": action.id, "display_name": action.display_name or action.id,
                    "description": action.description, "kind": action.kind, "risk": action.risk,
                    "params": params, "prefilled": prefilled,
                    "why": f"takes {', '.join(prefilled)}" if prefilled else f"declared on {entity.id}"})
    return out


def object_context(graph: OntologyGraph, db: Any, connection_id: str, schema_name: str, instance: ObjectInstance,
                   *, dialect: str = "duckdb") -> dict:
    """The four panels around one object."""
    entity = find_object_type(graph, instance.type_id)
    return {"metrics": object_metrics(graph, db, entity, instance, dialect=dialect),
            "findings": object_findings(connection_id, schema_name, graph, entity, instance),
            "notes": object_notes(connection_id, entity, instance),
            "actions": object_actions(graph, entity, instance)}
