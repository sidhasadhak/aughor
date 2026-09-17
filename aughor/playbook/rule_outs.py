"""IP-1 — data-quality plays reach the Verifier: rule-outs on a deep analysis that reports a move.

When a deep analysis reports its metric moving, the Verifier lists the known ways that metric reads wrong
in that direction — the KB's inflation causes when it rose, its deflation causes when it fell — each with
its fix, and says that none was checked against the data (ROADMAP §3.17; the user's call, 2026-09-17).
Deterministic: no model, no query.

The detection queries are not run. They name example tables (orders, refunds…), and on a connection's own
tables a row back would mean the data has the SHAPE where a pitfall can happen, not that this analysis made
the mistake — IP-3 makes them role-based.

Three reads, each one named so that a wrong rule-out can be traced to it:

- **the direction** is the report's own claim: the sign of `total_change_label`, the label the reader
  sees ("-$330K (-18.4% MoM)" fell, "+€39,945,224" rose), on a report measured against something. A label
  with no signed number ("N/A", "1,807 orders on 2026-09-16") reports no move;
- **the metric** is matched to the KB entries that carry causes, by name. An entry's title or intent tag
  must END the report's metric label, because the head of a noun phrase is its last word: "womenswear
  return rate" is a return rate, "total sales volume" is not total sales. A one-word alias must be the
  whole label once "total" or a period word is dropped: "total GMV" is GMV, "revenue growth" is not
  growth. A bracket that restates the measure as a count abstains: "Total sales (order count)" is not
  GMV. The longest name wins; the connection's own industry beats a function every industry shares;
  names are read across the connection's industry scope only (IP-0's rule);
- **the plays** are the playbook's active data-quality plays for the matched entries, tagged for the
  direction — so a check a person deprecates or deletes is gone from here too, and each rule-out
  carries the version and receipt of the play it came from.

Measured on the 202 deep reports stored on the builder's deployment (2026-09-17, read-only): 19 carry a
signed change against a comparison, and 9 of those name a KB entry, each the metric it reports — GMV six
times (one of them "total sales"), net revenue twice, gross margin % once. The 3 "Total sales (order
count)" reports, which a containment match paired with GMV, abstain. Across all 100 metric labels stored,
one name match is wrong: "investigation job failure rate", on the platform's own operations data with no
industry known, names manufacturing downtime's "failure rate" (that report has no signed change).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

#: The most rule-outs one report lists. One KB entry carries at most four causes in a direction
#: (measured over the 114 entries that carry causes), and two entries can tie on a name.
MAX_RULE_OUTS = 6

#: Said with every rule-out list, in the data, so no consumer can render the causes without it.
NOT_CHECKED = "Not checked against your data."

# A sign on a number: "-$330K", "+€39,945", "(-18.4% MoM)", "−0.82pp". The look-behind keeps a date's
# hyphen ("2026-09-16") and a word's ("56-month") from reading as a minus.
_SIGNED_NUMBER = re.compile(r"(?<![\w.])([+\-−–])\s?[$€£¥₹]?\s?\d")
_TOKEN = re.compile(r"[a-z0-9]+|%")
_BRACKET = re.compile(r"\(([^)]*)\)")
#: Words a one-word alias may carry in front of it and still be the whole label.
_QUALIFIERS = frozenset({"total", "overall", "daily", "weekly", "monthly", "quarterly", "annual", "yearly"})
#: The word a short bracket ends in when it restates the measure as a count ("(order count)", "(items)").
_COUNT_WORDS = frozenset({"count", "counts", "number", "volume", "items", "units", "quantity"})


@dataclass(frozen=True)
class KbMetric:
    """A KB entry that carries inflation or deflation causes, as a metric a report can be matched to."""
    kb_id: str
    title: str
    industry: str               # "" for an entry every industry reads


def lead(found: dict) -> str:
    """The sentence a surface puts above the list: what the causes are about, which way they push, and
    that none was checked — the same words the web report renders."""
    named = " / ".join(found.get("matched") or []) or found.get("metric") or "this metric"
    reads = "higher" if found.get("direction") == "up" else "lower"
    return f"Known ways {named} can read {reads} than it is. {found.get('note') or NOT_CHECKED}"


def change_direction(total_change_label: str) -> Optional[str]:
    """"up" or "down" from the first signed number in a report's change label, else None."""
    found = _SIGNED_NUMBER.search(total_change_label or "")
    if not found:
        return None
    return "up" if found.group(1) == "+" else "down"


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall((text or "").lower()))


def _restates_as_count(bracket: tuple[str, ...]) -> bool:
    """A bracket that names the measure's unit as a count: short and ending in a count word ("order
    count", "items"), or "number of …". A longer bracket is a definition, not a unit: "(sale price of
    order items)" still describes net revenue."""
    return (0 < len(bracket) <= 2 and bracket[-1] in _COUNT_WORDS) or bracket[:2] in (("number", "of"), ("count", "of"))


@lru_cache(maxsize=4)
def _alias_index(_roots: tuple) -> dict[tuple[str, ...], tuple[KbMetric, ...]]:
    """Every name of every KB entry that carries causes — its title, the title's bracketed short form and
    its intent tags — as tokens, in the packages' file order. Cached per pack roots."""
    from aughor.packs.knowledge import entry_industry, iter_kb_payloads

    index: dict[tuple[str, ...], list[KbMetric]] = {}
    for _file, data in iter_kb_payloads():
        for entry in (data if isinstance(data, list) else [data]):
            if not isinstance(entry, dict) or not (entry.get("inflation_causes") or entry.get("deflation_causes")):
                continue
            kb_id = str(entry.get("id") or "")
            if not kb_id:
                continue
            title = str(entry.get("title") or kb_id)
            metric = KbMetric(kb_id=kb_id, title=title, industry=entry_industry(kb_id))
            names = [_BRACKET.sub(" ", title), *_BRACKET.findall(title),
                     *(t for t in (entry.get("intent_tags") or []) if isinstance(t, str))]
            for name in names:
                tokens = _tokens(name)
                if tokens and metric not in index.setdefault(tokens, []):
                    index[tokens].append(metric)
    return {tokens: tuple(metrics) for tokens, metrics in index.items()}


def match_metric(metric_label: str, industry: Optional[str]) -> tuple[KbMetric, ...]:
    """The KB entries a report's metric label names, read in ``industry``'s scope
    (``metric_kb.industry_scope``: a curated id, "" for the shared entries only, None for every industry
    the deployment chose — `industry_choice.readable_industries`)."""
    from aughor.packs.knowledge import cache_token

    head = _tokens(_BRACKET.sub(" ", metric_label or "")) or _tokens(metric_label)
    if not head:
        return ()
    heads = [head, head[:-1]] if head[-1] == "%" and len(head) > 1 else [head]
    stripped = [tuple(t for i, t in enumerate(h) if not (t in _QUALIFIERS and all(x in _QUALIFIERS for x in h[:i + 1])))
                for h in heads]

    from aughor.packs.industry_choice import readable_industries
    readable = readable_industries(industry)
    best: dict[str, KbMetric] = {}
    best_len = 0
    for alias, metrics in _alias_index(cache_token()).items():
        n = len(alias)
        if n < best_len:
            continue
        if n == 1:
            named = any(s == alias for s in stripped)
        else:
            named = any(len(h) >= n and h[-n:] == alias for h in heads)
        if not named:
            continue
        in_scope = [m for m in metrics if readable is None or m.industry in readable]
        if not in_scope:
            continue
        if n > best_len:
            best, best_len = {}, n
        for m in in_scope:
            best.setdefault(m.kb_id, m)
    if not best:
        return ()

    if any(_restates_as_count(_tokens(b)) for b in _BRACKET.findall(metric_label or "")):
        return ()

    chosen = list(best.values())
    own = [m for m in chosen if industry and m.industry == industry]
    shared = [m for m in chosen if not m.industry]
    return tuple(own or shared or chosen)


def rule_outs(metric_label: str, total_change_label: str, comparison_basis: str, *,
              industry: Optional[str], connection_id: str = "") -> Optional[dict]:
    """The rule-outs for one deep-analysis report, or None when it reports no move, its metric names no
    KB entry, or no active data-quality play is left for that entry and direction.

    ``{"direction": "up"|"down", "metric": <the report's label>, "matched": [KB titles],
    "note": NOT_CHECKED, "lead": <the sentence above the list>, "items": [{"cause", "fix", "play_id",
    "version", "receipt"}]}``. The lead is carried rather than composed by each surface, so the web, the
    export and the CLI say the same words — and a platform surface never imports this package for them."""
    if not (comparison_basis or "").strip():
        return None
    direction = change_direction(total_change_label)
    if direction is None:
        return None
    metrics = match_metric(metric_label, industry)
    if not metrics:
        return None

    from aughor.playbook.retriever import is_data_quality
    from aughor.playbook.store import emit_playbook_use, list_active_entries

    tag = "inflation" if direction == "up" else "deflation"
    rank = {m.kb_id: i for i, m in enumerate(metrics)}
    plays = sorted((p for p in list_active_entries()
                    if p.source_kb_id in rank and is_data_quality(p) and tag in p.tags),
                   key=lambda p: rank[p.source_kb_id])
    items: list[dict] = []
    used: list = []
    seen: set[str] = set()
    for play in plays:
        cause = (play.cause or play.recommendation).strip()
        if not cause or cause.lower() in seen:
            continue
        seen.add(cause.lower())
        items.append({"cause": cause, "fix": play.fix, "play_id": play.id,
                      "version": play.version, "receipt": play.receipt})
        used.append(play)
        if len(items) >= MAX_RULE_OUTS:
            break
    if not items:
        return None
    for play in used:            # the Governed-Dive binding: listing a play on a report is using it
        emit_playbook_use(play, conn_id=connection_id or None, used_in="deep_analysis.rule_outs")
    listed = {p.source_kb_id for p in used}
    found = {"direction": direction, "metric": metric_label,
             "matched": [m.title for m in metrics if m.kb_id in listed],
             "note": NOT_CHECKED, "items": items}
    return {**found, "lead": lead(found)}
