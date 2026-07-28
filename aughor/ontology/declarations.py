"""Wave O6 — declared exclusions, coverage, and checking the promises the ontology makes.

**The marketing line, and it is earned by one function.** Genie's own documentation states
that a wrong cardinality declaration silently corrupts results. It *documents* the hazard.
This module **checks the promise**: a declared cardinality, grain or active-filter is
re-validated by a cheap probe, and a violated declaration flips the edge to `dirty` in V's
freshness vocabulary and surfaces as a caveat rather than sitting there being quietly
wrong. Measured-over-declared is J14, and this is where it is enforced against our own
declarations rather than someone else's data.

**Unmapped is not out-of-scope.** A table nobody has curated and a table deliberately
excluded look identical in a coverage number, and treating them alike produces the two
worst outcomes at once: a green dashboard hiding real gaps, and endless nagging about
tables nobody will ever map. A declared exclusion carries a REASON, so coverage can
distinguish "we decided not to" from "nobody has yet".

**No fifth freshness state.** Wave C3 defined `fresh|dirty|stale|unknown`, Wave V lifted
it platform-wide, and Wave N3 already refused to add a fifth state — it added an
orthogonal axis instead. A violated declaration is `dirty`: the structure still matches,
what the data *promised about itself* no longer holds. A test pins the vocabulary.

Deterministic; the probes are bounded aggregates, never scans, and there is no model call
anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: Why a table is out of scope. Free text would make coverage un-aggregatable, and
#: "other" with a note is better than a taxonomy nobody fits.
EXCLUSION_REASONS: tuple[str, ...] = (
    "system_table",      # framework/internal plumbing
    "deprecated",        # superseded, kept for history
    "out_of_domain",     # real data, not this connection's subject
    "sensitive",         # deliberately not curated for analysis
    "other",
)

#: Coverage bands for the per-connection rollup.
GREEN, ORANGE, RED = "green", "orange", "red"


@dataclass(frozen=True)
class Exclusion:
    """A table declared out of scope, with the reason that makes coverage honest."""

    table: str
    reason: str
    note: str = ""
    declared_by: str = ""

    def to_dict(self) -> dict:
        return {"table": self.table, "reason": self.reason, "note": self.note,
                "declared_by": self.declared_by}


@dataclass
class Coverage:
    """How much of a connection is actually curated, with excluded tables set aside."""

    total: int = 0
    mapped: int = 0
    excluded: int = 0

    @property
    def in_scope(self) -> int:
        """Tables that COULD be mapped — the honest denominator."""
        return max(0, self.total - self.excluded)

    @property
    def share(self) -> float:
        return round(self.mapped / self.in_scope, 3) if self.in_scope else 1.0

    @property
    def band(self) -> str:
        s = self.share
        return GREEN if s >= 0.8 else (ORANGE if s >= 0.4 else RED)

    def to_dict(self) -> dict:
        return {"total": self.total, "mapped": self.mapped, "excluded": self.excluded,
                "in_scope": self.in_scope, "share": self.share, "band": self.band}


def coverage(all_tables: Iterable[str], mapped_tables: Iterable[str],
             exclusions: Iterable[Exclusion]) -> Coverage:
    """Coverage with declared exclusions removed from the denominator.

    Counting an excluded table as unmapped is what makes a coverage number useless: it
    nags forever about tables nobody will map, and a team that learns to ignore the number
    also ignores the real gaps in it.
    """
    all_set = {str(t).split(".")[-1].lower() for t in all_tables if str(t).strip()}
    mapped = {str(t).split(".")[-1].lower() for t in mapped_tables} & all_set
    excluded = {e.table.split(".")[-1].lower() for e in exclusions} & all_set
    # An excluded table that somebody mapped anyway is still mapped — the exclusion says
    # "not required", never "not allowed".
    return Coverage(total=len(all_set), mapped=len(mapped - (excluded - mapped)),
                    excluded=len(excluded - mapped))


# ── declaration checks ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Declaration:
    """A promise the ontology makes about a table, which O6 re-validates."""

    table: str
    kind: str                       # "cardinality" | "grain" | "active_filter"
    expected: str                   # e.g. "one_to_many", "one row per order_id", a filter
    column: str = ""

    def to_dict(self) -> dict:
        return {"table": self.table, "kind": self.kind, "expected": self.expected,
                "column": self.column}


@dataclass
class CheckResult:
    """Whether a promise still holds, in V's vocabulary."""

    declaration: Declaration
    state: str                      # fresh | dirty | unknown
    observed: str = ""
    detail: str = ""

    @property
    def violated(self) -> bool:
        return self.state == "dirty"

    def caveat(self) -> str:
        """The sentence that rides an answer over this table. Empty unless violated."""
        if not self.violated:
            return ""
        d = self.declaration
        return (f"`{d.table}` declares {d.kind} {d.expected!r} and the data no longer "
                f"matches ({self.observed}). Results grouped on that assumption may be "
                f"wrong.")

    def to_dict(self) -> dict:
        return {**self.declaration.to_dict(), "state": self.state,
                "observed": self.observed, "detail": self.detail,
                "violated": self.violated, "caveat": self.caveat()}


#: A probe returns (observed, ok) or raises. Injected so the checks are testable without
#: a warehouse and so the SQL lives with the connector, not here.
Probe = Callable[[Declaration], tuple[str, bool]]


def check_declaration(decl: Declaration, probe: Probe) -> CheckResult:
    """Re-validate one declaration.

    A probe that CANNOT answer yields ``unknown``, never ``fresh``. That distinction is
    the whole point: "we checked and it holds" and "we could not check" are different
    facts, and collapsing them is how a green board comes to mean nothing. It is the same
    refusal N3 made when an unreadable ontology marked nothing stale.
    """
    try:
        observed, ok = probe(decl)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "a declaration probe that cannot run reports unknown, never fresh",
                 counter="ontology.declaration_probe")
        return CheckResult(declaration=decl, state="unknown",
                           detail=f"probe failed: {type(exc).__name__}")
    if ok:
        return CheckResult(declaration=decl, state="fresh", observed=observed)
    return CheckResult(declaration=decl, state="dirty", observed=observed,
                       detail="the declared promise no longer holds")


def check_all(declarations: Iterable[Declaration], probe: Probe) -> list[CheckResult]:
    return [check_declaration(d, probe) for d in declarations]


def caveats_for_tables(results: Iterable[CheckResult],
                       tables: Iterable[str]) -> list[str]:
    """The caveats that apply to an answer touching ``tables``.

    Q4 will render these on answers; O6's job is to produce them and to make sure a
    violated declaration cannot pass silently. Matching is on bare table names, the same
    normalisation the rest of the platform uses.
    """
    wanted = {str(t).split(".")[-1].lower() for t in tables}
    return [r.caveat() for r in results
            if r.violated and r.declaration.table.split(".")[-1].lower() in wanted]


@dataclass
class DriftReport:
    """Every declaration on a connection, and what still holds."""

    results: list[CheckResult] = field(default_factory=list)

    @property
    def violated(self) -> list[CheckResult]:
        return [r for r in self.results if r.violated]

    @property
    def unknown(self) -> list[CheckResult]:
        return [r for r in self.results if r.state == "unknown"]

    def summary(self) -> str:
        if not self.results:
            return "No declarations to check."
        parts = [f"{len(self.results)} declaration(s) checked",
                 f"{len(self.violated)} violated"]
        if self.unknown:
            # Named separately and always: folding "could not check" into "fine" is the
            # silent-success shape the L wave kept catching.
            parts.append(f"{len(self.unknown)} could not be checked")
        return ", ".join(parts) + "."

    def to_dict(self) -> dict:
        return {"summary": self.summary(),
                "violated": [r.to_dict() for r in self.violated],
                "unknown": [r.to_dict() for r in self.unknown],
                "results": [r.to_dict() for r in self.results]}


def drift_report(declarations: Iterable[Declaration], probe: Probe) -> DriftReport:
    return DriftReport(results=check_all(declarations, probe))


def freshness_vocabulary() -> tuple[str, ...]:
    """V's states, mirrored so a test can pin that O6 adds no sixth dialect."""
    return ("fresh", "dirty", "stale", "unknown")


def exclusion_from(raw: dict) -> Optional[Exclusion]:
    """Build an exclusion from a stored declaration, or ``None`` when malformed."""
    table = str(raw.get("table") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    if not table or reason not in EXCLUSION_REASONS:
        return None
    return Exclusion(table=table, reason=reason, note=str(raw.get("note") or ""),
                     declared_by=str(raw.get("declared_by") or ""))
