"""Runners — how a NON-HTTP caller runs a first-class piece of work.

A runner is not a second way to do the work. It is the small amount of glue a caller
without a request needs — build the request the one door already takes, pre-check what
that door would only raise about later, submit it as a supervised kernel job, and report
back what actually happened. The work itself stays where it was.

The package exists for a structural reason (Wave H5). Two packages need to start an
investigation and neither may own it: :mod:`aughor.automations` (a scheduled effect) and
:mod:`aughor.actions` (a declared ``trigger_investigation`` side effect). While the drain
lived inside ``automations/engine.py``, wiring kinetic to it would have made K import A —
inverting the wave dependency, since A already routes its ``kinetic_action`` effect
through K's executor. A module that imports neither makes both callers peers.
"""
from aughor.runners.investigation import (
    InvestigationRequest,
    InvestigationRun,
    refusal_for,
    run_investigation,
)

__all__ = [
    "InvestigationRequest",
    "InvestigationRun",
    "refusal_for",
    "run_investigation",
]
