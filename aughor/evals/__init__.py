"""The Evals plane — one protocol over the deterministic guard battery (Wave E2).

NOTE ON NAMING: this is ``aughor.evals`` — product code, importable from an
installed wheel. The repo-root ``evals/`` directory is the offline benchmark
harness (Spider, golden-SQL, ratchet), is not packaged, and is unrelated. Import
paths are the reliable tell: ``from aughor.evals import …`` here,
``from evals import …`` there.

Usage::

    from aughor.evals import EvalCase, EvalObservation, run_all
    from aughor.trust import Scope

    case = EvalCase(artifact=sql, scope=Scope(conn=db, dialect="duckdb"))
    obs  = EvalObservation(sql=sql, rows=rows, row_count=len(rows))
    scores = run_all(case, obs)
    failed = [s for s in scores if not s.passed and not s.skipped]

Built-ins register at import so the library works out of the box, matching
``aughor/capability/__init__.py``.
"""
from __future__ import annotations

from aughor.evals.builtins import register_builtins
from aughor.evals.evaluator import (
    REQUIREMENTS,
    EvalCase,
    EvalObservation,
    EvalScore,
    Evaluator,
    available,
    sql_of,
)
from aughor.evals.probe import ProbeFn, probe_fn_for
from aughor.evals.registry import (
    clear,
    deterministic_evaluators,
    get_evaluator,
    register_evaluator,
    registered_evaluators,
    run_all,
    run_evaluator,
)

register_builtins()

__all__ = [
    "REQUIREMENTS", "EvalCase", "EvalObservation", "EvalScore", "Evaluator",
    "ProbeFn", "available", "clear", "deterministic_evaluators", "get_evaluator",
    "probe_fn_for", "register_builtins", "register_evaluator",
    "registered_evaluators", "run_all", "run_evaluator", "sql_of",
]
