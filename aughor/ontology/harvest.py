"""Turn the definitions this deployment already holds into claims with provenance.

:mod:`aughor.ontology.authority` decides which definition wins. This is what gives it
something to decide BETWEEN: the stores already know that a person edited a formula on a
date, that the metric registry says something different, and that some SQL actually ran —
they just never recorded those as competing claims with an author on each.

Three sources, and each is only allowed to assert what it actually knows:

* **an ontology override** — a real authored edit. It carries `edited_by`, `edited_at`,
  and a per-field bind result, which is the only place `verified` may come from.
* **the metric registry** (``data/metrics.json``) — a curated definition with no author
  and no bind receipt, so it produces an UNATTRIBUTED, UNVERIFIED claim. It is usually the
  incumbent, which is exactly why it must not be flattered.
* **executed SQL** — how often something actually ran with this formula in it. Reliance is
  evidence about people, and it only ever fills ``use_count``.

🔑 The rule the whole thing rests on: ``verified`` means the formula BOUND against the live
database, and nothing else may set it. Not "the registry is curated", not "an admin wrote
it", not "it looks like valid SQL". If `verified` ever comes to mean "we think it's fine",
:mod:`authority`'s tier collapses into the popularity ranking it exists to beat, and it
does so silently — every answer keeps working, just sometimes with the wrong formula.

Pure: every function takes plain values and returns models. The suite pins the harvest
rules with no store, no database and no connection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from aughor.ontology.models import DefinitionSource

#: The registry is a file a team curates; naming it as the asset is more useful to a
#: reader than the path, which they cannot open from an answer panel anyway.
REGISTRY_ASSET = "metric registry"

_WS = re.compile(r"\s+")


def _norm(sql: str) -> str:
    """Whitespace- and case-insensitive form, for comparing two spellings of one formula."""
    return _WS.sub(" ", (sql or "").strip().lower())


def from_override(ov: Any) -> Optional[DefinitionSource]:
    """A person's edit, as a claim. ``None`` when the edit did not touch the formula.

    ``verified`` is read from the BIND RESULT the override already carries — the same
    field `_apply_metric` uses to decide whether the formula may be injected at all. An
    override whose SQL never bound is still a claim worth recording (somebody believes
    it), it simply loses to anything that did bind.
    """
    fields = getattr(ov, "fields", None) or {}
    formula = str(fields.get("formula_sql") or "").strip()
    if not formula:
        return None
    try:
        bound = bool(ov.sql_field_ok("formula_sql"))
    except Exception:
        binding = (getattr(ov, "binding", None) or {}).get("formula_sql") or {}
        bound = binding.get("bound") is True
    note = str(getattr(ov, "note", "") or "")
    return DefinitionSource(
        formula_sql=formula,
        source_asset="ontology override" + (f" — {note}" if note else ""),
        source_kind="manual",
        # Never invented. An unattributed edit scores lower in `authority`, which is the
        # honest outcome; filling in "system" or the current user would be a lie that
        # ranks better than the truth.
        author=str(getattr(ov, "edited_by", "") or ""),
        recorded_at=str(getattr(ov, "edited_at", "") or ""),
        certified=str(getattr(ov, "source", "")) == "human",
        verified=bound,
        verification_note="bound against the live database" if bound
                          else "never bound — recorded as a claim, not as a fact",
    )


def from_registry(md: Any) -> Optional[DefinitionSource]:
    """The curated registry entry, as a claim — unattributed and UNVERIFIED.

    `metrics.json` has no author field and no bind receipt. Both absences are reported
    rather than papered over: this is typically the incumbent definition, and the whole
    point of ranking is that being the incumbent is not evidence.
    """
    formula = str(getattr(md, "sql", "") or "").strip()
    if not formula:
        return None
    label = str(getattr(md, "label", "") or getattr(md, "name", "") or "").strip()
    return DefinitionSource(
        formula_sql=formula,
        source_asset=f"{REGISTRY_ASSET} — {label}" if label else REGISTRY_ASSET,
        source_kind="document",
        author="",
        recorded_at="",
        certified=False,
        verified=False,
        verification_note="the registry carries no bind receipt",
    )


def reliance(formula: str, executed_sql: Sequence[str]) -> int:
    """How many executed statements contain this formula.

    Substring over a normalised form, deliberately: two spellings of the same expression
    should count together, and anything cleverer (parsing every historical statement to
    compare expression trees) would be a second SQL engine maintained for a tiebreak.
    Conservative by construction — it undercounts paraphrases rather than overcounting
    coincidences, and `authority` caps it anyway so it can never dominate.
    """
    needle = _norm(formula)
    if not needle:
        return 0
    return sum(1 for s in executed_sql if needle in _norm(s))


@dataclass
class Evidence:
    """What the stores could say about ONE metric. Every field optional: a deployment
    with no overrides and no history still harvests a registry claim."""
    overrides: Sequence[Any] = field(default_factory=tuple)
    registry: Any = None
    executed_sql: Sequence[str] = field(default_factory=tuple)


def harvest(evidence: Evidence) -> list[DefinitionSource]:
    """Every claim we can evidence for one metric, de-duplicated, with reliance filled.

    Two sources asserting the SAME formula are collapsed onto the stronger record rather
    than double-counted — otherwise a definition copied into three places would out-rank a
    verified one purely by being repeated, which is the failure mode this whole design
    exists to avoid.
    """
    out: list[DefinitionSource] = []
    for ov in evidence.overrides or ():
        d = from_override(ov)
        if d is not None:
            out.append(d)
    reg = from_registry(evidence.registry) if evidence.registry is not None else None
    if reg is not None:
        out.append(reg)

    merged: dict[str, DefinitionSource] = {}
    for d in out:
        key = _norm(d.formula_sql)
        prior = merged.get(key)
        if prior is None:
            merged[key] = d
            continue
        # Keep the stronger record: a verified claim, else the attributed one, else first.
        if (d.verified and not prior.verified) or \
           (d.verified == prior.verified and d.author and not prior.author):
            merged[key] = d

    executed = list(evidence.executed_sql or ())
    for d in merged.values():
        d.use_count = reliance(d.formula_sql, executed)
    return list(merged.values())
