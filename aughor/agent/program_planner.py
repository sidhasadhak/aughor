"""Plan-as-program executor (Rec 4): plan → validate → run a typed PROGRAM over ONE database.

An investigation is turned into a deterministic, inspectable, replayable typed program. The LLM emits the
plan ONCE — an ordered list of steps, each either a DATA op (a grounded SELECT) or a SEMOP (one semantic
operator over a prior step's text residue). A deterministic runner then executes it step-by-step: the guard
battery validates each SQL step and every intermediate result is a NAMED artifact, so raw rows are threaded
between steps rather than re-flooding the LLM context.

Plan-then-execute (PromptQL), deterministic-first: the LLM only produces the *plan*; deterministic guards
validate it and the runner executes it. One LLM call, everything after is code — so the result is inspectable
(the plan + per-step artifacts are returned) and repeatable. This is the exact shape the cross-source
federated planner (`federated_planner.py`) already ships, generalized from "an ordered list of per-source
sub-queries folded by joins" to "an ordered list of DATA/SEMOP steps folded by named artifacts".

Scope of this increment (v1, honest boundary): DATA ops run their SQL against the live connection through
the shipped guard battery (`execute_guarded`), so they cannot yet consume a prior artifact as an input table
— `reads` is meaningful only for SEMOP steps (each consumes exactly one prior artifact). The realizable
programs are one-or-more DATA ops each followed by SEMOP chains over its text residue. "A DATA step reads a
prior artifact as a registered temp view" (true SQL-over-semop-output dataflow) is the deferred follow-on.

The in-run `by_name` dict is the source of truth for reads DURING a run (deterministic, no I/O); each result
is ALSO mirrored to the ledger (`kernel/ledger.py`) as a named, versioned artifact with provenance edges,
which is the durable/inspectable mirror a caller queries AFTER the run — never on the hot path.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

from aughor.platform.contracts.execution import QueryResult

logger = logging.getLogger(__name__)

_SEMOP_MAX_ROWS = 200   # apply_step's own cap; a larger result is refused (surfaced, never silent)


# ── The Plan IR ───────────────────────────────────────────────────────────────

class ProgramStep(BaseModel):
    id: str = Field(description="Stable step name, unique within the program. Referenced by later steps' `reads`.")
    kind: Literal["data", "semop"] = Field(description="'data' = a grounded SELECT; 'semop' = a semantic op over a prior artifact.")
    writes: str = Field(description="The artifact name this step produces. Unique within the program.")
    reads: list[str] = Field(default_factory=list, description="Artifact name(s) this step consumes. EMPTY for a DATA step; exactly one for a SEMOP.")

    # DATA op (kind == "data"): a single grounded SELECT on THIS connection's schema.
    sql: str = Field(default="", description="For kind='data': one SELECT grounded ONLY in the connection schema.")

    # SEMOP (kind == "semop"): one operator over the text of a prior artifact's QueryResult.
    operator: Literal["filter", "extract", "top_k", "aggregate", ""] = Field(default="", description="For kind='semop': which semantic operator.")
    column: str = Field(default="", description="For kind='semop': the text column of the read artifact to operate on.")
    predicate: str = Field(default="", description="filter: the natural-language keep-predicate.")
    fields: list[tuple[str, str]] = Field(default_factory=list, description="extract: [(name, description), ...].")
    criterion: str = Field(default="", description="top_k: what to rank by.")
    k: int = Field(default=10, description="top_k: how many to keep.")
    instruction: str = Field(default="", description="aggregate: how to synthesize one answer.")
    out_column: str = Field(default="answer", description="aggregate: the output column name.")


class Program(BaseModel):
    steps: list[ProgramStep] = Field(description="Ordered steps. steps[0] is the driver DATA op (reads nothing).")
    rationale: str = Field(default="", description="One sentence: how the artifacts chain.")


@dataclass
class ProgramResult:
    result: QueryResult                 # the final step's QueryResult (mirrors FederatedAnswer.result)
    program: Optional[Program]
    artifacts: dict[str, str]           # {artifact name -> ledger artifact_id} — inspectable
    warnings: list[str]                 # per-step guard/surfaced notes, prefixed with step id
    issues: list[str]                   # validation/exec issues (mirrors FederatedAnswer.issues)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _columns_of(conn, sql: str) -> Optional[list[str]]:
    """The output columns of ``sql`` (as a derived table), or None if it can't be introspected.

    The same LIMIT-0 introspection the federated planner uses to prove a sub-query grounds/parses."""
    try:
        res = conn.execute("__prog_cols__", f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS _t LIMIT 0")
        return list(res.columns) if not res.error else None
    except Exception:
        return None


def _uniquify(existing: list[str], new: list[str]) -> list[str]:
    """New column names disambiguated against existing ones and each other — matches the operators'
    own ``_uniquify`` so the projected schema predicts what ``semantic_extract`` actually appends."""
    seen = set(existing)
    out: list[str] = []
    for name in new:
        candidate, n = name, 2
        while candidate in seen:
            candidate, n = f"{name}_{n}", n + 1
        seen.add(candidate)
        out.append(candidate)
    return out


def _project_semop_columns(step: ProgramStep, src_cols: list[str]) -> list[str]:
    """The output columns a semop step produces from its input columns — mirrors the operators EXACTLY
    (filter/top_k preserve columns; extract appends its field names uniquified; aggregate → [out_column])."""
    if step.operator == "extract":
        return list(src_cols) + _uniquify(src_cols, [name for name, _ in step.fields])
    if step.operator == "aggregate":
        return [step.out_column or "answer"]
    return list(src_cols)                       # filter, top_k: same columns, fewer/reordered rows


def _error_result(msg: str) -> QueryResult:
    return QueryResult(hypothesis_id="__program__", sql="", columns=[], rows=[], row_count=0, error=msg)


def _write_artifact(step: ProgramStep, result: QueryResult, *, conn_id: str,
                    investigation_id: str, org_id: Optional[str]) -> str:
    """Mirror a step's result into the ledger as a named, versioned artifact with provenance edges.
    Fail-open: a ledger hiccup returns "" and never fails the run."""
    try:
        from aughor.kernel.ledger import Ledger
        return Ledger.default().artifact_write(
            kind="program_step",
            natural_key=f"artifact:{conn_id}:{investigation_id}:{step.writes}",
            payload={
                "columns": result.columns, "rows": result.rows, "row_count": result.row_count,
                "error": result.error, "step_id": step.id, "kind": step.kind,
                "sql": result.sql, "operator": step.operator or None,
            },
            conn_id=conn_id, org_id=org_id,
            lineage=[("reads", f"artifact:{conn_id}:{investigation_id}:{r}", step.id) for r in step.reads]
            + [("program", f"plan:{conn_id}:{investigation_id}", step.id)],
        )
    except Exception as exc:  # noqa: BLE001 — the ledger mirror is advisory; the run stands
        from aughor.kernel.errors import tolerate
        tolerate(exc, "program-step ledger mirror is fail-open; the run result is unaffected",
                 counter="plan.program.artifact_write")
        return ""


# ── Artifact ⇄ connection materialization (Stage A: DATA-reads-artifact dataflow) ──

def _register_artifact(db, name: str, qr: QueryResult) -> Optional[str]:
    """Register a prior artifact's rows as a queryable relation ``name`` on the connection, so a later DATA
    step can ``SELECT ... FROM name``. Returns the kind ("reg"|"view") on success via the out-list below, or
    an error string. Only DuckDB-family connections (a ``_conn`` with ``register``) can hold artifact tables;
    anything else returns an error the caller turns into a stop-on-error.

    Rows arrive stringified from the connection layer (every value is ``str()``-rendered, NULL → "NULL"), so
    the relation is all-VARCHAR — a numeric DATA step over an artifact should CAST. Returns (None, kind) on
    success or (error, "") on failure."""
    raw = getattr(db, "_conn", None)
    if raw is None or not hasattr(raw, "register"):
        return f"cannot read artifact {name!r}: connection does not support artifact tables (DuckDB only)"
    try:
        cols = list(qr.columns)
        if qr.rows:
            import pyarrow as pa               # the same Arrow path connectors/federated.py registers with
            table = pa.table({
                c: pa.array([row[j] if j < len(row) else None for row in qr.rows], type=pa.string())
                for j, c in enumerate(cols)
            })
            raw.register(name, table)          # a temp view in the in-memory catalog (read-only-safe)
            return None
        # Empty artifact: a 0-row typed view so `FROM name` still resolves.
        proj = ", ".join(f'CAST(NULL AS VARCHAR) AS "{c}"' for c in cols) or 'CAST(NULL AS VARCHAR) AS "_empty"'
        raw.execute(f'CREATE OR REPLACE TEMP VIEW "{name}" AS SELECT {proj} WHERE 1=0')
        return None
    except Exception as exc:  # noqa: BLE001 — a registration failure is a step error, not a crash
        return f"cannot materialize artifact {name!r}: {str(exc)[:100]}"


def _unregister_artifacts(db, names: list[str]) -> None:
    """Best-effort teardown of artifact relations so the pooled connection is never left polluted."""
    raw = getattr(db, "_conn", None)
    if raw is None:
        return
    for name in names:
        for teardown in (lambda n=name: raw.unregister(n),
                         lambda n=name: raw.execute(f'DROP VIEW IF EXISTS "{n}"')):
            try:
                teardown()
            except Exception:  # noqa: BLE001 — teardown is best-effort
                pass


# ── The deterministic validator ───────────────────────────────────────────────

def validate_program(program: Program, conn_id: str) -> list[str]:
    """Deterministic pre-execution checks. Mirrors ``validate_plan``: walk the steps building the model of
    what artifacts exist and their known columns, collecting issues; NOTHING executes if issues are returned.

    Order IS topology — every ``reads`` must name an EARLIER step's ``writes`` (only prior writes are in the
    model), which simultaneously rejects forward references and cycles with no sort. DATA steps must ground
    and parse; SEMOP steps must read exactly one artifact, name an operator with its required arg, and target
    a column that exists in the read artifact WHERE KNOWABLE (SQL-derived and extract-appended columns are
    tracked, so a semop chain still validates faithfully)."""
    from aughor.db.connection import open_connection_for

    issues: list[str] = []
    if not program.steps:
        return ["program has no steps"]

    written: dict[str, list[str]] = {}   # artifact name -> its known output columns (empty list = unknown)
    seen_ids: set[str] = set()
    for i, step in enumerate(program.steps):
        if step.id in seen_ids:
            issues.append(f"step {i}: duplicate id {step.id!r}")
        seen_ids.add(step.id)
        if not (step.writes or "").strip():
            issues.append(f"step {i} ({step.id}): writes is empty")
        elif step.writes in written:
            issues.append(f"step {i} ({step.id}): writes {step.writes!r} was already produced by an earlier step")

        for r in step.reads:
            if r not in written:
                issues.append(f"step {i} ({step.id}): reads {r!r} which is not an earlier step's output")

        if step.kind == "data":
            if i == 0 and step.reads:
                issues.append("step 0 (driver) must read nothing")
            if not (step.sql or "").strip():
                issues.append(f"step {i} ({step.id}): data step has empty sql")
                written[step.writes] = []
                continue
            if step.reads:
                # A DATA step that reads prior artifacts queries relations registered only at run time, so
                # its SQL cannot be parse-grounded statically (the relations don't exist yet). Structure is
                # checked above; the guard battery + stop-on-error catch a bad query at run. Columns unknown.
                written[step.writes] = []
            else:
                cols = _columns_of(open_connection_for(conn_id), step.sql)
                if cols is None:
                    issues.append(f"step {i} ({step.id}): sql did not parse/ground on the connection")
                written[step.writes] = cols or []
        else:  # semop
            if len(step.reads) != 1:
                issues.append(f"step {i} ({step.id}): a semop must read exactly one artifact (got {len(step.reads)})")
            if not step.operator:
                issues.append(f"step {i} ({step.id}): semop has no operator")
            elif step.operator == "filter" and not step.predicate.strip():
                issues.append(f"step {i} ({step.id}): filter needs a predicate")
            elif step.operator == "extract" and not step.fields:
                issues.append(f"step {i} ({step.id}): extract needs at least one field")
            elif step.operator == "top_k" and not step.criterion.strip():
                issues.append(f"step {i} ({step.id}): top_k needs a criterion")
            elif step.operator == "aggregate" and not step.instruction.strip():
                issues.append(f"step {i} ({step.id}): aggregate needs an instruction")
            src_cols = written.get(step.reads[0]) if step.reads else None
            if src_cols and step.column and step.column not in src_cols:
                issues.append(f"step {i} ({step.id}): column {step.column!r} is not in {step.reads[0]!r} ({', '.join(src_cols)})")
            written[step.writes] = _project_semop_columns(step, src_cols or [])
    return issues


# ── The deterministic executor ────────────────────────────────────────────────

def run_program(program: Program, conn_id: str, *, investigation_id: str,
                org_id: Optional[str] = None) -> ProgramResult:
    """Execute a validated program step-by-step, threading named artifacts. Fail-open per step and STOP on a
    hard error (matches ``answer_federated``: a failing step returns immediately, so no downstream semop reads
    a missing artifact). Callers should run ``validate_program`` first — the executor trusts that reads resolve.

    DATA steps run through the shipped guard battery (``execute_guarded``) in DETERMINISTIC-ONLY mode (no
    fix-prompt/provider → the guards run but no LLM repair). SEMOP steps run through ``apply_step`` over the
    prior artifact named in ``reads[0]``."""
    from aughor.db.connection import open_connection_for
    from aughor.semops.operators import apply_step
    from aughor.sql.executor import execute_guarded

    by_name: dict[str, QueryResult] = {}
    artifacts: dict[str, str] = {}
    warnings: list[str] = []
    registered: list[str] = []        # artifact relations put on the live connection; torn down in finally
    db = open_connection_for(conn_id)
    schema = db.get_schema()          # enables execute_guarded's deterministic preflight hardening

    result: QueryResult = _error_result("program has no steps")
    try:
        for i, step in enumerate(program.steps):
            if step.kind == "data":
                # Stage A: a DATA step may read prior artifacts as input tables — register each on the
                # (persistent, reused) connection under its name before the SQL runs. A reads step's SQL
                # references run-time relations the schema can't see, so skip schema-based preflight
                # (`schema=None`) to avoid identifier repair rewriting an artifact name; post-execute guards
                # still run. A no-reads step keeps full preflight hardening.
                reg_err = None
                for name in step.reads:
                    src = by_name.get(name)
                    if src is None:
                        reg_err = f"reads {name!r} which was not produced"
                        break
                    reg_err = _register_artifact(db, name, src)
                    if reg_err is not None:
                        break
                    if name not in registered:
                        registered.append(name)
                if reg_err is not None:
                    result = _error_result(f"data step {step.id!r} {reg_err}")
                else:
                    result = execute_guarded(db, step.sql, query_id=f"__program__{step.id}",
                                             schema=(None if step.reads else schema))
            else:
                src = by_name.get(step.reads[0]) if step.reads else None
                if src is None:
                    result = _error_result(f"semop step {step.id!r} reads {step.reads!r} which was not produced")
                else:
                    op = apply_step(
                        src, step.operator, step.column,
                        predicate=step.predicate, fields=step.fields, criterion=step.criterion,
                        k=step.k, instruction=step.instruction, out_column=step.out_column,
                        max_rows=_SEMOP_MAX_ROWS,
                    )
                    warnings.extend(f"{step.id}: {n}" for n in op.notes)
                    result = op.result

            artifacts[step.writes] = _write_artifact(
                step, result, conn_id=conn_id, investigation_id=investigation_id, org_id=org_id)
            if result.error:
                return ProgramResult(result, program, artifacts, warnings,
                                     [f"step {i} ({step.id}) failed: {result.error}"])
            by_name[step.writes] = result

        from aughor.stats import bump
        bump("plan.program.executed")
        return ProgramResult(result, program, artifacts, warnings, [])
    finally:
        _unregister_artifacts(db, registered)


def run_checked_program(program: Program, conn_id: str, *, investigation_id: str,
                        org_id: Optional[str] = None) -> ProgramResult:
    """Validate a (hand-authored) program then run it — or return an error result carrying the validation
    issues if it fails the deterministic gate. The public entry point for the ``/query/plan-run`` endpoint,
    so the router never has to touch the module internals."""
    issues = validate_program(program, conn_id)
    if issues:
        return ProgramResult(_error_result("program failed validation: " + "; ".join(issues)),
                             program, {}, [], issues)
    return run_program(program, conn_id, investigation_id=investigation_id, org_id=org_id)


# ── The Stage-3 LLM planner ───────────────────────────────────────────────────

_PLAN_SYS = (
    "You turn an analytical question into a deterministic PROGRAM over ONE database. Emit an ordered list "
    "of steps that assemble the answer. Each step is either:\n"
    "- a DATA op (`kind`='data'): a `sql` (a single SELECT grounded ONLY in this database's schema) that "
    "`writes` a named artifact. The FIRST step is a DATA op and `reads` nothing.\n"
    "- a SEMOP (`kind`='semop'): one of `operator` = filter | extract | top_k | aggregate applied to ONE "
    "prior artifact (named in `reads`) over its free-text `column`, writing a new artifact.\n"
    "A later DATA op may ALSO `reads` one or more prior artifacts and query them by name as tables — e.g. "
    "run a semop over free text, then `SELECT ... GROUP BY` over the semop's output artifact. Use artifact "
    "names DISTINCT from real table names (a collision shadows the real table); artifact columns are text, "
    "so CAST when doing arithmetic.\n"
    "Every step has a stable `id`, the artifact name it `writes`, and the artifact name(s) it `reads` (the "
    "first step reads nothing). Push all structured work — filters, joins, aggregations — into DATA-op SQL; "
    "use semops ONLY for reasoning over free text that SQL cannot do (filter by meaning, extract fields from "
    "prose, rank by a fuzzy criterion, summarize). Return only the program."
)


def plan_program(question: str, conn_id: str) -> Program:
    """One LLM call: ground the connection schema, return a typed program."""
    from aughor.db.connection import open_connection_for
    from aughor.llm.provider import get_provider

    schema = open_connection_for(conn_id).get_schema()
    user = f"Question: {question}\n\n=== schema ===\n{schema}\n\nProduce the program."
    return get_provider("coder").complete(system=_PLAN_SYS, user=user, response_model=Program)


def _gate_program_sql(program: Program, conn_id: str) -> Optional[str]:
    """Gate every DATA step's SQL through the same safety checker the Query Builder uses; the first block
    returns its message, else None. Applied to both freshly-planned and replayed programs."""
    from aughor.db.connection import gate_user_sql
    for i, step in enumerate(program.steps):
        if step.kind == "data":
            blocked = gate_user_sql(conn_id, "program_planner", step.sql)
            if blocked is not None:
                return f"step {i} sql blocked by safety gate: {blocked.error}"
    return None


def _replay_trusted_program(question: str, conn_id: str, *, investigation_id: str,
                            org_id: str) -> Optional[ProgramResult]:
    """If a trusted program matches this question, RE-VALIDATE it against the current schema and, if clean,
    replay it deterministically (no LLM). Returns the result, or None to fall through to fresh planning — a
    stale/invalid cached plan (schema drift, a newly-blocked query) never replays. Closed-loop-gated caller."""
    try:
        from aughor.semantic.trusted_programs import record_program_hit, retrieve_trusted_program
        hit = retrieve_trusted_program(question, conn_id, org_id=org_id)
    except Exception as exc:  # noqa: BLE001 — retrieval is best-effort; fall through to fresh planning
        from aughor.kernel.errors import tolerate
        tolerate(exc, "trusted-program retrieval is best-effort", counter="plan.program.replay_retrieve")
        return None
    if hit is None:
        return None
    tp, _score = hit
    try:
        cached = Program(**tp.program)
    except Exception:  # noqa: BLE001 — a corrupt stored plan just falls through
        return None
    if not cached.steps or _gate_program_sql(cached, conn_id) or validate_program(cached, conn_id):
        return None
    record_program_hit(tp.id)
    from aughor.kernel import metering
    metering.record_learning(trusted_program_replayed=1)   # per-run Learning Receipt (Wave 1·E4)
    return run_program(cached, conn_id, investigation_id=investigation_id, org_id=org_id)


def answer_program(question: str, conn_id: str, *, investigation_id: Optional[str] = None,
                   org_id: Optional[str] = None) -> ProgramResult:
    """Full plan-then-execute: plan (LLM) → gate + validate (deterministic) → run (engine). Mirrors
    ``answer_federated``: a planning failure is an answer, not a 500; every DATA sub-query is gated through
    the same safety checker the Query Builder uses before anything runs.

    Closed-loop replay (Stage C): when ``closed_loop`` is on, a matching trusted program is replayed
    deterministically instead of re-planning, and a clean fresh run is crystallized so it replays next time.
    Both are best-effort and default-off, so the base behaviour is unchanged."""
    from aughor.verify.priors import closed_loop_enabled

    inv = investigation_id or hashlib.sha1(question.encode()).hexdigest()[:12]
    oid = org_id or ""

    if closed_loop_enabled():
        replayed = _replay_trusted_program(question, conn_id, investigation_id=inv, org_id=oid)
        if replayed is not None:
            return replayed

    try:
        program = plan_program(question, conn_id)
    except Exception as exc:  # noqa: BLE001 — a planning failure is an answer, not a 500
        logger.warning("program planner: planning failed: %s", exc)
        return ProgramResult(_error_result(f"planning failed: {str(exc)[:120]}"), None, {}, [], ["planning failed"])

    if not program.steps:
        return ProgramResult(_error_result("program has no steps"), program, {}, [], ["program has no steps"])

    blocked = _gate_program_sql(program, conn_id)
    if blocked is not None:
        return ProgramResult(_error_result(blocked), program, {}, [], [blocked])

    issues = validate_program(program, conn_id)
    if issues:
        return ProgramResult(_error_result("program failed validation: " + "; ".join(issues)),
                             program, {}, [], issues)

    pr = run_program(program, conn_id, investigation_id=inv, org_id=oid)

    # Crystallize a clean, freshly-planned program so the next near-identical question replays it (Stage C).
    if closed_loop_enabled() and not pr.issues and not pr.result.error:
        try:
            from aughor.semantic.trusted_programs import TrustedProgram, save_trusted_program
            save_trusted_program(TrustedProgram(
                connection_id=conn_id, org_id=oid, question=question,
                program=program.model_dump(), plan_source="auto"))
        except Exception as exc:  # noqa: BLE001 — saving is best-effort; never fails the answer
            from aughor.kernel.errors import tolerate
            tolerate(exc, "trusted-program save is best-effort", counter="plan.program.save")
    return pr
