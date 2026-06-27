"""Instruments (Bet 7) — experts that bring governed analytical tools beyond SQL.

A specialist may ship instruments (a survival model, a forecaster, a tuned anomaly detector)
as DECLARATIVE, capability-gated tools — never arbitrary code, mirroring how the Inference
Plane vends LLM access. An instrument can only run when its required capability is granted, so
the deterministic-SQL correctness story (and the no-arbitrary-code non-goal) is preserved.
Pure; never raises.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Instrument:
    name: str
    method: str                 # e.g. "kaplan_meier" | "ets_forecast" | "stl_anomaly"
    required_capability: str     # capability that must be granted to invoke it
    assumptions: str = ""        # shown inline with the result for honesty


def can_invoke(instrument: Instrument, granted_capabilities: set) -> bool:
    """An instrument runs only if its required capability is in the granted set."""
    return instrument.required_capability in (granted_capabilities or set())
