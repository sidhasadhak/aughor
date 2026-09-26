"""Metrics catalog, health scorecard, and playbook endpoints."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aughor.licensing import Capability, gate

from aughor.semantic.metrics import (
    GLOBAL_CONNECTION,
    MetricDefinition,
    compute_value,
    delete_metric,
    get_metric,
    list_metrics,
    save_metric,
    validate_metric,
    check_freshness,
)
from aughor.security.authz import connection_owner_guard

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
    label: str
    sql: str
    tables: list[str] = []
    dimensions: list[str] = []
    filters: list[str] = []
    unit: Optional[str] = None
    caveats: Optional[str] = None
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
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    # Arc BR-2 — a person's correction of the time fields; sending them stamps the editor
    # as the one who confirmed them (`time_confirmed_by`).
    time_column: Optional[str] = None
    time_kind: Optional[str] = None
    outcome_column: Optional[str] = None
    until_column: Optional[str] = None
    settles_after_days: Optional[int] = None
    time_confirmed_by: Optional[str] = None


@router.get("/metrics")
def get_metrics(connection_id: Optional[str] = None):
    """The registry, optionally narrowed to one connection.

    `connection_id` applies `list_metrics`' own connection-shadows-global rule. It stays
    OPTIONAL so every existing caller is byte-identical: making it required would turn a
    re-key into a caller migration, and each unconverted site becomes a silent global read
    that looks correct (the same reasoning `list_metrics` records for its own default)."""
    return [m.model_dump() for m in list_metrics(connection_id=connection_id)]


# The path parameter is `conn_id`, not `connection_id`: `require_capability` (the `gate`
# below) declares `connection_id` as a QUERY parameter, and FastAPI refuses a name declared
# both ways on one route. `connection_owner_guard` accepts either spelling, so DATA-06
# ownership is enforced on these doors exactly as on the rest of the router.
@router.get("/metrics/catalogue/{conn_id}")
def get_metric_catalogue(conn_id: str, schema: Optional[str] = None):
    """Every metric that APPLIES to this connection — defined, industry and explorer.

    Not the same list as `/metrics`: that one is the registry, and most of what applies to
    a connection is not in the registry yet. A pack's recipe is role-bound until this
    connection binds those roles, and the explorer's judgement lives on the business
    profile. Both are computed here and materialised only when someone edits one."""
    from aughor.semantic.metric_catalogue import catalogue_for

    rows = catalogue_for(conn_id, schema)
    return {
        "connection_id": conn_id,
        "metrics": [r.as_dict() for r in rows],
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
    """Copy-on-write: turn a computed row into an editable, connection-scoped definition.

    Lands as `draft` — see `metric_catalogue.materialise`. A row that needs a binding is
    refused with the roles it is missing, rather than written as SQL that cannot run."""
    from aughor.semantic.metric_catalogue import MaterialiseError, materialise

    try:
        return materialise(conn_id, name, schema, actor=actor).model_dump()
    except MaterialiseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    from aughor.tools.profile_cache import latest_profile_entry
    try:
        profile = latest_profile_entry(req.connection)
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
    (`semantic.metric_author`); the answer is checked, never rewritten — a grouped, limited
    or multi-column query is refused with the reason and the model's text."""
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
        raw = (out.get("raw") or "").strip()
        detail = f"No statement written: {out['refused']}."
        if raw:
            detail += f" The model wrote: {raw[:400]}"
        raise HTTPException(status_code=422, detail=detail)
    return {"sql": out["sql"], "note": out["note"], "model": out["model"], "trace_id": trace_id}


@router.post("/metrics", status_code=201, dependencies=[gate(Capability.METRICS_DEFINE)])
def create_metric(req: MetricRequest):
    _require_statement(req.sql, None)
    # G1: declared LOW — auto-allowed and AUDITED, so defining a governed metric leaves a
    # trail. The approval question belongs to the approve transition, not to authoring.
    from aughor import govern
    govern.guard("metric.define", req.name)
    # Scoped: `revenue` on this connection is a different metric from `revenue` on
    # another, and from the global default. Checking the name alone refused the second
    # connection's own definition — the very thing the store's (connection, name) key
    # exists to allow.
    # EXACT scope, not a resolving read: `get_metric(name, connection_id=…)` falls back
    # to the global definition when the connection has none of its own — correct for
    # answering "what does this connection use", and wrong here, where it would report
    # the global `revenue` as this connection's duplicate and refuse the scoped one.
    _existing = get_metric(req.name, connection_id=req.connection)
    if _existing is not None and _existing.connection == req.connection:
        raise HTTPException(
            status_code=409,
            detail=(f"Metric '{req.name}' already exists for connection "
                    f"'{req.connection}'. Use PUT to update."))
    m = MetricDefinition(**req.model_dump())
    save_metric(m)
    return m.model_dump()


@router.put("/metrics/{name}", dependencies=[gate(Capability.METRICS_DEFINE)])
def update_metric(name: str, req: MetricRequest):
    from aughor import govern
    govern.guard("metric.define", name)   # G1: same declared action, the edit door
    # Resolve the metric being edited WITHIN its connection, and keep it there. Before
    # this, an edit rebuilt the definition from a request that could not express a
    # connection, so a scoped metric was rewritten as global and leaked into every
    # other connection's catalogue carrying SQL for tables they do not have.
    existing = get_metric(name, connection_id=req.connection)
    if existing is not None and existing.connection != req.connection:
        # A RESOLVING read, so this is the global definition standing in for a connection
        # that has none of its own. It is not the thing being edited: writing a scoped
        # override must not inherit the global's governance state, or a brand-new
        # per-connection formula would arrive already stamped `approved` by whoever
        # approved the house default. Treat it as a new definition at this scope.
        existing = None
    _require_statement(req.sql, existing)
    data = {**req.model_dump(), "name": name}
    # Arc BR-2: the time fields are kept unless this edit SENT them — an editor that does not
    # know them must not erase what the platform set — and a sent correction is a person's.
    from aughor.semantic.metric_time import TIME_FIELDS, merge_time_edit
    try:
        data.update(merge_time_edit(existing, req.model_dump(include=set(TIME_FIELDS) & req.model_fields_set)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit = None
    if existing is not None:
        # Governance state is owned by the transition workflow (B-8), not by edits —
        # carry status/version/stamps forward. But changing the FORMULA of an approved
        # metric un-approves it: it returns to 'proposed' for re-review, and that's audited.
        data["status"] = existing.status
        data["version"] = existing.version
        data["proposed_by"], data["proposed_at"] = existing.proposed_by, existing.proposed_at
        data["approved_by"], data["approved_at"] = existing.approved_by, existing.approved_at
        if existing.status == "approved" and (req.sql or "").strip() != (existing.sql or "").strip():
            from datetime import datetime, timezone
            data["status"] = "proposed"
            data["approved_by"] = data["approved_at"] = None
            audit = {"metric": name, "action": "edit_reproposed",
                     "actor": existing.owner or "editor", "from": "approved", "to": "proposed",
                     "version": existing.version, "at": datetime.now(timezone.utc).isoformat()}
    m = MetricDefinition(**data)
    save_metric(m)
    if audit:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("metric.governance", audit)
    return m.model_dump()


class TransitionRequest(BaseModel):
    action: str   # propose | approve | reject | deprecate
    actor: str    # who is performing it (person/team)
    #: WHICH connection's definition is being governed. Resolving by name alone meant a
    #: transition aimed at one connection's `revenue` landed on another's — live, an
    #: approve intended for theLook's draft was refused because the SAMPLES `revenue`
    #: was already approved, and the draft stayed unapproved with no sign why.
    #: Approval is per formula, and two connections' formulas are different things.
    connection: str = GLOBAL_CONNECTION


@router.post("/metrics/{name}/transition", dependencies=[gate(Capability.METRICS_DEFINE)])
def transition_metric(name: str, req: TransitionRequest):
    """B-8 — drive a metric through its governance lifecycle (propose → approve →
    deprecate …). Validates the transition, persists the new state, and journals an
    audit event so the trail is queryable."""
    from datetime import datetime, timezone
    from aughor.semantic.governance import apply_transition
    from aughor.kernel.ledger import Ledger

    m = get_metric(name, connection_id=req.connection)
    if m is not None and m.connection != req.connection:
        # A resolving read reached the house default, not this connection's definition.
        # Approving that would stamp the global formula on someone else's intent.
        m = None
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
    try:
        updated, audit = apply_transition(m.model_dump(), req.action, req.actor, now)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    save_metric(MetricDefinition(**updated))
    Ledger.default().emit("metric.governance", audit)
    return {"metric": updated, "audit": audit}


@router.get("/metrics/{name}/audit")
def metric_audit(name: str, limit: int = 50):
    """The governance audit trail for a metric — every transition, newest first."""
    from aughor.kernel.ledger import Ledger
    events = Ledger.default().events(kind="metric.governance", limit=1000)
    trail = [e["payload"] for e in events
             if e.get("payload") and e["payload"].get("metric") == name]
    return {"metric": name, "audit": trail[:limit]}


@router.get("/metrics/{name}/definition-report")
async def metric_definition_report(name: str, conn_id: str):
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
    from aughor.kernel.ledger import Ledger
    from aughor.semantic.definition_report import build_report

    metric = get_metric(name, connection_id=conn_id)
    if metric is not None and (metric.connection or GLOBAL_CONNECTION) != conn_id:
        # A resolving read reached the house default, not this connection's definition.
        metric = None
    if not metric:
        raise HTTPException(
            status_code=404,
            detail=f"Metric '{name}' not found for connection '{conn_id}'.")

    events = Ledger.default().events(kind="metric.governance", limit=1000)
    trail = [e["payload"] for e in events
             if e.get("payload") and e["payload"].get("metric") == name]

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
                  connection: Optional[str] = None):
    """Remove a metric — the one irreversible verb on this router, and until now the only
    unguarded one.

    Defining and editing were capability-gated and audited "so defining a governed metric
    leaves a trail"; deleting was neither, and omitting `sql` removes EVERY grain sharing
    the name. Two such calls emptied the catalogue on a live install — including a formula
    carrying `approved_by: Finance` — and nothing anywhere recorded it. The trail endpoint
    below would have shown a metric's whole history with its deletion missing.

    `metric.delete` is declared HIGH, so this now asks for approval like every other
    destructive verb, and the deletion lands in the same `metric.governance` trail as the
    transitions that preceded it.

    `connection` narrows it to ONE connection's definition. Omitted, the old behaviour
    stands and every connection's metric of that name goes — which is what you want when
    retiring a name outright, and emphatically not what you want when one warehouse
    redefines its own `revenue`.
    """
    from datetime import datetime, timezone

    from aughor import govern
    from aughor.kernel.ledger import Ledger

    govern.guard("metric.delete", name)
    # Read BEFORE deleting: the trail should say what was removed, and afterwards there is
    # nothing left to describe. SCOPED to the same connection `delete_metric` is about to use —
    # the deletion was always scoped, but the row read to DESCRIBE it was not, so the audit
    # entry could credit another connection's owner for a definition that never moved. A trail
    # that misdescribes what it recorded is worse than no trail, because it is believed.
    # With `connection` omitted the resolver behaves exactly as before, which is right: every
    # definition of that name is going, and the entry describes one of them.
    doomed = get_metric(name, connection_id=connection)
    if not delete_metric(name, sql=sql, connection_id=connection):
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    Ledger.default().emit("metric.governance", {
        "metric": name,
        "action": "delete",
        "at": datetime.now(timezone.utc).isoformat(),
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
