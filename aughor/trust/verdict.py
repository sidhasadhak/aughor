"""The Trust plane's contract types — `Scope`, `Check`, `Verdict`.

AL-01 of the Part-2 architecture review: the ~9 validation modules
(`sql/{readonly,safety,grain_guard,join_guard,trust_checks}`, `agent/{verify,soma,
sql_consensus}`, `tools/{semantic_validator,sql_consistency}`) are diffused across the
three answer paths, each of which grew a *different subset* of the same safeguards. The
Trust plane hoists them behind one `trust.verify(artifact, scope) -> Verdict` façade so a
capability asks "is this artifact safe?" once and gets one typed answer, instead of
hand-assembling a guard subset per path.

The verdict is deliberately non-throwing and additive: a `block`-severity check that fails
fails the whole `Verdict` (`ok is False`); `warn`/`info` checks are advisory — surfaced to
the caller/planner but never flipping `ok`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# A check's weight. "block" — a hard gate (a failed one fails the Verdict, e.g. a mutating
# statement). "warn" — advisory (fan-out, value-domain, E1 footguns) surfaced but not fatal.
# "info" — a receipt of work done (e.g. a preflight repair that succeeded).
BLOCK = "block"
WARN = "warn"
INFO = "info"


@dataclass(frozen=True)
class Check:
    """One guard's outcome within a Verdict."""
    name: str                                   # guard id: "readonly", "trust_checks", "join_domain", …
    ok: bool                                    # did this check pass?
    severity: str = WARN                        # BLOCK | WARN | INFO
    reason: str = ""                            # human-readable, for the planner / UI
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    """The outcome of verifying one artifact against a scope — the Trust plane's return type.

    `ok` is derived, not stored: a Verdict is *not ok* iff at least one `block`-severity check
    failed. `artifact` is the SQL/code/metadata the caller should actually use downstream — it
    equals the input unless a guard repaired it (then `repaired is True` and `original` holds
    the input)."""
    kind: str                                   # "sql" | "code" | "metadata"
    artifact: str                               # the (possibly repaired) artifact to use
    checks: tuple[Check, ...] = ()
    repaired: bool = False
    original: str = ""                          # the input artifact, set only when repaired

    @property
    def ok(self) -> bool:
        return not any((not c.ok) and c.severity == BLOCK for c in self.checks)

    @property
    def blockers(self) -> list[Check]:
        """Failed hard-gate checks — the reasons `ok` is False."""
        return [c for c in self.checks if (not c.ok) and c.severity == BLOCK]

    @property
    def warnings(self) -> list[Check]:
        """Failed advisory checks — surfaced to the planner, not fatal."""
        return [c for c in self.checks if (not c.ok) and c.severity == WARN]

    @property
    def reason(self) -> str:
        """The first blocker's reason (empty when `ok`)."""
        b = self.blockers
        return b[0].reason if b else ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe projection, including the derived `ok`/`reason`.

        Three call sites hand-projected this in three shapes (`routers/query.py`,
        the MLflow scorers, the capability result), so "what a verdict looks like
        over the wire" depended on which door you came through. `ok` and `reason`
        are computed properties and would otherwise be dropped by a naive
        `asdict`, which is exactly the field a consumer most wants."""
        return {
            "kind": self.kind,
            "ok": self.ok,
            "reason": self.reason,
            "artifact": self.artifact,
            "repaired": self.repaired,
            "original": self.original,
            "checks": [
                {"name": c.name, "ok": c.ok, "severity": c.severity,
                 "reason": c.reason, "detail": c.detail}
                for c in self.checks
            ],
        }


@dataclass
class Scope:
    """The context a guard needs, bundled once. Every field is optional so the pure guards
    (readonly, E1 trust-checks) run with a bare `Scope()`; the probe/repair guards
    (preflight, join value-domain, grain fan-out) run only when a live `conn` is present."""
    conn: Any = None                            # a live DatabaseConnection for probe/repair guards
    schema: str | None = None                   # rendered schema string (for identifier repair)
    question: str | None = None                 # the NL question (for semantic alignment — future)
    dialect: str = "duckdb"
    col_types: dict[str, str] | None = None     # "table.col" -> type, for E1 date-boundary checks
