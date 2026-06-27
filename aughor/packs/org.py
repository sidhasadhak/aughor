"""Expert org (Bet 3) — debate, conflict resolution, escalation.

When several specialists answer one question they can disagree (e.g. two definitions of
'revenue'). The rule: a GOVERNED canonical metric always wins; packs may only NARROW it,
never redefine it (DOMAIN_EXPERTISE_PACKS.md §12). Escalation lets one expert hand a finding
to the domain that owns it. Pure helpers over plain data; the fan-out itself reuses the
existing synthesis path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MetricClaim:
    pack_id: str
    definition: str


@dataclass
class MetricResolution:
    winner: str                 # pack id, or "governed"
    definition: str
    conflict: bool              # did the claims disagree?
    note: str = ""


def resolve_metric_definition(
    metric_name: str,
    claims: list[MetricClaim],
    governed_definition: Optional[str] = None,
) -> MetricResolution:
    """Resolve competing definitions of one metric across packs. A governed canonical wins
    outright; otherwise the conflict is surfaced (never silently merged)."""
    distinct = {c.definition.strip() for c in claims if c.definition.strip()}
    conflict = len(distinct) > 1
    if governed_definition:
        return MetricResolution(
            winner="governed", definition=governed_definition, conflict=conflict,
            note=("packs disagreed; governed canonical wins (packs may only narrow it)"
                  if conflict else "governed canonical"))
    if not claims:
        return MetricResolution(winner="", definition="", conflict=False, note="no claims")
    return MetricResolution(
        winner=claims[0].pack_id, definition=claims[0].definition, conflict=conflict,
        note=("CONFLICT — no governed canonical to arbitrate; surface to the user"
              if conflict else "single definition"))


@dataclass
class Escalation:
    from_pack: str
    to_domain: str
    reason: str


def route_escalation(from_pack: str, to_domain: str, reason: str) -> Escalation:
    """A specialist hands a finding to the domain that actually owns it (e.g. a 'churn spike'
    that's really a billing artifact → RevOps/Finance)."""
    return Escalation(from_pack=from_pack, to_domain=to_domain, reason=reason)
