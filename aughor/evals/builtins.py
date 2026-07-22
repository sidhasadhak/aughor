"""The built-in evaluator set — the deterministic guard battery, registered.

Every entry DELEGATES to a guard that already exists and is already tested. This
module contributes no detection logic of its own: that is the point. The guards
are the product's strongest correctness asset, and the value here is giving them
one call signature, not second-guessing them.

Composition mirrors ``capability/builtins.py``: a table of registrations plus an
idempotent ``register_builtins()``.
"""
from __future__ import annotations

from aughor.evals.adapters import (
    HintEvaluator,
    ListFindingEvaluator,
    OkReasonEvaluator,
    OptionalFindingEvaluator,
    PredicateEvaluator,
    conn_sql,
    sql_dialect,
    sql_only,
    sql_tablecols_dialect,
)
from aughor.evals.evaluator import EvalCase, EvalObservation, sql_of
from aughor.evals.registry import register_evaluator
from aughor.trust import BLOCK, WARN


# ── argument builders needing more than the shared ones ───────────────────────

def _trust_checks_args(case: EvalCase, obs: EvalObservation):
    return (sql_of(case, obs),), {"col_types": case.scope.col_types,
                                  "dialect": case.scope.dialect}


def _composite_key_args(case: EvalCase, obs: EvalObservation):
    """``composite_key`` wants SET-valued columns while ``fanout`` wants lists —
    two guards, two conventions, one trap. Coerce here so a caller never has to
    know which guard it is feeding."""
    cols = {k: set(v) for k, v in (case.table_cols or {}).items()}
    return (sql_of(case, obs), cols), {"dialect": case.scope.dialect}


def _grain_fanout_args(case: EvalCase, obs: EvalObservation):
    from aughor.evals.probe import probe_fn_for
    return (sql_of(case, obs), probe_fn_for(case.scope.conn)), {
        "dialect": case.scope.dialect}


def _capability_args(case: EvalCase, obs: EvalObservation):
    return (sql_of(case, obs), case.scope.dialect), {}


def _lint_args(case: EvalCase, obs: EvalObservation):
    return (sql_of(case, obs),), {"dialect": case.scope.dialect}


def _grain_intent_args(case: EvalCase, obs: EvalObservation):
    return (case.question, obs.row_count), {"columns_in_scope": tuple(obs.columns or ())}


def _insight_args(case: EvalCase, obs: EvalObservation):
    return (obs.rows,), {"finding_text": obs.narrative, "sql": sql_of(case, obs),
                         "conn": case.scope.conn, "columns": obs.columns or None}


def register_builtins() -> None:
    """Register the deterministic set. Idempotent — registration is by name."""
    from aughor.sql import (
        capability_check,
        composite_key,
        fanout,
        grain_guard,
        join_guard,
        lint,
        readonly,
        trust_checks,
    )

    # ── BLOCK: the hard gates ────────────────────────────────────────────────
    register_evaluator(PredicateEvaluator(
        "guard.readonly", readonly.is_mutating, args=sql_dialect, severity=BLOCK,
        reason="statement mutates data — the answer path is read-only"))
    register_evaluator(PredicateEvaluator(
        "guard.disallowed_functions", readonly.disallowed_functions, args=sql_dialect,
        severity=BLOCK, reason="statement calls a disallowed function"))

    # ── WARN, pure: no connection needed ─────────────────────────────────────
    register_evaluator(ListFindingEvaluator(
        "guard.e1_semantics", trust_checks.run_trust_checks, args=_trust_checks_args))
    register_evaluator(ListFindingEvaluator(
        "guard.lint", lint.lint, args=_lint_args))
    register_evaluator(HintEvaluator(
        "guard.capability_contract", capability_check.capability_diagnostics,
        args=_capability_args))

    # The fan-out family — the dominant wrong-number class (E2 in the CIDR
    # taxonomy), and the reason this battery exists at all.
    for name, fn in (
        ("guard.chasm_sum", fanout.sum_over_chasm_fanout),
        ("guard.chasm_avg", fanout.avg_over_chasm_fanout),
        ("guard.chasm_count", fanout.count_star_chasm_fanout),
        ("guard.join_key_fanout", fanout.join_key_fanout),
        ("guard.id_arithmetic", fanout.measure_times_key_arithmetic),
        ("guard.avg_of_row_ratios", fanout.avg_of_row_ratios),
        ("guard.cte_grain_mismatch", fanout.cte_grain_mismatch_fanout),
        ("guard.groupby_continuous", fanout.group_by_continuous_measure),
    ):
        register_evaluator(HintEvaluator(name, fn, args=sql_tablecols_dialect))

    for name, fn in (
        ("guard.count_ratio_distinct", fanout.count_ratio_distinct_risk),
        ("guard.count_distinct_variant", fanout.count_distinct_variant),
        ("guard.self_ratio_tautology", fanout.self_ratio_tautology),
    ):
        register_evaluator(HintEvaluator(name, fn, args=sql_dialect))

    # Takes no dialect — registering it with the others silently skipped it on
    # every case (TypeError → tolerated → looks exactly like "found nothing").
    # test_no_evaluator_skips_on_a_signature_error now makes that class loud.
    register_evaluator(HintEvaluator(
        "guard.integer_division", fanout.integer_division_risk, args=sql_only))

    register_evaluator(HintEvaluator(
        "guard.count_star_entity_fanout", fanout.count_star_entity_fanout,
        args=lambda c, o: ((sql_of(c, o),), {"table_cols": {
            k: list(v) for k, v in (c.table_cols or {}).items()} or None})))
    register_evaluator(OptionalFindingEvaluator(
        "guard.dim_ratio_chasm", fanout.dimension_ratio_chasm,
        args=sql_tablecols_dialect))
    register_evaluator(ListFindingEvaluator(
        "guard.partial_composite_key", composite_key.detect_partial_keys,
        args=_composite_key_args, requires=("sql", "table_cols")))

    # ── WARN, probe: needs a live connection ─────────────────────────────────
    register_evaluator(ListFindingEvaluator(
        "guard.join_value_domain", join_guard.check_join_value_domains,
        args=conn_sql, requires=("sql", "conn")))
    register_evaluator(ListFindingEvaluator(
        "guard.filter_value_domain", join_guard.check_filter_value_domains,
        args=conn_sql, requires=("sql", "conn")))
    register_evaluator(HintEvaluator(
        "guard.join_coverage", join_guard.check_join_coverage,
        args=conn_sql, requires=("sql", "conn")))
    register_evaluator(ListFindingEvaluator(
        "guard.grain_fanout", grain_guard.detect_fanout,
        args=_grain_fanout_args, requires=("sql", "conn")))

    # ── WARN, result-shaped: judges the OUTPUT, not the statement ────────────
    from aughor.explorer import verify as _explorer_verify
    from aughor.sql import grain_intent

    register_evaluator(HintEvaluator(
        "guard.result_grain_intent", grain_intent.check_result_grain,
        args=_grain_intent_args, requires=("sql", "question"), severity=WARN))
    register_evaluator(OkReasonEvaluator(
        "guard.insight_soundness", _explorer_verify.verify_insight,
        args=_insight_args, requires=("sql", "rows")))
