"""The probe bridge — a live connection as the callable the guards ask for.

Several guards take a ``probe_fn`` rather than a connection so they stay
backend-agnostic (``grain_guard.detect_fanout`` names an offline harness as a
first-class caller in its own docstring). The closure that adapts a connection to
that signature had been hand-rolled in three places —
``trust/__init__.py``, ``routers/query.py``, and a since-deleted coverage
script — which is two copies too many for four lines that must agree.
"""
from __future__ import annotations

from typing import Any, Callable

#: ``probe(sql) -> (ok, rows, error)`` — what the probe-taking guards expect.
ProbeFn = Callable[[str], tuple]


def probe_fn_for(conn: Any, label: str = "__eval_probe__") -> ProbeFn:
    """Adapt a connection to the guards' probe signature.

    Duck-typed on ``conn.execute(label, sql)``, which is all the guards ever use
    — any of the registered connectors, or a stub, works. Errors are returned
    rather than raised: a probe that cannot answer must leave the guard free to
    decline, not abort the evaluation.
    """
    def probe(sql: str) -> tuple:
        try:
            result = conn.execute(label, sql)
        except Exception as exc:
            return (False, [], str(exc))
        return (not result.error, result.rows or [], result.error or "")
    return probe
