"""2026-09-22 — typed properties mapped to expressions (ON-1b's deferred half).

A person maps a property to a SQL expression over the type's own row. The shape is checked here (a name that is
free, an expression that parses, holds no subquery, no aggregate and no window, and reads the backing's own columns
only), the expression is VERIFIED by running it on one row at the door, and the overlay rebuilds the property from
the recorded verdict without a database — the same three-way law bindings live under.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from aughor.ontology.models import ExpressionProperty, OntologyEntity, OntologyGraph

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ROLES = ("measure", "dimension")


def normalized_expression(raw: dict) -> dict:
    """One expression as the overrides tree stores it. Idempotent."""
    role = str(raw.get("semantic_type") or "measure").strip().lower()
    return {"expression": str(raw.get("expression") or "").strip(), "semantic_type": role,
            "unit": str(raw.get("unit") or "").strip(), "description": str(raw.get("description") or "").strip()}


def expression_problem(entity: OntologyEntity, name: str, spec: dict, graph: Optional[OntologyGraph] = None) -> str:
    """Why this expression cannot be a property of ``entity`` as written, or ""."""
    import sqlglot
    from sqlglot import exp
    from aughor.ontology.bindings import taken_names
    if not _NAME.match(name or ""):
        return f"'{name}' is not a property name — a lowercase letter, then lowercase letters, digits or underscores"
    taken = taken_names(graph, entity, list(entity.bindings or []))
    if name.lower() in taken and name not in (entity.expressions or {}):
        return f"{taken[name.lower()]} — a path segment names one thing"
    expression = str(spec.get("expression") or "").strip()
    if not expression:
        return "an expression property is a SQL expression over the type's own row — none was given"
    if spec.get("semantic_type") not in ROLES:
        return f"semantic_type is one of {', '.join(ROLES)}"
    try:
        node = sqlglot.parse_one(f"SELECT {expression} FROM _t", read="duckdb").expressions[0]
    except Exception as exc:  # noqa: BLE001 — an unparseable expression is a refusal, never a guess
        return f"the expression could not be parsed ({str(exc)[:120]})"
    if node.find(exp.Select) is not None:
        return "the expression holds a subquery; a property is a flat expression over the row"
    if node.find(exp.AggFunc) is not None:
        return "the expression holds an aggregate — a property is per row; an aggregate belongs to a metric"
    if node.find(exp.Window) is not None:
        return "the expression holds a window function; a property is a flat expression over the row"
    own = {k.lower() for k in (entity.properties or {}) if k not in (entity.expressions or {})}
    for col in node.find_all(exp.Column):
        if col.name.lower() not in own:
            return (f"'{col.name}' is not a column of {entity.id}'s own rows — an expression reads the backing's "
                    "columns only (a binding's column is not read here)")
    return ""


def probe_expression(db: Any, graph: OntologyGraph, entity: OntologyEntity, expression: str) -> dict:
    """Run the expression on ONE row of the type's own table: ``{bound, note, sample}``."""
    from aughor.ontology.validator import _check_value, _entity_table, _probe
    table = _entity_table(graph, entity.id) if entity.source_tables or entity.backing is not None else ""
    if not table:
        return {"bound": False, "note": f"{entity.id} has no source table to read the expression on", "sample": None}
    ok, err, val = _probe(db, f"SELECT ({expression}) AS v FROM {table} LIMIT 1")
    if not ok:
        return {"bound": False, "note": f"did not execute: {err}", "sample": None}
    sane, note = _check_value(val)
    return {"bound": bool(sane), "note": "" if sane else note, "sample": None if val is None else str(val)[:80]}


def declared_expressions(entity: OntologyEntity, specs: dict, verdicts: Optional[dict]) -> dict[str, ExpressionProperty]:
    """The expression properties an override declares, each carrying the verdict the door recorded — rebuilt on
    every read without a database. One that never bound reads `verified: False` and no reader follows it."""
    out: dict[str, ExpressionProperty] = {}
    verdicts = verdicts or {}
    for name, raw in (specs or {}).items():
        if not isinstance(raw, dict):
            continue
        spec = normalized_expression(raw)
        v = verdicts.get(name) or {}
        verified = True if v.get("bound") else (False if "bound" in v else None)
        out[name] = ExpressionProperty(expression=spec["expression"], semantic_type=spec["semantic_type"],
                                       unit=spec["unit"], description=spec["description"], verified=verified,
                                       note=str(v.get("note") or ("declared by a person; not yet verified"
                                                                  if verified is None else "")))
    return out
