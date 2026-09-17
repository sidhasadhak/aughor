"""ON-7b — the explorer maps the business first (ROADMAP §3.15, the second movement).

The builder mints one object type per profiled table, so the map of a warehouse reads like its schema. ON-7 gave a
person the doors to say what the business is instead — a declared entity, a part read through a binding, a declared
link. This module is the model's half of the same work, made safe the way the Ontology-Playground study said a
generator has to be. An explorer reads the SOURCE CATALOGUE — every table as profiled, the joins the builder found with
their measured cardinality, the bindings the data already proposes, what is already declared, the glossary and the
bound pack's claims — and PROPOSES the business ontology in one model call. Nothing it says is believed:

* every proposal is MEASURED before it lands. A part's key is counted against its entity's objects, and the data — not
  the model — decides whether it is one row per object (static), many (detail) or many over a clock (timeseries); a
  link's two sides are counted, and a link whose keys never meet is refused; a declared entity's key must name one
  object per row;
* what survives is written THROUGH ON-7's doors (the router hands them in as `DraftWriters`) with `origin: model` and
  `model:<id>@<version>` provenance (J4), so the platform and its agents read it at once — tiered PROPOSED until a person
  confirms it, which makes `origin` human and keeps the provenance;
* every proposal is keyed by its SUBSTANCE — which table under which entity, which two columns, which rows — so a second
  run over the same catalogue writes nothing twice, and a proposal a person withdrew is never proposed again.

`business_grouping` and `compare_groupings` are this wave's falsifier: a draft's grouping of tables into business
entities, set against a reference (ON-7's hand-declared LuxExperience). A draft that FUSES what the reference keeps
apart does not ship default-on.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, get_args

from pydantic import BaseModel, Field, field_validator

from aughor.ontology.bindings import bare, describe_with, measure_binding, primary_name, taken_names
from aughor.ontology.declared import (
    backs_existing_type,
    entity_fields,
    entity_spec_problem,
    link_fields,
    link_id,
    link_problem_on_graph,
    link_spec_problem,
    measure_declared_backing,
    measure_declared_link,
)
from aughor.ontology.display import display_of, key_of
from aughor.ontology.drafts import MAX_RUNS, DraftProposal, DraftRun, OntologyDraft
from aughor.ontology.models import Binding, OntologyEntity, OntologyGraph, Rollup, snake_name
from aughor.ontology.parts import backing_table, part_of, parts_of

logger = logging.getLogger(__name__)

#: Bump when the prompt or the output schema changes meaningfully — it is the `@<version>` of every proposal's
#: provenance, so a draft says which explorer said it.
EXPLORER_VERSION = 2
#: Columns one entity shows, sample values one column shows, and the catalogue's length — a wide warehouse is cut, and
#: the cut is said.
_MAX_COLUMNS = 48
_MAX_SAMPLES = 4
MAX_CATALOGUE_CHARS = 48_000
#: Proposals of one kind a single draft may write — a runaway answer must not become a hundred writes.
MAX_PER_KIND = 40
#: What a proposed rollup may reduce rows by — the model's own vocabulary, read off `Rollup`.
_AGGS = get_args(Rollup.model_fields["agg"].annotation)
#: Where a proposal can stand, read from the served graph (see `proposal_tier`).
TIERS = ("proposed", "confirmed", "released", "withdrawn", "refused")


# ── the source catalogue ────────────────────────────────────────────────────────────────────


def _count(n: Optional[int]) -> str:
    return "unmeasured" if n is None else f"{n:,}"


def _column_line(name: str, prop: Any) -> str:
    bits = [name, prop.data_type or "?"]
    if prop.semantic_type:
        bits.append(prop.semantic_type)
    if prop.is_primary_key:
        bits.append("key")
    samples = [str(s)[:40] for s in (prop.sample_values or [])[:_MAX_SAMPLES] if str(s).strip()]
    return " ".join(bits) + (f" = {' | '.join(samples)}" if samples else "")


def _who(origin: str) -> str:
    return {"human": "declared by a person", "model": "proposed by a model, not yet confirmed"}.get(origin, "")


def _glossary_lines(glossary: Optional[dict], tables: set[str]) -> list[str]:
    """The glossary's words for THIS scope's tables — a merged glossary also speaks of other connections' tables."""
    out: list[str] = []
    for name, info in ((glossary or {}).get("tables") or {}).items():
        if bare(str(name)).lower() not in tables:
            continue
        text = str(info.get("description") or "") if isinstance(info, dict) else str(info or "")
        if text.strip():
            out.append(f"- {bare(str(name))}: {text.strip()[:200]}")
    return out[:40]


def source_catalogue(graph: OntologyGraph, *, glossary: Optional[dict] = None,
                     deployed_packs: Optional[Iterable[str]] = None) -> str:
    """The SOURCE CATALOGUE an explorer reads — what the platform has measured or been told about this scope, as text:
    each entity with its table, its key's verdict, its rows and its columns (sample values where the profile kept
    them); the joins the builder found, with their measured cardinality and overlap; the bindings the data proposes;
    what a person or an earlier draft already declared; the glossary; and what an industry map expected that THIS
    data confirmed.

    `deployed_packs` are the packs deployed on this connection (active and bound — `bound_pack_ids`). Only their
    claims may be rendered, and only where the data measured them TRUE: an expectation the data cannot speak to, a
    claim a person settled and a claim the data contradicts are shown in the panel and reach no prompt (§3.15 ON-0a,
    "nothing from the map reaches a prompt block except through the same verified tier"). Passing none — the default
    — renders no claim at all.

    Pure and deterministic: the same graph and the same deployed packs render the same catalogue."""
    out: list[str] = [f"SOURCE CATALOGUE — connection {graph.connection_id}, schema {graph.schema_name or 'default'}",
                      "", "ENTITIES — id · its table · key (one row per object? measured) · rows · role · domain"]
    for e in sorted(graph.entities.values(), key=lambda x: x.id):
        b = e.backing
        verdict = {True: "unique", False: "NOT unique", None: "unmeasured"}[b.verified if b is not None else None]
        head = (f"- {e.id} · table {backing_table(e) or 'a keyed SELECT'} · key {key_of(e)} ({verdict}) · rows "
                f"{_count(b.rows if b is not None else None)} · {e.entity_type}" + (f" · {e.domain}" if e.domain else ""))
        holder = part_of(graph, e)
        if holder is not None:
            head += f" · already a part of {holder.id}"
        if e.origin != "table":
            head += f" · {_who(e.origin)}"
        out.append(head)
        if e.display_name and e.display_name != e.id:
            out.append(f"  called: {e.display_name}")
        if e.description:
            out.append(f"  about: {e.description[:240]}")
        props = list((e.properties or {}).items())
        more = f"; … {len(props) - _MAX_COLUMNS} more" if len(props) > _MAX_COLUMNS else ""
        out.append("  columns: " + "; ".join(_column_line(n, p) for n, p in props[:_MAX_COLUMNS]) + more)
        if e.has_lifecycle and e.lifecycle_column:
            out.append(f"  lifecycle: {e.lifecycle_column} in {', '.join(e.lifecycle_states[:8])}")

    found = sorted((r for r in graph.relationships.values() if r.origin == "join_map"), key=lambda x: x.id)
    out += ["", "JOINS the builder found — from table.column → to table.column · measured cardinality · keys that meet"]
    for r in found:
        label = r.measured_cardinality or f"{r.cardinality} (not measured)"
        overlap = "" if r.value_overlap is None else f" · {r.value_overlap:.0%} meet"
        out.append(f"- {bare(r.from_table)}.{r.from_col} → {bare(r.to_table)}.{r.to_col} · {label}{overlap} "
                   f"({r.from_entity} → {r.to_entity})")
    if not found:
        out.append("- none")

    proposed = [(e, p) for e in sorted(graph.entities.values(), key=lambda x: x.id) for p in e.proposed_bindings or []]
    out += ["", "MEASURED BY THE DATA — another table carries an entity's key"]
    for e, p in proposed:
        many = "many rows per object" if p.kind == "detail" else "one row per object"
        out.append(f"- {bare(p.table)}.{p.key} carries {e.id}'s key {key_of(e)}: {many}; covers {_count(p.covered)} of "
                   f"{_count(p.objects)} {e.id} objects")
    if not proposed:
        out.append("- none")

    declared: list[str] = []
    for e in sorted(graph.entities.values(), key=lambda x: x.id):
        if e.origin != "table":
            declared.append(f"- entity {e.id} over {backing_table(e) or 'a keyed SELECT'} ({_who(e.origin)})")
        for bound in e.bindings or []:
            by = "proposed by a model" if bound.source == "model" else "bound by a person"
            declared.append(f"- {e.id} reads {bare(bound.table) or 'a keyed SELECT'} as {bound.name} "
                            f"({bound.kind} binding, {by})")
        holder = part_of(graph, e)
        if holder is not None:
            declared.append(f"- {e.id} is a part of {holder.id}")
    for r in sorted(graph.relationships.values(), key=lambda x: x.id):
        if r.origin != "join_map":
            declared.append(f"- link {r.from_entity} {r.name or snake_name(r.verb)} {r.to_entity} on "
                            f"{r.from_col} = {r.to_col} ({_who(r.origin)})")
    for proc in sorted((graph.processes or {}).values(), key=lambda x: x.id):
        declared.append(f"- process {proc.id} on {proc.entity}: " + " → ".join(s.name for s in proc.stages)
                        + (f" ({_who(proc.origin)})" if _who(proc.origin) else ""))
    for rule in sorted((graph.rules or {}).values(), key=lambda x: x.id):
        declared.append(f"- rule {rule.id} on {rule.entity} ({rule.kind}" + (f", {_who(rule.origin)})" if _who(rule.origin)
                                                                              else ")"))
    out += ["", "ALREADY DECLARED — do not propose these again", *(declared or ["- nothing yet"])]

    tables = {backing_table(e).lower() for e in graph.entities.values() if backing_table(e)}
    words = _glossary_lines(glossary, tables)
    if words:
        out += ["", "GLOSSARY — the business's own words for these tables", *words]
    provenances = {f"pack:{pid}" for pid in (deployed_packs or ())}
    confirmed = [c for c in graph.core_claims
                 if c.tier == "measured-true" and c.provenance in provenances]
    if confirmed:
        out += ["", "PACK CLAIMS — what an industry map expected and this data confirmed"]
        for c in confirmed[:40]:
            out.append(f"- {c.kind} {c.subject}: expected {c.expected}"
                       + (f", measured {c.measured}" if c.measured else ""))
    text = "\n".join(out)
    if len(text) > MAX_CATALOGUE_CHARS:
        text = text[:MAX_CATALOGUE_CHARS] + f"\n… the catalogue was cut at {MAX_CATALOGUE_CHARS:,} characters"
    return text


# ── what the model is asked for ─────────────────────────────────────────────────────────────


def _coerce_json(v: Any) -> Any:
    """A local model intermittently sends a nested list as a JSON-encoded STRING (the enricher's lesson, M24c); read
    it back rather than lose the whole draft to one stringified field."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


class ProposedRollup(BaseModel):
    property: str
    column: str
    #: Validated after the call, not by the schema: a model that writes "SUM" must not lose the whole draft.
    agg: str = "sum"


class ProposedPart(BaseModel):
    entity: str
    table: str
    key: str
    name: str = ""
    time_column: str = ""
    rollups: list[ProposedRollup] = Field(default_factory=list)
    reason: str = ""

    @field_validator("rollups", mode="before")
    @classmethod
    def _rollups(cls, v: Any) -> Any:
        v = _coerce_json(v)
        return v if v is not None else []


class ProposedLink(BaseModel):
    from_entity: str
    to_entity: str
    verb: str
    from_column: str
    to_column: str
    reason: str = ""


class ProposedEntity(BaseModel):
    id: str
    display_name: str = ""
    description: str = ""
    domain: str = ""
    sql: str = ""
    table: str = ""
    key: str
    reason: str = ""


class ProposedStage(BaseModel):
    name: str
    timestamp: str = ""
    state: list[str] = Field(default_factory=list)
    property: str = ""

    @field_validator("state", mode="before")
    @classmethod
    def _states(cls, v: Any) -> Any:
        v = _coerce_json(v)
        return [str(s) for s in v] if isinstance(v, list) else ([] if v is None else v)


class ProposedProcess(BaseModel):
    """ON-9 — the stages one entity's objects move through. No promise: how fast the business promises to move is the
    business's to say."""
    id: str
    entity: str
    display_name: str = ""
    stages: list[ProposedStage] = Field(default_factory=list)
    reason: str = ""

    @field_validator("stages", mode="before")
    @classmethod
    def _stages(cls, v: Any) -> Any:
        v = _coerce_json(v)
        return v if v is not None else []


class ProposedRule(BaseModel):
    """ON-9 — a set of objects the business names: a value set or a condition. Never a metric's scope."""
    id: str
    entity: str
    kind: str = "condition"
    property: str = ""
    values: list[str] = Field(default_factory=list)
    conditions: list[dict] = Field(default_factory=list)
    reason: str = ""

    @field_validator("values", mode="before")
    @classmethod
    def _values(cls, v: Any) -> Any:
        v = _coerce_json(v)
        return [str(x) for x in v] if isinstance(v, list) else ([] if v is None else v)

    @field_validator("conditions", mode="before")
    @classmethod
    def _conditions(cls, v: Any) -> Any:
        v = _coerce_json(v)
        return v if v is not None else []


class BusinessDraft(BaseModel):
    """The explorer's answer: five FLAT lists (a flat list of flat objects is what local models emit reliably)."""
    entities: list[ProposedEntity] = Field(default_factory=list)
    parts: list[ProposedPart] = Field(default_factory=list)
    links: list[ProposedLink] = Field(default_factory=list)
    processes: list[ProposedProcess] = Field(default_factory=list)
    rules: list[ProposedRule] = Field(default_factory=list)

    @field_validator("entities", "parts", "links", "processes", "rules", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> Any:
        v = _coerce_json(v)
        return v if v is not None else []


@dataclass(frozen=True)
class Answerer:
    """The binding that ANSWERED the explorer's call — not merely the one that was asked, since a fallback link may
    stand in for it."""
    backend: str
    model: str
    fallback: bool = False

    @property
    def provenance(self) -> str:
        return f"model:{self.model or 'unknown'}@{EXPLORER_VERSION}"


_SYSTEM = ("You map the business behind a data warehouse. You propose; the platform measures every claim against the "
           "data and refuses what it does not hold.")


def draft_business(graph: OntologyGraph, llm: Any, *, glossary: Optional[dict] = None,
                   answered: Optional[Callable[[], Any]] = None,
                   deployed_packs: Optional[Iterable[str]] = None) -> tuple[BusinessDraft, Answerer, str]:
    """ONE model call: the catalogue in, the proposals out. Returns the proposals, the binding that answered, and the
    catalogue as sent. Raises what the provider raises — a draft that could not be asked for writes nothing.

    ``answered`` reads ``(backend, model, fallback)`` of the structured call that last succeeded — the router hands in
    `aughor.llm.provider.answered_by`, because this package is a store plane and never imports the inference plane
    (`test_ontology_llm_boundary`). Without it a draft is still made, and its provenance names no model."""
    from aughor.agent.prompts_ontology import EXPLORE_BUSINESS_PROMPT
    catalogue = source_catalogue(graph, glossary=glossary, deployed_packs=deployed_packs)
    before = answered() if answered is not None else None
    said = llm.complete(system=_SYSTEM, user=EXPLORE_BUSINESS_PROMPT.format(catalogue=catalogue),
                        response_model=BusinessDraft, temperature=0.0)
    after = answered() if answered is not None else None
    if after is not None and after is not before:
        backend, model, fallback = after
    else:                                   # not answered through the provider's chokepoint — name what we can
        backend, model, fallback = str(getattr(llm, "backend", "") or ""), "", False
    return said, Answerer(backend=backend, model=model, fallback=fallback), catalogue


# ── measuring and writing what was said ────────────────────────────────────────────────────


class ExplorerRefused(Exception):
    """A door refused a write; the message is the door's own sentence."""


@dataclass
class DraftWriters:
    """ON-7's doors, as the router hands them in. Each write raises `ExplorerRefused` with the door's reason."""
    declare_entity: Callable[[dict], Any]
    #: (entity id, binding name, spec, absorb the table's own type as a part) → the bind door's response.
    bind: Callable[[str, str, dict, bool], Any]
    declare_link: Callable[[dict], Any]
    #: The served graph, re-read — so each proposal is judged against what the previous writes made true.
    served: Callable[[], Optional[OntologyGraph]]
    #: ON-9's doors; an explorer handed none writes no processes or rules and says so.
    declare_process: Optional[Callable[[dict], Any]] = None
    declare_rule: Optional[Callable[[dict], Any]] = None


@dataclass
class Outcome:
    """What became of one proposal on one run."""
    key: str
    kind: str                     # entity · part · link · process · rule
    outcome: str                  # written · refused · already · withdrawn
    sentence: str
    note: str = ""
    target: dict = field(default_factory=dict)
    spec: dict = field(default_factory=dict)
    said: dict = field(default_factory=dict)
    measured: dict = field(default_factory=dict)

    def row(self) -> dict:
        return {"key": self.key, "kind": self.kind, "outcome": self.outcome, "sentence": self.sentence,
                "note": self.note, "target": dict(self.target)}


def part_key(entity_id: str, table: str) -> str:
    return f"part:{entity_id}:{bare(table).lower()}"


def link_key(from_entity: str, from_column: str, to_entity: str, to_column: str) -> str:
    """A link's substance: the two columns it joins, whichever way round it was said."""
    a, b = sorted((f"{from_entity}.{from_column.lower()}", f"{to_entity}.{to_column.lower()}"))
    return f"link:{a}={b}"


def entity_key(table: str = "", sql: str = "", primary_key: str = "") -> str:
    """An entity's substance: the rows it reads — its table, or its SELECT (whitespace and case aside) and key."""
    if table:
        return f"entity:table:{bare(table).lower()}"
    normal = " ".join((sql or "").lower().split()).rstrip(";").strip()
    return f"entity:sql:{hashlib.sha1(normal.encode()).hexdigest()[:12]}:{(primary_key or '').lower()}"


def _anchor(stage: dict) -> str:
    if stage.get("timestamp"):
        return str(stage["timestamp"]).strip().lower()
    states = ",".join(sorted(str(s).strip().lower() for s in stage.get("state") or []))
    return f"{str(stage.get('property') or '').strip().lower()}={states}"


def process_key(entity_id: str, stages: list[dict]) -> str:
    """A process by its substance: the type and each stage's moment or states, in order."""
    return f"process:{entity_id}:" + ">".join(_anchor(s) for s in stages)


def rule_key(entity_id: str, kind: str, prop: str = "", values: Optional[list] = None,
             conditions: Optional[list[dict]] = None) -> str:
    """A rule by its substance: a value set's property and values, or a condition's filters — never its name."""
    if kind == "value_set":
        return f"rule:{entity_id}:{str(prop).strip().lower()}=" + ",".join(sorted(str(v).strip().lower() for v in values or []))
    held = sorted(f"{str(c.get('path') or '').strip().lower()} {c.get('op') or '='} "
                  f"{json.dumps(c.get('values') if c.get('values') is not None else c.get('value'), sort_keys=True, default=str)}"
                  for c in conditions or [])
    return f"rule:{entity_id}:" + " and ".join(held)


def _entity_key_of(entity: OntologyEntity) -> str:
    b = entity.backing
    if b is not None and b.kind == "query" and b.sql:
        return entity_key(sql=b.sql, primary_key=b.primary_key)
    return entity_key(table=backing_table(entity))


def _type(graph: OntologyGraph, name: str) -> Optional[OntologyEntity]:
    wanted = (name or "").strip()
    if wanted in graph.entities:
        return graph.entities[wanted]
    low = wanted.lower()
    return next((e for e in sorted(graph.entities.values(), key=lambda x: x.id)
                 if low and low in (e.id.lower(), e.api_name.lower(), (e.display_name or "").lower())), None)


def _named(names: Any, wanted: str) -> Optional[str]:
    low = (wanted or "").strip().lower()
    return next((str(n) for n in names if str(n).lower() == low), None) if low else None


def _name_column(entity: OntologyEntity, column: str) -> Optional[str]:
    """The column ``entity`` is known by — its display property, measured to name one object per row — when it is
    neither ``column`` nor the key: the one other column a link's from-side may hold in place of the key (shipments that
    carry the warehouse's name, not its id)."""
    shown = display_of(entity)
    if shown.get("verified") is not True or shown.get("is_key"):
        return None
    name = _named(entity.properties or {}, str(shown.get("property") or ""))
    return name if name is not None and name.lower() != (column or "").lower() else None


def proposal_tier(graph: Optional[OntologyGraph], proposal: DraftProposal) -> str:
    """Where a recorded proposal stands NOW, read from the served graph rather than remembered: `proposed` (in the
    graph, still the model's), `confirmed` (a person made it theirs), `released` (a part whose binding stays but whose
    part mark a person released), `withdrawn` (a person removed it), or `refused` (the data refuted it when it was
    said)."""
    if proposal.status == "refused":
        return "refused"
    if graph is None:
        return "withdrawn"
    t = proposal.target
    if proposal.kind == "entity":
        entity = graph.entities.get(str(t.get("entity") or ""))
        if entity is None or entity.origin == "table":
            return "withdrawn"
        return "proposed" if entity.origin == "model" else "confirmed"
    if proposal.kind == "link":
        rel = graph.relationships.get(str(t.get("relationship") or ""))
        if rel is None or rel.origin == "join_map":
            return "withdrawn"
        return "proposed" if rel.origin == "model" else "confirmed"
    if proposal.kind in ("process", "rule"):
        declared = (graph.processes if proposal.kind == "process" else graph.rules or {}).get(str(t.get(proposal.kind) or ""))
        if declared is None:
            return "withdrawn"
        return "proposed" if declared.origin == "model" else "confirmed"
    parent = graph.entities.get(str(t.get("entity") or ""))
    bound = next((b for b in (parent.bindings if parent is not None else None) or []
                  if b.name == t.get("binding") and bare(b.table or "").lower() == str(t.get("table") or "").lower()),
                 None)
    if parent is None or bound is None:
        return "withdrawn"
    if t.get("part"):
        part = graph.entities.get(str(t["part"]))
        if part is None or part_of(graph, part) is not parent:
            return "released"
    return "proposed" if bound.source == "model" else "confirmed"


def _withdrawn(earlier: dict[str, str], key: str) -> str:
    tier = earlier.get(key)
    if tier == "withdrawn":
        return "a person withdrew this proposal — it is not proposed again"
    if tier == "released":
        return "a person released this part — it is not made a part again"
    return ""


def apply_draft(said: BusinessDraft, graph: OntologyGraph, db: Any, *, provenance: str, draft: OntologyDraft,
                writers: DraftWriters) -> list[Outcome]:
    """Measure every proposal against ``db`` and write the ones the data holds through ON-7's doors — entities first (a
    part or a link may name one), then parts, then links — re-reading the served graph after each write, so every
    proposal is judged against what the writes before it made true. One outcome per proposal, in the order said."""
    describe = describe_with(db)
    earlier = {key: proposal_tier(graph, p) for key, p in draft.proposals.items()}
    seen: set[str] = set()
    outcomes: list[Outcome] = []
    current = graph

    def settle(o: Outcome) -> None:
        nonlocal current
        if o.key in seen and o.outcome != "written":
            o = Outcome(key=o.key, kind=o.kind, outcome="already", sentence=o.sentence, said=o.said,
                        note="said more than once in this draft", target=o.target)
        seen.add(o.key)
        outcomes.append(o)
        if o.outcome == "written":
            current = writers.served() or current

    for p in said.entities[:MAX_PER_KIND]:
        settle(_entity_outcome(p, current, db, describe, earlier, writers, provenance))
    for p in said.parts[:MAX_PER_KIND]:
        settle(_part_outcome(p, current, db, describe, earlier, writers))
    for p in said.links[:MAX_PER_KIND]:
        settle(_link_outcome(p, current, db, earlier, writers, provenance))
    for p in said.processes[:MAX_PER_KIND]:
        settle(_process_outcome(p, current, db, earlier, writers, provenance))
    for p in said.rules[:MAX_PER_KIND]:
        settle(_rule_outcome(p, current, db, earlier, writers, provenance))
    return outcomes


def _entity_outcome(p: ProposedEntity, graph: OntologyGraph, db: Any, describe: Any, earlier: dict[str, str],
                    writers: DraftWriters, provenance: str) -> Outcome:
    said = p.model_dump()
    sql, table = (p.sql or "").strip(), ("" if (p.sql or "").strip() else bare(p.table).strip())
    backing = {**({"sql": sql} if sql else {"table": table}), "primary_key": (p.key or "").strip()}
    key = entity_key(table=table, sql=sql, primary_key=backing["primary_key"])
    ident = (p.id or "").strip()
    sentence = f"{ident or '?'} — an entity over {table or 'a keyed SELECT'}, one row per {backing['primary_key'] or '?'}"

    def done(outcome: str, note: str = "", **extra: Any) -> Outcome:
        return Outcome(key=key, kind="entity", outcome=outcome, sentence=sentence, note=note, said=said, **extra)

    why = _withdrawn(earlier, key)
    if why:
        return done("withdrawn", why)
    same = next((e for e in graph.entities.values() if _entity_key_of(e) == key), None)
    if same is not None:
        return done("already", f"{same.id} already reads these rows", target={"entity": same.id})
    spec: dict = {"id": ident, "display_name": (p.display_name or ident).strip(), "backing": backing,
                  "origin": "model", "provenance": provenance}
    for f in ("description", "domain"):
        if str(getattr(p, f) or "").strip():
            spec[f] = str(getattr(p, f)).strip()
    problem = entity_spec_problem(spec)
    if problem:
        return done("refused", problem, spec=spec)
    if ident in graph.entities:
        return done("refused", f"an entity '{ident}' already exists over other rows", spec=spec)
    if table:
        other = backs_existing_type(graph, table)
        if other is not None:
            return done("refused", f"{table} already backs {other.id} — a listed table is an entity or a part, never "
                                   "a second entity", spec=spec)
    entry = measure_declared_backing(db, entity_fields(spec), describe)
    measured = {k: entry.get(k) for k in ("bound", "unique", "rows", "unique_note", "note")}
    if not entry.get("bound"):
        return done("refused", str(entry.get("note") or "its rows could not be read"), spec=spec, measured=measured)
    if entry.get("unique") is not True:
        return done("refused", f"its key does not name one object per row — {entry.get('unique_note') or 'not counted'}",
                    spec=spec, measured=measured)
    try:
        writers.declare_entity(spec)
    except ExplorerRefused as exc:
        return done("refused", str(exc), spec=spec, measured=measured)
    return done("written", str(entry.get("unique_note") or ""), spec=spec, measured=measured, target={"entity": ident})


def _binding_name(wanted: str, parent: OntologyEntity, graph: OntologyGraph) -> str:
    """A free snake_case binding name on ``parent``, from how the model named the part."""
    base = snake_name(bare(wanted))[:60]
    if not base[0].isalpha():
        base = f"part_{base}"[:60]
    used = {b.name.lower() for b in parent.bindings or []} | {primary_name(parent).lower()}
    taken = taken_names(graph, parent, list(parent.bindings or []))
    name, n = base, 2
    while name in used or name in taken:
        name, n = f"{base}_{n}", n + 1
    return name


def _rollups(p: ProposedPart, columns: dict, owner: Optional[OntologyEntity], key_column: str, name: str,
             parent: OntologyEntity, graph: OntologyGraph) -> tuple[dict, list[str]]:
    """The rollups a detail part is bound with: the model's, each checked against the source's columns, the aggregates
    a rollup knows and the names free on the entity; and when none survives, the one the data vouches for — how many
    rows each object has."""
    taken = taken_names(graph, parent, list(parent.bindings or []))
    out: dict = {}
    dropped: list[str] = []
    for r in p.rollups[:12]:
        prop = snake_name(r.property)[:60] if (r.property or "").strip() else ""
        column = _named(columns, r.column)
        agg = (r.agg or "sum").strip().lower()
        why = ("it names no property" if not prop else f"{bare(p.table)} has no column {r.column!r}" if column is None
               else f"unknown agg {r.agg!r}" if agg not in _AGGS else taken.get(prop.lower(), "")
               or ("it is declared twice" if prop in out else ""))
        if why:
            dropped.append(f"rollup {prop or repr(r.property)} dropped: {why}")
            continue
        out[prop] = {"column": column, "agg": agg}
    if not out:
        counted = _named(columns, key_of(owner)) if owner is not None else None
        out[f"{name}_count"] = {"column": counted or key_column, "agg": "count"}
    return out, dropped


def _part_outcome(p: ProposedPart, graph: OntologyGraph, db: Any, describe: Any, earlier: dict[str, str],
                  writers: DraftWriters) -> Outcome:
    said = p.model_dump()
    parent = _type(graph, p.entity)
    table = bare(p.table).strip()
    parent_id = parent.id if parent is not None else (p.entity or "?")
    key = part_key(parent_id, table)
    sentence = f"{table or '?'} is a part of {parent_id}"

    def done(outcome: str, note: str = "", **extra: Any) -> Outcome:
        return Outcome(key=key, kind="part", outcome=outcome, sentence=sentence, note=note, said=said, **extra)

    if parent is None:
        return done("refused", f"no entity '{p.entity}' in this ontology")
    if not table:
        return done("refused", "a part names its table")
    why = _withdrawn(earlier, key)
    if why:
        return done("withdrawn", why)
    held = next((b for b in parent.bindings or [] if bare(b.table or "").lower() == table.lower()), None)
    if held is not None:
        by = "an earlier draft" if held.source == "model" else "a person"
        return done("already", f"{parent.id} already reads {table} as {held.name}, bound by {by}",
                    target={"entity": parent.id, "binding": held.name, "table": bare(held.table)})
    above = part_of(graph, parent)
    if above is not None:
        return done("refused", f"{parent.id} is itself a part of {above.id} — a part of a part is not a shape; "
                               f"{table} belongs under {above.id}")
    owner = backs_existing_type(graph, table)
    if owner is not None and owner.id == parent.id:
        return done("refused", f"{table} is {parent.id}'s own table")
    if owner is not None and parts_of(graph, owner):
        return done("refused", f"{owner.id} has parts of its own — making it a part would make a part of a part")
    columns, error = describe(table)
    if error or not columns:
        return done("refused", f"{table} could not be read: {error or 'no columns'}"[:300])
    column = _named(columns, p.key)
    if column is None:
        return done("refused", f"{table} has no column '{p.key}' to hold {parent.id}'s key — its columns: "
                               f"{', '.join(sorted(columns))[:200]}")
    trial = measure_binding(db, parent, Binding(name="explorer_trial", kind="static", table=table, key=column))
    measured = trial.counts()
    if trial.verified is None:
        return done("refused", f"not measurable — {trial.note}", measured=measured)
    if not trial.covered:
        return done("refused", f"{table}.{column} reaches no {parent.id}: the keys never meet ({trial.note})",
                    measured=measured)
    one_each = bool(trial.non_null) and trial.distinct == trial.non_null
    time_column = _named(columns, p.time_column) if (p.time_column or "").strip() else None
    notes: list[str] = []
    # The data decides the kind, never the model: a key that repeats is many rows per object.
    if one_each:
        kind = "static"
        if time_column:
            notes.append(f"one row per {parent.id}, so it is read as it is — not as readings over {time_column}")
    else:
        kind = "timeseries" if time_column else "detail"
    name = _binding_name(p.name or table, parent, graph)
    spec: dict = {"table": table, "key": column, "kind": kind}
    if kind == "timeseries":
        spec["time_column"] = time_column
    if kind == "detail":
        spec["rollups"], dropped = _rollups(p, columns, owner, column, name, parent, graph)
        notes += dropped
    notes.insert(0, f"{'one row' if one_each else 'many rows'} per {parent.id} — {trial.note}")
    sentence = f"{table} is a part of {parent.id}, read as {name} ({kind})"
    try:
        result = writers.bind(parent.id, name, spec, owner is not None)
    except ExplorerRefused as exc:
        return done("refused", str(exc), spec=spec, measured=measured)
    absorbed = str((result or {}).get("absorbed") or "") if isinstance(result, dict) else ""
    if owner is not None and not absorbed:
        warned = "; ".join((result or {}).get("warnings") or []) if isinstance(result, dict) else ""
        notes.append(f"bound, but {owner.id} was not made a part: {warned or 'the mark did not hold'}")
    return done("written", "; ".join(notes), spec=spec, measured=measured,
                target={"entity": parent.id, "binding": name, "table": table, "part": absorbed})


def _link_outcome(p: ProposedLink, graph: OntologyGraph, db: Any, earlier: dict[str, str], writers: DraftWriters,
                  provenance: str) -> Outcome:
    said = p.model_dump()
    a, b = _type(graph, p.from_entity), _type(graph, p.to_entity)
    verb = snake_name(p.verb)[:80] if (p.verb or "").strip() else ""
    a_col = _named((a.properties or {}) if a is not None else {}, p.from_column)
    b_col = _named((b.properties or {}) if b is not None else {}, p.to_column)
    ends = (a.id if a is not None else p.from_entity or "?", b.id if b is not None else p.to_entity or "?")
    key = link_key(ends[0], a_col or p.from_column or "?", ends[1], b_col or p.to_column or "?")
    sentence = f"{ends[0]} {verb or '?'} {ends[1]} on {a_col or p.from_column} = {b_col or p.to_column}"

    def done(outcome: str, note: str = "", **extra: Any) -> Outcome:
        return Outcome(key=key, kind="link", outcome=outcome, sentence=sentence, note=note, said=said, **extra)

    if a is None or b is None:
        return done("refused", f"no entity '{p.from_entity if a is None else p.to_entity}' in this ontology")
    if a_col is None or b_col is None:
        missing, entity = (p.from_column, a) if a_col is None else (p.to_column, b)
        return done("refused", f"{entity.id} has no column '{missing}' of its own to join on")
    why = _withdrawn(earlier, key)
    if why:
        return done("withdrawn", why)
    ours = {(a.id, a_col.lower()), (b.id, b_col.lower())}
    name_col = _name_column(b, b_col)
    by_name = {(a.id, a_col.lower()), (b.id, name_col.lower())} if name_col is not None else None
    same = next((r for r in graph.relationships.values()
                 if {(r.from_entity, r.from_col.lower()), (r.to_entity, r.to_col.lower())} in (ours, by_name)), None)
    if same is not None:
        return done("already", f"{same.id} already joins these columns", target={"relationship": same.id})
    spec = {"from_entity": a.id, "to_entity": b.id, "name": verb, "from_column": a_col, "to_column": b_col,
            "origin": "model", "provenance": provenance}
    problem = link_spec_problem(spec)
    if problem:
        return done("refused", problem, spec=spec)
    fields = link_fields(spec)
    if link_id(fields) in graph.relationships:
        return done("refused", f"{link_id(fields)} already links these types on other columns", spec=spec)
    problem = link_problem_on_graph(graph, fields)
    if problem:
        return done("refused", problem, spec=spec)
    entry = measure_declared_link(db, graph, fields)
    measured = {k: entry.get(k) for k in ("bound", "measured_cardinality", "value_overlap", "note")}
    if not entry.get("bound"):
        return done("refused", str(entry.get("note") or "its sides could not be counted"), spec=spec, measured=measured)
    overlap = entry.get("value_overlap")
    if overlap is None:
        return done("refused", "how many of its keys meet could not be counted", spec=spec, measured=measured)
    if overlap <= 0:
        # A key-for-a-name mistake: the from-side may hold the name the target is known by. Counted again on that one
        # column — measured to name one object per row — and written only when its keys meet; otherwise refused as said.
        if name_col is not None:
            retried = {**spec, "to_column": name_col}
            again = measure_declared_link(db, graph, link_fields(retried))
            if (again.get("bound") and (again.get("value_overlap") or 0) > 0
                    and not link_problem_on_graph(graph, link_fields(retried))):
                counted = {k: again.get(k) for k in ("bound", "measured_cardinality", "value_overlap", "note")}
                note = (f"its keys never met on {b.id}.{b_col}; {a.id}.{a_col} holds the name {b.id} is known by, so "
                        f"the link was counted on {name_col} — {again.get('note')}")
                try:
                    writers.declare_link(retried)
                except ExplorerRefused as exc:
                    return done("refused", str(exc), spec=retried, measured=counted)
                return done("written", note, spec=retried, measured=counted,
                            target={"relationship": link_id(link_fields(retried))})
        return done("refused", f"the keys never meet — {entry.get('note')}", spec=spec, measured=measured)
    try:
        writers.declare_link(spec)
    except ExplorerRefused as exc:
        return done("refused", str(exc), spec=spec, measured=measured)
    return done("written", str(entry.get("note") or ""), spec=spec, measured=measured,
                target={"relationship": link_id(fields)})


def _process_outcome(p: ProposedProcess, graph: OntologyGraph, db: Any, earlier: dict[str, str], writers: DraftWriters,
                     provenance: str) -> Outcome:
    """ON-9 — a process the model proposes: its stages resolved on the type and COUNTED before anything is written, and
    one whose stage no object reaches refused. The model proposes stages alone — how fast the business promises to move
    through them is the business's to say."""
    from aughor.ontology.processes import (
        NotMeasurable, measure_process, process_fields, process_spec_problem, resolve_process,
    )
    said = p.model_dump()
    entity = _type(graph, p.entity)
    stages = [{k: v for k, v in s.model_dump().items() if v not in ("", [], None)} for s in p.stages]
    owner = entity.id if entity is not None else (p.entity or "?")
    key = process_key(owner, stages)
    sentence = f"{owner} goes through " + " → ".join(str(s.get("name") or "?") for s in stages)

    def done(outcome: str, note: str = "", **extra: Any) -> Outcome:
        return Outcome(key=key, kind="process", outcome=outcome, sentence=sentence, note=note, said=said, **extra)

    if entity is None:
        return done("refused", f"no entity '{p.entity}' in this ontology")
    why = _withdrawn(earlier, key)
    if why:
        return done("withdrawn", why)
    same = next((x for x in (graph.processes or {}).values()
                 if x.entity == entity.id and process_key(x.entity, [s.model_dump() for s in x.stages]) == key), None)
    if same is not None:
        return done("already", f"{same.id} already declares these stages", target={"process": same.id, "entity": entity.id})
    process_id = snake_name(p.id)[:64]
    spec: dict = {"id": process_id, "entity": entity.id, "stages": stages, "origin": "model", "provenance": provenance}
    if p.display_name.strip():
        spec["display_name"] = p.display_name.strip()
    problem = process_spec_problem(spec)
    if problem:
        return done("refused", problem, spec=spec)
    if process_id in (graph.processes or {}):
        return done("refused", f"a process '{process_id}' already goes through other stages", spec=spec)
    problem, fields = resolve_process(graph, process_id, process_fields(spec))
    if problem:
        return done("refused", problem, spec=spec)
    try:
        measured = measure_process(db, graph, process_id, fields)
    except NotMeasurable as exc:
        return done("refused", f"it could not be counted: {exc}", spec=spec)
    counts = {"objects": measured.objects, "verified": measured.verified,
              "reached": {s.name: s.reached for s in measured.stages}}
    if measured.verified is not True:
        return done("refused", measured.note or "the data does not hold it", spec=spec, measured=counts)
    if writers.declare_process is None:
        return done("refused", "this explorer writes no processes", spec=spec, measured=counts)
    try:
        writers.declare_process(spec)
    except ExplorerRefused as exc:
        return done("refused", str(exc), spec=spec, measured=counts)
    return done("written", measured.note, spec=spec, measured=counts, target={"process": process_id, "entity": entity.id})


def _rule_outcome(p: ProposedRule, graph: OntologyGraph, db: Any, earlier: dict[str, str], writers: DraftWriters,
                  provenance: str) -> Outcome:
    """ON-9 — a rule the model proposes: counted before anything is written. One that admits no object, a value set that
    spells a value no row holds, or a condition that admits every object — so excludes nothing — is refused. The model
    never scopes a metric with a rule: what a metric means is a person's to change."""
    from aughor.ontology.business_rules import measure_rule, resolve_rule, rule_fields, rule_spec_problem
    from aughor.ontology.processes import NotMeasurable
    said = p.model_dump()
    entity = _type(graph, p.entity)
    owner = entity.id if entity is not None else (p.entity or "?")
    kind = p.kind if p.kind in ("value_set", "condition") else "condition"
    key = rule_key(owner, kind, p.property, p.values, p.conditions)
    rule_id = snake_name(p.id)[:64]
    words = (f"{p.property} in {', '.join(p.values)}" if kind == "value_set" else " and ".join(
        f"{c.get('path')} {c.get('op') or '='} {c.get('values') if c.get('values') is not None else c.get('value')}"
        for c in p.conditions))
    sentence = f"{rule_id or '?'} on {owner}: {words}"

    def done(outcome: str, note: str = "", **extra: Any) -> Outcome:
        return Outcome(key=key, kind="rule", outcome=outcome, sentence=sentence, note=note, said=said, **extra)

    if entity is None:
        return done("refused", f"no entity '{p.entity}' in this ontology")
    why = _withdrawn(earlier, key)
    if why:
        return done("withdrawn", why)
    same = next((r for r in (graph.rules or {}).values() if r.entity == entity.id
                 and rule_key(r.entity, r.kind, r.property, r.values, r.conditions) == key), None)
    if same is not None:
        return done("already", f"{same.id} already names these objects", target={"rule": same.id, "entity": entity.id})
    spec: dict = {"id": rule_id, "entity": entity.id, "kind": kind, "origin": "model", "provenance": provenance}
    if kind == "value_set":
        spec.update({"property": p.property, "values": list(p.values)})
    else:
        spec["conditions"] = [dict(c) for c in p.conditions]
    problem = rule_spec_problem(spec)
    if problem:
        return done("refused", problem, spec=spec)
    if rule_id in (graph.rules or {}):
        return done("refused", f"a rule '{rule_id}' already names other objects", spec=spec)
    problem, fields = resolve_rule(graph, rule_id, rule_fields(spec))
    if problem:
        return done("refused", problem, spec=spec)
    try:
        measured = measure_rule(db, graph, rule_id, fields)
    except NotMeasurable as exc:
        return done("refused", f"it could not be counted: {exc}", spec=spec)
    counts = {"objects": measured.objects, "admitted": measured.admitted, "observed": dict(measured.observed)}
    if not measured.verified:
        return done("refused", measured.note, spec=spec, measured=counts)
    if measured.missing:
        return done("refused", f"never observed: {', '.join(measured.missing)} — no {entity.id} holds "
                               f"{'that value' if len(measured.missing) == 1 else 'those values'} in {p.property}",
                    spec=spec, measured=counts)
    if kind == "condition" and measured.admitted == measured.objects:
        return done("refused", f"admits every one of the {measured.objects:,} {entity.id} objects — it excludes nothing",
                    spec=spec, measured=counts)
    if writers.declare_rule is None:
        return done("refused", "this explorer writes no rules", spec=spec, measured=counts)
    try:
        writers.declare_rule(spec)
    except ExplorerRefused as exc:
        return done("refused", str(exc), spec=spec, measured=counts)
    return done("written", measured.note, spec=spec, measured=counts, target={"rule": rule_id, "entity": entity.id})


# ── the record, and what a person reads ────────────────────────────────────────────────────


def record_run(draft: OntologyDraft, outcomes: list[Outcome], answerer: Answerer, said: BusinessDraft, *,
               catalogue_chars: int = 0, trace_id: str = "") -> DraftRun:
    """Fold one run into the record: a written or refused proposal is recorded under its substance key (a refusal
    never overwrites a proposal an earlier run wrote), the run itself is appended, and the run is returned."""
    tally = Counter(o.outcome for o in outcomes)
    run = DraftRun(id=uuid.uuid4().hex[:12], at=datetime.now(timezone.utc).isoformat(), backend=answerer.backend,
                   model=answerer.model, fallback=answerer.fallback, version=EXPLORER_VERSION,
                   provenance=answerer.provenance, catalogue_chars=catalogue_chars, trace_id=trace_id,
                   said={"entities": len(said.entities), "parts": len(said.parts), "links": len(said.links),
                         "processes": len(said.processes), "rules": len(said.rules)},
                   written=tally["written"], refused=tally["refused"], already=tally["already"],
                   withdrawn=tally["withdrawn"])
    for o in outcomes:
        prior = draft.proposals.get(o.key)
        if o.outcome not in ("written", "refused"):
            if prior is not None:
                prior.last_run = run.id
            continue
        if o.outcome == "refused" and prior is not None and prior.status == "proposed":
            prior.last_run = run.id
            continue
        draft.proposals[o.key] = DraftProposal(
            key=o.key, kind=o.kind, status="proposed" if o.outcome == "written" else "refused", sentence=o.sentence,
            note=o.note, target=o.target, spec=o.spec, said=o.said, measured=o.measured,
            provenance=answerer.provenance, first_run=prior.first_run if prior is not None else run.id, last_run=run.id)
    draft.runs = [*draft.runs, run][-MAX_RUNS:]
    return run


_KIND_ORDER = {"entity": 0, "part": 1, "link": 2, "process": 3, "rule": 4}


def _opens(graph: Optional[OntologyGraph], proposal: DraftProposal) -> str:
    """The object type a person opens to see this proposal where it lives."""
    if graph is None:
        return ""
    t = proposal.target
    ident = str(t.get("entity") or "")
    rel = graph.relationships.get(str(t.get("relationship") or ""))
    if not ident and rel is not None:
        ident = rel.from_entity
    entity = graph.entities.get(ident)
    return entity.api_name if entity is not None else ""


def draft_view(graph: Optional[OntologyGraph], draft: OntologyDraft) -> dict:
    """The draft as a person reads it: every proposal with where it stands NOW, the runs newest first, the counts per
    tier, and how the scope's tables group into business entities."""
    rows = []
    for p in sorted(draft.proposals.values(), key=lambda x: (_KIND_ORDER.get(x.kind, 9), x.sentence)):
        rows.append({"key": p.key, "kind": p.kind, "tier": proposal_tier(graph, p), "sentence": p.sentence,
                     "note": p.note, "reason": str(p.said.get("reason") or ""), "provenance": p.provenance,
                     "target": dict(p.target), "object_type": _opens(graph, p)})
    tiers = Counter(r["tier"] for r in rows)
    return {"connection_id": draft.connection_id, "schema_name": draft.schema_name,
            "runs": [r.model_dump() for r in reversed(draft.runs)], "proposals": rows,
            "counts": {t: tiers.get(t, 0) for t in TIERS},
            "grouping": business_grouping(graph) if graph is not None else {}}


def confirm_targets(graph: Optional[OntologyGraph], draft: OntologyDraft) -> list[dict]:
    """Every declaration of the draft that is still the model's, as the confirm door names it."""
    out: list[dict] = []
    for p in draft.proposals.values():
        if proposal_tier(graph, p) != "proposed":
            continue
        t = p.target
        if p.kind == "entity":
            out.append({"kind": "entity", "entity": t["entity"]})
        elif p.kind == "link":
            out.append({"kind": "link", "relationship": t["relationship"]})
        elif p.kind in ("process", "rule"):
            out.append({"kind": p.kind, p.kind: t[p.kind]})
        else:
            out.append({"kind": "binding", "entity": t["entity"], "binding": t["binding"]})
    return out


# ── the falsifier: how the tables group ────────────────────────────────────────────────────


def business_grouping(graph: OntologyGraph) -> dict[str, list[str]]:
    """``{top-level entity: its tables}`` — the tables each card on the map stands for: its own table, the tables of
    the types that are its parts, and any table it binds that no type of its own reads. A type that is a part is not a
    group; a table bound into an entity whose own type still stands stays with that type."""
    groups: dict[str, list[str]] = {}
    for entity in sorted(graph.entities.values(), key=lambda x: x.id):
        if part_of(graph, entity) is not None:
            continue
        tables = {backing_table(entity).lower()} if backing_table(entity) else set()
        for part, _binding in parts_of(graph, entity):
            if backing_table(part):
                tables.add(backing_table(part).lower())
        for bound in entity.bindings or []:
            table = bare(bound.table or "").lower()
            if table and backs_existing_type(graph, table) is None:
                tables.add(table)
        groups[entity.id] = sorted(tables)
    return groups


def compare_groupings(draft: dict[str, list[str]], reference: dict[str, list[str]]) -> dict:
    """A draft's grouping against a reference's, table by table. A FUSION is a draft group holding tables the reference
    keeps in different groups — two business things made one; a SPLIT is a reference group whose tables the draft left
    in several — a part not yet found. Fusions are what the falsifier refuses: a draft with any does not ship
    default-on. Pair precision and recall count the table pairs each side keeps together."""
    in_draft = {t: g for g, tables in draft.items() for t in tables}
    in_reference = {t: g for g, tables in reference.items() for t in tables}
    shared = set(in_draft) & set(in_reference)
    fusions = [{"draft": g, "tables": sorted(t for t in tables if t in shared),
                "fuses": sorted({in_reference[t] for t in tables if t in shared})}
               for g, tables in sorted(draft.items()) if len({in_reference[t] for t in tables if t in shared}) > 1]
    splits = [{"reference": g, "tables": sorted(t for t in tables if t in shared),
               "into": sorted({in_draft[t] for t in tables if t in shared})}
              for g, tables in sorted(reference.items()) if len({in_draft[t] for t in tables if t in shared}) > 1]
    matched = sorted(g for g, tables in reference.items()
                     if tables and set(tables) <= shared and len({in_draft[t] for t in tables}) == 1
                     and {t for t in draft[in_draft[tables[0]]] if t in shared} == set(tables))

    def together(of: dict[str, str]) -> set[tuple[str, str]]:
        ordered = sorted(shared)
        return {(x, y) for i, x in enumerate(ordered) for y in ordered[i + 1:] if of[x] == of[y]}

    kept_d, kept_r = together(in_draft), together(in_reference)
    both = kept_d & kept_r
    return {"reference_groups": len(reference), "draft_groups": len(draft), "matched": matched,
            "fusions": fusions, "splits": splits,
            "pair_precision": round(len(both) / len(kept_d), 4) if kept_d else None,
            "pair_recall": round(len(both) / len(kept_r), 4) if kept_r else None,
            "only_in_draft": sorted(set(in_draft) - shared), "only_in_reference": sorted(set(in_reference) - shared),
            "ships_default_on": not fusions}
