"""AT-7 — reading the operations vocabulary, and the one question it answers.

A concept nobody consults is a label. This module is the consulting: it turns
`concept = "key.identifier"` into "do not put this on a side of a correlation", which is a
decision a query planner can act on and a reader can check.

Two properties worth stating, because both were deliberate:

**Silence is not permission.** An unknown concept returns None and every helper below
answers conservatively — `forbids_numeric_relationship("")` is False, not True. A
vocabulary that blocked everything it had not been told about would be a guard that fails
closed on its own gaps, and the gaps are guaranteed: new concepts arrive from new witness
producers. `test_operations_covers_every_concept_the_layers_emit` is what keeps the gaps
from happening quietly, instead of a runtime refusal that punishes the wrong caller.

**Curated, not user-extensible — for now.** `docs/ANSWER_TRUTHFULNESS_ROADMAP_2026-08-16.md`
§5 lists that as an open question, and `ontology_column_config` is the natural home when it
is answered. Until then this file is the whole vocabulary, which keeps one source of truth
while the concepts themselves are still moving.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_PATH = Path(__file__).parent / "operations.yaml"


@dataclass(frozen=True)
class ConceptOps:
    """One concept's admissible and forbidden operations."""
    concept: str
    label: str = ""
    aggregate: tuple = ()
    never: tuple = ()
    numeric: bool = False
    note: str = ""

    def caveat(self) -> str:
        """The one line a prompt or a profile annotation carries.

        Forbidden operations lead, because a prompt has finite attention and "never SUM
        this" changes an answer where "may be AVGd" does not.
        """
        if self.never:
            return f"{self.label} — never {', '.join(self.never)}"
        return self.label


@dataclass(frozen=True)
class Vocabulary:
    version: int = 0
    by_concept: dict = field(default_factory=dict)


@functools.lru_cache(maxsize=1)
def load() -> Vocabulary:
    """Parse the YAML once. A missing or malformed file yields an EMPTY vocabulary rather
    than an exception: no opinion is a survivable state, and a profiler that raised because
    a data file moved would take the whole intelligence build with it."""
    try:
        import yaml
        doc = yaml.safe_load(_PATH.read_text()) or {}
    except Exception:
        return Vocabulary()
    out: dict[str, ConceptOps] = {}
    for concept, spec in (doc.get("concepts") or {}).items():
        if not isinstance(spec, dict):
            continue
        out[str(concept)] = ConceptOps(
            concept=str(concept),
            label=str(spec.get("label") or "").strip(),
            aggregate=tuple(spec.get("aggregate") or ()),
            never=tuple(spec.get("never") or ()),
            numeric=bool(spec.get("numeric", False)),
            note=" ".join(str(spec.get("note") or "").split()),
        )
    return Vocabulary(version=int(doc.get("version") or 0), by_concept=out)


def operations_for(concept: str) -> Optional[ConceptOps]:
    """This concept's row, or None when the vocabulary has nothing to say."""
    return load().by_concept.get(str(concept or "")) if concept else None


def known_concepts() -> frozenset:
    """Every concept the vocabulary covers — the ratchet's other half."""
    return frozenset(load().by_concept)


def forbids_numeric_relationship(concept: str) -> bool:
    """True when putting this column on a side of a CORR would produce a well-formed wrong
    answer: an id, a place name, a timestamp, a grouping dimension.

    Deliberately narrow. It answers only for a concept the vocabulary knows AND that is
    marked non-numeric; anything else is False, so a column with no concept behaves exactly
    as it did before AT-7 existed.
    """
    ops = operations_for(concept)
    return bool(ops and not ops.numeric)


def forbidden_operations(concept: str) -> tuple:
    ops = operations_for(concept)
    return ops.never if ops else ()


def caveat_for(concept: str) -> str:
    """The prompt-facing one-liner, or "" when there is nothing to say."""
    ops = operations_for(concept)
    return ops.caveat() if ops else ""
