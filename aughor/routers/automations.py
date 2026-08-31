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
        # then refuses. A step may SOURCE a fan-out only if its `publishes` above is
        # `null` — the open set — because every closed set in this plane is strings.
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
    from aughor.automations.palette import entries
    return {"entries": entries(conn_id)}


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


@router.post("/automations")
def create(body: CreateAutomationRequest):
    """Create an automation. A malformed condition or effect is rejected HERE, at construction —
    it never reaches the store, so a broken automation cannot sit in the DB looking schedulable."""
    try:
        automation = Automation(**body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    return upsert_automation(automation).model_dump()


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
    return upsert_automation(automation).model_dump()


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
    return {"deleted": automation_id}


@router.post("/automations/{automation_id}/enabled")
def set_enabled(automation_id: str, enabled: bool = True):
    a = set_automation_enabled(automation_id, enabled)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


@router.post("/automations/{automation_id}/pause")
def pause(automation_id: str, body: PauseRequest):
    """Mute until a timestamp (or clear it). Distinct from disabling: a pause has an end, and the
    run history keeps recording *why* nothing fired while it holds."""
    a = pause_automation(automation_id, body.until)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


@router.post("/automations/{automation_id}/run")
def run_now(automation_id: str):
    """Run one automation immediately, through the same gates the heartbeat uses — so a gated
    automation returns the REASON it is gated rather than silently doing nothing."""
    from aughor.automations.scheduler import trigger_now
    run = trigger_now(automation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return run.model_dump()


def _dry_run_payload(automation: Automation) -> dict:
    """``{"run": …, "graph": …}`` — the run AND the same graph an execution view reads.

    The graph is built here rather than fetched afterwards because a dry run is never
    stored: there is no id for `GET /automations/{id}/graph?run=…` to look up. Returning
    both means the canvas renders a preview through the code path it already uses for a
    real run, which is the whole reason a dry run returns an `AutomationRun` at all.
    """
    from aughor.automations.engine import run_automation
    run = run_automation(automation, dry_run=True)
    return {"run": run.model_dump(), "graph": {**build_graph(automation, run), "dry_run": True}}


@router.post("/automations/{automation_id}/dry-run")
def dry_run_stored(automation_id: str):
    """B2 — walk a STORED automation without dispatching anything.

    Distinct from `POST /{id}/run`, which is the real thing through the real gates: this
    one answers "what would it do" for an automation that is not armed, on a day its
    schedule is not due — the two states a design spends all of its life in before it
    goes live.
    """
    automation = get_automation(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="no such automation")
    return _dry_run_payload(automation)


@router.post("/automations/dry-run")
def dry_run_draft(body: CreateAutomationRequest):
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
    return _dry_run_payload(automation)


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
