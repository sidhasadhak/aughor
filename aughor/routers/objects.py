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


def _open_scoped(connection_id: str, schema_name: Optional[str], graph):
    """The connection, scoped to the schema the served graph was built for."""
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.routers.ontology import resolve_effective_schema
    return open_connection_for_with_schema(connection_id,
                                           graph.schema_name or resolve_effective_schema(connection_id, schema_name))


def _accepted_edits(connection_id: str) -> list:
    """ON-4 — this org's accepted property edits on the connection's objects, merged at read time."""
    from aughor.actions.overlay import accepted_object_edits
    return accepted_object_edits(connection_id)


@router.get("/objects/{object_type}/{pk}")
def get_object_page(object_type: str, pk: str, connection_id: str = BUILTIN_ID,
                    schema_name: Optional[str] = Query(default=None)):
    """ON-3: one object, resolved live through its backing — its properties, and its links resolved
    to the linked object's key (to-one) or a count of the linked objects (to-many). A link the
    compiler refuses is listed with its reason and never traversed. 404 when no object has that key;
    an unknown type is `path: refused` with the types that exist."""
    from aughor.semantic.object_context import object_context
    from aughor.semantic.object_instances import ObjectNotFound, get_object
    from aughor.semantic.object_query import ObjectQueryRefused

    graph = _served_graph(connection_id, schema_name)
    db = _open_scoped(connection_id, schema_name, graph)
    try:
        try:
            instance = get_object(graph, db, object_type, pk, overlay=_accepted_edits(connection_id))
        except ObjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ObjectQueryRefused as exc:
            return {"path": "refused", "refused": exc.reason, "available": exc.available,
                    "connection_id": connection_id, "schema_name": graph.schema_name}
        related = object_context(graph, db, connection_id, graph.schema_name, instance,
                                 dialect=getattr(db, "dialect", "") or "duckdb")
        return {"path": "object", "connection_id": connection_id, "schema_name": graph.schema_name,
                **instance.to_dict(), "related": related}
    finally:
        db.close()


@router.get("/objects/{object_type}/{pk}/links/{link}")
def get_object_links_page(object_type: str, pk: str, link: str, connection_id: str = BUILTIN_ID,
                          schema_name: Optional[str] = Query(default=None),
                          limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    """ON-3: one page of the objects a link reaches from one object, ordered by their key — refused
    when the link is (unmeasured, N:N, or touching a query backing)."""
    from aughor.semantic.object_instances import ObjectNotFound, list_linked
    from aughor.semantic.object_query import ObjectQueryRefused

    graph = _served_graph(connection_id, schema_name)
    db = _open_scoped(connection_id, schema_name, graph)
    try:
        try:
            page = list_linked(graph, db, object_type, pk, link, limit=limit, offset=offset)
        except ObjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ObjectQueryRefused as exc:
            return {"path": "refused", "refused": exc.reason, "available": exc.available,
                    "connection_id": connection_id, "schema_name": graph.schema_name}
        return {"path": "links", "connection_id": connection_id, "schema_name": graph.schema_name, **page}
    finally:
        db.close()


@router.get("/objects/catalog")
def get_object_catalog(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None)):
    """Every object type the compiler can query: properties by role, links with their measured
    cardinality (and why an unusable one is not), verified segments and verified metrics."""
    from aughor.semantic.object_query import object_catalog
    return object_catalog(_served_graph(connection_id, schema_name), overlay=_accepted_edits(connection_id))


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
            compiled = compile_object_query(query, graph, dialect=getattr(db, "dialect", "") or "duckdb",
                                            overlay=_accepted_edits(connection_id))
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
