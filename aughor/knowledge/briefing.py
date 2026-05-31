"""
Briefing Synthesis — M24b

Generates an LLM-authored executive narrative from cross-domain intelligence.

The narrator reads the top findings and patterns, then writes a 2-3 sentence
brief that connects them with inline citation markers [1], [2], etc.

Each citation maps back to a specific insight so the UI can render clickable
references that deep-link to the source finding.

Cache: data/briefing_cache.json  |  TTL: 2 hours per connection
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "briefing_cache.json"
_CACHE_TTL_HOURS = 2


# ── Pydantic schemas (structured LLM output) ──────────────────────────────────

class BriefingCitation(BaseModel):
    ref: str = Field(description="Citation number as it appears in the narrative, e.g. '1'")
    insight_id: str = Field(description="ID of the cited insight")
    domain: str = Field(description="Domain the insight belongs to")
    angle: str = Field(default="", description="Analytical angle of the insight")
    finding: str = Field(description="The finding text being cited")


class BriefingNarrative(BaseModel):
    narrative: str = Field(
        description=(
            "2-3 sentence executive synthesis. Must embed citation markers like [1], [2], [3] "
            "inline at the exact place each finding is referenced. Business language, no jargon."
        )
    )
    citations: list[BriefingCitation] = Field(
        description="Citations for every [N] marker in the narrative, in the same order they appear."
    )
    headline_theme: str = Field(
        description="A 4-6 word theme phrase summarising the most important insight, e.g. 'Enterprise Churn Driving Revenue Risk'",
        default="",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_hours(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 9999


# ── Synthesis ─────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an intelligence analyst writing a Monday morning executive briefing for a business data team.
Your role is to synthesise the most important cross-domain findings into a tight, readable narrative.

Rules:
- Write exactly 2-3 sentences. Be concise and direct.
- Identify connections between findings across different domains — don't just list.
- Use business language a CFO would understand: no SQL, no technical jargon.
- Embed citation markers like [1], [2], [3] inline at the exact point each finding is referenced.
- Every citation marker you use MUST appear in the citations list.
- At least 2 different domains must be referenced.
- Highlight urgency or opportunity where the data supports it.
"""


def _build_user_prompt(
    top_insights: list[dict],
    top_patterns: list[dict],
) -> str:
    lines = ["FINDINGS (ordered by novelty):"]
    for i, ins in enumerate(top_insights, 1):
        domain = ins.get("domain", "Unknown")
        novelty = ins.get("novelty", 0)
        angle = ins.get("angle", "")
        finding = ins.get("finding", "")
        lines.append(f"[{i}] Domain: {domain} | Novelty: {novelty:.1f} | Angle: {angle}\n    \"{finding}\"")

    if top_patterns:
        lines.append("\nCROSS-DOMAIN PATTERNS:")
        for p in top_patterns:
            lines.append(
                f"• {p.get('title', '')} ({p.get('type', '')}): "
                f"{p.get('evidence_count', 0)} findings across {len(p.get('domains', []))} domains"
            )

    lines.append(
        "\nGenerate a 2-3 sentence executive briefing narrative with inline citation markers."
    )
    return "\n".join(lines)


def generate_narrative(
    domain_data: dict[str, list[dict]],
    patterns: list[dict],
    connection_id: str,
) -> dict[str, Any]:
    """
    Call the LLM narrator and return a serialisable briefing dict.

    Returns:
        {
            "narrative":      str,
            "headline_theme": str,
            "citations":      [{"ref", "insight_id", "domain", "angle", "finding"}, ...],
            "generated_at":   str,
        }
    """
    # Flatten + sort insights by novelty desc
    all_insights: list[dict] = []
    for domain, insights in domain_data.items():
        for ins in insights:
            flat = dict(ins) if isinstance(ins, dict) else {}
            flat.setdefault("domain", domain)
            all_insights.append(flat)

    all_insights.sort(key=lambda i: i.get("novelty", 0), reverse=True)

    # Keep breadth: one-per-domain first, then fill to 8 by novelty
    seen_domains: set[str] = set()
    seen_ids:     set[str] = set()
    top: list[dict] = []

    for ins in all_insights:
        if len(top) >= 8:
            break
        d = ins.get("domain", "")
        if d not in seen_domains:
            seen_domains.add(d)
            seen_ids.add(ins.get("id", ""))
            top.append(ins)

    for ins in all_insights:
        if len(top) >= 8:
            break
        if ins.get("id", "") not in seen_ids:
            seen_ids.add(ins.get("id", ""))
            top.append(ins)

    if not top:
        return {
            "narrative":      "",
            "headline_theme": "",
            "citations":      [],
            "generated_at":   _now_iso(),
        }

    # Build prompt and call LLM
    from aughor.llm.provider import get_provider
    provider = get_provider("narrator")
    user_prompt = _build_user_prompt(top[:8], patterns[:3])

    result: BriefingNarrative = provider.complete(
        system=_SYSTEM,
        user=user_prompt,
        response_model=BriefingNarrative,
        temperature=0.3,
    )

    # Map citation refs back to actual insight IDs
    ref_to_insight: dict[str, dict] = {str(i + 1): ins for i, ins in enumerate(top[:8])}
    citations_out = []
    for cit in result.citations:
        source = ref_to_insight.get(cit.ref, {})
        citations_out.append({
            "ref":        cit.ref,
            "insight_id": source.get("id", cit.insight_id),
            "domain":     source.get("domain", cit.domain),
            "angle":      source.get("angle", cit.angle),
            "finding":    source.get("finding", cit.finding),
        })

    return {
        "narrative":      result.narrative,
        "headline_theme": result.headline_theme,
        "citations":      citations_out,
        "generated_at":   _now_iso(),
    }


# ── Cache layer ───────────────────────────────────────────────────────────────

def get_briefing(
    connection_id: str,
    domain_data: dict[str, list[dict]],
    patterns: list[dict],
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached briefing narrative if fresh, otherwise generate and cache."""
    if not force_refresh:
        try:
            if _CACHE_PATH.exists():
                cache = json.loads(_CACHE_PATH.read_text())
                entry = cache.get(connection_id)
                if entry and _age_hours(entry.get("generated_at", "")) < _CACHE_TTL_HOURS:
                    return entry
        except Exception:
            pass

    briefing = generate_narrative(domain_data, patterns, connection_id)

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if _CACHE_PATH.exists():
            try:
                existing = json.loads(_CACHE_PATH.read_text())
            except Exception:
                pass
        existing[connection_id] = briefing
        _CACHE_PATH.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass

    return briefing
