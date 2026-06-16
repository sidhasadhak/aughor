"""Industry metric-knowledge resolver.

Connects a connection's inferred BusinessProfile to curated, per-industry metric
recipes (formula + grain + anti-patterns) under data/kb/industry/*.json, with an
LLM fallback for metrics no curated entry covers. The recipe is what the explorer
injects into Phase-8 SQL generation — the lever for SQL ACCURACY (it carries the
canonical grain/join and the anti-pattern that avoids bugs like conversion > 1).
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_KB_DIR = Path(__file__).parent.parent.parent / "data" / "kb" / "industry"


def _norm(s: str) -> str:
    """Aggressive normalize for matching: alnum-only, lowercase."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 2}


@lru_cache(maxsize=1)
def load_industry_kbs() -> tuple[dict, ...]:
    """All curated industry KB files (cached). Tuple so it's hashable/cacheable."""
    kbs = []
    if _KB_DIR.exists():
        for f in sorted(_KB_DIR.glob("*.json")):
            try:
                kbs.append(json.loads(f.read_text()))
            except Exception as exc:
                logger.warning("industry KB %s failed to load: %s", f.name, exc)
    return tuple(kbs)


def match_industry(industry: str) -> Optional[dict]:
    """Pick the curated industry KB whose name/aliases best match the profile's
    industry string. Returns None if nothing matches (→ pure LLM fallback)."""
    if not industry:
        return None
    target = _norm(industry)
    best, best_score = None, 0
    for kb in load_industry_kbs():
        cands = [kb.get("industry", "")] + list(kb.get("aliases", []))
        score = sum(1 for c in cands if c and _norm(c) in target)
        if score > best_score:
            best, best_score = kb, score
    return best if best_score > 0 else None


def match_metric(kb: dict, metric_name: str) -> Optional[dict]:
    """Find the curated recipe in `kb` for a profile metric, by name/alias
    containment then token overlap."""
    if not kb:
        return None
    tn = _norm(metric_name)
    tt = _tokens(metric_name)
    best, best_overlap = None, 0.0
    for m in kb.get("metrics", []):
        names = [m.get("name", "")] + list(m.get("aliases", []))
        for nm in names:
            nn = _norm(nm)
            if nn and (nn in tn or tn in nn):
                return m
        # token-overlap fallback (Jaccard on the metric name)
        mt = _tokens(m.get("name", ""))
        if tt and mt:
            ov = len(tt & mt) / len(tt | mt)
            if ov > best_overlap:
                best, best_overlap = m, ov
    return best if best_overlap >= 0.5 else None


def _recipe_from_curated(m: dict, kb_industry: str) -> dict:
    return {
        "metric": m.get("name"),
        "formula": m.get("formula"),
        "grain": m.get("grain"),
        "anti_patterns": m.get("anti_patterns", []),
        "sane_range": m.get("sane_range"),
        "source": f"curated:{kb_industry}",
    }


def resolve_recipes(profile, schema: str) -> list[dict]:
    """For each of the profile's north-star metrics, return a computation recipe:
    curated (preferred) else a single-batch LLM-generated fallback grounded to the
    schema. Best-effort — a metric with no recipe is simply omitted (the explorer
    still has the profile's definition + maps_to)."""
    kb = match_industry(getattr(profile, "industry", ""))
    recipes: list[dict] = []
    uncovered = []  # (metric_name, definition, maps_to)
    for m in getattr(profile, "north_star_metrics", []):
        cur = match_metric(kb, m.name) if kb else None
        if cur:
            recipes.append(_recipe_from_curated(cur, kb.get("industry", "?")))
        else:
            uncovered.append(m)

    if uncovered:
        try:
            recipes.extend(_llm_fallback_recipes(profile, uncovered, schema))
        except Exception as exc:
            logger.warning("[metric_kb] LLM fallback recipes failed (non-fatal): %s", exc)

    logger.info(
        "[metric_kb] resolved %d recipes for %r (industry KB=%s): %d curated, %d llm-fallback",
        len(recipes), getattr(profile, "industry", "?"),
        kb.get("industry") if kb else "none",
        sum(1 for r in recipes if str(r.get("source", "")).startswith("curated")),
        sum(1 for r in recipes if r.get("source") == "llm-fallback"),
    )
    return recipes


def _llm_fallback_recipes(profile, uncovered: list, schema: str) -> list[dict]:
    """One batched LLM call: canonical formula + grain + anti-patterns for metrics
    the curated KB doesn't cover (e.g. a niche vertical), grounded to the schema."""
    from pydantic import BaseModel
    from aughor.llm.provider import get_provider

    class _Recipe(BaseModel):
        metric: str
        formula: str
        grain: str
        anti_patterns: list[str]
        sane_range: str

    class _Recipes(BaseModel):
        recipes: list[_Recipe]

    names = "\n".join(f"  - {m.name}: {m.definition} [maps to {m.maps_to}]" for m in uncovered)
    sys = (
        "You write canonical metric computation recipes for an autonomous SQL "
        "analyst. For each metric give the correct formula, the grain to compute at "
        "(with how to aggregate/pre-aggregate to avoid cardinality bugs), the "
        "anti-patterns that produce wrong numbers, and a sane unit/range. Ground "
        "everything in the real schema columns. A ratio metric must be bounded "
        "0..1 unless expansion-type (call that out)."
    )
    usr = (
        f"INDUSTRY: {profile.industry} ({profile.business_model})\n\n"
        f"SCHEMA:\n{schema}\n\n"
        f"Write a recipe for EACH of these metrics:\n{names}"
    )
    out: _Recipes = get_provider("coder").complete(
        system=sys, user=usr, response_model=_Recipes, temperature=0.1)
    return [{**r.model_dump(), "source": "llm-fallback"} for r in out.recipes]
