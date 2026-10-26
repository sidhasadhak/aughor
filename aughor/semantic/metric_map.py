"""Arc MC, MC-1 — the map a connection's metrics cover (ROADMAP §3.62, `docs/METRICS_COVERAGE_STUDY_2026-10-26.md`).

The user, 2026-10-26, on LuxExperience: *"only 12 proposed metrics.. for an e-commerce organisation that is probably not
even 50% of the matrix"*, and then the catch the study turned on: *"I think we already this list of metrics per industry
as knowledge base"*. The knowledge base's metric patterns (`packs/*/kb/*.json`) are the map: each carries its definition,
its template, what inflates and deflates it. They were read only to answer a question, never to propose a metric.

A map is a list of **areas** a business is read by — each with the question it answers — and the patterns and recipes
that read on each:

- an industry package declares its areas in `areas.yaml`, in the order its business reads (retail: its income statement
  first, then the operating areas); the function and base packages declare theirs, and an industry takes one of theirs
  into its own by naming it in `absorbs` (retail reads finance's `refunds` as its Returns). A function area no industry
  takes is read under its own name, after the industry's;
- every metric-shaped pattern names its `area`, its `kind` (volume · value · rate · duration · quality — the generic
  layer, true of any business) and its `direction` (up · down · either is good), on the pattern itself, not beside it;
- **the generic layer** closes the map: the five kinds, and one last area for what the data holds that no area names, so
  a connection no pack fits still has a map. Industry nouns stay in the packs (the industry-noun ratchet); this module
  reads ids and words it is handed.

Pure reads of the packages; no warehouse, no model. A pattern naming an area its package does not declare is a problem
said by `problems`, never a pattern silently dropped (MC-1's falsifier).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

#: The generic layer — what any metric is, whatever the business.
KINDS: tuple[str, ...] = ("volume", "value", "rate", "duration", "quality")
KIND_WORDS: dict[str, str] = {
    "volume": "how many", "value": "how much money", "rate": "a share of a population or a ratio",
    "duration": "how long between two moments", "quality": "a score, or a share of defects",
}
#: A pattern that is a way to read a metric (a volatility, a cohort assignment), not a metric: never proposed.
ANALYSIS = "analysis"
DIRECTIONS: tuple[str, ...] = ("up", "down", "either")
#: The pattern types that are metrics, and an untyped entry with a business definition (the `domain_*` files).
METRIC_SHAPED = frozenset({"metric", "ratio", "funnel", "cohort", "retention"})
#: The generic layer's own area: what the data holds that no area names.
OTHER = "other"
OTHER_NAME = "Everything else the data holds"
OTHER_QUESTION = "What else does this data measure?"


@dataclass(frozen=True)
class Pattern:
    """One metric pattern of the knowledge base, with the area it reads on (resolved for the connection)."""
    id: str
    title: str
    pack_id: str
    area: str
    kind: str
    direction: str
    definition: str = ""
    template: str = ""
    anti_patterns: tuple[str, ...] = ()
    intent_tags: tuple[str, ...] = ()
    #: The area id the pattern names in its pack — `area` is where it reads for THIS connection.
    declared_area: str = ""

    @property
    def proposable(self) -> bool:
        return self.kind != ANALYSIS

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "pack_id": self.pack_id, "area": self.area, "kind": self.kind,
                "direction": self.direction, "definition": self.definition, "proposable": self.proposable}


@dataclass(frozen=True)
class Recipe:
    """One typed recipe (`metrics/*.yaml`): role-bound, with its sane range."""
    name: str
    title: str
    pack_id: str
    area: str
    formula: str
    required_roles: tuple[str, ...] = ()
    sane_range: Optional[dict] = None
    definition: str = ""


@dataclass
class Area:
    id: str
    name: str
    question: str
    pack_id: str
    words: tuple[str, ...] = ()
    absorbs: tuple[str, ...] = ()
    patterns: list[Pattern] = field(default_factory=list)
    recipes: list[Recipe] = field(default_factory=list)
    #: The generic layer's area, said as such.
    generic: bool = False

    @property
    def proposable_patterns(self) -> list[Pattern]:
        return [p for p in self.patterns if p.proposable]

    @property
    def readable(self) -> bool:
        """An area a table can be placed in, or one that has a metric to propose: a methods-only area is neither."""
        return self.generic or bool(self.words) or bool(self.proposable_patterns) or bool(self.recipes)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "question": self.question, "pack_id": self.pack_id,
                "generic": self.generic, "patterns": [p.as_dict() for p in self.proposable_patterns],
                "recipes": [r.name for r in self.recipes]}


@dataclass
class MetricMap:
    areas: list[Area] = field(default_factory=list)
    #: The industry package whose areas lead, or "" when no industry package fits.
    industry_pack: str = ""
    problems: list[str] = field(default_factory=list)

    def area(self, area_id: str) -> Optional[Area]:
        return next((a for a in self.areas if a.id == area_id), None)

    def order(self, area_id: str) -> int:
        """An area's place in the map's reading order; an id the map lacks reads last."""
        return next((i for i, a in enumerate(self.areas) if a.id == area_id), len(self.areas))

    @property
    def readable(self) -> list[Area]:
        return [a for a in self.areas if a.readable]

    def patterns(self) -> list[Pattern]:
        return [p for a in self.areas for p in a.patterns]


# ── words ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _singular(token: str) -> str:
    """A token without a plural ending, so `shipments` meets `shipment` and `sales` meets `sale`."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    """A name or a phrase as its words, singular: `marketing_attribution` → [marketing, attribution]."""
    return [_singular(t) for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t]


def word_hits(text: str, words: Iterable[str]) -> list[str]:
    """The area words found in ``text`` as whole consecutive words, longest first."""
    have = tokens(text)
    hits = []
    for w in words:
        want = tokens(w)
        n = len(want)
        if n and any(have[i:i + n] == want for i in range(len(have) - n + 1)):
            hits.append(w)
    return sorted(hits, key=lambda w: (-len(tokens(w)), -len(w)))


def _strength(word: str) -> tuple[int, int]:
    return (len(tokens(word)), len(word))


def best_areas(text: str, areas: Iterable[Area]) -> list[tuple[Area, str]]:
    """The areas whose words name ``text`` most strongly — the phrase of most words wins, so `customer_service` is
    Service and not Customers — each with the word that placed it. Several when they tie (`return_logistics` serves
    Returns and Fulfilment), the longest word first, so a caller that keeps one keeps the most specific; none when no
    word is found."""
    scored: list[tuple[tuple[int, int], Area, str]] = []
    for a in areas:
        hits = word_hits(text, a.words)
        if hits:
            scored.append((_strength(hits[0]), a, hits[0]))
    if not scored:
        return []
    top = max(s[0] for s, _, _ in scored)
    tied = [(s, a, w) for s, a, w in scored if s[0] == top]
    return [(a, w) for _s, a, w in sorted(tied, key=lambda x: -x[0][1])]


def _norm(text: str) -> str:
    return " ".join(re.split(r"[^a-z0-9]+", str(text or "").lower())).strip()


def _title_names(title: str) -> set[str]:
    """A pattern title's names: whole, without its parenthesis, and the parenthesis — "Gross Merchandise Value (GMV)"
    is all three."""
    names = {_norm(title)}
    m = re.match(r"^(.*?)\(([^)]*)\)(.*)$", title or "")
    if m:
        names.add(_norm(m.group(1) + " " + m.group(3)))
        names.add(_norm(m.group(2)))
    return {n for n in names if n}


def match_pattern(name: str, label: str, patterns: Iterable[Pattern]) -> Optional[Pattern]:
    """The pattern a metric's name or label IS — its title or one of its intent tags, word for word. Never a
    containment: "Clienteling GMV per Interaction" is not the GMV pattern."""
    wanted = {_norm(name), _norm(label)} - {""}
    for p in patterns:
        if not p.proposable:
            continue
        if wanted & (_title_names(p.title) | {_norm(t) for t in p.intent_tags}):
            return p
    return None


# ── reading the packages ───────────────────────────────────────────────────────────────────────────────────────────

def is_metric_pattern(entry: object) -> bool:
    if not isinstance(entry, dict) or not entry.get("id"):
        return False
    kind = entry.get("pattern_type")
    return kind in METRIC_SHAPED or (kind is None and bool(entry.get("business_definition")))


def _packages_for(connection_id: str, schema_name: Optional[str]) -> list:
    from aughor.semantic.metric_catalogue import industry_packages
    return industry_packages(connection_id, schema_name)


def map_for(connection_id: str, schema_name: Optional[str] = None) -> MetricMap:
    """The map this connection's metrics are read against: its industry's areas, then the function and base areas no
    industry takes, then the generic layer's."""
    return map_of(_packages_for(connection_id, schema_name))


def map_of(packages: list) -> MetricMap:
    """The map the given knowledge packages make (`knowledge.Package` rows: an industry one at most leads)."""
    from aughor.packs.knowledge import iter_kb_payloads
    from aughor.packs.loader import load_pack

    out = MetricMap()
    loaded = []
    for pkg in packages:
        try:
            loaded.append((pkg, load_pack(pkg.directory)))
        except Exception as exc:  # noqa: BLE001 — one unreadable package is said, the rest still map
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"package {pkg.pack_id} did not load; its areas are not mapped", counter="metric_map.load")
            out.problems.append(f"package {pkg.pack_id} could not be loaded ({type(exc).__name__}) — its areas are not read")
    industry = [(pkg, pack) for pkg, pack in loaded if pkg.layer == "industry"]
    shared = [(pkg, pack) for pkg, pack in loaded if pkg.layer != "industry"]
    if industry:
        out.industry_pack = industry[0][0].pack_id

    by_id: dict[str, Area] = {}
    taken: dict[str, str] = {}          # a function or base area id → the industry area that reads it
    for pkg, pack in industry[:1]:
        for spec in pack.areas:
            area = Area(id=spec.id, name=spec.name or spec.id, question=spec.question, pack_id=pkg.pack_id,
                        words=tuple(spec.words), absorbs=tuple(spec.absorbs))
            by_id[area.id] = area
            out.areas.append(area)
            for raw in (spec.id, *spec.absorbs):
                taken.setdefault(raw, area.id)
    industry_ids = set(by_id)
    for pkg, pack in shared:
        for spec in pack.areas:
            if spec.id in taken:
                home = by_id[taken[spec.id]]
                if home.id not in industry_ids:                  # two function packs declare one area: one area
                    home.words = tuple(dict.fromkeys((*home.words, *spec.words)))
                continue                                         # an industry's area keeps its own name and words
            area = Area(id=spec.id, name=spec.name or spec.id, question=spec.question, pack_id=pkg.pack_id,
                        words=tuple(spec.words), absorbs=tuple(spec.absorbs))
            by_id[area.id] = area
            taken[spec.id] = area.id
            out.areas.append(area)
    other = Area(id=OTHER, name=OTHER_NAME, question=OTHER_QUESTION, pack_id="", generic=True)
    out.areas.append(other)
    by_id[OTHER] = other

    declared = {pkg.pack_id: {a.id for a in pack.areas} for pkg, pack in loaded}
    pack_ids = {pkg.pack_id for pkg, _ in loaded}
    for kb_file, data in iter_kb_payloads():
        if kb_file.pack_id not in pack_ids:
            continue
        for entry in (data if isinstance(data, list) else [data]):
            if not is_metric_pattern(entry):
                continue
            raw = str(entry.get("area") or "")
            kind = str(entry.get("kind") or "")
            if raw not in declared.get(kb_file.pack_id, set()):
                out.problems.append(f"pattern {entry['id']} ({kb_file.pack_id}/kb/{kb_file.name}) names area "
                                    f"{raw or 'none'}, which its package does not declare")
                continue
            if kind not in (*KINDS, ANALYSIS):
                out.problems.append(f"pattern {entry['id']} names kind {kind or 'none'}, not one of {', '.join(KINDS)}")
                continue
            home = by_id.get(taken.get(raw, raw))
            if home is None:
                continue
            nature = entry.get("metric_nature") if isinstance(entry.get("metric_nature"), dict) else {}
            home.patterns.append(Pattern(
                id=str(entry["id"]), title=str(entry.get("title") or entry["id"]), pack_id=kb_file.pack_id,
                area=home.id, kind=kind, declared_area=raw,
                direction=str(entry.get("direction") or "either"),
                definition=str(entry.get("business_definition") or nature.get("what_it_measures") or ""),
                template=_template(entry),
                anti_patterns=tuple(_anti(a) for a in (entry.get("anti_patterns") or [])[:6]),
                intent_tags=tuple(str(t) for t in (entry.get("intent_tags") or []))))

    for pkg, pack in loaded:
        for pm in pack.metrics:
            raw = pm.area
            if raw and raw not in declared[pkg.pack_id]:
                out.problems.append(f"recipe {pm.name} ({pkg.pack_id}) names area {raw}, which its package does not "
                                    "declare")
                raw = ""
            home = by_id.get(taken.get(raw, raw)) if raw else None
            if home is None:
                placed = best_areas(f"{pm.name} {pm.title}", [a for a in out.areas if not a.generic])
                home = placed[0][0] if placed else other
            sr = pm.sane_range
            home.recipes.append(Recipe(
                name=pm.name, title=pm.title or pm.name, pack_id=pkg.pack_id, area=home.id,
                formula=" ".join((pm.formula or "").split()), required_roles=tuple(pm.binds.required or []),
                sane_range=(sr.model_dump() if hasattr(sr, "model_dump") else sr), definition=(pm.definition or "").strip()))
    return out


def _template(entry: dict) -> str:
    """A pattern's template statement: its own, else the first of the statements a domain entry carries."""
    if entry.get("template"):
        return str(entry["template"])
    assets = entry.get("sql_assets")
    if isinstance(assets, dict):
        return str(next((v for v in assets.values() if isinstance(v, str) and v.strip()), ""))
    return ""


def _anti(item) -> str:
    """An anti-pattern in one line: its words, or what it is and why it is wrong."""
    if isinstance(item, dict):
        return " — ".join(str(item[k]) for k in ("pattern", "why_wrong") if item.get(k))
    return str(item)


def generic_patterns() -> list[Pattern]:
    """The generic layer's patterns — one per kind, with no template: what a person running ANY area reads. Handed to
    the writer for an area the knowledge base carries no pattern for, and cited as `generic:<kind>`."""
    return [Pattern(id=f"generic:{k}", title=f"{k.title()} — {KIND_WORDS[k]}", pack_id="", area="", kind=k,
                    direction="either", definition=KIND_WORDS[k]) for k in KINDS]
