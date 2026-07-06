"""Grain-of-intent check — does the RESULT's row count match the question's implied grain?

The Spider2 Phase-0 triage found 11/63 misses were grain errors that execute cleanly and
return plausible rows, so the error/empty/fan-out triggers all miss them: a "top three X"
question answered with 5 rows, a "which single Y…" answered with 7, a "for each match"
answered per-ball. The QUESTION declares its expected grain; the result's row count is
observable; comparing them is deterministic and execution-grounded — the guard class that
has held up (never an LLM judgement, only a detector feeding the existing repair loop).

Deliberately PRECISION-FIRST: every pattern here must be unambiguous enough that firing
wrongly is rare — a missed detection costs nothing (the query ships as-is), a false fire
costs a wasted repair round. Detection is pure (unit-testable offline); the entity→column
probe takes a callable so any backend/harness can wire it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# "top three customers", "top 5 players", "first 10 …", "5 highest-earning …"
_TOP_N = re.compile(
    r"\b(?:top|first|best|highest|largest|lowest|smallest|bottom)\s+"
    r"(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)
_N_SUPERLATIVE = re.compile(
    r"\b(\d{1,3}|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:most|least|highest|lowest|largest|smallest|best|worst)\b", re.I)
# "5 delivery drivers with the highest …" — N + short noun phrase + superlative clause
_N_NOUN_SUPERLATIVE = re.compile(
    r"\b(\d{1,3}|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"[a-z_]+(?:\s+[a-z_]+)?\s+with\s+the\s+"
    r"(?:most|least|highest|lowest|largest|smallest|best|worst)\b", re.I)

# Singular-intent openers: "which year …", "what is the …", "who has the highest …",
# "for the X that … how many/what …". Must clearly ask for ONE thing.
_SINGULAR = re.compile(
    r"^(?:in\s+)?(?:which|what|who)\s+(?:is|was|are|year|month|day|player|customer|store|"
    r"country|city|driver|team|category|product|university|company)\b.*?"
    r"\b(?:most|least|highest|lowest|largest|smallest|best|worst|closest|first|shortest|longest)\b",
    re.I | re.S)

# "for each X", "per X" — a per-entity grain declaration.
_PER_ENTITY = re.compile(r"\b(?:for\s+(?:each|every)|per)\s+([a-z_][a-z_ ]{2,30}?)(?:[,.:;]|\s+(?:and|in|of|the|please|calculate|show|list|provide|identify|from|with)\b)", re.I)


@dataclass
class GrainExpectation:
    kind: str            # "exact" | "per_entity"
    n: Optional[int]     # expected row count for "exact"
    entity: Optional[str]  # entity phrase for "per_entity"
    reason: str          # human-readable, feeds the repair diagnosis


def expected_grain(question: str) -> Optional[GrainExpectation]:
    """The question's implied result grain, or None when it doesn't clearly declare one."""
    q = (question or "").strip()
    m = _TOP_N.search(q) or _N_SUPERLATIVE.search(q) or _N_NOUN_SUPERLATIVE.search(q)
    if m:
        raw = m.group(1).lower()
        n = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
        if n:
            return GrainExpectation("exact", n, None,
                                    f'the question asks for {n} rows ("{m.group(0)}")')
    # per-entity BEFORE singular: "for each customer, which month …" is per-customer.
    m = _PER_ENTITY.search(q)
    if m:
        entity = m.group(1).strip().rstrip("s")
        return GrainExpectation("per_entity", None, entity,
                                f'the question asks for one row per {entity} ("{m.group(0).strip()}")')
    if _SINGULAR.match(q):
        return GrainExpectation("exact", 1, None,
                                "the question asks for a single answer row")
    return None


def _entity_column(entity: str, columns: Sequence[str]) -> Optional[str]:
    """Fuzzy-map an entity phrase ("match", "customer") to an id-ish column."""
    e = entity.lower().replace(" ", "_")
    cands = [c for c in columns if c.lower() in (f"{e}_id", f"{e}id", e, f"{e}_key", f"{e}_no")]
    if cands:
        return cands[0]
    # last resort: a column that starts with the entity word and ends id/key
    for c in columns:
        cl = c.lower()
        if cl.startswith(e) and cl.endswith(("id", "key", "_no")):
            return c
    return None


def check_result_grain(
    question: str,
    row_count: int,
    *,
    columns_in_scope: Sequence[str] = (),
    count_distinct: Optional[Callable[[str], Optional[int]]] = None,
    tie_tolerance: float = 1.0,
) -> Optional[str]:
    """Return a repair DIAGNOSIS when the result's row count contradicts the question's
    declared grain, else None. Precision-first: unclear ⇒ None.

    count_distinct(column) -> int|None probes the live data for per-entity expectations
    (the caller supplies it; absent ⇒ per-entity checks are skipped).
    tie_tolerance: an "exact N" question may legitimately return a few extra rows on
    ties — allow up to N*(1+tie_tolerance) before firing.
    """
    if row_count < 0:
        return None
    exp = expected_grain(question)
    if exp is None:
        return None
    if exp.kind == "exact" and exp.n:
        hi = int(exp.n * (1 + tie_tolerance))
        if row_count > hi or (row_count < exp.n and row_count == 0):
            return (f"GRAIN MISMATCH: {exp.reason}, but the result has {row_count} rows. "
                    f"Re-aggregate or re-rank so the output matches the asked-for grain "
                    f"(LIMIT/window over the correct entity, not a finer or coarser one).")
        return None
    if exp.kind == "per_entity" and exp.entity and count_distinct is not None:
        col = _entity_column(exp.entity, columns_in_scope)
        if not col:
            return None
        expected = count_distinct(col)
        if not expected or expected <= 1:
            return None
        # fire only on a strong mismatch — result far off one-row-per-entity
        if row_count > expected * 2 or row_count < max(1, int(expected * 0.5)):
            return (f"GRAIN MISMATCH: {exp.reason} (~{expected} distinct {exp.entity}s in the "
                    f"data), but the result has {row_count} rows. GROUP BY the {exp.entity} "
                    f"grain exactly — one output row per {exp.entity}.")
    return None
