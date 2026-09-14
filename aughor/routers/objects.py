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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from aughor.db.registry import BUILTIN_ID
from aughor.routers.ontology import refuse_organisation_scope
from aughor.semantic.object_query import ObjectQuery

#: ON-8 — an organisation's ontology is reached through `?domain=` only, never by naming its tree as a connection.
router = APIRouter(tags=["objects"], dependencies=[Depends(refuse_organisation_scope)])

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


def _domain_served(domain: str, *, allow_empty: bool = False):
    """ON-8 — ``(scope, graph)`` for the organisation's ontology a request names; 404 while nothing is declared in it —
    except for the map, whose empty state is where its first type is declared."""
    from aughor.ontology.domains import DomainRefused, domain_graph, resolve_domain
    try:
        scope = resolve_domain(domain)
    except DomainRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    graph = domain_graph(scope)
    if not graph.entities and not allow_empty:
        raise HTTPException(status_code=404, detail=(f"Nothing is declared in {scope.key} yet — declare a type with "
                                                     f"POST /ontology/entities?domain={scope.name}."))
    return scope, graph


def _checked_source(scope, connection_id: str) -> None:
    """ON-8 — a connection an organisation's ontology reads must still be the organisation's to read."""
    from aughor.ontology.domains import DomainRefused, check_source
    try:
        check_source(scope, connection_id)
    except DomainRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


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
def get_object_catalog(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None),
                       domain: Optional[str] = Query(default=None)):
    """Every object type the compiler can query: properties by role, links with their measured
    cardinality (and why an unusable one is not), verified segments and verified metrics. ON-8 — with ``domain``, the
    organisation's ontology."""
    from aughor.semantic.object_query import object_catalog
    if domain is not None:
        scope, graph = _domain_served(domain)
        return {**object_catalog(graph), "domain": scope.key}
    return object_catalog(_served_graph(connection_id, schema_name), overlay=_accepted_edits(connection_id))


class _TitlesRequest(BaseModel):
    """The keys an answer table (or any list of keys) wants the names of."""
    object_type: str
    keys: list[str] = []


@router.post("/objects/titles")
def post_object_titles(body: _TitlesRequest, connection_id: str = BUILTIN_ID,
                       schema_name: Optional[str] = Query(default=None)):
    """The name of each object a set of keys names — one query over the backing, so a table of keys costs one
    round trip. A type named by its own key resolves nothing and says so; a key nothing matches is absent from
    the map rather than guessed at. An unknown type is `path: refused`. No model call."""
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.routers.ontology import resolve_effective_schema
    from aughor.semantic.object_instances import titles
    from aughor.semantic.object_query import ObjectQueryRefused

    graph = _served_graph(connection_id, schema_name)
    db = open_connection_for_with_schema(connection_id,
                                         graph.schema_name or resolve_effective_schema(connection_id, schema_name))
    try:
        try:
            found = titles(graph, db, body.object_type, body.keys)
        except ObjectQueryRefused as exc:
            return {"path": "refused", "refused": exc.reason, "available": exc.available,
                    "connection_id": connection_id, "schema_name": graph.schema_name}
        return {"path": "titles", "connection_id": connection_id, "schema_name": graph.schema_name, **found}
    finally:
        db.close()


@router.get("/object-types")
def get_object_type_map(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None),
                        domain: Optional[str] = Query(default=None)):
    """ON-3b — the entity-type map: every object type with the measured facts its card shows (key verified, rows,
    bindings, links the compiler follows, declared actions, verified metrics), and every link between two types
    with its verb and measured cardinality. A cache read: no warehouse query, no model call. ON-8 — with ``domain``,
    the organisation's ontology: each type says the connection it lives on, and each link whether it crosses two."""
    from aughor.semantic.object_types import object_type_map
    if domain is not None:
        scope, graph = _domain_served(domain, allow_empty=True)
        return {**object_type_map(graph), "domain": scope.key}
    return object_type_map(_served_graph(connection_id, schema_name), overlay=_accepted_edits(connection_id))


@router.get("/object-types/{object_type}")
def get_object_type(object_type: str, connection_id: str = BUILTIN_ID,
                    schema_name: Optional[str] = Query(default=None), domain: Optional[str] = Query(default=None)):
    """ON-3b — one object type as the entity-type panel shows it and `describe_entity` returns it: the key and
    whether it is unique, the display property, every property with its source, the bindings, the links (followed,
    or refused and why), the declared actions and the verified metrics. An unknown type is `path: refused`. ON-8 —
    with ``domain``, a type of the organisation's ontology."""
    from aughor.semantic.object_query import ObjectQueryRefused
    from aughor.semantic.object_types import describe_object_type
    if domain is not None:
        scope, served = _domain_served(domain)
        try:
            body = describe_object_type(served, object_type)
        except ObjectQueryRefused as exc:
            return {"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key}
        return {"path": "object_type", "domain": scope.key, "schema_name": "", **body}
    graph = _served_graph(connection_id, schema_name)
    try:
        body = describe_object_type(graph, object_type, overlay=_accepted_edits(connection_id))
    except ObjectQueryRefused as exc:
        return {"path": "refused", "refused": exc.reason, "available": exc.available,
                "connection_id": connection_id, "schema_name": graph.schema_name}
    return {"path": "object_type", "connection_id": connection_id, "schema_name": graph.schema_name, **body}


@router.get("/object-paths")
def get_object_paths(source: str, target: str, connection_id: str = BUILTIN_ID,
                     schema_name: Optional[str] = Query(default=None),
                     max_hops: int = Query(default=4, ge=1, le=5), domain: Optional[str] = Query(default=None)):
    """ON-3b — how one object type reaches another: every chain of links within `max_hops`, each hop marked
    followed or refused with the compiler's reason, followed paths first. An unknown type is `path: refused`. ON-8 —
    with ``domain``, in the organisation's ontology."""
    from aughor.semantic.object_query import ObjectQueryRefused
    from aughor.semantic.object_types import find_paths
    if domain is not None:
        scope, served = _domain_served(domain)
        try:
            found = find_paths(served, source, target, max_hops=max_hops)
        except ObjectQueryRefused as exc:
            return {"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key}
        return {"path": "paths", "domain": scope.key, **found}
    graph = _served_graph(connection_id, schema_name)
    try:
        found = find_paths(graph, source, target, max_hops=max_hops)
    except ObjectQueryRefused as exc:
        return {"path": "refused", "refused": exc.reason, "available": exc.available,
                "connection_id": connection_id, "schema_name": graph.schema_name}
    return {"path": "paths", "connection_id": connection_id, "schema_name": graph.schema_name, **found}


@router.post("/objects/query")
def post_object_query(
    query: ObjectQuery,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    execute: bool = Query(default=True, description="False returns the compiled SQL and plan without running it"),
    domain: Optional[str] = Query(default=None, description="ON-8 — query an organisation's ontology, whose types may live on several connections"),
):
    """Compile an object query and run it through the guard battery (ON-2).

    `path` says what happened: `compiled` — the SQL, the plan (one line per decision the compiler
    made), the links relied on with their measured cardinality, and the rows — or `refused`, with
    the reason and the names that do exist. A refusal is an answer, not an error: the compiler
    never guesses. ON-8 — with ``domain``, the query runs on its anchor type's connection; a source on another
    connection is read by key and the answer aggregated over both (`cross_source` says how, `timings` how long)."""
    if domain is not None:
        return _domain_object_query(query, domain, execute)
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


def _domain_object_query(query: ObjectQuery, domain: str, execute: bool) -> dict:
    """ON-8 — `POST /objects/query` over an organisation's ontology. The anchor type's connection is where the query
    runs; a query that reads nothing on another connection runs there as one statement through the guard battery, and
    one that does is split and run across its sources (`aughor.semantic.cross_source`), every connection it reads
    checked as the organisation's first."""
    from aughor.db.connection import open_connection_for
    from aughor.kernel.registries.execution_hooks import collect_guard_receipts
    from aughor.ontology.sources import entity_source
    from aughor.semantic.cross_source import execute_plan
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query, find_object_type
    from aughor.sql.executor import execute_guarded

    scope, graph = _domain_served(domain)
    try:
        anchor = find_object_type(graph, query.object_type)
    except ObjectQueryRefused as exc:
        return {"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key}
    home = entity_source(graph, anchor)
    _checked_source(scope, home)
    db = open_connection_for(home)
    try:
        try:
            compiled = compile_object_query(query, graph, dialect=getattr(db, "dialect", "") or "duckdb")
        except ObjectQueryRefused as exc:
            return {"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key,
                    "connection_id": home}
        out = {"domain": scope.key, "connection_id": home, "schema_name": "", **compiled.to_dict()}
        if not execute:
            return out
        receipts: list = []
        timings: list = []
        if compiled.cross_source is not None:
            for read in compiled.cross_source.reads:
                _checked_source(scope, read.connection_id)
            result, timings = execute_plan(compiled.cross_source, home_connection_id=home, home_db=db,
                                           open_source=open_connection_for, label="objects", display_sql=compiled.sql)
        else:
            with collect_guard_receipts() as collected:
                result = execute_guarded(db, compiled.sql, query_id="objects")
            receipts = list(collected)
        rows = list(result.rows or [])
        out.update({"columns": list(result.columns or []) or list(compiled.columns),
                    "rows": rows[:_MAX_ROWS], "row_count": result.row_count,
                    "truncated": len(rows) > _MAX_ROWS, "error": result.error,
                    "caveats": list(compiled.caveats) + list(result.caveats or []),
                    "guard_receipts": receipts, "timings": timings})
        return out
    finally:
        db.close()
