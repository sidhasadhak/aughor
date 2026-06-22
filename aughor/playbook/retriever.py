"""
Match investigation context to playbook entries.
Used by ADA synthesis to surface proven interventions.
"""
from __future__ import annotations

import re

from aughor.playbook.models import PlaybookEntry
from aughor.playbook.store import list_active_entries


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_]*", text.lower()))


def _score(entry: PlaybookEntry, query_tokens: set[str]) -> float:
    """
    Score a playbook entry against a set of query tokens.
    Returns 0 if no overlap.
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
    if entry.historical_success_rate > 0:
        score += entry.historical_success_rate * 2.0

    return score


def retrieve_for_metric_and_phases(
    metric_labels: list[str],
    limit: int = 6,
) -> list[PlaybookEntry]:
    """
    Given a list of metric/phase labels extracted from the investigation,
    return the top matching playbook entries sorted by relevance and success rate.
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
    scored = [(s, e) for e in entries if (s := _score(e, query_tokens)) > 0]
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


def build_playbook_prompt_section(entries: list[PlaybookEntry]) -> str:
    """
    Render matched playbook entries as a prompt block for ADA synthesis.
    Returns empty string if no entries.
    """
    if not entries:
        return ""

    lines = [
        "PLAYBOOK — proven interventions from organisational knowledge:",
        "(Prefer these recommendations. For root causes NOT covered here, generate a recommendation "
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
        from aughor.process.causal import build_causal_context_section
        return build_causal_context_section(question, conn_id=conn_id)
    except Exception:
        return ""
