"""Per-connection persistence for the Business Profile.

Mirrors the explorer-store pattern: a plain JSON file under data/, wrapping the
pydantic content with metadata the LLM should not author.
    data/business_profile_{connection_id}.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from aughor.profile.models import BusinessProfile

_DATA_DIR = Path("data")


def _path(connection_id: str) -> Path:
    safe = connection_id.replace("/", "_")
    return _DATA_DIR / f"business_profile_{safe}.json"


def save(connection_id: str, profile: BusinessProfile, *,
         schema_name: Optional[str] = None, model: Optional[str] = None,
         generated_at: Optional[str] = None,
         recipes: Optional[list] = None) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "connection_id": connection_id,
        "schema_name": schema_name,
        "model": model,
        "generated_at": generated_at,
        "profile": profile.model_dump(),
        # Per-metric computation recipes (curated industry KB + LLM fallback) — the
        # SQL-accuracy knowledge the explorer injects into Phase-8 generation.
        "recipes": recipes or [],
    }
    _path(connection_id).write_text(json.dumps(payload, indent=2, default=str))


def load_raw(connection_id: str) -> Optional[dict]:
    """The full stored payload (profile + metadata), or None."""
    p = _path(connection_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def load(connection_id: str) -> Optional[BusinessProfile]:
    """The typed BusinessProfile, or None if absent/corrupt."""
    raw = load_raw(connection_id)
    if not raw or "profile" not in raw:
        return None
    try:
        return BusinessProfile(**raw["profile"])
    except Exception:
        return None


def load_recipes(connection_id: str) -> list[dict]:
    """The stored per-metric computation recipes, or []."""
    raw = load_raw(connection_id)
    return (raw or {}).get("recipes", []) if raw else []


def invalidate(connection_id: str) -> None:
    p = _path(connection_id)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
