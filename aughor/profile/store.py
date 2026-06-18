"""Per-(connection, schema) persistence for the Business Profile.

Mirrors the explorer-store pattern: a plain JSON file under data/, wrapping the
pydantic content with metadata the LLM should not author.

    data/business_profile_{connection_id}.json            # the connection default
    data/business_profile_{connection_id}__{schema}.json  # a schema-scoped profile

A connection can expose several schemas (e.g. a warehouse with analytics + ecommerce),
each a different "business". Keying by (connection, schema) lets the Briefing's KPI strip
and dashboard show metrics for the SELECTED schema instead of one frozen connection-level
profile. `schema_name=None` is the connection default (also the legacy file name, so
existing profiles keep loading). A schema-scoped lookup falls back to the legacy file ONLY
when that file was itself built for the requested schema — never serving another schema's
metrics for a selection it doesn't match.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from aughor.profile.models import BusinessProfile

_DATA_DIR = Path("data")


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def _path(connection_id: str) -> Path:
    return _DATA_DIR / f"business_profile_{_safe(connection_id)}.json"


def save(connection_id: str, profile: BusinessProfile, *,
         schema_name: Optional[str] = None, model: Optional[str] = None,
         generated_at: Optional[str] = None,
         recipes: Optional[list] = None) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "connection_id": connection_id,
        "schema_name": schema_name,   # WHICH schema this profile describes (matched on read)
        "model": model,
        "generated_at": generated_at,
        "profile": profile.model_dump(),
        # Per-metric computation recipes (curated industry KB + LLM fallback) — the
        # SQL-accuracy knowledge the explorer injects into Phase-8 generation.
        "recipes": recipes or [],
    }
    _path(connection_id).write_text(json.dumps(payload, indent=2, default=str))


def load_raw(connection_id: str, schema_name: Optional[str] = None) -> Optional[dict]:
    """The full stored payload (profile + metadata), or None.

    The explorer stores ONE profile per connection (its configured schema), tagging the
    schema it describes. A schema-scoped read returns it only when it MATCHES the requested
    schema — so the Briefing's KPI strip / dashboard show that schema's metrics or nothing,
    never another schema's (mismatch → None → available=False, and the strip/charts cleanly
    collapse). schema_name=None ('All schemas') always returns the connection default."""
    p = _path(connection_id)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text())
    except Exception:
        return None
    if schema_name and raw.get("schema_name") != schema_name:
        return None
    return raw


def load(connection_id: str, schema_name: Optional[str] = None) -> Optional[BusinessProfile]:
    """The typed BusinessProfile, or None if absent/corrupt."""
    raw = load_raw(connection_id, schema_name)
    if not raw or "profile" not in raw:
        return None
    try:
        return BusinessProfile(**raw["profile"])
    except Exception:
        return None


def load_recipes(connection_id: str, schema_name: Optional[str] = None) -> list[dict]:
    """The stored per-metric computation recipes, or []."""
    raw = load_raw(connection_id, schema_name)
    return (raw or {}).get("recipes", []) if raw else []


def invalidate(connection_id: str, schema_name: Optional[str] = None) -> None:
    """Delete the scoped profile, or ALL of a connection's profiles when schema_name is
    None (so deleting a connection clears every schema's profile, not just the default)."""
    if schema_name:
        targets = [_path(connection_id, schema_name)]
    else:
        targets = list(_DATA_DIR.glob(f"business_profile_{_safe(connection_id)}*.json"))
    for p in targets:
        try:
            p.unlink()
        except Exception:
            pass
