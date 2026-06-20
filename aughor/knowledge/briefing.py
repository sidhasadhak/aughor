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
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "briefing_cache.json"
_CACHE_TTL_HOURS = 2


# ── Pydantic schemas (structured LLM output) ──────────────────────────────────

class BriefingCitation(BaseModel):
    ref: str = Field(description="Citation number as it appears in the narrative, e.g. '1'")
    insight_id: str = Field(description="ID of the cited insight")
    domain: str = Field(description="Domain the insight belongs to")
    angle: str = Field(default="", description="Analytical angle of the insight")
    finding: str = Field(description="The finding text being cited")

    # Local models routinely return ref / insight_id as integers (6, not "6"),
    # which fails str validation and made the whole briefing retry until timeout.
    # Coerce scalars to strings so a numeric citation marker no longer breaks it.
    @field_validator("ref", "insight_id", "domain", "angle", "finding", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> Any:
        if v is None:
            return ""
        return v if isinstance(v, str) else str(v)


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

from aughor.util.time import now_iso as _now_iso


from aughor.util.time import age_hours as _age_hours


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

# Used for the "All schemas" aggregate brief, where findings come from SEPARATE businesses.
# Drawing cross-domain connections (the single-business rule above) would invent links
# between unrelated companies — so this variant forbids it and summarizes per business.
_SYSTEM_MULTI = """\
You are an intelligence analyst writing a Monday morning executive briefing that spans SEVERAL
SEPARATE, UNRELATED businesses (each finding is tagged with its Business).

Rules:
- Write exactly 2-3 sentences. Be concise and direct.
- These findings come from DIFFERENT businesses — do NOT draw connections, comparisons, or
  shared causes across them. Treat each business independently.
- Lead with the single most important signal and NAME its business; cover at least two businesses.
- Use business language a CFO would understand: no SQL, no technical jargon.
- Embed citation markers like [1], [2], [3] inline; every marker MUST appear in the citations list.
"""


def _build_user_prompt(
    top_insights: list[dict],
    top_patterns: list[dict],
    macro_context: Optional[dict] = None,
    coverage_digest: str = "",
    multi_schema: bool = False,
    currency_sym: str = "$",
) -> str:
    lines = []
    # Tier 2: lead with the long-arc context so the narrator can juxtapose the recent
    # regime (the findings) against the full-history trend ("up 4× over 8 yrs, now flat").
    if macro_context:
        from aughor.explorer.temporal import render_macro_context
        block = render_macro_context(macro_context)
        if block:
            lines.append(block)
            lines.append("")
    # Findings arrive impact-ranked (magnitude-of-change × north-star × confidence), NOT by
    # novelty — so [1] is the single biggest business move and the narrator must lead with it.
    if multi_schema:
        lines.append(
            "FINDINGS (ordered by business impact; [1] is the single most important signal) — these "
            "come from SEPARATE, UNRELATED businesses (see Business tag). Do NOT connect findings "
            "across businesses:"
        )
    else:
        lines.append("FINDINGS (ordered by business impact — [1] is the single most important signal):")
    for i, ins in enumerate(top_insights, 1):
        domain = ins.get("domain", "Unknown")
        angle = ins.get("angle", "")
        finding = ins.get("finding", "")
        biz = ins.get("source_schema", "")
        prefix = f"Business: {biz} | " if (multi_schema and biz) else ""
        lines.append(f"[{i}] {prefix}Domain: {domain} | Angle: {angle}\n    \"{finding}\"")

    # Full-coverage digest: a per-domain fold of ALL findings (not just the cited top-N) so the
    # narrator's synthesis reflects everything. Context only — it carries no citation numbers.
    if coverage_digest:
        lines.append("")
        lines.append(
            "FULL COVERAGE (every finding, summarized per domain — use for context and breadth; "
            "do NOT cite these as numbered findings, only the FINDINGS above are citable):"
        )
        lines.append(coverage_digest)

    if top_patterns:
        lines.append("\nCROSS-DOMAIN PATTERNS:")
        for p in top_patterns:
            lines.append(
                f"• {p.get('title', '')} ({p.get('type', '')}): "
                f"{p.get('evidence_count', 0)} findings across {len(p.get('domains', []))} domains"
            )

    if macro_context:
        lines.append(
            "\nWhere the long-arc context reframes a recent finding, say so "
            "(e.g. a recent dip that is still far above the multi-year base, or recent "
            "growth that is flattening a longer climb). Do not cite the macro context as a "
            "numbered finding."
        )
    if multi_schema:
        lines.append(
            f"\nLEAD with finding [1] (the highest-impact signal); then summarize the single most "
            f"important signal from EACH of the other distinct businesses separately (name the "
            f"business) — do NOT imply any connection or shared cause across businesses. Report any "
            f"monetary figure in {currency_sym}, never another currency symbol."
        )
    else:
        lines.append(
            f"\nLEAD the narrative with finding [1] — it is the highest-impact signal; open on it, "
            f"then connect the rest. Report any monetary figure in {currency_sym} (this business "
            f"reports in that currency), never another currency symbol."
        )
    lines.append(
        "\nGenerate a 2-3 sentence executive briefing narrative with inline citation markers."
    )
    return "\n".join(lines)


# ── Coverage digest (hierarchical tree-reduce over ALL findings) ──────────────
# The narrative cites only the top-N findings; when more exist, fold ALL of them into a compact,
# partition-aware (per-domain) digest so the synthesis reflects the full picture instead of silently
# dropping findings N+1.. Within a domain the findings are themselves tree-reduced (pack → summarize
# → recurse). Fail-open: any LLM error returns "" → the briefing falls back to the top-N-only prompt.

class _Digest(BaseModel):
    text: str = Field(description="One tight sentence — the key signal only, no preamble, no citations.")


_DIGEST_SYSTEM = (
    "You compress analytical findings into ONE tight sentence capturing the key signal. "
    "No preamble, no citation markers, business language a CFO would understand."
)
_DIGEST_FANOUT = 8


def _coverage_digest(domain_data: dict[str, list[dict]], cited_ids: set[str]) -> str:
    """Per-domain fold of every finding, for the narrator's context. ``""`` when nothing was dropped
    (the top-N prompt already holds everything) or on any failure (fail-open)."""
    groups = {d: ins for d, ins in domain_data.items() if ins}
    total = sum(len(v) for v in groups.values())
    if total <= len(cited_ids):
        return ""
    try:
        from aughor.llm.provider import get_provider
        from aughor.llm.reduce import hierarchical_reduce, partitioned_reduce

        provider = get_provider("fast")

        def _one(prompt: str) -> str:
            return provider.complete(system=_DIGEST_SYSTEM, user=prompt,
                                     response_model=_Digest, temperature=0.2).text.strip()

        def summarize_group(domain: str, findings: list[dict]) -> str:
            def leaf(batch: list[dict]) -> str:
                listing = "\n".join(f"- {f.get('finding', '')}" for f in batch)
                return _one(f"Domain: {domain}\nFindings:\n{listing}\n\nOne sentence capturing the key signal.")

            def comb(parts: list[str]) -> str:
                listing = "\n".join(f"- {p}" for p in parts)
                return _one(f"Domain: {domain}\nPartial summaries:\n{listing}\n\nMerge into one sentence.")

            digest = hierarchical_reduce(findings, summarize=leaf, combine=comb, fanout=_DIGEST_FANOUT)
            return f"{domain}: {digest}"

        # Domains are distinct buckets — keep them on separate lines, never blended.
        return partitioned_reduce(
            groups, summarize_group=summarize_group,
            combine=lambda parts: "\n".join(parts), fanout=_DIGEST_FANOUT,
        )
    except Exception:
        return ""


def _profile_signals(profile: Any) -> tuple[list, str]:
    """(north-star token-sets, currency symbol) from a BusinessProfile (model or dict).
    Empty/`$` defaults when no profile — the brief still gates and ranks, just without
    north-star weighting or currency correction."""
    from aughor.knowledge.triage import north_star_tokens, currency_symbol
    names: list[str] = []
    code: Optional[str] = None
    if isinstance(profile, dict):
        names = [m.get("name", "") for m in (profile.get("north_star_metrics") or [])]
        code = profile.get("currency_code")
    elif profile is not None:
        names = [getattr(m, "name", "") for m in (getattr(profile, "north_star_metrics", None) or [])]
        code = getattr(profile, "currency_code", None)
    from aughor.orgsettings import resolve_currency
    return north_star_tokens(names), currency_symbol(resolve_currency(code or ""))


def generate_narrative(
    domain_data: dict[str, list[dict]],
    patterns: list[dict],
    connection_id: str,
    macro_context: Optional[dict] = None,
    profile: Any = None,
) -> dict[str, Any]:
    """
    Call the LLM narrator and return a serialisable briefing dict.

    A daily executive brief leads with the biggest business move and never prints an
    impossible number or an anti-causal correlation as fact. So before synthesis we run
    the deterministic triage (``knowledge.triage``) over every candidate finding:
      • SUPPRESS impossible magnitudes (an inventory turnover of 3,600×) entirely,
      • DEMOTE anti-causal correlations (stockouts falling as lead time rises) to a
        flagged hypothesis that never reaches the narrative,
      • RANK the survivors by business impact (magnitude-of-change × north-star ×
        confidence) so the lead [1] is what moves the business, not the newest finding.
    Held-back signals are returned (with reasons) so the UI can show the audit trail.

    Returns:
        {
            "narrative":      str,
            "headline_theme": str,
            "citations":      [{"ref", "insight_id", "domain", "angle", "finding"}, ...],
            "held_back":      [{"finding", "domain", "severity", "reason"}, ...],
            "currency_code":  str,
            "generated_at":   str,
        }
    """
    from aughor.knowledge.triage import plausibility, impact_score
    ns_tokens, currency_sym = _profile_signals(profile)
    from aughor.orgsettings import resolve_currency
    # Override-wins: a set org currency beats the inferred currency_code (resolve_currency
    # already falls back to the inferred value, then "USD").
    currency_code = resolve_currency(
        (profile.get("currency_code") if isinstance(profile, dict) else getattr(profile, "currency_code", None)) or ""
    )

    # Currency-normalise any text shown in the brief: a non-USD business should never display
    # a '$' figure (findings were authored before currency-awareness). Rewrites '$<number>' to
    # the business symbol across the narrative, citations AND held-back text so the whole
    # surface is consistent. A no-op when the business reports in USD.
    import re as _re
    def _cur(text: str) -> str:
        if not text or currency_sym == "$":
            return text
        return _re.sub(r"\$(?=\s?[\d.])", currency_sym, text)

    # Flatten, then TRIAGE: split into trusted (synthesised) vs held-back (suppressed/demoted).
    all_insights: list[dict] = []
    for domain, insights in domain_data.items():
        for ins in insights:
            flat = dict(ins) if isinstance(ins, dict) else {}
            flat.setdefault("domain", domain)
            all_insights.append(flat)

    held_back: list[dict] = []
    trusted:   list[dict] = []
    for ins in all_insights:
        finding = ins.get("finding", "")
        verdict = plausibility(finding, ins.get("sql", ""))
        if not verdict.ok:
            held_back.append({
                "finding":  _cur(finding),
                "domain":   ins.get("domain", ""),
                "severity": verdict.severity,   # 'implausible' (suppressed) | 'confound' (demoted)
                "reason":   verdict.reason,
            })
            continue
        ins["_impact"] = impact_score(
            finding, ins.get("novelty", 0), ins.get("confidence", 0), ns_tokens
        )
        trusted.append(ins)

    # Impact-ranked (was novelty): the lead [1] is the single biggest business move.
    trusted.sort(key=lambda i: i.get("_impact", 0.0), reverse=True)

    # Keep breadth: one-per-domain first (in impact order), then fill to 8 by impact.
    seen_domains: set[str] = set()
    seen_ids:     set[str] = set()
    top: list[dict] = []

    for ins in trusted:
        if len(top) >= 8:
            break
        d = ins.get("domain", "")
        if d not in seen_domains:
            seen_domains.add(d)
            seen_ids.add(ins.get("id", ""))
            top.append(ins)

    for ins in trusted:
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
            "held_back":      held_back,
            "currency_code":  currency_code,
            "generated_at":   _now_iso(),
        }

    # Full-coverage digest: when trusted findings were dropped from the top-8, fold them (per
    # domain, tree-reduced) so the narrative reflects the whole TRUSTED picture. Built from the
    # trusted set only — a suppressed/demoted finding must not leak back in as digest context.
    trusted_by_domain: dict[str, list[dict]] = {}
    for ins in trusted:
        trusted_by_domain.setdefault(ins.get("domain", ""), []).append(ins)
    coverage = _coverage_digest(trusted_by_domain, {ins.get("id", "") for ins in top[:8]})

    # RC6 — when the cited findings span multiple businesses (the "All schemas" aggregate),
    # forbid cross-business synthesis: a beauty-ecommerce finding and a bakery finding must
    # not be woven into one causal story.
    multi_schema = len({ins.get("source_schema") for ins in top[:8] if ins.get("source_schema")}) > 1

    # Build prompt and call LLM
    from aughor.llm.provider import get_provider
    provider = get_provider("narrator")
    user_prompt = _build_user_prompt(
        top[:8], patterns[:3], macro_context, coverage_digest=coverage,
        multi_schema=multi_schema, currency_sym=currency_sym,
    )

    result: BriefingNarrative = provider.complete(
        system=_SYSTEM_MULTI if multi_schema else _SYSTEM,
        user=user_prompt,
        response_model=BriefingNarrative,
        temperature=0.3,
    )

    # Currency-normalise the synthesis (and the cited source findings below): the narrator
    # echoes a '$' straight from a finding's prose, and for a non-USD business every '$' figure
    # in the brief is wrong. Bounded fix at the synthesis authority (explorer-side prevention
    # is tracked separately).
    narrative_text = _cur(result.narrative)

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
            "finding":    _cur(source.get("finding", cit.finding)),
        })

    # P5 — attribute each cited sentence back to its finding and persist it as that
    # finding's contextual narrative (the briefing's "why it matters" framing). A
    # drill-in then shows it from the dossier instead of re-synthesizing. The
    # aggregate narrator pass already ran; this is pure attribution, no new LLM call.
    # Best-effort: provenance must never break briefing generation.
    try:
        import re as _re
        from aughor.explorer.dossier import update_dossier
        _sentences = _re.split(r"(?<=[.!?])\s+", result.narrative or "")
        _by_ref: dict[str, list[str]] = {}
        for _sent in _sentences:
            refs = _re.findall(r"\[(\d+)\]", _sent)
            if not refs:
                continue
            _clean = _re.sub(r"\s*\[\d+\]", "", _sent).strip()
            for _r in refs:
                if _clean:
                    _by_ref.setdefault(_r, []).append(_clean)
        for _ref, _ins in ref_to_insight.items():
            _texts = _by_ref.get(_ref)
            if _texts and _ins.get("id"):
                update_dossier(
                    connection_id, _ins["id"],
                    merge={"narrative": " ".join(dict.fromkeys(_texts))},
                    lineage_edge=("narrated_by", "briefing:synthesis", None),
                )
    except Exception:
        import logging
        logging.getLogger(__name__).debug("per-finding narrative attribution failed", exc_info=True)

    return {
        "narrative":      narrative_text,
        "headline_theme": result.headline_theme,
        "citations":      citations_out,
        "held_back":      held_back,
        "currency_code":  currency_code,
        "generated_at":   _now_iso(),
    }


# ── Cache layer ───────────────────────────────────────────────────────────────

def get_briefing(
    connection_id: str,
    domain_data: dict[str, list[dict]],
    patterns: list[dict],
    force_refresh: bool = False,
    scope_key: str | None = None,
    macro_context: Optional[dict] = None,
    profile: Any = None,
    metric_moves: "Optional[Any]" = None,
) -> dict[str, Any]:
    """Return cached briefing narrative if fresh, otherwise generate and cache.

    `scope_key` is the cache key (defaults to `connection_id` for backward compatibility).
    A Canvas passes e.g. ``f"canvas:{canvas_id}"`` so a canvas-scoped briefing — built from
    the canvas's curated tables — never collides with the connection-wide one.

    `profile` is the BusinessProfile (model or dict) — its north-star metrics drive impact
    ranking and its `currency_code` drives currency-correct figures.

    `metric_moves` is an OPTIONAL zero-arg callable returning synthetic metric-move findings
    (north-star trends). It is called ONLY on a cache miss — so the chart_sql it runs never
    burdens the cache-hit path — and its moves join the candidates as a 'Key Metrics' domain.
    """
    key = scope_key or connection_id
    if not force_refresh:
        try:
            if _CACHE_PATH.exists():
                cache = json.loads(_CACHE_PATH.read_text())
                entry = cache.get(key)
                if entry and _age_hours(entry.get("generated_at", "")) < _CACHE_TTL_HOURS:
                    return entry
        except Exception:
            pass

    # Cache miss → fold in north-star metric moves (the biggest KPI swings) as candidates.
    if metric_moves is not None:
        try:
            moves = metric_moves() or []
        except Exception:
            moves = []
        if moves:
            domain_data = {**domain_data, "Key Metrics": list(moves) + list(domain_data.get("Key Metrics", []))}

    briefing = generate_narrative(domain_data, patterns, connection_id, macro_context, profile=profile)

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if _CACHE_PATH.exists():
            try:
                existing = json.loads(_CACHE_PATH.read_text())
            except Exception:
                pass
        existing[key] = briefing
        _CACHE_PATH.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass

    return briefing
