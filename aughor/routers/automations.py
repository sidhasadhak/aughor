"""Automations API (Wave A) — CRUD, run-now, and the tick history.

Every route self-gates on the ``automations.engine`` flag, so with it off the whole surface 404s
and nothing here is reachable — the same shape ``routers/kinetic.py`` uses.

``GET /automations/{id}/runs`` is the endpoint the subsystem exists for: it answers "did it run,
and why did nothing happen?", which the monitor API cannot answer because ``monitor_alerts`` stores
only the ticks that fired.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from aughor.automations.graph import build_graph
from aughor.automations.models import Automation, Condition, Effect
from aughor.automations.store import (
    delete_automation,
    get_automation,
    get_layout,
    get_runs,
    list_automations,
    pause_automation,
    set_automation_enabled,
    set_layout,
    upsert_automation,
)

router = APIRouter(tags=["automations"])


# ── Request bodies ─────────────────────────────────────────────────────────────

class CreateAutomationRequest(BaseModel):
    conn_id: str
    name: str
    description: str = ""
    conditions: list[Condition] = Field(min_length=1)
    condition_logic: str = "all"
    effects: list[Effect] = Field(min_length=1)
    fallback_effect: Optional[Effect] = None
    enabled: bool = True
    paused_until: Optional[str] = None
    expires_at: Optional[str] = None
    max_retries: int = 1
    retry_backoff_seconds: float = 30.0
    #: DS-7 — `ordered` (the default, every pre-DS-7 automation) or `parallel` (steps
    #: run as their arrows allow). An authored field like `condition_logic` above, so
    #: the PUT carries it and a rename cannot silently re-serialise a parallel chain.
    scheduling: str = "ordered"
    #: DS-14 — may an external MCP client invoke this chain? Authored, so it rides the PUT
    #: like `scheduling` above. Missing from this model the field was accepted, echoed back
    #: as True by the response model, and dropped on the way to the store: the PUT answered
    #: 200 and the flag never persisted. Found by driving it live, and it is the SAME shape
    #: as the half-added-column trap the store warns about one layer down — a request model
    #: that silently ignores a key is the HTTP spelling of a named binding that does.
    exposed_as_tool: bool = False


class ProposeRequest(BaseModel):
    """DS-15 — what a person says, and which connection to ground it in."""

    outcome: str = Field(description="What the chain should achieve, in the user's words.")
    conn_id: str = Field(description="The connection the chain runs against.")


class PauseRequest(BaseModel):
    until: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC to mute until, or null to clear the mute.",
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/automations/vocabulary")
def vocabulary():
    """B1 — what each effect kind publishes and may bind, for the canvas's ports.

    FETCHED by the client rather than mirrored into it: a hand-copied vocabulary rots
    in the worst direction (a key added here while the UI keeps refusing it), and the
    required-keys mirror already costs a guard test to keep honest. `publishes: null`
    is the OPEN set — a declared-action step's keys are that action's own outcome
    shape, and the canvas draws it as a wildcard port rather than no port."""
    from aughor.automations.dataflow import (
        BINDABLE_FIELDS, FAN_PUBLISHED, GUARD_OPS, ITEM_ALIAS, ITEM_VALUE, MAX_FAN_OUT,
        PUBLISHED_KEYS, UNARY_OPS,
    )
    return {
        "kinds": {
            kind: {
                "publishes": list(keys) if keys is not None else None,
                "bindable": list(BINDABLE_FIELDS.get(kind, ())),
            }
            for kind, keys in PUBLISHED_KEYS.items()
        },
        # W1 — the guard operators, for the same reason as the ports above: a picker
        # that offered an operator the engine cannot evaluate would fail at 09:00, and
        # `unary` is what tells the form to hide the second field rather than ask for a
        # value that is then ignored.
        "guard_ops": [{"op": op, "label": label, "unary": op in UNARY_OPS}
                      for op, label in GUARD_OPS.items()],
        # W2 — the fan-out's own vocabulary, fetched for the third time for the same
        # reason: the cap is enforced by the engine and by the model, and an authoring
        # form carrying its own copy would drift into offering a 200-item list the save
        # then refuses.
        #
        # ⚠️ DS-11 amended the rule this used to state. It read: "a step may SOURCE a
        # fan-out only if its `publishes` is null — the open set — because every closed
        # set in this plane is strings." The second half stopped being true the moment a
        # remote read landed: `integration_call` publishes `items`, a real list, and its
        # keys are its OPERATION's rather than its kind's — so it is `null` here (the
        # kind cannot answer) and closed-with-a-list at `/integrations/operations`, which
        # is where a fan-source picker for that kind must look.
        "for_each": {
            "max_items": MAX_FAN_OUT,
            "item_alias": ITEM_ALIAS,
            "item_value_key": ITEM_VALUE,
            "publishes": list(FAN_PUBLISHED),
        },
    }


@router.get("/automations/palette")
def palette(conn_id: Optional[str] = None):
    """DS-1 — what may be placed on the Design canvas, and whether it works HERE.

    A sibling of `/automations/vocabulary` rather than an extension of it: that document
    is a pure closed set (the same constants `validate_chain` refuses against) cached
    module-side and shared by every row on screen, while this one is deployment-shaped —
    it counts Slack bots, triggers, subscriptions and monitors, and its answer changes the
    moment a reader creates one. Folding a per-deployment reading into a cached constant
    table is how a palette comes to insist you have no bots an hour after you made one.

    `conn_id` scopes the objects that are themselves connection-scoped (subscriptions,
    monitors); omit it and those probes count across the workspace.
    """
    # DS-10 — served FROM the one registry, not from a second reading of the same tables.
    # The shape is unchanged (this is the canvas's wire contract), but the rows now come
    # through `components()`, so "does this kind exist" and "does it work here" have
    # exactly one answer on this deployment instead of two that happen to agree.
    from aughor.components import components

    out = []
    for c in components(conn_id=conn_id):
        if c.family not in ("trigger", "effect"):
            continue
        out.append({
            "kind": c.kind,
            "group": "trigger" if c.family == "trigger" else "action",
            "label": c.label, "description": c.description,
            "icon": c.icon, "priority": c.priority,
            "publishes": c.outputs,
            "bindable": [p.name for p in c.inputs if p.bindable],
            "availability": c.availability, "reason": c.reason,
        })
    return {"entries": out}


class LayoutRequest(BaseModel):
    """`{alias: {x, y}}` — where each step sits on the Design canvas."""

    layout: dict = Field(default_factory=dict)


def _layout_user_id(request: Request) -> str:
    """The account key for a canvas arrangement — the identified user, or a shared
    'default' on localhost / identity-off so one operator sees the same canvas on any
    device. Upgrades to true per-user the moment RBAC identity is bound, with no
    migration. Same resolution the cockpit's layout uses; two account keys that could
    disagree would put a user's arrangement somewhere they cannot find it."""
    try:
        from aughor.security.authz import get_principal
        p = get_principal(request)
        return p.user_id if p and p.user_id else "default"
    except Exception:
        return "default"


@router.get("/automations/{automation_id}/layout")
def read_layout(automation_id: str, request: Request):
    """Where the caller arranged this automation's steps (`{}` if never touched).

    Server-side and account-keyed rather than `localStorage`, for the reason the cockpit
    settled once: an arrangement a person made on their laptop and cannot find on their
    desktop reads as the product having forgotten it. No 404 for an unknown automation —
    an empty layout IS the answer for one nobody has arranged.
    """
    return {"layout": get_layout(automation_id, _layout_user_id(request))}


@router.put("/automations/{automation_id}/layout")
def write_layout(automation_id: str, body: LayoutRequest, request: Request):
    """Persist the whole arrangement. Separate from `PUT /automations/{id}` on purpose:
    that route carries the governed record a person authored, this one carries where they
    happened to drag it, and folding a view preference into the record the engine reads
    is how a rename comes to move somebody's nodes."""
    set_layout(automation_id, _layout_user_id(request), body.layout or {})
    return {"ok": True}


@router.get("/automations")
def list_all(conn_id: Optional[str] = None, enabled_only: bool = False):
    return {"automations": [a.model_dump() for a in list_automations(conn_id, enabled_only)]}


@router.get("/automations/runs")
def all_runs(conn_id: Optional[str] = None, limit: int = 100):
    """Runs across EVERY automation, newest first (Wave CR5) — the store read
    (`get_runs`) always supported this; only the per-automation route existed.
    Declared before `/automations/{automation_id}` so "runs" is never read as
    an id."""
    return {"runs": [r.model_dump()
                     for r in get_runs(conn_id=conn_id, limit=min(int(limit), 500))]}


@router.post("/automations/propose")
def propose(body: ProposeRequest):
    """DS-15 — describe an outcome, get a drawn chain with a dry-run receipt.

    Creation by PROPOSAL, the shape every governed write here already has: nothing is
    saved, the draft is refused by the same validators a save runs, and a human arms it.
    The response is the authoring payload the canvas already knows how to render, so the
    proposal arrives as an editable chain rather than as a message about one.

    Declared BEFORE `/automations/{automation_id}` for the reason DS-14 learned the hard
    way one route up: FastAPI matches in declaration order, and a static segment after the
    path-parameter route is never reached.
    """
    from aughor.automations.propose import propose_chain

    proposal = propose_chain(body.outcome, conn_id=body.conn_id)
    if proposal.verdict != "proposed":
        # 200, not 4xx: "nothing here can do that" is an ANSWER to the question that was
        # asked, and the reason is the useful half of it. A 422 would make the client
        # render a failure where the server produced a considered refusal.
        return {"verdict": proposal.verdict, "reason": proposal.reason,
                "notes": proposal.notes, "draft": proposal.draft}
    return {"verdict": "proposed", "draft": proposal.draft,
            "dry_run": proposal.dry_run, "notes": proposal.notes,
            "reason": ""}


class ImportFlowRequest(BaseModel):
    #: The flow document, verbatim — whatever the Langflow/Flowise editor exported.
    flow: dict


@router.post("/automations/import")
def import_foreign_flow(body: ImportFlowRequest):
    """DS-16 — the migration funnel: a Langflow (or archived-Flowise) flow, translated.

    Model/prompt/agent/tool nodes map onto a draft chain (plus a suggested agent record);
    code-carrying nodes are REFUSED with the no-code-injection law and the declarative
    alternative named. Nothing is saved and nothing runs — the draft seeds the same
    canvas-first create view a DS-15 proposal does, and the per-node report IS half the
    receipt. Declared before `/automations/{automation_id}` (FastAPI declaration order).
    """
    from aughor.automations.import_flow import import_flow
    from aughor.automations.models import Automation

    result = import_flow(body.flow)
    if result.verdict != "imported":
        # 200, not 4xx — same reasoning as /propose: "nothing mapped" with each refusal
        # named is an answer, not a failure.
        return result.model_dump()
    # DS-15's law, with the importer's one honest exception: validate by CONSTRUCTING
    # the real Automation (every model validator plus the chain validator), failing
    # CLOSED on anything STRUCTURAL — an unknown binding, a cycle, a kind that does not
    # exist. A MISSING REQUIRED KEY is different: a translation cannot know this
    # deployment's bot_id, and the create canvas's incomplete gate exists precisely to
    # collect it — so those become "to fill" notes and the draft still seeds.
    #
    # Two passes, deliberately: pydantic SKIPS the Automation-level chain validator when
    # a field validator fails, so a missing key would MASK a broken binding — the first
    # construction names the holes, the second runs with the holes placeholder-filled so
    # the chain law actually gets its turn.
    from aughor.automations.models import required_keys

    to_fill: list[str] = []
    filled = []
    for i, e in enumerate(result.draft["effects"], start=1):
        cfg = dict(e.get("config") or {})
        for key in required_keys(str(e.get("kind") or ""), family="effect"):
            if not cfg.get(key):
                to_fill.append(f"Action {i} needs {key}")
                cfg[key] = "…"          # a visible placeholder, never a plausible value
        filled.append({**e, "config": cfg})
    try:
        Automation(conn_id="import-preview", name=result.name or "Imported flow",
                   conditions=result.draft["conditions"], effects=filled)
    except Exception as exc:
        return {**result.model_dump(), "verdict": "nothing_mapped", "draft": None,
                "reason": f"the translated chain failed the save-time validators: {exc}"}
    # The draft that seeds carries the HOLES, not the placeholders — a "…" that reached
    # a saved chain would be a message posted to a real channel.
    return {**result.model_dump(), "to_fill": to_fill}


# NOTE: declared BEFORE `/automations/{automation_id}` on purpose — FastAPI
# matches routes in declaration order, so a static segment that comes after the
# path-parameter route is never reached: `/automations/tools` was answering
# "Automation not found" because `tools` was being read as an id.
@router.get("/automations/tools")
def exposed_tools(conn_id: str = ""):
    """DS-14 — the automations this deployment offers as MCP tools.

    Read by the MCP server at start, so what an outside agent can invoke is whatever the
    owners OPTED IN — never every automation the API happens to hold.

    Both flags must hold. `exposed_as_tool` is the intent and `enabled` is the switch, and
    a chain someone deliberately switched off must not stay callable from outside: that
    would make the off switch a lie for exactly the caller nobody is watching.

    A name collision is refused HERE rather than left for the server to resolve, because
    the two tools would be indistinguishable to the client that has to choose between
    them. The first by creation order keeps the name and the rest are reported with the
    reason, so the answer is one an operator can act on instead of a silently shorter list.
    """
    from aughor.automations.store import list_automations
    from aughor.mcp.server import automation_tool_name

    rows = [a for a in list_automations(conn_id=conn_id or None)
            if getattr(a, "exposed_as_tool", False) and a.enabled]
    tools: list[dict] = []
    refused: list[dict] = []
    taken: set[str] = set()
    for a in sorted(rows, key=lambda x: (x.created_at or "", x.id)):
        name = automation_tool_name(a.name)
        if name in taken:
            refused.append({"id": a.id, "name": a.name, "tool_name": name,
                            "reason": f"another exposed automation already answers to "
                                      f"'{name}' — rename one of them"})
            continue
        taken.add(name)
        tools.append({
            "id": a.id, "name": a.name, "tool_name": name,
            "description": a.description or "",
            "conn_id": a.conn_id,
            # The steps, so the tool's description can say what the chain DOES. A model
            # choosing between tools cannot choose on "runs an automation".
            "steps": [e.kind for e in (a.effects or [])],
        })
    return {"tools": tools, "refused": refused}


@router.get("/automations/{automation_id}")
def get_one(automation_id: str):
    a = get_automation(automation_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


def _validation_detail(exc: ValidationError) -> list[dict]:
    """Pydantic errors, safe to serialise.

    `exc.errors()` embeds the ORIGINAL exception object under `ctx` for a `value_error`
    — which is what a `model_validator` raising `ValueError` produces. Starlette then
    fails to JSON-encode the 422 body and the response becomes a 500, so a mistake the
    user could fix arrives as "the server broke". Found live: an automation with a
    forward step reference returned 500 while the validator was working perfectly.

    `include_context=False` drops the object; the message Pydantic already rendered into
    `msg` is the part a caller needs.
    """
    return exc.errors(include_url=False, include_context=False)


def _save(automation: Automation) -> dict:
    """Persist, turning the store's integrity refusals into a 422 a form can render.

    DS-9's subchain cycle check lives on the store (it is the one write path, and it needs
    the rest of the library to answer). It raises `ValueError`, which would otherwise leave
    the route as a 500 — "the server broke" for a mistake the author can see and fix in the
    editor they are already looking at. Same shape, and the same lesson, as
    `_validation_detail`: a refusal the user can act on must not arrive as a crash.
    """
    try:
        return upsert_automation(automation).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/automations")
def create(body: CreateAutomationRequest):
    """Create an automation. A malformed condition or effect is rejected HERE, at construction —
    it never reaches the store, so a broken automation cannot sit in the DB looking schedulable."""
    try:
        automation = Automation(**body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    return _save(automation)


@router.put("/automations/{automation_id}")
def update(automation_id: str, body: CreateAutomationRequest):
    existing = get_automation(automation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    try:
        # `CreateAutomationRequest` is the AUTHORING shape — what a person types. Every
        # field OUTSIDE it belongs to the engine, and the upsert is a full-row replace,
        # so anything not carried here is erased by a rename. It was: `last_run_at` and
        # `last_status` went back to null (the card read "never run" again) and
        # `agent_id` — which the engine reads to decide who a step runs AS — went back
        # to empty. Third of its family in this subsystem, which is why it now has a test.
        automation = Automation(**body.model_dump(), id=automation_id,
                                created_at=existing.created_at,
                                agent_id=existing.agent_id,
                                last_run_at=existing.last_run_at,
                                last_status=existing.last_status)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    return _save(automation)


@router.delete("/automations/{automation_id}")
def remove(automation_id: str):
    if not delete_automation(automation_id):
        raise HTTPException(status_code=404, detail="Automation not found")
    # Owner cascade (A4): grants an automation minted, and proposals it staged, are its
    # property — per-owner revocation, so deleting the automation takes them along. Kept at the
    # router (application) layer so the automations store never imports the kinetic plane.
    from aughor.actions import grants, inbox
    grants.purge_owner("automation", automation_id)
    inbox.purge_source(f"automation:{automation_id}")
    # DS-17 — and its webhook token, for the same reason: it is the automation's property.
    # The route already refuses a token whose automation is gone, so this is not a hole
    # being closed — it is a credential not being left behind, which is what the same
    # cascade does for a grant. Found by driving the receipt: deleting the chain left the
    # row sitting there with nothing to open.
    from aughor.automations.webhooks import revoke_webhook_token
    revoke_webhook_token(automation_id)
    return {"deleted": automation_id}


@router.post("/automations/{automation_id}/enabled")
def set_enabled(automation_id: str, enabled: bool = True):
    a = set_automation_enabled(automation_id, enabled)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


@router.post("/automations/{automation_id}/exposed")
def set_exposed(automation_id: str, exposed: bool = True):
    """DS-17 — flip only the MCP-tool flag (`enabled`'s sibling, and shaped like it).

    Not the full PUT, deliberately. `exposed_as_tool` is the field that was once accepted,
    echoed back as true and dropped because `CreateAutomationRequest` did not carry it; a
    Deploy menu that had to send the whole automation to flip one boolean would re-enter
    that trap on every click, and the PUT-erase family says a surface eventually sends one
    field short. A query param rather than a body, to mirror `/enabled` exactly — two
    sibling switches with two different call shapes is a papercut with no upside.
    """
    from aughor.automations.store import set_automation_exposed
    a = set_automation_exposed(automation_id, exposed)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


@router.get("/automations/{automation_id}/doors")
def automation_doors(automation_id: str):
    """DS-17 — every way into this chain from outside, and which of them are open.

    The states are the palette's plus one: a door has a POSITION, so `ready` splits into
    `open` (traffic comes through now) and `closed` (in place, one gesture away). Reading
    this opens nothing — the verbs are the routes beside it.
    """
    from aughor.automations.doors import doors, summary
    a = get_automation(automation_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    rows = doors(a)
    return {"doors": rows, "summary": summary(rows)}


@router.post("/automations/{automation_id}/webhook")
def issue_webhook(automation_id: str, request: Request):
    """DS-17 — mint this chain's webhook token and return it ONCE.

    The plaintext is in this response and nowhere else, ever: every later read is a
    comparison. Re-calling rotates, which is what makes rotation a thing an operator will
    actually do — and it is the only remedy for a leaked token, so it must not be buried.

    Refused when the chain has no `webhook` trigger, and that refusal is load-bearing
    rather than tidy. A token fires a chain through the same path Run now uses, which
    deliberately BYPASSES the schedule — so a token issued for a chain that has no webhook
    trigger would be a way to run any scheduled chain on demand, unauthenticated. The
    trigger on the canvas is the author's consent to being called; without it there is none.
    """
    a = get_automation(automation_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    if not any(c.kind == "webhook" for c in (a.conditions or [])):
        raise HTTPException(
            status_code=409,
            detail="This chain has no Webhook trigger — add one on the canvas first.")

    from aughor.automations.webhooks import issue_webhook_token
    token = issue_webhook_token(automation_id)
    return {
        "automation_id": automation_id,
        "token": token,
        # The whole URL, assembled server-side from the request the caller actually
        # reached us on. A client building it from a hardcoded host is how a copied URL
        # comes to point at localhost from someone else's machine.
        "url": str(request.url_for("call_webhook", automation_id=automation_id)),
        "header": "Authorization: Bearer <token>",
        "shown_once": True,
    }


@router.delete("/automations/{automation_id}/webhook")
def revoke_webhook(automation_id: str):
    """DS-17 — delete this chain's token. The trigger stays on the canvas.

    Revocation is deletion, not a flag: a revoked row is one somebody can un-revoke, and
    the absence IS the state the door reads. The chain keeps its Webhook trigger because
    design and deployment are different questions — which is the whole of this wave.
    """
    from aughor.automations.webhooks import revoke_webhook_token
    return {"automation_id": automation_id, "revoked": revoke_webhook_token(automation_id)}


@router.post("/automations/{automation_id}/pause")
def pause(automation_id: str, body: PauseRequest):
    """Mute until a timestamp (or clear it). Distinct from disabling: a pause has an end, and the
    run history keeps recording *why* nothing fired while it holds."""
    a = pause_automation(automation_id, body.until)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


class RunNowRequest(BaseModel):
    """DS-3 — the id this run will have.

    A run writes a span per step under `trace_id == run_id` WHILE it runs, so a surface
    that wants to watch one needs the id before the request returns — and this request
    does not return until the whole chain has finished. Supplying it is the whole
    difference between watching a run and being told about it afterwards. Omitted, the
    engine mints one exactly as before."""

    run_id: Optional[str] = None


@router.post("/automations/{automation_id}/run")
def run_now(automation_id: str, body: Optional[RunNowRequest] = None):
    """Run one automation immediately, through the same gates the heartbeat uses — so a gated
    automation returns the REASON it is gated rather than silently doing nothing."""
    from aughor.automations.scheduler import trigger_now
    run = trigger_now(automation_id, run_id=(body.run_id if body else None) or None)
    if run is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return run.model_dump()


def _dry_run_payload(automation: Automation, until: Optional[str] = None) -> dict:
    """``{"run": …, "graph": …}`` — the run AND the same graph an execution view reads.

    The graph is built here rather than fetched afterwards because a dry run is never
    stored: there is no id for `GET /automations/{id}/graph?run=…` to look up. Returning
    both means the canvas renders a preview through the code path it already uses for a
    real run, which is the whole reason a dry run returns an `AutomationRun` at all.

    DS-2 — `until` stops the walk after that step. The graph is still built from the WHOLE
    automation, so every node is drawn and only the walked ones carry an outcome: the
    steps beyond the cut read as untouched rather than as missing, which is the difference
    between "not asked" and "did nothing".
    """
    from aughor.automations.engine import run_automation
    run = run_automation(automation, dry_run=True, until_alias=until)
    return {"run": run.model_dump(),
            "graph": {**build_graph(automation, run), "dry_run": True},
            "until": until or ""}


@router.post("/automations/{automation_id}/dry-run")
def dry_run_stored(automation_id: str, until: Optional[str] = None):
    """B2 — walk a STORED automation without dispatching anything.

    Distinct from `POST /{id}/run`, which is the real thing through the real gates: this
    one answers "what would it do" for an automation that is not armed, on a day its
    schedule is not due — the two states a design spends all of its life in before it
    goes live.
    """
    automation = get_automation(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="no such automation")
    return _dry_run_payload(automation, until)


@router.post("/automations/dry-run")
def dry_run_draft(body: CreateAutomationRequest, until: Optional[str] = None):
    """B2 — walk an UNSAVED design. The one a canvas needs.

    "Try it before you arm it" is worth most before the thing exists at all, and the
    editor holds a draft the store has never seen. Validation is the create route's,
    unchanged: a draft that could not be saved is refused here with the same 422, so a
    preview can never be more permissive than the thing it previews.
    """
    try:
        automation = Automation(**body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    return _dry_run_payload(automation, until)


@router.get("/automations/{automation_id}/graph")
def graph(automation_id: str, run: str = ""):
    """The automation as a graph — the same shape whether it has run or not.

    `run` selects Execution mode: `latest` decorates the nodes with the most recent run,
    an explicit run id with that one. Omitted, the response is Structure — what is
    designed. One derivation, two readings, so the picture cannot drift from the run.
    """
    automation = get_automation(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="no such automation")

    chosen = None
    if run:
        runs_ = get_runs(automation_id=automation_id, limit=1 if run == "latest" else 50)
        chosen = (runs_[0] if runs_ else None) if run == "latest" else \
            next((r for r in runs_ if r.id == run), None)
        if chosen is None:
            # An honest empty rather than a 404: the automation exists and its STRUCTURE
            # is exactly what the caller asked to see decorated. Refusing the whole
            # graph because it has never run would hide the thing they came to look at.
            return {**build_graph(automation), "run_missing": True}
    graph = build_graph(automation, chosen)
    # VA-4c — the runs rail, so a canvas can offer "which run?" without a second request
    # and without inventing its own idea of recency. Bounded: a rail is for picking, and
    # a list long enough to scroll is a different surface.
    graph["runs"] = [
        {"id": r.id, "outcome": r.outcome, "at": r.started_at,
         "duration_ms": r.duration_ms,
         "steps": len(r.effects or []),
         "failed": sum(1 for e in (r.effects or [])
                       if e.status not in ("executed", "skipped"))}
        for r in get_runs(automation_id=automation_id, limit=12)
    ]
    graph["run_id"] = getattr(chosen, "id", "") if chosen is not None else ""
    return graph


@router.get("/automations/{automation_id}/runs")
def runs(automation_id: str, limit: int = 50):
    return {"runs": [r.model_dump() for r in get_runs(automation_id=automation_id, limit=limit)]}
