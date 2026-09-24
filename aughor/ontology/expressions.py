"""2026-09-22 — typed properties mapped to expressions (ON-1b's deferred half).

A person maps a property to a SQL expression over the type's row. The shape is checked here (a name that is free, an
expression that parses and holds no subquery, no aggregate and no window), the expression is VERIFIED against the data
at the door, and the overlay rebuilds the property from the recorded verdict without a database — the same three-way
law bindings live under.

PENDING item 27 — an expression read the backing's own columns only and was verified on ONE row. It now reads every
name the object compiler reads (a binding's property — a linked table joined on the object's key —, another formula,
a property through to-one links, `customer.tier`), each checked by the compiler's own path law at the door; and it is
verified through that compiler on up to `PROBE_ROWS` of the type's objects, so a formula that fails past the first
row, or reads nothing on every one, does not verify.
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
    paths = list(dict.fromkeys(".".join(p.name for p in col.parts) for col in node.find_all(exp.Column)))
    if any(path.lower() == name.lower() for path in paths):
        return f"'{name}' reads itself — a formula cannot be defined by itself"
    if graph is None:
        own = {k.lower() for k in (entity.properties or {}) if k not in (entity.expressions or {})}
        stray = next((path for path in paths if path.lower() not in own), None)
        return (f"'{stray}' is not a column of {entity.id}'s own rows — with no graph to read its links, an expression "
                "reads the backing's columns only") if stray else ""
    from aughor.semantic.object_query import ObjectQueryRefused, property_at
    for path in paths:
        try:
            property_at(graph, entity.api_name, path, purpose=f"the expression '{name}'")
        except ObjectQueryRefused as exc:
            return exc.reason
    return ""


#: How many of a type's objects a formula is verified on — the first rows of its table, read as a query reads them.
PROBE_ROWS = 1000


def _sampled(sql: str, dialect: str, rows: int) -> str:
    """``sql`` with its ANCHOR — the object type's own table, ``t0`` — read as its first ``rows`` rows. Everything the
    formula joins stays whole, so a linked table is still read the way a query reads it."""
    import sqlglot
    from sqlglot import exp
    tree = sqlglot.parse_one(sql, read=dialect)
    source = (tree.args.get("from_") or tree.args.get("from")).this
    if not isinstance(source, exp.Table):
        return sql                     # already a subquery — a query-backed type reads its own keyed SELECT
    first = exp.select("*").from_(exp.Table(this=source.this.copy(), db=source.args.get("db"),
                                            catalog=source.args.get("catalog"))).limit(rows)
    source.replace(exp.Subquery(this=first, alias=exp.TableAlias(this=exp.to_identifier(source.alias))))
    return tree.sql(dialect=dialect)


def _cell(value: Any) -> Any:
    """A probe cell: the display path spells SQL NULL "NULL"."""
    return None if value is None or (isinstance(value, str) and value.strip().upper() == "NULL") else value


def probe_expression(db: Any, graph: OntologyGraph, entity: OntologyEntity, expression: str, *,
                     name: str = "") -> dict:
    """Verify the expression through the object compiler on up to `PROBE_ROWS` of the type's objects — every path it
    reads joined as a query would join it: ``{bound, note, sample, rows_checked, non_null}``. Bound when it executes,
    its smallest and largest values are sane, and it holds a value on at least one object checked."""
    from aughor.ontology.validator import check_value
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
    if not (entity.source_tables or entity.backing is not None):
        return {"bound": False, "note": f"{entity.id} has no source table to read the expression on", "sample": None}
    probe = name or "probe_expression"
    work = graph.model_copy(deep=True)
    target = work.entities[entity.id]
    candidate = ExpressionProperty(expression=expression, verified=True)
    target.expressions = {**(target.expressions or {}), probe: candidate}
    target.properties = {**(target.properties or {}), probe: candidate.as_property(probe)}
    dialect = (getattr(db, "dialect", "") or "duckdb").lower()
    try:
        # grouped BY the value, never MIN/MAX over it: an aggregate over a boolean does not run everywhere (Postgres)
        compiled = compile_object_query({"object_type": target.api_name, "by": [probe],
                                         "measures": [{"name": "objects", "agg": "count"}]}, work, dialect=dialect)
    except ObjectQueryRefused as exc:
        return {"bound": False, "note": exc.reason, "sample": None}
    if compiled.cross_source is not None:
        return {"bound": False, "sample": None,
                "note": "it reads another connection — a formula is read on the connection its type lives on"}
    grouped = _sampled(compiled.sql, dialect, PROBE_ROWS)
    # the counts in SQL, exact on any connector — a result's returned rows are capped (500 on DuckDB), its groups not
    totals_sql = (f"SELECT SUM(g.objects) AS n, SUM(CASE WHEN g.{probe} IS NOT NULL THEN g.objects ELSE 0 END) "
                  f"AS non_null FROM ({grouped}) AS g")
    bounded = getattr(db, "execute_bounded", None)
    try:
        totals = db.execute("__ontology_validate__", totals_sql)
        values = (bounded("__ontology_validate__", grouped, PROBE_ROWS) if callable(bounded)
                  else db.execute("__ontology_validate__", grouped))
    except Exception as exc:  # noqa: BLE001 — a probe that cannot run does not bind, and says why
        return {"bound": False, "note": f"did not execute: {str(exc)[:200]}", "sample": None}
    error = getattr(totals, "error", None) or getattr(values, "error", None)
    if error:
        return {"bound": False, "note": f"did not execute: {str(error)[:200]}", "sample": None}
    n, non_null = ([int(float(_cell(v) or 0)) for v in (totals.rows or [[0, 0]])[0]] + [0, 0])[:2]
    columns = [str(c).lower() for c in (values.columns or compiled.columns)]
    at_value = columns.index(probe.lower()) if probe.lower() in columns else 0
    sample = None
    for row in values.rows or []:
        value = _cell(row[at_value])
        if value is None:
            continue
        sample = value if sample is None else sample
        sane, note = check_value(value)
        if not sane:
            return {"bound": False, "note": note, "sample": str(value)[:80], "rows_checked": n, "non_null": non_null}
    if n and not non_null:
        return {"bound": False, "sample": None, "rows_checked": n, "non_null": 0,
                "note": f"it is empty on every one of the {n:,} {entity.id} objects checked — a formula that reads "
                        "nothing is not verified (a path that never joins, a column that is never set)"}
    return {"bound": True, "note": "" if n else f"{entity.id} has no rows to check it on yet",
            "sample": None if sample is None else str(sample)[:80], "rows_checked": n, "non_null": non_null}


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
