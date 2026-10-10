"""Arc OC-8 — doors for builders: what the published ontology lets an outside program read and propose, generated.

The ontology was a contract only for the platform's own screens: an outside script had no way to learn what an Order
holds, which segments name late ones, or what *Flag for review* takes — short of reading the platform's own types. From
the release a scope serves, this module writes the contract out in the forms a builder already reads:

* a JSON Schema for each entity's objects (its properties, its key, the segments a listing may name) and for each
  declared action's parameters (what a proposal must carry — an object parameter as ``<type>:<key>``);
* TypeScript declarations of the same, for a builder who writes TypeScript;
* stamped with the release they were generated from (`<connection>/<schema>@<n>`), so a program that pinned one can
  tell when the contract moved.

Decision (d), as decided: schemas and types and one MCP proposal tool per declared action (`aughor/mcp/server.py`), no
client library — a program lists objects and PROPOSES actions through the versioned doors (`/objects/v1/…`); a person
approves every one. Nothing here runs code, and nothing reads the warehouse: generation is a pure function of the graph.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from aughor.ontology.models import KineticAction, OntologyEntity, OntologyGraph

#: The JSON Schema dialect every generated schema declares.
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _json_type(data_type: str) -> dict:
    """A warehouse type as a JSON Schema type. A type this does not recognise is a string — what the door returns it as."""
    t = (data_type or "").upper()
    if "BOOL" in t:
        return {"type": "boolean"}
    if any(w in t for w in ("INT", "BIGINT", "SMALLINT", "TINYINT")) and "INTERVAL" not in t:
        return {"type": "integer"}
    if any(w in t for w in ("FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL", "NUMBER", "BIGNUMERIC")):
        return {"type": "number"}
    if t.startswith("DATE") and "TIME" not in t:
        return {"type": "string", "format": "date"}
    if "TIMESTAMP" in t or "DATETIME" in t:
        return {"type": "string", "format": "date-time"}
    return {"type": "string"}


def _segments(graph: OntologyGraph, entity: OntologyEntity) -> list[str]:
    """Every segment a listing of ``entity`` may name: its own, and the ones its processes and rules derive (late,
    overdue, a rule's objects)."""
    from aughor.ontology.derived import derived_for, overdue_derivations
    names = list((entity.segments or {}).keys())
    names += [d.name for d in derived_for(graph, entity).segments if d.usable]
    names += [d.name for p in (graph.processes or {}).values() for d in overdue_derivations(p)
              if d.entity == entity.id and d.usable]
    return sorted(dict.fromkeys(names))


def entity_schema(graph: OntologyGraph, entity: OntologyEntity, release: str = "") -> dict:
    """The JSON Schema of one object of ``entity``: each property with its type and description, the key required."""
    key = ""
    props: dict[str, Any] = {}
    for name, prop in (entity.properties or {}).items():
        schema = {**_json_type(prop.data_type), "description": prop.description or prop.display_name or name}
        if not prop.is_primary_key:
            schema = {"anyOf": [schema, {"type": "null"}], "description": schema.pop("description")}
        else:
            key = name
        props[name] = schema
    return {"$schema": DIALECT, "$id": f"aughor:{release or 'unreleased'}:entity:{entity.id}",
            "title": entity.display_name or entity.id, "description": entity.description or "",
            "type": "object", "properties": props, "required": [key] if key else [],
            "x-aughor": {"entity": entity.id, "object_type": entity.api_name, "key": key,
                         "segments": _segments(graph, entity), "release": release,
                         **({"held_by_the_platform": True} if entity.backing is not None
                            and entity.backing.kind == "platform" else {})}}


def action_schema(action: KineticAction, release: str = "") -> dict:
    """The JSON Schema of a PROPOSAL of ``action``: its parameters, an object parameter as ``<type>:<key>``."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in action.params:
        if p.kind == "object":
            ref = p.object_type or "object"
            schema: dict = {"type": "string", "pattern": f"^{re.escape(ref)}:.+$",
                            "description": (p.description or f"the {ref} this acts on")
                                           + f" — written {ref}:<key>, as a listing names it"}
        else:
            schema = {**_json_type(p.data_type), "description": p.description or p.display_name or p.name}
            if p.default_value not in (None, ""):
                schema["default"] = p.default_value
        props[p.name] = schema
        if p.required:
            required.append(p.name)
    return {"$schema": DIALECT, "$id": f"aughor:{release or 'unreleased'}:action:{action.id}",
            "title": action.display_name or action.id, "description": action.description or "",
            "type": "object", "properties": props, "required": required, "additionalProperties": False,
            "x-aughor": {"action": action.id, "kind": action.kind, "risk": action.risk,
                         "object_type": action.object_type or "", "creates": action.creates or "",
                         "sets": [e.property for e in action.edits], "release": release,
                         "proposes_only": True}}


def ontology_contract(graph: OntologyGraph, release: str = "") -> dict:
    """The whole contract a scope serves: every entity's and every declared action's schema, stamped with the
    release. Entities an organisation marked as parts are included (a listing may name them)."""
    return {"release": release or "", "connection_id": graph.connection_id, "schema_name": graph.schema_name,
            "entities": {e.id: entity_schema(graph, e, release) for e in sorted(graph.entities.values(), key=lambda e: e.id)},
            "actions": {a.id: action_schema(a, release) for a in sorted(graph.declared_actions(), key=lambda a: a.id)}}


# ── TypeScript ───────────────────────────────────────────────────────────────────────────────────────────────────────

_TS_RESERVED = {"break", "case", "class", "const", "default", "delete", "do", "else", "enum", "export", "extends",
                "false", "for", "function", "if", "import", "in", "new", "null", "return", "super", "switch", "this",
                "throw", "true", "try", "typeof", "var", "void", "while", "with"}


def _pascal(name: str) -> str:
    out = "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", name) if part)
    return out if out and not out[0].isdigit() else f"T{out}"


def _ts_key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name) and name not in _TS_RESERVED else repr(name)


def _ts_type(schema: dict) -> str:
    if "anyOf" in schema:
        return " | ".join(_ts_type(s) for s in schema["anyOf"])
    return {"integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(
        str(schema.get("type")), "string")


def _ts_doc(text: str, indent: str = "") -> str:
    text = " ".join(str(text or "").split()).replace("*/", "* /")
    return f"{indent}/** {text} */\n" if text else ""


def typescript(contract: dict) -> str:
    """TypeScript declarations of a contract: an interface per entity, a union of each entity's segments, a params
    interface per declared action, and the release they were generated from. Declarations only — nothing to run."""
    lines = [f"// Generated by Aughor from {contract.get('release') or 'an unreleased ontology'} "
             f"({contract.get('connection_id')}/{contract.get('schema_name')}). Do not edit — regenerate from "
             "GET /ontology/v1/types.d.ts.\n",
             f"export const RELEASE = {contract.get('release', '')!r} as const;\n"]
    for eid, schema in contract.get("entities", {}).items():
        name = _pascal(eid)
        lines.append(_ts_doc(schema.get("description") or schema.get("title")))
        lines.append(f"export interface {name} {{\n")
        for prop, ps in schema["properties"].items():
            lines.append(_ts_doc(ps.get("description"), "  "))
            lines.append(f"  {_ts_key(prop)}: {_ts_type(ps)};\n")
        lines.append("}\n")
        segments = schema["x-aughor"]["segments"]
        lines.append(f"export type {name}Segment = {' | '.join(repr(s) for s in segments) or 'never'};\n")
    ids = list(contract.get("actions", {}))
    for aid, schema in contract.get("actions", {}).items():
        lines.append(_ts_doc(f"{schema.get('title')} — {schema.get('description') or ''} "
                             "Proposed through POST /objects/v1/actions/{id}/propose; a person approves it."))
        lines.append(f"export interface {_pascal(aid)}Params {{\n")
        required = set(schema.get("required") or [])
        for prop, ps in schema["properties"].items():
            lines.append(_ts_doc(ps.get("description"), "  "))
            lines.append(f"  {_ts_key(prop)}{'' if prop in required else '?'}: {_ts_type(ps)};\n")
        lines.append("}\n")
    lines.append(f"export type ActionId = {' | '.join(repr(a) for a in ids) or 'never'};\n")
    return "".join(lines)


def validate_params(schema: dict, params: dict) -> Optional[str]:
    """Why ``params`` do not fit an action's schema, or None — the parameters no other parameter check would name
    (an unknown name, a missing required one, an object reference of the wrong type). The executor's own coercion and
    criteria still run when the proposal is accepted."""
    props = schema.get("properties") or {}
    unknown = sorted(set(params) - set(props))
    if unknown:
        return f"{schema.get('title')} takes no parameter {unknown[0]!r} — it takes {', '.join(props) or 'none'}"
    missing = [r for r in schema.get("required") or [] if params.get(r) in (None, "")]
    if missing:
        return f"{schema.get('title')} needs {missing[0]!r}"
    for name, ps in props.items():
        value = params.get(name)
        if value in (None, "") or "pattern" not in ps:
            continue
        if not re.match(ps["pattern"], str(value)):
            return f"{name!r} names an object as {ps['pattern'].strip('^$').replace(chr(92), '')} — got {value!r}"
    return None
