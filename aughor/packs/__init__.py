"""Specialist Agents / Domain Expertise Packs (Phase A · P0).

A pack is a declarative FOLDER that declares a domain expert's *intent* — persona, metric
recipes, entity ROLE bindings, the questions it owns, playbooks, a surface, and evals. The
existing engine (ADA / Insight / Explorer) is unchanged; a pack only injects steering
metadata at intake, and aughor's grounding compiles that intent against the real warehouse.

P0 ships the spec + loader + validator + feature flag (no LLM, no connection). The
entity-binding resolver (the deploy-time grounding crux) is P1. See
docs/DOMAIN_EXPERTISE_PACKS.md and docs/DOMAIN_EXPERTISE_PACKS_10X.md.
"""
from aughor.packs.models import (
    Pack,
    PackManifest,
    PackMetric,
    PackQuestions,
    PackPlaybook,
    PackSurface,
    PackEval,
    RoleSpec,
)
from aughor.packs.loader import load_pack, list_packs, PacksError
from aughor.packs.validate import validate_pack, ValidationReport

__all__ = [
    "Pack", "PackManifest", "PackMetric", "PackQuestions", "PackPlaybook",
    "PackSurface", "PackEval", "RoleSpec",
    "load_pack", "list_packs", "PacksError",
    "validate_pack", "ValidationReport",
]
