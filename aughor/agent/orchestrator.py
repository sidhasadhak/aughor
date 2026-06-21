"""The Orchestrator — makes the Analyst's phase autonomy *legible* and reconciles
findings across phases into a typed report.

Two responsibilities, both deterministic by design:

1. **Phase plan (decompose).** Today ADA's phase path is emergent: each router gate
   (``route_after_baseline`` …) decides the next node from one runtime signal. That is
   correct but invisible — there is no declared "here is what I intend to run". The
   Orchestrator derives, at intake, the SAME plan those deterministic routers will
   execute (from the question shape + intake spec) and journals it as a plan of record.
   The routers stay the executors and the safety net; this only adds the declaration.

2. **Cross-phase ContradictionReport.** The synthesis step already scans phase summaries
   for factual contradictions, but as a throwaway prompt string. This module returns a
   *typed* ``ContradictionReport`` so the tension is a first-class artifact the Trust
   Receipt and the report can carry — while ``to_prompt_section()`` reproduces the exact
   string the synthesizer used before, so behaviour is byte-stable.

DESIGN NOTE — why deterministic, not an LLM Orchestrator. The R4 ablation
(``docs/R4_ABLATION_EVAL_2026-06-21.md``) showed the deterministic guards are the trust
moat and that injecting LLM-derived context into the decision path *regresses*. So the
Orchestrator does not *decide* phases with a model — it mirrors the deterministic gates
and makes them visible. Legibility without drift.

Pure and dependency-free: every function here is safe to call repeatedly and never
touches the network or the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Phase plan ─────────────────────────────────────────────────────────────────

# disposition: how confident the plan is that a step runs.
#   "planned"     — will run (entry phase, or a phase the question forces)
#   "conditional" — runtime-gated; runs unless a deterministic gate stops it
#   "gated_off"   — current signals say skip (a safety net could still run it)
_DISPOSITIONS = ("planned", "conditional", "gated_off")


@dataclass
class PhaseStep:
    """One declared step in the Analyst's intended phase path."""
    phase_id: str
    phase_name: str
    icon: str
    disposition: str          # one of _DISPOSITIONS
    reason: str

    def to_dict(self) -> dict:
        return {"phase_id": self.phase_id, "phase_name": self.phase_name,
                "icon": self.icon, "disposition": self.disposition, "reason": self.reason}


@dataclass
class OrchestrationPlan:
    """The Analyst's declared phase path — derived deterministically at intake."""
    question_kind: str               # "temporal" | "cross_sectional"
    steps: list = field(default_factory=list)   # list[PhaseStep]

    @property
    def planned_ids(self) -> list:
        """Phase ids expected to run (planned or conditional, not gated_off)."""
        return [s.phase_id for s in self.steps if s.disposition != "gated_off"]

    def to_dict(self) -> dict:
        return {"question_kind": self.question_kind,
                "steps": [s.to_dict() for s in self.steps],
                "planned_ids": self.planned_ids}

    def summary(self) -> str:
        """One-line declaration for the journal / Fleet view."""
        order = " → ".join(s.phase_id for s in self.steps if s.disposition != "gated_off")
        off = [s.phase_id for s in self.steps if s.disposition == "gated_off"]
        line = f"[{self.question_kind}] {order}"
        return line + (f"  (skipping {', '.join(off)})" if off else "")


# Phase metadata mirrors the phase nodes in investigate.py (kept in sync deliberately —
# these are the same five analysis phases + the two book-ends).
_PHASE_META = {
    "intake":        ("Question Intake", "🔍"),
    "baseline":      ("Baseline & Anomaly Assessment", "📊"),
    "decomposition": ("Metric Decomposition", "🧩"),
    "dimensional":   ("Dimensional Attribution", "🔬"),
    "behavioral":    ("Behavioral & Operational Diagnostics", "👥"),
    "cross_section": ("Cross-Sectional Weakness Scan", "🧭"),
    "synthesis":     ("Synthesis", "📋"),
}


def _step(phase_id: str, disposition: str, reason: str) -> PhaseStep:
    name, icon = _PHASE_META.get(phase_id, (phase_id.title(), "•"))
    return PhaseStep(phase_id, name, icon, disposition, reason)


def plan_phases(*, question: str, cross_sectional: bool,
                dimension_ask: bool, behavioral: bool) -> OrchestrationPlan:
    """Declare the phase path the deterministic routers will execute.

    Mirrors ``route_after_intake/baseline/decompose/dimensional`` in investigate.py —
    intentionally, so the declaration can never disagree with what actually runs. The
    booleans are exactly the signals those routers key on (computed by the caller with
    the same predicates), so this stays a pure, faithful mirror, not a second opinion.
    """
    # Cross-sectional / diagnostic questions skip the temporal battery entirely.
    if cross_sectional:
        return OrchestrationPlan(
            question_kind="cross_sectional",
            steps=[
                _step("intake", "planned", "parse the question into a metric + dimensions"),
                _step("cross_section", "planned",
                      "no usable time axis — scan dimensions for where value is weakest"),
                _step("synthesis", "planned", "assemble the diagnostic report"),
            ],
        )

    # Temporal path. decompose/dimensional/behavioral are runtime-gated; the only ones
    # the plan can promise are intake, baseline and synthesis. A dimension question forces
    # the breakdown phases; a behavioral question forces the behavioral phase.
    steps = [
        _step("intake", "planned", "parse the question into a metric + comparison window"),
        _step("baseline", "planned", "measure the change vs the comparison period; test significance"),
    ]
    if dimension_ask:
        steps.append(_step("decomposition", "planned",
                           "the question names a dimension — split the metric to set it up"))
        steps.append(_step("dimensional", "planned",
                           "attribute the change across the dimension the question asked about"))
    else:
        steps.append(_step("decomposition", "conditional",
                           "runs unless the baseline change is within normal variance"))
        steps.append(_step("dimensional", "conditional",
                           "runs if the anomaly is large (≥3σ) or decomposition is inconclusive"))
    if behavioral:
        steps.append(_step("behavioral", "planned",
                           "the question asks about behaviour (churn/refunds/retention)"))
    else:
        steps.append(_step("behavioral", "gated_off",
                           "no behavioural signal in the question — skipped to avoid noise"))
    steps.append(_step("synthesis", "planned", "assemble the attribution report"))
    return OrchestrationPlan(question_kind="temporal", steps=steps)


def reconcile(planned_ids: Any, actual_phase_ids: Any) -> dict:
    """Close the loop: which planned phases actually ran, which were skipped, and any
    that ran unplanned. Journaled at synthesis so planned-vs-actual is legible. Takes the
    declared ``planned_ids`` (from ``OrchestrationPlan.planned_ids`` or its serialized
    dict) so it round-trips cleanly through state."""
    planned = set(planned_ids or [])
    actual = set(actual_phase_ids or [])
    return {
        "planned": sorted(planned),
        "actual": sorted(actual),
        "skipped": sorted(planned - actual),     # planned but a gate stopped it
        "unplanned": sorted(actual - planned),   # ran without being declared (should be rare)
    }


# ── Cross-phase contradictions (typed) ───────────────────────────────────────────

@dataclass
class Contradiction:
    """One factual tension between two or more phase summaries."""
    kind: str          # "significance_flip" | "direction_flip"
    detail: str        # the resolve-this instruction (byte-identical to the legacy string)
    phases: list = field(default_factory=list)   # phase names involved
    severity: str = "high"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail,
                "phases": self.phases, "severity": self.severity}


@dataclass
class ContradictionReport:
    """Typed cross-phase consistency verdict. Carries the same instructions the
    synthesizer used to receive as a raw string — now also a first-class artifact."""
    items: list = field(default_factory=list)   # list[Contradiction]

    @property
    def has_contradictions(self) -> bool:
        return bool(self.items)

    @property
    def severity(self) -> str:
        return "high" if self.items else "none"

    def to_dict(self) -> dict:
        return {"severity": self.severity, "count": len(self.items),
                "items": [c.to_dict() for c in self.items]}

    def to_prompt_section(self) -> str:
        """Reproduce — byte-for-byte — the section the legacy ``_detect_phase_contradictions``
        injected before synthesis, so wiring this in changes nothing the model sees."""
        if not self.items:
            return ""
        lines = [
            "\n⚠ CROSS-PHASE CONTRADICTIONS DETECTED — address each explicitly in your report "
            "(surface them in the risks or data quality notes; do NOT silently average them out):"
        ]
        for i, c in enumerate(self.items, 1):
            lines.append(f"  {i}. {c.detail}")
        lines.append("")
        return "\n".join(lines)


_SIG_POSITIVE = re.compile(
    r'\b(significant|anomal|unusual|notable|material|above.normal|outside.normal)\b')
_SIG_NEGATIVE = re.compile(
    r'\b(within.normal|no.anomal|not.significant|insignificant|expected.variance|'
    r'consistent.with.historical|normal.variance|no.significant)\b')
_METRIC_RE = re.compile(
    r'\b(revenue|orders|conversion|churn|retention|aov|gmv|mrr|sessions|'
    r'traffic|cac|ltv|profit|margin|spend|cost)\b')
_DIRECTION_UP = re.compile(r'\b(increas|grew|up|higher|gain|improv|recover|surged)\b')
_DIRECTION_DOWN = re.compile(r'\b(declin|decreas|fell|drop|down|lower|reduc|shrunk|worsened)\b')


def detect_contradictions(phases: Any) -> ContradictionReport:
    """Deterministically scan phase summaries for direct factual contradictions, as a
    typed report. Same two detection classes the legacy string scanner used:

      A. Significance flip — one phase calls the change significant/anomalous while
         another calls it within normal variance.
      B. Direction flip — one phase says a metric is up, another says it is down.

    Never raises — returns an empty report on any error."""
    report = ContradictionReport()
    try:
        if not phases or len(phases) < 2:
            return report
        summaries = [(p.get("phase_name", ""), (p.get("summary") or "").lower()) for p in phases]

        # ── Class A: significance flip ──────────────────────────────────────────
        sig = [n for n, s in summaries if _SIG_POSITIVE.search(s)]
        neg = [n for n, s in summaries if _SIG_NEGATIVE.search(s)]
        if sig and neg:
            report.items.append(Contradiction(
                kind="significance_flip",
                detail=(
                    f"Significance contradiction: phase(s) {', '.join(sig)} "
                    f"describe the change as significant/anomalous, but phase(s) "
                    f"{', '.join(neg)} describe it as within normal variance. "
                    f"You MUST resolve this tension explicitly in your report — do NOT paper over it."
                ),
                phases=list(dict.fromkeys(sig + neg)),
            ))

        # ── Class B: direction flip on the same metric keyword ──────────────────
        metric_directions: dict = {}
        for name, s in summaries:
            for m in _METRIC_RE.finditer(s):
                metric = m.group(1)
                ctx = s[max(0, m.start() - 80):min(len(s), m.end() + 80)]
                if _DIRECTION_UP.search(ctx):
                    metric_directions.setdefault(metric, {}).setdefault("up", []).append(name)
                elif _DIRECTION_DOWN.search(ctx):
                    metric_directions.setdefault(metric, {}).setdefault("down", []).append(name)
        for metric, dirs in metric_directions.items():
            if "up" in dirs and "down" in dirs:
                report.items.append(Contradiction(
                    kind="direction_flip",
                    detail=(
                        f"Direction contradiction on '{metric}': "
                        f"phase(s) {', '.join(dirs['up'])} describe it as increasing, "
                        f"phase(s) {', '.join(dirs['down'])} describe it as decreasing. "
                        f"Clarify which direction is correct and over what time period."
                    ),
                    phases=list(dict.fromkeys(dirs["up"] + dirs["down"])),
                ))
        return report
    except Exception:
        return ContradictionReport()
