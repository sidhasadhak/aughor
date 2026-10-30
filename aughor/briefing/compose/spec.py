"""Arc BC-2 · the blocks an edition is composed from, and what code checks before any is shown (ROADMAP §3.67).

The model chooses; code decides what may be drawn — the `agent/present_tool.py` rule, applied to a page. The
vocabulary is closed and versioned: a sentence with cited numbers, a figure, a bridge, a comparison, a table, a map,
small multiples, a heat grid, progress, a line, a control other blocks listen to, a decision, a quiet line. A block
names the source(s) it reads and the columns it draws; it never carries a number of its own.

Two passes, both code:

* **validate** — every type known, every source present and readable, every column named one its source has, every
  citation pointing at a source, every listener listening to a control whose column its source holds. What fails
  comes back as SENTENCES, handed to the model for one rewrite.
* **gate** — every word (titles, kickers, sentences) against the numbers the sources hold, their changes and
  shares, and against claiming a cause or a forecast (Arc BG's gates). A sentence that fails is withheld and listed;
  a block left with nothing to say is dropped and listed. Withheld is said, never implied.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from aughor.briefing.compose.sources import KNOWN, KNOWN_TEXT, Source

VERSION = 1
MAX_BLOCKS = 14

#: Each type, what it needs, and what it draws — the vocabulary the model is shown, verbatim.
TYPES: dict[str, str] = {
    "lead": "text (required): the range's answer in one or two sentences, numbers cited as {words|source_id}; "
            "sub: one or two sentences more. Always first.",
    "figure": "source (a check): one figure against its usual range; text: a caption.",
    "bridge": "how a total got from one figure to another. EITHER source = a breakdown (from its usual total, each "
              "segment's change, to this range's total) OR chain = check source ids in order (a total, then each "
              "next total; the steps between are their differences).",
    "compare": "source; label (a category column), value (a number column), compare (optional: a column to set it "
               "against, e.g. usual). Bars of this range against the comparison.",
    "table": "source; columns (optional: which to show, in order); link (optional: a column holding an object's key, "
             "e.g. order_id, so each row opens it).",
    "map": "source; label (a country-name column), value (a number column), compare (optional: usual). A world map "
           "coloured by change, with a ranked list beside it.",
    "multiples": "source; x (a date column), series (a column, one small chart per value), value (a number column). "
                 "Each small chart shades its own usual range.",
    "heat": "source; label (row column), series (column column), value, compare (optional). A grid shaded by change; "
            "cells under 30 rows are not shaded.",
    "progress": "source; label, value. Bars of a few totals against each other (a quarter against last year's).",
    "line": "source; x, value; mark (optional): {at: an x value, text: a few words}.",
    "control": "source + column: offers that column's values (and All); other blocks listen to it by naming this "
               "block's id in listens — they fade the rows of every other value. Their sources must hold the column.",
    "decision": "text (required): one sentence asking for a decision. The reader is offered what to do with it: "
                "take it into deep analysis, give it to a team, or put it away.",
    "quiet": "text: one line of what held steady, numbers cited.",
    "context": "source: one of what the platform already knows — a deep analysis (analysis_*), an explorer finding "
               "(finding_*), a decision in the record (decision_*) or what someone said outside the platform "
               "(discussion_*); text: what it means for this range, cited. Draws "
               "that work with a way to open it — a deep analysis this edition started reads as being looked into.",
}
#: What a reader may do with a decision — offered by code on every decision, never chosen by the model.
ACTIONS = ("deep_analysis", "give_to_team", "not_now")
_CITE_RE = re.compile(r"\{([^{}|]+)\|([A-Za-z0-9_\-]+)\}")
_ID_RE = re.compile(r"[^a-z0-9_]+")
#: Where one sentence ends — the split Arc BG's gates read sentences by.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class Mark(BaseModel):
    at: str
    text: str


class Block(BaseModel):
    """One element. Which fields matter depends on ``type`` (see :data:`TYPES`)."""
    id: str = ""
    type: str
    kicker: str = Field(default="", description="A few words: why this block is here")
    title: str = Field(default="", description="A plain sentence saying what it shows")
    text: str = ""
    sub: str = ""
    source: str = ""
    chain: list[str] = Field(default_factory=list)
    label: str = ""
    value: str = ""
    compare: str = ""
    series: str = ""
    x: str = ""
    columns: list[str] = Field(default_factory=list)
    link: str = ""
    column: str = ""
    listens: str = ""
    mark: Optional[Mark] = None
    actions: list[str] = Field(default_factory=list)
    #: Set by code: a block the code added (the floor), or a drill/answer written into the page.
    by_code: bool = False


class Spec(BaseModel):
    version: int = VERSION
    blocks: list[Block] = Field(default_factory=list)


def cites(text: str) -> list[tuple[str, str]]:
    return _CITE_RE.findall(text or "")


def plain(text: str) -> str:
    """The words without the citation marks — what a reader reads and the gates check."""
    return _CITE_RE.sub(lambda m: m.group(1), text or "")


def sources_of(b: Block) -> list[str]:
    ids = ([b.source] if b.source else []) + list(b.chain)
    for field in (b.text, b.sub, b.title, b.kicker):
        ids += [s for _w, s in cites(field)]
    return list(dict.fromkeys(ids))


# ── validate ─────────────────────────────────────────────────────────────────────────────────

def _need(b: Block, n: int, *fields: str) -> list[str]:
    return [f"block {n} ({b.type}) needs {f}" for f in fields if not getattr(b, f)]


def validate(spec: Spec, sources: dict[str, Source]) -> tuple[list[Block], list[str]]:
    """``(blocks that may be drawn, refusals as sentences)``. Ids are made unique slugs; a block with any refusal
    is not among the blocks."""
    refusals: list[str] = []
    kept: list[Block] = []
    seen: set[str] = set()
    controls: dict[str, Block] = {}
    if not spec.blocks:
        return [], ["the edition has no blocks"]
    if len(spec.blocks) > MAX_BLOCKS:
        refusals.append(f"an edition holds at most {MAX_BLOCKS} blocks; this one has {len(spec.blocks)}")
    for n, raw in enumerate(spec.blocks[:MAX_BLOCKS], start=1):
        b = raw.model_copy()
        bid = _ID_RE.sub("_", (b.id or f"{b.type}_{n}").lower()).strip("_") or f"block_{n}"
        if bid in seen:
            bid = f"{bid}_{n}"
        seen.add(bid)
        b.id = bid
        why: list[str] = []
        if b.type not in TYPES:
            refusals.append(f"block {n}: there is no block type {b.type!r} — use one of {', '.join(TYPES)}")
            continue
        if b.type in ("lead", "decision"):
            why += _need(b, n, "text")
        if b.type in ("figure", "compare", "table", "map", "multiples", "heat", "progress", "line", "control",
                      "context"):
            why += _need(b, n, "source")
        if b.type == "bridge" and not (b.source or len(b.chain) >= 2):
            why.append(f"block {n} (bridge) needs a breakdown source or a chain of at least two check sources")
        for sid in sources_of(b):
            src = sources.get(sid)
            if src is None:
                why.append(f"block {n} ({b.type}) reads {sid!r}, which no source is called")
            elif src.status == "refused":
                why.append(f"block {n} ({b.type}) reads {sid!r}, which could not be measured ({src.error[:80]})")
        src = sources.get(b.source)
        if src is not None and src.status != "refused":
            cols = set(src.columns)
            named = [getattr(b, f) for f in ("label", "value", "compare", "series", "x", "link", "column")]
            named += list(b.columns)
            for c in [c for c in named if c and c not in cols]:
                why.append(f"block {n} ({b.type}) names column {c!r}; {b.source!r} has {', '.join(src.columns)}")
            if b.type == "figure" and src.kind != "check":
                why.append(f"block {n} (figure) must read a check; {b.source!r} is a {src.kind}")
            if b.type == "context" and src.kind not in KNOWN:
                why.append(f"block {n} (context) reads a deep analysis, a finding, a decision or a discussion; "
                           f"{b.source!r} is a {src.kind}")
            if b.type != "context" and src.kind in KNOWN and b.type not in ("lead", "quiet", "decision"):
                why.append(f"block {n} ({b.type}) cannot draw {b.source!r}, the platform's own work — use a context block")
            if b.type == "bridge" and b.source and src.kind not in ("breakdown", "drill"):
                why.append(f"block {n} (bridge) reads a breakdown; {b.source!r} is a {src.kind}")
            if b.type in ("compare", "map", "heat", "progress") and not (b.label and b.value) \
                    and src.kind not in ("breakdown", "drill"):
                why.append(f"block {n} ({b.type}) needs label and value columns")
            if b.type in ("multiples",) and not (b.x and b.series and b.value):
                why.append(f"block {n} (multiples) needs x, series and value columns")
            if b.type == "line" and not (b.x and b.value) and src.kind != "check":
                why.append(f"block {n} (line) needs x and value columns")
            if b.type == "control" and not b.column:
                why.append(f"block {n} (control) needs the column whose values it offers")
        if b.type == "decision":
            b.actions = list(ACTIONS)
        if why:
            refusals += why
            continue
        if b.type == "control":
            controls[b.id] = b
        kept.append(b)
    # listeners last: a control may come after nothing, but a listener must hear one whose column it holds
    out = []
    for b in kept:
        if b.listens:
            ctrl = controls.get(b.listens)
            src = sources.get(b.source)
            if ctrl is None:
                refusals.append(f"block {b.id} listens to {b.listens!r}, which is not a control")
                continue
            if src is None or ctrl.column not in src.columns:
                refusals.append(f"block {b.id} listens to {b.listens!r}, but its source has no {ctrl.column!r} column")
                continue
        out.append(b)
    if out and out[0].type != "lead":
        refusals.append("the first block must be the lead: the range's answer in a sentence")
    return out, refusals


# ── gate ─────────────────────────────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def allowed_numbers(sources: dict[str, Source]) -> list[float]:
    """Every number a sentence may state: each source's cells, its facts, the change and share between the cells of
    a row, each column's total and a cell's share of it, and how many rows it has."""
    vals: set[float] = set()

    def add(v: Optional[float], *, share: bool = False):
        if v is None:
            return
        vals.update({v, abs(v)})
        if share or abs(v) <= 1:
            vals.update({v * 100, abs(v * 100)})

    for src in sources.values():
        if src.status == "refused":
            continue
        if src.kind in KNOWN:
            # the platform's own work: a sentence citing it may repeat the numbers it states, and no others of its
            from aughor.briefing.edition import numbers_in
            for k in KNOWN_TEXT:
                for v in numbers_in(str(src.facts.get(k) or "")):
                    add(v)
            continue
        add(float(len(src.rows)))
        share = "ratio" in (src.unit or "") or "%" in (src.unit or "")
        for k, v in (src.facts or {}).items():
            if k in ("rel", "rel_last_year") and _num(v) is not None:
                add(_num(v) * 100)
            elif isinstance(v, dict):
                for vv in v.values():
                    add(_num(vv))
            elif not str(k).endswith("_text"):
                add(_num(v), share=share)
        f = src.facts or {}
        for a, b in (("current", "previous"), ("current", "usual_mean"), ("current", "last_year")):
            x, y = _num(f.get(a)), _num(f.get(b))
            if x is not None and y is not None:
                add(x - y, share=share)
                if y:
                    add((x / y - 1) * 100)
        totals = [0.0] * len(src.columns)
        for row in src.rows:
            nums = [_num(c) for c in row]
            for i, v in enumerate(nums):
                add(v, share=share)
                if v is not None and i < len(totals):
                    totals[i] += v
            present = [v for v in nums if v is not None]
            for i, x in enumerate(present):
                for y in present[i + 1:]:
                    add(x - y, share=share)
                    if y:
                        add((x / y - 1) * 100)
                    if x:
                        add((y / x - 1) * 100)
        for i, t in enumerate(totals):
            if t:
                add(t)
                for row in src.rows:
                    v = _num(row[i]) if i < len(row) else None
                    if v is not None:
                        add(v / t * 100)
    return sorted(vals)


#: The words that only ever claim a direction — "more" and "less" are left out on purpose ("€9.4k more" says how
#: much, not against what), and "up"/"down" count only before a number or a comparison ("down 4%", "up on usual").
_UP = re.compile(r"(?i)\b(rose|risen|rising|grew|grown|increased|higher|above)\b"
                 r"|\bup(?=\s+(?:[-−+€$£]?\d|on\b|from\b|against\b))")
_DOWN = re.compile(r"(?i)\b(fell|fallen|falling|dropped|declined|decreased|lower|below)\b"
                   r"|\bdown(?=\s+(?:[-−+€$£]?\d|on\b|from\b|against\b))")


def _direction(words: str) -> int:
    up, down = bool(_UP.search(words)), bool(_DOWN.search(words))
    return 1 if up and not down else -1 if down and not up else 0


def _labels(src: Source) -> dict[str, list[int]]:
    """The segments a source names — each text value of its first text column — and the rows holding each."""
    col = next((i for i in range(len(src.columns))
                if any(isinstance(r[i], str) for r in src.rows if i < len(r))), None)
    out: dict[str, list[int]] = {}
    if col is None:
        return out
    for n, r in enumerate(src.rows):
        v = r[col] if col < len(r) else None
        if isinstance(v, str) and len(v.strip()) >= 3:
            out.setdefault(v.strip(), []).append(n)
    return out


def _row_numbers(src: Source, rows: list[int]) -> list[float]:
    """What a sentence may say about one segment: its own cells and the changes between them, and its share of each
    column's whole."""
    vals = set(allowed_numbers({src.id: src.model_copy(update={"rows": [src.rows[i] for i in rows], "facts": {}})}))
    for c in range(len(src.columns)):
        total = sum(_num(r[c]) or 0.0 for r in src.rows if c < len(r))
        for i in rows:
            v = _num(src.rows[i][c]) if c < len(src.rows[i]) else None
            if total and v is not None:
                vals.update({v / total * 100, abs(v / total * 100)})
    return sorted(vals)


def _bound(numbers: str, context: str, src: Source, pool: list[float], *, cited: bool = True) -> str:
    """Why words put a number on the wrong thing in ``src``, or "": a cited number another source holds but this
    one does not; a number that is not the segment's the ``context`` (the clause around it) names; a direction the
    measured change does not take."""
    from aughor.briefing.edition import unmeasured_numbers

    if src.status == "refused":
        return ""
    if cited:
        wrong = [n for n in unmeasured_numbers(numbers, allowed_numbers({src.id: src}))
                 if not unmeasured_numbers(n, pool)]
        if wrong:
            return f"it cites {src.label} for {', '.join(wrong)}, which {src.label} does not hold"
    said = _direction(context)
    word = "rose" if said > 0 else "fell"
    if src.kind == "check":
        f = src.facts or {}
        against = ("usual_mean",) if "usual" in context.lower() else ("previous", "usual_mean", "last_year")
        diffs = [_num(f.get("current")) - _num(f.get(k)) for k in against
                 if _num(f.get("current")) is not None and _num(f.get(k)) is not None]
        if said and diffs and all(d * said < 0 for d in diffs):
            return (f"it says {src.label} {word}, but it is {'below' if said > 0 else 'above'} "
                    f"{'its usual' if against == ('usual_mean',) else 'every range it is compared with'}")
        return ""
    labels = _labels(src)
    named = [lab for lab in labels if re.search(rf"(?<!\w){re.escape(lab)}(?!\w)", context)]
    if len(named) != 1:
        return ""
    lab, rows = named[0], labels[named[0]]
    wrong = unmeasured_numbers(numbers, _row_numbers(src, rows))
    if wrong:
        return f"it puts {', '.join(wrong)} on {lab}, which is not {lab}'s in {src.label}"
    if said and src.kind in ("breakdown", "drill") and "change" in src.columns:
        at = src.columns.index("change")
        moves = [_num(src.rows[i][at]) for i in rows if at < len(src.rows[i])]
        moves = [m for m in moves if m is not None]
        if moves and all(m * said < 0 for m in moves):
            return f"it says {lab} {word}, but {lab} is {'below' if said > 0 else 'above'} its usual in {src.label}"
    return ""


#: Where a clause ends — the words around a citation that are about it, and no further.
_CLAUSE_RE = re.compile(r",(?!\d)|[;:—–]|\s(?:but|while|whereas|although|though)\s", re.I)


def _clause(sentence: str, at: int, end: int) -> str:
    """The clause of ``sentence`` around the citation at ``at``…``end`` — read with every citation's own words
    masked, so "€150,773" never ends one."""
    masked = _CITE_RE.sub(lambda m: "x" * len(m.group(0)), sentence)
    before = [m.end() for m in _CLAUSE_RE.finditer(masked, 0, at)]
    after = _CLAUSE_RE.search(masked, end)
    return plain(sentence[(before[-1] if before else 0):(after.start() if after else len(sentence))])


def licensed(sentence: str, sources: dict[str, Source]) -> bool:
    """Whether a sentence that claims a cause cites a finished deep analysis whose claims were licensed causal — the
    one ground a cause stands on here (`agent/claim_type`: the analysis earned it, the edition only repeats it)."""
    return any(sources[sid].kind == "analysis" and sources[sid].status == "final"
               and sources[sid].facts.get("licence") == "causal"
               for _w, sid in cites(sentence) if sid in sources)


def misused(sentence: str, b: Block, sources: dict[str, Source], pool: list[float]) -> str:
    """Why a sentence (citation marks intact) uses a measured number wrongly, or "". Each cited number must come
    from the source its citation names — and from the segment the clause around it names, moving the way it says;
    a number outside a citation must come from a source the block reads."""
    from aughor.briefing.edition import unmeasured_numbers

    for m in _CITE_RE.finditer(sentence):
        words, sid = m.group(1), m.group(2)
        if sid in sources:
            why = _bound(words, _clause(sentence, m.start(), m.end()), sources[sid], pool)
            if why:
                return why
    own = {sid: sources[sid] for sid in sources_of(b) if sid in sources and sources[sid].status != "refused"}
    outside = _CITE_RE.sub(" ", sentence)
    if own:
        wrong = [n for n in unmeasured_numbers(outside, allowed_numbers(own)) if not unmeasured_numbers(n, pool)]
        if wrong:
            return (f"it states {', '.join(wrong)}, which none of the sources it reads "
                    f"({', '.join(s.label for s in own.values())}) holds")
    if b.source in sources and not b.chain and not cites(sentence):
        return _bound(outside, outside, sources[b.source], pool, cited=False)
    return ""


def _words_of(b: Block) -> list[tuple[str, str]]:
    out = [(f, plain(getattr(b, f))) for f in ("kicker", "title", "text", "sub") if getattr(b, f)]
    if b.mark:
        out.append(("mark", b.mark.text))
    return out


def gate(blocks: list[Block], sources: dict[str, Source]) -> tuple[list[Block], list[dict], list[str]]:
    """``(blocks, withheld sentences, held sentences as refusals)``: every word checked against the sources'
    numbers and against claiming a cause or a forecast."""
    from aughor.briefing.edition import held_sentences

    allowed = allowed_numbers(sources)
    withheld: list[dict] = []
    refusals: list[str] = []
    out: list[Block] = []
    for b in blocks:
        b = b.model_copy()
        for field, words in _words_of(b):
            raw = b.mark.text if field == "mark" and b.mark else getattr(b, field)
            held = dict(held_sentences(words, allowed))
            for sentence in _SENTENCE_RE.split(raw):
                said = plain(sentence).strip()
                if said in held and held[said].startswith("it claims a cause") and licensed(sentence, sources):
                    del held[said]
                if said and said not in held:
                    why = misused(sentence, b, sources, allowed)
                    if why:
                        held[said] = why
            if not held:
                continue
            refusals += [f"block {b.id}: “{s}” — {why}" for s, why in held.items()]
            kept = []
            for sentence in _SENTENCE_RE.split(raw):
                if plain(sentence).strip() in held:
                    withheld.append({"block": b.id, "sentence": plain(sentence).strip(),
                                     "why": held[plain(sentence).strip()]})
                elif sentence.strip():
                    kept.append(sentence.strip())
            if field == "mark" and b.mark:
                b.mark = Mark(at=b.mark.at, text=" ".join(kept)) if kept else None
            else:
                setattr(b, field, " ".join(kept))
        if b.type in ("lead", "decision", "quiet") and not b.text:
            withheld.append({"block": b.id, "sentence": "", "why": "every sentence of it was held"})
            continue
        out.append(b)
    return out, withheld, refusals
