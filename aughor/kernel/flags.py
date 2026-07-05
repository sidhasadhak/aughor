"""Runtime feature flags — operator-toggleable, env-var fallback.

A handful of capabilities ship off-by-default because they cost (per-row LLM calls,
per-table version probes). They were previously env-only (`AUGHOR_AI_SQL`,
`AUGHOR_SNAPSHOT_RECEIPTS`), so an operator had to restart the process to flip them.
This stores an override in the kernel ledger kv so the UI can toggle them at runtime;
when no override is set, the env var still decides.

`flag_enabled(name)` is the resolver the feature code calls. The override is read from
SQLite per call (one indexed kv read — negligible; these aren't ultra-hot paths).
"""
from __future__ import annotations

import os

from aughor.kernel.ledger import Ledger

_STORE = "feature_flags"

# Registered flags: logical name → the env var that decides when no override is set.
FLAG_ENV = {
    "ai_sql": "AUGHOR_AI_SQL",
    "snapshot_receipts": "AUGHOR_SNAPSHOT_RECEIPTS",
    "explorer.synthesis_incremental": "AUGHOR_SYNTHESIS_INCREMENTAL",
    "specialist_packs": "AUGHOR_SPECIALIST_PACKS",
    "explore.parallel_subq": "AUGHOR_EXPLORE_PARALLEL",
    "ada.parallel_lenses": "AUGHOR_ADA_PARALLEL_LENSES",
    "ada.why_where_interaction": "AUGHOR_ADA_WHY_WHERE_INTERACTION",
    "trust.verify_facade": "AUGHOR_TRUST_FACADE",
    "trust.verify_live": "AUGHOR_TRUST_VERIFY_LIVE",
    "semantic.resolve_live": "AUGHOR_SEMANTIC_RESOLVE_LIVE",
    "capability.pipeline_live": "AUGHOR_CAPABILITY_PIPELINE_LIVE",
}

# Human-facing copy for the Settings UI.
FLAG_META = {
    "ai_sql": {
        "label": "In-SQL AI operators",
        "description": "Register the governed prompt()/embedding() UDFs and let the generator use them. Makes per-row LLM calls — enable deliberately.",
    },
    "snapshot_receipts": {
        "label": "Snapshot-pinned receipts",
        "description": "Pin every finding to the exact data version it ran against (reproducible-as-of). The version probe touches the DB on each emit.",
    },
    "explorer.synthesis_incremental": {
        "label": "Incremental synthesis",
        "description": "Fire cross-finding synthesis the moment a new finding creates a combinable pair, not only at end-of-run. More 'alive', more compute. Phase 9 always runs at end-of-run regardless.",
    },
    "specialist_packs": {
        "label": "Specialist Agents (Domain Expertise Packs)",
        "description": "Load user-built specialist packs (packs/) and let them steer the engine at intake. Off by default while the subsystem lands — see docs/DOMAIN_EXPERTISE_PACKS.md.",
    },
    "explore.parallel_subq": {
        "label": "Parallel explore sub-questions",
        "description": "Run independent explore sub-questions concurrently in dependency-respecting waves (map-reduce over the operator.add state) instead of one-at-a-time. Cuts wall-clock on multi-cut investigations; multiplies concurrent LLM calls (bounded by the fan-out width cap + the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "ada.parallel_lenses": {
        "label": "Parallel Deep-Analysis lenses",
        "description": "For a cross-sectional Deep-Analysis ('why is X high/low'), run independent investigative lenses (segment/where ∥ mechanism/why) concurrently instead of one bundled scan — a deeper, multi-angle answer at ~flat wall-clock. Multiplies concurrent LLM calls (bounded by the P6 token budget). Off by default — see docs/PARALLEL_MULTIAGENT_GROUNDWORK.md.",
    },
    "ada.why_where_interaction": {
        "label": "WHY×WHERE interaction lens",
        "description": "After the parallel WHERE and WHY lenses, forward-chain one more query crossing the leading return reason with the highest-impact segment — does the cause concentrate where the metric is worst (→ target that segment) or is it uniform (→ a broad problem)? Turns two independent findings into the actionable link. Adds one LLM-planned query per qualifying run; requires 'Parallel Deep-Analysis lenses'. Off by default.",
    },
    "trust.verify_facade": {
        "label": "Unified trust.verify façade",
        "description": "Route SQL validation through the one Trust-plane façade (aughor/trust) — one Verdict composing the read-only/mutation gate, E1 footguns, preflight repair, and value-domain/fan-out probes — instead of a per-path guard subset. Adds the AST read-only gate to the /query/validate surface (closes SEC-02 there). Off by default while the plane lands (AL-01).",
    },
    "trust.verify_live": {
        "label": "Trust plane on the deep answer path",
        "description": "In the Deep-Analysis executor, route every generated SQL through trust.verify before execute — the AST read-only BLOCK the generation path never ran (defence-in-depth; the connection layer is already fail-closed). A blocked statement returns a blocked result instead of executing. Off by default (AL-01 live migration).",
    },
    "semantic.resolve_live": {
        "label": "Semantic plane resolved at the router",
        "description": "Resolve the Semantic plane (metrics · ontology · profile · KB) once when a deep investigation is seeded and attach the SemanticContext to the run state, so every node reads one consistent context instead of re-consulting ad-hoc. Off by default (AL-05 live migration).",
    },
    "capability.pipeline_live": {
        "label": "Capability plane answer path",
        "description": "Enable the end-to-end Capability-plane answer path (/query/capability-answer): a data question runs generate → validate (trust.verify) → execute → interpret through the one CapabilityPipeline template. Off by default (AL-02 live migration).",
    },
}


def _env_bool(var: str) -> bool:
    return os.getenv(var, "").strip().lower() in ("1", "true", "yes", "on")


def _override(name: str):
    return Ledger.default().kv_get(_STORE, name, None)


def flag_enabled(name: str) -> bool:
    """The effective value: a runtime override wins; otherwise the env var decides."""
    ov = _override(name)
    if ov is not None:
        return bool(ov)
    return _env_bool(FLAG_ENV.get(name, ""))


def set_flag(name: str, value: bool) -> None:
    """Set a runtime override (wins over the env var until cleared)."""
    Ledger.default().kv_put(_STORE, name, bool(value))


def clear_flag(name: str) -> None:
    """Drop the override so the env var decides again."""
    Ledger.default().kv_put(_STORE, name, None)


def list_flags() -> dict:
    """All registered flags with their effective value + source, for the Settings UI."""
    out = {}
    for name, var in FLAG_ENV.items():
        ov = _override(name)
        meta = FLAG_META.get(name, {})
        out[name] = {
            "value": bool(ov) if ov is not None else _env_bool(var),
            "source": "runtime" if ov is not None else "env",
            "env_var": var,
            "label": meta.get("label", name),
            "description": meta.get("description", ""),
        }
    return out
