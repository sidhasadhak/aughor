"""Which definition wins when the warehouse disagrees with itself — and why.

Ported from the warehouse-vendor context layer studied 2026-09-08, with one deliberate
inversion. (The full citation lives in the study note, not in this file.)

That design ranks competing business definitions by AUTHORITY: where a definition came
from, the standing of its author, how often people rely on it, how close it sits to
certified assets, how fresh it is. That is a good answer to "whose claim should I trust"
when nobody can check the claim.

We can check the claim. `OntologyMetric.verified` means the formula was EXECUTED against
the live database, and that is evidence of a different kind — evidence about the data
rather than about people. So verification is a TIER here, never a term in the score:

    a verified definition outranks an unverified one no matter who wrote it,
    how blessed its dashboard is, or how many teams already rely on it.

Authority orders candidates that are equally verified, and nothing else. The failure this
avoids is the one popularity ranking cannot: a wrong formula on the company's most-loved
certified dashboard, relied on by forty teams, beating the correct formula nobody has
opened yet. PageRank would pick the popular wrong one and sound confident.

Pure and dependency-free: `rank`/`choose` take models and return models, so the suite
pins the law without a database, a graph or a model call.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from aughor.ontology.models import DefinitionSource

#: How much the KIND of a source counts, when nothing stronger separates two claims. A
#: pipeline writes the table the dashboard reads, so it is closer to the definition than
#: the dashboard is; a manual note is a person asserting rather than a system computing.
_KIND_WEIGHT = {
    "pipeline": 5, "query": 4, "dashboard": 3,
    "table": 2, "document": 1, "manual": 1, "unknown": 0,
}

#: Reliance is real evidence but a shallow one, and it compounds: a definition used 400
#: times is not 400× better than one used once, and letting it act that way is how
#: popularity swamps every other signal. Capped, then scored on that cap.
_USE_COUNT_CAP = 25


def _recency(value: str) -> float:
    """Days-ago as a NEGATIVE number (newer = larger), or a floor when unparseable.

    Deliberately parsed rather than string-compared: this field arrives from several
    writers and has already carried both the ISO ``T`` form and the space-separated one.
    A lexical compare across the two silently mis-orders them — the same trap that dropped
    boundary-day rows out of a SQL window in this repo once already.
    """
    text = (value or "").strip()
    if not text:
        return -10_000.0
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        return -10_000.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return -(datetime.now(timezone.utc) - parsed).total_seconds() / 86_400.0


def authority(d: DefinitionSource) -> tuple:
    """The tiebreak score, HIGHEST first. Never consulted across verification tiers."""
    return (
        1 if d.certified else 0,
        min(int(d.use_count or 0), _USE_COUNT_CAP),
        _KIND_WEIGHT.get(d.source_kind, 0),
        1 if (d.author or "").strip() else 0,   # attribution is weak evidence, but evidence
        _recency(d.recorded_at),
    )


def rank(definitions: Sequence[DefinitionSource]) -> list[DefinitionSource]:
    """Best first: verified above unverified, then authority within each tier."""
    return sorted(definitions,
                  key=lambda d: (1 if d.verified else 0, authority(d)),
                  reverse=True)


@dataclass
class Chosen:
    winner: Optional[DefinitionSource]
    #: The best claim that DISAGREES with the winner's formula, if any. A runner-up that
    #: says the same thing is corroboration, not a conflict, and is not reported as one.
    dissenter: Optional[DefinitionSource]
    #: One sentence, for the panel beside the answer. Names the asset and the author,
    #: because "whose definition is this" is the question a reader actually has.
    why: str

    @property
    def contested(self) -> bool:
        return self.dissenter is not None


def _cite(d: DefinitionSource) -> str:
    asset = (d.source_asset or "").strip() or "an unnamed source"
    author = (d.author or "").strip()
    return f"{asset} ({author})" if author else f"{asset}, unattributed"


def choose(definitions: Sequence[DefinitionSource]) -> Chosen:
    """Pick the definition to use, and say why in words a person can argue with."""
    ordered = rank([d for d in definitions if (d.formula_sql or "").strip()])
    if not ordered:
        return Chosen(winner=None, dissenter=None,
                      why="No definition has been recorded for this metric.")

    winner = ordered[0]
    dissenter = next((d for d in ordered[1:]
                      if d.formula_sql.strip() != winner.formula_sql.strip()), None)

    if winner.verified:
        why = f"Using the definition from {_cite(winner)} — its formula was verified " \
              "against the live database."
    else:
        why = f"Using the definition from {_cite(winner)}. NOTHING here is verified: no " \
              "candidate formula has been executed against the live database, so this is " \
              "the most authoritative CLAIM, not a checked one."

    if dissenter is not None:
        why += f" {_cite(dissenter)} defines it differently"
        if winner.verified and not dissenter.verified:
            why += ", and that definition is unverified."
        elif dissenter.verified and winner.verified:
            # Two formulas that both run but disagree is a REAL disagreement about the
            # business, and no ranking should paper over it.
            why += " — and it is also verified, so the warehouse genuinely disagrees " \
                   "with itself. A person has to settle this one."
        else:
            why += "."
    return Chosen(winner=winner, dissenter=dissenter, why=why)
