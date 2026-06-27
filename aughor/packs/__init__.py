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
from aughor.packs.resolver import (
    SchemaFacts, TableFact, ColumnFact, BindingCandidate,
    propose_bindings, binding_report, verify_binding_columns,
)
from aughor.packs.evalrunner import run_pack_evals, check_expectation
from aughor.packs.adapter import schema_facts_from_table_cols
from aughor.packs.bindings import save_binding, load_binding, is_bound
from aughor.packs.routing import select_pack, rank_packs, score_pack
from aughor.packs.inject import build_injection, PackInjection
from aughor.packs.trust import autonomy_tier, routing_weight, tier_allows
from aughor.packs.evalgate import evaluate_activation, EvalResult, ActivationDecision
from aughor.packs.flywheel import distill_deltas, PackDelta, DistillResult
from aughor.packs.org import resolve_metric_definition, MetricClaim, route_escalation
from aughor.packs.mandate import Mandate, evaluate_mandate, MandateOutcome
from aughor.packs.marketplace import import_readiness, ImportReadiness
from aughor.packs.instruments import Instrument, can_invoke

__all__ = [
    "Pack", "PackManifest", "PackMetric", "PackQuestions", "PackPlaybook",
    "PackSurface", "PackEval", "RoleSpec",
    "load_pack", "list_packs", "PacksError",
    "validate_pack", "ValidationReport",
    "SchemaFacts", "TableFact", "ColumnFact", "BindingCandidate",
    "propose_bindings", "binding_report",
]
