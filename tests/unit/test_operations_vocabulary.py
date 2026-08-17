"""AT-7 — the operations vocabulary, and the drift ratchet that keeps it honest.

The vocabulary is the seam where a concept stops being a label and becomes a consequence.
Its characteristic failure is not being wrong — it is going quietly EMPTY for a concept,
because a missing row reads as "no opinion", which reads as "no objection". Half this file
is that guard.
"""
from __future__ import annotations

import re
from pathlib import Path

from aughor.ontology.operations import (
    caveat_for,
    forbidden_operations,
    forbids_numeric_relationship,
    known_concepts,
    load,
    operations_for,
)

_ROOT = Path(__file__).resolve().parents[2]


# ── the table ────────────────────────────────────────────────────────────────

def test_the_vocabulary_loads_and_is_not_empty():
    v = load()
    assert v.version >= 1
    assert len(v.by_concept) >= 15


def test_an_identifier_refuses_arithmetic_and_says_why():
    ops = operations_for("key.identifier")
    assert ops is not None
    assert not ops.numeric
    assert "SUM" in ops.never and "CORR" in ops.never
    assert "90210" in ops.note          # the reason, checkable by a reader


def test_a_coordinate_may_be_correlated_but_never_summed():
    """The distinction the whole wave turns on: `never SUM/AVG` is not `not a number`.
    A latitude on a side of a correlation is the question 'does where the customer is
    relate to how late we are', which is exactly what was asked six times."""
    ops = operations_for("geo.latitude")
    assert ops.numeric is True
    assert set(ops.never) == {"SUM", "AVG"}
    assert not forbids_numeric_relationship("geo.latitude")


def test_a_per_unit_rate_may_be_averaged_and_never_summed():
    ops = operations_for("rate.per_unit")
    assert "SUM" in ops.never and "AVG" in ops.aggregate


def test_a_flag_is_a_rate_not_a_magnitude():
    ops = operations_for("flag.derived_comparison")
    assert "AVG" in ops.aggregate
    assert "how often" in ops.note and "how much" in ops.note


def test_the_caveat_leads_with_the_prohibition():
    assert caveat_for("key.identifier").endswith("never SUM, AVG, CORR")
    # a concept with nothing forbidden says only what it is
    assert caveat_for("count.quantity") == "a count of things"


# ── silence is not permission, and not refusal either ────────────────────────

def test_an_unknown_concept_changes_nothing():
    """A guard that failed closed on its own gaps would punish the wrong caller: gaps are
    guaranteed, because new concepts arrive from new witness producers."""
    assert operations_for("nope.not.a.concept") is None
    assert forbids_numeric_relationship("nope.not.a.concept") is False
    assert forbids_numeric_relationship("") is False
    assert forbids_numeric_relationship(None) is False
    assert forbidden_operations("nope") == ()
    assert caveat_for("nope") == ""


# ── the ratchet: every concept any layer can emit must have a row ────────────

def _emitted_concepts() -> set:
    """Every concept string the witness producers can actually emit.

    Read from the SOURCE, not from a list maintained beside it — a list would drift, and a
    guard that drifts goes blind rather than loud. Each producer names its concepts as
    string literals in one recognisable place, so the literals are what gets scanned.
    """
    found: set[str] = set()

    # the NAME layer — the rule table in the profiler
    text = (_ROOT / "aughor" / "tools" / "profiler.py").read_text()
    block = text.split("_NAME_WITNESS_RULES", 1)[1].split("\ndef ", 1)[0]
    found |= set(re.findall(r'"([a-z_]+\.[a-z_]+)"', block))

    # the PAIR layer — `roles=` tuples on each finding
    text = (_ROOT / "aughor" / "tools" / "pairs.py").read_text()
    for roles in re.findall(r"roles=\(([^)]*)\)", text):
        found |= set(re.findall(r'"([a-z_]+\.[a-z_]+)"', roles))

    # the USAGE layer — the role→concept map
    text = (_ROOT / "aughor" / "tools" / "usage.py").read_text()
    block = text.split("_ROLE_CONCEPTS", 1)[1].split("\ndef ", 1)[0]
    found |= set(re.findall(r'\("([a-z_]+\.[a-z_]+)",', block))

    return {c for c in found if "." in c}


def test_the_scan_actually_finds_the_concepts_it_claims_to():
    """A failed probe and a true negative look identical — so the ratchet below is only
    worth anything if this passes first."""
    emitted = _emitted_concepts()
    assert len(emitted) >= 12, f"the source scan found only {emitted} — it has gone blind"
    assert "geo.latitude" in emitted          # name AND pair
    assert "flag.derived_comparison" in emitted
    assert "measure.additive_total" in emitted
    assert "key.identifier" in emitted


def test_operations_covers_every_concept_the_layers_emit():
    missing = sorted(_emitted_concepts() - known_concepts())
    assert not missing, (
        "these concepts can be resolved but the operations vocabulary has no row for "
        f"them: {missing}\n\nA missing row reads as 'no opinion', which reads as 'no "
        "objection'. Add them to aughor/ontology/operations.yaml."
    )


def test_the_vocabulary_carries_no_rows_nothing_can_emit():
    """The other direction — a row for a concept no layer produces is dead weight that
    reads as coverage. Fails loudly rather than rotting quietly."""
    orphans = sorted(known_concepts() - _emitted_concepts())
    assert not orphans, (
        f"the vocabulary has rows nothing can emit: {orphans}\n\nEither a witness producer "
        "was removed, or the row was written for a concept that never shipped."
    )


def test_every_row_is_complete():
    for concept, ops in load().by_concept.items():
        assert ops.label, f"{concept} has no label — the prompt would render a bare slug"
        assert ops.note, f"{concept} has no note — a reader cannot check it"
        assert ops.aggregate or ops.never, f"{concept} says nothing about operations at all"
