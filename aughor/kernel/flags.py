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
