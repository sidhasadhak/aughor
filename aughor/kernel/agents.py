"""The seed of the Phase-0 agent registry.

A minimal map from a job ``kind`` to the named agent that runs it, so the Fleet
view reads as *agents* (Scout, Analyst) rather than opaque job kinds. The full
charter (role · goal · tools · budget · memory) comes later — this is the
smallest thing that makes the autonomy we already run legible as a fleet.

See docs/AGENTIC_ARCHITECTURE.md §6-7 and docs/MOTHERDUCK_LEARNINGS.md R2/R5.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AgentInfo:
    agent: str   # display name (the role)
    blurb: str   # one line: what it does
    icon: str    # a glyph for the Fleet view

    def to_dict(self) -> dict:
        return asdict(self)


# job kind → the agent that runs it. The commented entries are reserved: they get
# registered when monitors/briefs/profile move under the kernel (Phase 0 proper),
# at which point they appear in the Fleet view automatically.
AGENTS: dict[str, AgentInfo] = {
    "exploration":           AgentInfo("Scout",   "Explores your data and surfaces findings", "telescope"),
    "investigation":         AgentInfo("Analyst", "Root-causes a question with evidence",     "microscope"),
    "investigation_salvage": AgentInfo("Analyst", "Recovers an interrupted investigation",    "microscope"),
    # "monitor": AgentInfo("Watcher", "Watches KPIs and raises alerts",   "radar"),
    # "brief":   AgentInfo("Briefer", "Synthesizes the briefing verdict", "newspaper"),
    # "profile": AgentInfo("Curator", "Keeps the profile and ontology fresh", "folder"),
}

_UNKNOWN = AgentInfo("Worker", "Background work", "gear")


def agent_for(kind: str | None) -> AgentInfo:
    """The agent that runs jobs of this kind (never raises; unknown → a generic Worker)."""
    return AGENTS.get(kind or "", _UNKNOWN)
