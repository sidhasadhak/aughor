"""Metrics catalog, health scorecard, and playbook endpoints."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aughor.licensing import Capability, gate

logger = logging.getLogger(__name__)

from aughor.semantic.metrics import (
    ALL_DATASETS,
    GLOBAL_CONNECTION,
    MetricDefinition,
    compute_value,
    definition_at,
    delete_metric,
    get_metric,
    home_schema,
    is_org_scope,
    list_metrics,
    move_metric,
    org_scope,
    organisation_visible,
    same_dataset,
    save_metric,
    validate_metric,
    check_freshness,
)
from aughor.security.authz import caller, connection_owner_guard

#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
router = APIRouter(tags=["metrics"], dependencies=[Depends(connection_owner_guard)])

#: G1 — transition verbs that map onto a DECLARED governed action, and the action each one
#: is. Module-level rather than a local dict so the enforcement ratchet can see it: an action
#: guarded through a lookup is still enforced, but a check that only reads literal
#: ``guard("…")`` arguments would call it a gap and push the code into whatever shape the
#: check could parse. The ratchet reads this mapping instead.
#:
#: Verbs absent here (``deprecate``) are left to the existing transition validation rather
#: than reclassified HIGH by ``classify``'s fail-safe — widening the gate is its own
#: governance decision, and G1 is about closing declared gaps.
GUARDED_TRANSITIONS = {"approve": "metric.approve", "propose": "metric.propose"}


class MetricRequest(BaseModel):
    name: str
    #: WHICH connection this definition governs. The store has always keyed metrics by
    #: the (connection, name) PAIR — this model did not carry the field, so every write
    #: through the API fell back to the model default `"*"` and became global. Two
    #: consequences, both seen live: a second connection could never hold its own
    #: `revenue` (the duplicate check 409'd on the name alone), and EDITING a
    #: connection-scoped metric silently re-wrote it as global — which is how theLook's
    #: `sales_volume_by_category`, whose SQL reads `inventory_items`, appeared in
    #: LuxExperience's catalogue where that table does not exist.
    #:
    #: Two e-commerce businesses do not share a formula; the tables and columns differ.
    #: `"*"` stays the default so an intentionally global house metric is still one call.
    connection: str = GLOBAL_CONNECTION
    #: The dataset it belongs to (`MetricDefinition.schema_name`); ``"*"`` — every dataset of the
    #: connection. Sending another dataset than the one addressed moves the definition there.
    schema_name: Optional[str] = None
    label: str
    sql: str = ""
    tables: list[str] = []
    dimensions: list[str] = []
    filters: list[str] = []
    unit: Optional[str] = None
    caveats: Optional[str] = None
    #: `additive` | `non_additive`. Not carried by this model before, so every edit erased it.
    additivity: Optional[str] = None
    target_value: Optional[float] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    target_period: Optional[str] = None
    benchmark_source: Optional[str] = None
    # Governance fields (M21)
    owner: Optional[str] = None
    freshness_sla: Optional[str] = None
    freshness_check_sql: Optional[str] = None
    quality_tests: list[str] = []
    lineage: list[str] = []
    wrong_usage_examples: list[str] = []
    #: IGNORED. Approval is stamped by the approve transition with the person signed in — a create
    #: that carried `approved_by` used to land already approved, and an edit's typed value was
    #: silently overwritten. Kept so an older client that still sends them is not refused.
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    # Arc BR-2 — a person's correction of the time fields; sending them stamps the editor
    # as the one who confirmed them (`time_confirmed_by`).
    time_column: Optional[str] = None
    time_kind: Optional[str] = None
    outcome_column: Optional[str] = None
    until_column: Optional[str] = None
    settles_after_days: Optional[int] = None
    time_grain: Optional[str] = None
    #: IGNORED — stamped by the server with the person signed in (see `_stamp_time_edit`).
    time_confirmed_by: Optional[str] = None


@router.get("/metrics")
def get_metrics(connection_id: Optional[str] = None):
    """The registry, optionally narrowed to one connection.

    `connection_id` applies `list_metrics`' own connection-shadows-global rule (own · folded ·
    the connection's ORGANISATION · global). It stays OPTIONAL so every existing caller is
    byte-identical: making it required would turn a re-key into a caller migration, and each
    unconverted site becomes a silent global read that looks correct (the same reasoning
    `list_metrics` records for its own default). Unscoped, with identity on, the list is the
    caller's organisation's: the global rows, its `org:` rows and its visible connections' —
    never another organisation's (the 2027 study §E item 2)."""
    rows = list_metrics(connection_id=connection_id)
    # `home_schema` — the dataset each belongs to, resolved as the store resolves it (a definition
    # that names none belongs to the one its SQL reads), so a client matches a catalogue row to its
    # definition by dataset and name, never by name alone.
    return [{**m.model_dump(), "home_schema": home_schema(m)}
            for m in (rows if connection_id else organisation_visible(rows))]


# The path parameter is `conn_id`, not `connection_id`: `require_capability` (the `gate`
# below) declares `connection_id` as a QUERY parameter, and FastAPI refuses a name declared
# both ways on one route. `connection_owner_guard` accepts either spelling, so DATA-06
# ownership is enforced on these doors exactly as on the rest of the router.
def _declared_schema(conn_id: str) -> Optional[str]:
    """The schema a connection is registered on, or None.

    The explorer keeps a connection's suggested metrics on its business profile, keyed by
    (connection, schema). A caller that names no schema read the bare key, so a connection
    registered on one schema showed none of them: theLook's Semantic Layer listed 0 explorer
    metrics where its `thelook` profile holds 3 (2026-10-07). Only when that schema HAS a
    profile of its own: a connection whose only profile is the bare one keeps reading it. A
    connection with no declared schema (a multi-dataset workspace) is unchanged — its caller
    must say which dataset."""
    try:
        from aughor.business_profile import store as profile_store
        from aughor.db.registry import get_meta
        declared = (get_meta(conn_id) or {}).get("schema_name") or None
        if declared and profile_store.load_raw(conn_id, declared) is not None:
            return declared
    except Exception as exc:  # noqa: BLE001 — an unknown connection keeps the bare read
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the connection's declared schema could not be read; the catalogue reads the bare key",
                 counter="metrics.catalogue_declared_schema")
    return None


@router.get("/metrics/catalogue/{conn_id}")
def get_metric_catalogue(conn_id: str, schema: Optional[str] = None):
    """Every metric that APPLIES to this connection — defined, industry and explorer.

    Not the same list as `/metrics`: that one is the registry, and most of what applies to
    a connection is not in the registry yet. A pack's recipe is role-bound until this
    connection binds those roles, and the explorer's judgement lives on the business
    profile. Both are computed here and materialised only when someone edits one."""
    from aughor.semantic.metric_catalogue import catalogue_for, removed_for

    # ``schema=*`` — every dataset of the connection at once (the Semantic Layer's "All schemas").
    schema = schema or _declared_schema(conn_id)
    rows = catalogue_for(conn_id, schema)
    return {
        "connection_id": conn_id,
        "schema": schema,
        "metrics": [r.as_dict() for r in rows],
        # The proposals a person removed here — listed so a removal can be undone, never re-proposed.
        "removed": removed_for(conn_id, schema),
        "counts": {
            "total": len(rows),
            "defined": sum(1 for r in rows if r.source == "defined"),
            "industry": sum(1 for r in rows if r.source == "industry"),
            "explorer": sum(1 for r in rows if r.source == "explorer"),
            "needs_binding": sum(1 for r in rows if r.state == "needs_binding"),
            "needs_formula": sum(1 for r in rows if r.state == "needs_formula"),
            # Counted apart from `needs_formula` on purpose: a connection where every
            # metric lands here is telling you about the CONNECTION, not about missing SQL.
            "formula_rejected": sum(1 for r in rows if r.state == "formula_rejected"),
        },
    }


@router.post("/metrics/catalogue/{conn_id}/{name}/materialise",
             status_code=201, dependencies=[gate(Capability.METRICS_DEFINE)])
def materialise_metric(conn_id: str, name: str, schema: Optional[str] = None,
                       actor: str = ""):
    """Copy-on-write: turn a computed row into an editable definition of this connection and dataset.

    Lands as `draft` — see `metric_catalogue.materialise`. A recipe this connection has not bound
    lands as a draft whose SQL is the person's to write, with the package's formula beside it.
    ``actor`` is ignored: the draft is the signed-in person's."""
    from aughor.semantic.metric_catalogue import MaterialiseError, materialise

    try:
        return materialise(conn_id, name, schema or _declared_schema(conn_id), actor=caller()).model_dump()
    except MaterialiseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/metrics/catalogue/{conn_id}/{name}/remove", dependencies=[gate(Capability.METRICS_DEFINE)])
def remove_proposal(conn_id: str, name: str, schema: Optional[str] = None):
    """Remove a PROPOSED metric — an industry recipe or the explorer's — from this dataset (``*``:
    every dataset). The user, 2026-10-07: *"user needs the right to remove the proposed Metric"*.
    Recorded, with who and when, so a rebuild never proposes it again, and restorable."""
    from aughor.semantic.metric_catalogue import SOURCE_DEFINED, find_entry
    from aughor.semantic.metrics import dismiss_proposal

    dataset = schema or _declared_schema(conn_id) or ALL_DATASETS
    entry = find_entry(conn_id, name, dataset)
    if entry is not None and entry.source == SOURCE_DEFINED:
        raise HTTPException(status_code=409, detail=(
            f"{entry.label!r} is a definition, not a proposal — remove it from its editor "
            f"(an approved one is retired first)."))
    record = dismiss_proposal(conn_id, entry.schema if entry is not None else dataset, name, by=caller(),
                              label=(entry.label if entry is not None else name),
                              source=(entry.source if entry is not None else ""))
    _audit({"metric": name, "connection": conn_id, "schema_name": record["schema_name"],
            "action": "remove_proposal", "source": record["source"]})
    return record


@router.post("/metrics/catalogue/{conn_id}/{name}/restore", dependencies=[gate(Capability.METRICS_DEFINE)])
def restore_removed_proposal(conn_id: str, name: str, schema: Optional[str] = None):
    """Undo a removal: the proposal is listed again."""
    from aughor.semantic.metrics import restore_proposal

    dataset = schema or _declared_schema(conn_id) or ALL_DATASETS
    if not restore_proposal(conn_id, dataset, name):
        raise HTTPException(status_code=404, detail=f"No removed proposal named {name!r} here.")
    _audit({"metric": name, "connection": conn_id, "schema_name": dataset, "action": "restore_proposal"})
    return {"ok": True, "name": name, "schema_name": dataset}


def _audit(event: dict) -> None:
    """One `metric.governance` event, stamped with who did it and when."""
    from datetime import datetime, timezone

    from aughor.kernel.ledger import Ledger
    Ledger.default().emit("metric.governance", {
        "actor": caller(), "at": datetime.now(timezone.utc).isoformat(), **event})


#: 2026-09-26, the user: *"let every metric have mandatorily a SELECT statement"*. A row
#: written before the rule keeps its expression until its FORMULA is edited — confirming its
#: dates or changing its label must not refuse a metric someone already approved.
_STATEMENT_RULE = ("A metric's SQL is a whole SELECT statement (CTEs allowed) that returns one row "
                   "with the metric's value — for example: SELECT SUM(amount) AS revenue FROM orders "
                   "WHERE status = 'active'. An aggregate expression without SELECT is no longer "
                   "accepted.")


def _require_statement(sql: str, existing) -> None:
    from aughor.semantic.metric_statement import is_statement
    if is_statement(sql):
        return
    if existing is not None and (sql or "").strip() == (existing.sql or "").strip():
        return
    raise HTTPException(status_code=422, detail=_STATEMENT_RULE)


def _require_binds(sql: str, connection: str, name: str, tables, filters, existing) -> None:
    """Refuse a definition the engine cannot run — the check the save door never had.

    A governed definition was the one artifact nothing validated. `_require_statement`
    above asks only whether the text LOOKS like a statement; it never parsed it, never
    bound it, never checked a column existed. Measured on theLook 2026-09-27, that let two
    definitions be saved AND approved as the organisation's revenue: `SUM(total_amount)`,
    naming a column the warehouse does not have, and `SELECT (SUM(sale_price) AS revenue
    FROM order_items WHERE status <> 'Cancelled'` — one paren short, so it does not parse
    at all. Both then held every Slack send that stated revenue, and the reader was told the
    number was untrustworthy rather than that the definition was broken.

    The platform already owned the answer: `conn.dry_run` runs against EVERY query in
    `sql/safety.preflight_repair`. This asks it once more, at the door where a definition
    becomes governance.

    What is refused and what is not, deliberately:

    * A parse error is refused always — it needs no warehouse and cannot be a false alarm.
    * A bind failure is refused when the connection answered. That is the engine's own
      verdict on the engine's own schema.
    * Unreachable connection, no dry-run support, or a global (`*`) definition with no
      connection to ask: NOT refused. An author must not be blocked by infrastructure they
      cannot see, so the check fails OPEN — but it says so (counter + log) rather than
      returning a silent pass, because "checked and fine" and "never checked" must not
      look identical (§ the typed-verdict rule).
    * SQL the edit did not change is never re-checked. A save that only edits a caveat must
      not start failing because a table was dropped months after the formula was approved.

    The runnable form is what is checked — `as_statement` over the declared tables and
    filters — because that is exactly what the value path executes, not the stored text.
    """
    text = (sql or "").strip()
    if not text:
        return
    if existing is not None and text == (str(getattr(existing, "sql", "") or "")).strip():
        return                      # untouched formula — not this save's business
    from aughor.semantic.metric_checks import runs_on
    verdict, why = runs_on(text, connection, name, tables, filters)
    if verdict == "refused":
        raise HTTPException(status_code=422, detail=why)


def _restate_briefings(connection: str) -> None:
    """A governed definition changed, so every cached Briefing for its connection is stale.

    Measured 2026-09-28: after approving five of theLook's metrics, the Month Briefing (which
    had been rebuilt) measured twelve while the Day measured five and the Week one — and the
    Day's five said *"no approved definition; approve one in the Semantic Layer to measure it"*
    about metrics approved minutes earlier. Nothing was wrong with the period logic: each view
    was serving a two-hour cache built before the approval, and only the period someone
    happened to regenerate told the truth. Forcing a person to press Regenerate once per period
    to see a governance change is a cache pretending to be an answer.

    Best-effort and silent about nothing: an invalidation that fails is counted, because the
    next reader would otherwise be told yesterday's answer with today's confidence.
    """
    if not connection:
        return
    try:
        from aughor.knowledge import briefing as _briefing
        if connection == GLOBAL_CONNECTION or is_org_scope(connection):
            # A house-wide or an organisation's definition reaches every connection that does not
            # define its own, so every connection's cached Briefings were measured without it.
            from aughor.db.registry import list_connections
            dropped = sum(_briefing.invalidate(str(c.get("id"))) for c in list_connections() if c.get("id"))
            if dropped:
                logger.info("metric change invalidated %d cached briefing(s) across connections", dropped)
            return
        dropped = _briefing.invalidate(connection)
        if dropped:
            logger.info("metric change invalidated %d cached briefing(s) for %s", dropped, connection)
    except Exception as exc:  # noqa: BLE001 — the metric change stands either way
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the metric changed but its connection's cached Briefings could not be "
                      "dropped; they will read as stale until they expire",
                 counter="metrics.briefing_invalidate")


class ProposalsRequest(BaseModel):
    """What the metric editor sends to be offered what the platform proposes for a definition:
    its runnable statement (when it was written as an expression) and the dates it could be
    grained at."""
    connection: str
    sql: str = ""
    tables: list[str] = []
    filters: list[str] = []
    name: str = "value"


@router.post("/metrics/proposals")
def metric_proposals(req: ProposalsRequest):
    """The platform's proposals for a definition, read from the profiler's latest entry (no
    warehouse call). ``statements``: the runnable statement(s) for an expression written
    before the rule — one when its table is declared or one profiled table carries its
    columns, several when several do (the note says so; a person picks); ``[]`` for a
    statement as written. ``candidates``: every date- or time-typed column of the tables
    the statement reads, written as the grain, each table's main date first — only those
    tables (the user, 2026-09-26: *"only when there are multiple date or timestamp columns
    in the table proposed in the SQL statement, only then the user may choose"*). Each empty
    list carries its reason."""
    from aughor.semantic.metric_statement import date_candidates, proposed_statements, statement_tables
    from aughor.tools.profile_cache import profile_entry_for
    try:
        # The entry that describes THIS statement's tables — not merely the newest, which on a
        # connection of several schemas describes whichever was profiled last.
        profile = profile_entry_for(req.connection, statement_tables(req.sql) or req.tables)
    except Exception as exc:  # noqa: BLE001 — a failed read is said, not an empty list
        why = f"the profile could not be read ({type(exc).__name__})"
        return {"statements": [], "statement_note": why, "candidates": [], "note": why}
    if not profile:
        why = ("this connection has no profile yet — explore it first, then the platform can "
               "propose its tables and dates")
        return {"statements": [], "statement_note": why, "candidates": [], "note": why}
    statements, statement_note = proposed_statements(req.sql, req.tables, req.filters, req.name, profile)
    candidates = date_candidates(req.sql, req.tables, profile)
    read = statement_tables(req.sql) or [t for t in req.tables if str(t).strip()]
    if candidates:
        note = ""
    elif not read:
        note = "the statement names no table, so there is no date to propose — the FROM comes first"
    else:
        note = f"no date or timestamp column was profiled on {', '.join(read)}"
    return {"statements": statements, "statement_note": statement_note,
            "candidates": candidates, "note": note}


class GenerateSqlRequest(BaseModel):
    """What the editor holds about the metric when the person asks the model to write its
    statement. `definition` is the catalogue's definition when the row has one, else the
    caveats the person wrote."""
    connection: str
    name: str
    label: str = ""
    definition: str = ""
    unit: str = ""
    tables: list[str] = []
    filters: list[str] = []
    dimensions: list[str] = []
    wrong_usage_examples: list[str] = []


@router.post("/metrics/generate-sql", dependencies=[gate(Capability.METRICS_DEFINE)])
async def generate_metric_sql(req: GenerateSqlRequest):
    """The model writes the metric's statement from the definition in the editor — ONE model
    call, on the person's click (the user, 2026-09-26: *"generate SQL query for metric …
    right at the SQL statement input box … based on the metric in question"*). The
    platform's own SQL writer over this connection's schema, framed for a governed metric
    (`semantic.metric_author`); the answer is checked, never rewritten — a grouped, limited,
    multi-column or unparsable query is served WITH the finding in `refused`, so the person
    sees the text and the verdict together."""
    from uuid import uuid4

    from aughor.db.connection import open_connection_for
    from aughor.semantic.metric_author import MetricBrief, write_statement
    from aughor.telemetry import bind_trace

    if not req.name.strip():
        raise HTTPException(status_code=422, detail="Name the metric first — the name becomes the statement's column.")
    try:
        db = open_connection_for(req.connection)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    brief = MetricBrief(name=req.name.strip(), label=req.label, definition=req.definition, unit=req.unit,
                        tables=list(req.tables), filters=list(req.filters), dimensions=list(req.dimensions),
                        wrong_usage=list(req.wrong_usage_examples))
    trace_id = uuid4().hex
    loop = asyncio.get_running_loop()

    def _work():
        try:
            with bind_trace(trace_id):
                return write_statement(brief, db)
        finally:
            try:
                db.close()
            except Exception as exc:  # noqa: BLE001 — a close that fails is logged, not raised over the answer
                from aughor.kernel.errors import tolerate
                tolerate(exc, "metrics.generate_sql.close", counter="metrics.generate_sql")

    try:
        out = await loop.run_in_executor(None, _work)
    except Exception as e:  # noqa: BLE001 — the model or the warehouse failing is said with its text
        raise HTTPException(status_code=502, detail=f"The statement could not be written: {e}")
    if not out["sql"]:
        raise HTTPException(status_code=422, detail=f"No statement written: {out['refused']}.")
    # The model's text is served even when the check found it wanting — `refused` says what,
    # and the editor shows both; hiding the text behind a refusal was the first cut's mistake.
    return {"sql": out["sql"], "refused": out["refused"], "note": out["note"],
            "model": out["model"], "trace_id": trace_id}


def _require_own_organisation(connection: str) -> None:
    """An organisation-scoped definition (`org:<id>`) is written only by that organisation when identity
    is on (the 2027 study §E item 2); identity off is one tenant, and every scope is its own."""
    if not is_org_scope(connection):
        return
    from aughor.security.authz import tenant_scope
    org = tenant_scope()
    if org is not None and connection != org_scope(org):
        raise HTTPException(status_code=403, detail={
            "code": "ORGANISATION_SCOPE_DENIED",
            "why": f"{connection!r} is another organisation's scope; this organisation writes {org_scope(org)!r}"})


#: What a client may not set on a definition: governance is the transitions', and approval and a
#: date confirmation are stamped with the person signed in.
_SERVER_OWNED = ("status", "version", "proposed_by", "proposed_at", "approved_by", "approved_at",
                 "time_confirmed_by", "time_source",
                 # Arc OC-3 — the entity is confirmed through its own door, by the person signed in
                 "entity", "entity_confirmed_by")


def _stamp_time_edit(existing, req: MetricRequest) -> dict:
    """The time fields this save writes. Ones the edit SENT are a person's — confirmed by the person
    signed in, never by a name the form carried (the user, 2026-10-07: *"user did not enter the name
    again because the user is already logged in"*)."""
    from aughor.semantic.metric_time import TIME_FIELDS, merge_time_edit
    sent = req.model_dump(include=(set(TIME_FIELDS) - {"time_confirmed_by"}) & req.model_fields_set)
    if sent:
        sent["time_confirmed_by"] = caller()
    try:
        return merge_time_edit(existing, sent)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _plain_unit(unit: Optional[str]) -> Optional[str]:
    """A saved unit carries no figure measured once — see `metric_catalogue.plain_unit`."""
    from aughor.semantic.metric_catalogue import plain_unit
    return plain_unit(unit) or None


def _dataset(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    return v or None


@router.post("/metrics", status_code=201, dependencies=[gate(Capability.METRICS_DEFINE)])
def create_metric(req: MetricRequest):
    _require_own_organisation(req.connection)
    _require_statement(req.sql, None)
    _require_binds(req.sql, req.connection, req.name, req.tables, req.filters, None)
    # G1: declared LOW — auto-allowed and AUDITED, so defining a governed metric leaves a
    # trail. The approval question belongs to the approve transition, not to authoring.
    from aughor import govern
    govern.guard("metric.define", req.name)
    # EXACT scope — this connection's own definition of this name IN ITS DATASET. A resolving read
    # would report the global `revenue` as this connection's duplicate; a name-only read would
    # report staging's `revenue` as marts' (the user, 2026-10-07: each dataset may define its own).
    home = home_schema(req.model_dump())
    if definition_at(req.name, req.connection, home) is not None:
        where = "every dataset of " if home == ALL_DATASETS else f"dataset '{home}' of "
        raise HTTPException(status_code=409, detail=(
            f"'{req.name}' is already defined for {where}connection '{req.connection}' — open it "
            f"to change it, or choose another name."))
    data = {k: v for k, v in req.model_dump().items() if k not in _SERVER_OWNED}
    data["unit"] = _plain_unit(data.get("unit"))
    data.update(_stamp_time_edit(None, req))
    from aughor.semantic.metric_time import with_dates
    m = with_dates(req.connection, MetricDefinition(**data))
    save_metric(m)
    _restate_briefings(req.connection)
    _audit({"metric": m.name, "connection": m.connection, "schema_name": home_schema(m), "action": "define"})
    return m.model_dump()


def _addressed(name: str, connection: str, schema: Optional[str]):
    """The definition a request addresses: this connection's own, in the dataset named — never the
    house default standing in for it (a write must not inherit the global's governance state)."""
    if schema:
        return definition_at(name, connection, schema)
    existing = get_metric(name, connection_id=connection)
    if existing is not None and existing.connection != connection:
        return None
    return existing


@router.put("/metrics/{name}", dependencies=[gate(Capability.METRICS_DEFINE)])
def update_metric(name: str, req: MetricRequest, schema: Optional[str] = None):
    """Edit a definition — ANY field (the user, 2026-10-07): its name and its dataset too, which
    move it. ``schema`` is the dataset of the definition being edited; ``req.schema_name`` is the
    one it is saved in. Governance stays the transitions': a changed formula on an approved metric
    returns it to `proposed` for review."""
    _require_own_organisation(req.connection)
    from aughor import govern
    govern.guard("metric.define", name)   # G1: same declared action, the edit door
    existing = _addressed(name, req.connection, _dataset(schema))
    _require_statement(req.sql, existing)
    new_name = (req.name or name).strip()
    _require_binds(req.sql, req.connection, new_name, req.tables, req.filters, existing)
    from aughor.semantic.metric_catalogue import normalize_name
    if new_name != name and normalize_name(new_name) != new_name:
        raise HTTPException(status_code=422, detail=(
            f"A metric's name is lowercase words joined by underscores — {normalize_name(new_name)!r}, "
            f"for example. The label is where it reads as a person would write it."))
    was = home_schema(existing) if existing is not None else None
    target_ds = _dataset(req.schema_name) or was
    moved = existing is not None and (new_name != name or not same_dataset(target_ds, was))
    if moved and definition_at(new_name, req.connection, target_ds or ALL_DATASETS) is not None:
        where = "every dataset of" if (target_ds or ALL_DATASETS) == ALL_DATASETS else f"dataset '{target_ds}' of"
        raise HTTPException(status_code=409, detail=(
            f"'{new_name}' is already defined in {where} connection '{req.connection}' — open that "
            f"one, or choose another name."))
    data = {k: v for k, v in req.model_dump().items() if k not in _SERVER_OWNED}
    data.update({"name": new_name, "schema_name": target_ds, "unit": _plain_unit(data.get("unit"))})
    data.update(_stamp_time_edit(existing, req))
    audit = None
    if existing is not None:
        # Governance state is owned by the transition workflow (B-8), not by edits —
        # carry status/version/stamps forward. But changing the FORMULA of an approved
        # metric un-approves it: it returns to 'proposed' for re-review, and that's audited.
        for k in ("status", "version", "proposed_by", "proposed_at", "approved_by", "approved_at",
                  "entity", "entity_confirmed_by"):        # Arc OC-3: an edit keeps the confirmed entity
            data[k] = getattr(existing, k)
        if existing.status == "approved" and (req.sql or "").strip() != (existing.sql or "").strip():
            data["status"] = "proposed"
            data["approved_by"] = data["approved_at"] = None
            audit = {"metric": new_name, "connection": req.connection, "schema_name": target_ds,
                     "action": "edit_reproposed", "from": "approved", "to": "proposed",
                     "version": existing.version}
    from aughor.semantic.metric_time import with_dates
    m = with_dates(req.connection, MetricDefinition(**data))
    if moved:
        move_metric(name, req.connection, was, m)
        _audit({"metric": new_name, "connection": req.connection, "schema_name": home_schema(m),
                "action": "moved", "from_name": name, "from_schema": was})
    else:
        save_metric(m)
    _restate_briefings(req.connection)
    if audit:
        _audit(audit)
    return m.model_dump()


class _MetricEntity(BaseModel):
    """Arc OC-3 — the entity a metric measures, an ontology id; empty clears it."""
    entity: Optional[str] = None


@router.put("/metrics/{name}/entity", dependencies=[gate(Capability.METRICS_DEFINE)])
def confirm_metric_entity(name: str, req: _MetricEntity, connection_id: str, schema: Optional[str] = None):
    """Arc OC-3 — confirm which entity a metric measures (`GET /ontology/keys` proposes one from its grain), as the
    person signed in. The entity must be one the metric's dataset serves; empty clears the key. Its statement, status
    and version are untouched: keying says what the metric is about, it does not change what it computes."""
    _require_own_organisation(connection_id)
    from aughor import govern
    govern.guard("metric.define", name)
    existing = _addressed(name, connection_id, _dataset(schema))
    if existing is None or existing.connection != connection_id:
        raise HTTPException(status_code=404, detail=f"'{name}' has no definition of its own on connection "
                                                    f"'{connection_id}' to key")
    entity = (req.entity or "").strip()
    if entity:
        from aughor.routers.ontology import served_ontology_graph
        dataset = home_schema(existing)
        graph = served_ontology_graph(connection_id, None if dataset in ("", "*") else dataset)
        known = sorted(graph.entities) if graph is not None else []
        if entity not in known:
            raise HTTPException(status_code=400, detail=(
                f"no entity '{entity}' on this connection's ontology"
                + (f" — entities: {', '.join(known)}" if known else " — none is built")))
    keyed = existing.model_copy(update={"entity": entity or None, "entity_confirmed_by": caller() if entity else None})
    save_metric(keyed)
    _audit({"metric": name, "connection": connection_id, "schema_name": home_schema(keyed),
            "action": "entity_confirmed" if entity else "entity_cleared", "entity": entity})
    return keyed.model_dump()


@router.post("/metrics/{name}/promote", dependencies=[gate(Capability.METRICS_DEFINE)])
def promote_metric(name: str, connection_id: str, schema: str):
    """Promote one dataset's definition to its whole CONNECTION (the user, 2026-10-07: datasets
    *"should be distinctly defined for each of the schema with a possibility of promoting it to the
    connection level"*). Every dataset then reads it, except one that keeps a definition of its
    own under the same name. Its governance state moves with it; the move is audited."""
    existing = definition_at(name, connection_id, schema)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No definition '{name}' in dataset '{schema}'.")
    was = home_schema(existing)
    if was == ALL_DATASETS:
        raise HTTPException(status_code=409, detail=f"'{name}' already belongs to every dataset of this connection.")
    if definition_at(name, connection_id, ALL_DATASETS) is not None:
        raise HTTPException(status_code=409, detail=(
            f"This connection already has a '{name}' for every dataset — open it to compare, then "
            f"remove or rename one of the two."))
    from aughor import govern
    govern.guard("metric.define", name)
    promoted = existing.model_copy(update={"schema_name": ALL_DATASETS})
    move_metric(name, connection_id, was, promoted)
    _restate_briefings(connection_id)
    _audit({"metric": name, "connection": connection_id, "schema_name": ALL_DATASETS,
            "action": "promoted", "from_schema": was})
    return promoted.model_dump()


class TransitionRequest(BaseModel):
    action: str   # propose | approve | reject | deprecate
    #: IGNORED — the transition is the signed-in person's (`caller`). It was required, and the
    #: Metrics tab asked whoever clicked Approve to type a name, which is what it then recorded.
    actor: str = ""
    #: WHICH connection's definition is being governed. Resolving by name alone meant a
    #: transition aimed at one connection's `revenue` landed on another's — live, an
    #: approve intended for theLook's draft was refused because the SAMPLES `revenue`
    #: was already approved, and the draft stayed unapproved with no sign why.
    #: Approval is per formula, and two connections' formulas are different things.
    connection: str = GLOBAL_CONNECTION
    #: WHICH dataset's definition, when two datasets each define the name.
    schema_name: Optional[str] = None
    #: Approve a definition that measures exactly what an approved one does. Refused without it
    #: (409 `same_as_approved`); with it, the audit names the metric it measures the same as.
    approve_anyway: bool = False


@router.post("/metrics/{name}/transition", dependencies=[gate(Capability.METRICS_DEFINE)])
def transition_metric(name: str, req: TransitionRequest):
    """B-8 — drive a metric through its governance lifecycle (propose → approve →
    deprecate …). Validates the transition, persists the new state, and journals an
    audit event so the trail is queryable."""
    from datetime import datetime, timezone
    from aughor.semantic.governance import apply_transition
    from aughor.kernel.ledger import Ledger

    m = _addressed(name, req.connection, _dataset(req.schema_name))
    if not m:
        raise HTTPException(
            status_code=404,
            detail=f"Metric '{name}' not found for connection '{req.connection}'.")
    # G1: the two DECLARED transitions carry their declared risk — `metric.approve` is HIGH
    # (it is what makes a formula authoritative for every later answer) and `metric.propose`
    # is LOW. Verbs govern.actions does not declare are left to the existing transition
    # validation rather than silently reclassified HIGH by `classify`'s fail-safe: widening
    # the gate is a governance decision, and this change is about closing declared gaps.
    if (_action := GUARDED_TRANSITIONS.get(str(req.action or "").strip().lower())):
        from aughor import govern
        govern.guard(_action, name)
    now = datetime.now(timezone.utc).isoformat()
    # One measure, one approved definition (the user, 2026-10-08: "Why should we have duplicates?").
    # The name check at definition never saw two names for one figure; the approval is where a
    # definition becomes authoritative, so it is checked here, by its figures.
    twin = _twin_check(m, req.connection) if str(req.action or "").strip().lower() == "approve" else None
    if twin and twin.get("twin") and not req.approve_anyway:
        from aughor.semantic import metric_twins
        raise HTTPException(status_code=409, detail={
            "reason": "same_as_approved", "twin": twin["twin"], "message": metric_twins.said(m, twin)})
    try:
        updated, audit = apply_transition(m.model_dump(), req.action, caller(), now)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    save_metric(MetricDefinition(**updated))
    _restate_briefings(req.connection)
    audit = {**audit, "connection": req.connection, "schema_name": home_schema(m)}
    if twin and twin.get("twin"):
        audit["approved_though_same_as"] = twin["twin"]["name"]
    elif twin and not twin.get("checked"):
        audit["same_as_check"] = f"not read: {twin.get('why') or 'unknown'}"
    Ledger.default().emit("metric.governance", audit)
    if updated.get("status") == "approved":
        _reopen_questions(req.connection, home_schema(m), f"{m.label or name} was approved")
    return {"metric": updated, "audit": audit}


def _twin_check(m: MetricDefinition, connection: str) -> dict:
    """``metric_twins.twin_of`` against this connection's approved definitions in the metric's dataset
    (and the ones every dataset reads), on the connection's own warehouse. A check that cannot run
    says so; it never stops an approval by itself."""
    from datetime import datetime, timezone

    from aughor.knowledge import period_brief
    from aughor.semantic import metric_twins

    home = home_schema(m)
    approved = [x for x in list_metrics(connection_id=connection, schema_name=None if home == ALL_DATASETS else home)
                if x.status == "approved" and x.connection == connection]
    if not metric_twins.candidates(m, approved):
        return dict(metric_twins.NO_TWIN)               # nothing reads its tables: nothing to measure
    try:
        with period_brief.connection_runner(connection) as (run_sql, dialect):
            return metric_twins.twin_of(m, approved, run_sql=run_sql, dialect=dialect,
                                        today=datetime.now(timezone.utc).date())
    except Exception as exc:  # noqa: BLE001 — not known is said in the audit, never taken for "no twin"
        from aughor.kernel.errors import tolerate
        tolerate(exc, "whether a metric measures the same as an approved one could not be read",
                 counter="metrics.twin_check")
        return {"twin": None, "months": 0, "checked": False,
                "why": f"the connection could not be opened ({type(exc).__name__})"}


def _reopen_questions(conn_id: Optional[str], schema: Optional[str], why: str) -> None:
    """A newly approved metric is a named event that reopens its dataset's questions (exploration
    principles §3): the next check asks them, the model's curiosity included, within the budget. A
    metric promoted to the connection reopens every dataset of it."""
    if not conn_id:
        return
    try:
        from aughor.explorer import program
        from aughor.explorer import store as expl_store
        from aughor.semantic.metrics import ALL_DATASETS
        keys = expl_store.schema_run_keys(conn_id)
        if not keys:
            targets = [conn_id]
        elif schema and schema != ALL_DATASETS:
            targets = [k for k in keys if k == f"{conn_id}__{schema}"] or [conn_id]
        else:
            targets = keys
        for k in targets:
            program.reopen(k, why)
    except Exception as exc:  # noqa: BLE001 — the approval stands; the reopen is the explorer's to miss
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an approved metric could not reopen its dataset's questions", counter="metrics.reopen")


def _trail(name: str, connection: Optional[str] = None, schema: Optional[str] = None) -> list[dict]:
    """A definition's governance events, newest first. An event recorded before events named their
    connection and dataset is kept — it cannot be told apart, and dropping it would hide history."""
    from aughor.kernel.ledger import Ledger
    events = Ledger.default().events(kind="metric.governance", limit=1000)
    out = []
    for e in events:
        p = e.get("payload") or {}
        if p.get("metric") != name and p.get("from_name") != name:
            continue
        if connection and p.get("connection") and p.get("connection") != connection:
            continue
        if schema and p.get("schema_name") and not same_dataset(p.get("schema_name"), schema):
            continue
        out.append(p)
    return out


@router.get("/metrics/{name}/audit")
def metric_audit(name: str, limit: int = 50, connection_id: Optional[str] = None,
                 schema: Optional[str] = None):
    """The governance audit trail for a metric — every transition, newest first."""
    return {"metric": name, "audit": _trail(name, connection_id, schema)[:limit]}


@router.get("/metrics/{name}/definition-report")
async def metric_definition_report(name: str, conn_id: str, schema: Optional[str] = None):
    """A3 — the instrument beside the approval ask.

    `POST /metrics/{name}/transition` validates the lifecycle, persists and journals, and tells
    the approver nothing about what they are approving. This answers the four questions the bare
    ask leaves open: what this is changing from, whether it executes and what it reads, what the
    definition leaves undeclared, and how reproducible that read is.

    **Advisory.** It never holds or refuses anything — the definition is the user's call, and
    `semantic/definition_report.py` cannot even import the module that holds a send.

    Spelled `conn_id`, like its three siblings (`/value`, `/validate`, `/freshness`) and for the
    same reason `/metrics/catalogue/{conn_id}` is: `require_capability` declares `connection_id`
    as a QUERY parameter and FastAPI refuses one name declared both ways on a route. This door is
    ungated because it is a read, as every other read on this router is.

    🔴 It resolves the metric SCOPED, then checks the connection came back matching — the same
    two steps `transition_metric` takes. `get_metric` falls back to the GLOBAL definition when a
    connection has none of its own, which is why `/value`, `/validate` and `/freshness` (all of
    which call `get_metric(name)` with no connection) can answer for a formula belonging to
    somebody else entirely. Reporting on the wrong definition is worse here than anywhere: this
    screen exists to be trusted at the moment a person commits to one.
    """
    from aughor.db.connection import open_connection_for
    from aughor.kernel.errors import tolerate
    from aughor.semantic.definition_report import build_report

    metric = _addressed(name, conn_id, _dataset(schema))
    if not metric:
        raise HTTPException(
            status_code=404,
            detail=f"Metric '{name}' not found for connection '{conn_id}'.")

    trail = _trail(name, conn_id, schema)

    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    def _work():
        try:
            # `table_cols` is deliberately NOT supplied: the only accessor here
            # (`routers/_shared.get_schema_cached`) BUILDS on a cache miss, and a read that
            # builds is the defect that once hung `GET /ontology`. The report records the
            # grain check as skipped, with the reason, rather than silently omitting it.
            return build_report(metric, db, connection_id=conn_id, audit_events=trail)
        finally:
            try:
                db.close()
            except Exception as exc:
                tolerate(exc, "definition-report connection close is best-effort",
                         counter="metrics.definition_report.close")

    loop = asyncio.get_running_loop()
    report = await loop.run_in_executor(None, _work)
    return _report_payload(report)


def _report_payload(report) -> dict:
    """Serialise the report for the wire, keeping every typed verdict's WORD.

    The outcome and mode strings travel verbatim — flattening `unavailable` to a null value or
    `unpinnable` to an absent field is exactly the collapse the dataclasses refuse to make.
    """
    def claim(c) -> dict:
        return {
            "outcome": c.outcome,
            "summary": c.summary,
            "findings": [{"code": f.code, "severity": f.severity,
                          "what": f.what, "evidence": f.evidence} for f in c.findings],
            "detail": dict(c.detail),
        }

    return {
        "metric": report.metric,
        "connection_id": report.connection_id,
        "status": report.status,
        "version": report.version,
        "advisory": report.advisory,
        "taken_at": report.taken_at,
        "predecessor": claim(report.predecessor),
        "execution": claim(report.execution),
        "declaration": claim(report.declaration),
        "segments": claim(report.segments),
        "population": {
            "mode": report.population.mode,
            "reason": report.population.reason,
            "token": report.population.token,
            "tables": list(report.population.tables),
            "taken_at": report.population.taken_at,
            "reproducible": report.population.reproducible,
        },
        "defects": [f.code for f in report.defects],
    }


@router.delete("/metrics/{name}", dependencies=[gate(Capability.METRICS_DEFINE)])
def remove_metric(name: str, sql: Optional[str] = None,
                  connection: Optional[str] = None, schema: Optional[str] = None):
    """Remove a metric — the one irreversible verb on this router, and until now the only
    unguarded one.

    Defining and editing were capability-gated and audited "so defining a governed metric
    leaves a trail"; deleting was neither, and omitting `sql` removes EVERY grain sharing
    the name. Two such calls emptied the catalogue on a live install — including a formula
    carrying `approved_by: Finance` — and nothing anywhere recorded it. The trail endpoint
    below would have shown a metric's whole history with its deletion missing.

    `metric.delete` is declared HIGH, so a definition that was EVER approved asks for approval
    like every other destructive verb. One nobody ever approved — a draft, a proposal — is
    removed on the person's click (the user, 2026-10-07: *"the right to remove the proposed
    Metric"*): nothing was ever measured or sent on it. Either way the removal lands in the same
    `metric.governance` trail as the transitions that preceded it, stamped with who removed it.

    `connection` (and `schema`, its dataset) narrows it to ONE definition, and records the name as
    removed there, so the explorer or a package that proposed it does not propose it again.
    Omitted, the old behaviour stands and every connection's metric of that name goes — which is
    what you want when retiring a name outright, and emphatically not what you want when one
    warehouse redefines its own `revenue`.
    """
    from aughor import govern

    # Read BEFORE deleting: the trail should say what was removed, and afterwards there is
    # nothing left to describe. SCOPED to the same connection `delete_metric` is about to use —
    # the deletion was always scoped, but the row read to DESCRIBE it was not, so the audit
    # entry could credit another connection's owner for a definition that never moved. A trail
    # that misdescribes what it recorded is worse than no trail, because it is believed.
    # With `connection` omitted the resolver behaves exactly as before, which is right: every
    # definition of that name is going, and the entry describes one of them.
    doomed = (definition_at(name, connection, schema) if connection and schema
              else get_metric(name, connection_id=connection))
    if doomed is None or connection is None or int(doomed.version or 0) > 0 or doomed.status in ("approved", "deprecated"):
        govern.guard("metric.delete", name)
    if not delete_metric(name, sql=sql, connection_id=connection, schema_name=schema):
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    dataset = home_schema(doomed) if doomed is not None else (schema or ALL_DATASETS)
    if connection:
        from aughor.semantic.metrics import dismiss_proposal
        dismiss_proposal(connection, dataset, name, by=caller(),
                         label=(doomed.label if doomed else name), source="defined")
    _audit({
        "metric": name,
        "connection": connection,
        "schema_name": dataset if connection else None,
        "action": "delete",
        # Which grain, when a name carries several. `null` means every one of them went.
        "sql": sql,
        "approved_by": (doomed.approved_by if doomed else None),
        "owner": (doomed.owner if doomed else None),
    })
    return {"ok": True, "name": name}


@router.post("/metrics/{name}/validate")
async def run_metric_validation(name: str, conn_id: str):
    """Run all quality_tests for a metric against the given connection.

    Resolved SCOPED — see `get_metric_value` for the measurement behind this. Running one
    connection's quality tests against another's warehouse reports on a contract nobody wrote.
    """
    from aughor.db.connection import open_connection_for

    metric = get_metric(name, connection_id=conn_id)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    loop = asyncio.get_running_loop()
    def _work():
        try:
            return validate_metric(metric, db)
        finally:
            try:
                db.close()
            except Exception:
                pass

    try:
        result = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result.model_dump()


@router.get("/metrics/{name}/freshness")
async def get_metric_freshness(name: str, conn_id: str):
    """Check the freshness of a metric's underlying data against its SLA.

    Resolved SCOPED — see `get_metric_value`. An SLA is a promise a particular team made about
    a particular warehouse; answering with another connection's is not a near-miss, it is a
    different promise.
    """
    from aughor.db.connection import open_connection_for

    metric = get_metric(name, connection_id=conn_id)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    loop = asyncio.get_running_loop()
    def _work():
        try:
            return check_freshness(metric, db)
        finally:
            try:
                db.close()
            except Exception:
                pass

    try:
        result = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result.model_dump()


@router.get("/metrics/{name}/value")
async def get_metric_value(name: str, conn_id: str):
    """Compute a governed metric's CURRENT value by running its registered SQL
    against a connection — the exact governed number, not an LLM re-derivation.
    This is what the MCP `get_metric` tool returns so an external agent binds to
    the same definition the rest of Aughor enforces (vs improvising a formula).

    🔴 Resolved SCOPED. Until 2026-09-20 this read `get_metric(name)` with no connection, and
    the resolver's no-connection branch returns the FIRST row matching the name, whatever
    connection owns it. Measured live: `GET /metrics/revenue/value?conn_id=8233e4fd` answered
    `SUM(total_amount) FROM orders` — the `samples` definition, on a connection id that is no
    longer in `GET /connections` at all — with the `samples` caveat prose attached, at HTTP 200,
    and no field naming whose definition had run. It failed on theLook only because
    `total_amount` is not a column there; where the names overlap it returns a confident number
    for a formula the caller never asked about. The promise in the docstring above — "the exact
    governed number, not an LLM re-derivation" — was the thing being broken.

    Passing the connection is the whole fix. A strict `metric.connection == conn_id` check would
    also close it and would break `"*"`, which is how a house-wide definition reaches every
    connection; the resolver already shadows a global row with a scoped one."""
    from aughor.db.connection import open_connection_for

    metric = get_metric(name, connection_id=conn_id)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    # The query and the run both live in `semantic/metrics.py` — see the note there.
    # This route and the health scorecard each had their own copy, each called
    # `db.execute(query)` against a two-argument signature, and each swallowed the
    # resulting TypeError into a field that reads as "the data could not answer":
    # value=null with a note here, status="unknown" there. Neither had ever computed a
    # number, and their two query builders did not even agree on which number.
    def _work():
        try:
            return compute_value(metric, db)
        finally:
            try:
                db.close()
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "metric-value connection close is best-effort",
                         counter="metrics.value.close")

    loop = asyncio.get_running_loop()
    computed = await loop.run_in_executor(None, _work)
    out = {
        "name": metric.name,
        "label": metric.label,
        "value": computed.value,
        "unit": metric.unit,
        "sql": computed.sql,
        "filters": metric.filters,
        "caveats": metric.caveats,
    }
    if computed.error:
        # A bare-aggregate metric on an ambiguous (e.g. multi-schema) connection can't
        # be auto-computed — report that honestly rather than 500-ing.
        out["note"] = f"Could not compute against '{conn_id}': {computed.error}"
    return out


@router.get("/connections/{conn_id}/health-scorecard")
async def get_health_scorecard(conn_id: str):
    """Execute each targeted metric's SQL and return health status."""
    from aughor.db.connection import open_connection_for

    targeted = [m for m in list_metrics() if m.target_value is not None]
    if not targeted:
        return []

    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    _targeted = targeted

    def _work():
        results = []
        for metric in _targeted:
            try:
                # The SAME governed query the value route runs — filters included. The
                # copy that stood here ran the bare aggregate with no FROM and no
                # filters, so on the day it started working it would have scored a
                # metric against a number its own definition excludes.
                current = compute_value(metric, db).value

                if current is None:
                    status = "unknown"
                    variance = None
                else:
                    variance = (current - metric.target_value) / metric.target_value if metric.target_value else None
                    if metric.critical_threshold is not None and abs(current - metric.target_value) >= metric.critical_threshold:
                        status = "red"
                    elif metric.warning_threshold is not None and abs(current - metric.target_value) >= metric.warning_threshold:
                        status = "yellow"
                    else:
                        status = "green"

                results.append({
                    "name": metric.name, "label": metric.label, "current": current,
                    "target": metric.target_value, "variance": variance, "status": status,
                    "unit": metric.unit, "target_period": metric.target_period,
                    "benchmark_source": metric.benchmark_source,
                })
            except Exception:
                results.append({
                    "name": metric.name, "label": metric.label, "current": None,
                    "target": metric.target_value, "variance": None, "status": "unknown",
                    "unit": metric.unit, "target_period": metric.target_period,
                    "benchmark_source": metric.benchmark_source,
                })
        try:
            db.close()
        except Exception:
            pass
        return results

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Playbook ──────────────────────────────────────────────────────────────────

class PlaybookEntryRequest(BaseModel):
    trigger_metric: str
    trigger_condition: str
    trigger_operator: str = "any"
    trigger_value: float = 0.0
    recommendation: str
    expected_impact: str = ""
    typical_timeline: str = ""
    owner_role: str = ""
    tags: list[str] = []
    status: str = "draft"
    source_kb_id: Optional[str] = None


@router.get("/playbook")
def get_playbook():
    from aughor.playbook.store import list_entries
    return [e.model_dump() for e in list_entries()]


@router.get("/playbook/{entry_id}")
def get_playbook_entry(entry_id: str):
    from aughor.playbook.store import get_entry
    e = get_entry(entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Entry not found")
    return e.model_dump()


@router.get("/playbook/{entry_id}/versions")
def get_playbook_versions(entry_id: str):
    """The immutable Governed-Dive history of a play — every frozen version (with its receipt),
    oldest → newest. A finding that cited an older version can be resolved against the exact
    content it relied on."""
    from aughor.playbook.store import get_entry, list_versions
    if not get_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return list_versions(entry_id)


@router.post("/playbook", status_code=201, dependencies=[gate(Capability.PLAYBOOK)])
def create_playbook_entry(req: PlaybookEntryRequest):
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.store import save_entry
    import uuid
    entry = PlaybookEntry(id=f"user_{uuid.uuid4().hex[:12]}", **req.model_dump())
    save_entry(entry)
    return entry.model_dump()


@router.put("/playbook/{entry_id}", dependencies=[gate(Capability.PLAYBOOK)])
def update_playbook_entry(entry_id: str, req: PlaybookEntryRequest):
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.store import get_entry, save_entry
    existing = get_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Entry not found")
    updated = PlaybookEntry(
        id=entry_id,
        evidence_sources=existing.evidence_sources,
        historical_success_rate=existing.historical_success_rate,
        # A data-quality play's cause and fix are not in the request: the playbook screen PUTs the
        # play back to change its status, and rebuilding from the request alone would erase them.
        cause=existing.cause,
        fix=existing.fix,
        **req.model_dump(),
    )
    save_entry(updated)
    return updated.model_dump()


@router.delete("/playbook/{entry_id}")
def delete_playbook_entry(entry_id: str):
    from aughor.playbook.store import delete_entry
    if not delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True, "id": entry_id}


@router.post("/playbook/seed")
def reseed_playbook():
    """Force re-seed of playbook from KB."""
    from aughor.playbook.builder import seed_from_kb
    n = seed_from_kb(force=True)
    return {"seeded": n}


@router.get("/metrics/enforcement-rate")
def metric_enforcement_rate(connection_id: str = "", limit: int = 500):
    """B-7 — the measured enforcement rate: of the answers that TARGETED a
    governed metric, what fraction USED the governed formula (vs improvised).
    Aggregated from the metric.enforcement journal events. The honest
    denominator is metric-bearing answers only — questions with no governed
    metric don't count for or against."""
    from aughor.kernel.ledger import Ledger
    evs = Ledger.default().events(
        kind="metric.enforcement",
        conn_id=connection_id or None, limit=int(limit),
    )
    total = len(evs)
    enforced = sum(1 for e in evs if (e.get("payload") or {}).get("enforced"))
    drift_metrics: dict[str, int] = {}
    for e in evs:
        for m in (e.get("payload") or {}).get("drift", []) or []:
            drift_metrics[m] = drift_metrics.get(m, 0) + 1
    return {
        "connection_id": connection_id or "all",
        "metric_bearing_answers": total,
        "enforced": enforced,
        "enforcement_rate": round(enforced / total, 3) if total else None,
        "drift_by_metric": drift_metrics,
    }
