"""ON-10 — the question framed against the declared ontology before anything reads it (ROADMAP §3.15, the second movement).

Until this module the investigation met the ontology AFTER it had parsed the question: the intake chose a metric, a
table and a date column from the schema, and only then was the entity those tables back looked up. A business term
the schema does not spell — "dispatch delay", "fulfilled orders", "the Southeast" — was re-derived by whoever read it,
every time, from whatever columns looked closest.

Here the question's words are resolved FIRST, deterministically, against the names the business declared: the object
types (by name, display name, backing table and a person's synonyms) and their properties, the processes with their
stages and promises, what each promise derives (`late_<noun>`, `<noun>_breach_rate`, `<noun>_lag_days`), and the
rules. What they resolve to is the FRAME:

* the OUTCOME the question asks about — a promise (the objects that broke it, and the rate), a lag between two stages,
  or a rule — in the declaration's own words and with its measured numbers. When the words fit several declared
  definitions equally they are all candidates and none is chosen here: a model chooses among them, and only among
  them (`aughor.agent.framing`);
* where to START — the type the outcome is kept per, its backing and its key;
* the RULES and stage MOMENTS the question names, a rule applied from the start through measured to-one links;
* the candidate DRIVERS — the dimensions reachable from the start by declared, measured to-one links within N hops,
  the ones the question names first;
* the outcome COMPILED by the object door's own compiler, so the definition the frame hands on is exactly the one the
  door executes.

A builder-made segment or metric is recorded as a term and defines nothing: the validator proves a guessed filter
EXECUTES, never that the business means it. Only what was declared and measured — a process, a promise, a rule — is a
definition.

Pure: no model, no database, no store — the graph and a person's synonyms are handed in. A frame that resolved no
declared definition `defines` nothing and renders nothing, so a question on a connection where nothing was declared
reads exactly as it did before.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, Field, computed_field

from aughor.ontology.derived import lag_name, late_name, promise_filters, promise_noun, rate_name, rule_filters
from aughor.ontology.models import BusinessRule, EntityProperty, OntologyEntity, OntologyGraph, Process

#: How many declared links a candidate driver may sit from where the frame starts.
DEFAULT_HOPS = 2
_MAX_DRIVERS = 8
#: Breakdowns of the chosen outcome compiled by the drivers the question names — enough to show the shape of "by".
_MAX_COMPILED_BY = 2
#: …and by the CANDIDATE drivers it did not name (2026-09-22): the dimensions the frame reached by measured to-one
#: links, compiled the same way — so a diagnostic run ("what is causing late dispatch") breaks the DECLARED definition
#: down by carrier, category or seller instead of asking a planner to invent the cut, which is where the LuxExperience
#: receipt lost the carrier its question named. Compiling is free (SQL only, no warehouse read); the RUN is bounded on
#: its own (`investigate._MAX_CANDIDATE_BREAKDOWNS`).
_MAX_COMPILED_CANDIDATES = 4
_MAX_PATH_EXPANSIONS = 400

# ── words ───────────────────────────────────────────────────────────────────────────────────

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[A-Za-z0-9]+")


def stem(word: str) -> str:
    """A word reduced to what its inflections share — `dispatched`, `dispatches` → `dispatch`; `delivery`, `delivered`
    → `deliver`; `categories` → `categor`. Small, deterministic and English-only: it never needs to be a linguist, only
    to bring a question's word and a declared name's word to the same stem."""
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        w = w[:-2]
    elif len(w) > 4 and w.endswith(("ches", "shes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suffix in ("ment", "ing", "ed"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break
    if len(w) > 6 and w.endswith("al"):
        w = w[:-2]
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    if len(w) > 3 and w.endswith("y"):
        w = w[:-1]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]
    return w


def words_of(text: str) -> list[str]:
    """The words of a question or a name: `OrderItem` and `order_items` both read `order`, `items`."""
    return _WORD.findall(_CAMEL.sub(" ", text or ""))


def _stems(text: str) -> tuple[str, ...]:
    return tuple(stem(w) for w in words_of(text))


def _stem_set(*words: str) -> frozenset[str]:
    return frozenset(stem(w) for w in words)


_STOP = _stem_set("the", "a", "an", "of", "to", "in", "on", "for", "by", "and", "or", "is", "are", "was", "were", "be",
                  "what", "which", "who", "how", "why", "when", "where", "do", "does", "did", "our", "my", "we", "us",
                  "per", "each", "every", "with", "from", "at", "as", "that", "this", "it", "its", "all", "any")
#: Words that ask whether a promise was kept.
_LATE = _stem_set("late", "lateness", "overdue", "breach", "breached", "breaches", "broke", "broken", "break",
                  "breaking", "miss", "missed", "misses", "missing", "sla", "deadline", "tardy", "promise", "promised")
#: Words that ask about lateness OR about duration, by what stands beside them ("a dispatch delay" · "delay in days").
_DELAY = _stem_set("delay", "delayed", "delays", "behind")
#: Words that judge how a stage is doing — a promise's record, when the stage they judge carries one.
_JUDGE = _stem_set("worst", "best", "worse", "better", "bad", "good", "record", "performance", "perform", "performing",
                   "doing", "hold", "holds", "held", "kept", "keep", "keeping", "reliable", "reliability", "compliance",
                   "adherence", "fail", "failed", "failing", "failure")
#: Words that ask how long a stage takes.
_DURATION = _stem_set("lag", "long", "day", "hour", "time", "turnaround", "lead", "duration", "take", "took", "taking",
                      "speed", "fast", "faster", "quick", "quickly", "slow", "slower", "wait", "waiting", "cycle")
#: Trailing words a property's name carries that no question says: `product_category_name` is asked as "product category".
_GENERIC_TAIL = _stem_set("name", "nm", "id", "code", "cd", "desc", "label", "txt")

# ── the frame ───────────────────────────────────────────────────────────────────────────────

TermKind = Literal["entity", "property", "process", "stage", "promise", "lag", "rule", "metric", "segment"]


class FrameTerm(BaseModel):
    """One run of the question's words and the declared name it resolved to."""
    text: str
    kind: TermKind
    #: The name resolved to: an entity id, `Entity.property`, a process id, `process.stage`, a rule id, a metric name.
    target: str
    label: str = ""
    #: How it matched: name · display name · api name · table · synonym · promise · derived name · short name · its
    #: words (a rule's name, its words in another order within one sentence).
    via: str = ""
    #: For a derived name: what it asks — `late` (the segment), `rate` (the metric) or `lag`.
    intent: str = ""
    start: int = 0
    end: int = 0


class FrameOutcome(BaseModel):
    """A declared definition the question may be asking about — its words, its numbers and the names it compiles to."""
    kind: Literal["promise", "lag", "rule"]
    #: The name the object door executes: the breach rate for a promise, the lag for a lag, the segment for a rule.
    name: str
    label: str
    entity: str
    object_type: str
    process: str = ""
    stage: str = ""
    promise: str = ""
    segment: str = ""
    metric: str = ""
    lag: str = ""
    definition: str = ""
    measured: str = ""
    rate: Optional[float] = None
    usable: bool = False
    why_not: str = ""
    caveats: list[str] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    score: int = 0
    #: What the link graph said about this candidate when it ranked it.
    note: str = ""


class FrameRule(BaseModel):
    """A rule the question names, as filters from where the frame starts."""
    id: str
    label: str
    entity: str
    words: str
    owner: str = ""
    matched: str = ""
    #: The to-one link path from the start to the rule's type ("" when the rule is about the start itself).
    via: str = ""
    filters: list[dict] = Field(default_factory=list)
    measured: str = ""
    usable: bool = False
    why_not: str = ""


class FrameMoment(BaseModel):
    """A stage the question names for its moment ("placed in 2017"): the timestamp the business means by it."""
    text: str
    process: str
    process_label: str
    stage: str
    entity: str
    timestamp: str


class FrameDriver(BaseModel):
    """A dimension reachable from the start by measured to-one links — a candidate explanation of the outcome."""
    path: str
    label: str
    entity: str
    object_type: str
    property: str
    #: The table the property is read from — the type's backing table, or the binding's that supplies it.
    table: str = ""
    links: list[str] = Field(default_factory=list)
    named: bool = False


class Frame(BaseModel):
    """What a question's words resolve to on one ontology. `defines` says whether any of it is a declared definition."""
    question: str
    connection_id: str = ""
    schema_name: str = ""
    hops: int = DEFAULT_HOPS
    terms: list[FrameTerm] = Field(default_factory=list)
    outcomes: list[FrameOutcome] = Field(default_factory=list)
    #: The outcome read, by its index in `outcomes`; None when there is none or the words fit several equally.
    chosen: Optional[int] = None
    #: `names` — the declared names settled it; `model` — a model chose among the candidates.
    chosen_by: str = ""
    start: Optional[dict] = None
    rules: list[FrameRule] = Field(default_factory=list)
    moments: list[FrameMoment] = Field(default_factory=list)
    drivers: list[FrameDriver] = Field(default_factory=list)
    #: The definitions compiled by the object door: `{name: {"query", "sql", "plan", "caveats"} | {"query", "refused"}}`.
    compiled: dict[str, dict] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    reading: str = ""

    @property
    def outcome(self) -> Optional[FrameOutcome]:
        return self.outcomes[self.chosen] if self.chosen is not None and 0 <= self.chosen < len(self.outcomes) else None

    def candidates(self) -> list[FrameOutcome]:
        return [o for o in self.outcomes if o.usable]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def defines(self) -> bool:
        """True when the question's words reached something the business DECLARED and the data measured: a promise, a
        lag or a rule the object door can execute, or a stage's moment."""
        return any(o.usable for o in self.outcomes) or any(r.usable for r in self.rules) or bool(self.moments)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ambiguous(self) -> bool:
        return self.chosen is None and len(self.candidates()) > 1


# ── the names the business declared ─────────────────────────────────────────────────────────

_KIND_RANK = {"entity": 1, "segment": 2, "metric": 2, "property": 2,
              "process": 3, "stage": 3, "promise": 3, "lag": 3, "rule": 3}
_VIA_RANK = {"derived name": 0, "name": 1, "promise": 1, "display name": 2, "api name": 3, "table": 4, "synonym": 5,
             "short name": 6, "its words": 7}
#: What follows an answer instruction's verb — "Return THE region", "Order EACH category" — and never follows a type named
#: as the noun that heads a clause.
_DETERMINERS = frozenset({"the", "each", "every", "a", "an", "all", "only", "both", "its", "their", "this", "these",
                          "those", "top", "first", "last", "one", "two", "three", "four", "five", "six", "seven", "eight",
                          "nine", "ten"})
_SENTENCE_END = re.compile(r"[?!;]|\.(?=\s|$)")
_CLAUSE_BREAK = re.compile(r"[?!;:,]|\.(?=\s|$)")


@dataclass(frozen=True)
class _Name:
    stems: tuple[str, ...]
    kind: str
    target: str
    label: str
    via: str
    intent: str = ""


@dataclass
class _Index:
    names: list[_Name] = field(default_factory=list)

    def add(self, text: str, kind: str, target: str, label: str, via: str, intent: str = "") -> None:
        self.add_stems(_stems(text), kind, target, label, via, intent)

    def add_stems(self, stems: tuple[str, ...], kind: str, target: str, label: str, via: str, intent: str = "") -> None:
        if stems and not all(s in _STOP for s in stems):
            self.names.append(_Name(stems, kind, target, label, via, intent))


def _label(entity: OntologyEntity) -> str:
    return entity.display_name or entity.id


def _process_label(process: Process) -> str:
    return process.display_name or process.id.replace("_", " ")


def _readable_properties(entity: OntologyEntity) -> dict[str, EntityProperty]:
    """The properties the object door reads on a type: its backing's, then each binding's it would not refuse."""
    from aughor.ontology.bindings import binding_problem
    props = dict(entity.properties or {})
    for binding in entity.bindings or []:
        if not binding_problem(entity, binding):
            for name, p in binding.properties.items():
                props.setdefault(name, p)
    return props


def _property_stems(entity: OntologyEntity, name: str) -> list[tuple[tuple[str, ...], str]]:
    """The ways a question names a property: its name with a generic tail dropped, and — as a weaker short name —
    without the type's own name in front (`seller_state` on Seller is also just "state")."""
    stems = list(_stems(name))
    while len(stems) > 1 and stems[-1] in _GENERIC_TAIL:
        stems.pop()
    out = [(tuple(stems), "name")]
    owns = {_stems(entity.id), _stems(entity.api_name), *(_stems(t.rsplit(".", 1)[-1]) for t in entity.source_tables)}
    for own in owns:
        if own and len(stems) > len(own) and tuple(stems[:len(own)]) == own:
            out.append((tuple(stems[len(own):]), "short name"))
        elif own and len(stems) > 1 and stems[0] == own[-1]:
            out.append((tuple(stems[1:]), "short name"))
    return list(dict.fromkeys(out))


def _index(graph: OntologyGraph, synonyms: Iterable[Any]) -> _Index:
    ix = _Index()
    tables: dict[str, str] = {}
    for e in graph.entities.values():
        label = _label(e)
        ix.add(e.id, "entity", e.id, label, "name")
        ix.add(e.api_name, "entity", e.id, label, "api name")
        ix.add(e.display_name or "", "entity", e.id, label, "display name")
        for t in e.source_tables:
            bare = t.rsplit(".", 1)[-1]
            tables.setdefault(bare.lower(), e.id)
            ix.add(bare, "entity", e.id, label, "table")
        for name, p in _readable_properties(e).items():
            if (p.semantic_type or "") == "key":
                continue
            for stems, via in _property_stems(e, name):
                ix.add_stems(stems, "property", f"{e.id}.{name}", f"{label} · {name.replace('_', ' ')}", via)
        for sid, seg in (e.segments or {}).items():
            if seg.verified and (seg.filter_sql or "").strip():
                ix.add(sid, "segment", f"{e.id}.{sid}", seg.display_name or sid, "name")
                ix.add(seg.display_name or "", "segment", f"{e.id}.{sid}", seg.display_name or sid, "display name")
    for p in (graph.processes or {}).values():
        plabel = _process_label(p)
        ix.add(p.id, "process", p.id, plabel, "name")
        ix.add(p.display_name or "", "process", p.id, plabel, "display name")
        for i, s in enumerate(p.stages):
            target = f"{p.id}.{s.name}"
            ix.add(s.name, "stage", target, f"{plabel} · {s.name}", "name")
            ix.add(s.display_name or "", "stage", target, f"{plabel} · {s.name}", "display name")
            if s.promise is not None:
                noun = promise_noun(s)
                ix.add(noun, "promise", target, f"the {noun} promise", "promise")
                ix.add(late_name(s), "promise", target, f"the {noun} promise", "derived name", intent="late")
                ix.add(rate_name(s), "promise", target, f"the {noun} promise", "derived name", intent="rate")
            previous = p.stages[i - 1] if i else None
            if s.timestamp and previous is not None and previous.timestamp:
                ix.add(lag_name(s), "lag", target, lag_name(s), "derived name", intent="lag")
    for r in (graph.rules or {}).values():
        ix.add(r.id, "rule", r.id, r.display_name or r.id, "name")
        ix.add(r.display_name or "", "rule", r.id, r.display_name or r.id, "display name")
        # the property a rule groups is named by its last word too: "EU markets … return the country" means the
        # `ship_country` the rule is defined on, a word nothing else in the index gives it
        entity = graph.entities.get(r.entity)
        for prop in _rule_properties(r):
            if entity is None or prop not in _readable_properties(entity):
                continue
            stems = list(_stems(prop))
            while len(stems) > 1 and stems[-1] in _GENERIC_TAIL:
                stems.pop()
            if len(stems) > 1:
                ix.add_stems((stems[-1],), "property", f"{entity.id}.{prop}",
                             f"{_label(entity)} · {prop.replace('_', ' ')}", "short name")
    for mid, m in (graph.metrics or {}).items():
        ix.add(mid, "metric", mid, m.display_name or mid, "name")
        ix.add(m.display_name or "", "metric", mid, m.display_name or mid, "display name")
    for s in synonyms or ():
        kind, subject, synonym = _synonym_parts(s)
        target = _synonym_target(graph, tables, kind, subject)
        if target is not None:
            ix.add(synonym, target[0], target[1], target[2], "synonym")
    return ix


def _synonym_parts(s: Any) -> tuple[str, str, str]:
    if isinstance(s, (tuple, list)):
        return str(s[0]), str(s[1]), str(s[2])
    return str(getattr(s, "subject_kind", "")), str(getattr(s, "subject_id", "")), str(getattr(s, "synonym", ""))


def _synonym_target(graph: OntologyGraph, tables: dict[str, str], kind: str,
                    subject: str) -> Optional[tuple[str, str, str]]:
    """What a person's synonym names on THIS graph, as (kind, target, label) — or None, never a guess."""
    low = subject.strip().lower()
    if kind == "table":
        eid = tables.get(low.rsplit(".", 1)[-1])
        return ("entity", eid, _label(graph.entities[eid])) if eid else None
    if kind == "column":
        table, _, column = low.rpartition(".")
        for e in graph.entities.values():
            if table and table.rsplit(".", 1)[-1] not in {t.rsplit(".", 1)[-1].lower() for t in e.source_tables}:
                continue
            name = next((n for n in _readable_properties(e) if n.lower() == column), None)
            if name:
                return "property", f"{e.id}.{name}", f"{_label(e)} · {name.replace('_', ' ')}"
        return None
    for e in graph.entities.values():
        if low in (e.id.lower(), e.api_name.lower()):
            return "entity", e.id, _label(e)
    for p in (graph.processes or {}).values():
        if low == p.id.lower():
            return "process", p.id, _process_label(p)
        for s in p.stages:
            if low == f"{p.id}.{s.name}".lower():
                return "stage", f"{p.id}.{s.name}", f"{_process_label(p)} · {s.name}"
    for r in (graph.rules or {}).values():
        if low == r.id.lower():
            return "rule", r.id, r.display_name or r.id
    metric = next((k for k in graph.metrics or {} if k.lower() == low), None)
    return ("metric", metric, metric) if metric else None


# ── matching ────────────────────────────────────────────────────────────────────────────────


def _match(question: str, ix: _Index) -> tuple[list[FrameTerm], list[str], list[str]]:
    """Every declared name the question spells, kept unless a longer match of at least its rank covers it; a rule's name
    also with its words in another order within one sentence; never the verb of an answer instruction. Returns the
    terms, the question's words and their stems."""
    words = words_of(question)
    tokens = [stem(w) for w in words]
    sentence, commands = _clauses(question)
    found: dict[tuple[int, int, str, str], _Name] = {}
    for name in ix.names:
        n = len(name.stems)
        for i in range(len(tokens) - n + 1):
            if tuple(tokens[i:i + n]) != name.stems or (n == 1 and i in commands):
                continue
            key = (i, i + n, name.kind, name.target)
            held = found.get(key)
            if held is None or _VIA_RANK.get(name.via, 9) < _VIA_RANK.get(held.via, 9):
                found[key] = name
    # a stage's name and its promise's noun are the same words for the same stage: the promise says more
    for (i, j, kind, target) in list(found):
        if kind == "stage" and (i, j, "promise", target) in found:
            del found[(i, j, kind, target)]
    kept = []
    for (i, j, kind, target), name in found.items():
        rank = _KIND_RANK[kind]
        covered = any(a <= i and j <= b and (b - a) > (j - i) and _KIND_RANK[k] >= rank for (a, b, k, _t) in found)
        if not covered:
            kept.append((i, j, name))
    # a short name that repeats the tail of a property the question already named in full ("seller states … return the
    # state") is that property again, never a second one
    full_tails = [name.stems for _i, _j, name in kept if name.kind == "property" and name.via != "short name"]
    kept = [(i, j, name) for i, j, name in kept
            if not (name.kind == "property" and name.via == "short name"
                    and any(len(t) > len(name.stems) and t[-len(name.stems):] == name.stems for t in full_tails))]
    # a rule's name with its words in another order inside one sentence ("returns that were controllable") — weaker than
    # its spelling, and covering nothing: the words between are the question's own
    texts: dict[tuple[int, int, str], str] = {}
    spelled = {target for (_i, _j, kind, target) in found if kind == "rule"}
    for name in ix.names:
        if name.kind != "rule" or len(name.stems) < 2 or name.target in spelled:
            continue
        at = _in_one_sentence(name.stems, tokens, sentence, commands)
        if at is None:
            continue
        spelled.add(name.target)
        i, j = min(at), max(at) + 1
        kept.append((i, j, _Name(name.stems, name.kind, name.target, name.label, "its words")))
        texts[(i, j, name.target)] = " … ".join(words[p] for p in sorted(at))
    kept.sort(key=lambda m: (m[0], -(m[1] - m[0]), _VIA_RANK.get(m[2].via, 9), m[2].target))
    terms = [FrameTerm(text=texts.get((i, j, name.target)) or " ".join(words[i:j]), kind=name.kind, target=name.target,
                       label=name.label, via=name.via, intent=name.intent, start=i, end=j) for i, j, name in kept]
    return terms, words, tokens


def _clauses(question: str) -> tuple[list[int], set[int]]:
    """For each of the question's words, as `words_of` reads them, the sentence it sits in — and which words are an answer
    instruction's verb: a clause's first word followed by a determiner ("Return the region", "Order each category"), a
    thing the question asks the reader to DO, never a type it names. A plural is a noun ("Reviews the customers wrote")."""
    text = _CAMEL.sub(" ", question or "")
    found = list(_WORD.finditer(text))
    sentence: list[int] = []
    heads: set[int] = set()
    at, last = 0, 0
    for k, m in enumerate(found):
        gap = text[last:m.start()]
        if k and _SENTENCE_END.search(gap):
            at += 1
        if k == 0 or _CLAUSE_BREAK.search(gap) or found[k - 1].group().lower() in ("and", "then"):
            heads.add(k)
        sentence.append(at)
        last = m.end()
    commands: set[int] = set()
    for k in heads:
        word = found[k].group().lower()
        after = found[k + 1].group().lower() if k + 1 < len(found) else ""
        if (after in _DETERMINERS or after.isdigit()) and not (word.endswith("s") and not word.endswith("ss")):
            commands.add(k)
    return sentence, commands


def _in_one_sentence(stems: tuple[str, ...], tokens: list[str], sentence: list[int],
                     commands: set[int]) -> Optional[list[int]]:
    """Distinct positions spelling each of ``stems`` inside a single sentence, in any order — in the first sentence that
    holds them all — or None."""
    for at in dict.fromkeys(sentence):
        taken: list[int] = []
        for s in stems:
            p = next((k for k, t in enumerate(tokens)
                      if t == s and sentence[k] == at and k not in taken and k not in commands), None)
            if p is None:
                break
            taken.append(p)
        else:
            return taken
    return None


# ── links, from where the frame stands ──────────────────────────────────────────────────────


def _to_one_paths(graph: OntologyGraph, start: OntologyEntity, hops: int) -> list[tuple[OntologyEntity, list]]:
    """Every type reachable from ``start`` by measured to-one links within ``hops``, shortest chains first — the start
    itself at no hop. A link the object door would refuse to traverse is never followed."""
    from aughor.semantic.object_query import link_problem, object_links
    out: list[tuple[OntologyEntity, list]] = [(start, [])]
    queue: deque = deque([(start, [])])
    budget = _MAX_PATH_EXPANSIONS
    while queue and budget > 0:
        entity, chain = queue.popleft()
        if len(chain) >= hops:
            continue
        on_chain = {start.id} | {h.target.id for h in chain}
        for h in object_links(graph, entity):
            budget -= 1
            if not h.to_one or h.target.id in on_chain or link_problem(h):
                continue
            step = chain + [h]
            out.append((h.target, step))
            queue.append((h.target, step))
    return out


def _path_to(paths: list[tuple[OntologyEntity, list]], entity_id: str) -> Optional[list]:
    return next((chain for e, chain in paths if e.id == entity_id), None)


def _prefixed(filters: Iterable[dict], prefix: str) -> list[dict]:
    out = []
    for f in filters:
        g = dict(f)
        if prefix:
            g["path"] = f"{prefix}.{g['path']}"
            if g.get("value_path"):
                g["value_path"] = f"{prefix}.{g['value_path']}"
        out.append(g)
    return out


# ── the outcomes ────────────────────────────────────────────────────────────────────────────


def _stage_at(graph: OntologyGraph, target: str) -> tuple[Optional[Process], int]:
    pid, _, sname = target.partition(".")
    process = (graph.processes or {}).get(pid)
    if process is None:
        return None, -1
    return process, next((i for i, s in enumerate(process.stages) if s.name == sname), -1)


def _api(graph: OntologyGraph, entity_id: str) -> str:
    e = graph.entities.get(entity_id)
    return e.api_name if e is not None else entity_id


def _a(word: str) -> str:
    return f"{'an' if (word or 'x')[0].lower() in 'aeiou' else 'a'} {word}"


def _promise_outcome(graph: OntologyGraph, process: Process, index: int) -> Optional[FrameOutcome]:
    stage = process.stages[index]
    spec = promise_filters(process, index)
    promise = stage.promise
    if spec is None or promise is None:
        return None
    noun = promise_noun(stage)
    grain = graph.entities.get(spec["grain"])
    grain_label = _label(grain) if grain is not None else spec["grain"]
    usable = promise.verified is True
    why_not = "" if usable else ("it was measured and does not hold — " + promise.note if promise.verified is False
                                 else "it has not been measured — POST /ontology/measure counts it")
    definition = (f"{_a(grain_label)} breaks it when {spec['words']}; its rate counts only the {grain_label} objects "
                   f"that reached {stage.name} with the promise in force")
    return FrameOutcome(
        kind="promise", name=rate_name(stage), label=f"the {noun} promise of {_process_label(process)} (stage {stage.name})",
        entity=spec["grain"], object_type=_api(graph, spec["grain"]), process=process.id, stage=stage.name, promise=noun,
        segment=late_name(stage), metric=rate_name(stage), definition=definition, measured=promise.note,
        rate=promise.breach_rate, usable=usable, why_not=why_not,
        caveats=[f"the {noun} promise: {flag}" for flag in promise.flags])


def _lag_outcome(graph: OntologyGraph, process: Process, index: int) -> Optional[FrameOutcome]:
    stage = process.stages[index]
    previous = process.stages[index - 1] if index else None
    if not (stage.timestamp and previous is not None and previous.timestamp):
        return None
    usable = stage.verified is True and previous.verified is True
    timed = [f"p{q} {v:g}" for q, v in ((50, stage.p50_days), (90, stage.p90_days), (95, stage.p95_days)) if v is not None]
    measured = (f"{stage.both:,} {process.entity} objects carry both moments; " + " · ".join(timed) + " calendar days"
                if stage.both and timed else stage.note)
    return FrameOutcome(
        kind="lag", name=lag_name(stage), label=f"{lag_name(stage)} of {_process_label(process)}",
        entity=process.entity, object_type=_api(graph, process.entity), process=process.id, stage=stage.name,
        lag=lag_name(stage),
        definition=(f"the calendar days from {previous.name} ({previous.timestamp}) to {stage.name} ({stage.timestamp}) "
                    f"on each {process.entity} object"),
        measured=measured, usable=usable,
        why_not="" if usable else "its stages have not been measured, or one of them is reached by no object")


def _rule_words(rule: BusinessRule) -> str:
    if rule.kind == "value_set":
        return f"{rule.entity}.{rule.property} is one of {', '.join(rule.values)}"
    out = []
    for c in rule.conditions:
        rhs = c.get("value_path") or c.get("values") or c.get("value")
        out.append(f"{c.get('path')} {c.get('op')}" + ("" if rhs in (None, "", []) else f" {rhs}"))
    return "; ".join(out)


def _rule_properties(rule: BusinessRule) -> list[str]:
    """The properties of its own type a rule is defined on — a value set's property, a condition's paths — by name."""
    paths = [rule.property] if rule.kind == "value_set" else [str(c.get("path") or "") for c in rule.conditions]
    return [p for p in dict.fromkeys(paths) if p and "." not in p]


def _rule_outcome(graph: OntologyGraph, rule: BusinessRule) -> FrameOutcome:
    usable = rule.verified is True
    return FrameOutcome(
        kind="rule", name=rule.id, label=f"rule {rule.id}" + (f" (owned by {rule.owner})" if rule.owner else ""),
        entity=rule.entity, object_type=_api(graph, rule.entity), segment=rule.id,
        definition=rule.description or _rule_words(rule), measured=rule.note, usable=usable,
        why_not="" if usable else "it has not been measured, or it admits no object",
        caveats=[f"rule {rule.id}: {flag}" for flag in rule.flags])


@dataclass
class _Asks:
    """What kind of answer the question's words ask for, apart from the names they spell."""
    late: bool          # a promise kept or broken
    delay: bool         # "delay" — lateness, or duration when a duration word stands beside it
    duration: bool      # how long a stage takes
    judge: bool         # how a stage is doing — its promise's record, when it carries one
    late_word: str


def _asks(words: list[str], tokens: list[str]) -> _Asks:
    on_time = {i + 1 for i in range(len(tokens) - 1) if tokens[i] == "on" and tokens[i + 1] == stem("time")}
    late_at = [i for i, t in enumerate(tokens) if t in _LATE] + sorted(on_time)
    delay_at = [i for i, t in enumerate(tokens) if t in _DELAY]
    duration = any(t in _DURATION for i, t in enumerate(tokens) if i not in on_time)
    said = sorted(late_at + delay_at)
    return _Asks(late=bool(late_at), delay=bool(delay_at), duration=duration,
                 judge=any(t in _JUDGE for t in tokens), late_word=words[said[0]] if said else "")


def _outcomes(graph: OntologyGraph, terms: list[FrameTerm], asks: _Asks, named_groups: list[list[tuple[str, str]]],
              hops: int) -> list[FrameOutcome]:
    found: dict[tuple[str, str], FrameOutcome] = {}

    def keep(o: Optional[FrameOutcome], score: int, said: str) -> None:
        if o is None:
            return
        held = found.get((o.kind, o.name))
        if held is None:
            o.score, o.matched = score, [said]
            found[(o.kind, o.name)] = o
            return
        held.score = max(held.score, score)
        if said not in held.matched:
            held.matched.append(said)

    lateness = asks.late or (asks.delay and not asks.duration)
    for t in terms:
        if t.kind not in ("promise", "stage", "lag"):
            continue
        process, index = _stage_at(graph, t.target)
        if process is None or index < 0:
            continue
        if t.intent in ("late", "rate"):
            keep(_promise_outcome(graph, process, index), 3, t.text)
            continue
        if t.intent == "lag":
            keep(_lag_outcome(graph, process, index), 3, t.text)
            continue
        if process.stages[index].promise is not None and (lateness or asks.delay or asks.judge):
            keep(_promise_outcome(graph, process, index), 2 if (lateness or asks.judge) else 1, t.text)
        if asks.duration:
            keep(_lag_outcome(graph, process, index), 1 if asks.late else 2, t.text)
    if (asks.late or asks.delay) and not any(o.kind == "promise" for o in found.values()):
        # a promise asked about by no stage's name: every promise of the processes named — of every process when none
        # is — is a candidate, ranked by what the question names that its type can reach
        named_processes = {t.target for t in terms if t.kind == "process"}
        entity_terms = {t.target for t in terms if t.kind == "entity"}
        for process in (graph.processes or {}).values():
            if named_processes and process.id not in named_processes:
                continue
            for index, stage in enumerate(process.stages):
                o = _promise_outcome(graph, process, index) if stage.promise is not None else None
                if o is None:
                    continue
                score, grain = 1, graph.entities.get(o.entity)
                if grain is not None and named_groups:
                    # each run of words the question spends on a property is explained when the type reaches ANY
                    # property those words fit — a homonym no type reaches must not veto the one that is reached
                    reach = {e.id for e, _chain in _to_one_paths(graph, grain, hops)}
                    missing = [group for group in named_groups if not any(eid in reach for eid, _p in group)]
                    if not missing:
                        score += 1
                    else:
                        words = sorted({prop.replace("_", " ") for group in missing for _eid, prop in group})
                        o.note = (f"kept per {o.entity}, which reaches no {', '.join(words)} "
                                  f"by measured to-one links within {hops} hops")
                if o.entity in entity_terms:
                    score += 1
                keep(o, score, asks.late_word)
    if not found:
        for t in terms:
            if t.kind == "rule" and t.target in (graph.rules or {}):
                keep(_rule_outcome(graph, graph.rules[t.target]), 2, t.text)

    def first_seen(o: FrameOutcome) -> int:
        return min((t.start for t in terms if t.text in o.matched), default=10_000)

    def in_process_order(o: FrameOutcome) -> tuple:
        process = (graph.processes or {}).get(o.process)
        index = next((i for i, s in enumerate(process.stages) if s.name == o.stage), 0) if process is not None else 0
        return (o.process, index, o.kind, o.name)

    return sorted(found.values(), key=lambda o: (not o.usable, -o.score, first_seen(o), in_process_order(o)))


def _choose(outcomes: list[FrameOutcome], choice: str) -> tuple[Optional[int], str]:
    usable = [i for i, o in enumerate(outcomes) if o.usable]
    if choice:
        low = choice.strip().lower()
        hit = next((i for i in usable if low in (outcomes[i].name.lower(), outcomes[i].label.lower(),
                                                 outcomes[i].segment.lower())), None)
        if hit is not None:
            return hit, ""
        return _choose(outcomes, "")[0], f"'{choice}' is not one of the declared definitions the question fits"
    if not usable:
        return None, ""
    top = outcomes[usable[0]].score
    tied = [i for i in usable if outcomes[i].score == top]
    if len(tied) > 1 and all(outcomes[i].kind == "rule" for i in tied):
        # rules named together are filters that all apply from where the reading starts — never definitions to choose
        # between — so no choice is asked for, and the first named reads as the outcome
        return usable[0], ""
    return (usable[0] if len(tied) == 1 else None), ""


# ── the frame ───────────────────────────────────────────────────────────────────────────────


def frame_question(question: str, graph: Optional[OntologyGraph], *, synonyms: Iterable[Any] = (),
                   hops: int = DEFAULT_HOPS, dialect: str = "duckdb", choice: str = "", chosen_by: str = "") -> Frame:
    """Resolve ``question``'s words against the names declared on ``graph`` and return the frame. ``synonyms`` are a
    person's (`Synonym` rows, or ``(subject_kind, subject_id, synonym)``). ``choice`` names one of the outcome
    candidates — a model's choice among them; a name that is not a candidate chooses nothing and says so."""
    from aughor.semantic.object_query import MAX_LINK_HOPS
    hops = max(1, min(int(hops or DEFAULT_HOPS), MAX_LINK_HOPS))
    frame = Frame(question=question or "", hops=hops)
    if graph is None or not graph.entities:
        return frame
    frame.connection_id, frame.schema_name = graph.connection_id, graph.schema_name
    terms, words, tokens = _match(question or "", _index(graph, synonyms))
    frame.terms = terms
    spans: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for t in terms:
        if t.kind == "property":
            entity_id, prop = t.target.split(".", 1)
            spans.setdefault((t.start, t.end), []).append((entity_id, prop))
    frame.outcomes = _outcomes(graph, terms, _asks(words, tokens), list(spans.values()), hops)
    frame.chosen, note = _choose(frame.outcomes, choice)
    if note:
        frame.notes.append(note)
    if frame.chosen is not None:
        frame.chosen_by = (chosen_by or "model") if choice and not note else "names"
        frame.notes.extend(f"{o.label}: {o.note}" for o in frame.candidates() if o.note and o is not frame.outcome)
        frame.notes.extend(frame.outcome.caveats)
    else:
        frame.notes.extend(c for o in frame.candidates() for c in o.caveats)

    start = _start_entity(graph, frame, terms)
    paths = _to_one_paths(graph, start, hops) if start is not None else []
    if start is not None:
        b = start.backing
        frame.start = {"object_type": start.api_name, "entity": start.id, "name": _label(start),
                       "table": (b.table if b is not None and b.kind == "table" else "a keyed SELECT") or "",
                       "key": (b.primary_key if b is not None else "") or start.identity_key,
                       "key_unique": b.verified if b is not None else None}
    _frame_rules(graph, frame, terms, start, paths)
    _frame_moments(graph, frame, terms)
    _frame_drivers(frame, _said_which(graph, frame, terms, spans), start, paths)
    _frame_compiled(graph, frame, dialect)
    frame.reading = frame_reading(frame)
    return frame


def _start_entity(graph: OntologyGraph, frame: Frame, terms: list[FrameTerm]) -> Optional[OntologyEntity]:
    o = frame.outcome
    if o is not None and o.kind != "rule":
        return graph.entities.get(o.entity)
    rules = [graph.rules[t.target] for t in terms if t.kind == "rule" and t.target in (graph.rules or {})
             and graph.rules[t.target].verified is True]
    if o is not None and o.name in (graph.rules or {}):
        rules = [graph.rules[o.name], *(r for r in rules if r.id != o.name)]
    candidates = frame.candidates()
    if rules and (o is not None or (len(candidates) > 1 and all(c.kind == "rule" for c in candidates))):
        return _filtered_start(graph, frame, terms, rules)
    if o is not None:
        return graph.entities.get(o.entity)
    if len(candidates) > 1:
        return None                                      # several candidates: where to start follows the choice
    for t in terms:
        if t.kind == "rule" and t.target in (graph.rules or {}):
            return graph.entities.get(graph.rules[t.target].entity)
    for t in terms:
        if t.kind in ("stage", "promise", "process"):
            process = (graph.processes or {}).get(t.target.split(".", 1)[0])
            if process is not None:
                return graph.entities.get(process.entity)
    widest = max((t for t in terms if t.kind == "entity"), key=lambda t: (t.end - t.start, -t.start), default=None)
    return graph.entities.get(widest.target) if widest is not None else None


#: The words that head a count: what they name first is what the question counts.
_COUNT_HEADS = {("how", "many"), ("number", "of"), ("count", "of")}


def _filtered_start(graph: OntologyGraph, frame: Frame, terms: list[FrameTerm],
                    rules: list[BusinessRule]) -> Optional[OntologyEntity]:
    """Where a reading of rules alone starts. A question that asks how many of a rule, or of a type a rule is defined on —
    "How many VIP customers placed an order" — counts that type, and reads from it when it reaches every rule's type.
    Otherwise: a type the question names that reaches every rule's type by measured to-one links — the objects the rules
    filter, so "orders placed by VIP customers" counts orders, and "Which EU core customer wrote the most reviews" counts
    reviews — preferring a type that is no rule's own; else the first rule's type that reaches the others; else the first
    rule's type."""
    kinds = list(dict.fromkeys(r.entity for r in rules))

    def reaches_all(entity: OntologyEntity) -> bool:
        reach = {e.id for e, _chain in _to_one_paths(graph, entity, frame.hops)}
        return all(k in reach for k in kinds)

    lowered = [w.lower() for w in words_of(frame.question)]
    heads = [i + 2 for i in range(len(lowered) - 1) if (lowered[i], lowered[i + 1]) in _COUNT_HEADS]
    if heads:
        # what a count's head names first is what the question counts, when a rule is defined on it
        first = min((t for t in terms if t.start >= heads[0] and ((t.kind == "entity" and t.target in graph.entities)
                     or (t.kind == "rule" and t.target in (graph.rules or {})))), key=lambda t: t.start, default=None)
        counted = "" if first is None else (graph.rules[first.target].entity if first.kind == "rule" else first.target)
        if counted in kinds and counted in graph.entities and reaches_all(graph.entities[counted]):
            return graph.entities[counted]

    named = sorted((t for t in terms if t.kind == "entity" and t.target in graph.entities),
                   key=lambda t: (t.target in kinds, -(t.end - t.start), t.start))
    for t in named:
        if reaches_all(graph.entities[t.target]):
            return graph.entities[t.target]
    for kind in kinds:
        entity = graph.entities.get(kind)
        if entity is not None and reaches_all(entity):
            return entity
    return graph.entities.get(kinds[0])


def _said_which(graph: OntologyGraph, frame: Frame, terms: list[FrameTerm],
                spans: dict[tuple[int, int], list[tuple[str, str]]]) -> set[tuple[str, str]]:
    """The properties the question names. A word that fits several is narrowed only where the question says which: to the
    property a rule in the frame is defined on ("EU markets … the country" is the ship country), else to the ones on a
    type the question names ("the customers' state"); a bare word keeps every property it fits."""
    anchored = {(r.entity, p) for r in frame.rules if r.usable and r.id in (graph.rules or {})
                for p in _rule_properties(graph.rules[r.id])}
    said: set[tuple[str, str]] = set()
    for (start, end), group in spans.items():
        # a type named by OTHER words: "country" is also the Country type's name, which says nothing about which country
        # property the word means
        named_types = {t.target for t in terms if t.kind == "entity" and (t.end <= start or end <= t.start)}
        said.update([c for c in group if c in anchored] or [c for c in group if c[0] in named_types] or group)
    return said


def _frame_rules(graph: OntologyGraph, frame: Frame, terms: list[FrameTerm], start: Optional[OntologyEntity],
                 paths: list) -> None:
    for t in terms:
        rule = (graph.rules or {}).get(t.target) if t.kind == "rule" else None
        if rule is None or any(r.id == rule.id for r in frame.rules):
            continue
        row = FrameRule(id=rule.id, label=rule.display_name or rule.id, entity=rule.entity, words=_rule_words(rule),
                        owner=rule.owner, matched=t.text, measured=rule.note, usable=rule.verified is True)
        if rule.verified is not True:
            row.why_not = "it has not been measured, or it admits no object"
        elif start is not None:
            chain = _path_to(paths, rule.entity)
            if chain is None:
                row.usable = False
                row.why_not = (f"{rule.entity} is not reachable from {start.id} by measured to-one links within "
                               f"{frame.hops} hops, so the rule cannot filter {start.id} objects")
            else:
                row.via = ".".join(h.name for h in chain)
                row.filters = _prefixed(rule_filters(rule), row.via)
        else:
            row.filters = list(rule_filters(rule))
        frame.rules.append(row)


def _frame_moments(graph: OntologyGraph, frame: Frame, terms: list[FrameTerm]) -> None:
    about = {(o.process, o.stage) for o in frame.outcomes}
    for t in terms:
        if t.kind not in ("stage", "promise"):
            continue
        process, index = _stage_at(graph, t.target)
        if process is None or index < 0:
            continue
        stage = process.stages[index]
        if not stage.timestamp or stage.verified is not True or (process.id, stage.name) in about:
            continue
        if any(m.process == process.id and m.stage == stage.name for m in frame.moments):
            continue
        frame.moments.append(FrameMoment(text=t.text, process=process.id, process_label=_process_label(process),
                                         stage=stage.name, entity=process.entity, timestamp=stage.timestamp))


def _table_of(entity: OntologyEntity, name: str) -> str:
    """The table ``name`` is read from on ``entity``: its backing's when the backing carries it, else the binding's."""
    if name in (entity.properties or {}):
        b = entity.backing
        return (b.table if b is not None and b.kind == "table" else "") or (entity.source_tables or [""])[0]
    return next((b.table or "" for b in entity.bindings or [] if name in b.properties), "")


def _frame_drivers(frame: Frame, named_props: set, start: Optional[OntologyEntity], paths: list) -> None:
    from aughor.semantic.object_query import is_temporal
    if start is None:
        return
    rows: list[tuple[tuple, FrameDriver]] = []
    reached: set[tuple[str, str]] = set()
    for entity, chain in paths:
        for name, p in _readable_properties(entity).items():
            named = (entity.id, name) in named_props
            if (entity.id, name) in reached or (not named and ((p.semantic_type or "") != "dimension" or is_temporal(p))):
                continue
            reached.add((entity.id, name))
            links = [h.name for h in chain]
            driver = FrameDriver(path=".".join([*links, name]), label=name.replace("_", " "), entity=entity.id,
                                 object_type=entity.api_name, property=name, table=_table_of(entity, name),
                                 links=links, named=named)
            rows.append(((len(chain), entity.entity_type != "reference_data", name), driver))
    rows.sort(key=lambda r: r[0])
    named_rows = [d for _k, d in rows if d.named]
    frame.drivers = named_rows + [d for _k, d in rows if not d.named][:max(0, _MAX_DRIVERS - len(named_rows))]
    reached_names = {name for _eid, name in reached if (_eid, name) in named_props}
    for eid, name in sorted(named_props):
        if (eid, name) not in reached and name not in reached_names:
            frame.notes.append(f"{name.replace('_', ' ')} is on {eid}, which {start.id} does not reach by measured "
                               f"to-one links within {frame.hops} hops — a breakdown by it would repeat {start.id} "
                               "objects")


def _qualified(graph: OntologyGraph) -> OntologyGraph:
    """A copy whose tables carry the graph's schema, so the compiled SQL names `ecommerce.orders` the way the schema a
    reader is shown does — the served graph keeps bare names and the door runs them on a connection scoped to the schema."""
    schema = (graph.schema_name or "").strip()
    bare = [e for e in graph.entities.values()
            if any("." not in t for t in e.source_tables) or (e.backing is not None and e.backing.table and "." not in e.backing.table)
            or any(b.table and "." not in b.table for b in e.bindings or [])]
    if not schema or schema in ("main", "default") or not bare:
        return graph
    work = graph.model_copy(deep=True)

    def q(table: Optional[str]) -> Optional[str]:
        return f"{schema}.{table}" if table and "." not in table else table

    for e in work.entities.values():
        e.source_tables = [q(t) or t for t in e.source_tables]
        if e.backing is not None and e.backing.kind == "table":
            e.backing.table = q(e.backing.table)
        for b in e.bindings or []:
            b.table = q(b.table)
    return work


def _compile_candidate(graph: OntologyGraph, query: dict, dialect: str) -> dict:
    """`_compile` for a candidate breakdown: any failure is a recorded refusal, never an exception."""
    try:
        return _compile(graph, query, dialect)
    except Exception as exc:  # noqa: BLE001 — a candidate the compiler cannot take is said, not raised
        return {"query": query, "refused": f"could not compile: {type(exc).__name__}: {exc}"}


def _compile(graph: OntologyGraph, query: dict, dialect: str) -> dict:
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
    try:
        compiled = compile_object_query(query, graph, dialect=dialect, fiscal_start_month=1)
    except ObjectQueryRefused as exc:
        return {"query": query, "refused": exc.reason}
    return {"query": query, "sql": compiled.sql, "plan": list(compiled.plan), "caveats": list(compiled.caveats)}


def _definition_queries(o: FrameOutcome, filters: list[dict]) -> dict[str, dict]:
    if o.kind == "promise":
        return {o.segment: {"object_type": o.object_type, "segment": o.segment, "filters": filters,
                            "measures": [{"name": o.segment, "agg": "count"}]},
                o.metric: {"object_type": o.object_type, "filters": filters,
                           "measures": [{"name": o.metric, "metric": o.metric}]}}
    if o.kind == "lag":
        return {o.lag: {"object_type": o.object_type, "filters": filters,
                        "measures": [{"name": f"avg_{o.lag}", "agg": "avg", "path": o.lag}]}}
    return {o.segment: {"object_type": o.object_type, "segment": o.segment,
                        "measures": [{"name": o.segment, "agg": "count"}]}}


def _frame_compiled(graph: OntologyGraph, frame: Frame, dialect: str) -> None:
    graph = _qualified(graph)
    chosen = frame.outcome
    filters = [f for r in frame.rules if r.usable for f in r.filters] if chosen is not None else []
    for o in frame.candidates():
        mine = filters if o is chosen and o.kind != "rule" else []
        for key, query in _definition_queries(o, mine).items():
            frame.compiled[key] = _compile(graph, query, dialect)
    if chosen is not None and chosen.kind in ("promise", "lag"):
        measure = ({"name": chosen.metric, "metric": chosen.metric} if chosen.kind == "promise"
                   else {"name": f"avg_{chosen.lag}", "agg": "avg", "path": chosen.lag})
        named = [d for d in frame.drivers if d.named][:_MAX_COMPILED_BY]
        candidates = [d for d in frame.drivers if not d.named][:_MAX_COMPILED_CANDIDATES]
        for d in named + candidates:
            query = {"object_type": chosen.object_type, "filters": filters, "by": [d.path], "measures": [measure]}
            # A NAMED driver compiles the way it always did — the question asked for it, so a failure is
            # loud. A CANDIDATE is the frame's own suggestion: one that cannot compile (a binding shape the
            # compiler refuses, a field a walk mutated) is recorded with its reason and the frame stands.
            frame.compiled[f"by {d.path}"] = (_compile(graph, query, dialect) if d.named
                                              else _compile_candidate(graph, query, dialect))
    if not frame.outcomes:
        for r in frame.rules:
            if r.usable and r.id not in frame.compiled:
                frame.compiled[r.id] = _compile(graph, {"object_type": _api(graph, r.entity), "segment": r.id,
                                                        "measures": [{"name": r.id, "agg": "count"}]}, dialect)


# ── reading it ──────────────────────────────────────────────────────────────────────────────


def _said(texts: Iterable[str]) -> str:
    return " … ".join(dict.fromkeys(t for t in texts if t))


def frame_reading(frame: Frame) -> str:
    """The frame in a few sentences, for the person who asked — what each word was read as, where the reading starts
    and what it will test. "" when the frame defines nothing."""
    if not frame.defines:
        return ""
    parts: list[str] = []
    o = frame.outcome
    if o is not None:
        parts.append(f'Read "{_said(o.matched)}" as {o.label}: {o.definition}'
                     + (f" ({o.measured})." if o.measured else "."))
    elif frame.ambiguous:
        cands = frame.candidates()
        parts.append(f'"{_said(t for c in cands for t in c.matched)}" fits {len(cands)} declared definitions: '
                     + "; ".join(c.label for c in cands) + ".")
    for r in frame.rules:
        if r.usable and not (o is not None and o.kind == "rule" and o.name == r.id):
            parts.append(f'"{r.matched}" is rule {r.id}' + (f" (owned by {r.owner})" if r.owner else "")
                         + f": {r.words}" + (f", reached through {r.via}" if r.via else "") + ".")
    for m in frame.moments:
        parts.append(f'"{m.text}" is stage {m.stage} of {m.process_label}: the moment {m.timestamp}.')
    if frame.start is not None and not frame.ambiguous:
        tested = ", ".join(d.label for d in frame.drivers[:3])
        parts.append(f"Starting from {frame.start['name']}"
                     + (f" ({frame.start['table']})" if frame.start.get("table") else "")
                     + (f"; testing {tested}." if tested else "."))
    return " ".join(parts)


def render_frame_block(frame: Frame) -> str:
    """The frame as a prompt section: every declared definition the question reached, with the SQL the object door
    compiles for it, where to start and the candidate drivers. "" when the frame defines nothing, so a question on a
    connection with nothing declared leaves the prompt byte-identical."""
    if not frame.defines:
        return ""
    lines = ["QUESTION FRAME (the question's business terms, resolved against the DECLARED ontology before any SQL is "
             "written. Each definition below is the business's own and was measured against this data — read the "
             "question through it and follow its compiled SQL; never re-derive the definition from column names):"]
    chosen = frame.outcome
    cands = frame.candidates()
    if chosen is not None:
        lines.append(f'- "{_said(chosen.matched)}" → {chosen.label}: {chosen.definition}')
        if chosen.measured:
            lines.append(f"  measured: {chosen.measured}")
        lines.extend(_compiled_lines(frame, chosen))
    elif len(cands) > 1:
        lines.append(f"- The question's words fit {len(cands)} declared definitions. Use the ONE the question means:")
        for i, c in enumerate(cands, 1):
            lines.append(f"  ({i}) {c.label}: {c.definition} — kept per {c.entity}")
            lines.extend(_compiled_lines(frame, c))
    for r in frame.rules:
        if r.usable:
            lines.append(f'- "{r.matched}" → rule {r.id}' + (f" (owned by {r.owner})" if r.owner else "")
                         + f": {r.words}" + (f" — applied through {r.via}" if r.via else "")
                         + (f"; {r.measured}" if r.measured else ""))
            if r.filters:
                lines.append(f"  as filters from the start: {_filters_text(r.filters)}")
        elif r.why_not:
            lines.append(f'- "{r.matched}" → rule {r.id}, which this frame cannot apply: {r.why_not}')
    for m in frame.moments:
        lines.append(f'- "{m.text}" → stage {m.stage} of {m.process_label}: {_a(m.entity)} reaches it at {m.timestamp}')
    if frame.start is not None and not frame.ambiguous:
        s = frame.start
        key = ""
        if s.get("key"):
            key = f"; key {s['key']}" + ("" if s.get("key_unique") else ", NOT unique per row — count rows, not keys")
        lines.append(f"- Start from {s['name']} ({s.get('table') or 'its backing'}{key}).")
    if frame.drivers:
        lines.append("- Candidate drivers, reachable from the start by measured to-one links: "
                     + "; ".join(f"{d.path}{' (named in the question)' if d.named else ''}" for d in frame.drivers))
    for note in frame.notes:
        lines.append(f"- Note: {note}")
    return "\n".join(lines)


def _filters_text(filters: list[dict]) -> str:
    out = []
    for f in filters:
        rhs = f.get("value_path") or f.get("values") or f.get("value")
        out.append(f"{f.get('path')} {f.get('op')}" + ("" if rhs in (None, "", []) else f" {rhs}"))
    return "; ".join(out)


def _compiled_lines(frame: Frame, o: FrameOutcome) -> list[str]:
    keys = [k for k in frame.compiled
            if k in {o.segment, o.metric, o.lag} - {""} or (o is frame.outcome and k.startswith("by "))]
    lines = []
    for key in keys:
        entry = frame.compiled[key]
        if entry.get("sql"):
            sql = "\n".join(f"    {line}" for line in entry["sql"].strip().splitlines())
            lines.append(f"  {key}, compiled by the object door:\n{sql}")
        elif entry.get("refused"):
            lines.append(f"  {key}: the object door refused it — {entry['refused']}")
    # A promise's rate compiles to a FRACTION while its measured note reads a percentage: the model once rounded 0.1109
    # to 0.11 where the question asked for 11.09%. Said once, beside the SQL that returns it.
    if o.kind == "promise" and any(frame.compiled[k].get("sql") for k in keys if k == o.metric or k.startswith("by ")):
        example = (f"the measured {o.rate:.4f} is {o.rate * 100:.2f}%" if o.rate is not None else "0.0935 is 9.35%")
        lines.append(f"  unit: {o.metric} is a FRACTION of 1 ({example}) — multiply by 100 when the question asks "
                     "for a percentage")
    return lines


__all__ = ["DEFAULT_HOPS", "Frame", "FrameDriver", "FrameMoment", "FrameOutcome", "FrameRule", "FrameTerm",
           "frame_question", "frame_reading", "render_frame_block", "stem", "words_of"]
