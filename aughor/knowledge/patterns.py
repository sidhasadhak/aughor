"""
Pattern Library — extracts recurring patterns from domain intelligence.

A pattern is a theme that appears consistently across multiple domains, angles,
or entity references, suggesting a stable characteristic of the business rather
than a one-time observation.

Pattern types:
  angle      — same analytical angle (e.g. "Seasonality") recurs across ≥2 domains
  entity     — same table/entity drives findings across ≥2 domains
  convergence — ≥2 high-novelty (≥6) insights all point to the same angle

Patterns are extracted from already-computed domain insights — no LLM or DB
queries required. Results are cached per-connection with a 6-hour TTL.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "patterns_cache.json"
_CACHE_TTL_HOURS = 6


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pattern_id(connection_id: str, kind: str, key: str) -> str:
    raw = f"{connection_id}:{kind}:{key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _age_hours(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 9999


# ── Core extraction ───────────────────────────────────────────────────────────

def extract_patterns(
    domain_data: dict[str, list[dict]],
    connection_id: str,
) -> list[dict[str, Any]]:
    """
    Extract patterns from domain insight data.

    Args:
        domain_data: {domain_name: [insight_dict, ...]}  (already grouped by domain)
        connection_id: used for stable pattern IDs

    Returns:
        List of pattern dicts sorted by descending strength.
    """
    # Flatten all insights, tagging each with its domain
    all_insights: list[dict] = []
    for domain, insights in domain_data.items():
        for ins in insights:
            flat = dict(ins) if isinstance(ins, dict) else {}
            flat.setdefault("domain", domain)
            all_insights.append(flat)

    if len(all_insights) < 3:
        return []

    patterns: list[dict] = []
    seen_ids: set[str] = set()

    # ── 1. Angle patterns ─────────────────────────────────────────────────────
    # Same analytical angle recurring across ≥2 domains with ≥3 total insights

    by_angle: dict[str, list[dict]] = defaultdict(list)
    for ins in all_insights:
        angle = (ins.get("angle") or "").strip()
        if angle:
            by_angle[angle].append(ins)

    for angle, insights in by_angle.items():
        domains_in = sorted({i.get("domain", "") for i in insights if i.get("domain")})
        if len(domains_in) < 2 or len(insights) < 3:
            continue

        avg_nov = sum(i.get("novelty", 3) for i in insights) / len(insights)
        top = sorted(insights, key=lambda i: i.get("novelty", 0), reverse=True)[:3]
        entities = list({
            e for i in insights
            for e in (i.get("entities_involved") or [])
        })
        strength = len(domains_in) * len(insights) * avg_nov

        pid = _pattern_id(connection_id, "angle", angle)
        seen_ids.add(pid)
        patterns.append({
            "id": pid,
            "type": "angle",
            "title": angle,
            "description": (
                f"This analytical angle recurs across {len(domains_in)} domain"
                f"{'s' if len(domains_in) > 1 else ''} with "
                f"{len(insights)} supporting finding{'s' if len(insights) > 1 else ''}."
            ),
            "domains": domains_in,
            "evidence_count": len(insights),
            "novelty": round(avg_nov, 1),
            "entities": entities[:10],
            "example_findings": [i.get("finding", "") for i in top],
            "_strength": strength,
        })

    # ── 2. Entity patterns ────────────────────────────────────────────────────
    # Same entity/table driving findings across ≥2 domains with ≥4 insights

    by_entity: dict[str, list[dict]] = defaultdict(list)
    for ins in all_insights:
        for entity in (ins.get("entities_involved") or []):
            by_entity[entity.lower()].append(ins)

    for entity, insights in by_entity.items():
        domains_in = sorted({i.get("domain", "") for i in insights if i.get("domain")})
        if len(domains_in) < 2 or len(insights) < 4:
            continue

        avg_nov = sum(i.get("novelty", 3) for i in insights) / len(insights)
        angles = sorted({(i.get("angle") or "") for i in insights if i.get("angle")})
        top = sorted(insights, key=lambda i: i.get("novelty", 0), reverse=True)[:3]
        strength = len(domains_in) * len(insights) * avg_nov

        label = entity.replace("_", " ").title()
        pid = _pattern_id(connection_id, "entity", entity)
        seen_ids.add(pid)
        patterns.append({
            "id": pid,
            "type": "entity",
            "title": f"{label} — cross-domain driver",
            "description": (
                f"{label} is a key driver across {len(domains_in)} domain"
                f"{'s' if len(domains_in) > 1 else ''}, "
                f"appearing in {len(insights)} findings from "
                f"{len(angles)} analytical angle{'s' if len(angles) > 1 else ''}."
            ),
            "domains": domains_in,
            "evidence_count": len(insights),
            "novelty": round(avg_nov, 1),
            "entities": [entity],
            "angles": angles[:6],
            "example_findings": [i.get("finding", "") for i in top],
            "_strength": strength,
        })

    # ── 3. High-novelty convergence ───────────────────────────────────────────
    # ≥2 high-novelty insights (≥6) all pointing to the same angle not already captured

    high = [i for i in all_insights if (i.get("novelty") or 0) >= 6]
    by_angle_h: dict[str, list[dict]] = defaultdict(list)
    for ins in high:
        angle = (ins.get("angle") or "General").strip()
        by_angle_h[angle].append(ins)

    for angle, insights in by_angle_h.items():
        if len(insights) < 2:
            continue
        pid = _pattern_id(connection_id, "convergence", angle)
        if pid in seen_ids:
            # Enrich existing angle pattern with high-novelty count
            for p in patterns:
                if p.get("title") == angle and p.get("type") == "angle":
                    p["high_novelty_count"] = len(insights)
            continue

        domains_in = sorted({i.get("domain", "") for i in insights if i.get("domain")})
        avg_nov = sum(i.get("novelty", 0) for i in insights) / len(insights)
        top = sorted(insights, key=lambda i: i.get("novelty", 0), reverse=True)[:3]
        entities = list({e for i in insights for e in (i.get("entities_involved") or [])})

        seen_ids.add(pid)
        patterns.append({
            "id": pid,
            "type": "convergence",
            "title": angle,
            "description": (
                f"{len(insights)} high-novelty findings all converge on this theme, "
                f"spanning {len(domains_in)} domain{'s' if len(domains_in) > 1 else ''}."
            ),
            "domains": domains_in,
            "evidence_count": len(insights),
            "novelty": round(avg_nov, 1),
            "entities": entities[:10],
            "example_findings": [i.get("finding", "") for i in top],
            "_strength": sum(i.get("novelty", 0) for i in insights),
        })

    # ── Sort + clean ──────────────────────────────────────────────────────────
    patterns.sort(key=lambda p: p.pop("_strength", 0), reverse=True)

    now = _now_iso()
    for p in patterns:
        p["computed_at"] = now

    return patterns


# ── Cache layer ───────────────────────────────────────────────────────────────

def get_patterns(
    connection_id: str,
    domain_data: dict[str, list[dict]],
    force_refresh: bool = False,
) -> list[dict]:
    """Return cached patterns if fresh, else recompute and cache."""
    if not force_refresh:
        try:
            if _CACHE_PATH.exists():
                cache = json.loads(_CACHE_PATH.read_text())
                entry = cache.get(connection_id)
                if entry and _age_hours(entry.get("computed_at", "")) < _CACHE_TTL_HOURS:
                    return entry["patterns"]
        except Exception:
            pass

    patterns = extract_patterns(domain_data, connection_id)

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if _CACHE_PATH.exists():
            try:
                existing = json.loads(_CACHE_PATH.read_text())
            except Exception:
                pass
        existing[connection_id] = {"computed_at": _now_iso(), "patterns": patterns}
        _CACHE_PATH.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass

    return patterns
