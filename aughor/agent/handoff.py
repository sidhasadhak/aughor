"""Typed hand-off contracts for the ADA specialist agents (Phase 2).

Within an Analyst investigation, each phase already runs a three-specialist
micro-cycle: **SQL-Engineer** (plan + grounded SQL + repair) → **Verifier**
(fan-out / trust guards) → **Narrator** (interpret the evidence into findings).
Today those hand-offs are implicit local variables inside ``run_analysis_phase``.

This module makes each hand-off an explicit *typed contract* and journals it as an
``agent.handoff`` event, so the collaboration is legible in the Fleet view and the
Trust Receipt — *without changing the pipeline's logic*. It is additive and
fail-open: a journaling error never touches the investigation.

The deeper structural split (a standalone Verifier node, immutable premise
correction) is a deliberate follow-up; this is the safe, legible foundation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class EngineeredQuery:
    """One query the SQL-Engineer planned, grounded, and executed."""
    title: str
    sql: str
    row_count: int
    error: Optional[str] = None
    error_class: Optional[str] = None   # R3 typed class (parser|binder|semantic|runtime) if it errored


@dataclass
class SqlEngineerHandoff:
    """SQL-Engineer → Verifier: the executed queries for a phase."""
    phase_id: str
    queries: list = field(default_factory=list)   # list[EngineeredQuery]

    @property
    def ok_count(self) -> int:
        return sum(1 for q in self.queries if not q.error)

    def summary(self) -> dict:
        return {"queries": len(self.queries), "ok": self.ok_count,
                "rows": sum(q.row_count for q in self.queries)}


@dataclass
class VerifierHandoff:
    """Verifier → Narrator: the trust verdict over the engineered queries."""
    phase_id: str
    query_count: int
    caveats: list = field(default_factory=list)   # list[str]
    passed: bool = True
    error_classes: list = field(default_factory=list)   # R3 typed classes of any failed queries

    def summary(self) -> dict:
        return {"queries": self.query_count, "caveats": self.caveats, "passed": self.passed,
                "error_classes": self.error_classes}


@dataclass
class NarratorHandoff:
    """Narrator → Orchestrator (Analyst): the findings the phase produced."""
    phase_id: str
    finding_count: int

    def summary(self) -> dict:
        return {"findings": self.finding_count}


def emit_handoff(from_agent: str, to_agent: str, phase_id: str, payload: dict,
                 *, conn_id: Optional[str] = None) -> None:
    """Journal one agent→agent hand-off. Fail-open — never raises into the run."""
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.kernel.jobs import current_job_id
        Ledger.default().emit(
            "agent.handoff",
            {"from": from_agent, "to": to_agent, "phase": phase_id, **payload},
            conn_id=conn_id, job_id=current_job_id(),
        )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent handoff journal", counter="handoff")


def journal_phase_handoffs(phase_id: str, *, plan: Any, results: Any,
                           fanout_caveat: Optional[str], interpretation: Any,
                           conn_id: Optional[str] = None, dialect: str = "duckdb") -> None:
    """Build + journal the SQL-Engineer → Verifier → Narrator hand-offs for one ADA
    phase, from the data ``run_analysis_phase`` already has. The Verifier gives each
    failed query its R3 typed class (``parser|binder|semantic|runtime``) so the repair
    signal is legible in the Fleet view / Trust Receipt. Additive; fail-open."""
    try:
        from aughor.agent.verifier import Verifier
        # title → typed error class for the queries that failed (R3).
        cls_by_title = dict(Verifier.classify_failures(results, dialect))
        eq = [
            EngineeredQuery(
                title=getattr(q, "title", "") or "",
                sql=getattr(r, "sql", "") or "",
                row_count=int(getattr(r, "row_count", 0) or 0),
                error=getattr(r, "error", None),
                error_class=cls_by_title.get(getattr(q, "title", "") or "") if getattr(r, "error", None) else None,
            )
            for (q, r) in (results or [])
        ]
        se = SqlEngineerHandoff(phase_id, eq)
        caveats = [c for c in [fanout_caveat] if c]
        error_classes = list(dict.fromkeys(q.error_class for q in eq if q.error_class))
        ve = VerifierHandoff(phase_id, len(eq), caveats, passed=se.ok_count > 0, error_classes=error_classes)
        findings = len(getattr(interpretation, "findings", []) or []) if interpretation else 0
        na = NarratorHandoff(phase_id, findings)
        emit_handoff("sql_engineer", "verifier", phase_id, se.summary(), conn_id=conn_id)
        emit_handoff("verifier", "narrator", phase_id, ve.summary(), conn_id=conn_id)
        emit_handoff("narrator", "analyst", phase_id, na.summary(), conn_id=conn_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "phase handoffs journal", counter="handoff")
