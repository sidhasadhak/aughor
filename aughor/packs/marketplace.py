"""Marketplace (Bet 6) — portable expertise that re-grounds on import.

Because a pack ships zero table names, a community/consultant pack can light up on any
warehouse via the resolver. The safety rule: an imported pack is INERT until it re-validates,
re-binds, and re-evals on the LOCAL warehouse — never trusted on the author's word. This is the
import-readiness gate (composition of validate + bind + eval gates). Pure; never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportReadiness:
    ready: bool = False                       # may the imported pack be activated locally?
    blockers: list[str] = field(default_factory=list)


def import_readiness(
    validation_ok: bool,
    fully_bound: bool,
    evals_passed: bool,
) -> ImportReadiness:
    """Decide whether an imported pack may activate on THIS warehouse. All three must hold:
    it validates, every role binds, and its evals pass locally."""
    blockers: list[str] = []
    if not validation_ok:
        blockers.append("pack fails static validation")
    if not fully_bound:
        blockers.append("not every role binds on this warehouse")
    if not evals_passed:
        blockers.append("evals do not pass on this warehouse")
    return ImportReadiness(ready=not blockers, blockers=blockers)
