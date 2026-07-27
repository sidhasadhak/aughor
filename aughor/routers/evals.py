"""The Evals surface — suites, cases, runs (Wave E3).

Every route is gated on ``Capability.EVAL_SUITE``, which until now was declared
in the licensing table, sold as an Enterprise capability, and gated **nothing** —
there was not one ``gate(Capability.EVAL_SUITE)`` call site in the codebase.

This is the consolidation door. Four eval surfaces existed before it, none of
which shared a store, a record schema, a scorer or a gate:
``POST /eval/run`` (ungated, self-scoring, unreachable from a wheel — removed),
``/semantic/{conn}/benchmarks`` (string-matched, zero records ever authored —
deprecated here, retargeted when the UI moves in E5),
``/agents/custom/{id}/evaluate`` (execution-grounded and good, but per-agent and
flag-hidden), and ``/packs/{id}/evaluate`` (the promotion-gate concept worth
keeping). The golden-SQL corpus and its hermetic CI gate are deliberately
untouched: they are load-bearing.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aughor.evals import store
from aughor.licensing import Capability, gate

router = APIRouter(tags=["evals"])


class SuiteIn(BaseModel):
    name: str
    description: str = ""
    target: str = "reference"
    connection_id: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class CaseIn(BaseModel):
    question: str = ""
    artifact: str = ""
    expected: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class CasesIn(BaseModel):
    cases: list[CaseIn]


class RunIn(BaseModel):
    iterations: int = Field(default=1, ge=1, le=10)
    evaluators: Optional[list[str]] = None
    persist: bool = True


class GraduateIn(BaseModel):
    suite_id: str
    #: Judge this run; when omitted, the suite's most recent run is used.
    run_id: Optional[str] = None
    #: The flag-OFF pass rate to beat. When omitted, the run must clear ``min_pass_rate``.
    baseline_pass_rate: Optional[float] = None
    min_pass_rate: float = 1.0


def _ab_evidence(suite_id: str, flag: str, *, limit: int = 24) -> tuple:
    """Derive the A/B baseline and its noise floor from the suite's OWN run history.

    A caller-supplied ``baseline_pass_rate`` is a scalar with no provenance: nothing
    about it says which runs produced it, or whether those runs agree with themselves.
    That is how a flag graduates on jitter, so the gate now demands floor evidence — and
    demanding it from the caller only moves the burden. The runs are already on disk,
    stamped by `run_experiment` with the cell that produced them, so the server can just
    look.

    Returns ``(baseline_pass_rate, delta)`` — both ``None`` when the history does not
    contain a usable A/B for this flag, in which case the caller's own inputs stand.

    Cells are classified by what the run RECORDED it was asked for
    (``config.cell_requested.flags[flag]``), never by the label, so a cell named
    "control" that actually ran with the flag on cannot be read as the baseline.
    """
    from aughor.evals import fidelity as _fidelity

    off_runs: list[dict] = []
    on_runs: list[dict] = []
    for run in store.list_runs(suite_id, limit=limit):
        if run.get("status") != "succeeded":
            continue
        cfg = run.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "a run whose config JSON is unreadable cannot be attributed "
                              "to a cell, so it is not counted as A/B evidence",
                         counter="evals.graduate.bad_run_config")
                continue
        requested = ((cfg or {}).get("cell_requested") or {}).get("flags") or {}
        if flag not in requested:
            continue
        summary = run.get("summary") or {}
        if summary.get("pass_rate") is None:
            continue
        (on_runs if requested[flag] else off_runs).append(summary)

    # One replicate per side cannot establish a floor — a configuration compared only
    # against another configuration, never against itself, tells you nothing about
    # whether it agrees with itself.
    if len(off_runs) < 2 or not on_runs:
        return None, None
    baseline = sum(r["pass_rate"] for r in off_runs) / len(off_runs)
    return baseline, _fidelity.compare(off_runs, on_runs, axis="pass_rate")


def _suite_or_404(suite_id: str) -> dict:
    suite = store.get_suite(suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


# ── suites ────────────────────────────────────────────────────────────────────

@router.get("/evals/suites", dependencies=[gate(Capability.EVAL_SUITE)])
def list_suites():
    return {"suites": store.list_suites()}


@router.post("/evals/suites", status_code=201, dependencies=[gate(Capability.EVAL_SUITE)])
def create_suite(body: SuiteIn):
    return store.create_suite(body.name, description=body.description,
                              target=body.target, connection_id=body.connection_id,
                              config=body.config)


@router.get("/evals/suites/{suite_id}", dependencies=[gate(Capability.EVAL_SUITE)])
def get_suite(suite_id: str):
    suite = _suite_or_404(suite_id)
    return {**suite, "cases": store.list_cases(suite_id)}


@router.delete("/evals/suites/{suite_id}", dependencies=[gate(Capability.EVAL_SUITE)])
def delete_suite(suite_id: str):
    if not store.delete_suite(suite_id):
        raise HTTPException(status_code=404, detail="Suite not found")
    return {"deleted": suite_id}


# ── cases ─────────────────────────────────────────────────────────────────────

@router.post("/evals/suites/{suite_id}/cases", status_code=201,
             dependencies=[gate(Capability.EVAL_SUITE)])
def add_cases(suite_id: str, body: CasesIn):
    _suite_or_404(suite_id)
    added = store.add_cases(suite_id, [c.model_dump() for c in body.cases])
    return {"added": added}


@router.delete("/evals/cases/{case_id}", dependencies=[gate(Capability.EVAL_SUITE)])
def delete_case(case_id: str):
    if not store.delete_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return {"deleted": case_id}


# ── runs ──────────────────────────────────────────────────────────────────────

@router.post("/evals/suites/{suite_id}/run", dependencies=[gate(Capability.EVAL_SUITE)])
def run_suite_route(suite_id: str, body: RunIn):
    """Run a suite against its declared target.

    Synchronous by design for now: a suite is bounded by its case count and the
    caller chose the iteration count, so the cost is knowable up front rather
    than discovered. A long model-backed suite belongs on the job kernel, which
    is the natural follow-on once a target that calls a model is wired here.
    """
    suite = _suite_or_404(suite_id)
    from aughor.evals.runner import run_suite
    from aughor.evals.targets import reference_checker, reference_target

    if suite["target"] != "reference":
        raise HTTPException(
            status_code=400,
            detail=f"target {suite['target']!r} is not runnable from the API yet; "
                   "only 'reference' (replay the case's own SQL, no model) is wired")

    conn_id = suite.get("connection_id") or ""
    if not conn_id:
        raise HTTPException(status_code=400, detail="suite has no connection_id")
    try:
        from aughor.db.connection import open_connection_for
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    dialect = getattr(db, "dialect", None) or "duckdb"
    table_cols = None
    try:
        from aughor.db.schema_render import parse_schema_tables
        table_cols = parse_schema_tables(db.get_schema())
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "eval run: schema unavailable; static guards run degraded",
                 counter="evals.route.schema")

    summary = run_suite(
        suite_id,
        reference_target(db, dialect=dialect, table_cols=table_cols),
        iterations=body.iterations, evaluators=body.evaluators,
        checker=reference_checker(db), persist=body.persist,
    )
    return summary.to_dict()


@router.get("/evals/runs", dependencies=[gate(Capability.EVAL_SUITE)])
def list_runs(suite_id: Optional[str] = None, limit: int = 50):
    return {"runs": store.list_runs(suite_id, limit=limit)}


@router.get("/evals/runs/{run_id}", dependencies=[gate(Capability.EVAL_SUITE)])
def get_run(run_id: str):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {**run, "results": store.run_results(run_id)}


# ── graduations (Wave E6 — the promotion gate) ──────────────────────────────────

@router.post("/evals/flags/{flag}/graduate", dependencies=[gate(Capability.EVAL_SUITE)])
def graduate_flag(flag: str, body: GraduateIn):
    """Decide whether ``flag`` has earned default-on, from an eval run, and RECEIPT it.

    This records a decision — it does not flip the flag. A graduation is the evidence a
    human uses to change ``FLAG_DEFAULT`` in a reviewed PR; setting a runtime override here
    would re-create the ledger-on/code-off drift the 2026-07-22 audit removed. The decision
    (and its blockers, if any) is persisted and emitted as an ``eval.graduation`` ledger
    event — the receipt.
    """
    from aughor.evals import store
    from aughor.evals.promotion import evaluate_graduation
    from aughor.kernel.flags import FLAG_DEFAULT, FLAG_ENV
    from aughor.kernel.ledger import Ledger

    suite = _suite_or_404(body.suite_id)

    run = store.get_run(body.run_id) if body.run_id else None
    if run is None and not body.run_id:
        recent = store.list_runs(body.suite_id, limit=1)
        run = recent[0] if recent else None
    if body.run_id and run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run_summary = (run or {}).get("summary") or None

    # Prefer evidence the server can see over a number the caller asserts. When the
    # suite's history holds a real A/B for this flag, its baseline AND its floor are
    # derived here; a caller-supplied baseline is only used when there is no such
    # history, and then it is refused for lacking a floor (which is the honest answer,
    # not a regression).
    derived_baseline, derived_delta = _ab_evidence(body.suite_id, flag)
    decision = evaluate_graduation(
        flag, run_summary,
        registered_flags=set(FLAG_ENV),
        current_default=bool(FLAG_DEFAULT.get(flag, False)),
        baseline_pass_rate=(derived_baseline if derived_baseline is not None
                            else body.baseline_pass_rate),
        min_pass_rate=body.min_pass_rate,
        delta=derived_delta,
    )
    payload = decision.to_dict()
    # A no-run decision carries no suite_id from the summary — pin the one the caller named.
    payload["suite_id"] = payload.get("suite_id") or body.suite_id

    record = store.record_graduation(payload)
    try:
        Ledger.default().emit("eval.graduation", record,
                              conn_id=suite.get("connection_id") or None)
    except Exception as exc:  # the decision is already persisted; the event is the audit copy
        from aughor.kernel.errors import tolerate
        tolerate(exc, "eval graduation: ledger emit failed; decision still recorded",
                 counter="evals.graduation.emit")
    return {**payload, "receipt_id": record["id"], "decided_at": record["decided_at"]}


@router.get("/evals/graduations", dependencies=[gate(Capability.EVAL_SUITE)])
def list_graduations(flag: Optional[str] = None, limit: int = 50):
    from aughor.evals import store
    return {"graduations": store.list_graduations(flag, limit=limit)}


@router.get("/evals/evaluators", dependencies=[gate(Capability.EVAL_SUITE)])
def list_evaluators():
    """The registered evaluator set — what a suite can be scored against."""
    from aughor.evals import deterministic_evaluators, get_evaluator, registered_evaluators
    names = registered_evaluators()
    out = []
    for name in names:
        ev = get_evaluator(name)
        out.append({"name": name, "severity": getattr(ev, "severity", ""),
                    "requires": list(getattr(ev, "requires", ())),
                    "deterministic": bool(getattr(ev, "deterministic", True))})
    return {"evaluators": out, "deterministic_count": len(deterministic_evaluators())}
