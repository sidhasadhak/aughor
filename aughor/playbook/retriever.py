"""
Match investigation context to playbook entries.
Used by ADA synthesis, the Explorer and chat answers to surface matching interventions.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.playbook.models import DATA_QUALITY_TAG, PlaybookEntry
from aughor.playbook.store import list_active_entries


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_]*", text.lower()))


def _score(entry: PlaybookEntry, query_tokens: set[str], *, learned_rates: bool = True) -> float:
    """
    Score a playbook entry against a set of query tokens.
    Returns 0 if no overlap.
    ``learned_rates=False`` scores relevance alone: a success rate is learned from outcomes
    on every connection, and a caller that reads one connection only does not rank by it.
    """
    metric_tokens = _tokenize(entry.trigger_metric)
    tag_tokens: set[str] = set()
    for t in entry.tags:
        tag_tokens |= _tokenize(t)
    rec_tokens = _tokenize(entry.recommendation)

    score = 0.0
    for qt in query_tokens:
        if qt in metric_tokens:
            score += 3.0
        elif qt in tag_tokens:
            score += 1.5
        elif qt in rec_tokens:
            score += 0.5

    # Boost active entries over drafts
    if entry.status == "active":
        score *= 1.2

    # Boost proven entries
    if learned_rates and entry.historical_success_rate > 0:
        score += entry.historical_success_rate * 2.0

    return score


def is_data_quality(entry: PlaybookEntry) -> bool:
    """A KB-seeded check on the number itself ("GMV appears inflated: check whether cancelled orders
    are filtered"), not a move for the business."""
    return bool(entry.source_kb_id) and DATA_QUALITY_TAG in entry.tags


def retrieve_for_metric_and_phases(
    metric_labels: list[str],
    limit: int = 6,
    *,
    learned_rates: bool = True,
    industry: Optional[str] = None,
    include_data_quality: bool = False,
) -> list[PlaybookEntry]:
    """
    Given a list of metric/phase labels extracted from the investigation,
    return the top matching playbook entries sorted by relevance and success rate.
    ``learned_rates=False`` sorts by relevance alone — the explorer's call, since a rate is
    learned on every connection and the explorer does not look beyond its own (the user's
    rule, 2026-09-14).

    ``industry`` is ``aughor.business_profile.metric_kb.industry_scope`` for the connection being
    analysed. A curated id ("airline") reads that industry's plays plus the ones every industry shares,
    ``""`` reads only the shared ones, and ``None`` — nothing is known about the industry — reads all of
    them. Unscoped, a SaaS "why is churn up this quarter" drew four e-commerce plays. Data-quality plays
    are left out unless ``include_data_quality``: they check a number, they don't recommend a move.
    """
    if not metric_labels:
        return []

    query_tokens: set[str] = set()
    for label in metric_labels:
        query_tokens |= _tokenize(label)

    # Strip very common stop words that add noise
    _STOP = {"the", "a", "an", "is", "are", "was", "were", "for", "by", "of", "in",
             "to", "and", "or", "not", "with", "on", "at", "this", "that", "has"}
    query_tokens -= _STOP

    if not query_tokens:
        return []

    entries = list_active_entries()
    if not include_data_quality:
        entries = [e for e in entries if not is_data_quality(e)]
    if industry is not None:
        from aughor.business_profile.metric_kb import kb_entry_industry
        entries = [e for e in entries if kb_entry_industry(e.source_kb_id) in ("", industry)]
    scored = [(s, e) for e in entries if (s := _score(e, query_tokens, learned_rates=learned_rates)) > 0]
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


_TEMPORAL_TRIGGER_RE = re.compile(
    r"\b(up|down|flat|increas\w*|decreas\w*|spik\w*|drop\w*|rising|falling|"
    r"grew|fell|declin\w*|trend\w*|mom|yoy|month.over.month|year.over.year)\b",
    re.IGNORECASE,
)


def filter_by_approach(entries: list[PlaybookEntry], *,
                       cross_sectional: bool) -> list[PlaybookEntry]:
    """Drop entries whose trigger describes a CHANGE from a cross-sectional prompt (PE-3).

    The measured specimen injected five "When GMV up…" playbook entries — 428 tokens,
    every one a temporal pattern — into a report whose own note said "this is NOT a
    period-over-period decline", and told the model to PREFER them. A ranking of
    where value sits has no "up"; guidance about movement is noise there at best and
    a wrong-frame invitation at worst. Temporal prompts keep everything: a change
    question can still benefit from a level-shaped intervention."""
    if not cross_sectional:
        return entries
    return [e for e in entries
            if not _TEMPORAL_TRIGGER_RE.search(e.trigger_condition or "")]


def build_playbook_prompt_section(entries: list[PlaybookEntry]) -> str:
    """
    Render matched playbook entries as a prompt block for ADA synthesis.
    Returns empty string if no entries.

    The header says "proven" only when an entry has a logged outcome. Every play seeded from the KB
    starts with none, and the block used to open with "proven interventions … Prefer these" regardless.
    """
    if not entries:
        return ""

    proven = any(e.historical_success_rate > 0 for e in entries)
    lines = [
        "PLAYBOOK — proven interventions from organisational knowledge:" if proven else
        "PLAYBOOK — reference patterns from organisational knowledge (none has a logged outcome yet):",
        "(Use an entry where this analysis's evidence supports it; an entry with a success rate has worked "
        "before. For root causes NOT covered here, generate a recommendation "
        "but append \"[unproven — consider adding to playbook]\" so the user can review it.)",
    ]
    for e in entries:
        sr = f"  [{e.historical_success_rate * 100:.0f}% historical success rate]" if e.historical_success_rate > 0 else "  [no outcome data yet]"
        impact = f" | expected: {e.expected_impact}" if e.expected_impact else ""
        timeline = f" | timeline: {e.typical_timeline}" if e.typical_timeline else ""
        lines.append(f"  • {e.recommendation}{impact}{timeline}{sr}")

    # Governed-Dive binding: rendering a play into the analysis prompt IS using it, so pin
    # each to its version + receipt in the ledger. Fail-open — never affects the rendering.
    try:
        from aughor.playbook.store import emit_playbook_use
        for e in entries:
            emit_playbook_use(e, used_in="ada_synthesis")
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "playbook-use binding is best-effort", counter="playbook.use")

    return "\n".join(lines) + "\n"


def build_causal_playbook_section(question: str, conn_id: str) -> str:
    """
    Prepend upstream causal context from the confirmed causal graph.
    Injected into the playbook section so ADA knows which upstream drivers
    have been previously confirmed as causes.
    """
    try:
        from aughor.lifecycle.causal import build_causal_context_section
        return build_causal_context_section(question, conn_id=conn_id)
    except Exception:
        return ""
