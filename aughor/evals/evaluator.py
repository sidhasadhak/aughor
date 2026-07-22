"""The Evals plane's contract types — ``EvalCase``, ``EvalObservation``, ``EvalScore``, ``Evaluator``.

Wave E2. Mirrors the shape of ``aughor/capability/pipeline.py`` (typed request →
Protocol → typed result) so the two planes read the same way.

**Why this exists.** The guard battery is the product's strongest asset and it
has no common interface: six mutually-incompatible return shapes across ~25
guards — ``list[Finding]``, ``str | None``, ``Finding | None``, ``bool``,
``(sql, receipt)``, ``(ok, reason)``. ``routers/query.py`` hand-projects six of
them into six differently-shaped JSON lists, which is exactly the cost of having
no protocol. One ``Evaluator`` gives every guard the same call signature and the
same result type, without rewriting a single guard.

**Reuses ``trust.Check`` verbatim** as the normalised finding rather than
inventing a parallel vocabulary. ``Verdict.ok``/``blockers``/``warnings``
semantics then apply unchanged, and a receipt, a ``/query/validate`` response and
an eval score all describe a guard outcome with the same words.

**``requires`` drives SKIP, not failure.** A guard that needs a live connection
must not count as failing on a case that has none — that would silently turn
"not applicable" into "broken", which is how a suite starts lying about
coverage. The runner reports skips separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from aughor.trust import BLOCK, Check, Scope

#: What an evaluator can ask a case/observation to provide. A guard whose needs
#: are not met is skipped, never failed.
REQUIREMENTS = ("sql", "conn", "table_cols", "col_types", "rows", "question")


@dataclass
class EvalCase:
    """One test case. ``scope`` is the SAME :class:`aughor.trust.Scope` the guards
    already take, so every existing context requirement is expressible without a
    second context object."""
    id: str = ""
    question: str = ""                                   # NL — grain-intent + LLM judges need it
    artifact: str = ""                                   # the SQL under test
    scope: Scope = field(default_factory=Scope)          # conn / schema / dialect / col_types
    #: table -> columns. Guards disagree on the value type (``fanout`` wants a
    #: list, ``composite_key`` a set); adapters coerce, callers need not care.
    table_cols: Optional[dict[str, Any]] = None
    expected: dict[str, Any] = field(default_factory=dict)   # reference_sql / accept_sql / expect
    tags: tuple[str, ...] = ()


@dataclass
class EvalObservation:
    """What happened when the target ran the case — the ``(result)`` third of
    ``(sql, connection, result)``. Field names mirror ``QueryResult`` so an
    adapter from a real run is a field copy."""
    sql: str = ""                                        # the FINAL sql (post-repair)
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    error: str = ""
    caveats: list[str] = field(default_factory=list)
    narrative: str = ""                                  # finding text, for soundness checks
    meta: dict[str, Any] = field(default_factory=dict)   # tokens, latency, model…


@dataclass
class EvalScore:
    """One evaluator's verdict on one case.

    ``checks`` is a tuple of :class:`aughor.trust.Check` — the same type the
    Trust plane and receipts speak. ``value`` is the 0..1 axis a suite can set an
    objective against; ``skipped`` means the evaluator could not run, which is
    deliberately distinct from ``passed=False``.
    """
    evaluator: str
    passed: bool
    value: float = 0.0
    checks: tuple[Check, ...] = ()
    rationale: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if (not c.ok) and c.severity == BLOCK]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator": self.evaluator,
            "passed": self.passed,
            "value": self.value,
            "skipped": self.skipped,
            "rationale": self.rationale,
            "checks": [
                {"name": c.name, "ok": c.ok, "severity": c.severity,
                 "reason": c.reason, "detail": c.detail}
                for c in self.checks
            ],
            "detail": self.detail,
        }


@runtime_checkable
class Evaluator(Protocol):
    """One check over a case and what the target produced.

    ``name`` is the registry key. ``severity`` is the default weight of the
    Checks it emits (BLOCK fails a Verdict; WARN is advisory). ``requires``
    declares what it cannot run without. ``deterministic`` is False only for
    judge-style evaluators — a suite must be able to separate "our guards said
    so" from "a model said so", because those two claims do not carry the same
    weight.
    """
    name: str
    severity: str
    requires: tuple[str, ...]
    deterministic: bool

    def evaluate(self, case: EvalCase, obs: EvalObservation) -> EvalScore: ...


def available(case: EvalCase, obs: EvalObservation) -> set[str]:
    """What this case/observation can actually supply, for ``requires`` matching."""
    have: set[str] = set()
    if (obs.sql or case.artifact):
        have.add("sql")
    if case.scope is not None and case.scope.conn is not None:
        have.add("conn")
    if case.table_cols:
        have.add("table_cols")
    if case.scope is not None and case.scope.col_types:
        have.add("col_types")
    if obs.rows:
        have.add("rows")
    if case.question:
        have.add("question")
    return have


def sql_of(case: EvalCase, obs: EvalObservation) -> str:
    """The SQL to judge: what actually ran, falling back to what was proposed.

    Order matters — a guard must see the statement that produced the observed
    result, not a pre-repair draft that never executed.
    """
    return (obs.sql or case.artifact or "").strip()
