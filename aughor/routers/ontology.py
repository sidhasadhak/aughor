"""Ontology graph — entities, relationships, actions, metrics, lifecycle counts, rebuild."""
from __future__ import annotations

import asyncio
import threading
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aughor.db.connection import open_connection_for
from aughor.db.registry import BUILTIN_ID, get_meta
from aughor.ontology.models import QueryTemplate
from aughor.ontology.overrides import DOMAIN_CARRIER, ORGANISATION_SEGMENT
from aughor.routers._shared import invalidate_schema_cache as _invalidate_schema_cache
from aughor.security.authz import connection_owner_guard

from aughor.licensing import Capability, gate


def refuse_organisation_scope(request: Request) -> None:
    """ON-8 — a door reads or edits ONE connection's ontology by the connection id it is given, and an organisation's
    ontology is read and edited only through the doors that take ``?domain=``. So a connection id naming an
    organisation's tree (``org=<org>``) is refused on every door — no door reaches another organisation's declarations,
    or edits one past the rule that people alone edit them, by naming it — and the scope the web carries an
    organisation's ontology in (``domain:<name>``) is refused on a door that takes no ``?domain=``. The explorer's doors
    take none: the explorer drafts one connection's ontology and reads nothing beyond it (the user's rule, 2026-09-14)."""
    route = request.scope.get("route")
    params = getattr(getattr(route, "dependant", None), "query_params", None) or []
    # the carrier reaches an organisation's ontology only beside the ?domain= that names it, on a door that takes one
    names_domain = any(getattr(p, "alias", "") == "domain" for p in params) and "domain" in request.query_params
    for name, value in request.query_params.multi_items():
        if name != "connection_id" and not name.endswith("_connection_id"):
            continue
        if value.startswith(ORGANISATION_SEGMENT) or (value.startswith(DOMAIN_CARRIER) and not names_domain):
            explorer = str(getattr(route, "path", "")).startswith(("/ontology/explore", "/ontology/draft"))
            raise HTTPException(status_code=400, detail=(
                f"'{value}' is an organisation's ontology, not a connection — "
                + ("the explorer drafts one connection's ontology and never reads beyond it; " if explorer
                   else "this door reads or edits one connection's ontology; ")
                + "an organisation's ontology is read and edited by people, through the doors that take ?domain="))


#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
router = APIRouter(tags=["ontology"], dependencies=[Depends(refuse_organisation_scope), Depends(connection_owner_guard)])


class _UseInstead(BaseModel):
    """Routing guidance: query ``table`` rather than this entity's own table.

    ``scope`` says WHEN ("general sales calculations"); empty means always. ``reason``
    is the author's own words, shown to the model and never parsed. The named table is
    existence-bound on write — an unbound rule is stored but never enforced.
    """
    table: str
    scope: str = ""
    reason: str = ""


class _BackingSpec(BaseModel):
    """ON-1: what an object is read from — a keyed SELECT whose rows are its instances."""
    kind: Literal["table", "query"] = "query"
    table: Optional[str] = None
    sql: Optional[str] = None
    primary_key: str


class _BackingPreview(BaseModel):
    """A keyed SELECT a person considers as a type's backing, previewed before anything is written."""
    sql: str
    primary_key: str


class _BindingSpec(BaseModel):
    """ON-1b — a further binding: a table or keyed SELECT joined to the object on its key."""
    table: Optional[str] = None
    sql: Optional[str] = None
    #: ON-8 — in an organisation's ontology (`?domain=`): the connection the source lives on when it is not the type's
    #: own, and the schema that qualifies a bare table there.
    connection_id: Optional[str] = None
    schema_name: Optional[str] = None
    #: The binding's column that holds the object's key.
    key: str
    kind: Literal["static", "timeseries", "detail"] = "static"
    #: A timeseries binding's time column.
    time_column: Optional[str] = None
    #: ON-7 — ``{property: {column, agg}}``: what a DETAIL binding (many rows per object, no clock) rolls up to
    #: one value per object; a detail binding supplies exactly these.
    rollups: Optional[dict[str, dict]] = None
    #: ON-7 — when the source table is another type's own table, mark that type a PART of this one (hidden from
    #: the map, listed under this type). The mark holds only while this binding does.
    absorb: Optional[bool] = None
    #: ``{property: column}``. Absent, every column but the key is supplied under its own name, and a name the type
    #: already uses is skipped with the reason.
    properties: Optional[dict[str, str]] = None
    #: ON-5 — ``{property: {column, agg, range, window, offset}}``: frames over a timeseries binding's readings,
    #: each becoming a property of the type read at the object's latest reading.
    frames: Optional[dict[str, dict]] = None


class _EntityOverride(BaseModel):
    description: Optional[str] = None
    backing: Optional[_BackingSpec] = None
    active_filter: Optional[str] = None
    default_filters: Optional[list[str]] = None
    exclude_when: Optional[list[str]] = None
    lifecycle_states: Optional[list[str]] = None
    terminal_states: Optional[list[str]] = None
    # NOTE: this model is narrower than `_EDITABLE["entity"]` — `display_name` and
    # `domain` are editable in the store but have never been reachable through this
    # endpoint. Anything absent here is dropped by the `model_dump()` filter below, so
    # a new editable field must be added in BOTH places or it silently does nothing.
    use_instead: Optional[_UseInstead] = None
    #: ON-3b — the property whose value names one object of this type; it must be a property the type has.
    display_property: Optional[str] = None
    #: ON-7 — the id of the type this one is a part of; "" releases it. Bound against the graph: the parent must
    #: carry a binding over this type's own table, and the mark holds only while it does.
    absorbed_into: Optional[str] = None


class _DeclaredBacking(BaseModel):
    """ON-7 — the source whose rows ARE a declared type's objects."""
    table: Optional[str] = None
    sql: Optional[str] = None
    primary_key: str
    #: ON-8 — in an organisation's ontology (`?domain=`): the connection the rows live on, and the schema that
    #: qualifies a bare table there.
    connection_id: Optional[str] = None
    schema_name: Optional[str] = None


class _DeclaredEntity(BaseModel):
    """ON-7 — a business entity declared by a person (or an explorer, ON-7b): the noun first, the table bound
    into it."""
    id: str
    display_name: str
    description: Optional[str] = None
    domain: Optional[str] = None
    entity_type: Optional[Literal["reference_data", "business_object", "event", "standalone"]] = None
    backing: _DeclaredBacking
    origin: Optional[Literal["human", "model"]] = None
    #: who proposed it, `model:<id>@<version>` — a person confirming a model's proposal declares `origin: human`
    #: and keeps the model's provenance beside it
    provenance: Optional[str] = Field(default=None, max_length=200)


class _DeclaredLink(BaseModel):
    """ON-7 — a link declared between two types: a business verb and the column each side joins on."""
    from_entity: str
    to_entity: str
    name: str
    from_column: str
    to_column: str
    cardinality: Optional[Literal["1:1", "1:N", "N:1", "N:N"]] = None
    reverse_name: Optional[str] = None
    origin: Optional[Literal["human", "model"]] = None
    provenance: Optional[str] = Field(default=None, max_length=200)


class _DeclaredPromise(BaseModel):
    """ON-9 — what the business promises about reaching a stage: within N calendar days of the previous stage, within N
    hours of its moment, or by a deadline property of the object that carries it (`grain`, reached from it through
    `via`)."""
    name: Optional[str] = None
    within_days: Optional[int] = None
    within_hours: Optional[int] = None
    deadline: Optional[str] = None
    grain: Optional[str] = None
    via: Optional[str] = None
    target: Optional[float] = None


class _DeclaredStage(BaseModel):
    """ON-9 — one stage, anchored to the moment an object reaches it or to the states that place it there."""
    name: str
    display_name: Optional[str] = None
    timestamp: Optional[str] = None
    state: Optional[list[str]] = None
    property: Optional[str] = None
    promise: Optional[_DeclaredPromise] = None


class _DeclaredProcess(BaseModel):
    """ON-9 — a process one object type goes through: its stages in order."""
    id: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    entity: str
    stages: list[_DeclaredStage]
    owner: Optional[str] = None
    origin: Optional[Literal["human", "model", "pack"]] = None
    provenance: Optional[str] = Field(default=None, max_length=200)


class _DeclaredRule(BaseModel):
    """ON-9 — a named, owned definition over one type: a value set, or conditions in the object door's shape."""
    id: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    entity: str
    kind: Literal["value_set", "condition"] = "condition"
    property: Optional[str] = None
    values: Optional[list] = None
    conditions: Optional[list[dict]] = None
    #: The verified metrics on its type the rule scopes: each read within it wherever it is read.
    scopes: Optional[list[str]] = None
    owner: Optional[str] = None
    origin: Optional[Literal["human", "model", "pack"]] = None
    provenance: Optional[str] = Field(default=None, max_length=200)


class _ActionOverride(BaseModel):
    description: Optional[str] = None
    sql_template: Optional[str] = None
    business_rules_enforced: Optional[list[str]] = None
    returns: Optional[str] = None


class _KineticActionBody(BaseModel):
    """Wave K5 — author a DECLARED KineticAction (distinct from the read-side _ActionOverride)."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    entity: Optional[str] = None
    kind: Optional[str] = None                       # annotate | side_effect | query
    params: Optional[list] = None
    rule: Optional[str] = None
    submission_criteria: Optional[list] = None       # each {expr, message}
    side_effects: Optional[list] = None              # each {kind, config}
    risk: Optional[str] = None                       # read_only | low | high
    origin: Optional[str] = None
    object_type: Optional[str] = None                # ON-4 — the object type the action is about
    edits: Optional[list] = None                     # ON-4 — each {object, property, value, note}


class _MergeEntitiesRequest(BaseModel):
    merge_ids: list[str]      # the cluster of entity ids to merge (must include canonical_id)
    canonical_id: str         # the survivor — others are merged into it
    #: Per other type, the column of its table that holds the survivor's key — when that is not the type's own key.
    keys: dict[str, str] = Field(default_factory=dict)


class _ColumnConfigEdit(BaseModel):
    """One human edit to one column's {visible, sample, index} config (R11).
    Only the flags present in the body change; the entry becomes source=human."""
    table: str
    column: str
    visible: Optional[bool] = None
    sample: Optional[bool] = None
    index: Optional[bool] = None
    note: str = ""


class _ComputedPropertyOverride(BaseModel):
    label: Optional[str] = None
    formula_sql: Optional[str] = None
    unit: Optional[str] = None


class _SegmentOverride(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    filter_sql: Optional[str] = None
    is_default: Optional[bool] = None


class _MetricOverride(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    formula_sql: Optional[str] = None
    grain: Optional[str] = None
    unit: Optional[str] = None
    entity: Optional[str] = None   # required only when authoring a brand-new metric


def _resolve_schema(connection_id: str, schema_name: Optional[str]) -> str:
    """Return the effective schema name: explicit param > connection meta > 'default'."""
    if schema_name:
        return schema_name
    try:
        meta = get_meta(connection_id)
        return meta.get("schema_name") or "default"
    except Exception:
        return "default"


#: Public name for the effective-schema rule, for callers outside this router (the
#: converse tool roster's `propose_context_note` resolves the same schema the ontology
#: routes write to — one rule, so an agent note lands where the UI reads it).
resolve_effective_schema = _resolve_schema


def _domain_scope(domain: Optional[str]):
    """ON-8 — the organisation's ontology a request names (`?domain=`); 400 when the name cannot be a domain's."""
    from aughor.ontology.domains import DomainRefused, resolve_domain
    try:
        return resolve_domain(domain)
    except DomainRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


def _open_source(connection_id: str):
    """ON-8 — one registered connection, opened for a domain declaration to read its source on."""
    return open_connection_for(connection_id)


def _domain_door(run):
    """ON-8 — a domain door's body, its refusal answered with the status it carries."""
    from aughor.ontology.domains import DomainRefused
    try:
        return run()
    except DomainRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


def _own_connection_spec(spec: dict, connection_id: str) -> dict:
    """ON-8 — a binding spec on ONE connection's ontology: a source on another connection is refused with where it
    belongs, and a schema qualifies a bare table."""
    spec = dict(spec)
    foreign = str(spec.pop("connection_id", "") or "").strip()
    if foreign and foreign != connection_id:
        raise HTTPException(status_code=400, detail=(
            f"a source on another connection ({foreign}) is bound in an organisation's ontology — send this with "
            "?domain=default; one connection's ontology reads its own connection only"))
    schema = str(spec.pop("schema_name", "") or "").strip()
    if schema and spec.get("table") and "." not in str(spec["table"]):
        spec["table"] = f"{schema}.{spec['table']}"
    return spec


def _own_connection_backing(spec: dict, connection_id: str) -> dict:
    """ON-8 — a declared type on ONE connection's ontology reads that connection: another one is refused with where the
    declaration belongs."""
    spec = dict(spec)
    backing = dict(spec.get("backing") or {})
    foreign = str(backing.pop("connection_id", "") or "").strip()
    if foreign and foreign != connection_id:
        raise HTTPException(status_code=400, detail=(
            f"a type whose rows live on another connection ({foreign}) is declared in an organisation's ontology — send "
            "this with ?domain=default; one connection's ontology reads its own connection only"))
    spec["backing"] = backing
    return spec


def cached_ontology_schemas(connection_id: str) -> list[str]:
    """The schemas that actually HAVE a cached ontology for this connection."""
    try:
        from aughor.ontology.store import list_schemas
        return list_schemas(connection_id)
    except Exception:
        return []


def _get_ontology_graph(connection_id: str, schema_name: Optional[str] = None):
    """The cached OntologyGraph for this {connection, schema}, or None.

    🔴🔴 **THIS READ NEVER BUILDS.** It used to fall through to
    `db.build_intelligence()` when nothing was cached — a heavy path (render the
    schema, profile every column, infer + enrich + validate the ontology) whose own
    docstring says "call this from a background task, never on the hot path". Measured
    on the live instance: `GET /ontology?connection_id=workspace&schema_name=main`
    never returned. Not an error, not a slow answer — the request simply hung, and the
    Ontology panel showed nothing at all for as long as anyone was willing to wait.
    A read that can block for minutes is a broken read however correct its answer.
    Building is now exclusively the job of `POST /ontology/rebuild`, which is gated,
    audited, and clicked on purpose.

    🔴 **An explicit `schema_name` is a SCOPE, not a hint.** Before, an unbuilt schema
    fell back to `load_latest_ontology(connection_id, None)` — whatever was cached last
    — so `?schema_name=no_such_schema_xyz` answered with the `ecommerce` graph, nine
    entities and all, under the requested name. Every panel asking for schema X could
    be handed schema Y's entities, relationships, metrics and actions, with nothing on
    screen saying so.

    The ONE substitution that is not a leak: a connection with exactly one cached
    ontology has no other schema to confuse it with. That case is real and common,
    because the schema NAME the UI asks with comes from the catalog tree while the
    cache key comes from whoever built it — a gsheets connection is browsed as
    `spotify` and cached as `default`. The graph carries its own `schema_name`, so the
    answer still states which schema it is; the panel prints that, not the request.
    """
    try:
        from aughor.ontology.store import load_latest_ontology
        if not schema_name:
            # No scope asked for: the connection's OWN configured schema first, then
            # the any-schema scan (legacy callers that genuinely do not know one).
            return (load_latest_ontology(connection_id, _resolve_schema(connection_id, None))
                    or load_latest_ontology(connection_id, None))

        graph = load_latest_ontology(connection_id, schema_name)
        if graph is not None:
            # load_latest_ontology already overlays human overrides (the shared
            # authority seam), so the read APIs / UI reflect edits for free.
            return graph

        built = cached_ontology_schemas(connection_id)
        if len(built) == 1:
            return load_latest_ontology(connection_id, built[0])
        return None
    except Exception:
        return None


#: Public name for the served-graph read, for callers outside this router: the object plane
#: (routers/objects.py) and the converse `query_objects` tool compile against exactly the graph
#: `GET /ontology` returns, under the same scope rule — one read, never a second opinion.
served_ontology_graph = _get_ontology_graph


def _latest_fingerprint(connection_id: str, schema_name: Optional[str] = None) -> Optional[str]:
    from aughor.ontology.store import _load, _schema_prefix
    cache = _load()
    effective = _resolve_schema(connection_id, schema_name)
    prefix = _schema_prefix(connection_id, effective)
    matches = [k for k in cache if k.startswith(prefix)]
    if not matches:
        return None
    # key = "{conn_id}:{schema_name}:{fingerprint}" — return the fingerprint part
    last = matches[-1]
    return last[len(prefix):]


# ── Read endpoints ─────────────────────────────────────────────────────────────

@router.get("/ontology/schemas")
def list_ontology_schemas(connection_id: str = BUILTIN_ID):
    """List the DB schemas that have a cached ontology for this connection."""
    from aughor.ontology.store import list_schemas
    schemas = list_schemas(connection_id)
    # Always include the connection's configured schema even if not yet cached
    try:
        meta = get_meta(connection_id)
        configured = meta.get("schema_name") or "default"
        if configured not in schemas:
            schemas = [configured] + schemas
    except Exception:
        pass
    return {"schemas": schemas}


@router.get("/ontology")
def get_ontology(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        # The 404 names the way out. "Not available" is true and useless; the caller
        # needs to know whether the ontology exists under a DIFFERENT schema (switch
        # scope) or nowhere at all (build it) — and the read no longer builds, so the
        # panel has to offer that door rather than wait for one.
        built = cached_ontology_schemas(connection_id)
        detail = (
            f"No ontology built for schema '{schema_name}'. Built for: {', '.join(built)}."
            if schema_name and built
            else "No ontology has been built for this connection yet."
        )
        raise HTTPException(status_code=404, detail=detail,
                            headers={"X-Ontology-Schemas": ",".join(built)})
    return graph.model_dump()


def _graph_domain_aggregation(cg) -> dict:
    """Level-1 anti-hairball data: table nodes grouped by domain, and cross-domain
    join edges COLLAPSED to one aggregated edge per domain pair with a count — so the
    top level is a handful of cards, never a hairball."""
    domains: dict[str, list[str]] = {}
    for n in cg.nodes.values():
        if n.kind == "table":
            dom = (n.data or {}).get("domain") or "Ungrouped"
            domains.setdefault(dom, []).append(n.id)
    table_domain = {tid: dom for dom, ids in domains.items() for tid in ids}
    pair_counts: dict[tuple, int] = {}
    for e in cg.edges.values():
        if e.kind == "joins_on":
            a, b = table_domain.get(e.from_id), table_domain.get(e.to_id)
            if a and b and a != b:
                key = tuple(sorted((a, b)))
                pair_counts[key] = pair_counts.get(key, 0) + 1
    return {
        "domains": [{"label": d, "tables": ids, "table_count": len(ids)}
                    for d, ids in sorted(domains.items())],
        "domain_edges": [{"from": a, "to": b, "count": c}
                         for (a, b), c in sorted(pair_counts.items())],
    }


@router.get("/graph")
def get_context_graph(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave C4 — the connection knowledge graph for the anti-hairball surface: the full
    nodes + edges + provenance, PLUS a level-1 domain aggregation (cross-domain joins
    collapsed to counts) and the typed staleness state. Builds on demand when a graph is
    not yet committed."""
    from aughor.org.context import current_org_id
    from aughor.ontology.context_graph_search import merge_graphs
    from aughor.ontology.context_graph_store import load_graphs_for_connection

    org = current_org_id()
    cg = merge_graphs(load_graphs_for_connection(org, connection_id))
    if cg is None:
        from aughor.ontology.context_graph_build import build_context_graph
        cg = build_context_graph(connection_id, schema_name, org_id=org)
    if cg is None:
        raise HTTPException(status_code=404,
                            detail="No knowledge graph for this connection (build it first)")

    payload = cg.model_dump()
    payload["counts"] = cg.counts()
    payload.update(_graph_domain_aggregation(cg))
    _stamp_warrants(payload, cg)
    try:
        from aughor.ontology.graph_freshness import staleness_of
        # Compare against the ontology for the GRAPH's own schema (the committed graph may
        # live under a different schema than the request's active-schema hint).
        payload["staleness"] = staleness_of(connection_id, cg.schema_name or schema_name, org_id=org)
    except Exception:
        payload["staleness"] = "unknown"
    return payload


def _stamp_warrants(payload: dict, cg) -> None:
    """Wave P2 — attach the derived warrant class to every node and edge in a response.

    Derived at READ time and never written to the artifact: the committed graph stays the
    structural truth, and a graph built before this wave gets its warrants for free. Best
    effort — a surface that cannot classify still renders the graph.
    """
    from aughor.kernel.errors import tolerate
    try:
        from aughor.ontology.graph_warrant import warrant_of_edge, warrant_of_node
    except Exception as exc:
        tolerate(exc, "warrant stamping is a read-time annotation; the graph renders without it",
                 counter="context_graph.warrant_stamp")
        return
    # Per ITEM, not per pass: one node that raises used to leave every node after it in
    # dict order unstamped, with no error and nothing to distinguish it from "warrants
    # unavailable".
    for nid, raw in (payload.get("nodes") or {}).items():
        node = cg.nodes.get(nid)
        if node is None:
            continue
        try:
            raw["warrant"] = warrant_of_node(node).to_dict()
        except Exception as exc:
            tolerate(exc, f"warrant for node {nid} could not be derived",
                     counter="context_graph.warrant_stamp")
    for eid, raw in (payload.get("edges") or {}).items():
        edge = cg.edges.get(eid)
        if edge is None:
            continue
        try:
            raw["warrant"] = warrant_of_edge(edge).to_dict()
        except Exception as exc:
            tolerate(exc, f"warrant for edge {eid} could not be derived",
                     counter="context_graph.warrant_stamp")


@router.get("/graph/audit")
def get_context_graph_audit(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave P2 — the graph's honesty scorecard: how much of it is measured, and how much
    is a name match.

    One call, because the three honesty signals are only meaningful together: the warrant
    mix says how *well-founded* the graph is, `staleness` says whether the SCHEMA still
    matches, and `drift` says whether the graph still holds what the platform has since
    learned. A surface showing any one alone can read as reassurance — a Fresh badge over
    a graph of unprobed name matches is exactly the shape this wave refuses.
    """
    from aughor.ontology.graph_warrant import audit
    from aughor.org.context import current_org_id

    org = current_org_id()
    cg = _load_graph_or_404(connection_id, schema_name)
    out = {"connection_id": connection_id, "schema_name": cg.schema_name,
           "graph_version": cg.version, **audit(cg)}
    try:
        from aughor.ontology.graph_freshness import staleness_of
        out["staleness"] = staleness_of(connection_id, cg.schema_name or schema_name, org_id=org)
    except Exception:
        out["staleness"] = "unknown"
    try:
        from aughor.ontology.graph_freshness import content_drift
        out["drift"] = content_drift(connection_id, cg.schema_name or schema_name,
                                     org_id=org).to_dict()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "content drift is a second axis; the audit still reports the warrant mix",
                 counter="context_graph.audit_drift")
        out["drift"] = None
    return out


def _load_graph_or_404(connection_id: str, schema_name: Optional[str]):
    from aughor.ontology.context_graph_search import merge_graphs
    from aughor.ontology.context_graph_store import load_graphs_for_connection
    from aughor.org.context import current_org_id
    org = current_org_id()
    cg = merge_graphs(load_graphs_for_connection(org, connection_id))
    if cg is None:
        from aughor.ontology.context_graph_build import build_context_graph
        cg = build_context_graph(connection_id, schema_name, org_id=org)
    if cg is None:
        raise HTTPException(status_code=404,
                            detail="No knowledge graph for this connection (build it first)")
    return cg


@router.get("/graph/drift")
def get_graph_content_drift(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Is a rebuild owed? — the content axis `staleness` deliberately does not cover.

    `staleness` answers "does the schema still match" and reported **fresh** for a graph
    holding 0 findings and 3 glossary terms whose sources held 100 and 255: true in the only
    sense it claims, and read by a human as "up to date". This reports the shortfall in the
    projection's own numbers, so a Fresh badge can never stand alone over a graph that is
    missing what the platform has already learned.

    Costs an in-memory projection (no LLM, no warehouse), which is why it is a separate call
    rather than part of every `/graph` read.
    """
    from aughor.ontology.graph_freshness import content_drift
    from aughor.org.context import current_org_id

    drift = content_drift(connection_id, schema_name, org_id=current_org_id())
    return {"connection_id": connection_id, **drift.to_dict()}


@router.get("/graph/lineage")
def get_context_graph_lineage(
    connection_id: str = BUILTIN_ID,
    node_id: Optional[str] = Query(default=None),
    table: Optional[str] = Query(default=None),
    schema_name: Optional[str] = Query(default=None),
):
    """Wave P4 — what depends on this node, with the expression that would break.

    The lineage walker (`govern/lineage.py`) has been built and tested since Wave G7 with
    no route and no caller: the question "what breaks if this table changes" was answerable
    and unasked. This is the seam.

    Each dependent carries its **site** — the line of the finding's SQL, or the metric
    formula, that names the thing in question. A dependency list without sites says which
    artifacts to open; with them it says what to look at once open.
    """
    from aughor.govern.lineage import dependents_of

    if not node_id and not table:
        raise HTTPException(status_code=400, detail="Pass either node_id or table")
    cg = _load_graph_or_404(connection_id, schema_name)

    root = node_id
    if not root:
        bare = str(table or "").split(".")[-1].lower()
        for nid, n in cg.nodes.items():
            if n.kind != "table":
                continue
            names = {str(s).split(".")[-1].lower()
                     for s in ((n.data or {}).get("source_tables") or [])}
            if bare in names or bare == nid.split(":", 1)[-1].lower():
                root = nid
                break
        if not root:
            raise HTTPException(status_code=404,
                                detail=f"No table `{table}` in this connection's graph")
    elif root not in cg.nodes:
        raise HTTPException(status_code=404, detail=f"No node `{root}` in this graph")

    report = dependents_of(cg, root)
    node = cg.nodes.get(root)
    return {"connection_id": connection_id, "node_id": root,
            "label": getattr(node, "label", "") or root,
            **report.to_dict()}


@router.get("/graph/review")
def get_context_graph_review(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Wave P5 — what the graph knows it cannot vouch for.

    The proactive half of "check every node": rather than waiting for a question and
    explaining it afterwards, the graph reports the nodes worth checking BEFORE one is
    asked — unprobed joins, isolated tables, findings that disagree, undocumented hubs.

    Deterministic and LLM-free. Ranked by how many other nodes depend on the thing in
    doubt, never by an invented severity score.
    """
    from aughor.ontology.graph_questions import queue_summary, review_queue_with_total
    from aughor.org.context import current_org_id

    cg = _load_graph_or_404(connection_id, schema_name)
    drift = None
    try:
        from aughor.ontology.graph_freshness import content_drift
        drift = content_drift(connection_id, cg.schema_name or schema_name,
                              org_id=current_org_id()).to_dict()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "drift is one input to the review queue; the structural checks still run",
                 counter="context_graph.review_drift")

    items, found = review_queue_with_total(cg, drift=drift, limit=limit)
    return {"connection_id": connection_id, "schema_name": cg.schema_name,
            "graph_version": cg.version,
            "items": [i.to_dict() for i in items],
            **queue_summary(items, total_found=found)}


@router.get("/graph/trust")
def get_context_graph_trust(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave P3 — what standing each node has earned.

    A read-time SIDECAR: nothing here is written to the committed artifact, so a
    conclusion about a node can never outlive the evidence for it.

    On a warehouse where nobody has recorded a verdict, every node reads `unchecked` —
    that is the honest report, not an empty feature, and `human_signal: false` says so
    in one field rather than leaving a reader to infer it from a row of zeros.
    """
    from aughor.ontology.graph_trust import trust_for_connection
    from aughor.org.context import current_org_id

    cg = _load_graph_or_404(connection_id, schema_name)
    return trust_for_connection(connection_id, cg, org_id=current_org_id()).to_dict()


@router.get("/graph/tour")
def get_context_graph_tour(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    narrate: bool = Query(default=False),
):
    """Wave C5 — the connection tour: a reading order computed from graph TOPOLOGY (hub entry →
    BFS → metrics capstone), a curriculum rather than a listicle. Deterministic by default;
    ``narrate=true`` adds a one-time LLM narration over the already-fixed order."""
    cg = _load_graph_or_404(connection_id, schema_name)
    from aughor.ontology.graph_tour import build_tour, narrate_tour
    tour = build_tour(cg)
    if narrate:
        tour = narrate_tour(tour)
    return tour.model_dump()


@router.get("/ontology/entities")
def get_ontology_entities(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {eid: e.model_dump() for eid, e in graph.entities.items()}


@router.get("/ontology/relationships")
def get_ontology_relationships(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {rid: r.model_dump() for rid, r in graph.relationships.items()}


def _claims_out(claims, pack: Optional[str], connection_id: str, schema_name: Optional[str]) -> Optional[dict]:
    """A claims summary, saying whether the pack it names is DEPLOYED on this connection (active and bound).

    A person may measure any pack's map against their data — that is how a package is reviewed before it is
    activated (§3.17 gate 6). The claims are saved and shown, and the explorer's prompt reads only a deployed
    pack's confirmed claims, so this flag is the difference a reader has to see.
    """
    if claims is None:
        return None
    out = claims.summary()
    if pack:
        from aughor.packs.ontology_map import bound_pack_ids
        out["deployed"] = pack in bound_pack_ids(connection_id, schema_name)
    return out


@router.post("/ontology/measure", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def measure_ontology(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    pack: Optional[str] = Query(default=None, description="A pack id whose industry map is evaluated as claims (ON-0a); packs deployed on the connection apply regardless. Any pack may be named — reviewing a draft package against your data is what gate 6 asks for — and the answer says whether it is deployed here; only a deployed pack's confirmed claims reach a prompt"),
    domain: Optional[str] = Query(default=None, description="ON-8 — measure an organisation's ontology instead: every declaration in the domain, on the connections it names"),
):
    """Measure the cached ontology against the live data and save what it says — no model
    call, no rebuild (ON-0a).

    Two measurements: relationship cardinality (a side is "1" when its key is unique over
    its non-null rows; a contradicted label is replaced, the authored one kept in a note)
    and lifecycle terminal states (an observed state the lists never named, or a claimed
    terminal state whose timestamp is set on rows now in another state, contradicts the
    lifecycle; end-state names the terminal set omits are reported as unconfirmed). The
    builder inferred both and marked them verified on key overlap and execution alone. A
    rebuild measures now but spends a model call per entity; this door measures the graph
    that is already there, invalidates the enriched-schema cache that embeds the blocks,
    and journals `ontology.measure`.
    """
    if domain is not None:
        from aughor.ontology.domains import measure_domain
        scope = _domain_scope(domain)
        return _domain_door(lambda: measure_domain(scope, _open_source))
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.store import measure_latest
    effective = _resolve_schema(connection_id, schema_name)
    db = open_connection_for_with_schema(connection_id, effective)
    try:
        reports = measure_latest(connection_id, effective, db, pack_id=pack)
    finally:
        db.close()
    if reports is None:
        raise HTTPException(
            status_code=404,
            detail=f"No ontology built for schema '{effective}' on this connection — nothing to measure.")
    _invalidate_schema_cache(connection_id)
    claims = reports.get("claims")
    out = {"connection_id": connection_id, "schema_name": effective,
           "relationships": reports["relationships"].summary(),
           "lifecycles": reports["lifecycles"].summary(),
           "backings": reports["backings"].summary(),
           "display_properties": reports["display_properties"].summary(),
           "bindings": reports["bindings"].summary(),
           # ON-7 — every declared link, its sides counted again on this pass.
           "declared_links": reports.get("declared_links", []),
           # ON-9 — every declared process and rule, counted again on this pass.
           "processes": reports.get("processes", []),
           "rules": reports.get("rules", []),
           "claims": _claims_out(claims, pack, connection_id, effective)}
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("ontology.measure", {"ok": True, "schema": effective,
                                                   "relationships": out["relationships"],
                                                   "lifecycles": out["lifecycles"]},
                              conn_id=connection_id)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("ontology.measure emit skipped", exc_info=True)
    return out


@router.get("/ontology/metrics/{metric_id}/provenance")
def get_metric_provenance(
    metric_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Every recorded definition of one metric, who is behind each, and which one wins.

    The panel beside an answer reads this. It exists because "revenue" having two
    definitions is not a bug to resolve quietly — it is a fact about the business that the
    person reading the number is entitled to see, along with whose definition they are
    looking at.

    Harvest is best-effort per SOURCE: a deployment with no overrides, or a history store
    that cannot be read, still returns the claims the other sources could evidence. What
    it must never do is return a definition it could not evidence, so a failed source
    contributes nothing rather than a placeholder.
    """
    from aughor.ontology import harvest as harvest_mod
    from aughor.ontology.authority import choose

    graph = _get_ontology_graph(connection_id, schema_name)
    metric = (graph.metrics.get(metric_id) if graph is not None else None)
    if metric is None:
        raise HTTPException(status_code=404, detail="No such metric")

    overrides = []
    try:
        from aughor.ontology.overrides import load_overrides
        overrides = [o for o in load_overrides(connection_id, schema_name or "")
                     if getattr(o, "target_kind", "") == "metric"
                     and getattr(o, "target_id", "") == metric_id]
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "override harvest is per-source best-effort",
                 counter="ontology.provenance.overrides")

    registry = None
    try:
        from aughor.semantic.metrics import list_metrics
        registry = next((m for m in list_metrics(connection_id=connection_id)
                         if getattr(m, "name", "") == metric_id
                         or getattr(m, "label", "") == metric.display_name), None)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "registry harvest is per-source best-effort",
                 counter="ontology.provenance.registry")

    executed: list[str] = []
    try:
        from aughor.db.history import recent_executed_sql
        executed = recent_executed_sql(connection_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "reliance is a tiebreak, never a blocker",
                 counter="ontology.provenance.reliance")

    definitions = harvest_mod.harvest(harvest_mod.Evidence(
        overrides=overrides, registry=registry, executed_sql=executed))

    # The graph's OWN formula is a claim too, and often the only one — but it is only
    # `verified` if the graph says it was bound, never because it is the incumbent.
    if metric.formula_sql.strip() and not any(
            d.formula_sql.strip() == metric.formula_sql.strip() for d in definitions):
        from aughor.ontology.models import DefinitionSource
        definitions.append(DefinitionSource(
            formula_sql=metric.formula_sql, source_asset="the ontology graph",
            source_kind="table", verified=bool(metric.verified),
            verification_note=metric.verification_note,
            use_count=harvest_mod.reliance(metric.formula_sql, executed)))

    chosen = choose(definitions)
    return {
        "metric_id": metric_id,
        "display_name": metric.display_name,
        "definitions": [d.model_dump() for d in definitions],
        "chosen": chosen.winner.model_dump() if chosen.winner else None,
        "dissenter": chosen.dissenter.model_dump() if chosen.dissenter else None,
        "contested": chosen.contested,
        "why": chosen.why,
        # Recorded divergences the graph already knew about, for the same panel.
        "known_divergent_calculations": list(metric.known_divergent_calculations),
    }


@router.get("/ontology/duplicate-entities")
def get_duplicate_entities(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    threshold: float = Query(default=0.85, ge=0.5, le=1.0),
):
    """Near-duplicate entity clusters (embedding self-similarity + connected components), as merge
    SUGGESTIONS — never applied. A read; empty when embeddings are unavailable or nothing clusters."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    # CB-4 — a pair a person rejected is not offered again: the read applies the scope's decisions.
    from aughor.ontology.dedup_decisions import detect_with_decisions
    return detect_with_decisions(graph, connection_id, schema_name or "default", threshold=threshold)


class _RejectDuplicates(BaseModel):
    entity_ids: list[str]
    reason: str = ""


@router.post("/ontology/duplicate-entities/reject", status_code=201, dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def reject_duplicate_entities(
    body: _RejectDuplicates,
    request: Request,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """CB-4 — "these are different": record it, with the reason and who said so, so the pair is not
    suggested again. Two or more ids; every pair among them is rejected."""
    from aughor.ontology.dedup_decisions import reject
    principal = getattr(request.state, "principal", None)
    by = next((str(getattr(principal, a)) for a in ("user_id", "email", "id") if getattr(principal, a, "")), "")
    try:
        rows = reject(connection_id, schema_name or "default", body.entity_ids, reason=body.reason, rejected_by=by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"rejected": rows}


@router.delete("/ontology/duplicate-entities/reject", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def reconsider_duplicate_entities(
    a: str = Query(...),
    b: str = Query(...),
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """CB-4 — take a rejection back; the pair may be suggested again."""
    from aughor.ontology.dedup_decisions import reconsider
    if not reconsider(connection_id, schema_name or "default", a, b):
        raise HTTPException(status_code=404, detail="no rejection for that pair")
    return {"ok": True}


@router.get("/ontology/actions")
def get_ontology_actions(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {aid: a.model_dump() for aid, a in graph.actions.items()}


@router.get("/ontology/kinetic-actions")
def get_kinetic_actions(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave K: human-declared governed actions overlaid onto the graph. Read-only — empty unless
    the connection has declared actions in its ontology overrides (the plane is always on; the
    `kinetic.actions` flag was deleted 2026-08-02). These are NOT executed here (that is the K2
    executor); this surfaces what is declared, for the authoring UI and for the agent's action
    prompt-section."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    # DS-13 — masked, never raw. This feeds the authoring form, which must be able to show
    # that a credential is SET without being able to read it back out.
    from aughor.ontology.models import mask_action_secrets
    return {a.id: mask_action_secrets(a.model_dump()) for a in graph.declared_actions()}


@router.get("/ontology/entities/{entity_id}/segments")
def get_entity_segments(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Return every saved, named filter (segment) on an entity — keyed by segment id."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return {sid: s.model_dump() for sid, s in entity.segments.items()}


@router.get("/ontology/entities/{entity_id}/object-sets", deprecated=True)
def get_entity_object_sets(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """DEPRECATED alias of ``GET /ontology/entities/{entity_id}/segments``.

    Identical payload — it delegates to the handler above. Kept so a client pinned to the
    old path keeps working for one release; use ``/segments``.
    """
    return get_entity_segments(entity_id, connection_id, schema_name)


@router.get("/ontology/entities/{entity_id}/properties")
def get_entity_properties(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Return the EntityProperty map for a single entity — keyed by column name."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return {name: prop.model_dump() for name, prop in entity.properties.items()}


@router.get("/ontology/interfaces")
def get_ontology_interfaces(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Return all detected OntologyInterfaces for this schema — keyed by interface id."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {iid: iface.model_dump() for iid, iface in graph.interfaces.items()}


@router.get("/ontology/metrics")
def get_ontology_metrics(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {mid: m.model_dump() for mid, m in graph.metrics.items()}


# ── Override (write) endpoints ─────────────────────────────────────────────────
#
# Overrides are persisted to the fingerprint-INDEPENDENT YAML overlay
# (aughor/ontology/overrides.py), NOT the structural fingerprint cache, so they
# survive every rebuild (a row-count change re-fingerprints and rebuilds). SQL
# fields are EXPLAIN-bound against the live DB before they can earn authority.

def _explain_for(connection_id: str):
    """Return (explain_fn, closer): explain_fn(sql) -> error-or-None via dry_run."""
    db = open_connection_for(connection_id)

    def _explain(sql: str) -> Optional[str]:
        ok, msg = db.dry_run(sql)
        return None if ok else (msg or "did not bind")

    def _close():
        try:
            db.close()
        except Exception:
            pass

    return _explain, _close


def _bind_and_persist(connection_id: str, schema: str, ov):
    """EXPLAIN-bind the override's SQL fields, persist it, and return (ov, graph)."""
    from aughor.ontology.overrides import EXISTENCE_FIELDS, bind_overrides, save_override
    graph = _get_ontology_graph(connection_id, schema)
    try:
        explain, close = _explain_for(connection_id)
        try:
            bind_overrides(ov, graph, explain)
        finally:
            close()
    except Exception as exc:
        # Binding is best-effort for SQL fields: unbound SQL simply won't earn
        # `verified`. But an EXISTENCE field must never come back with an empty
        # binding — `verified` is `all(...) if binding else True`, so silence there
        # reads as "checked and fine" for a table nobody could look for. When the
        # connection itself is unreachable, say THAT rather than nothing — and the
        # graph-only binds (a display property, a part mark) still get their verdict.
        from aughor.ontology.overrides import bind_graph_only
        bind_graph_only(ov, graph)
        for field in ov.fields:
            if field in EXISTENCE_FIELDS and field not in ov.binding:
                ov.binding[field] = {
                    "bound": False,
                    "note": f"could not reach the connection to check: {str(exc)[:160]}",
                }
    save_override(connection_id, schema, ov)
    return ov, graph


def _override_result(ov) -> dict:
    """Response shape: the saved override + whether its SQL bound + any warnings."""
    warnings = [f"{f}: {b.get('note')}" for f, b in ov.binding.items() if not b.get("bound")]
    return {
        "override": ov.model_dump(),
        # verified == every SQL field bound (no-SQL override is trivially verified)
        "verified": all(b.get("bound") for b in ov.binding.values()) if ov.binding else True,
        "warnings": warnings,
    }


def _display_property_or_error(connection_id: str, schema: str, entity_id: str, name: str) -> str:
    """ON-3b — the property a display-property edit names, spelled as the type spells it: 404 when the type is not
    in the served graph, 400 with the reason when it cannot name objects (`display.display_property_problem`)."""
    from aughor.ontology.display import display_property_problem
    graph = _get_ontology_graph(connection_id, schema)
    entity = graph.entities.get(entity_id) if graph is not None else None
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    match, problem = display_property_problem(entity, name)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    return match


@router.put("/ontology/entities/{entity_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def override_ontology_entity(
    entity_id: str,
    body: _EntityOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None, description="ON-8 — name the objects of a type of an organisation's ontology"),
):
    # ON-8 — with ``domain``, a declared type of the organisation's ontology takes its display property here and nothing
    # else. The scope the web carries that ontology in reaches this door only beside the ?domain= that names it
    # (`refuse_organisation_scope`), and the store refuses a write to it through one connection's writer besides.
    if domain is not None:
        return _domain_edit_entity(entity_id, body, domain)
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.overrides import OntologyOverride, find_override
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    served = _get_ontology_graph(connection_id, effective)
    if served is not None and entity_id not in served.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    if "display_property" in fields:
        fields["display_property"] = _display_property_or_error(connection_id, effective, entity_id,
                                                                fields["display_property"])
    # MERGE into the entity's existing override rather than replacing its file: a PUT of one field used to
    # wipe a description, a backing or a routing rule already there (the routing-proposal door below merges
    # for the same reason). The kept binding lets a re-bind carry a measurement of an unchanged value.
    existing = find_override(connection_id, effective, "entity", entity_id)
    ov = OntologyOverride(target_kind="entity", target_id=entity_id,
                          fields={**(existing.fields if existing else {}), **fields},
                          source=(existing.source if existing else "human"),
                          binding=dict(existing.binding) if existing else {})
    ov, graph = _bind_and_persist(connection_id, effective, ov)
    if graph is not None and entity_id not in graph.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return _override_result(ov)


def _domain_edit_entity(entity_id: str, body: _EntityOverride, domain: str) -> dict:
    """ON-8 — the DECLARATIVE edits of a type in an organisation's ontology (2026-09-22): its display property
    (measured where it is read), and its description, filters as words, lifecycle states, routing guidance and the
    part mark — none reads a warehouse, so they open on a type whatever connection it lives on. What SQL binds
    (`active_filter`, a backing) stays with the type's own connection and is refused here, saying so."""
    from aughor import govern
    from aughor.ontology.domains import DECLARATIVE_FIELDS, domain_graph, edit_type, set_display_property
    from aughor.semantic.object_types import describe_object_type
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    sql_bound = sorted(set(fields) - DECLARATIVE_FIELDS - {"display_property"})
    if sql_bound or not fields:
        raise HTTPException(status_code=400, detail=(
            "a type of an organisation's ontology takes its declarative fields through this door — its display "
            "property, description, filters as words, lifecycle states, routing guidance and part mark"
            + (f" — not {', '.join(sql_bound)}, which SQL binds on the type's own connection" if sql_bound
               else ", and none was given")
            + "; the type is declared with POST /ontology/entities?domain= and its sources bound with "
              "PUT /ontology/entities/{id}/bindings/{name}?domain="))
    scope = _domain_scope(domain)
    govern.guard("ontology.override", scope.key)  # P4: mutating the semantic layer
    display = fields.pop("display_property", None)
    ov = None
    if fields:
        ov = _domain_door(lambda: edit_type(scope, entity_id, fields))
    if display is not None:
        ov = _domain_door(lambda: set_display_property(scope, entity_id, display, _open_source))
    served = domain_graph(scope)
    return {**_override_result(ov), "entity": describe_object_type(served, entity_id), "domain": scope.key}


@router.put("/ontology/entities/{entity_id}/bindings/{name}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def bind_ontology_entity(
    entity_id: str,
    name: str,
    body: _BindingSpec,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None, description="ON-8 — bind onto a type of an organisation's ontology, from a source on any of its connections"),
):
    """Bind a further source to an object type (ON-1b): a table or keyed SELECT joined to the object on its key,
    supplying properties its backing does not carry. The source is read for its columns first — its key, its time
    column and every property it supplies must exist and be free on the type, or nothing is written (400) — then it is
    counted against the objects: a static binding must hold one row per object, a timeseries binding must reach them.
    Merged into the type's other human edits; the response carries the binding as the entity-type panel shows it.
    No model call. ON-8 — with ``domain`` the type is the organisation's, and the source may live on another
    connection (``connection_id``): read there, and counted against the objects across both."""
    if domain is not None:
        return _domain_bind(entity_id, name, body.model_dump(exclude_none=True), domain)
    return _bind_entity_core(entity_id, name, body.model_dump(exclude_none=True), connection_id, schema_name)


def _bind_entity_core(entity_id: str, name: str, spec: dict, connection_id: str, schema_name: Optional[str], *,
                      origin: str = "human", provenance: str = "") -> dict:
    """The bind door's body, shared with the explorer (ON-7b), which binds what it proposes through exactly this path
    — ``origin="model"`` and its provenance recorded on the bind entry, so the binding reads as proposed until a
    person confirms it."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.bindings import bind_binding, binding_block, declared_bindings, describe_with, measure_binding
    from aughor.ontology.overrides import OntologyOverride, find_override, save_override
    from aughor.semantic.object_types import describe_object_type
    effective = _resolve_schema(connection_id, schema_name)
    spec = _own_connection_spec(spec, connection_id)
    graph = _get_ontology_graph(connection_id, effective)
    entity = graph.entities.get(entity_id) if graph is not None else None
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        spec = dict(spec)
        absorb = bool(spec.pop("absorb", False))
        entry = bind_binding(entity, name, spec, graph, describe_with(db))
        if not entry["bound"]:
            raise HTTPException(status_code=400, detail=f"binding '{name}' on {entity_id} did not bind: {entry['note']}")
        if origin == "model":
            # ON-7b — an explorer's binding: read like any other, proposed until a person confirms it.
            entry = {**entry, "origin": "model", "provenance": provenance}
            if absorb:
                # PENDING item 20 — absorbing hides a type from the map and the agent's catalogue, so a proposal never
                # does it: the table reads both ways until a person confirms the part, and confirming absorbs it.
                entry["absorb_on_confirm"] = True
                absorb = False
        existing = find_override(connection_id, effective, "entity", entity_id)
        fields = dict(existing.fields) if existing else {}
        fields["bindings"] = {**(fields.get("bindings") or {}), name: entry["spec"]}
        kept = dict(existing.binding) if existing else {}
        entries = {**((kept.get("bindings") or {}).get("entries") or {}), name: entry}
        # Count it now, over exactly what the overlay will build, so the verdict arrives while the person is here.
        built, _ = declared_bindings(entity.model_copy(update={"bindings": []}), fields["bindings"],
                                     {"entries": entries}, graph)
        mine = next((b for b in built if b.name == name), None)
        if mine is not None:
            counted = measure_binding(db, entity, mine)
            entries[name] = {**entry, "measured": {"spec": entry["spec"], **counted.counts()}}
        ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields,
                              source=(existing.source if existing else "human"),
                              binding={**kept, "bindings": binding_block(entries)})
        save_override(connection_id, effective, ov)
    finally:
        db.close()
    absorbed, warnings = None, []
    if absorb:
        # ON-7 — the bound table's own type becomes a PART of this one; refused with the reason, never guessed.
        absorbed, why = _absorb_after_bind(connection_id, effective, entity_id, entry["spec"].get("table"))
        if why:
            warnings.append(why)
    elif entry.get("absorb_on_confirm"):
        warnings.append(f"{entry['spec'].get('table')}'s own type stays visible until a person confirms this part; "
                        "confirming it makes that type a part")
    served = _get_ontology_graph(connection_id, effective)
    described = (describe_object_type(served, entity_id)
                 if served is not None and entity_id in served.entities else {})
    row = next((b for b in described.get("bindings", []) if b["name"] == name), None)
    result = _override_result(ov)
    return {**result, "warnings": [*result["warnings"], *warnings], "binding": row,
            "absorbed": absorbed, "parts": described.get("parts", []),
            "absorb_on_confirm": bool(entry.get("absorb_on_confirm"))}


def _merge_entity_fields(connection_id: str, schema: str, entity_id: str, fields: dict):
    """Merge ``fields`` into the entity's existing override (never replacing its file), bind and persist."""
    from aughor.ontology.overrides import OntologyOverride, find_override
    existing = find_override(connection_id, schema, "entity", entity_id)
    ov = OntologyOverride(target_kind="entity", target_id=entity_id,
                          fields={**(existing.fields if existing else {}), **fields},
                          source=(existing.source if existing else "human"),
                          binding=dict(existing.binding) if existing else {})
    return _bind_and_persist(connection_id, schema, ov)


def _absorb_after_bind(connection_id: str, schema: str, parent_id: str, table: Optional[str]) -> tuple[Optional[str], str]:
    """ON-7 — ``(absorbed type id, why not)``: the type whose own rows are ``table``'s is marked a part of
    ``parent_id`` when the mark holds on the served graph; otherwise nothing is written and the reason is returned."""
    from aughor.ontology.declared import backs_existing_type
    from aughor.ontology.parts import absorb_problem
    graph = _get_ontology_graph(connection_id, schema)
    if graph is None or not table:
        return None, "absorb: a keyed SELECT names no table whose type could be absorbed"
    other = backs_existing_type(graph, table)
    if other is None or other.id == parent_id:
        return None, f"absorb: no other object type is read from {table}"
    problem = absorb_problem(graph, parent_id, other)
    if problem:
        return None, f"absorb: {problem}"
    _merge_entity_fields(connection_id, schema, other.id, {"absorbed_into": parent_id})
    return other.id, ""


@router.post("/ontology/entities/{entity_id}/backing/preview", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def preview_ontology_backing(
    entity_id: str,
    body: _BackingPreview,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """What a keyed SELECT would change if it became this type's backing — read, never written: whether it reads, its
    rows and whether its key is unique over them, and the type's properties it keeps, drops (they would stop
    resolving) and adds, beside what the type is read from now. Setting it is `PUT /ontology/entities/{id}` with
    `backing`; `DELETE /ontology/entities/{id}/backing` reads the table again."""
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.backing import preview_backing
    from aughor.ontology.bindings import describe_with
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    entity = graph.entities.get(entity_id) if graph is not None else None
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        return preview_backing(db, entity, body.sql, body.primary_key, describe_with(db))
    finally:
        db.close()


@router.delete("/ontology/entities/{entity_id}/backing", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def withdraw_ontology_backing(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Withdraw the backing a person set on a type: it is read from its table again, and every other edit on it
    stays. 404 when the type has no backing a person set. A declared type's backing IS its declaration, so it is
    refused here — `DELETE /ontology/entities/{id}` withdraws the type."""
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_override, find_override, save_override
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    if existing is None or "backing" not in existing.fields:
        raise HTTPException(status_code=404, detail=f"{entity_id} has no backing a person set")
    if existing.fields.get("declared"):
        raise HTTPException(status_code=400, detail=(
            f"{entity_id} is a declared type: its backing is its declaration — DELETE /ontology/entities/{entity_id} "
            "withdraws the type"))
    fields = {k: v for k, v in existing.fields.items() if k != "backing"}
    if fields:
        binding = {k: v for k, v in existing.binding.items() if k != "backing"}
        save_override(connection_id, effective, existing.model_copy(update={"fields": fields, "binding": binding}))
    else:
        delete_override(connection_id, effective, "entity", entity_id)
    return {"withdrawn": "backing", "entity": entity_id, "kept": sorted(fields)}


@router.delete("/ontology/entities/{entity_id}/bindings/{name}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def unbind_ontology_entity(
    entity_id: str,
    name: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Remove one binding a person set (ON-1b). The type's other human edits stay; the properties that binding
    supplied stop resolving on the next read. 404 when the type has no such binding. ON-8 — with ``domain``, from a
    type in the organisation's ontology."""
    if domain is not None:
        connection_id, schema_name = _domain_scope(domain).tree
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.bindings import binding_block
    from aughor.ontology.overrides import (
        OntologyOverride, delete_organisation_override, delete_override, find_override, save_organisation_override,
        save_override,
    )
    # ON-8 — an organisation's ontology has its own writer, which takes a person's declaration only.
    save, remove = ((save_organisation_override, delete_organisation_override) if domain is not None
                    else (save_override, delete_override))
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    specs = dict((existing.fields.get("bindings") if existing else None) or {})
    if existing is None or name not in specs:
        # 2026-09-22 — a binding no override declared is the BUILDER's (or the data's): withdrawing it is recorded
        # on the type's override, so the next read leaves it out and the UI can restore it.
        from aughor.ontology.bindings import primary_name
        if domain is not None:
            from aughor.ontology.domains import domain_graph
            graph = domain_graph(_domain_scope(domain))
        else:
            graph = _get_ontology_graph(connection_id, effective)
        ent = graph.entities.get(entity_id) if graph is not None else None
        found = next((b for b in (ent.bindings or []) if b.name == name), None) if ent is not None else None
        if found is None:
            raise HTTPException(status_code=404, detail=f"{entity_id} has no binding '{name}'")
        if name == primary_name(ent):
            raise HTTPException(status_code=400, detail=(
                f"'{name}' is {entity_id}'s backing — its objects; DELETE /ontology/entities/{entity_id}/backing "
                "withdraws a backing a person set"))
        fields = dict(existing.fields) if existing is not None else {}
        gone = sorted({*(fields.get("withdrawn_bindings") or []), name})
        ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields={**fields, "withdrawn_bindings": gone},
                              source=(existing.source if existing is not None else "human"),
                              binding=dict(existing.binding) if existing is not None else {})
        save(connection_id, effective, ov)
        return {"removed": True, "entity": entity_id, "binding": name, "withdrawn": True}
    specs.pop(name)
    fields = {k: v for k, v in existing.fields.items() if k != "bindings"}
    binding = {k: v for k, v in existing.binding.items() if k != "bindings"}
    if specs:
        fields["bindings"] = specs
        entries = dict((existing.binding.get("bindings") or {}).get("entries") or {})
        entries.pop(name, None)
        binding["bindings"] = binding_block(entries)
    if fields:
        save(connection_id, effective, OntologyOverride(
            target_kind="entity", target_id=entity_id, fields=fields, source=existing.source, binding=binding))
    else:
        remove(connection_id, effective, "entity", entity_id)
    return {"removed": True, "entity": entity_id, "binding": name}


class _ExpressionSpec(BaseModel):
    """2026-09-22 — a property mapped to a SQL expression over the type's own row."""
    expression: str
    semantic_type: Literal["measure", "dimension"] = "measure"
    unit: str = ""
    description: str = ""


@router.put("/ontology/entities/{entity_id}/expressions/{name}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def declare_ontology_expression(
    entity_id: str,
    name: str,
    body: _ExpressionSpec,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """2026-09-22 — map a typed property to an expression (ON-1b's deferred half). The name must be free on the type,
    the expression must parse flat (no subquery, aggregate or window) over names the object compiler reads — its own
    columns, a binding's, another formula, a to-one link's (PENDING item 27) — and it is VERIFIED through that
    compiler on up to 1,000 of the type's objects before anything is written — a refusal says why and writes nothing.
    The compiler, the framing and the pages then read it like any column."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.expressions import expression_problem, normalized_expression, probe_expression
    from aughor.ontology.overrides import OntologyOverride, find_override, save_override
    from aughor.semantic.object_types import describe_object_type
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    entity = graph.entities.get(entity_id) if graph is not None else None
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    spec = normalized_expression(body.model_dump())
    problem = expression_problem(entity, name, spec, graph)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        verdict = probe_expression(db, graph, entity, spec["expression"], name=name)
    finally:
        db.close()
    if not verdict.get("bound"):
        raise HTTPException(status_code=400, detail=f"'{name}' did not bind on {entity_id}: {verdict.get('note')}")
    existing = find_override(connection_id, effective, "entity", entity_id)
    fields = dict(existing.fields) if existing is not None else {}
    fields["expressions"] = {**(fields.get("expressions") or {}), name: spec}
    binding = dict(existing.binding) if existing is not None else {}
    binding["expressions"] = {**(binding.get("expressions") or {}), name: verdict}
    ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields,
                          source=(existing.source if existing is not None else "human"), binding=binding)
    save_override(connection_id, effective, ov)
    _invalidate_schema_cache(connection_id)
    served = _get_ontology_graph(connection_id, effective)
    return {**_override_result(ov), "expression": {"name": name, **spec, "verified": True, "sample": verdict.get("sample")},
            "entity": describe_object_type(served, entity_id)}


@router.delete("/ontology/entities/{entity_id}/expressions/{name}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def withdraw_ontology_expression(
    entity_id: str,
    name: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """2026-09-22 — remove an expression property a person declared. 404 when the type has none of that name."""
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_override, find_override, save_override
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    specs = dict((existing.fields.get("expressions") if existing else None) or {})
    if existing is None or name not in specs:
        raise HTTPException(status_code=404, detail=f"{entity_id} has no expression property '{name}'")
    specs.pop(name)
    fields = {k: v for k, v in existing.fields.items() if k != "expressions"}
    binding = {k: v for k, v in existing.binding.items() if k != "expressions"}
    if specs:
        fields["expressions"] = specs
        verdicts = dict(existing.binding.get("expressions") or {})
        verdicts.pop(name, None)
        binding["expressions"] = verdicts
    if fields:
        save_override(connection_id, effective, existing.model_copy(update={"fields": fields, "binding": binding}))
    else:
        delete_override(connection_id, effective, "entity", entity_id)
    _invalidate_schema_cache(connection_id)
    return {"removed": True, "entity": entity_id, "expression": name}


class _SemiAdditiveSpec(BaseModel):
    """PENDING item 27 — a property that is a reading at a moment, and the time property its readings are taken over."""
    over: str
    note: str = ""


@router.put("/ontology/entities/{entity_id}/semiadditive/{prop}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def declare_semiadditive(
    entity_id: str,
    prop: str,
    body: _SemiAdditiveSpec,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """PENDING item 27 — declare that a property must not be summed across time: a stock level, a balance, a headcount
    is a reading AT a moment, taken `over` a time property. Checked against the graph before anything is written — the
    property must be one the object compiler reads, `over` a date or timestamp of the type's own — and a refusal says
    why and writes nothing. From then on a sum of it that spans more than one moment is refused, with how to ask."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.overrides import OntologyOverride, find_override, save_override
    from aughor.ontology.semiadditive import forget_declared, normalized_semiadditive, semiadditive_problem
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    entity = graph.entities.get(entity_id) if graph is not None else None
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    spec = normalized_semiadditive(body.model_dump())
    problem = semiadditive_problem(graph, entity, prop, spec)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    existing = find_override(connection_id, effective, "entity", entity_id)
    fields = dict(existing.fields) if existing is not None else {}
    fields["semiadditive"] = {**(fields.get("semiadditive") or {}), prop: spec}
    binding = dict(existing.binding) if existing is not None else {}
    binding["semiadditive"] = {**(binding.get("semiadditive") or {}),
                               prop: {"bound": True, "note": "", "over": spec["over"]}}
    ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields,
                          source=(existing.source if existing is not None else "human"), binding=binding)
    save_override(connection_id, effective, ov)
    _invalidate_schema_cache(connection_id)
    forget_declared(connection_id)                  # the trust checks read the declaration at once, not in 30s
    return {**_override_result(ov), "semiadditive": {"property": prop, **spec}}


@router.delete("/ontology/entities/{entity_id}/semiadditive/{prop}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def withdraw_semiadditive(
    entity_id: str,
    prop: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """PENDING item 27 — withdraw a semiadditive declaration. 404 when the type declares none for that property."""
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_override, find_override, save_override
    from aughor.ontology.semiadditive import forget_declared
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    specs = dict((existing.fields.get("semiadditive") if existing else None) or {})
    if existing is None or prop not in specs:
        raise HTTPException(status_code=404, detail=f"{entity_id} declares no semiadditive '{prop}'")
    specs.pop(prop)
    verdicts = dict(existing.binding.get("semiadditive") or {})
    verdicts.pop(prop, None)
    fields = {k: v for k, v in existing.fields.items() if k != "semiadditive"}
    binding = {k: v for k, v in existing.binding.items() if k != "semiadditive"}
    if specs:
        fields["semiadditive"], binding["semiadditive"] = specs, verdicts
    if fields:
        save_override(connection_id, effective, existing.model_copy(update={"fields": fields, "binding": binding}))
    else:
        delete_override(connection_id, effective, "entity", entity_id)
    _invalidate_schema_cache(connection_id)
    forget_declared(connection_id)
    return {"removed": True, "entity": entity_id, "semiadditive": prop}


@router.post("/ontology/entities/{entity_id}/bindings/{name}/restore", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def restore_ontology_binding(
    entity_id: str,
    name: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """2026-09-22 — put back a builder-found binding a person withdrew: the name leaves `withdrawn_bindings`, and
    the next read carries the binding again. 404 when nothing of that name was withdrawn."""
    if domain is not None:
        connection_id, schema_name = _domain_scope(domain).tree
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.overrides import (delete_organisation_override, delete_override, find_override,
                                           save_organisation_override, save_override)
    save, remove = ((save_organisation_override, delete_organisation_override) if domain is not None
                    else (save_override, delete_override))
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    gone = list((existing.fields.get("withdrawn_bindings") if existing else None) or [])
    if name not in gone:
        raise HTTPException(status_code=404, detail=f"{entity_id} has no withdrawn binding '{name}'")
    fields = {k: v for k, v in existing.fields.items() if k != "withdrawn_bindings"}
    kept = [n for n in gone if n != name]
    if kept:
        fields["withdrawn_bindings"] = kept
    if fields:
        save(connection_id, effective, existing.model_copy(update={"fields": fields}))
    else:
        remove(connection_id, effective, "entity", entity_id)
    return {"restored": True, "entity": entity_id, "binding": name}


@router.post("/ontology/entities", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def declare_ontology_entity(
    body: _DeclaredEntity,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None, description="ON-8 — declare the type in an organisation's ontology, on the connection `backing.connection_id` names"),
):
    """Declare a business entity (ON-7): the noun first, then the source bound into it — a table or a keyed
    SELECT whose rows are its objects, with the column that is its key. The source is read for its columns and
    the key is counted before anything is written (400 with the reason when it cannot be read); a table that
    already backs a type is refused — rename or absorb that type instead of doubling it. The declaration lives
    in the overrides tree with provenance (human, or a model's proposal) and survives every rebuild. No model
    call. ON-8 — with ``domain`` the type is the organisation's: ``backing.connection_id`` names the connection its
    rows live on, and they are read and counted there."""
    if domain is not None:
        return _domain_declare_entity(body.model_dump(exclude_none=True), domain)
    return _declare_entity_core(body.model_dump(exclude_none=True), connection_id, schema_name)


def _declare_entity_core(spec: dict, connection_id: str, schema_name: Optional[str]) -> dict:
    """The entity door's body, shared with the explorer (ON-7b): the spec carries `origin` and, for a model's
    proposal, its provenance."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.bindings import describe_with
    from aughor.ontology.declared import (
        backs_existing_type, entity_fields, entity_spec_problem, measure_declared_backing,
    )
    from aughor.ontology.overrides import OntologyOverride, save_override
    from aughor.semantic.object_types import describe_object_type
    effective = _resolve_schema(connection_id, schema_name)
    spec = _own_connection_backing(spec, connection_id)
    problem = entity_spec_problem(spec)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    entity_id = str(spec["id"])
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No ontology built for schema '{effective}' on this connection")
    if entity_id in graph.entities:
        raise HTTPException(status_code=409, detail=f"an object type '{entity_id}' already exists")
    fields = entity_fields(spec)
    if fields["backing"].get("table"):
        other = backs_existing_type(graph, fields["backing"]["table"])
        if other is not None:
            raise HTTPException(status_code=400, detail=(
                f"{fields['backing']['table']} already backs {other.id} — a second type over the same rows is a "
                f"duplicate; rename {other.id}, or bind the table into another type and absorb it"))
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        entry = measure_declared_backing(db, fields, describe_with(db))
    finally:
        db.close()
    if not entry.get("bound"):
        raise HTTPException(status_code=400, detail=f"{entity_id} did not bind: {entry.get('note')}")
    ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields, source=fields["origin"],
                          binding={"backing": entry})
    save_override(connection_id, effective, ov)
    served = _get_ontology_graph(connection_id, effective)
    if served is None or entity_id not in served.entities:
        raise HTTPException(status_code=500, detail=f"{entity_id} was written but does not read back — see the overlay report")
    return {**_override_result(ov), "entity": describe_object_type(served, entity_id)}


@router.delete("/ontology/entities/{entity_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def delete_declared_entity(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Withdraw a DECLARED entity (ON-7) — its override file, and with it the type. A type the builder made from
    a table is not deletable here (404 says so): absorb it into another type, or leave it. A declared link on
    the withdrawn type stops applying on the next read and is reported skipped, never silently kept. ON-8 — with
    ``domain``, from the organisation's ontology."""
    if domain is not None:
        connection_id, schema_name = _domain_scope(domain).tree
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_organisation_override, delete_override, find_override
    remove = delete_organisation_override if domain is not None else delete_override  # ON-8 — its own writer
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    if existing is None or not existing.fields.get("declared"):
        graph = _get_ontology_graph(connection_id, effective)
        if graph is not None and entity_id in graph.entities:
            raise HTTPException(status_code=404, detail=(
                f"{entity_id} was built from its table, not declared — a built type is absorbed into another or "
                "kept, never deleted"))
        raise HTTPException(status_code=404, detail=f"no declared entity '{entity_id}'")
    remove(connection_id, effective, "entity", entity_id)
    return {"removed": True, "entity": entity_id}


@router.post("/ontology/links", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def declare_ontology_link(
    body: _DeclaredLink,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None, description="ON-8 — declare the link in an organisation's ontology, where its two types may live on two connections"),
):
    """Declare a link between two types (ON-7): a business verb and the column each side joins on. Both columns
    must be properties of their type, the name must be free on the from-side and the reverse name on the to-side
    (a path segment names one thing), and no found link may already join the same columns — name that one instead.
    Each side is counted (a side is "1" when its key is unique — the cardinality, ON-0a's law) and the share of
    from-keys the to-side holds is measured before anything is written; the compiler follows the link exactly as
    it would a found one: measured, and not N:N. No model call. ON-8 — with ``domain``, between types of the
    organisation's ontology: each side counted on its own connection, and a link across two is `cross-source`."""
    if domain is not None:
        return _domain_declare_link(body.model_dump(exclude_none=True), domain)
    return _declare_link_core(body.model_dump(exclude_none=True), connection_id, schema_name)


def _declare_link_core(spec: dict, connection_id: str, schema_name: Optional[str]) -> dict:
    """The link door's body, shared with the explorer (ON-7b): the spec carries `origin` and, for a model's proposal,
    its provenance."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.declared import (
        link_fields, link_id, link_problem_on_graph, link_spec_problem, measure_declared_link,
    )
    from aughor.ontology.overrides import OntologyOverride, save_override
    from aughor.semantic.object_types import describe_object_type
    effective = _resolve_schema(connection_id, schema_name)
    problem = link_spec_problem(spec)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No ontology built for schema '{effective}' on this connection")
    fields = link_fields(spec)
    if link_id(fields) in graph.relationships:
        raise HTTPException(status_code=409, detail=f"a link '{link_id(fields)}' already exists")
    problem = link_problem_on_graph(graph, fields)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        entry = measure_declared_link(db, graph, fields)
    finally:
        db.close()
    if not entry.get("bound"):
        raise HTTPException(status_code=400, detail=f"link '{fields['name']}' did not bind: {entry.get('note')}")
    ov = OntologyOverride(target_kind="link", target_id=link_id(fields), fields=fields, source=fields["origin"],
                          binding={"link": entry})
    save_override(connection_id, effective, ov)
    served = _get_ontology_graph(connection_id, effective)
    described = describe_object_type(served, fields["from_entity"]) if served is not None else {}
    row = next((link for link in described.get("links", []) if link["relationship"] == ov.target_id), None)
    return {**_override_result(ov), "link": row, "relationship": ov.target_id}


@router.delete("/ontology/links/{relationship_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def delete_declared_link(
    relationship_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Withdraw a DECLARED link (ON-7). A link the builder found is not deletable here (404 says so). ON-8 — with
    ``domain``, from the organisation's ontology."""
    if domain is not None:
        connection_id, schema_name = _domain_scope(domain).tree
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_organisation_override, delete_override, find_override
    remove = delete_organisation_override if domain is not None else delete_override  # ON-8 — its own writer
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "link", relationship_id)
    if existing is None or not existing.fields.get("declared"):
        # 2026-09-22 — a FOUND link is withdrawn by a recorded override (it used to be "named, never deleted",
        # and a person had no way to delink a join the builder guessed wrong). The relationship leaves the
        # served graph on the next read; POST /ontology/links/{id}/restore puts it back.
        from aughor.ontology.overrides import OntologyOverride, save_override
        graph = None if domain is not None else _get_ontology_graph(connection_id, effective)
        rel = graph.relationships.get(relationship_id) if graph is not None else None
        if rel is None:
            raise HTTPException(status_code=404, detail=f"no link '{relationship_id}'")
        fields = {**(existing.fields if existing is not None else {}), "withdrawn": True,
                  "from_entity": rel.from_entity, "to_entity": rel.to_entity}
        ov = OntologyOverride(target_kind="link", target_id=relationship_id, fields=fields,
                              source=(existing.source if existing is not None else "human"))
        save_override(connection_id, effective, ov)
        return {"removed": True, "link": relationship_id, "withdrawn": True}
    remove(connection_id, effective, "link", relationship_id)
    return {"removed": True, "link": relationship_id}


@router.post("/ontology/links/{relationship_id}/restore", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def restore_ontology_link(
    relationship_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """2026-09-22 — put back a found link a person withdrew. 404 when it was not withdrawn."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.overrides import delete_override, find_override, save_override
    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "link", relationship_id)
    if existing is None or not existing.fields.get("withdrawn"):
        raise HTTPException(status_code=404, detail=f"link '{relationship_id}' was not withdrawn")
    fields = {k: v for k, v in existing.fields.items() if k not in ("withdrawn", "from_entity", "to_entity")}
    if fields:
        save_override(connection_id, effective, existing.model_copy(update={"fields": fields}))
    else:
        delete_override(connection_id, effective, "link", relationship_id)
    return {"restored": True, "link": relationship_id}


# ── ON-8: one ontology, many sources ────────────────────────────────────────────────────────


@router.get("/ontology/domains")
def list_ontology_domains():
    """ON-8 — the organisation's ontologies: the default domain every organisation has, and each other domain it has
    declared anything in, with how many types and links each holds, how many of the links cross two connections, and
    the connections it reads. A read of the declaration files: no warehouse query, no model call."""
    from aughor.ontology.domains import DEFAULT_DOMAIN, connections_of, domain_graph, domain_names
    rows = []
    for name in dict.fromkeys([DEFAULT_DOMAIN, *domain_names()]):
        scope = _domain_scope(name)
        graph = domain_graph(scope)
        rows.append({"domain": name, "key": scope.key, "object_types": len(graph.entities),
                     "links": len(graph.relationships),
                     "cross_source_links": sum(1 for r in graph.relationships.values() if r.traversal == "cross-source"),
                     "connections": connections_of(graph)})
    return {"org": _domain_scope(None).org, "default": DEFAULT_DOMAIN, "domains": rows}


def _domain_declare_entity(spec: dict, domain: str) -> dict:
    from aughor import govern
    from aughor.ontology.domains import declare_entity, domain_graph
    from aughor.semantic.object_types import describe_object_type
    scope = _domain_scope(domain)
    govern.guard("ontology.override", scope.key)  # P4: mutating the semantic layer
    ov = _domain_door(lambda: declare_entity(scope, spec, _open_source))
    served = domain_graph(scope)
    if ov.target_id not in served.entities:
        raise HTTPException(status_code=500, detail=f"{ov.target_id} was written but does not read back — see the overlay report")
    return {**_override_result(ov), "entity": describe_object_type(served, ov.target_id), "domain": scope.key}


def _domain_bind(entity_id: str, name: str, spec: dict, domain: str) -> dict:
    from aughor import govern
    from aughor.ontology.domains import absorb_part, bind_source, domain_graph
    from aughor.semantic.object_types import describe_object_type
    scope = _domain_scope(domain)
    govern.guard("ontology.override", scope.key)  # P4: mutating the semantic layer
    ov = _domain_door(lambda: bind_source(scope, entity_id, name, spec, _open_source))
    # 2026-09-22 — `absorb` marks the bound table's own type a part of this one, when the mark holds on the served
    # domain graph: same table, same connection (`parts.part_binding` with the graph).
    absorbed, absorb_note = (absorb_part(scope, entity_id, str(spec.get("table") or "")) if spec.get("absorb")
                             else (None, ""))
    served = domain_graph(scope)
    described = describe_object_type(served, entity_id) if entity_id in served.entities else {}
    row = next((b for b in described.get("bindings", []) if b["name"] == name), None)
    return {"absorbed": absorbed, **({"warnings": [absorb_note]} if absorb_note else {}), **_override_result(ov), "binding": row, "domain": scope.key}


def _domain_declare_link(spec: dict, domain: str) -> dict:
    from aughor import govern
    from aughor.ontology.domains import declare_link, domain_graph
    from aughor.semantic.object_types import describe_object_type
    scope = _domain_scope(domain)
    govern.guard("ontology.override", scope.key)  # P4: mutating the semantic layer
    ov = _domain_door(lambda: declare_link(scope, spec, _open_source))
    served = domain_graph(scope)
    source = str(ov.fields.get("from_entity") or "")
    described = describe_object_type(served, source) if source in served.entities else {}
    row = next((link for link in described.get("links", []) if link["relationship"] == ov.target_id), None)
    return {**_override_result(ov), "link": row, "relationship": ov.target_id, "domain": scope.key}


# ── ON-9: processes, promises and rules ─────────────────────────────────────────────────────


@router.get("/ontology/processes")
def list_ontology_processes(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Every declared process (ON-9) with what its measurement counted — each stage and how many objects reach it,
    each transition timed, each promise with its breaches and the names it derives — and every declared rule. ON-8 —
    with ``domain``, the organisation's ontology's."""
    from aughor.ontology.business_rules import describe_rule
    from aughor.ontology.processes import describe_process
    if domain is not None:
        from aughor.ontology.domains import domain_graph
        scope = _domain_scope(domain)
        graph, where = domain_graph(scope), {"domain": scope.key}
    else:
        graph = _get_ontology_graph(connection_id, schema_name)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        where = {"connection_id": connection_id, "schema_name": graph.schema_name}
    return {**where, "processes": [describe_process(graph, p) for _, p in sorted(graph.processes.items())],
            "rules": [describe_rule(graph, r) for _, r in sorted(graph.rules.items())]}


class _FrameQuestion(BaseModel):
    """ON-10 — a question to frame against the declared ontology."""
    question: str
    #: How many measured to-one links a candidate driver may sit from where the frame starts (1–3).
    hops: Optional[int] = None


def _frame_dialect(connection_id: str) -> str:
    """The dialect the object door compiles in for this connection — the connector's own when it writes native SQL,
    else DuckDB's (the rule `aughor.db.connection` executes by). No connection is opened."""
    try:
        from aughor.db.connection import connection_traits
        from aughor.db.registry import get_conn_type
        traits = connection_traits(get_conn_type(connection_id))
        return (traits.get("dialect") or "duckdb") if traits.get("writes_native_sql") else "duckdb"
    except Exception:  # noqa: BLE001 — an unknown connection compiles as the platform's own engine does
        return "duckdb"


@router.post("/ontology/frame")
def frame_ontology_question(
    body: _FrameQuestion,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Frame a question against the declared ontology (ON-10): its business terms resolved — deterministically,
    against the declared names, a person's synonyms, the processes with their stages and promises, what each promise
    derives, and the rules — to the outcome's definition in the declaration's own words with its measured numbers,
    where to start, the rules and stage moments it names, and the drivers reachable from the start by measured
    to-one links, each definition compiled by the object door. When the words fit several declared definitions
    equally they are all returned and none is chosen. No model call, no warehouse: the investigation frames every
    question this way before its intake reads it, and this door shows the same frame. ON-8 — with ``domain``, against
    the organisation's ontology: what people declared there alone. A person's synonyms are recorded on one connection
    and name its tables and columns, so none of them widens the words of an ontology whose types live on several."""
    from aughor.ontology.framing import DEFAULT_HOPS, frame_question
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="a question is required")
    if domain is not None:
        from aughor.ontology.domains import connections_of, domain_graph
        scope = _domain_scope(domain)
        graph = domain_graph(scope)
        # the dialect the object door compiles in on the connections the domain reads: theirs when they share one
        dialects = {_frame_dialect(c) for c in connections_of(graph)}
        frame = frame_question(question[:2000], graph, hops=body.hops or DEFAULT_HOPS,
                               dialect=dialects.pop() if len(dialects) == 1 else "duckdb")
        return {"domain": scope.key, "frame": frame.model_dump(mode="json")}
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    try:
        from aughor.ontology.vocabulary import synonyms_for
        synonyms = [s for s in synonyms_for(connection_id) if s.source == "human"]
    except Exception:  # noqa: BLE001 — synonyms widen what a question may name; the declared names still resolve
        synonyms = []
    frame = frame_question(question[:2000], graph, synonyms=synonyms, hops=body.hops or DEFAULT_HOPS,
                           dialect=_frame_dialect(connection_id))
    return {"connection_id": connection_id, "schema_name": graph.schema_name, "frame": frame.model_dump(mode="json")}


@router.post("/ontology/processes", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def declare_ontology_process(
    body: _DeclaredProcess,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Declare a process (ON-9): the type that goes through it, its stages in order — each anchored to the moment an
    object reaches it or to the states that place it there — and on a stage the promise about reaching it: within N
    calendar days of the previous stage, or by a deadline property of the object that carries it. Every anchor is
    resolved by the object door's own path law and the whole declaration is COUNTED through its compiler before
    anything is written (400 with the reason when it cannot be); the count rides the override file and is taken again
    on every measure pass. The door then compiles what each promise derives — `late_<name>`, `<name>_breach_rate`,
    `<name>_lag_days`. No model call. ON-8 — with ``domain``, into the organisation's ontology, where a stage may be
    anchored on a type or binding on another connection and is counted across the two."""
    if domain is not None:
        return _domain_declare_process(body.model_dump(exclude_none=True), domain)
    return _declare_process_core(body.model_dump(exclude_none=True), connection_id, schema_name)


def _declare_process_core(spec: dict, connection_id: str, schema_name: Optional[str]) -> dict:
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.overrides import OntologyOverride, save_override
    from aughor.ontology.processes import (
        NotMeasurable, describe_process, measure_process, process_entry, process_fields, process_spec_problem,
        resolve_process,
    )
    effective = _resolve_schema(connection_id, schema_name)
    problem = process_spec_problem(spec)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No ontology built for schema '{effective}' on this connection")
    process_id = str(spec["id"])
    if process_id in graph.processes:
        raise HTTPException(status_code=409, detail=f"a process '{process_id}' already exists")
    problem, fields = resolve_process(graph, process_id, process_fields(spec))
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        measured = measure_process(db, graph, process_id, fields)
    except NotMeasurable as exc:
        raise HTTPException(status_code=400, detail=f"{process_id} could not be counted: {exc}") from exc
    finally:
        db.close()
    ov = OntologyOverride(target_kind="process", target_id=process_id, fields=fields, source=fields["origin"],
                          binding={"process": process_entry(fields, measured)})
    save_override(connection_id, effective, ov)
    served = _get_ontology_graph(connection_id, effective)
    if served is None or process_id not in served.processes:
        raise HTTPException(status_code=500, detail=f"{process_id} was written but does not read back — see the overlay report")
    return {**_override_result(ov), "process": describe_process(served, served.processes[process_id])}


def _domain_declare_process(spec: dict, domain: str) -> dict:
    from aughor import govern
    from aughor.ontology.domains import declare_process, domain_graph
    from aughor.ontology.processes import describe_process
    scope = _domain_scope(domain)
    govern.guard("ontology.override", scope.key)  # P4: mutating the semantic layer
    ov = _domain_door(lambda: declare_process(scope, spec, _open_source))
    served = domain_graph(scope)
    if ov.target_id not in served.processes:
        raise HTTPException(status_code=500, detail=f"{ov.target_id} was written but does not read back — see the overlay report")
    return {**_override_result(ov), "process": describe_process(served, served.processes[ov.target_id]),
            "domain": scope.key}


@router.delete("/ontology/processes/{process_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def delete_declared_process(
    process_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Withdraw a declared process (ON-9) — its override file, and with it every name it derived. ON-8 — with
    ``domain``, from the organisation's ontology."""
    if domain is not None:
        connection_id, schema_name = _domain_scope(domain).tree
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_organisation_override, delete_override, find_override
    remove = delete_organisation_override if domain is not None else delete_override  # ON-8 — its own writer
    effective = _resolve_schema(connection_id, schema_name)
    if find_override(connection_id, effective, "process", process_id) is None:
        raise HTTPException(status_code=404, detail=f"no declared process '{process_id}'")
    remove(connection_id, effective, "process", process_id)
    return {"removed": True, "process": process_id}


@router.post("/ontology/rules", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def declare_ontology_rule(
    body: _DeclaredRule,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Declare a named business rule (ON-9): a value set — the values of one property the business groups under one
    name, "DACH is DE, AT and CH" — or conditions in the object door's shape. Compiled and COUNTED before it is
    written: how many objects it admits, and for a value set the rows per value, a value no row holds flagged. The
    object door reads it as a segment named by its id. No model call. ON-8 — with ``domain``, into the organisation's
    ontology, where a condition may read a type on another connection through a to-one link."""
    if domain is not None:
        return _domain_declare_rule(body.model_dump(exclude_none=True), domain)
    return _declare_rule_core(body.model_dump(exclude_none=True), connection_id, schema_name)


def _declare_rule_core(spec: dict, connection_id: str, schema_name: Optional[str]) -> dict:
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.business_rules import (
        describe_rule, measure_rule, resolve_rule, rule_entry, rule_fields, rule_spec_problem,
    )
    from aughor.ontology.overrides import OntologyOverride, save_override
    from aughor.ontology.processes import NotMeasurable
    effective = _resolve_schema(connection_id, schema_name)
    problem = rule_spec_problem(spec)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No ontology built for schema '{effective}' on this connection")
    rule_id = str(spec["id"])
    if rule_id in graph.rules:
        raise HTTPException(status_code=409, detail=f"a rule '{rule_id}' already exists")
    problem, fields = resolve_rule(graph, rule_id, rule_fields(spec))
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        measured = measure_rule(db, graph, rule_id, fields)
    except NotMeasurable as exc:
        raise HTTPException(status_code=400, detail=f"{rule_id} could not be counted: {exc}") from exc
    finally:
        db.close()
    ov = OntologyOverride(target_kind="rule", target_id=rule_id, fields=fields, source=fields["origin"],
                          binding={"rule": rule_entry(fields, measured)})
    save_override(connection_id, effective, ov)
    served = _get_ontology_graph(connection_id, effective)
    if served is None or rule_id not in served.rules:
        raise HTTPException(status_code=500, detail=f"{rule_id} was written but does not read back — see the overlay report")
    return {**_override_result(ov), "rule": describe_rule(served, served.rules[rule_id])}


def _domain_declare_rule(spec: dict, domain: str) -> dict:
    from aughor import govern
    from aughor.ontology.business_rules import describe_rule
    from aughor.ontology.domains import declare_rule, domain_graph
    scope = _domain_scope(domain)
    govern.guard("ontology.override", scope.key)  # P4: mutating the semantic layer
    ov = _domain_door(lambda: declare_rule(scope, spec, _open_source))
    served = domain_graph(scope)
    if ov.target_id not in served.rules:
        raise HTTPException(status_code=500, detail=f"{ov.target_id} was written but does not read back — see the overlay report")
    return {**_override_result(ov), "rule": describe_rule(served, served.rules[ov.target_id]), "domain": scope.key}


@router.delete("/ontology/rules/{rule_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def delete_declared_rule(
    rule_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
):
    """Withdraw a declared rule (ON-9) — its override file, and with it the segment it named. ON-8 — with ``domain``,
    from the organisation's ontology."""
    if domain is not None:
        connection_id, schema_name = _domain_scope(domain).tree
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_organisation_override, delete_override, find_override
    remove = delete_organisation_override if domain is not None else delete_override  # ON-8 — its own writer
    effective = _resolve_schema(connection_id, schema_name)
    if find_override(connection_id, effective, "rule", rule_id) is None:
        raise HTTPException(status_code=404, detail=f"no declared rule '{rule_id}'")
    remove(connection_id, effective, "rule", rule_id)
    return {"removed": True, "rule": rule_id}


class _LinkName(BaseModel):
    """ON-3b — a link's business-verb name (`shipment_ships_order`). An empty name CLEARS the business name
    (2026-09-22): the withdrawal of a name, a person's or the explorer's."""
    name: str


def _name_link_core(connection_id: str, effective: str, relationship_id: str, name: str, *,
                    origin: str = "human", provenance: str = "") -> dict:
    """The naming door's one body (2026-09-22), shared by the person's PUT and the explorer's proposal.

    It MERGES into the link's override. A declared link's whole spec lives in that file, and the door used
    to replace the file with `{name}` — naming a declared link erased its declaration. `origin` says whose
    name it is (`human` from the PUT, `model` from the explorer, tiered PROPOSED until confirmed). An empty
    name clears the name and its origin; a file left with no fields is deleted."""
    from aughor.ontology.overrides import OntologyOverride, delete_override, find_override, save_override
    from aughor.semantic.object_types import link_name_problem
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None or relationship_id not in graph.relationships:
        raise HTTPException(status_code=404, detail=f"Link '{relationship_id}' not found")
    wanted = (name or "").strip()
    existing = find_override(connection_id, effective, "link", relationship_id)
    fields = dict(existing.fields) if existing is not None else {}
    if not wanted:
        if fields.get("declared"):
            # A declared link's `name` IS its verb — the declaration itself. Clearing it would erase the link.
            raise HTTPException(status_code=400, detail=(
                f"'{relationship_id}' is a declared link, named by its verb: rename it, or withdraw the link with "
                "DELETE /ontology/links/{id}"))
        for k in ("name", "name_origin", "name_provenance"):
            fields.pop(k, None)
        if not fields:
            delete_override(connection_id, effective, "link", relationship_id)
            return {"target_kind": "link", "target_id": relationship_id, "fields": {}, "bound": True, "warnings": []}
    else:
        problem = link_name_problem(graph, relationship_id, wanted)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        fields.update({"name": wanted, "name_origin": "model" if origin == "model" else "human",
                       "name_provenance": provenance if origin == "model" else ""})
    ov = OntologyOverride(target_kind="link", target_id=relationship_id, fields=fields)
    if existing is not None:
        ov.binding = dict(existing.binding or {})
    save_override(connection_id, effective, ov)
    return _override_result(ov)


@router.put("/ontology/links/{relationship_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def name_ontology_link(
    relationship_id: str,
    body: _LinkName,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None, description="ON-8 — name a link of an organisation's ontology"),
):
    """Name a link by its business verb (ON-3b). Its mechanical names stay — every query and page still accepts
    them — and this one is accepted beside them. Refused when it is not snake_case, or already names another
    link or a property on either type the link joins: a path segment must name exactly one thing. An empty
    name clears it. Merges into the link's override, so a declared link keeps its declaration. ON-8 — with
    ``domain``, a link of the organisation's ontology, whatever connections its types live on: a name reads no
    warehouse, so the door is open there."""
    from aughor import govern
    if domain is not None:
        return _domain_name_link(relationship_id, body.name, domain)
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    effective = _resolve_schema(connection_id, schema_name)
    return _name_link_core(connection_id, effective, relationship_id, body.name, origin="human")


def _domain_name_link(relationship_id: str, name: str, domain: str) -> dict:
    """ON-8 (2026-09-22) — a link's business name in an organisation's ontology: declarative, so it opens on a
    cross-source link too. Merged into the organisation's own override and written by its own writer."""
    from aughor import govern
    from aughor.ontology.domains import domain_graph
    from aughor.ontology.overrides import (OntologyOverride, delete_organisation_override, find_override,
                                           save_organisation_override)
    from aughor.semantic.object_types import link_name_problem
    scope = _domain_scope(domain)
    govern.guard("ontology.override", scope.key)  # P4: mutating the semantic layer
    graph = domain_graph(scope)
    if relationship_id not in graph.relationships:
        raise HTTPException(status_code=404, detail=f"Link '{relationship_id}' not found in {scope.key}")
    wanted = (name or "").strip()
    existing = find_override(*scope.tree, "link", relationship_id)
    fields = dict(existing.fields) if existing is not None else {}
    if not wanted:
        if fields.get("declared"):
            raise HTTPException(status_code=400, detail=(
                f"'{relationship_id}' is a declared link, named by its verb: rename it, or withdraw the link with "
                "DELETE /ontology/links/{id}?domain="))
        for k in ("name", "name_origin", "name_provenance"):
            fields.pop(k, None)
        if not fields:
            delete_organisation_override(*scope.tree, "link", relationship_id)
            return {"target_kind": "link", "target_id": relationship_id, "fields": {}, "bound": True, "warnings": [],
                    "domain": scope.key}
    else:
        problem = link_name_problem(graph, relationship_id, wanted)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        fields.update({"name": wanted, "name_origin": "human", "name_provenance": ""})
    ov = OntologyOverride(target_kind="link", target_id=relationship_id, fields=fields,
                          source=(existing.source if existing is not None else "human"))
    if existing is not None:
        ov.binding = dict(existing.binding or {})
    save_organisation_override(*scope.tree, ov)
    return {**_override_result(ov), "domain": scope.key}


# ── ON-7b: the explorer maps the business first ────────────────────────────────────────────────


class _ConfirmTarget(BaseModel):
    """One declaration a person makes theirs: a declared entity, a declared link, the binding a part is read through,
    or a declared process or rule (ON-9)."""
    kind: Literal["entity", "binding", "link", "link_name", "process", "rule"]
    entity: Optional[str] = None
    binding: Optional[str] = None
    relationship: Optional[str] = None
    process: Optional[str] = None
    rule: Optional[str] = None


class _ConfirmRequest(BaseModel):
    #: Every proposal of the scope's draft that is still the model's.
    all: bool = False
    targets: list[_ConfirmTarget] = []
    #: Who confirms — recorded on the declaration beside the model that proposed it.
    actor: str = ""


def _through_door(write):
    """Run one of ON-7's doors for the explorer: a refusal (a 4xx) becomes the explorer's refusal carrying the door's
    own sentence; anything else is raised as it is."""
    from aughor.ontology.explorer import ExplorerRefused
    try:
        return write()
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        raise ExplorerRefused(str(exc.detail)) from exc


#: One exploration per scope at a time (PENDING item 20): the birth rite runs the explorer on a new connection, and a
#: person pressing Explore meanwhile would pay a second model call to race the first over the same record.
_EXPLORING: dict[tuple[str, str], "threading.Lock"] = {}
_EXPLORING_GUARD = threading.Lock()


def _exploration_lock(connection_id: str, schema: str) -> "threading.Lock":
    with _EXPLORING_GUARD:
        return _EXPLORING.setdefault((connection_id, schema), threading.Lock())


@router.post("/ontology/explore", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def explore_ontology(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """ON-7b — an explorer drafts the BUSINESS ontology over this scope in ONE model call: which tables are one business
    thing (an entity and its parts), the links the business names, the processes its objects go through and the sets of
    objects it names (ON-9: stages without promises, rules without scopes), and — rarely — an entity no table stands for. Every
    proposal is measured before it lands — a part's key counted against its entity's objects, the data deciding static,
    detail or timeseries; a link's sides counted and keys that never meet refused; a declared entity's key unique — and
    what survives is written through ON-7's doors with `origin: model` and `model:<id>@<version>` provenance: read at
    once, PROPOSED until a person confirms it. A second run writes nothing twice, and a proposal a person withdrew is
    not proposed again. Costs one model call, so nothing starts it but a person asking."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.drafts import load_draft
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail=(f"No ontology built for schema '{effective}' on this connection — "
                                                     "the explorer reads what the build measured, so build it first"))
    from aughor.ontology.drafts import DraftUnreadable
    try:
        # Read BEFORE the model call: a record that does not parse holds what people withdrew, and the run could
        # neither honour it nor be saved over it — so it is refused without spending the call (PENDING item 20).
        load_draft(connection_id, effective, strict=True)
    except DraftUnreadable as exc:
        raise HTTPException(status_code=409, detail=(f"this scope's explorer record cannot be read, so the explorer "
                                                     f"cannot tell what a person withdrew — repair or remove it "
                                                     f"first: {exc}"))
    lock = _exploration_lock(connection_id, effective)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=(f"an exploration of '{effective}' is already running — its "
                                                     "proposals appear here when it finishes"))
    try:
        return _explore_locked(connection_id, effective, graph)
    finally:
        lock.release()


def _explore_locked(connection_id: str, effective: str, graph):
    """The explorer run itself, under the scope's lock (`explore_ontology`)."""
    import uuid
    from aughor.llm.provider import NoModelConfigured, answered_by, get_provider
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.drafts import load_draft, save_draft
    from aughor.telemetry import bind_trace
    from aughor.ontology.explorer import DraftWriters, apply_draft, draft_business, draft_view, record_run
    glossary: dict = {}
    try:
        from aughor.semantic.glossary import load_merged_glossary
        glossary = load_merged_glossary(connection_id=connection_id) or {}
    except Exception:  # noqa: BLE001 — the glossary is one input among several, never a precondition
        glossary = {}
    # The run's own trace. The session log drops an event with no ambient trace, so without one the explorer's model
    # call was metered and never recorded — missing from Spend and Activity on the one door that exists to spend.
    trace_id = uuid.uuid4().hex
    try:
        with bind_trace(trace_id):
            # ON-0a: only the packs DEPLOYED here may reach the prompt, and only where the data measured them
            # true — the catalogue filters on both.
            from aughor.packs.ontology_map import bound_pack_ids
            said, answerer, catalogue = draft_business(graph, get_provider("coder"), glossary=glossary,
                                                       answered=answered_by,
                                                       deployed_packs=bound_pack_ids(connection_id, effective))
    except NoModelConfigured:
        raise
    except Exception as exc:  # noqa: BLE001 — a draft that could not be asked for writes nothing, and says why
        raise HTTPException(status_code=502, detail=(f"the explorer's model call failed, so nothing was proposed: "
                                                     f"{type(exc).__name__}: {str(exc)[:300]}"))
    draft = load_draft(connection_id, effective)
    writers = DraftWriters(
        declare_entity=lambda spec: _through_door(lambda: _declare_entity_core(spec, connection_id, effective)),
        bind=lambda entity_id, name, spec, absorb: _through_door(lambda: _bind_entity_core(
            entity_id, name, {**spec, "absorb": absorb}, connection_id, effective,
            origin="model", provenance=answerer.provenance)),
        declare_link=lambda spec: _through_door(lambda: _declare_link_core(spec, connection_id, effective)),
        name_link=lambda rel_id, name: _through_door(lambda: _name_link_core(
            connection_id, effective, rel_id, name, origin="model", provenance=answerer.provenance)),
        served=lambda: _get_ontology_graph(connection_id, effective),
        declare_process=lambda spec: _through_door(lambda: _declare_process_core(spec, connection_id, effective)),
        declare_rule=lambda spec: _through_door(lambda: _declare_rule_core(spec, connection_id, effective)))
    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        outcomes = apply_draft(said, graph, db, provenance=answerer.provenance, draft=draft, writers=writers)
    except Exception as exc:  # noqa: BLE001 — recorded, then reported: the call it paid for is not paid again
        # PENDING item 20 — the model call is spent; recording the run is what stops every restart that finds no run
        # from spending it again. What was written before the failure stays written, each through its own door.
        failed = record_run(draft, [], answerer, said, catalogue_chars=len(catalogue), trace_id=trace_id)
        failed.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        save_draft(draft)
        raise HTTPException(status_code=500, detail=(f"the explorer's proposals stopped part-way ({failed.error}); "
                                                     f"the run is recorded as {failed.id}"))
    finally:
        db.close()
    run = record_run(draft, outcomes, answerer, said, catalogue_chars=len(catalogue), trace_id=trace_id)
    save_draft(draft)
    _invalidate_schema_cache(connection_id)
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("ontology.explore", {"ok": True, "schema": effective, "run": run.id,
                                                   "backend": run.backend, "model": run.model,
                                                   "fallback": run.fallback, "said": run.said,
                                                   "written": run.written, "refused": run.refused,
                                                   "already": run.already, "withdrawn": run.withdrawn},
                              conn_id=connection_id, trace_id=trace_id)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).debug("ontology.explore emit skipped", exc_info=True)
    return {**draft_view(_get_ontology_graph(connection_id, effective), draft), "run": run.model_dump(),
            "outcomes": [o.row() for o in outcomes]}


@router.get("/ontology/draft", dependencies=[gate(Capability.ONTOLOGY_VIEW)])
def get_ontology_draft(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    reference_connection_id: Optional[str] = Query(
        default=None, description="Compare this scope's grouping of tables into business entities with another "
                                  "scope's (ON-7b's falsifier: a draft that fuses what the reference keeps apart)"),
    reference_schema_name: Optional[str] = Query(default=None),
):
    """ON-7b — the scope's explorer draft: every proposal with where it stands NOW (read from the served graph —
    proposed, confirmed, released, withdrawn — or refused when it was said), every run with the model that answered,
    and how the tables group into business entities. With a reference scope, that grouping is compared with the
    reference's, table by table. No model call, no warehouse query."""
    from aughor.ontology.drafts import load_draft
    from aughor.ontology.explorer import business_grouping, compare_groupings, draft_view
    effective = _resolve_schema(connection_id, schema_name)
    view = draft_view(_get_ontology_graph(connection_id, effective), load_draft(connection_id, effective))
    if reference_connection_id:
        reference = _get_ontology_graph(reference_connection_id, reference_schema_name)
        if reference is None:
            raise HTTPException(status_code=404,
                                detail=f"No ontology built for the reference scope '{reference_connection_id}'")
        grouping = business_grouping(reference)
        view["comparison"] = {"reference_connection_id": reference_connection_id,
                              "reference_schema_name": reference.schema_name, "reference_grouping": grouping,
                              **compare_groupings(view["grouping"], grouping)}
    return view


@router.post("/ontology/draft/confirm", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def confirm_ontology_proposals(
    body: _ConfirmRequest,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """ON-7b — a person makes an explorer's proposals theirs: `origin` becomes human, the provenance of the model that
    proposed it is kept, and nothing else about the declaration or its measurement changes. `all` confirms every
    proposal of the scope's draft that is still the model's; `targets` names declarations — a declared entity, a
    declared link, or the binding a part is read through. A target that is not a model's proposal is refused with the
    reason, never quietly confirmed. No model call."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.drafts import load_draft
    from aughor.ontology.explorer import confirm_targets, draft_view
    effective = _resolve_schema(connection_id, schema_name)
    draft = load_draft(connection_id, effective)
    targets = [t.model_dump(exclude_none=True) for t in body.targets]
    if body.all:
        targets += confirm_targets(_get_ontology_graph(connection_id, effective), draft)
    if not targets:
        raise HTTPException(status_code=400,
                            detail="nothing to confirm — no target was named, and no proposal is still the model's")
    confirmed, refused = [], []
    for target in targets:
        why = _confirm_proposal(connection_id, effective, target, body.actor.strip())
        (refused if why else confirmed).append({**target, **({"why": why} if why else {})})
    _invalidate_schema_cache(connection_id)
    return {**draft_view(_get_ontology_graph(connection_id, effective), draft),
            "confirmed": confirmed, "refused": refused}


def _confirm_proposal(connection_id: str, schema: str, target: dict, actor: str) -> str:
    """Make one model-proposed declaration a person's; returns why not, or ""."""
    from datetime import datetime, timezone
    from aughor.ontology.bindings import binding_block
    from aughor.ontology.overrides import find_override, save_override
    kind = target.get("kind")
    now = datetime.now(timezone.utc).isoformat()
    who = actor or "a person"
    if kind in ("entity", "link", "process", "rule"):
        ident = str(target.get({"entity": "entity", "link": "relationship"}.get(kind, kind)) or "")
        ov = find_override(connection_id, schema, kind, ident)
        if ov is None or not ov.fields.get("declared"):
            return f"no declared {kind} '{ident}'"
        if ov.fields.get("origin") != "model":
            return f"{ident} was declared by a person — there is no proposal to confirm"
        ov.fields["origin"] = "human"
        ov.source, ov.edited_at = "human", now
        ov.edited_by = actor or ov.edited_by
        ov.note = f"confirmed by {who}; proposed by {ov.fields.get('provenance') or 'a model'}"
        save_override(connection_id, schema, ov)
        return ""
    if kind == "link_name":
        # 2026-09-22 — the explorer's name for a found link becomes the person's.
        ident = str(target.get("relationship") or "")
        ov = find_override(connection_id, schema, "link", ident)
        if ov is None or not ov.fields.get("name"):
            return f"link '{ident}' carries no business name"
        if ov.fields.get("name_origin") != "model":
            return f"link '{ident}' was named by a person — there is no proposal to confirm"
        ov.fields["name_origin"] = "human"
        ov.source, ov.edited_at = "human", now
        ov.edited_by = actor or ov.edited_by
        ov.note = f"name confirmed by {who}; proposed by {ov.fields.get('name_provenance') or 'a model'}"
        save_override(connection_id, schema, ov)
        return ""
    if kind == "binding":
        entity_id, name = str(target.get("entity") or ""), str(target.get("binding") or "")
        ov = find_override(connection_id, schema, "entity", entity_id)
        entries = dict(((ov.binding.get("bindings") or {}).get("entries") or {}) if ov is not None else {})
        entry = entries.get(name)
        if ov is None or entry is None:
            return f"{entity_id} has no binding '{name}'"
        if entry.get("origin") != "model":
            return f"{entity_id}.{name} was bound by a person — there is no proposal to confirm"
        entries[name] = {**entry, "origin": "human", "confirmed_by": who, "confirmed_at": now}
        entries[name].pop("absorb_on_confirm", None)
        ov.binding["bindings"] = binding_block(entries)
        save_override(connection_id, schema, ov)
        if entry.get("absorb_on_confirm"):
            # PENDING item 20 — the absorption the proposal deferred: the table's own type becomes a part now that a
            # person has said it is one. Refused with the reason when the mark would not hold, as at the bind door.
            _absorbed, why = _absorb_after_bind(connection_id, schema, entity_id, (entry.get("spec") or {}).get("table"))
            if why:
                import logging
                logging.getLogger(__name__).info("confirmed %s.%s; its table's type was not made a part: %s",
                                                 entity_id, name, why)
        return ""
    return f"there is no {kind!r} to confirm"


class _RoutingProposal(BaseModel):
    """A volunteered correction: "for X questions you should have used table Y"."""
    table: str
    scope: str = ""
    reason: str = ""
    #: Where this came from, so a proposal can be traced back to the turn that
    #: produced it. Wave-L rule: evidence must point at a run that EXISTS.
    evidence: str = ""


@router.post("/ontology/entities/{entity_id}/routing-proposal",
             dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def propose_entity_routing(
    entity_id: str,
    body: _RoutingProposal,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Capture a routing correction as a PENDING proposal (Wave 2 / Layer 1.1).

    Never applies it. The proposal is stored in its own field, so enforcement — which
    reads only ``use_instead`` — cannot see it: "a proposal changes nothing" is true by
    construction rather than by a status check someone has to remember. It IS
    existence-bound here though, while the person who volunteered it is still present,
    so a typo is reported now instead of at accept time.

    Merges into any existing override for the entity rather than replacing the file,
    so proposing does not wipe a description or an active filter that is already there.
    """
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.overrides import (
        PROPOSED_FIELD, OntologyOverride, find_override)

    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    fields = dict(existing.fields) if existing else {}
    fields[PROPOSED_FIELD] = {
        "table": body.table.strip(),
        "scope": body.scope.strip(),
        "reason": body.reason.strip(),
        "evidence": body.evidence.strip(),
    }
    ov = OntologyOverride(
        target_kind="entity", target_id=entity_id, fields=fields,
        source=(existing.source if existing else "human"),
        binding=dict(existing.binding) if existing else {},
    )
    ov, graph = _bind_and_persist(connection_id, effective, ov)
    if graph is not None and entity_id not in graph.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return _proposal_result(entity_id, ov)


@router.get("/ontology/routing-proposals", dependencies=[gate(Capability.ONTOLOGY_VIEW)])
def list_routing_proposals(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Every pending routing proposal for this connection — the review surface.

    Each carries its bind verdict, so the reviewer sees "this table does not exist"
    before accepting rather than after.
    """
    from aughor.ontology.overrides import PROPOSED_FIELD, load_overrides

    effective = _resolve_schema(connection_id, schema_name)
    out = []
    for ov in load_overrides(connection_id, effective):
        if ov.target_kind == "entity" and ov.fields.get(PROPOSED_FIELD):
            out.append(_proposal_result(ov.target_id, ov))
    return {"proposals": out, "connection_id": connection_id, "schema_name": effective}


@router.post("/ontology/entities/{entity_id}/routing-proposal/accept",
             dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def accept_entity_routing(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Promote a pending proposal to the live routing rule — the human click (C4).

    This is the ONLY path from proposed to enforced. Refuses a proposal that did not
    existence-bind: accepting a rule that names a table nobody can read would put a
    dead pointer into every prompt for this connection.
    """
    from aughor import govern
    govern.guard("ontology.override", connection_id)
    from aughor.ontology.overrides import (
        PROPOSED_FIELD, ROUTING_FIELD, OntologyOverride, find_override)

    effective = _resolve_schema(connection_id, schema_name)
    existing = find_override(connection_id, effective, "entity", entity_id)
    proposed = (existing.fields.get(PROPOSED_FIELD) if existing else None)
    if not proposed:
        raise HTTPException(status_code=404,
                            detail=f"no pending routing proposal for '{entity_id}'")
    if not existing.sql_field_ok(PROPOSED_FIELD):
        note = (existing.binding.get(PROPOSED_FIELD) or {}).get("note") or "did not bind"
        raise HTTPException(
            status_code=409,
            detail=f"this proposal never bound ({note}) — it would route to a table "
                   "that cannot be read, so it cannot be accepted")

    fields = dict(existing.fields)
    fields[ROUTING_FIELD] = {k: v for k, v in proposed.items() if k != "evidence"}
    fields.pop(PROPOSED_FIELD, None)
    binding = {k: v for k, v in existing.binding.items() if k != PROPOSED_FIELD}
    ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields,
                          source="human", binding=binding,
                          note=f"routing accepted from proposal ({proposed.get('evidence') or 'no evidence'})")
    ov, _graph = _bind_and_persist(connection_id, effective, ov)
    return _override_result(ov)


def _proposal_result(entity_id: str, ov) -> dict:
    """One proposal, with the before/after a reviewer needs to judge it."""
    from aughor.ontology.overrides import PROPOSED_FIELD, ROUTING_FIELD

    bind = ov.binding.get(PROPOSED_FIELD) or {}
    return {
        "entity_id": entity_id,
        "proposed": ov.fields.get(PROPOSED_FIELD) or {},
        # What is live today, so the reviewer sees what accepting would REPLACE.
        "current": ov.fields.get(ROUTING_FIELD) or None,
        "bound": bool(bind.get("bound")),
        "bind_note": bind.get("note") or "",
    }


def _object_types_problem(declared, graph) -> str:
    """ON-4 — why an action's objects do not hold in this scope, or "". Every object parameter and the
    action's own object type must name an object type the scope serves, and an edit may not set a
    column the type already reads from its source: an edit adds an overlay property, it never
    rewrites a source value."""
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type, find_property
    wanted = [p for p in declared.params if p.kind == "object"]
    if not wanted and not declared.object_type:
        return ""
    if graph is None:
        return "an object parameter needs an ontology built for this scope"
    try:
        types = {p.name: find_object_type(graph, p.object_type) for p in wanted}
        if declared.object_type:
            find_object_type(graph, declared.object_type)
    except ObjectQueryRefused as exc:
        return exc.reason
    for edit in declared.edits:
        entity = types[edit.object]
        if find_property(entity, edit.property) is not None:
            return (f"'{edit.property}' is a column {entity.id} reads from its source — an edit sets an "
                    "overlay property and never rewrites a source value")
    return ""


@router.put("/ontology/kinetic-actions/{action_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def author_kinetic_action(
    action_id: str,
    body: _KineticActionBody,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave K5 — author (or edit) a DECLARED KineticAction as a per-connection ontology override: the
    write path for the authoring UI. Persisted as ``target_kind='action'`` and overlaid onto the graph
    at read time (always — the ``kinetic.actions`` flag was deleted 2026-08-02). The full spec is validated HERE, so a malformed
    action (e.g. a submission criterion missing its authored message) is rejected at author time — not
    silently dropped at overlay or discovered at execute."""
    from aughor import govern
    govern.guard("ontology.override", connection_id)   # P4: mutating the semantic layer
    from aughor.ontology.models import KineticAction, encrypt_action_secrets
    from aughor.ontology.overrides import OntologyOverride, find_override
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields.get("kind"):
        raise HTTPException(status_code=400,
                            detail="a declared action requires a 'kind' (annotate|side_effect|query)")
    # DS-13 — a declared component's credential is encrypted BEFORE it is validated and
    # persisted, and an unchanged (masked) one is carried forward from what is stored. The
    # override is a file: a plaintext key here would be a plaintext key in the repo.
    prior = find_override(connection_id, effective, "action", action_id)
    fields = encrypt_action_secrets(fields, getattr(prior, "fields", None) if prior else None)
    try:
        declared = KineticAction.model_validate({**fields, "id": action_id})
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"invalid action spec: {e}")
    problem = _object_types_problem(declared, _get_ontology_graph(connection_id, effective))
    if problem:
        raise HTTPException(status_code=422, detail=f"invalid action spec: {problem}")
    ov = OntologyOverride(target_kind="action", target_id=action_id, fields=fields)
    ov, _ = _bind_and_persist(connection_id, effective, ov)
    return _override_result(ov)


@router.put(
    "/ontology/entities/{entity_id}/computed-properties/{prop_id}",
    dependencies=[gate(Capability.ONTOLOGY_EDIT)],
)
def override_ontology_computed_property(
    entity_id: str,
    prop_id: str,
    body: _ComputedPropertyOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Assert (or correct) a derived metric on an entity. Once its formula EXPLAIN-binds,
    it is injected into the NL2SQL prompt with authority — overriding the auto-derived one."""
    from aughor.ontology.overrides import OntologyOverride
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    ov = OntologyOverride(
        target_kind="computed_property", target_id=f"{entity_id}::{prop_id}", fields=fields)
    ov, graph = _bind_and_persist(connection_id, effective, ov)
    if graph is not None and entity_id not in graph.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return _override_result(ov)


@router.put(
    "/ontology/entities/{entity_id}/segments/{segment_id}",
    dependencies=[gate(Capability.ONTOLOGY_EDIT)],
)
def override_entity_segment(
    entity_id: str,
    segment_id: str,
    body: _SegmentOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Define (or correct) a saved, named row-filter (segment) on an entity."""
    from aughor.ontology.overrides import OntologyOverride
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    # target_kind stays "object_set": it is the persisted override-store value and the
    # on-disk directory name (see ontology.overrides.TargetKind). Only the URL renamed.
    ov = OntologyOverride(
        target_kind="object_set", target_id=f"{entity_id}::{segment_id}", fields=fields)
    ov, graph = _bind_and_persist(connection_id, effective, ov)
    if graph is not None and entity_id not in graph.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return _override_result(ov)


@router.put(
    "/ontology/entities/{entity_id}/object-sets/{set_id}",
    dependencies=[gate(Capability.ONTOLOGY_EDIT)],
    deprecated=True,
)
def override_ontology_object_set(
    entity_id: str,
    set_id: str,
    body: _SegmentOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """DEPRECATED alias of ``PUT /ontology/entities/{entity_id}/segments/{segment_id}``.

    Same body, same payload, same persisted override — it delegates to the handler above.
    Kept for one release; use ``/segments/{segment_id}``.
    """
    return override_entity_segment(entity_id, set_id, body, connection_id, schema_name)


@router.put("/ontology/metrics/{metric_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def override_ontology_metric(
    metric_id: str,
    body: _MetricOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Assert (or correct) a metric's canonical formula. EXPLAIN-bound, then injected
    with authority through the unified metrics catalog."""
    from aughor.ontology.overrides import OntologyOverride
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    ov = OntologyOverride(target_kind="metric", target_id=metric_id, fields=fields)
    ov, _ = _bind_and_persist(connection_id, effective, ov)
    return _override_result(ov)


@router.delete("/ontology/overrides/{kind}/{target_id:path}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def delete_ontology_override(
    kind: str,
    target_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Remove a human override so the auto-derived value is restored on next read."""
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from typing import get_args

    from aughor.ontology.overrides import TargetKind, delete_override
    # "segment" is accepted as the current spelling and mapped to the FROZEN store kind
    # "object_set" — the override store's directory name and YAML value (overrides.TargetKind).
    kind = "object_set" if kind == "segment" else kind
    # Read the store's own vocabulary instead of restating it. The hand-copied tuple that
    # used to live here omitted "action", so a kinetic action could be written by
    # PUT /ontology/kinetic-actions/{id} (target_kind="action") and then never deleted —
    # a list that has to be kept in sync by hand eventually is not.
    if kind not in get_args(TargetKind):
        raise HTTPException(status_code=400, detail=f"unknown override kind '{kind}'")
    effective = _resolve_schema(connection_id, schema_name)
    removed = delete_override(connection_id, effective, kind, target_id)  # type: ignore[arg-type]
    return {"removed": removed, "kind": kind, "target_id": target_id}


@router.get("/ontology/overrides", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def list_ontology_overrides(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """List all human overrides for this connection+schema (the version-controlled set)."""
    from aughor.ontology.overrides import load_overrides
    effective = _resolve_schema(connection_id, schema_name)
    return {"overrides": [o.model_dump() for o in load_overrides(connection_id, effective)]}


# ── Self-improving loop: engine-proposed recommendations ────────────────────────

@router.get("/ontology/recommendations", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def list_ontology_recommendations(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    ripe_only: bool = Query(default=True),
):
    """List engine-proposed ontology fixes (the self-improving loop's output).

    ripe_only (default) hides one-off sightings — only recommendations seen enough
    times to be worth a human's review are returned.
    """
    from aughor.ontology.recommendations import load_recommendations
    effective = _resolve_schema(connection_id, schema_name)
    recs = load_recommendations(connection_id, effective)
    if ripe_only:
        recs = [r for r in recs if r.ripe]
    return {"recommendations": [r.model_dump() for r in recs]}


@router.post("/ontology/recommendations/{rec_id}/accept", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def accept_ontology_recommendation(
    rec_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Promote a recommendation into an EXPLAIN-bound human override (override-wins path).

    A staged agent NOTE (kind ``column_note`` / ``table_note`` — ontology/agent_notes.py)
    is accepted through its own writer: a column note becomes a human-sourced column
    note, a table note becomes the glossary grain. Same review inbox, two sinks."""
    from aughor.ontology.agent_notes import accept_note
    from aughor.ontology.recommendations import accept
    effective = _resolve_schema(connection_id, schema_name)
    noted = accept_note(connection_id, effective, rec_id)
    if noted is not None:
        _invalidate_schema_cache(connection_id)
        return noted
    graph = _get_ontology_graph(connection_id, effective)
    explain, close = _explain_for(connection_id)
    try:
        res = accept(connection_id, effective, rec_id, graph, explain)
    finally:
        close()
    if res is None:
        raise HTTPException(status_code=404, detail=f"recommendation '{rec_id}' not found")
    return res


@router.post("/ontology/recommendations/{rec_id}/dismiss", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def dismiss_ontology_recommendation(
    rec_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Dismiss a recommendation so the loop won't resurface it."""
    from aughor.ontology.recommendations import get_recommendation, save_recommendation
    effective = _resolve_schema(connection_id, schema_name)
    rec = get_recommendation(connection_id, effective, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"recommendation '{rec_id}' not found")
    rec.status = "dismissed"
    save_recommendation(connection_id, effective, rec)
    return {"dismissed": True, "id": rec_id}


# ── Version-control round-trip: export ontology to files / import edits ─────────

@router.post("/ontology/export", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def export_ontology_tree(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Write the live ontology to a readable, version-controllable YAML tree — each declaration (a declared type,
    link, process or rule) under `declared/`, as the spec its door takes."""
    from aughor.ontology.filetree import export_tree, export_root
    from aughor.ontology.overrides import load_overrides
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    root = export_root(connection_id, effective)
    paths = export_tree(root, graph, load_overrides(connection_id, effective))
    return {"root": str(root), "files": len(paths)}


@router.post("/ontology/import", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def import_ontology_tree(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Re-import on-disk edits to the exported tree as EXPLAIN-bound overrides, and each declaration in it.

    Edits are diffed against the PRE-override auto-built graph, so re-importing an
    unedited export is a no-op and only changed fields become overrides. A declaration — a declared type, link,
    process or rule, under `declared/` — is declared again through its own door, counted and refused with the
    reason; one the overrides tree already holds unchanged is left as it is. A declared type's later edits are not
    in its file: each is made again through its own door.
    """
    # G1: an import writes overrides in BULK — the same governed semantic edit the two
    # single-field override endpoints above have always gated, arriving by the door that
    # was never locked.
    from aughor import govern
    govern.guard("ontology.import", connection_id)
    from aughor.ontology.filetree import declaration_spec, export_root, import_tree, read_declarations
    from aughor.ontology.overrides import bind_overrides, find_override, save_override
    from aughor.ontology.store import load_ontology
    effective = _resolve_schema(connection_id, schema_name)
    fingerprint = _latest_fingerprint(connection_id, effective)
    base = load_ontology(connection_id, effective, fingerprint) if fingerprint else None
    if base is None:
        base = _get_ontology_graph(connection_id, effective)
    if base is None:
        raise HTTPException(status_code=404, detail="Ontology not available")

    root = export_root(connection_id, effective)
    declarations, unreadable = read_declarations(root)
    doors = {"entity": _declare_entity_core, "link": _declare_link_core, "process": _declare_process_core,
             "rule": _declare_rule_core}
    declared = []
    for kind, target, spec, edits in declarations:
        row = {"kind": kind, "target": target, "declared": False, "note": ""}
        existing = find_override(connection_id, effective, kind, target)
        if existing is not None and existing.fields.get("declared") and declaration_spec(existing) == spec:
            row["note"] = "unchanged"
        else:
            try:
                doors[kind](spec, connection_id, effective)
            except HTTPException as exc:
                row["note"] = str(exc.detail)
            else:
                row["declared"] = True
                if edits:
                    row["note"] = f"declared; its later edits ({', '.join(edits)}) are made again through their own doors"
        declared.append(row)

    candidates = import_tree(root, base)
    saved = []
    if candidates:
        explain, close = _explain_for(connection_id)
        try:
            for ov in candidates:
                bind_overrides(ov, base, explain)
                save_override(connection_id, effective, ov)
                saved.append({"kind": ov.target_kind, "target": ov.target_id,
                              "bound": all(b.get("bound") for b in ov.binding.values()) if ov.binding else True})
        finally:
            close()
    return {"imported": len(saved), "overrides": saved, "declared": declared, "unreadable": unreadable}


# ── R11: per-column {visible, sample, index} config ─────────────────────────

@router.get("/ontology/column-config")
def get_column_config(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """The persisted per-column config, grouped per table. Readable regardless of
    the config store; `enabled` is kept in the payload as a stable contract for the
    editor UI, and is always true now that per-column config is unconditional."""
    from aughor.ontology.column_config import load_column_configs
    effective = _resolve_schema(connection_id, schema_name)
    tables: dict[str, dict[str, dict]] = {}
    for (table, column), fl in sorted(load_column_configs(connection_id, effective).items()):
        tables.setdefault(table, {})[column] = fl.model_dump()
    return {
        "connection_id": connection_id,
        "schema": effective,
        "enabled": True,
        "tables": tables,
    }


@router.put("/ontology/column-config", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def put_column_config(
    body: _ColumnConfigEdit,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Apply a human edit to one column's config — override-wins, rebuild-proof.
    Invalidates the schema cache so pruning changes AND notes reach the next
    prompt (a note rides the column line since 2026-08-14 — before that, the
    endpoint accepted one and nothing read it, and a note-only edit was 422'd)."""
    if (body.visible is None and body.sample is None and body.index is None
            and not (body.note or "").strip()):
        raise HTTPException(status_code=422,
                            detail="pass at least one of visible/sample/index/note")
    from aughor.ontology.column_config import set_column_flags
    effective = _resolve_schema(connection_id, schema_name)
    flags = set_column_flags(
        connection_id, effective, body.table, body.column,
        visible=body.visible, sample=body.sample, index=body.index, note=body.note,
    )
    _invalidate_schema_cache(connection_id)
    return {
        "saved": True,
        "table": body.table,
        "column": body.column,
        "flags": flags.model_dump(),
    }


@router.post("/ontology/entities/merge", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def merge_ontology_entities(
    body: _MergeEntitiesRequest,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Apply a duplicate-entity merge (the confirm step for `/ontology/duplicate-entities`) as "two tables, one
    binding" (ROADMAP §3.15): each other type's table is bound onto `canonical_id` on its key — a static binding,
    counted one row per object — and the type becomes a PART of it, hidden from the map and listed under it. Nothing
    is deleted and nothing is repointed: a part keeps its objects, links and pages by its name, and removing the
    binding releases it. `keys` names, per type, the column of its table that holds the survivor's key when that is
    not the type's own key. The whole cluster is planned and counted first, and one step the data does not hold
    refuses the merge (400, every reason named) before anything is written. Written through the bind door into the
    overrides tree, so a rebuild keeps it. Gated + explicit — never automatic, because a wrong merge would corrupt
    the ontology."""
    if len(set(body.merge_ids)) < 2:
        raise HTTPException(status_code=400, detail="merge_ids must list at least 2 distinct entities")
    if body.canonical_id not in body.merge_ids:
        raise HTTPException(status_code=400, detail="canonical_id must be one of merge_ids")

    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.bindings import describe_with
    from aughor.ontology.dedup import merge_plan
    from aughor.semantic.object_types import describe_object_type
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    unknown = [e for e in body.merge_ids if e not in graph.entities]
    if unknown:
        raise HTTPException(status_code=404, detail=f"unknown entities: {', '.join(unknown)}")

    db = open_connection_for_with_schema(connection_id, graph.schema_name or effective)
    try:
        steps = merge_plan(graph, body.canonical_id, body.merge_ids, body.keys, describe_with(db), db)
    finally:
        db.close()
    refused = [f"{s.member}: {s.problem}" for s in steps if s.problem]
    if refused:
        raise HTTPException(status_code=400,
                            detail=f"nothing was merged into {body.canonical_id} — " + "; ".join(refused))

    absorbed: list[str] = []
    bindings: list[dict] = []
    warnings: list[str] = []
    for step in steps:
        if step.spec is not None:
            done = _bind_entity_core(body.canonical_id, step.name, {**step.spec, "absorb": True}, connection_id,
                                     effective)
            warnings.extend(done["warnings"])
            if done.get("binding"):
                bindings.append(done["binding"])
            if done.get("absorbed"):
                absorbed.append(done["absorbed"])
        else:
            got, why = _absorb_after_bind(connection_id, effective, body.canonical_id, step.table)
            if why:
                warnings.append(why)
            if got:
                absorbed.append(got)
    served = _get_ontology_graph(connection_id, effective)
    described = (describe_object_type(served, body.canonical_id)
                 if served is not None and body.canonical_id in served.entities else {})
    return {"merged_into": body.canonical_id, "absorbed": absorbed, "bindings": bindings,
            "parts": described.get("parts", []), "warnings": warnings}


@router.put("/ontology/actions/{action_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def override_ontology_action(
    action_id: str,
    body: _ActionOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    from aughor.ontology.store import patch_action
    effective = _resolve_schema(connection_id, schema_name)
    fingerprint = _latest_fingerprint(connection_id, effective)
    if not fingerprint:
        graph = _get_ontology_graph(connection_id, effective)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = patch_action(connection_id, effective, fingerprint, action_id, overrides)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")
    return updated.actions[action_id].model_dump()


# ── Lifecycle counts ───────────────────────────────────────────────────────────

@router.get("/ontology/entities/{entity_id}/lifecycle-counts")
async def get_entity_lifecycle_counts(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    loop = asyncio.get_running_loop()

    graph = await loop.run_in_executor(None, lambda: _get_ontology_graph(connection_id, schema_name))
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    if not entity.has_lifecycle or not entity.lifecycle_column or not entity.source_tables:
        return []

    table = entity.source_tables[0]
    col   = entity.lifecycle_column
    where = f"WHERE {entity.active_filter}" if entity.active_filter else ""
    sql   = f"SELECT {col} AS state, COUNT(*) AS cnt FROM {table} {where} GROUP BY {col} ORDER BY cnt DESC LIMIT 50"

    def _work():
        db  = open_connection_for(connection_id)
        try:
            res = db.execute("lifecycle_counts", sql)
        finally:
            try:
                db.close()
            except Exception:
                pass
        return res

    try:
        res = await loop.run_in_executor(None, _work)
        if res.error:
            raise HTTPException(status_code=500, detail=res.error)
        return [{"state": str(r[0]), "count": int(r[1])} for r in (res.rows or [])]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Rebuild ────────────────────────────────────────────────────────────────────

class OntologyRebuildError(RuntimeError):
    """A rebuild that saved no new graph. The message says why; ``kept`` says whether the schema still has the
    ontology it had before, and ``journaled`` whether the build got far enough to journal its own outcome."""

    def __init__(self, message: str, *, kept: bool, journaled: bool = False):
        super().__init__(message)
        self.kept = kept
        self.journaled = journaled


def rebuild_ontology_graph(connection_id: str, schema_name: str):
    """Build the ontology for one {connection, schema}; return ``(graph, last_build)``.

    🔴🔴 **This used to delete first and build never.** `POST /ontology/rebuild` invalidated the cached graph, then
    read it back through `_get_ontology_graph`, which by design never builds. "Rebuild ontology now" on a working
    ontology destroyed it and answered 422, or, on a connection with exactly one OTHER schema cached, answered 200
    with that schema's graph under the requested name. The hourly auto-refresh deleted the same way.

    Now it builds, through the `build_intelligence()` the birth job runs, inside `forced_rebuild` so unchanged data
    is re-extracted instead of answered by the fingerprint cache. Nothing is deleted: the builder saves over the
    cached entry only once it has a graph, so a failed build leaves the previous ontology where it was. Success is
    read back strictly, under the schema the build saved to (never through the read's one-cached-schema
    substitution), and must be a newer graph than the one that was there.

    Raises `OntologyRebuildError` for every failure. Heavy and blocking (profiles, extraction, a model call to
    enrich), so call it from a request thread or an executor, never on an event loop.
    """
    from aughor.db.connection import open_connection_for_with_schema
    from aughor.ontology.store import forced_rebuild, load_latest_ontology

    _invalidate_schema_cache(connection_id)
    # "default" is how this router and the builder spell NO schema, not a schema to scope the connection to.
    scope = None if schema_name == "default" else schema_name
    try:
        db = open_connection_for_with_schema(connection_id, scope)
    except Exception as exc:
        raise OntologyRebuildError(f"The connection could not be opened: {str(exc)[:300]}",
                                   kept=load_latest_ontology(connection_id, schema_name) is not None) from exc
    try:
        # The builder saves under the connection's own schema label, so read back under the same one.
        label = getattr(db, "_schema_name", None) or "default"
        before = load_latest_ontology(connection_id, label)
        if not hasattr(db, "build_intelligence"):
            raise OntologyRebuildError("This connection type has no ontology build.", kept=before is not None)
        try:
            with forced_rebuild(connection_id):
                db.build_intelligence()
        except Exception as exc:
            raise OntologyRebuildError(f"The build failed: {str(exc)[:300]}", kept=before is not None) from exc
        last_build = getattr(db, "last_build", None)
        last_build = last_build if isinstance(last_build, dict) else {}
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "closing the rebuild's connection is best-effort",
                     counter="ontology.rebuild_close", conn_id=connection_id)

    if last_build and not last_build.get("ok", True):
        raise OntologyRebuildError(
            f"The build stopped at {last_build.get('stage') or 'an unrecorded stage'}: "
            f"{last_build.get('error') or 'no reason was recorded'}",
            kept=before is not None, journaled=True)
    graph = load_latest_ontology(connection_id, label)
    if graph is None or (before is not None and graph.generated_at == before.generated_at):
        raise OntologyRebuildError("The build finished without saving a new graph for this schema.",
                                   kept=before is not None, journaled=bool(last_build))
    return graph, last_build


# Rebuild one schema's ontology from the data (see `rebuild_ontology_graph`). A failure answers 422 with the reason
# and whether the previous ontology is unchanged. A comment, not a docstring: the docstring would become the
# operation's OpenAPI description and move the generated client.
@router.post("/ontology/rebuild", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def rebuild_ontology(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    effective = _resolve_schema(connection_id, schema_name)
    try:
        graph, last_build = rebuild_ontology_graph(connection_id, effective)
    except OntologyRebuildError as exc:
        # In-memory file uploads (local_upload, dsn local://…) are empty on re-open, so their build produces no
        # graph. That is client-actionable, not a server fault: name it rather than repeat the build's words.
        from aughor.db.registry import get_dsn
        try:
            conn_type, dsn = get_dsn(connection_id)
        except Exception:
            conn_type, dsn = "", ""
        in_memory = conn_type == "local_upload" or str(dsn).startswith("local://")
        detail = (
            "Ontology can't be rebuilt for an in-memory file upload — its data isn't re-readable on rebuild. "
            "Re-upload the data to refresh."
            if in_memory else f"Ontology could not be rebuilt. {exc}"
        )
        if exc.kept:
            detail += " The previous ontology is unchanged."
        if not exc.journaled:
            # The build never reached the step that journals its own outcome; journal the failure here, so
            # "the ontology silently doesn't build" stays a queryable event.
            try:
                from aughor.kernel.ledger import Ledger
                Ledger.default().emit(
                    "ontology.build",
                    {"ok": False, "entities": 0, "stage": "rebuild", "error": detail, "in_memory": in_memory},
                    conn_id=connection_id,
                )
            except Exception as emit_exc:
                from aughor.kernel.errors import tolerate
                tolerate(emit_exc, "the rebuild's failure journal is best-effort",
                         counter="ontology.rebuild_journal", conn_id=connection_id)
        raise HTTPException(status_code=422, detail=detail) from exc
    # Industry-aware intelligence keystone: (re)infer the Business Profile whenever
    # the ontology is rebuilt, so the explorer's industry-specific angles are ready
    # before exploration. Best-effort — a profile failure must not fail the rebuild.
    # Only after a graph was really built: the inference is a model call.
    profile_industry = None
    try:
        from aughor.business_profile.infer import infer_business_profile
        from aughor.orgsettings import resolve_industry
        bp = infer_business_profile(connection_id, effective)
        profile_industry = resolve_industry(bp.industry)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Business-profile inference after ontology rebuild failed (non-fatal): %s", exc)
    out = {
        "ok": True,
        "schema_name": graph.schema_name,
        "generated_at": graph.generated_at,
        "entities": len(graph.entities),
        "industry": profile_industry,
    }
    if last_build.get("error"):
        # Built, but a best-effort stage did not finish (semantic enrichment): the graph is usable, and the
        # person who clicked should know what it lacks.
        out["warning"] = last_build["error"]
    return out


@router.get("/ontology/build-status")
def ontology_build_status(connection_id: str = BUILTIN_ID, limit: int = 5):
    """Surface the ontology build outcome — the WCH-3 observability the original
    'ontology silently doesn't build' symptom needed. Returns the connection's
    last in-memory build result (which stage failed + why) AND the recent
    ontology.build journal events (persistent trail across restarts)."""
    from aughor.kernel.ledger import Ledger
    last_build = None
    try:
        db = open_connection_for(connection_id)
        last_build = getattr(db, "last_build", None)
        db.close()
    except Exception:
        last_build = None
    events = Ledger.default().events(kind="ontology.build", conn_id=connection_id, limit=int(limit))
    return {"connection_id": connection_id, "last_build": last_build, "recent_builds": events}


# ── Skills (learned actions / procedural memory) ────────────────────────────────

def _skill_schema(connection_id: str, schema_name: Optional[str]) -> str:
    """Airtight {conn}:{schema} key for learned skills.

    An explicit schema_name (the UI passes one drawn from the graph's own schema
    list) is honored; otherwise we read the schema the live ontology graph is
    actually built under — the SAME value the planner's overlay reads from — never
    a connection-metadata guess.  This guarantees the write key == the read key.
    """
    if schema_name:
        return schema_name
    from aughor.memory.skills import resolve_active_schema
    return resolve_active_schema(connection_id)


@router.get("/ontology/skills")
def list_learned_skills(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Learned skills (origin='learned' QueryTemplates) for this connection/schema."""
    from aughor.memory.skills import load_learned_actions
    effective = _skill_schema(connection_id, schema_name)
    actions = load_learned_actions(connection_id, effective)
    return {"schema_name": effective, "skills": [a.model_dump() for a in actions.values()]}


@router.post("/ontology/skills/propose")
def propose_learned_skill(
    inv_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Crystallize a *candidate* skill from a finished investigation.

    Returns the proposed QueryTemplate WITHOUT persisting it — the UI shows it
    for confirmation, then calls POST /ontology/skills to save.
    """
    from aughor.memory.skills import propose_skill_from_investigation
    graph = _get_ontology_graph(connection_id, schema_name)
    # Key on the graph's own schema_name — the exact overlay read key.
    effective = graph.schema_name if graph else _skill_schema(connection_id, schema_name)
    t2e = dict(graph.table_to_entity) if graph else None
    candidate = propose_skill_from_investigation(inv_id, table_to_entity=t2e)
    if candidate is None:
        raise HTTPException(
            status_code=422,
            detail="Run is not skill-worthy (low confidence, ungrounded, or no read-only query).",
        )
    return {"schema_name": effective, "candidate": candidate.model_dump()}


@router.post("/ontology/skills", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def save_learned_skill(
    action: QueryTemplate,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Persist a confirmed learned skill, gated by a read-only dry-run (EXPLAIN)."""
    # G1: declared LOW, so this is auto-allowed and AUDITED rather than blocked — the point
    # is that saving a skill leaves a governance trail, not that it needs approval.
    from aughor import govern
    govern.guard("skill.save", connection_id)
    from aughor.memory.skills import save_skill

    effective = _skill_schema(connection_id, schema_name)

    def _validator(sql: str) -> bool:
        db = open_connection_for(connection_id)
        try:
            res = db.execute("skill_dry_run", f"EXPLAIN {sql}")
            return not res.error
        finally:
            try:
                db.close()
            except Exception:
                pass

    ok = save_skill(connection_id, effective, action, validator=_validator)
    if not ok:
        raise HTTPException(status_code=422, detail="Skill rejected: SQL is not read-only or failed dry-run.")
    return {"ok": True, "schema_name": effective, "id": action.id}


@router.post("/ontology/skills/{action_id}/use")
def use_learned_skill(
    action_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Increment a learned skill's usage_count (feeds per-skill autonomy)."""
    from aughor.memory.skills import record_skill_use
    from aughor.memory.trust import skill_autonomy
    effective = _skill_schema(connection_id, schema_name)
    count = record_skill_use(connection_id, effective, action_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="Learned skill not found.")
    return {"ok": True, "usage_count": count, "autonomy": skill_autonomy(count, connection_id)}


@router.delete("/ontology/skills/{action_id}")
def delete_learned_skill(
    action_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    from aughor.memory.skills import delete_skill
    effective = _skill_schema(connection_id, schema_name)
    if not delete_skill(connection_id, effective, action_id):
        raise HTTPException(status_code=404, detail="Learned skill not found.")
    return {"ok": True}


# ── Autonomy (trust → L0–L3 ladder) ─────────────────────────────────────────────

@router.get("/ontology/autonomy")
def get_autonomy(connection_id: str = BUILTIN_ID):
    """The connection's earned L0–L3 autonomy level, computed from reflection
    signals (aughor.memory.trust)."""
    from aughor.memory.trust import autonomy_level
    return autonomy_level(connection_id)


@router.get("/framing/misses")
def framing_misses(connection_id: str = BUILTIN_ID):
    """PENDING item 12 — the questions on this connection that reached none of its declared business
    terms: how many, when, and (while the session log keeps the run) what was asked. The record holds
    each run's trace id, never the question's text; a person turns a miss into a synonym."""
    from aughor.ontology.framing_misses import misses
    return misses(connection_id)
