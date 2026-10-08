"""A move explained in words — the model writes it, the data holds it to account (2026-10-08).

The exploration principles §4: time detects, dimensions explain. The watch job (`explorer/watch.py`) finds a
settled figure that really moved and breaks it down by its dimensions with SQL — which segments carry the
move and by how much. That says WHERE the change sits. This module adds the sentence a person reads: the
model is handed exactly those numbers, the segments' shares of the move worked out in advance (the model
does no arithmetic), and what the platform already found about a moving segment, and writes two or three
sentences.

Held to account before it is kept, the same way a message is before it leaves (`govern/departure.py`):

* **every number in it is one it was handed**, at the precision it is written
  (`explorer.grounding.numeral_matches_measure`) — a number the breakdown does not hold is refused;
* **it claims no more than a breakdown shows** — descriptive only: a causal, associational or forecast
  sentence (`agent.claim_type.sentence_claims`) is refused. A breakdown shows where a change sits, not why.

A draft that breaks either rule is sent back once with what it broke; a second failure is WITHHELD and says
so — an explanation never reaches a person with a number nobody measured in it. Runs as a supervised job
under the Explorer's charter (`explain_move`), so its tokens count against the month's exploration budget
and the job is capped at what is left of it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

#: The most earlier findings handed to the model beside the numbers.
MAX_FINDINGS = 4
JOB_KIND = "explain_move"


class MoveStory(BaseModel):
    text: str = Field(description="Two or three sentences explaining where the move sits, using only the numbers given")


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def facts_of(move: dict, explained: list[dict], *, reading: dict, grain: str,
             findings: Optional[list[str]] = None, unit: str = "") -> dict:
    """The exact numbers the model is handed — and the only ones it may write."""
    rel = _num(move.get("rel"))
    segs = []
    cur_total, prev_total = _num(move.get("current")), _num(move.get("previous"))
    total_change = (cur_total - prev_total) if cur_total is not None and prev_total is not None else None
    for e in explained or []:
        if e.get("metric") != move.get("metric"):
            continue
        change = _num(e.get("change"))
        share = (round(100.0 * change / total_change, 1)
                 if change is not None and total_change not in (None, 0.0) and change * total_change > 0 else None)
        segs.append({"dimension": e.get("dimension"), "segment": e.get("group"),
                     "current": _num(e.get("current")), "previous": _num(e.get("previous")),
                     "change": change, "share_of_the_move_pct": share,
                     "is_a_share_metric": bool(e.get("share"))})
    return {
        "metric": move.get("name") or move.get("metric"), "unit": unit,
        "period": f"the {grain} to {reading.get('through')}", "compared_with": f"the {grain} before",
        "current": cur_total, "previous": prev_total,
        "change_pct": round(rel * 100, 1) if rel is not None else None,
        "segments": segs,
        "what_the_platform_found_earlier": [str(f)[:300] for f in (findings or [])[:MAX_FINDINGS]],
    }


def allowed_values(facts: dict) -> list[float]:
    vals: list[float] = []
    for k in ("current", "previous", "change_pct"):
        if facts.get(k) is not None:
            vals.append(float(facts[k]))
    if facts.get("current") is not None and facts.get("previous") is not None:
        vals.append(float(facts["current"]) - float(facts["previous"]))
    for s in facts.get("segments") or []:
        for k in ("current", "previous", "change", "share_of_the_move_pct"):
            if s.get(k) is not None:
                vals.append(float(s[k]))
        if s.get("is_a_share_metric") and s.get("change") is not None:
            vals.append(float(s["change"]) * 100)          # a share's change, said in points
    return vals


def problems_with(text: str, facts: dict) -> list[str]:
    """What the draft broke: a number it was not handed, or a claim beyond a description."""
    from aughor.agent.claim_type import sentence_claims
    from aughor.explorer.grounding import extract_numerals, numeral_matches_measure
    out: list[str] = []
    if not str(text or "").strip():
        return ["it is empty"]
    # a date in the period ("2026-10-07") is the period's, not a measured number
    period = str(facts.get("period") or "")
    allowed = allowed_values(facts)
    for n in extract_numerals(text):
        if n.text in period or (not n.suffix and n.decimals == 0 and 1900 <= abs(n.value) <= 2100):
            continue
        if not any(numeral_matches_measure(n, v) for v in allowed):
            out.append(f"it states {n.text}, which the breakdown does not hold")
    for sentence, claim, verb in sentence_claims(text):
        out.append(f"it makes a {claim} claim ('{verb}') — a breakdown shows where a change sits, not why")
    return out


_SYSTEM = (
    "You explain a move in a business metric to the person who watches it, in two or three plain sentences. "
    "You are given the metric's value for a period and the period before, and a breakdown of the change by its "
    "dimensions: each segment's values, its change and its share of the whole move, worked out for you. "
    "Say how much the metric moved, then which segments carry most of it, with their numbers. If the platform "
    "found something earlier about a moving segment, say what it found, attributed (\"the platform found "
    "earlier that …\"). Use ONLY the numbers given, exactly as given or rounded — write no other number, and "
    "do no arithmetic of your own. Do not speculate about reasons. "
)


def narrate(facts: dict, *, llm: Any = None) -> dict:
    """The model's explanation of one move, checked; ``{"text", "model", "at"}`` or ``{"withheld", …}``."""
    from aughor.agent.claim_type import admissible_verbs_directive
    if llm is None:
        from aughor.llm.provider import get_provider
        llm = get_provider("narrator")
    system = _SYSTEM + admissible_verbs_directive(
        "descriptive", "the explanation rests on a breakdown of the figure by its dimensions, which shows "
                       "where the change sits and not why")
    user = json.dumps(facts, default=str, indent=1)
    draft = llm.complete(system=system, user=user, response_model=MoveStory)
    text = str(getattr(draft, "text", "") or "").strip()
    problems = problems_with(text, facts)
    if problems:
        retry = (f"{user}\n\nYour draft was:\n{text}\n\nIt broke these rules: " + "; ".join(problems)
                 + ". Rewrite it using only the numbers given and describing only where the change sits.")
        text = str(getattr(llm.complete(system=system, user=retry, response_model=MoveStory), "text", "") or "").strip()
        problems = problems_with(text, facts)
    stamp = {"model": str(getattr(llm, "model", "") or ""), "at": datetime.now(timezone.utc).isoformat()}
    if problems:
        return {"text": "", "withheld": f"the explanation the model wrote was withheld: {problems[0]}", **stamp}
    return {"text": text, "checked": ["every number is one the breakdown holds", "a description, no causal claim"],
            **stamp}


def findings_naming(state: dict, segments: list[str]) -> list[str]:
    """What the platform already found that names a moving segment (a name under four characters names
    everything, so it is never matched) — the Briefing's own rule (`briefing.recipes.why_links`)."""
    want = [s for s in segments if s and len(s) >= 4]
    out = []
    for i in state.get("insights") or []:
        f = str((i or {}).get("finding") or "")
        if f and any(s.lower() in f.lower() for s in want):
            out.append(f)
    return out[:MAX_FINDINGS]


def explain_reading(conn_id: str, schema: Optional[str], grain: str, *, llm: Any = None) -> Optional[dict]:
    """Write and keep the explanation of the biggest move in a dataset's newest reading of ``grain``.
    None when there is no move to explain or it is already explained."""
    from aughor.explorer import program as P
    from aughor.explorer import store as expl_store
    key = P.key_for(conn_id, schema)
    reading = (P.load(key).get("watch") or {}).get(grain) or {}
    moved = reading.get("moved") or []
    if not moved or reading.get("story"):
        return None
    top = max(moved, key=lambda m: abs(m.get("rel") or 0))
    explained = [e for e in reading.get("explained") or [] if e.get("metric") == top.get("metric")]
    findings = findings_naming(expl_store.load(key), [str(e.get("group") or "") for e in explained])
    facts = facts_of(top, explained, reading=reading, grain=grain, findings=findings, unit=top.get("unit") or "")
    story = narrate(facts, llm=llm)
    P.record_story(key, grain, {**story, "metric": top.get("name")})
    return story
