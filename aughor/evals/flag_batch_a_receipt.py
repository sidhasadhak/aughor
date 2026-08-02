"""Flag strategy batch A — deterministic evidence for nine construction-decidable flags.

**The batch claim.** `docs/FLAG_STRATEGY_2026-07-31.md` §4A: each of these nine flags is
deterministic and its graduation claim is decidable by CONSTRUCTION — no model in the
loop, no sampling, so (per the L4/N3/CR0/Wave-H carve-out) no A/B grid and no noise
floor. One suite carries all nine because they graduate as one reviewed batch; every
scenario is named ``<flag prefix>__<claim>`` (see :data:`SCENARIO_PREFIX`) so a receipt
reader can see exactly which cases back which flag.

The nine, and the claim each rests on:

- ``preflight.parallel`` — the four plan-time retrievals are independent, deterministic,
  non-LLM; the flag changes only WHICH EXECUTOR runs the same closures, and the risk it
  buys is context propagation into pooled workers — asserted here through the exact
  ``fanout_region`` + ``ContextThreadPoolExecutor`` pattern the code uses.
- ``deep_analysis.evidence_dedup`` — lossless by construction: the FIRST occurrence renders full
  and byte-identical, only later same-fingerprint repeats become pointers naming where
  the full copy is, and an errored result is never collapsed. (The fingerprint is over
  normalized SQL — the same same-SQL-same-run equivalence the wandering veto already
  embodies more aggressively.)
- ``schema.two_tier_catalog`` — safe direction only: a small schema returns
  byte-identical, a focused output is never larger than the input, and the table named
  ONLY in the error message is autoloaded with full DDL (the outcome-changing half).
- ``explore.wandering_detector`` — fail-open in the strongest sense: a repeat is reused
  VERBATIM (never re-run, never re-summarised), and malformed history means the query
  runs exactly as it would have.
- ``monitors.guarded`` — caveat-and-deliver: the alert's severity and message are
  byte-identical on vs off, the caveat is purely additive, the monitor's SQL is never
  rewritten, and a probe crash leaves the alert untouched.
- ``consistency.divergence`` — the routes are the whole surface: off they 404, on they
  answer read-only from receipts already stored; nothing on the answer path.
- ``ops.metered_monitors`` — the same ``_work`` closure runs on both paths by
  construction; with no kernel loop captured the bridge DECLINES (returns None, runs
  nothing) so the caller falls back inline — the property that makes the flip safe in
  every process that never started the kernel.
- ``evals.experiments`` — off refuses LOUDLY (a grid silently run under one
  configuration would read as "the variant made no difference"); on, ambient traffic is
  untouched because the experiment plane lives in contextvars that default unset.
- ``starters.library`` — the payload is deterministic (same input, same starters, each
  declaring its route and purpose up front) and purely additive on /suggestions.

Hermetic: no LLM, no warehouse, no network; monitor scenarios run against an in-memory
stub DB; nothing writes outside throwaway objects.
"""
from __future__ import annotations

from typing import Callable

from aughor.evals.equivalence import Comparison, DeterministicEquivalenceEvaluator
from aughor.evals.evaluator import EvalCase, EvalObservation

#: Suite name — looked up by name so creating the suite is idempotent across runs.
SUITE_NAME = "flag strategy batch A — nine construction-decidable graduations"

#: The flags this suite is evidence for (each minted its own graduation decision).
FLAGS = (
    "preflight.parallel", "deep_analysis.evidence_dedup", "schema.two_tier_catalog",
    "explore.wandering_detector", "monitors.guarded", "consistency.divergence",
    "ops.metered_monitors", "evals.experiments", "starters.library",
)

#: The scenario-name prefix that backs each flag — the receipt's flag→cases map.
SCENARIO_PREFIX = {
    "preflight.parallel": "preflight_parallel",
    "deep_analysis.evidence_dedup": "evidence_dedup",
    "schema.two_tier_catalog": "two_tier_catalog",
    "explore.wandering_detector": "wandering_detector",
    "monitors.guarded": "monitors_guarded",
    "consistency.divergence": "consistency_divergence",
    "ops.metered_monitors": "metered_monitors",
    "evals.experiments": "evals_experiments",
    "starters.library": "starters_library",
}

Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


def _qr(step: str, sql: str, *, rows=None, error=None):
    from aughor.control_plane.contracts.execution import QueryResult
    rows = [[1]] if rows is None else rows
    return QueryResult(hypothesis_id=step, sql=sql, columns=["a"], rows=rows,
                       row_count=len(rows), error=error, caveats=[])


# ── preflight.parallel ───────────────────────────────────────────────────────────

@scenario("preflight_parallel__context_reaches_pooled_workers")
def _preflight_parallel__context_reaches_pooled_workers() -> Comparison:
    """The flag swaps the executor, not the work: four closures either run serially or
    through ``ContextThreadPoolExecutor`` inside ``fanout_region("deep_analysis.preflight")`` —
    the exact pattern at aughor/agent/nodes.py. What the flip actually risks is context
    loss in the pool (flags, org, model pins all travel by contextvar), so that is what
    is asserted: the pooled run sees the same context and returns the same values in
    the same fixed assembly order as the serial run."""
    from aughor.kernel.concurrency import ContextThreadPoolExecutor
    from aughor.kernel.flags import flag_enabled, flag_overrides
    from aughor.kernel.parallel_safety import fanout_region
    from aughor.org.context import current_org_id, using_org

    def probe(tag: str):
        # Deterministic, context-reading stand-ins for the four retrievals.
        return (tag, flag_enabled("preflight.parallel"), current_org_id())

    with flag_overrides({"preflight.parallel": True}), using_org("default"):
        serial = [probe(t) for t in ("schema", "kb", "causal", "priors")]
        with fanout_region("deep_analysis.preflight"), ContextThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(probe, t) for t in ("schema", "kb", "causal", "priors")]
            pooled = [f.result() for f in futs]
    return Comparison(
        scenario="preflight_parallel__context_reaches_pooled_workers",
        expected={"values": serial}, observed={"values": pooled},
        oracle="serial run",
        note="pooled workers inherit flag + org context and assemble in fixed order",
    )


# ── ada.evidence_dedup ───────────────────────────────────────────────────────────

@scenario("evidence_dedup__collapse_is_lossless_by_construction")
def _evidence_dedup__collapse_is_lossless_by_construction() -> Comparison:
    """First occurrence full and byte-identical; only the LATER same-fingerprint repeat
    becomes a pointer naming the step that holds the full copy; an errored result is
    never collapsed even when its SQL repeats."""
    from aughor.agent import evidence_budget as EB

    render = lambda r: f"FULL[{r.hypothesis_id}:{r.sql}]"  # noqa: E731
    dup_sql = "SELECT region, SUM(rev) FROM sales GROUP BY region"
    history = [
        _qr("Q1", dup_sql),
        _qr("Q2", "SELECT 1 FROM other"),
        _qr("Q3", "select   region,\n  sum(rev)\nfrom sales\ngroup by region;"),  # same query, reformatted
        _qr("Q4", dup_sql, error="timeout"),                                      # errored — never collapsed
    ]
    parts, info = EB.render_history(history, full_renderer=render,
                                    collapse_duplicates=True, seen={})
    return Comparison(
        scenario="evidence_dedup__collapse_is_lossless_by_construction",
        expected={"first_is_full": True, "repeat_is_pointer": True,
                  "error_kept_full": True, "duplicates": 1, "full": 3},
        observed={"first_is_full": parts[0] == render(history[0]),
                  "repeat_is_pointer": "Q1" in parts[2] and parts[2] != render(history[2]),
                  "error_kept_full": parts[3] == render(history[3]),
                  "duplicates": info["duplicates"], "full": info["full"]},
        oracle="declared (Wave R3, lossless-by-construction)",
        note="the full copy is always in the block exactly once; errors never collapse",
    )


# ── schema.two_tier_catalog ──────────────────────────────────────────────────────

def _big_schema(*tables: str) -> str:
    blocks = []
    for t in tables:
        cols = "\n".join(f"  {t}_col{i} INTEGER" for i in range(1, 21))
        blocks.append(f"TABLE: {t}  (10,000 rows)\n{cols}\n")
    return "\n".join(blocks)


@scenario("two_tier_catalog__a_small_schema_returns_byte_identical")
def _two_tier_catalog__a_small_schema_returns_byte_identical() -> Comparison:
    """Below FOCUS_MIN_CHARS the full schema is returned untouched even with the flag
    on — the safe-direction floor."""
    from aughor.agent.schema_focus import for_repair
    from aughor.kernel.flags import flag_overrides

    small = _big_schema("orders", "customers")
    with flag_overrides({"schema.two_tier_catalog": True}):
        out = for_repair(small, "SELECT * FROM orders", "no such column: x")
    return Comparison(
        scenario="two_tier_catalog__a_small_schema_returns_byte_identical",
        expected={"identical": True}, observed={"identical": out == small},
        oracle="the input schema",
        note="a small schema is never narrowed — trimming it could only lose ground",
    )


@scenario("two_tier_catalog__the_error_named_table_is_autoloaded")
def _two_tier_catalog__the_error_named_table_is_autoloaded() -> Comparison:
    """The outcome-changing half: a table named ONLY in the error message gets full DDL
    (a binder error is unfixable without it), and the focused output is never larger
    than the input."""
    from aughor.agent import schema_focus as SF
    from aughor.kernel.flags import flag_overrides

    big = _big_schema(*[f"t{i}" for i in range(1, 41)], "orders", "customers")
    assert len(big) > SF.FOCUS_MIN_CHARS
    with flag_overrides({"schema.two_tier_catalog": True}):
        out = SF.for_repair(big, "SELECT * FROM orders",
                            'no such column: signup_date on table "customers"')
    return Comparison(
        scenario="two_tier_catalog__the_error_named_table_is_autoloaded",
        expected={"referenced_table_full": True, "error_table_full": True,
                  "never_larger": True, "narrowed": True},
        observed={"referenced_table_full": "orders_col20" in out,
                  "error_table_full": "customers_col20" in out,
                  "never_larger": len(out) <= len(big),
                  "narrowed": len(out) < len(big)},
        oracle="declared (Wave R3, error-path autoload)",
        note="the repair prompt keeps every table the failure involves, at less cost",
    )


# ── explore.wandering_detector ───────────────────────────────────────────────────

@scenario("wandering_detector__a_repeat_is_reused_verbatim")
def _wandering_detector__a_repeat_is_reused_verbatim() -> Comparison:
    """A re-emitted query (even reformatted) is vetoed and the EARLIER result is reused
    verbatim — same rows, same columns — with the veto marked."""
    from aughor.agent import wandering as W

    prior = _qr("Q1", "SELECT region, SUM(rev) FROM sales GROUP BY region",
                rows=[["EU", 10], ["NA", 20]])
    history = [prior]
    resend = "select region,   sum(rev) from sales group by region;"
    verdict = W.check_before_dispatch(resend, history)
    repeat = W.find_repeat(resend, history)
    veto = W.veto_result("Q7", resend, repeat, verdict) if repeat is not None else None
    return Comparison(
        scenario="wandering_detector__a_repeat_is_reused_verbatim",
        expected={"is_repeat": True, "rows_reused": True, "marked": True},
        observed={"is_repeat": bool(verdict.wandering and repeat is prior),
                  "rows_reused": bool(veto is not None and veto.rows == prior.rows
                                      and veto.columns == prior.columns),
                  "marked": bool(veto is not None and veto.caveats)},
        oracle="the earlier result",
        note="the scan AND the interpret call are saved; the evidence is unchanged",
    )


@scenario("wandering_detector__malformed_history_fails_open")
def _wandering_detector__malformed_history_fails_open() -> Comparison:
    """Garbage in the run's own history must never veto a real query — any error reads
    as 'not wandering' and the query runs exactly as it would have."""
    from aughor.agent import wandering as W

    try:
        verdict = W.check_before_dispatch("SELECT 1", [object(), None, 42])
        open_ok, wandering = True, bool(verdict.wandering)
    except Exception:
        open_ok, wandering = False, True
    return Comparison(
        scenario="wandering_detector__malformed_history_fails_open",
        expected={"survives": True, "vetoes": False},
        observed={"survives": open_ok, "vetoes": wandering},
        oracle="declared (fail-open)",
        note="a detector that can suppress real evidence is worse than the redundancy",
    )


# ── monitors.guarded ─────────────────────────────────────────────────────────────

class _StubDB:
    """The test_monitors_guarded stub: id-arithmetic SQL over a two-column schema."""
    dialect = "duckdb"

    def rows(self, sql, label=None):
        return [[999.0]]

    def scalar(self, sql, label=None, cast=float):
        return 999.0

    def get_schema(self):
        return "TABLE: sales\n  order_id  INTEGER\n  amt  DOUBLE\n"


class _BrokenSchemaDB(_StubDB):
    def get_schema(self):
        raise RuntimeError("schema probe unavailable")


def _guarded_monitor():
    from aughor.monitors.models import Monitor
    return Monitor(conn_id="batch-a-receipt", name="revenue watch",
                   alert_on="threshold_cross",
                   custom_sql="SELECT SUM(amt * order_id) AS x FROM sales",
                   warning_threshold=10.0, threshold_direction="above")


@scenario("monitors_guarded__caveat_and_deliver_never_rewrites")
def _monitors_guarded__caveat_and_deliver_never_rewrites() -> Comparison:
    """On vs off: identical severity and message, identical monitor SQL afterwards; the
    only delta is an additive caveat naming the id-arithmetic footgun."""
    from aughor.kernel.flags import flag_overrides
    from aughor.monitors.runner import run_monitor

    def fire(flag_on: bool):
        m = _guarded_monitor()
        with flag_overrides({"monitors.guarded": flag_on}):
            alert = run_monitor(m, _StubDB(), suppress=False)
        return m, alert

    m_off, off = fire(False)
    m_on, on = fire(True)
    return Comparison(
        scenario="monitors_guarded__caveat_and_deliver_never_rewrites",
        expected={"severity_same": True, "message_same": True, "sql_same": True,
                  "off_caveat": False, "on_caveat": True},
        observed={"severity_same": off.severity == on.severity,
                  "message_same": off.message == on.message,
                  "sql_same": m_off.custom_sql == m_on.custom_sql,
                  "off_caveat": bool(getattr(off, "caveat", None)),
                  "on_caveat": bool(getattr(on, "caveat", None))},
        oracle="flag-off run",
        note="the alert still fires and says the same thing; the caveat is additive",
        detail={"caveat": getattr(on, "caveat", None)},
    )


@scenario("monitors_guarded__a_probe_crash_leaves_the_alert_untouched")
def _monitors_guarded__a_probe_crash_leaves_the_alert_untouched() -> Comparison:
    """Fail-open: a schema probe that raises must not block, delay or alter the alert."""
    from aughor.kernel.flags import flag_overrides
    from aughor.monitors.runner import run_monitor

    with flag_overrides({"monitors.guarded": False}):
        off = run_monitor(_guarded_monitor(), _BrokenSchemaDB(), suppress=False)
    with flag_overrides({"monitors.guarded": True}):
        on = run_monitor(_guarded_monitor(), _BrokenSchemaDB(), suppress=False)
    return Comparison(
        scenario="monitors_guarded__a_probe_crash_leaves_the_alert_untouched",
        expected={"fired": True, "severity_same": True, "message_same": True},
        observed={"fired": on is not None,
                  "severity_same": off.severity == on.severity,
                  "message_same": off.message == on.message},
        oracle="flag-off run",
        note="guard probes are best-effort; a broken probe changes nothing",
    )


# ── consistency.divergence ───────────────────────────────────────────────────────

@scenario("consistency_divergence__the_routes_are_the_whole_surface")
def _consistency_divergence__the_routes_are_the_whole_surface() -> Comparison:
    """Off, every /consistency route 404s. On, the summary answers read-only from the
    receipts store — for a connection with none, an empty accounting, written nowhere."""
    from fastapi import HTTPException

    from aughor.kernel.flags import flag_overrides
    from aughor.routers.consistency import consistency_summary

    def probe(flag_on: bool) -> dict:
        with flag_overrides({"consistency.divergence": flag_on}):
            try:
                out = consistency_summary(connection_id="batch-a-receipt-none")
                return {"status": 200, "is_dict": isinstance(out, dict)}
            except HTTPException as exc:
                return {"status": exc.status_code, "is_dict": False}

    off, on = probe(False), probe(True)
    return Comparison(
        scenario="consistency_divergence__the_routes_are_the_whole_surface",
        expected={"off_status": 404, "on_status": 200, "on_answers": True},
        observed={"off_status": off["status"], "on_status": on["status"],
                  "on_answers": on["is_dict"]},
        oracle="declared (route-gated, read-only)",
        note="nothing on the answer path; the flip makes an audit surface reachable",
    )


# ── ops.metered_monitors ─────────────────────────────────────────────────────────

@scenario("metered_monitors__with_no_kernel_loop_the_bridge_declines")
def _metered_monitors__with_no_kernel_loop_the_bridge_declines() -> Comparison:
    """The property that makes default-on safe everywhere: in a process with no
    captured kernel loop, ``submit_background_tick`` returns None WITHOUT running the
    work, and the scheduler's very next line runs the same ``_work`` closure inline —
    the legacy path, unchanged. The no-loop condition is FORCED rather than assumed
    (a first draft assumed it, and promptly failed inside the full test suite, where
    an earlier test had captured a loop — a receipt that only passes in a bare
    process is measuring the process). The routed path's equivalence is the same
    closure object by construction (see aughor/monitors/scheduler.py) and is pinned
    by tests/unit/test_metered_background.py."""
    from aughor.kernel import jobs as jobs_mod
    from aughor.kernel.jobs import submit_background_tick

    ran = {"n": 0}
    saved = getattr(jobs_mod, "_main_loop", None)
    try:
        jobs_mod._main_loop = None
        out = submit_background_tick("monitor",
                                     lambda: ran.__setitem__("n", ran["n"] + 1),
                                     conn_id="batch-a-receipt")
    finally:
        jobs_mod._main_loop = saved
    return Comparison(
        scenario="metered_monitors__with_no_kernel_loop_the_bridge_declines",
        expected={"declined": True, "work_not_run_by_bridge": True},
        observed={"declined": out is None, "work_not_run_by_bridge": ran["n"] == 0},
        oracle="declared (WP-7 no-loop fallback)",
        note="declining cleanly is what keeps every loop-less process byte-identical",
        detail={"loop_was_captured_here": saved is not None},
    )


# ── evals.experiments ────────────────────────────────────────────────────────────

@scenario("evals_experiments__off_refuses_loudly_on_stays_ambient_inert")
def _evals_experiments__off_refuses_loudly_on_stays_ambient_inert() -> Comparison:
    """Off: a grid REFUSES with the flag named — never a silent one-configuration run
    that reads as 'the variant made no difference'. On: ambient traffic is untouched —
    the plane lives in contextvars that default unset, so with no experiment entered
    there are no run-scoped overrides at all."""
    from aughor.evals.runner import run_experiment
    from aughor.kernel.flags import active_flag_overrides, flag_overrides

    with flag_overrides({"evals.experiments": False}):
        try:
            run_experiment("no-such-suite", lambda: (lambda case: None), [])
            refused, msg = False, ""
        except RuntimeError as exc:
            refused, msg = True, str(exc)
        except TypeError as exc:  # signature drift would surface here, loudly
            refused, msg = False, f"signature: {exc}"
    # Ambient traffic never enters the plane: outside any experiment cell (and outside
    # any flag_overrides block) the run-scoped contextvar is unset — the exact state
    # every ordinary request runs in, flag on or off.
    ambient = active_flag_overrides()
    return Comparison(
        scenario="evals_experiments__off_refuses_loudly_on_stays_ambient_inert",
        expected={"refused": True, "names_the_flag": True, "ambient_overrides": {}},
        observed={"refused": refused, "names_the_flag": "evals.experiments" in msg,
                  "ambient_overrides": ambient},
        oracle="declared (E4 inert-plane contract)",
        note="off is a loud refusal; on changes nothing until a run enters the plane",
    )


# ── starters.library ─────────────────────────────────────────────────────────────

@scenario("starters_library__the_payload_is_deterministic_and_declared")
def _starters_library__the_payload_is_deterministic_and_declared() -> Comparison:
    """Same input, same starters — and every starter declares its route (mode) and
    purpose up front, so the surface adds one-click templates, never a model call."""
    from aughor.starters import starter_payload

    a = starter_payload("batch-a-receipt-none", "nope")
    b = starter_payload("batch-a-receipt-none", "nope")
    return Comparison(
        scenario="starters_library__the_payload_is_deterministic_and_declared",
        expected={"deterministic": True, "non_empty": True, "all_declare_routes": True},
        observed={"deterministic": a == b, "non_empty": len(a) > 0,
                  "all_declare_routes": all({"id", "mode", "purpose"} <= set(s) for s in a)},
        oracle="a second identical call",
        note="templates, no model; /suggestions gains a `starters` key and nothing else",
        detail={"starters": [s["id"] for s in a][:6]},
    )


# ── the target, suite and graduation ─────────────────────────────────────────────

def receipt_target() -> Callable[[EvalCase], EvalObservation]:
    """Run the scenario named in ``case.expected["scenario"]``; unknown is an ERROR."""
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown batch-A scenario: {name!r}")
        comparison = fn()
        return EvalObservation(narrative=comparison.note, meta=comparison.to_meta())

    return target


def ensure_suite() -> str:
    """Create the suite (idempotent by name) with one case per scenario; return its id."""
    from aughor.evals import store

    existing = next((s for s in store.list_suites(200) if s["name"] == SUITE_NAME), None)
    if existing is None:
        existing = store.create_suite(
            SUITE_NAME,
            description=("Flag strategy batch A — nine deterministic flags graduate on "
                         "construction-decidable claims: byte-identical or lossless "
                         "transforms (preflight.parallel, deep_analysis.evidence_dedup, "
                         "schema.two_tier_catalog), fail-open cost brakes "
                         "(explore.wandering_detector), additive audit surfaces "
                         "(monitors.guarded, consistency.divergence, starters.library), "
                         "and inert-until-entered planes (ops.metered_monitors, "
                         "evals.experiments). Scenario names carry the flag they back. "
                         "Hermetic: no LLM, no warehouse, stub DBs only."),
            target="flag_batch_a_receipt")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["flag-strategy", "batch-a", n.split("__")[0]]}
            for n in missing
        ])
    return suite_id


def run_suite(*, iterations: int = 1, persist: bool = True):
    """Run every scenario and return the :class:`~aughor.evals.runner.RunSummary`."""
    from aughor.evals import runner
    from aughor.evals.registry import get_evaluator, register_evaluator

    if get_evaluator(DeterministicEquivalenceEvaluator.name) is None:
        register_evaluator(DeterministicEquivalenceEvaluator())

    suite_id = ensure_suite()
    return runner.run_suite(
        suite_id, receipt_target(), iterations=iterations, persist=persist,
        evaluators=[DeterministicEquivalenceEvaluator.name])
