"""
Briefing Synthesis — M24b

Generates an LLM-authored executive narrative from cross-domain intelligence.

The narrator reads the top findings and patterns, then writes a multi-paragraph
brief that connects them with inline citation markers [1], [2], etc. — a 2-3
sentence lede (all the UI's collapsed card shows) followed by the depth behind it
(what "Read full synthesis" expands to).

Each citation maps back to a specific insight so the UI can render clickable
references that deep-link to the source finding.

Cache: data/briefing_cache.json  |  TTL: 2 hours per connection
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from aughor.db.paths import state_dir

_CACHE_PATH = state_dir() / "briefing_cache.json"
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
            "Executive synthesis: a 2-3 sentence LEDE paragraph carrying the headline, then 2-4 "
            "short paragraphs of depth, separated by blank lines. Must embed citation markers like "
            "[1], [2], [3] inline at the exact place each finding is referenced. Business language, "
            "no jargon."
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

from aughor.util.format import round_long_decimals
from aughor.util.time import now_iso as _now_iso


from aughor.util.time import age_hours as _age_hours


# ── Synthesis ─────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an intelligence analyst writing a Monday morning executive briefing for a business data team.
Your role is to synthesise the most important cross-domain findings into a readable narrative that
stands on its own.

Structure:
- Open with a LEDE of 2-3 sentences carrying the single biggest business move. A reader who stops
  after the lede must still have the headline.
- Then 2-4 short paragraphs of depth: what connects the findings, what appears to be driving what,
  what it means for the business, and what deserves attention first.
- Separate paragraphs with a blank line. Aim for 200-350 words in total.

Rules:
- Identify connections between findings across different domains — don't just list them.
- Carry every finding that does real work in the argument, not only the first two or three.
- Use business language a CFO would understand: no SQL, no technical jargon.
- Embed citation markers like [1], [2], [3] inline at the exact point each finding is referenced.
- Every citation marker you use MUST appear in the citations list.
- At least 2 different domains must be referenced.
- Highlight urgency or opportunity where the data supports it.
- Never pad. If the findings only support a short brief, write a short one — length must come from
  evidence, never from filler, restatement, or speculation beyond what the findings show.
"""

# Used for the "All schemas" aggregate brief, where findings come from SEPARATE businesses.
# Drawing cross-domain connections (the single-business rule above) would invent links
# between unrelated companies — so this variant forbids it and summarizes per business.
_SYSTEM_MULTI = """\
You are an intelligence analyst writing a Monday morning executive briefing that spans SEVERAL
SEPARATE, UNRELATED businesses (each finding is tagged with its Business).

Structure:
- Open with a LEDE of 2-3 sentences on the single most important signal, NAMING its business.
- Then one short paragraph per other business covered, each self-contained.
- Separate paragraphs with a blank line. Aim for 200-350 words in total.

Rules:
- These findings come from DIFFERENT businesses — do NOT draw connections, comparisons, or
  shared causes across them. Treat each business independently. This holds for every paragraph:
  more room to write is not licence to link them.
- Cover at least two businesses.
- Use business language a CFO would understand: no SQL, no technical jargon.
- Embed citation markers like [1], [2], [3] inline; every marker MUST appear in the citations list.
- Never pad. Length must come from evidence, never from filler or speculation.
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
            "FULL COVERAGE (the remaining findings, per domain — use for context and breadth; "
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
        "\nGenerate the executive briefing narrative: a 2-3 sentence lede, then 2-4 short "
        "paragraphs of depth, separated by blank lines, with inline citation markers."
    )
    return "\n".join(lines)


# ── Coverage digest (deterministic per-domain listing) ────────────────────────
# The narrative cites only the top-N findings; when more exist, the rest are listed here so the
# synthesis reflects the full picture instead of silently dropping findings N+1..
#
# This WAS an LLM tree-reduce (pack → summarize → recurse, fanout 8). Measured on a real brief it
# spent ~5 model calls compressing 1,291 characters into ~3 sentences — for a narrator whose context
# window holds 32k+ tokens. That trade only makes sense when the source cannot fit; here it cost
# latency and quota (a free tier's whole per-minute allowance went on the digest alone, so the brief
# died before the narrator ran), added a failure mode, and DISCARDED detail the narrator could have
# used. Listing the findings verbatim is cheaper, faster, and strictly more faithful.
#
# Only UNCITED findings are listed: the top-N are already in the prompt above, in full.

_DIGEST_MAX_PER_DOMAIN = 12     # findings listed per domain before the tail is counted, not shown
_DIGEST_MAX_CHARS = 4000        # whole-digest budget; the narrator's window is far larger


def _coverage_digest(domain_data: dict[str, list[dict]], cited_ids: set[str]) -> str:
    """Per-domain listing of the findings the prompt did NOT already carry.

    ``""`` when nothing was dropped (the top-N prompt already holds everything). Deterministic:
    no LLM call, so it cannot fail, stall, or invent — the old version's fail-open ``except``
    returned "" on any model error, which silently cost the narrative its breadth."""
    remaining: dict[str, list[str]] = {}
    for domain, insights in domain_data.items():
        texts = [t for ins in insights
                 if ins.get("id", "") not in cited_ids
                 and (t := str(ins.get("finding", "")).strip())]
        if texts:
            remaining[domain] = texts
    if not remaining:
        return ""

    lines: list[str] = []
    budget = _DIGEST_MAX_CHARS
    for domain, texts in remaining.items():
        shown, hidden = texts[:_DIGEST_MAX_PER_DOMAIN], texts[_DIGEST_MAX_PER_DOMAIN:]
        head = f"{domain}:"
        entries: list[str] = []
        for t in shown:
            entry = f"  - {t}"
            if len(entry) > budget:                    # budget spent — count the tail, never drop it silently
                hidden = texts[len(entries):]
                break
            entries.append(entry)
            budget -= len(entry)
        if not entries:
            continue
        lines.append(head)
        lines.extend(entries)
        if hidden:
            lines.append(f"  - (+{len(hidden)} further findings in this domain)")
    return "\n".join(lines)


def _profile_signals(profile: Any, workspace_id: Optional[str] = None) -> tuple[list, str]:
    """(north-star token-sets, currency symbol) from a BusinessProfile (model or dict).
    Empty/`$` defaults when no profile — the brief still gates and ranks, just without
    north-star weighting or currency correction. `workspace_id` lets a workspace-scoped
    currency override win over the app default (else app default, else the inferred code)."""
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
    return north_star_tokens(names), currency_symbol(resolve_currency(code or "", workspace_id))


def _dataset_subject(profile: Any) -> str:
    """A 'THIS DATASET:' block from the schema's own BusinessProfile — '' when there is none.

    The brief's subject is the data being briefed, not the organization reading it. Those are
    the same thing for a single-company deployment and emphatically NOT the same when one
    workspace holds several unrelated datasets as schemas — which is exactly when the narrator
    used to hand the org's name to someone else's data.

    `industry` and `summary` are already inferred PER SCHEMA by the profiler and were being
    loaded and then dropped: only the profile's north-star tokens and currency ever reached the
    prompt. This just stops throwing the rest away."""
    if profile is None:
        return ""
    get = (lambda k: profile.get(k)) if isinstance(profile, dict) else (lambda k: getattr(profile, k, None))
    industry = (get("industry") or "").strip()
    summary = (get("summary") or "").strip()
    model = (get("business_model") or "").strip()
    if not (industry or summary):
        return ""
    bits = " · ".join(b for b in (industry, model) if b)
    lines = ["THIS DATASET — what the findings below are ABOUT:"]
    if bits:
        lines.append(f"  {bits}")
    if summary:
        lines.append(f"  {summary}")
    lines.append(
        "  Write about THIS dataset. Do not attribute its activity to the reader's organization "
        "unless they are plainly the same business."
    )
    return "\n".join(lines) + "\n"


def group_held_back(held_back: list[dict]) -> list[dict]:
    """Collapse held-back signals that were suppressed for the SAME reason into one entry.

    A trust-gate reason is derived from the SQL *idiom* (``AVG()`` over a rate, ``SUM()``
    over a VARCHAR), not from the finding — so N findings sharing one bad idiom produce N
    byte-identical strings, and the strip renders the same sentence seven times. Grouping
    is the honest fix: one line per DISTINCT reason, carrying ``count`` (and the domains it
    hit) so nothing is silently dropped — ``sum(count)`` still equals the number of signals
    the gate held back. Order is preserved (first occurrence wins), most-frequent first."""
    groups: dict[tuple[str, str], dict] = {}
    for h in held_back:
        key = (h.get("severity", ""), h.get("reason", ""))
        g = groups.get(key)
        if g is None:
            groups[key] = {**h, "count": 1, "domains": [h.get("domain", "")] if h.get("domain") else []}
            continue
        g["count"] += 1
        dom = h.get("domain", "")
        if dom and dom not in g["domains"]:
            g["domains"].append(dom)
    return sorted(groups.values(), key=lambda g: -g["count"])


def generate_narrative(
    domain_data: dict[str, list[dict]],
    patterns: list[dict],
    connection_id: str,
    macro_context: Optional[dict] = None,
    profile: Any = None,
    workspace_id: Optional[str] = None,
    col_types: Optional[dict[str, str]] = None,
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
            "held_back":      [{"finding", "domain", "severity", "reason", "count", "domains"}, ...],
                              # grouped by (severity, reason) — see `group_held_back`
            "currency_code":  str,
            "generated_at":   str,
        }
    """
    from aughor.knowledge.triage import plausibility, impact_score
    ns_tokens, currency_sym = _profile_signals(profile, workspace_id)
    from aughor.orgsettings import resolve_currency
    # Override-wins: a workspace-scoped (then app) org currency beats the inferred
    # currency_code (resolve_currency already falls back to the inferred value, then "USD").
    currency_code = resolve_currency(
        (profile.get("currency_code") if isinstance(profile, dict) else getattr(profile, "currency_code", None)) or "",
        workspace_id,
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
        # `col_types` (bare + qualified column → declared dtype) lets triage suppress a
        # finding whose SQL applies a non-additive aggregate to a non-numeric column
        # (SUM over a VARCHAR fiscal-year) BEFORE the narrator sees it — so the AI prose
        # can never cite a type-void number. Omitted → that check no-ops (no regression).
        verdict = plausibility(finding, ins.get("sql", ""), col_types)
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
            "held_back":      group_held_back(held_back),
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
    # WHAT THIS DATA IS — the dataset's OWN characterization, from the per-schema
    # BusinessProfile that was already loaded for this scope. Without it the narrator had only
    # the org's identity to go on and attributed the data to the org: a Netflix title catalog
    # opened "LuxExperience has aggressively scaled content production…". The subject of the
    # brief is the DATASET; the organization is who's reading it. Deterministic — no new
    # inference, just passing through what the profiler already decided for this schema.
    try:
        _subject = _dataset_subject(profile)
        if _subject:
            user_prompt = _subject + "\n" + user_prompt
    except Exception as _e:
        import logging as _l
        _l.getLogger(__name__).debug("briefing: dataset subject unavailable: %s", _e)

    # Identity context (company/HQ/website/industry) — declared identity only, '' when unset (a
    # no-op for unconfigured orgs), workspace override-wins. Framed explicitly as the READER's
    # organization, because org settings are workspace-global while a brief is schema-scoped:
    # one workspace can hold several unrelated datasets, and the org does not own all of them.
    try:
        from aughor.orgsettings import org_context
        _org = org_context(workspace_id)
        if _org:
            user_prompt = _org + "\n" + user_prompt
    except Exception as _e:
        import logging as _l
        _l.getLogger(__name__).debug("briefing: org_context unavailable: %s", _e)

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
    # …and number-normalise it, for the same reason one layer up: the narrator echoes digits
    # straight out of a finding's prose. Explorer-side prevention (rows_for_prompt + hygiene at
    # emit) means this should now be a no-op on fresh findings — it stays as the response-boundary
    # guarantee, covering findings persisted before that landed. `aughor.util.format` owns the rule.
    narrative_text = round_long_decimals(_cur(result.narrative))

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
        "held_back":      group_held_back(held_back),
        "currency_code":  currency_code,
        "generated_at":   _now_iso(),
    }


# ── Cache layer ───────────────────────────────────────────────────────────────

def peek_briefing(scope_key: str) -> dict[str, Any] | None:
    """The cached brief for a scope, or None — READ ONLY, never generates.

    `get_briefing` synthesizes on a miss (an LLM call plus a coverage fan-out), which is far
    too expensive for a read-side consumer. "Ask this briefing" grounds its answers in the
    brief the user is actually looking at, so it wants exactly this: the current artifact if
    one exists, and otherwise nothing to say. Ignores the TTL deliberately — a slightly stale
    brief is still the one on screen, and refreshing it is the Briefing's job, not the ask's."""
    try:
        if not _CACHE_PATH.exists():
            return None
        entry = json.loads(_CACHE_PATH.read_text()).get(scope_key)
        return entry if isinstance(entry, dict) and entry.get("narrative") else None
    except Exception:
        return None


def get_briefing(
    connection_id: str,
    domain_data: dict[str, list[dict]],
    patterns: list[dict],
    force_refresh: bool = False,
    scope_key: str | None = None,
    macro_context: Optional[dict] = None,
    profile: Any = None,
    metric_moves: "Optional[Any]" = None,
    workspace_id: Optional[str] = None,
    col_types: Optional[dict[str, str]] = None,
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

    `col_types` (bare + qualified column → declared dtype) is threaded into the triage so a
    finding whose SQL applies a non-additive aggregate to a non-numeric column is held back
    from the narrative — the same authority the insight cards stamp by. Omit → the check
    no-ops. Only consulted on a cache miss (where generate_narrative runs).
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

    briefing = generate_narrative(domain_data, patterns, connection_id, macro_context,
                                  profile=profile, workspace_id=workspace_id,
                                  col_types=col_types)

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


def invalidate(connection_id: str, schema: str | None = None) -> int:
    """Drop cached briefings for a connection. With ``schema``, remove that schema's
    scope (``'conn_id:schema'``) AND the now-stale 'All schemas' aggregate (``'conn_id'``),
    leaving sibling schemas — used when a single schema is removed. Without it, remove the
    connection-level entry AND every schema scope — used by the catalog-delete cascade.
    Returns the number of entries removed."""
    if not _CACHE_PATH.exists():
        return 0
    try:
        cache = json.loads(_CACHE_PATH.read_text())
    except Exception:
        return 0
    if schema:
        # the schema's own briefing AND the now-stale 'All schemas' aggregate; siblings stay
        drop = {f"{connection_id}:{schema}", connection_id}
        kept = {k: v for k, v in cache.items() if k not in drop}
    else:
        prefix = f"{connection_id}:"
        kept = {k: v for k, v in cache.items()
                if k != connection_id and not k.startswith(prefix)}
    removed = len(cache) - len(kept)
    if removed:
        _CACHE_PATH.write_text(json.dumps(kept, indent=2))
    return removed
