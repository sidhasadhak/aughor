"""AT-4 — the two-witness contract, and the ratchet that keeps it the only way in.

The failure this module exists for is not "the profiler guessed wrong". It is that the
profiler guessed once, confidently, from one layer of evidence, and every downstream
consumer read the guess as a fact. The AT-0 pre-check put a number on how often a lone
witness is wrong (3 of 5 bounded-±90 columns are not coordinates; `^[A-Z]{2}$` matched
`Customer State`), so the rule here is not stylistic: two layers agree, or the answer is
"the evidence does not say".
"""
from __future__ import annotations

import pathlib
import re

import pytest

from aughor.tools.concept import (
    CONFIDENT,
    LAYER_DECLARED,
    LAYER_NAME,
    LAYER_PAIR,
    LAYER_USAGE,
    LAYER_VALUE,
    ConceptVerdict,
    Witness,
    concept_of,
    resolve_concept,
)


def w(layer: str, concept: str, confidence: float = 0.6, evidence: str = "because") -> Witness:
    return Witness(layer=layer, concept=concept, confidence=confidence, evidence=evidence)


# ── the rule ──────────────────────────────────────────────────────────────────

def test_two_layers_agreeing_assign_the_concept():
    v = resolve_concept([
        w(LAYER_VALUE, "geo.latitude", 0.6, "values −33.9…48.8 at 8 dp over 6,716 distinct"),
        w(LAYER_PAIR, "geo.latitude", 0.6, "partnered with Longitude in ±180"),
    ])
    assert v.concept == "geo.latitude"
    assert v.is_confident
    assert v.confidence == pytest.approx(0.84)          # noisy-or, not a max
    assert any("values −33.9" in e for e in v.evidence)
    assert any(e.startswith("pair: ") for e in v.evidence)


def test_one_witness_is_a_hint_and_never_confident():
    """The whole module in one assertion: a single layer, however sure, cannot act."""
    v = resolve_concept([w(LAYER_VALUE, "geo.latitude", 0.99, "every value inside ±90")])
    assert v.concept == "geo.latitude"          # kept — it is real information
    assert not v.is_confident
    assert v.confidence < CONFIDENT
    assert concept_of(v.concept, v.confidence) == ""
    assert any("hint only" in e for e in v.evidence)
    assert any("a second layer must agree" in e for e in v.evidence)


def test_two_witnesses_from_the_SAME_layer_are_still_one_witness():
    """Two name patterns agreeing is one layer saying the same thing twice. This is the
    exact shape that made `Customer State` an ISO-3166 country code: a name rule and a
    two-letter-pattern rule both keying off surface text."""
    v = resolve_concept([
        w(LAYER_NAME, "code.iso3166", 0.7, "named *_country"),
        w(LAYER_NAME, "code.iso3166", 0.8, "matches ^[A-Z]{2}$"),
    ])
    assert not v.is_confident
    assert v.confidence <= 0.49


def test_layer_count_beats_a_louder_single_layer():
    """Two layers at 0.6 must beat one layer at 0.95 — otherwise the rule is decorative."""
    v = resolve_concept([
        w(LAYER_NAME, "money.amount", 0.95, "named *_price"),
        w(LAYER_VALUE, "percent.fraction", 0.6, "every value in 0–1"),
        w(LAYER_USAGE, "percent.fraction", 0.6, "never SUMmed, always AVGd"),
    ])
    assert v.concept == "percent.fraction"
    assert v.is_confident
    assert any("rival concept money.amount" in e for e in v.evidence)


def test_a_tie_between_two_supported_concepts_resolves_to_nothing():
    """Inventing a tiebreak would be the same mistake one level up: a preference dressed
    as a finding."""
    v = resolve_concept([
        w(LAYER_NAME, "geo.latitude", 0.6), w(LAYER_VALUE, "geo.latitude", 0.6),
        w(LAYER_PAIR, "geo.longitude", 0.6), w(LAYER_USAGE, "geo.longitude", 0.6),
    ])
    assert v.concept == ""
    assert not v.is_confident
    assert any("equally supported" in e for e in v.evidence)


def test_a_human_declaration_stands_alone_and_is_not_outvoted():
    v = resolve_concept([
        w(LAYER_DECLARED, "money.amount", 1.0, "operator set unit = USD"),
        w(LAYER_VALUE, "percent.fraction", 0.9), w(LAYER_USAGE, "percent.fraction", 0.9),
    ])
    assert v.concept == "money.amount"
    assert v.confidence == 1.0
    assert v.is_confident
    assert v.evidence[0].startswith("declared: ")
    # the outvoted evidence is still carried — a human deserves to see what disagreed
    assert any("percent.fraction" in e or "value: " in e for e in v.evidence)


def test_no_witnesses_and_zero_confidence_witnesses_resolve_to_nothing():
    assert resolve_concept([]).concept == ""
    assert resolve_concept(None).concept == ""
    assert resolve_concept([w(LAYER_VALUE, "geo.latitude", 0.0)]).concept == ""
    assert resolve_concept([w(LAYER_VALUE, "", 0.9)]).concept == ""


def test_an_unknown_layer_is_refused_at_construction():
    with pytest.raises(ValueError):
        Witness(layer="vibes", concept="geo.latitude", confidence=0.9, evidence="felt right")


def test_confidence_never_reaches_certainty_from_evidence_alone():
    v = resolve_concept([w(LAYER_VALUE, "x", 0.99), w(LAYER_PAIR, "x", 0.99), w(LAYER_USAGE, "x", 0.99)])
    assert v.confidence <= 0.99
    assert v.confidence < 1.0


def test_concept_of_is_the_single_honest_read():
    assert concept_of("geo.latitude", 0.84) == "geo.latitude"
    assert concept_of("geo.latitude", 0.49) == ""
    assert concept_of("", 0.99) == ""
    assert concept_of(None, None) == ""
    assert concept_of("geo.latitude", "not a number") == ""    # never raises on cache junk


# ── the contract on ColumnProfile ─────────────────────────────────────────────

def test_column_profile_carries_the_concept_and_roundtrips():
    from aughor.tools.profiler import ColumnProfile

    cp = ColumnProfile(
        table="t", column="Latitude", dtype="VARCHAR", semantic_type="key",
        concept="geo.latitude", concept_confidence=0.84, concept_evidence=["value: ±90 at 8 dp"],
    )
    back = ColumnProfile.from_dict(cp.to_dict())
    assert (back.concept, back.concept_confidence) == ("geo.latitude", 0.84)
    assert back.concept_evidence == ["value: ±90 at 8 dp"]


def test_a_cache_written_before_AT4_loads_as_no_concept_not_as_None():
    """The v4 cache on disk has no concept keys. `.concept_evidence` arriving as None
    where every reader expects a list is the sort of thing that only fails in production."""
    from aughor.tools.profiler import ColumnProfile

    old = {"table": "t", "column": "c", "dtype": "BIGINT", "semantic_type": "measure",
           "null_rate": 0.0, "distinct_count": 3}
    cp = ColumnProfile.from_dict(old)
    assert cp.concept == ""
    assert cp.concept_confidence == 0.0
    assert cp.concept_evidence == []
    assert concept_of(cp.concept, cp.concept_confidence) == ""


# ── the ratchet ───────────────────────────────────────────────────────────────

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: `resolve_concept` is the only function allowed to decide a concept. These files may
#: assign the field: the resolver itself, and the profiler seam that stamps its verdict
#: onto the profile. Everything else must READ.
_WRITERS = {
    "aughor/tools/concept.py",
    "aughor/tools/profiler.py",
}

_ASSIGNS_CONCEPT = re.compile(r"\.concept\s*=(?!=)")


def test_resolve_concept_is_the_only_writer():
    """The defect this prevents is the one AT-4 exists for, one level up: some module
    finds a witness it likes and writes `cp.concept = "geo.latitude"` directly, and the
    two-witness rule is silently gone for that column."""
    offenders: list[str] = []
    for path in sorted((_ROOT / "aughor").rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel in _WRITERS:
            continue
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if _ASSIGNS_CONCEPT.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "something other than resolve_concept is deciding what a column IS:\n  "
        + "\n  ".join(offenders)
        + "\n\nBuild a Witness and let resolve_concept weigh it against the other layers."
    )


def test_every_consumer_reads_the_confidence():
    """Reading `.concept` without `.concept_confidence` is 'one witness spoke and the
    system believed it' at the consumer. `concept_of()` is the one honest read; a module
    that mentions `.concept` must go through it (or read the confidence itself)."""
    offenders: list[str] = []
    for path in sorted((_ROOT / "aughor").rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel == "aughor/tools/concept.py":
            continue
        text = path.read_text(errors="ignore")
        mentions = re.findall(r"(?<![\w.])(?:cp|profile|prof|col)\.concept(?![_\w])", text)
        if not mentions:
            continue
        if "concept_of(" in text or ".concept_confidence" in text or "is_confident" in text:
            continue
        offenders.append(rel)
    assert not offenders, (
        "these read a concept without asking whether it is confident: " + ", ".join(offenders)
        + "\n\nUse aughor.tools.concept.concept_of(cp.concept, cp.concept_confidence)."
    )


def test_the_verdict_default_is_no_concept():
    """A ConceptVerdict constructed with nothing must be a refusal, not an empty truth."""
    v = ConceptVerdict()
    assert v.concept == "" and v.confidence == 0.0 and v.evidence == []
    assert not v.is_confident
