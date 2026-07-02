"""Declarative mode manifest (P5, AI-FDE Pillar C).

AI FDE structures its agent as version-controlled `agents.md`/`skill.md` files: a mode
declares the task context, which tools/docs it loads, and how it approaches the problem.
Aughor's four routing modes (direct/investigate/explore/final_text) are structurally wired
to graph branches, so the STRUCTURE stays in code — but a mode's *tunable* config (how it's
routed to, how lean its context is, which playbooks it pulls) becomes an editable manifest
here, so behaviour can be tuned per-deployment without a code change. Mirrors the already-
declarative Domain Expertise Packs (`packs/loader.py`).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SchemaScope(BaseModel):
    """How lean this mode's working context should be (feeds the P2 context surface).
    AI FDE: a mode loads only the tools/tables relevant to its task."""
    top_k_tables: int = 4          # schema-linker breadth
    max_tables: int = 10           # hard context cap


class ModeManifest(BaseModel):
    name: str
    description: str = ""
    # Regex patterns that, when a question matches, route it to THIS mode (a
    # deterministic override on top of the LLM classifier). Editing this list tunes
    # routing without touching code — the file-driven behaviour P5 proves.
    route_keywords: list[str] = Field(default_factory=list)
    # Only apply the keyword override when the classifier's mode is one of these
    # (empty = apply from any mode). Captures conditional rules like
    # "explore→investigate for driver questions".
    route_from: list[str] = Field(default_factory=list)
    schema_scope: SchemaScope = Field(default_factory=SchemaScope)
    playbook_refs: list[str] = Field(default_factory=list)
    enabled: bool = True
