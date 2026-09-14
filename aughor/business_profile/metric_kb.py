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
    """All curated industry KB files (cached). Tuple so it's hashable/cacheable.

    Each KB carries its ``id``, the file stem ("airline", "retail", …): the closed name an industry
    text resolves to (:func:`industry_id`) and the tag playbook retrieval is scoped by."""
    kbs = []
    if _KB_DIR.exists():
        for f in sorted(_KB_DIR.glob("*.json")):
            try:
                kb = json.loads(f.read_text())
            except Exception as exc:
                logger.warning("industry KB %s failed to load: %s", f.name, exc)
                continue
            kb.setdefault("id", f.stem)
            kbs.append(kb)
    return tuple(kbs)


#: Words that name an industry no curated KB covers yet. A generic alias ("retail", "subscription",
#: "marketplace") never lends its KB to an industry text that also names one of these: a bank is not a
#: retailer because it offers retail banking, and a telecom is not a software business because it sells
#: subscriptions. A word leaves this list when a KB for its industry lands and claims it as an alias
#: (tests/unit/test_industry_match.py fails while a word is both).
_UNCURATED_INDUSTRY_TERMS: tuple[str, ...] = (
    # financial services
    "bank", "banks", "banking", "lending", "lender", "loan", "loans", "mortgage", "mortgages",
    "credit union", "fintech", "payments", "brokerage", "wealth management", "asset management",
    "insurance", "insurer", "reinsurance",
    # health
    "healthcare", "health care", "hospital", "hospitals", "clinic", "clinics", "medical", "pharma",
    "pharmaceutical", "pharmaceuticals", "biotech", "life sciences",
    # communications, media, entertainment
    "telecom", "telecoms", "telecommunications", "telco", "broadband", "media", "streaming",
    "publishing", "broadcasting", "entertainment", "music", "gaming", "games", "casino", "betting",
    "gambling",
    # travel and property
    "travel", "tourism", "hotel", "hotels", "hospitality", "lodging", "accommodation", "cruise",
    "real estate", "property management", "proptech",
    # energy, public sector, education
    "energy", "utility", "utilities", "electricity", "oil and gas", "government", "public sector",
    "nonprofit", "non profit", "charity", "education", "edtech", "university", "universities",
    "school", "schools",
    # other verticals
    "automotive", "dealership", "dealerships", "wholesale", "wholesaler", "construction",
    "agriculture", "advertising", "adtech", "restaurant", "restaurants", "qsr", "mobility",
    "rideshare", "ride hailing", "taxi", "car rental", "legal", "law firm", "consulting",
)


def _words(s: str) -> list[str]:
    """Lowercase alphanumeric words in order: "E-commerce" → ["e", "commerce"]."""
    return [w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if w]


def _names(words: list[str], phrase: str) -> bool:
    """Whether ``phrase`` occurs in ``words`` as whole consecutive words, a plural "s" allowed on its last
    word: "carrier" names "Air Carriers", and "oem" never names "poem"."""
    target = _words(phrase)
    n = len(target)
    for i in range(len(words) - n + 1) if n else ():
        window = words[i:i + n]
        if window[:-1] == target[:-1] and window[-1] in (target[-1], target[-1] + "s"):
            return True
    return False


def _sole_best(scored: list[tuple[tuple[int, int], dict]]) -> Optional[dict]:
    """The highest-scoring KB, or None on a tie — a tie is a guess, and a wrong KB is worse than none."""
    scored = sorted(scored, key=lambda s: s[0], reverse=True)
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


def match_industry(industry: str) -> Optional[dict]:
    """Pick the curated industry KB an industry text names. Returns None if none does (→ LLM fallback).

    Names and aliases match as whole words, never as substrings. A KB's ``generic_aliases`` — a business
    model, channel or category several industries share ("retail", "subscription", "marketplace",
    "carrier") — decide only when no KB is named by a specific alias AND the text names no uncurated
    industry. The substring test this replaces gave "Retail Banking" the retail KB and "Online Travel
    Marketplace" the food-delivery one."""
    words = _words(industry)
    if not words:
        return None
    specific: list[tuple[tuple[int, int], dict]] = []
    generic: list[tuple[tuple[int, int], dict]] = []
    for kb in load_industry_kbs():
        weak = {tuple(_words(a)) for a in kb.get("generic_aliases", [])}
        strong_hits: set[str] = set()
        weak_hits: set[str] = set()
        for alias in [kb.get("industry", "")] + list(kb.get("aliases", [])):
            if alias and _names(words, alias):
                (weak_hits if tuple(_words(alias)) in weak else strong_hits).add(alias)
        hits, bucket = (strong_hits, specific) if strong_hits else (weak_hits, generic)
        if hits:
            bucket.append(((len(hits), sum(len(_words(h)) for h in hits)), kb))
    if specific:
        return _sole_best(specific)
    if generic and not any(_names(words, t) for t in _UNCURATED_INDUSTRY_TERMS):
        return _sole_best(generic)
    return None


def industry_id(industry: str) -> str:
    """The curated industry an industry text names, as its KB id ("airline", "retail", …), or ""."""
    kb = match_industry(industry)
    return str(kb.get("id") or "") if kb else ""


@lru_cache(maxsize=1)
def _kb_entry_industries() -> dict[str, str]:
    """``{deep-KB entry id: the industry whose kb_files hold it}``. An entry from a file no industry
    claims (finance, marketing, product, the generic metrics) is absent: every industry may read it."""
    out: dict[str, str] = {}
    for kb in load_industry_kbs():
        for stem in kb.get("kb_files", []):
            try:
                items = json.loads((_KB_DIR.parent / f"{stem}.json").read_text())
            except Exception as exc:
                logger.warning("industry KB %s names kb file %s, which failed to load: %s",
                               kb.get("id"), stem, exc)
                continue
            for e in items if isinstance(items, list) else [items]:
                if isinstance(e, dict) and e.get("id"):
                    out[str(e["id"])] = str(kb.get("id") or "")
    return out


def kb_entry_industry(kb_entry_id: Optional[str]) -> str:
    """The industry a deep-KB entry belongs to, or "" for an entry every industry may read."""
    return _kb_entry_industries().get(kb_entry_id or "", "")


def industry_scope(connection_id: str, schema_name: Optional[str] = None, *,
                   industry: Optional[str] = None) -> Optional[str]:
    """Which industry's knowledge a connection reads.

    A curated id ("airline") means that industry's entries plus the ones every industry shares; ""
    means an industry is known but no curated KB covers it, so only the shared entries; None means
    nothing is known about the industry, so nothing is scoped.

    ``industry`` is text a caller has already resolved (the explorer's effective industry). Without it,
    the organisation's declared industry wins, then the connection's STORED profile — a read, never an
    inference. Any failure answers None, which reads everything, as before scoping existed."""
    text = industry
    if text is None:
        try:
            from aughor.business_profile.store import load_raw
            from aughor.orgsettings import resolve_industry
            from aughor.workspace.store import workspace_for_connection
            raw = load_raw(connection_id, schema_name) or {}
            profiled = str((raw.get("profile") or {}).get("industry") or "")
            text = resolve_industry(profiled, workspace_for_connection(connection_id))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "industry scope is best-effort; unscoped knowledge is read instead",
                     counter="industry_scope.resolve")
            return None
    text = (text or "").strip()
    return industry_id(text) if text else None


@lru_cache(maxsize=16)
def metric_vocabulary(industry: str = "") -> tuple:
    """The recognized metric vocabulary for an industry — ``((token, canonical_label, formula), …)``
    built from the curated KB matched to ``industry`` (or the union of ALL KBs when nothing matches).
    Each metric contributes its name + every alias as a normalized token. This is the deterministic,
    data-driven vocabulary a coherence check uses to recognize WHICH metric a query or claim names —
    so airline (load factor, RASM) and manufacturing (OEE, yield) are covered by their JSON, with no
    hardcoded per-metric list. Returns a tuple so it stays hashable/cacheable."""
    kb = match_industry(industry) if industry else None
    kbs = [kb] if kb else list(load_industry_kbs())
    seen: dict = {}
    for one in kbs:
        if not one:
            continue
        for m in one.get("metrics", []):
            label = m.get("name") or ""
            formula = m.get("formula") or ""
            for tok in [label] + list(m.get("aliases", [])):
                t = _norm(tok)
                if t and t not in seen:
                    seen[t] = (t, label, formula)
    return tuple(seen.values())


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
    from aughor.orgsettings import resolve_industry
    usr = (
        f"INDUSTRY: {resolve_industry(profile.industry)} ({profile.business_model})\n\n"
        f"SCHEMA:\n{schema}\n\n"
        f"Write a recipe for EACH of these metrics:\n{names}"
    )
    out: _Recipes = get_provider("coder").complete(
        system=sys, user=usr, response_model=_Recipes, temperature=0.1)
    return [{**r.model_dump(), "source": "llm-fallback"} for r in out.recipes]
