"""Static validation of a specialist pack (P0) — schema + structural rules, no connection.

This is the `pack validate` gate: it catches the errors we can find WITHOUT a warehouse
(missing manifest fields, illegal enums, a metric that binds a role the pack never declares,
an empty expert). The deploy-time checks that DO need a connection — role→column resolution
and dry-run/EXPLAIN of each recipe — are the resolver's job (P1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from aughor.packs.loader import load_pack, PacksError
from aughor.packs.models import Pack, VALID_GRAINS, VALID_STATUSES


@dataclass
class ValidationReport:
    pack_id: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_pack(path: Union[str, Path]) -> ValidationReport:
    """Load + statically validate the pack at `path`. A load failure (no/invalid manifest)
    is itself a single fatal error; otherwise we accumulate structural errors + warnings."""
    try:
        pack = load_pack(path)
    except PacksError as e:
        return ValidationReport(errors=[f"load failed: {e}"])
    return validate_loaded(pack)


def validate_loaded(pack: Pack) -> ValidationReport:
    """Validate an already-loaded Pack (so callers that hold one don't re-read the disk)."""
    r = ValidationReport(pack_id=pack.id)
    m = pack.manifest

    # ── manifest ──────────────────────────────────────────────────────────────
    if not (m.name or "").strip():
        r.errors.append("manifest: 'name' is required")
    if m.status not in VALID_STATUSES:
        r.errors.append(f"manifest: status {m.status!r} not in {VALID_STATUSES}")
    if m.default_temporal_grain not in VALID_GRAINS:
        r.errors.append(f"manifest: default_temporal_grain {m.default_temporal_grain!r} "
                        f"not in {VALID_GRAINS}")
    if not isinstance(m.scope, dict) or "connections" not in m.scope:
        r.warnings.append("manifest: scope has no 'connections' — defaulting to all")

    # ── metrics ↔ entity roles (the binding contract is checkable statically) ───
    declared_roles = set(pack.entities.keys())
    metric_names = set()
    for metric in pack.metrics:
        if not (metric.name or "").strip():
            r.errors.append("a metric is missing 'name'")
            continue
        metric_names.add(metric.name)
        if not (metric.formula or "").strip():
            r.warnings.append(f"metric {metric.name!r}: no formula")
        for role in metric.binds.required:
            if role not in declared_roles:
                r.errors.append(f"metric {metric.name!r} binds required role {role!r}, "
                                f"which is not declared in entities.yaml")
        for role in metric.binds.optional:
            if role not in declared_roles:
                r.warnings.append(f"metric {metric.name!r} binds optional role {role!r} "
                                  f"not declared in entities.yaml")

    # ── role spec sanity ───────────────────────────────────────────────────────
    for name, role in pack.entities.items():
        if role.default and role.one_of and role.default not in role.one_of:
            r.errors.append(f"role {name!r}: default {role.default!r} not in one_of {role.one_of}")

    # ── playbooks reference known metrics (warn — a metric may be KB-provided) ──
    for pb in pack.playbooks:
        if pb.trigger_metric and pb.trigger_metric not in metric_names:
            r.warnings.append(f"playbook trigger_metric {pb.trigger_metric!r} is not a pack metric")

    # ── completeness warnings (a pack that does nothing is rarely intended) ─────
    if not pack.metrics:
        r.warnings.append("no metrics defined")
    if not pack.entities:
        r.warnings.append("no entity roles declared — metrics cannot be ground-bound")
    if not (pack.questions.canonical or pack.questions.intent_tags):
        r.warnings.append("no canonical questions or intent_tags — routing cannot select this pack")
    if not pack.evals:
        r.warnings.append("no evals — the pack cannot be promotion-gated (Bet 2)")
    if not (pack.expertise or "").strip():
        r.warnings.append("no expertise.md — the expert has no reasoning persona")

    return r
