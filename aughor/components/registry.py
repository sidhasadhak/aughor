"""The one typed roster the palette reads (DS-10).

Five families, five existing sources of truth, one shape:

===================  ==========================================================
family               read from
===================  ==========================================================
``trigger``          ``automations.palette.TRIGGERS`` + its prerequisite probes
``effect``           ``automations.palette.ACTIONS`` + the same probes
``connector``        ``connectors.registry`` (REGISTRY / FORM_FIELDS / drivers)
``platform_tool``    ``agent.platform_tools.platform_tools()``
``mcp_tool``         ``mcp.server.mcp``'s own tool manager
``declared_action``  the connection's ontology overlay (its declared writes)
===================  ==========================================================

**Adapted, never copied.** Every collector calls the module that owns its family and
reshapes what comes back. A registry that held its own table of effect kinds would be a
second place to add the seventh one, and the seventh one would be added to exactly one of
them — which is the failure this whole wave exists to end, one level up from where it
usually happens.

**The law: a component references a governed capability.** Every row names, in
``governed_by``, the module that governs its use — the approval gate for a declared write,
the one engine for an automation step, the connection registry for a connector. It is a
real dotted module path and a ratchet imports every distinct value, so a component cannot
claim a governor that does not exist. That is what stops this from becoming a catalogue of
things a deployment merely wishes it had, which is precisely what a 400-component palette
is when nobody checks.

**Availability is measured, never assumed.** A family whose probe raises is reported
``ready`` rather than dimmed — an unreachable store is our problem, not the reader's — and
only a successful count of zero dims a row. That rule is `palette.entries`'s, inherited
here deliberately: two surfaces that dim on different evidence teach a reader the product
has two opinions about what it can do.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

FAMILIES: tuple[str, ...] = (
    "trigger", "effect", "connector", "platform_tool", "mcp_tool", "declared_action",
)

#: The display states a component may carry. **Empty by intent** — nothing in this
#: deployment is beta or legacy today, and the point of naming them here is that when
#: something is, it is registry METADATA rather than a word hard-coded into one surface's
#: rendering. A badge invented in a component would be invisible to every other reader.
BADGES: tuple[str, ...] = ("beta", "legacy")

#: Every module that may appear in ``Component.governed_by``. Dotted paths, because a
#: ratchet imports each one: a taxonomy nobody can check is how a roster starts describing
#: a system that no longer exists.
GOVERNORS: tuple[str, ...] = (
    "aughor.automations.engine",     # every automation step runs through this one engine
    "aughor.actions.executor",       # the one governed-write executor (criteria, then approval)
    "aughor.govern.actions",         # the graduated-approval gate a declared write passes
    "aughor.db.registry",            # connections, their secrets and their drivers
    "aughor.agent.platform_tools",   # the read-only platform roster the agent may call
    "aughor.mcp.server",             # the MCP surface, and everything it exposes outward
)


class ComponentPort(BaseModel):
    """One declared, typed input to a component.

    Typed rather than free-form because the point of the registry is that a surface can
    RENDER a component it has never heard of. ``visible_when`` carries the dynamic-field
    rule their contract shape has and ours did not: `{"other_input": ["value", …]}` means
    this field is shown only while that one holds one of those values, so a form can hide
    the credential fields of an auth mode nobody picked without the form knowing what any
    particular connector is.
    """
    name: str
    label: str = ""
    type: str = "string"                     # string | number | boolean | object | list
    required: bool = False
    #: A credential. Never placed in a URL, a query string or a log line — the same rule
    #: the connector catalog states for its own `secret_fields`, carried onto the port so a
    #: renderer cannot lose it on the way.
    secret: bool = False
    placeholder: str = ""
    visible_when: dict = Field(default_factory=dict)
    #: May a chain BIND this input to an earlier step's output (`{"$from": …}`)? Carried on
    #: the port rather than derived from `required`, because the two are independent — a
    #: declared action's `params` is both — and a palette rebuilt from a derivation would
    #: quietly start drawing edges onto ports the engine does not read.
    bindable: bool = False


class Component(BaseModel):
    """One capability this deployment has, in the one shape every family reports."""

    #: Unique across families: ``<family>:<kind>`` for the singletons, with the connection
    #: folded in where the same kind means different things on different connections
    #: (``declared_action:fixture:issue_refund``). Stable, because a surface will remember
    #: it — a layout, a favourite, a DS-14 tool name.
    id: str
    family: Literal["trigger", "effect", "connector", "platform_tool", "mcp_tool",
                    "declared_action"]
    kind: str
    label: str
    description: str = ""
    icon: str = ""
    #: The curated order within a family; ties break alphabetically at the serving layer.
    priority: int = 100

    inputs: list[ComponentPort] = Field(default_factory=list)
    #: What later steps may read. ``None`` is the OPEN set — a component whose outputs
    #: cannot be enumerated (a declared action returns whatever its dispatcher returns), so
    #: a binding onto it is accepted unchecked rather than wrongly refused. Exactly the
    #: distinction `PUBLISHED_KEYS` already draws; `[]` means "publishes nothing".
    outputs: Optional[list[str]] = None

    availability: Literal["ready", "needs_setup", "unavailable"] = "ready"
    reason: str = ""
    badges: list[str] = Field(default_factory=list)

    #: DS-14 reads this: may this component be served to a model as a callable tool? True
    #: for the two families that already ARE tools and for a declared action (the agent can
    #: already propose one). False for the rest — an automation step is not callable on its
    #: own, and saying otherwise would promise DS-14 a surface that does not exist.
    exposable_as_tool: bool = False

    #: THE LAW. The module that governs using this component; one of ``GOVERNORS``.
    governed_by: str


# ── collectors — one per family, each reading that family's own source ────────────

def _ports_from_json_schema(schema: dict) -> list[ComponentPort]:
    """A JSON-Schema `parameters` object (agent tools, MCP tools) as typed ports."""
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    out: list[ComponentPort] = []
    for name, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        out.append(ComponentPort(
            name=str(name),
            label=str(spec.get("title") or "").strip(),
            type=str(spec.get("type") or "string"),
            required=name in required,
            placeholder=str(spec.get("description") or "")[:120],
        ))
    return out


def _automation_components(conn_id: Optional[str]) -> list[Component]:
    """Triggers and effects — from the palette's own entries, prerequisite reading included.

    `palette.entries` already answers the hard half (does the object this kind REFERENCES
    exist on this deployment), so calling it is what keeps one answer rather than two. The
    required-config keys become required ports; the bindable fields become the optional
    ones, which is the same split `validate_chain` refuses against.
    """
    from aughor.automations.models import required_keys
    from aughor.automations.palette import entries as palette_entries

    out: list[Component] = []
    for e in palette_entries(conn_id):
        family = "trigger" if e["group"] == "trigger" else "effect"
        required = required_keys(e["kind"], family=family)
        bindable = tuple(e.get("bindable") or ())
        ports = [ComponentPort(name=k, required=True, bindable=k in bindable)
                 for k in required]
        ports += [ComponentPort(name=k, bindable=True) for k in bindable
                  if k not in required]
        out.append(Component(
            id=f"{family}:{e['kind']}", family=family, kind=e["kind"],
            label=e["label"], description=e["description"], icon=e["icon"],
            priority=e["priority"], inputs=ports, outputs=e.get("publishes"),
            availability=e["availability"], reason=e.get("reason", ""),
            # A declared-action step is the one automation kind that reaches the approval
            # gate; every other kind is governed by the engine that runs it.
            governed_by=("aughor.actions.executor" if e["kind"] == "kinetic_action"
                         else "aughor.automations.engine"),
        ))
    return out


def _connector_components() -> list[Component]:
    """Connector types — from the live registry, not `connectors/catalog.json`.

    The catalog is a GENERATED artifact for people reading the repo; the registry is what
    the running process can actually open. They agree today, and the moment they disagree
    the catalog is the stale one — so a roster that answers "what can this install do"
    must read the registry, and must ask about drivers per request (an install can change
    under a running process, which is why `/connectors/types` recomputes too).
    """
    from aughor.connectors.registry import (
        CATEGORIES, DSN_PREVIEWS, FORM_FIELDS, REGISTRY, missing_drivers,
    )

    # The full set, from CATEGORIES — NOT `REGISTRY.supported_types()`.
    #
    # The builder registry holds the types with an `open_connection()`, which deliberately
    # excludes the two KNOWLEDGE connectors: Notion and Confluence are configured and
    # authenticated like any other connection and then synced by
    # `POST /connections/{id}/knowledge-sync`, never queried. They are real capabilities of
    # this deployment — implemented, documented in `connectors/catalog.json`, and reachable
    # by a live route — and a roster built off the builders alone omits them, which is the
    # precise failure this wave is against. (`/connectors/types` is built off the builders
    # and so has never offered them; that gap is real and is not DS-10's to close, because
    # what it would change is a creation FORM, not a roster.)
    builders = set(REGISTRY.supported_types())
    ordered_types = ["duckdb", "postgres"] + sorted(
        t for t in CATEGORIES if t not in ("duckdb", "postgres"))
    out: list[Component] = []
    for n, conn_type in enumerate(ordered_types):
        missing = missing_drivers(conn_type)
        queryable = conn_type in builders or conn_type in ("duckdb", "postgres")
        ports = [
            ComponentPort(name=str(f.get("key", "")), label=str(f.get("label", "")),
                          secret=bool(f.get("secret")), required=not f.get("optional"),
                          placeholder=str(f.get("placeholder", "")))
            for f in (FORM_FIELDS.get(conn_type) or []) if f.get("key")
        ]
        out.append(Component(
            id=f"connector:{conn_type}", family="connector", kind=conn_type,
            label=conn_type,
            # Category first, then the DSN shape: "warehouse · bigquery://project-id" tells
            # a reader what KIND of thing this is before it tells them how to spell it.
            description=(f"{CATEGORIES.get(conn_type, 'built-in')} · "
                         f"{DSN_PREVIEWS.get(conn_type, conn_type)}"
                         + ("" if queryable else " · indexed for context, never queried")),
            icon="plug", priority=10 * (n + 1), inputs=ports,
            # A connection publishes no chain values; it is a place to read FROM.
            outputs=[],
            # A driver this install cannot import is `unavailable`, not `needs_setup`:
            # nothing the reader can fill into a form fixes a missing package, and
            # offering them a form that ends in an ImportError is the failure
            # `/connectors/types` was written to stop.
            availability="ready" if not missing else "unavailable",
            reason=("" if not missing
                    else f"driver not installed here: {', '.join(missing)}"),
            governed_by="aughor.db.registry",
        ))
    return out


def _platform_tool_components(conn_id: Optional[str]) -> list[Component]:
    from aughor.agent.platform_tools import platform_tools

    out: list[Component] = []
    for n, spec in enumerate(platform_tools(conn_id or "")):
        out.append(Component(
            id=f"platform_tool:{spec.name}", family="platform_tool", kind=spec.name,
            label=spec.name.replace("_", " "),
            description=(spec.description or "").strip().split("\n")[0][:300],
            icon="terminal", priority=10 * (n + 1),
            inputs=_ports_from_json_schema(spec.parameters or {}),
            # A tool returns a payload nobody here can enumerate — the OPEN set.
            outputs=None, exposable_as_tool=True,
            governed_by="aughor.agent.platform_tools",
        ))
    return out


def _mcp_tool_components() -> list[Component]:
    """The MCP surface's own tools, read from its tool manager rather than by counting
    decorators. A grep for `@mcp.tool()` answers what the FILE says; the manager answers
    what the SERVER would serve, which is the thing a reader is actually asking about."""
    from aughor.mcp.server import mcp

    # `_tool_manager` is FastMCP's, not ours, and reaching into a third-party internal is
    # a thing to do knowingly: the public `list_tools()` is a coroutine, and this collector
    # is called from sync code where there may or may not be a loop already running —
    # `asyncio.run` would be correct in a threadpool worker and a crash inside the event
    # loop. The reach is contained to this one line, the family is wrapped by the
    # collector guard in `components()` (so a FastMCP upgrade that moves it degrades to
    # "no MCP tools" rather than taking the roster down), and a test counts the `@mcp.tool`
    # decorators in the source INDEPENDENTLY — so that degradation fails CI instead of
    # quietly shipping a roster with a family missing.
    out: list[Component] = []
    for n, tool in enumerate(mcp._tool_manager.list_tools()):
        schema = {}
        meta = getattr(tool, "fn_metadata", None)
        if meta is not None:
            schema = getattr(meta, "arg_model", None) and meta.arg_model.model_json_schema() or {}
        out.append(Component(
            id=f"mcp_tool:{tool.name}", family="mcp_tool", kind=tool.name,
            label=tool.name.replace("_", " "),
            description=(tool.description or "").strip().split("\n")[0][:300],
            icon="plug", priority=10 * (n + 1),
            inputs=_ports_from_json_schema(schema),
            outputs=None, exposable_as_tool=True,
            governed_by="aughor.mcp.server",
        ))
    return out


def _declared_action_components(conn_id: Optional[str]) -> list[Component]:
    """The connection's declared, governed writes.

    The only DEPLOYMENT-SHAPED family whose membership is authored rather than shipped:
    every other family is the same on every install of this version, and this one is
    whatever the ontology overlay declares. Scoped to a connection for that reason — asking
    for the roster without one returns none rather than every connection's, because a
    declared action is meaningful only against the connection that declares it.
    """
    if not conn_id:
        return []
    from aughor.ontology.store import load_latest_ontology

    graph = load_latest_ontology(conn_id, None)
    actions = getattr(graph, "kinetic_actions", None) or {}
    out: list[Component] = []
    for n, (action_id, action) in enumerate(sorted(actions.items())):
        ports = [
            ComponentPort(name=getattr(p, "name", ""), required=True)
            for p in (getattr(action, "params", None) or []) if getattr(p, "name", "")
        ]
        risk = str(getattr(action, "risk", "high"))
        out.append(Component(
            id=f"declared_action:{conn_id}:{action_id}", family="declared_action",
            kind=action_id,
            label=str(getattr(action, "display_name", "") or action_id),
            description=str(getattr(action, "description", "") or "")[:300],
            icon="bolt", priority=10 * (n + 1), inputs=ports, outputs=None,
            exposable_as_tool=True,
            # Named for what it is, not dimmed: a high-risk action is fully available —
            # it simply stops for a human on the way (DS-8). Reporting it as needs_setup
            # would tell the reader to go and configure something that is already correct.
            reason=f"risk: {risk}" if risk else "",
            governed_by="aughor.govern.actions",
        ))
    return out


_COLLECTORS: dict[str, Any] = {
    "trigger": _automation_components,
    "effect": _automation_components,
    "connector": lambda conn_id: _connector_components(),
    "platform_tool": _platform_tool_components,
    "mcp_tool": lambda conn_id: _mcp_tool_components(),
    "declared_action": _declared_action_components,
}


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def components(conn_id: Optional[str] = None, family: Optional[str] = None,
               q: Optional[str] = None) -> list[Component]:
    """The roster: everything this deployment can do, ordered, filtered and searchable.

    A collector that RAISES contributes nothing and does not take the roster down with it:
    one unimportable subsystem must not make the whole surface answer "this install can do
    nothing", which is both false and the most alarming possible way to be wrong. It is
    logged, and the families that did answer are still served.
    """
    wanted = FAMILIES if not family else tuple(f for f in FAMILIES if f == family)
    out: list[Component] = []
    seen_automation = False
    for fam in wanted:
        # `trigger` and `effect` come from ONE call — the palette answers both at once, and
        # calling it twice would run every prerequisite probe a second time.
        if fam in ("trigger", "effect"):
            if seen_automation:
                continue
            seen_automation = True
        try:
            got = _COLLECTORS[fam](conn_id)
        except Exception:
            logger.warning("component registry: the %s family could not be read",
                           fam, exc_info=True)
            continue
        out.extend(got)
    if family:
        out = [c for c in out if c.family == family]
    if q:
        needle = _norm(q)
        out = [c for c in out
               if needle in _norm(f"{c.label} {c.description} {c.kind} {c.family}")]
    # Family order first (the table in the module docstring), then the curated priority,
    # then alphabetical — the same three keys the palette panel already sorts by, so a
    # reader moving between the two surfaces does not have to relearn the order.
    order = {f: i for i, f in enumerate(FAMILIES)}
    out.sort(key=lambda c: (order.get(c.family, 99), c.priority, c.label.lower()))
    return out
