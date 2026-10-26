"""ON-2 — the object plane's doors: the catalog of object types, and the compiled object query.

`POST /objects/query` compiles a typed object query over the SERVED ontology — the graph
`GET /ontology` returns, human overrides overlaid, under the same scope rule — and runs the SQL
through the guard battery. No model call anywhere on this path: the query is typed, the SQL is
assembled by `aughor.semantic.object_query`, and a refusal is an answer that says why and names
what exists. `GET /objects/catalog` lists exactly the names the compiler accepts. ON-3's object
pages (`GET /objects/{type}/{pk}`) will live beside these.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from aughor.db.registry import BUILTIN_ID
from aughor.ontology.security import acting_agent_from_request
from aughor.ontology.security_sql import object_door_from_request
from aughor.routers.ontology import refuse_organisation_scope
from aughor.security.authz import connection_owner_guard
from aughor.semantic.object_query import ObjectListing, ObjectQuery

#: ON-8 — an organisation's ontology is reached through `?domain=` only, never by naming its tree as a connection;
#: DATA-06 — every connection a door names belongs to the caller's org (identity on).
router = APIRouter(tags=["objects"], dependencies=[Depends(refuse_organisation_scope), Depends(connection_owner_guard),
                                                  Depends(acting_agent_from_request),    # Arc OC-7 — an agent reads only what its person may
                                                  Depends(object_door_from_request)])    # Arc ED, ED-1 — its statements apply OC-7 themselves


#: Arc AP-6 — the group a builder previews a dashboard as: one more party among the reader's, so it only narrows.
AS_GROUP = Query(default=None, description="Arc AP-6 — read as you and a member of this group would: only ever less")


def _preview(as_group: Optional[str]):
    """The group a request previews as, checked to be one of this organisation's — or nothing to preview."""
    import contextlib
    if not isinstance(as_group, str) or not as_group:      # called as a function, the default is FastAPI's Query
        return contextlib.nullcontext()
    from aughor.ontology.security import previewing
    from aughor.org.context import current_org_id
    from aughor.rbac.groups import list_groups
    if as_group not in {g.id for g in list_groups(current_org_id())}:
        raise HTTPException(status_code=422, detail=f"There is no group {as_group!r} here to preview as.")
    return previewing(as_group)


async def preview_from_request(as_group: Optional[str] = AS_GROUP) -> None:
    """A route dependency: the group a builder previews a dashboard as, held for the rest of the request — set on the
    request's own context, as the acting agent's header is, so it reaches the read and no other request."""
    if isinstance(as_group, str) and as_group:
        from aughor.ontology.security import set_previewing
        _preview(as_group)                                  # refuses a group this organisation does not have
        set_previewing(as_group)

#: Rows a response carries; `row_count` still says how many the query returned.
_MAX_ROWS = 1000


def _complete(out: Any, clock: Any, **facts) -> Any:
    """Arc ED-6 — the answer with how complete its read is (`semantic/completeness.py`), when ``objects.completeness``
    is on; as it was when off. A refusal is said as ``refused``, with its reason."""
    from aughor.semantic import completeness as C
    if not C.enabled() or not isinstance(out, dict):
        return out
    if out.get("path") == "refused":
        return {**out, "completeness": C.refused(str(out.get("refused") or ""), clock)}
    return {**out, "completeness": C.of_read(took_ms=clock.ms(), **facts)}


def _truthful(out: dict, result: Any) -> dict:
    """With ``objects.completeness`` on, ``truncated`` says what the connection did: it stopped at its own cap (500)
    long before the 1,000 this door compares with, so the old boolean was never true. Off: as before."""
    from aughor.semantic import completeness as C
    if C.enabled() and C.cut(result):
        out["truncated"] = True
    return out


def _read_facts(graph: Any, compiled: Any, result: Any, shown: int) -> dict:
    """What a query's read says of its completeness: cut at the connection's cap, a row policy's narrowing, or a read
    that failed — refused over a cap among them."""
    from aughor.semantic import completeness as C
    error = str(getattr(result, "error", "") or "")
    return {"shown": shown, "truncated": C.cut(result), "withheld": list(getattr(compiled, "withheld", []) or []),
            "said": C.policy_words(graph, getattr(compiled, "withheld", []) or []), "refused": error}


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


def _domain_edits(graph) -> list:
    """ON-4 × ON-8 — the accepted edits a read of an organisation's ontology merges: each type's OWN, from the
    connection its rows live on (PENDING item 25: the domain object query merged none, so an accepted edit vanished
    from every query over the organisation's ontology). Never another connection's edits on a type of the same
    name — two connections' `customers` are two types."""
    from aughor.ontology.sources import entity_source

    def word(s: str) -> str:
        return "".join(ch for ch in (s or "").lower() if ch.isalnum())
    by_connection: dict[str, list] = {}
    out: list = []
    for entity in graph.entities.values():
        home = entity_source(graph, entity)
        if not home:
            continue
        if home not in by_connection:
            by_connection[home] = _accepted_edits(home)
        names = {word(entity.api_name), word(entity.id)}
        out += [e for e in by_connection[home] if word(getattr(e, "object_type", "")) in names]
    return out


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


@contextmanager
def _domain_sources(scope):
    """ON-8 — the connections one request reads an organisation's objects from: each checked as the organisation's and
    opened the first time a read needs it, and every one closed when the request ends."""
    from aughor.db.connection import open_connection_for
    opened: dict = {}

    def source_db(connection_id: str):
        if connection_id not in opened:
            _checked_source(scope, connection_id)
            opened[connection_id] = open_connection_for(connection_id)
        return opened[connection_id]
    try:
        yield source_db
    finally:
        for db in opened.values():
            db.close()


@router.get("/objects/{object_type}/{pk}", dependencies=[Depends(preview_from_request)])
def get_object_page(object_type: str, pk: str, connection_id: str = BUILTIN_ID,
                    schema_name: Optional[str] = Query(default=None), domain: Optional[str] = Query(default=None)):
    """ON-3: one object, resolved live through its backing — its properties, and its links resolved
    to the linked object's key (to-one) or a count of the linked objects (to-many). A link the
    compiler refuses is listed with its reason and never traversed. 404 when no object has that key;
    an unknown type is `path: refused` with the types that exist. ON-8 — with ``domain``, an object of the
    organisation's ontology: its row, each binding and each linked type read on the connection it lives on."""
    from aughor.semantic.completeness import Clock
    clock = Clock()
    if domain is not None:
        return _domain_object_page(object_type, pk, domain, clock)
    from aughor.semantic.object_context import object_context
    from aughor.semantic.object_instances import ObjectNotFound, ObjectWithheld, get_object
    from aughor.semantic.object_query import ObjectQueryRefused, keyed_metrics_for

    graph = _served_graph(connection_id, schema_name)
    db = _open_scoped(connection_id, schema_name, graph)
    try:
        try:
            instance = get_object(graph, db, object_type, pk, overlay=_accepted_edits(connection_id))
        except ObjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ObjectWithheld as exc:   # Arc OC-7 — withheld, said, never missing
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "connection_id": connection_id, "schema_name": graph.schema_name}, clock)
        related = object_context(graph, db, connection_id, graph.schema_name, instance,
                                 dialect=getattr(db, "dialect", "") or "duckdb",
                                 keyed=keyed_metrics_for(connection_id, graph.schema_name))   # Arc OC-3, flag-gated
        return _complete({"path": "object", "connection_id": connection_id, "schema_name": graph.schema_name,
                          **instance.to_dict(), "related": related}, clock, **_object_facts(instance))
    finally:
        db.close()


def _object_facts(instance: Any) -> dict:
    """One object's completeness: each sensitive property emptied for this reader, said in its own words."""
    masked = [p for p in instance.properties if p.get("withheld")]
    return {"shown": 1, "masked": [str(p.get("name") or "") for p in masked],
            "said": [str(p["withheld"]) for p in masked]}


def _domain_object_page(object_type: str, pk: str, domain: str, clock: Any = None) -> dict:
    from aughor.ontology.sources import entity_source
    from aughor.semantic.object_context import object_context
    from aughor.semantic.object_instances import ObjectNotFound, ObjectWithheld, get_object
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type

    from aughor.semantic.completeness import Clock
    clock = clock or Clock()
    scope, graph = _domain_served(domain)
    try:
        entity = find_object_type(graph, object_type)
    except ObjectQueryRefused as exc:
        return _complete({"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key},
                         clock)
    home = entity_source(graph, entity)
    with _domain_sources(scope) as source_db:
        try:
            instance = get_object(graph, None, entity.api_name, pk, overlay=_domain_edits(graph), source_db=source_db)
        except ObjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ObjectWithheld as exc:   # Arc OC-7 — withheld, said, never missing
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key,
                              "connection_id": home}, clock)
        db = source_db(home)
        table = (entity.backing.table if entity.backing is not None else "") or ""

        def run_plan(compiled):
            """A metric that reads another connection runs as its plan — never its display SQL (PENDING item 25) —
            every connection it reads checked as the organisation's first."""
            from aughor.semantic.cross_source import execute_plan
            try:
                result, _ = execute_plan(compiled.cross_source, home_connection_id=home, home_db=db,
                                         open_source=source_db, label="object_metric", display_sql=compiled.sql)
            except HTTPException as exc:
                raise ObjectQueryRefused(str(exc.detail)) from exc
            return result
        # the findings and notes around it are the ones kept on the connection its rows live on
        related = object_context(graph, db, home, table.split(".")[-2] if "." in table else "", instance,
                                 dialect=getattr(db, "dialect", "") or "duckdb", run_cross_source=run_plan)
    return _complete({"path": "object", "domain": scope.key, "connection_id": home, "schema_name": "",
                      **instance.to_dict(), "related": related}, clock, **_object_facts(instance))


@router.get("/objects/{object_type}/{pk}/links/{link}")
def get_object_links_page(object_type: str, pk: str, link: str, connection_id: str = BUILTIN_ID,
                          schema_name: Optional[str] = Query(default=None),
                          limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                          domain: Optional[str] = Query(default=None)):
    """ON-3: one page of the objects a link reaches from one object, ordered by their key — refused
    when the link is (unmeasured, N:N, or touching a query backing). ON-8 — with ``domain``, in the organisation's
    ontology: the object read where it lives, and the linked objects where theirs do."""
    from aughor.semantic.completeness import Clock
    clock = Clock()
    if domain is not None:
        return _domain_links_page(object_type, pk, link, domain, limit, offset, clock)
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
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "connection_id": connection_id, "schema_name": graph.schema_name}, clock)
        return _complete({"path": "links", "connection_id": connection_id, "schema_name": graph.schema_name, **page},
                         clock, **_page_facts(graph, page))
    finally:
        db.close()


def _page_facts(graph: Any, page: dict) -> dict:
    """A linked page's completeness: the row policy that narrowed the linked objects, and the properties emptied."""
    from aughor.semantic.completeness import narrowed, policy_words
    withheld = narrowed((graph.entities or {}).get(page.get("type_id") or ""))
    masked = dict(page.get("masked") or {})
    return {"shown": len(page.get("rows") or []), "withheld": withheld, "masked": list(masked),
            "said": policy_words(graph, withheld) + list(masked.values())}


def _domain_links_page(object_type: str, pk: str, link: str, domain: str, limit: int, offset: int,
                       clock: Any = None) -> dict:
    from aughor.ontology.sources import entity_source
    from aughor.semantic.object_instances import ObjectNotFound, list_linked
    from aughor.semantic.object_query import ObjectQueryRefused

    from aughor.semantic.completeness import Clock
    clock = clock or Clock()
    scope, graph = _domain_served(domain)
    with _domain_sources(scope) as source_db:
        try:
            page = list_linked(graph, None, object_type, pk, link, limit=limit, offset=offset, source_db=source_db)
        except ObjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "domain": scope.key}, clock)
    where = entity_source(graph, graph.entities[page["type_id"]])
    return _complete({"path": "links", "domain": scope.key, "connection_id": where, "schema_name": "", **page},
                     clock, **_page_facts(graph, page))


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
                       schema_name: Optional[str] = Query(default=None), domain: Optional[str] = Query(default=None)):
    """The name of each object a set of keys names — one query over the backing, so a table of keys costs one
    round trip. A type named by its own key resolves nothing and says so; a key nothing matches is absent from
    the map rather than guessed at. An unknown type is `path: refused`. No model call. ON-8 — with ``domain``, a
    type of the organisation's ontology, its names read where they live."""
    from aughor.semantic.completeness import Clock
    clock = Clock()
    if domain is not None:
        return _domain_titles(body, domain, clock)
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
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "connection_id": connection_id, "schema_name": graph.schema_name}, clock)
        return _complete({"path": "titles", "connection_id": connection_id, "schema_name": graph.schema_name, **found},
                         clock, **_titles_facts(graph, found, body))
    finally:
        db.close()


class _FindRequest(BaseModel):
    """Arc FA, FA-1 — the words an object goes by, and how many of each entity's matches to show."""
    q: str
    limit_per_entity: int = 5


@router.post("/objects/find", dependencies=[Depends(preview_from_request)])
def post_object_find(body: _FindRequest, connection_id: str = BUILTIN_ID,
                     schema_name: Optional[str] = Query(default=None)):
    """Arc FA, FA-1 (flag ``objects.find``) — the objects whose name holds the words, across the served entities: each
    entity titled by a text property is listed by its key and title with the words as a ``contains`` condition, through
    the object door's compiler and its row policies, on one connection. At most 12 entities and a few objects each;
    ``said`` is how many entities it searched of how many there are, ``skipped`` each other one with why, ``more`` those
    with more matches than shown. 404 while the flag is off. No model call."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("objects.find"):
        raise HTTPException(status_code=404, detail="Finding an object by its name is off on this install.")
    from aughor.semantic.completeness import Clock, policy_words
    from aughor.semantic.object_find import find_objects
    from aughor.semantic.object_query import ObjectQueryRefused
    from aughor.sql.executor import execute_guarded

    clock = Clock()
    graph = _served_graph(connection_id, schema_name)
    db = _open_scoped(connection_id, schema_name, graph)
    try:
        try:
            found = find_objects(graph, lambda sql: execute_guarded(db, sql, query_id="objects.find"), body.q,
                                 dialect=getattr(db, "dialect", "") or "duckdb", overlay=_accepted_edits(connection_id),
                                 per_entity=body.limit_per_entity)
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "connection_id": connection_id, "schema_name": graph.schema_name}, clock)
    finally:
        db.close()
    said = policy_words(graph, found["withheld"])
    out = {"path": "found", "connection_id": connection_id, "schema_name": graph.schema_name, **found,
           "withheld_said": said}
    return _complete(out, clock, shown=len(found["hits"]), withheld=found["withheld"], masked=found["masked"], said=said)


def _titles_facts(graph: Any, found: dict, body: Any) -> dict:
    """The names read for a set of keys: the first ``MAX_TITLES`` of them when more were asked, and a row policy's
    narrowing — a key it withholds is absent from the map, so it is said."""
    from aughor.semantic.completeness import narrowed, policy_words
    withheld = narrowed((graph.entities or {}).get(found.get("type_id") or ""))
    return {"shown": len(found.get("titles") or {}), "of": len(dict.fromkeys(body.keys or [])),
            "truncated": bool(found.get("truncated")), "withheld": withheld, "said": policy_words(graph, withheld)}


def _domain_titles(body: _TitlesRequest, domain: str, clock: Any = None) -> dict:
    from aughor.ontology.sources import entity_source
    from aughor.semantic.object_instances import titles
    from aughor.semantic.object_query import ObjectQueryRefused

    from aughor.semantic.completeness import Clock
    clock = clock or Clock()
    scope, graph = _domain_served(domain)
    with _domain_sources(scope) as source_db:
        try:
            found = titles(graph, None, body.object_type, body.keys, source_db=source_db)
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "domain": scope.key}, clock)
    home = entity_source(graph, graph.entities[found["type_id"]])
    return _complete({"path": "titles", "domain": scope.key, "connection_id": home, "schema_name": "", **found},
                     clock, **_titles_facts(graph, found, body))


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
    return {"path": "object_type", "connection_id": connection_id, "schema_name": graph.schema_name, **body,
            "withdrawn": _withdrawn_of(connection_id, graph.schema_name or "", str(body.get("id") or ""))}


@router.get("/object-types/{object_type}/uses")
def get_object_type_uses(object_type: str, connection_id: str = BUILTIN_ID,
                         schema_name: Optional[str] = Query(default=None)):
    """ROADMAP §6 item 53 — what one entity is used by: its dependents (automations, processes, rules, actions,
    links, parts, metrics — each with how), every dashboard whose pieces read it, and how many audited statements
    named its tables in each of the last twelve months. Behind `ontology.entity_usage`: off, the door says so and
    the type's own page is exactly what it was. An unknown type is `path: refused`."""
    from aughor.ontology import entity_uses
    if not entity_uses.enabled():
        return {"path": "off", "said": "What uses an entity is not shown: the setting is off."}
    from aughor.semantic.object_query import ObjectQueryRefused
    from aughor.semantic.object_types import describe_object_type
    graph = _served_graph(connection_id, schema_name)
    try:
        body = describe_object_type(graph, object_type, overlay=_accepted_edits(connection_id))
    except ObjectQueryRefused as exc:
        return {"path": "refused", "refused": exc.reason, "available": exc.available,
                "connection_id": connection_id, "schema_name": graph.schema_name}
    return {"path": "uses", "connection_id": connection_id, "schema_name": graph.schema_name,
            "entity": str(body.get("id") or object_type), **entity_uses.uses_of(graph, connection_id, body)}


def _withdrawn_of(connection_id: str, schema: str, entity_id: str) -> dict:
    """2026-09-22 — what a person withdrew on this type, read from the overrides: the builder-found bindings
    (`withdrawn_bindings`) and the found links (`withdrawn`) on either side of it — so the panel can restore them.
    Best-effort: an unreadable tree lists nothing rather than failing the page."""
    out: dict = {"bindings": [], "links": []}
    try:
        from aughor.ontology.overrides import load_overrides
        for ov in load_overrides(connection_id, schema):
            if ov.target_kind == "entity" and ov.target_id == entity_id:
                out["bindings"] = sorted(str(n) for n in (ov.fields.get("withdrawn_bindings") or []))
            elif ov.target_kind == "link" and ov.fields.get("withdrawn") and entity_id in (
                    ov.fields.get("from_entity"), ov.fields.get("to_entity")):
                out["links"].append({"relationship": ov.target_id, "from_entity": ov.fields.get("from_entity") or "",
                                     "to_entity": ov.fields.get("to_entity") or ""})
    except Exception as exc:  # noqa: BLE001 — a page that cannot list withdrawals still shows the type
        from aughor.kernel.errors import tolerate
        tolerate(exc, "withdrawn overrides unreadable; the type page lists none", counter="objects.withdrawn")
    return out


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


@router.post("/objects/query", dependencies=[Depends(preview_from_request)])
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
    from aughor.semantic.completeness import Clock
    clock = Clock()
    if domain is not None:
        return _domain_object_query(query, domain, execute, clock)
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.kernel.registries.execution_hooks import collect_guard_receipts
    from aughor.routers.ontology import resolve_effective_schema
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query, keyed_metrics_for
    from aughor.sql.executor import execute_guarded

    graph = _served_graph(connection_id, schema_name)
    from aughor.ontology.platform_objects import is_platform
    from aughor.ontology.platform_objects import query as platform_query
    from aughor.semantic.object_query import find_object_type
    try:
        counted = find_object_type(graph, query.object_type)
    except ObjectQueryRefused:
        counted = None
    if is_platform(counted):
        # Arc AP-4 — a platform-owned type is counted from the edit layer that holds its objects: a case queue's figures
        out = platform_query(counted, _accepted_edits(connection_id), measures=[m.model_dump() for m in query.measures],
                             by=list(query.by), filters=[f.model_dump() for f in query.filters], segment=query.segment,
                             time=query.time, grain=query.grain)
        return _complete({"connection_id": connection_id, "schema_name": graph.schema_name, **out}, clock,
                         shown=len(out.get("rows") or []))
    db = open_connection_for_with_schema(connection_id,
                                         graph.schema_name or resolve_effective_schema(connection_id, schema_name))
    try:
        try:
            compiled = compile_object_query(query, graph, dialect=getattr(db, "dialect", "") or "duckdb",
                                            overlay=_accepted_edits(connection_id),
                                            metrics=keyed_metrics_for(connection_id, graph.schema_name))
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "connection_id": connection_id, "schema_name": graph.schema_name}, clock)
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
        return _complete(_truthful(out, result), clock, **_read_facts(graph, compiled, result, len(out["rows"])))
    finally:
        db.close()


@router.post("/objects/list", dependencies=[Depends(preview_from_request)])
def post_object_listing(
    listing: ObjectListing,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    execute: bool = Query(default=True, description="False returns the compiled SQL and plan without running it"),
):
    """Arc OC-4 — one page of objects (ROADMAP §3.56): an entity, or a segment of it, with the columns asked for, sorted
    with the key breaking ties, from `offset`, at most 200 — and `total`, the objects the set holds. Compiled by the
    object door's own compiler over the SERVED ontology, an accepted edit read like a column, and run through the guard
    battery. `path` is `listed`, or `refused` with the reason and the names that exist. No model call."""
    from aughor.kernel.registries.execution_hooks import collect_guard_receipts
    from aughor.semantic.completeness import Clock
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_listing
    from aughor.sql.executor import execute_guarded

    clock = Clock()
    graph = _served_graph(connection_id, schema_name)
    from aughor.ontology.platform_objects import is_platform
    from aughor.ontology.platform_objects import listing as platform_listing
    from aughor.semantic.object_query import find_object_type
    try:
        listed = find_object_type(graph, listing.entity)
    except ObjectQueryRefused:
        listed = None
    if is_platform(listed):
        # Arc OC-6 — a platform-owned type is listed from the edit layer that holds its objects
        page = platform_listing(listed, _accepted_edits(connection_id), columns=list(listing.columns),
                                filters=[f.model_dump() for f in listing.filters], order_by=listing.order_by,
                                descending=listing.descending, offset=listing.offset, limit=listing.limit,
                                segment=listing.segment)
        return _complete({"connection_id": connection_id, "schema_name": graph.schema_name, **page}, clock,
                         shown=len(page.get("rows") or []), of=page.get("total"))
    db = _open_scoped(connection_id, schema_name, graph)
    try:
        try:
            compiled = compile_object_listing(listing, graph, dialect=getattr(db, "dialect", "") or "duckdb",
                                              overlay=_accepted_edits(connection_id))
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available,
                              "connection_id": connection_id, "schema_name": graph.schema_name}, clock)
        out = {"connection_id": connection_id, "schema_name": graph.schema_name, "offset": listing.offset,
               "limit": listing.limit, **compiled.to_dict()}
        if not execute:
            return out
        with collect_guard_receipts() as receipts:
            page = execute_guarded(db, compiled.sql, query_id="objects.list")
            counted = execute_guarded(db, compiled.count_sql, query_id="objects.list") if not page.error else None
        error = page.error or (counted.error if counted is not None else "")
        n = (counted.rows or [[None]])[0][0] if counted is not None and not counted.error else None
        out.update({"names": list(page.columns or []), "rows": list(page.rows or [])[:listing.limit],
                    "total": int(n) if n not in (None, "", "NULL") else None, "error": error,
                    "caveats": list(compiled.caveats) + list(page.caveats or []), "guard_receipts": list(receipts)})
        from aughor.semantic.completeness import policy_words
        return _complete(out, clock, shown=len(out["rows"]), of=out["total"], refused=str(error or ""),
                         withheld=compiled.withheld, said=policy_words(graph, compiled.withheld))
    finally:
        db.close()


def _domain_object_query(query: ObjectQuery, domain: str, execute: bool, clock: Any = None) -> dict:
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

    from aughor.semantic.completeness import Clock
    clock = clock or Clock()
    scope, graph = _domain_served(domain)
    try:
        anchor = find_object_type(graph, query.object_type)
    except ObjectQueryRefused as exc:
        return _complete({"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key},
                         clock)
    home = entity_source(graph, anchor)
    _checked_source(scope, home)
    db = open_connection_for(home)
    try:
        try:
            compiled = compile_object_query(query, graph, dialect=getattr(db, "dialect", "") or "duckdb",
                                            overlay=_domain_edits(graph))
        except ObjectQueryRefused as exc:
            return _complete({"path": "refused", "refused": exc.reason, "available": exc.available, "domain": scope.key,
                              "connection_id": home}, clock)
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
        return _complete(_truthful(out, result), clock, **_read_facts(graph, compiled, result, len(out["rows"])))
    finally:
        db.close()
