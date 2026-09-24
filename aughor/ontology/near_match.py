"""PENDING.md item 12 — near-matches for a question worded differently from the declared names.

The frame matcher accepts only the words the business declared and a person's synonyms, by design
(§3.15: "a definition asked in words nobody declared needs a person's synonym"). This module does
NOT change that: nothing here frames a question or reaches an answer. It proposes the declared
definitions a missed question MIGHT mean — so the decision to offer them to the existing chooser
(one model call, `agent.framing.choose_definition`) can be taken on a measurement instead of a
hunch. That decision reverses a "by design" rule, and it is the user's.

How a candidate is found, deterministically: each declared definition (a business rule, a
promise's breach rate, a stage's lag) is a small document — its NAME words are strong, its
DESCRIPTION words weak. A question's content stems are matched against it by stem, or by a shared
prefix of four letters or more (risky · risk, fraudulent · fraud), and each hit is weighted by how
rare the stem is across all the definitions — "orders" names half of them and says little,
"jewellery" names one. Ranked, the best few returned with the words that hit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: A definition is a candidate when its weighted hits reach this. Tuned on the dev split only.
THRESHOLD = 1.0
#: How many candidates are returned.
TOP = 3
_PREFIX = 4

#: Words about a duration, which point at a lag rather than a breach rate.
_DURATION = ("day", "days", "long", "take", "takes", "took", "time", "average")
#: Words about lateness, which point at a breach rate.
_LATENESS = ("late", "later", "after", "past", "overdue", "promise", "promised", "estimated", "limit", "deadline")


@dataclass
class _Doc:
    name: str                      # the outcome name the frame would use ("vip_customers", "refund_breach_rate")
    kind: str                      # "rule" | "promise" | "lag"
    label: str
    strong: set[str] = field(default_factory=set)
    weak: set[str] = field(default_factory=set)


def _content(text: str) -> set[str]:
    from aughor.ontology.framing import STOP_STEMS, stem, words_of
    return {s for s in (stem(w) for w in words_of(text)) if len(s) > 2 and s not in STOP_STEMS}


def _question_stems(question: str) -> set[str]:
    """The question's content stems, without the verb of an answer instruction ("Return the
    five brands…" asks nothing about returns) — the matcher's own reading of commands."""
    from aughor.ontology.framing import STOP_STEMS, instruction_verbs, stem, words_of
    commands = instruction_verbs(question)
    return {s for i, s in enumerate(stem(w) for w in words_of(question))
            if i not in commands and len(s) > 2 and s not in STOP_STEMS}


def _type_words(graph: Any) -> set[str]:
    """Words that name a TYPE (an entity, its table) — every definition is about some type, so
    naming one alone says nothing about which definition is meant."""
    out: set[str] = set()
    for e in (getattr(graph, "entities", None) or {}).values():
        out |= _content(f"{e.id} {getattr(e, 'api_name', '')} {getattr(e, 'display_name', '') or ''}")
        for t in getattr(e, "source_tables", None) or []:
            out |= _content(t.rsplit(".", 1)[-1])
    return out


def _docs(graph: Any) -> list[_Doc]:
    from aughor.ontology.derived import lag_name, promise_noun, rate_name
    docs: list[_Doc] = []
    for r in (getattr(graph, "rules", None) or {}).values():
        docs.append(_Doc(r.id, "rule", r.display_name or r.id,
                         strong=_content(f"{r.id} {r.display_name or ''}"), weak=_content(r.description or "")))
    for p in (getattr(graph, "processes", None) or {}).values():
        stages = list(p.stages)
        for i, s in enumerate(stages):
            names = f"{s.name} {s.display_name or ''} {promise_noun(s)}"
            if s.promise is not None:
                deadline = getattr(s.promise, "deadline", "") or ""
                docs.append(_Doc(rate_name(s), "promise", f"the {promise_noun(s)} promise",
                                 strong=_content(names), weak=_content(f"{deadline} {' '.join(_LATENESS)}")))
            if s.timestamp and i and stages[i - 1].timestamp:
                docs.append(_Doc(lag_name(s), "lag", lag_name(s),
                                 strong=_content(names), weak=_content(" ".join(_DURATION))))
    return docs


def _hit(q: str, words: set[str]) -> str:
    """The definition word ``q`` names: the same stem, or one that is a prefix of the other and at
    least four letters (fraud · fraudulent) — never two words that merely begin alike (channel ·
    change, measured on the dev controls)."""
    if q in words:
        return q
    for w in words:
        short, long_ = (q, w) if len(q) <= len(w) else (w, q)
        if len(short) >= _PREFIX and long_.startswith(short):
            return w
    return ""


def near_candidates(question: str, graph: Any, *, top: int = TOP, threshold: float = THRESHOLD) -> list[dict]:
    """The declared definitions ``question`` might mean, best first: ``{"name", "kind", "label",
    "score", "words"}``. Pure; no model, no warehouse. [] when nothing reaches the threshold."""
    docs = _docs(graph)
    if not docs:
        return []
    df: dict[str, int] = {}
    for d in docs:
        for w in d.strong | d.weak:
            df[w] = df.get(w, 0) + 1
    q = _question_stems(question)
    types = _type_words(graph)
    scored = []
    for d in docs:
        score, hits = 0.0, []
        for s in q:
            strong = _hit(s, d.strong)
            weak = "" if strong else _hit(s, d.weak)
            word = strong or weak
            if word:
                score += (2.0 if strong else 1.0) / df.get(word, 1)
                hits.append(word)
        if score >= threshold and any(h not in types for h in hits):
            scored.append({"name": d.name, "kind": d.kind, "label": d.label, "score": round(score, 3),
                           "words": sorted(set(hits))})
    scored.sort(key=lambda c: (-c["score"], c["name"]))
    return scored[:top]
