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


#: What one query word is worth when it names the play's trigger metric, one of its tags, or merely
#: appears in its recommendation text. A caller that wants a play to FIT a thing — not just share a
#: word with it — asks for a relevance of at least ``METRIC_HIT`` (``min_relevance``).
METRIC_HIT = 3.0
TAG_HIT = 1.5
WORD_HIT = 0.5


def _relevance(entry: PlaybookEntry, query_tokens: set[str]) -> float:
    """How much a play is about the query's words, before any boost: 0 with no overlap."""
    metric_tokens = _tokenize(entry.trigger_metric)
    tag_tokens: set[str] = set()
    for t in entry.tags:
        tag_tokens |= _tokenize(t)
    rec_tokens = _tokenize(entry.recommendation)
    score = 0.0
    for qt in query_tokens:
        if qt in metric_tokens:
            score += METRIC_HIT
        elif qt in tag_tokens:
            score += TAG_HIT
        elif qt in rec_tokens:
            score += WORD_HIT
    return score


#: The words a tag's phrasing carries ("what is my CAC", "how much per user"): not part of the name.
_STOP = {"what", "is", "are", "my", "how", "much", "many", "to", "a", "an", "per", "by", "of", "the", "and", "or",
         "in", "for", "with", "which", "most", "do", "does", "has", "have", "vs", "versus", "up", "down", "flat", "why"}
#: Words that are part of a name but name nothing on their own: "rate" is every rate, "total" every
#: total. A name must be read with them and must have a word beyond them.
_GENERIC = {"rate", "count", "total", "avg", "average", "mean", "pct", "percent", "share", "num", "number", "overall",
            "aggregate", "company", "wide", "breakdown", "distribution", "split", "mix", "performance", "analysis",
            "trend", "cost", "price", "value", "volume", "revenue", "sales", "customer", "customers", "user", "users",
            "order", "orders", "product", "products", "category", "categories"}
#: A pack's prefix on a trigger metric's name ("ec_return_rate"): not a word of the name.
_PREFIXES = {"ec", "mkt", "fin", "ops", "saas", "cs", "hr", "mfg", "log", "air", "fd", "b2b", "ret"}


def words(text: str) -> set[str]:
    """The words a text is made of: underscores and hyphens split, the phrasing words left out."""
    return set(re.findall(r"[a-z][a-z0-9]*", (text or "").lower())) - _STOP


def metric_words(name: str) -> set[str]:
    """A trigger metric's name as words, its pack prefix left out."""
    return words(name) - _PREFIXES


def _names(entry: PlaybookEntry, name: set[str], query_words: set[str]) -> bool:
    """Every word of ``name`` is in the query, and the name has a word that names something."""
    return bool(name - _GENERIC) and name <= query_words


def fits(entry: PlaybookEntry, query_words: set[str]) -> bool:
    """Whether the play is ABOUT the query: every word of its trigger metric's name is there, or
    every word of one of its tags — and the name has a word beyond the generic ones. One shared
    word — "cost" from "customer acquisition cost", "category" from "category breakdown",
    "customer" in one tag and "overall" in another — is not a fit, however proven the play.
    Measured on theLook's findings (2026-10-09): under looser rules "Overall return rate" was
    handed blended CAC, "Average age by gender" the new-vs-returning play, and "Retail-price
    breakdown by department" a CPM play on the tag "price per 1000"."""
    if _names(entry, metric_words(entry.trigger_metric), query_words):
        return True
    return any(_names(entry, words(tag), query_words) for tag in entry.tags)


def _score(entry: PlaybookEntry, query_tokens: set[str], *, learned_rates: bool = True) -> float:
    """
    Score a playbook entry against a set of query tokens.
    Returns 0 if no overlap.
    ``learned_rates=False`` scores relevance alone: a success rate is learned from outcomes
    on every connection, and a caller that reads one connection only does not rank by it.
    """
    score = _relevance(entry, query_tokens)
    if score <= 0:
        return 0.0

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
    min_relevance: float = 0.0,
    fit: bool = False,
) -> list[PlaybookEntry]:
    """
    Given a list of metric/phase labels extracted from the investigation,
    return the top matching playbook entries sorted by relevance and success rate.
    ``learned_rates=False`` sorts by relevance alone — the explorer's call, since a rate is
    learned on every connection and the explorer does not look beyond its own (the user's
    rule, 2026-09-14).

    ``min_relevance`` is the least a play must score on overlap before any boost counts, and
    ``fit`` asks for more: that the play NAMES the thing — every word of its trigger metric's name
    is in the labels, or every word of one of its tags (:func:`fits`). The Briefing asks for ``fit``, because a
    play's learned success rate adds up to two points whatever the fit, and eight citations of
    one Briefing were handed the same proven play on a one-word overlap (the user, 2026-10-09:
    "of course those don't fit"). The defaults keep every other caller as it was: any overlap.

    ``industry`` is ``aughor.business_profile.metric_kb.industry_scope`` for the connection being
    analysed. A curated id ("airline") reads that industry's plays plus the ones every industry shares,
    ``""`` reads only the shared ones, and ``None`` — nothing is known about the industry — reads all of
    them (IP-2: all of the industries chosen at install). Unscoped, a SaaS "why is churn up this quarter" drew four e-commerce plays. Data-quality plays
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
    from aughor.packs.industry_choice import readable_industries
    readable = readable_industries(industry)
    if readable is not None:
        from aughor.business_profile.metric_kb import kb_entry_industry
        entries = [e for e in entries if kb_entry_industry(e.source_kb_id) in readable]
    if min_relevance > 0:
        entries = [e for e in entries if _relevance(e, query_tokens) >= min_relevance]
    if fit:
        named = set().union(*(words(label) for label in metric_labels))
        # A play that names the thing is relevant by construction — worth a metric hit at least,
        # whatever the token scorer makes of "repeat purchase rate" against "repeat_purchase_rate".
        def fit_score(e: PlaybookEntry) -> float:
            floor = METRIC_HIT * 1.2
            if learned_rates and e.historical_success_rate > 0:
                floor += e.historical_success_rate * 2.0
            return max(_score(e, query_tokens | named, learned_rates=learned_rates), floor)
        scored = [(fit_score(e), e) for e in entries if fits(e, named)]
    else:
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
        # Phase 5: the rate is said with its count — "held in 3 of 4 reviewed outcomes" — never as a
        # bare percentage; a play with no reviewed outcome says so.
        n = int(getattr(e, "outcome_n", 0) or 0)
        if n > 0:
            held = round(e.historical_success_rate * n)
            sr = f"  [held in {held} of {n} reviewed outcome{'s' if n != 1 else ''}]"
        elif e.historical_success_rate > 0:
            sr = f"  [{e.historical_success_rate * 100:.0f}% historical success rate; count not recorded]"
        else:
            sr = "  [no outcome data yet]"
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
