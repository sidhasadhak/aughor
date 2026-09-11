"""ON-2 — the object plane's doors: the catalog of object types, and the compiled object query.

`POST /objects/query` compiles a typed object query over the SERVED ontology — the graph
`GET /ontology` returns, human overrides overlaid, under the same scope rule — and runs the SQL
through the guard battery. No model call anywhere on this path: the query is typed, the SQL is
assembled by `aughor.semantic.object_query`, and a refusal is an answer that says why and names
what exists. `GET /objects/catalog` lists exactly the names the compiler accepts. ON-3's object
pages (`GET /objects/{type}/{pk}`) will live beside these.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from aughor.db.registry import BUILTIN_ID
from aughor.semantic.object_query import ObjectQuery

router = APIRouter(tags=["objects"])

#: Rows a response carries; `row_count` still says how many the query returned.
_MAX_ROWS = 1000


def _served_graph(connection_id: str, schema_name: Optional[str]):
    from aughor.routers.ontology import served_ontology_graph
    graph = served_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404,
                            detail="No ontology is built for this scope — there are no object types to query yet.")
    return graph


@router.get("/objects/catalog")
def get_object_catalog(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None)):
    """Every object type the compiler can query: properties by role, links with their measured
    cardinality (and why an unusable one is not), verified segments and verified metrics."""
    from aughor.semantic.object_query import object_catalog
    return object_catalog(_served_graph(connection_id, schema_name))


@router.post("/objects/query")
def post_object_query(
    query: ObjectQuery,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    execute: bool = Query(default=True, description="False returns the compiled SQL and plan without running it"),
):
    """Compile an object query and run it through the guard battery (ON-2).

    `path` says what happened: `compiled` — the SQL, the plan (one line per decision the compiler
    made), the links relied on with their measured cardinality, and the rows — or `refused`, with
    the reason and the names that do exist. A refusal is an answer, not an error: the compiler
    never guesses."""
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.kernel.registries.execution_hooks import collect_guard_receipts
    from aughor.routers.ontology import resolve_effective_schema
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
    from aughor.sql.executor import execute_guarded

    graph = _served_graph(connection_id, schema_name)
    db = open_connection_for_with_schema(connection_id,
                                         graph.schema_name or resolve_effective_schema(connection_id, schema_name))
    try:
        try:
            compiled = compile_object_query(query, graph, dialect=getattr(db, "dialect", "") or "duckdb")
        except ObjectQueryRefused as exc:
            return {"path": "refused", "refused": exc.reason, "available": exc.available,
                    "connection_id": connection_id, "schema_name": graph.schema_name}
        out = {"connection_id": connection_id, "schema_name": graph.schema_name, **compiled.to_dict()}
        if not execute:
            return out
        with collect_guard_receipts() as receipts:
            result = execute_guarded(db, compiled.sql, query_id="objects")
        rows = list(result.rows or [])
        out.update({"columns": list(result.columns or []) or list(compiled.columns),
                    "rows": rows[:_MAX_ROWS], "row_count": result.row_count,
                    "truncated": len(rows) > _MAX_ROWS, "error": result.error,
                    "caveats": list(compiled.caveats) + list(result.caveats or []),
                    "guard_receipts": list(receipts)})
        return out
    finally:
        db.close()
