"""What a column IS, decided by agreeing witnesses rather than by whoever spoke first.

`semantic_type` answers a different question — how to *handle* a column (key, measure,
dimension, flag) — and fifteen modules read it as truth. This module adds a stricter field
beside it and leaves it alone.

The defect it exists for: **one witness spoke and the system believed it.** The column NAME
said `Late_delivery_risk` was a risk score; the VALUES said it was a 0/1 flag. The LOADER
said `Latitude` was `VARCHAR`; the values said coordinates to eight decimal places.
`_GEO_CODE_PATTERN` in the profiler still says a latitude is a *key*, so the one column that
could have answered "where is this customer" was excluded from every numeric path.

The AT-0 pre-check measured what a lone witness is worth across 105 tables and 890 columns:

* 3 of the 5 columns whose VALUES sit inside ±90 with four decimal places are not
  coordinates — they are `Shipping costs`, `Defect rates` and a profit ratio (60% false
  positive);
* `^[A-Z]{2}$` matched `Customer State` (`UT`, `MD`, `GA`) as an ISO-3166 country code;
* an arithmetic sweep found `transactionID * unitPrice ≈ franchiseID` holding on 100% of
  rows, because `unitPrice` is the constant 3.

Every one of those is a confident, well-formed, wrong answer from a single layer of
evidence. So a concept is assigned only when **two witnesses from different layers agree**.
A lone witness is kept — it is real information — but as a hint below `CONFIDENT`, and
nothing is allowed to act on a hint.

The layers, in the order they became available:

    name       the column's name                    `Latitude`, `*_risk`, `is_*`
    value      the shape of its values              ±90 at 8 dp; values ⊆ {0,1}
    pair       coherence with a partner column      lat needs a lon; a delay needs a plan
    usage      how the column is actually queried   GROUP BY'd, SUM'd, joined on
    declared   a human said so                      `ColumnFlags`, an ontology override

`declared` is the one layer that stands alone: a human owning the answer is the authority,
not a witness competing with the others.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

#: The evidence layers. A concept needs agreement ACROSS two of these, never two witnesses
#: from the same one — two name patterns agreeing is one witness saying the same thing twice.
LAYER_NAME = "name"
LAYER_VALUE = "value"
LAYER_PAIR = "pair"
LAYER_USAGE = "usage"
LAYER_DECLARED = "declared"

LAYERS = (LAYER_NAME, LAYER_VALUE, LAYER_PAIR, LAYER_USAGE, LAYER_DECLARED)

#: At or above this, the concept is ASSIGNED and may be acted on. Below it the concept is a
#: HINT: worth showing a human, never worth planning a query from. One number, one meaning —
#: consumers ask `is_confident()` rather than each inventing a threshold.
CONFIDENT = 0.5

#: A lone witness is capped strictly below CONFIDENT no matter how sure it claims to be.
#: This is the whole rule, in one constant: certainty about the wrong thing is what the
#: pre-check measured, and it is not fixed by the witness trying harder.
_LONE_CEILING = 0.49


@dataclass(frozen=True)
class Witness:
    """One layer's opinion about one column.

    `confidence` is that layer's own certainty (0–1) and is never the final word; the
    resolver combines it with the other layers. `evidence` is the sentence a human reads to
    check the machine — "values 17.98…48.78 at 8 dp over 6,716 distinct", not "matched".
    """
    layer: str
    concept: str
    confidence: float
    evidence: str

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise ValueError(f"unknown witness layer {self.layer!r}; expected one of {LAYERS}")


@dataclass(frozen=True)
class ConceptVerdict:
    """What the witnesses add up to. `concept` may be set while `confidence` is below
    CONFIDENT — that is a hint, and `is_confident` is False for it."""
    concept: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    @property
    def is_confident(self) -> bool:
        return bool(self.concept) and self.confidence >= CONFIDENT


def _noisy_or(confidences: Iterable[float]) -> float:
    """Independent witnesses compound: 1 − Π(1 − c).

    Two layers at 0.6 reach 0.84, not 0.6 — agreement across layers is worth more than
    either layer alone, which is the entire claim this module makes. Capped below 1.0 so
    nothing computed from evidence ever reads as certain; only a human reaches 1.0.
    """
    product = 1.0
    for c in confidences:
        product *= (1.0 - max(0.0, min(1.0, float(c))))
    return round(min(0.99, 1.0 - product), 4)


def resolve_concept(witnesses: Iterable[Witness]) -> ConceptVerdict:
    """The ONLY writer of `concept`. Two agreeing layers assign it; one layer hints.

    Ties are demoted rather than broken. When two concepts are equally well supported the
    honest answer is "the evidence does not say", and inventing a tiebreak here would be the
    same mistake as believing a lone witness — a preference dressed up as a finding.
    """
    live = [w for w in (witnesses or ()) if w and w.concept and w.confidence > 0]
    if not live:
        return ConceptVerdict()

    # A human override is authority, not evidence. It does not need a second witness and it
    # is not outvoted by any number of them.
    declared = [w for w in live if w.layer == LAYER_DECLARED]
    if declared:
        best = max(declared, key=lambda w: w.confidence)
        others = [f"{w.layer}: {w.evidence}" for w in live if w is not best]
        return ConceptVerdict(
            concept=best.concept,
            confidence=round(min(1.0, best.confidence), 4),
            evidence=[f"declared: {best.evidence}"] + others,
        )

    # Best witness per (concept, layer) — a layer speaks once.
    by_concept: dict[str, dict[str, Witness]] = {}
    for w in live:
        per_layer = by_concept.setdefault(w.concept, {})
        prev = per_layer.get(w.layer)
        if prev is None or w.confidence > prev.confidence:
            per_layer[w.layer] = w

    scored = [
        (len(per_layer), _noisy_or(x.confidence for x in per_layer.values()), concept, per_layer)
        for concept, per_layer in by_concept.items()
    ]
    # Layer COUNT first: two layers at 0.6 beat one layer at 0.95, which is the rule the
    # pre-check paid for. Score only separates candidates that agree on layer count.
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    layers, score, concept, per_layer = scored[0]

    supported = [s for s in scored if s[0] >= 2]
    if len(supported) >= 2 and supported[0][:2] == supported[1][:2]:
        rivals = ", ".join(f"{s[2]} ({s[1]:.2f})" for s in supported[:3])
        return ConceptVerdict(
            concept="", confidence=0.0,
            evidence=[f"no concept: {len(supported)} candidates are equally supported — {rivals}"],
        )

    if layers >= 2:
        evidence = [f"{w.layer}: {w.evidence}" for w in per_layer.values()]
        # The runner-up is named whatever its layer count — a LOUD single layer that lost
        # is the most interesting disagreement there is. AT-0 found 27 columns where the
        # name says one thing and the values say another; this line is where the reader
        # sees that it happened here and which side won.
        if len(scored) > 1:
            rival = scored[1]
            evidence.append(
                f"rival concept {rival[2]} at {rival[1]:.2f} on "
                f"{rival[0]} layer{'s' if rival[0] != 1 else ''}")
        return ConceptVerdict(concept=concept, confidence=score, evidence=evidence)

    # One layer only. Keep it, cap it, and say what is missing — a hint that names the
    # second witness it needs is how the next layer gets built.
    lone = max(live, key=lambda w: w.confidence)
    return ConceptVerdict(
        concept=lone.concept,
        confidence=round(min(_LONE_CEILING, lone.confidence), 4),
        evidence=[
            f"{lone.layer}: {lone.evidence}",
            f"hint only — one witness ({lone.layer}); a second layer must agree before "
            f"{lone.concept} is used",
        ],
    )


def concept_of(
    concept: Optional[str],
    confidence: Optional[float],
    *,
    minimum: float = CONFIDENT,
) -> str:
    """The concept when it is confident enough to act on, else "".

    The single honest read, so no consumer has to remember the rule. Reading `.concept`
    without `.concept_confidence` is exactly the "one witness spoke and the system believed
    it" failure, one level up — `test_concept_consumers_read_confidence` enforces this.
    """
    if not concept:
        return ""
    try:
        return str(concept) if float(confidence or 0.0) >= minimum else ""
    except (TypeError, ValueError):
        return ""
