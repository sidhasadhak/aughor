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


def _path(connection_id: str, schema_name: Optional[str] = None) -> Path:
    base = f"business_profile_{_safe(connection_id)}"
    if schema_name:
        base += f"__{_safe(schema_name)}"
    return _DATA_DIR / f"{base}.json"


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
    _path(connection_id, schema_name).write_text(json.dumps(payload, indent=2, default=str))


def _read(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _anchor_metric_trends(raw: Optional[dict]) -> Optional[dict]:
    """Serve-time: re-anchor each north-star metric's ``chart_sql`` to the MOST RECENT N
    buckets. LLM-authored trend SQL uses ``ORDER BY <bucket> LIMIT N`` (ascending), which
    returns the OLDEST window — so on a multi-year dataset the briefing freezes on year-1
    and the KPI delta is computed on stale history. ``recent_window`` is a deterministic,
    idempotent, fail-open transform that ONLY touches a provably-ascending LIMITed time
    trend (a top-N breakdown is left untouched). Done here, at the single read chokepoint,
    so BOTH the /business-profile endpoint and the backend metric-moves get the fix — and
    existing stored profiles are corrected without a re-inference. Best-effort."""
    if not raw:
        return raw
    try:
        from aughor.sql.trend_window import recent_window
        for m in (raw.get("profile", {}).get("north_star_metrics") or []):
            cs = (m.get("chart_sql") or "").strip()
            if cs:
                m["chart_sql"] = recent_window(cs)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "serve-time trend re-anchor is best-effort; the stored chart_sql is "
                 "still returned (a stale-window trend, not a wrong number)",
                 counter="profile.trend_reanchor")
    return raw


def load_raw(connection_id: str, schema_name: Optional[str] = None) -> Optional[dict]:
    """The stored payload for a (connection, schema), or None.

    Each schema of a multi-schema connection has its OWN profile file
    (business_profile_{conn}__{schema}.json). A schema-scoped read returns that schema's
    profile or None (never another schema's) — so the Briefing's KPI strip / dashboard show
    the selected schema's metrics or cleanly collapse. schema_name=None ('All schemas')
    returns the connection-level file if present, else — for a connection that has exactly
    ONE schema profile — that single profile (so a single-schema connection's default view
    still resolves). With several schema profiles and no connection-level one, None (the
    aggregate view supplies the summary).

    Each metric's ``chart_sql`` is re-anchored to the most-recent window on read (see
    ``_anchor_metric_trends``)."""
    if schema_name:
        return _anchor_metric_trends(_read(_path(connection_id, schema_name)))
    conn_level = _read(_path(connection_id))
    if conn_level is not None:
        return _anchor_metric_trends(conn_level)
    scoped = sorted(_DATA_DIR.glob(f"business_profile_{_safe(connection_id)}__*.json"))
    if len(scoped) == 1:
        return _anchor_metric_trends(_read(scoped[0]))
    return None


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
