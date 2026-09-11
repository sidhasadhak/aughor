"""The core the business extends — an industry map as claims to measure (ROADMAP §3.15 ON-0a).

A pack's `ontology.yaml` is an APPROXIMATE map of an industry: the object types it expects,
the links between them with the cardinality the data must confirm, the lifecycles with the
states it expects to be terminal, and the fields it knows carry business-specific aliases
without knowing which. None of it is rendered into a prompt. Each entry is evaluated against
THIS graph and THIS data and recorded as a `CoreClaim` with a tier — `expected` until the
data can speak, `measured-true`, `measured-false` (the data wins), `human` — so a UI can show
what the core expected and what the warehouse said. What reaches the model is only the
measured label on the relationship or entity itself, through the verified tier it already
has (ON-0's reach ratchet is the gate).

Layering rides the pack `extends` chain: `core-ecommerce` ← `fashion-ecommerce` ← the
company's own pack. Parents resolve first; a child entry with the same name replaces its
parent's. Matching is deterministic — names and aliases against entity ids, display names
and table stems — never a model call; a wrong alignment is edited like any other override.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.ontology.models import CoreClaim, OntologyGraph
from aughor.packs.models import Pack, PackOntology

_FLIP = {"1:N": "N:1", "N:1": "1:N", "1:1": "1:1", "N:N": "N:N"}
_PREFIXES = ("dim_", "fact_", "tbl_", "stg_", "raw_")


def _norm(name: str) -> str:
    """Case, punctuation, common warehouse prefixes and a trailing plural 's' are noise."""
    s = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    for pre in _PREFIXES:
        if s.startswith(pre.replace("_", "")):
            s = s[len(pre) - 1:]
    if len(s) > 3 and s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


def _stem(table: str) -> str:
    return table.split(".")[-1]


def load_pack_by_id(pack_id: str) -> Optional[Pack]:
    from aughor.packs.loader import load_pack
    from aughor.packs.roots import pack_dir
    root = pack_dir(pack_id)
    if root is None:
        return None
    try:
        return load_pack(root)
    except Exception:  # noqa: BLE001 — an unloadable pack is "no map", never a build failure
        return None


def _merge(into: PackOntology, other: PackOntology) -> None:
    objs = {o.name: o for o in into.objects}
    objs.update({o.name: o for o in other.objects})
    into.objects = list(objs.values())
    links = {(lk.from_object, lk.to_object): lk for lk in into.links}
    links.update({(lk.from_object, lk.to_object): lk for lk in other.links})
    into.links = list(links.values())
    lcs = {lc.object: lc for lc in into.lifecycles}
    lcs.update({lc.object: lc for lc in other.lifecycles})
    into.lifecycles = list(lcs.values())
    als = {a.field: a for a in into.aliases}
    als.update({a.field: a for a in other.aliases})
    into.aliases = list(als.values())


def resolve_ontology(pack_id: str, _seen: Optional[set[str]] = None) -> Optional[PackOntology]:
    """The pack's map with its `extends` chain folded in — parents first, child wins a name."""
    seen = _seen if _seen is not None else set()
    if pack_id in seen:
        return None
    seen.add(pack_id)
    pack = load_pack_by_id(pack_id)
    if pack is None:
        return None
    merged = PackOntology()
    for parent in pack.manifest.extends:
        po = resolve_ontology(parent, seen)
        if po is not None:
            _merge(merged, po)
    if pack.ontology is not None:
        _merge(merged, pack.ontology)
    if not (merged.objects or merged.links or merged.lifecycles or merged.aliases):
        return None
    return merged


def end_state_names_for_pack(pack_id: str) -> set[str]:
    po = resolve_ontology(pack_id)
    if po is None:
        return set()
    return {n for lc in po.lifecycles for n in lc.end_state_names}


def match_objects(po: PackOntology, graph: OntologyGraph) -> dict[str, str]:
    """expected object name → entity id. Ids and display names first, table stems second;
    an expected object matches at most one entity and an entity at most one object."""
    by_name: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    for eid, e in graph.entities.items():
        for cand in (e.id, e.display_name):
            by_name.setdefault(_norm(cand), eid)
        for t in e.source_tables:
            by_stem.setdefault(_norm(_stem(t)), eid)
    out: dict[str, str] = {}
    taken: set[str] = set()
    for obj in po.objects:
        names = [_norm(obj.name)] + [_norm(a) for a in obj.aliases]
        hit = next((by_name[n] for n in names if n in by_name and by_name[n] not in taken), None) \
            or next((by_stem[n] for n in names if n in by_stem and by_stem[n] not in taken), None)
        if hit:
            out[obj.name] = hit
            taken.add(hit)
    return out


@dataclass
class ClaimsReport:
    pack_id: str
    claims: list[CoreClaim] = field(default_factory=list)
    matched: dict[str, str] = field(default_factory=dict)

    def by_tier(self) -> dict[str, int]:
        out: dict[str, int] = {"expected": 0, "measured-true": 0, "measured-false": 0, "human": 0}
        for c in self.claims:
            out[c.tier] = out.get(c.tier, 0) + 1
        return out

    def summary(self) -> dict:
        return {"pack": self.pack_id, "matched": self.matched, "by_tier": self.by_tier(),
                "claims": [{"kind": c.kind, "subject": c.subject, "expected": c.expected,
                            "measured": c.measured, "tier": c.tier, "note": c.note} for c in self.claims]}


def apply_core_claims(graph: OntologyGraph, po: PackOntology, pack_id: str, db: Any = None) -> ClaimsReport:
    """Evaluate every claim in the map against the graph (and the data when `db` is given)
    and record the result on the graph, replacing this pack's earlier claims."""
    from aughor.ontology.lifecycle import observed_states, rows_that_left
    prov = f"pack:{pack_id}"
    matched = match_objects(po, graph)
    claims: list[CoreClaim] = []

    for obj in po.objects:
        eid = matched.get(obj.name)
        if eid:
            table = (graph.entities[eid].source_tables or ["?"])[0]
            claims.append(CoreClaim(kind="object", subject=obj.name, expected="present", measured=f"{eid} ({table})",
                                    tier="measured-true", provenance=prov, note=f"matched {eid} backed by {table}"))
        else:
            tried = ", ".join([obj.name] + obj.aliases[:5])
            claims.append(CoreClaim(kind="object", subject=obj.name, expected="present", tier="expected",
                                    provenance=prov, note=f"no table matched — tried {tried}"))

    rel_by_pair: dict[frozenset, Any] = {}
    for rel in graph.relationships.values():
        rel_by_pair.setdefault(frozenset((rel.from_entity, rel.to_entity)), rel)
    for lk in po.links:
        subject = f"{lk.from_object} → {lk.to_object}"
        a, b = matched.get(lk.from_object), matched.get(lk.to_object)
        if not a or not b or a == b:
            claims.append(CoreClaim(kind="link", subject=subject, expected=lk.cardinality, tier="expected",
                                    provenance=prov, note="one end has no matched table"))
            continue
        rel = rel_by_pair.get(frozenset((a, b)))
        if rel is None:
            claims.append(CoreClaim(kind="link", subject=subject, expected=lk.cardinality, tier="expected",
                                    provenance=prov, note=f"no join found between {a} and {b}"))
            continue
        if lk.via and lk.via.lower() not in (rel.from_col.lower(), rel.to_col.lower()):
            claims.append(CoreClaim(kind="link", subject=subject, expected=lk.cardinality, tier="expected",
                                    provenance=prov,
                                    note=f"the built graph joins {a} ↔ {b} on {rel.from_col}; the core expects {lk.via}"))
            continue
        label = rel.measured_cardinality
        if label is None:
            claims.append(CoreClaim(kind="link", subject=subject, expected=lk.cardinality, measured=None,
                                    tier="expected", provenance=prov,
                                    note=f"authored {rel.cardinality}, not yet measured ({rel.id})"))
            continue
        oriented = label if rel.from_entity == a else _FLIP[label]
        tier = "measured-true" if oriented == lk.cardinality else "measured-false"
        claims.append(CoreClaim(kind="link", subject=subject, expected=lk.cardinality, measured=oriented, tier=tier,
                                provenance=prov, note=f"{rel.id}: {rel.cardinality_note}"[:240]))

    for lc in po.lifecycles:
        eid = matched.get(lc.object)
        entity = graph.entities.get(eid) if eid else None
        if entity is None:
            claims.append(CoreClaim(kind="lifecycle", subject=lc.object, expected=", ".join(lc.terminal_states),
                                    tier="expected", provenance=prov, note="no matched table"))
            continue
        if not entity.lifecycle_column:
            claims.append(CoreClaim(kind="lifecycle", subject=lc.object, expected=", ".join(lc.terminal_states),
                                    tier="expected", provenance=prov,
                                    note=f"no lifecycle detected on {eid}" + (f" (the core looks for `{lc.column_hint}`)" if lc.column_hint else "")))
            continue
        table, column = entity.source_tables[0], entity.lifecycle_column
        observed = observed_states(db, table, column) if db is not None else None
        for state in lc.terminal_states:
            subject = f"{lc.object}.{column} terminal '{state}'"
            if observed is None:
                claims.append(CoreClaim(kind="lifecycle", subject=subject, expected="terminal", tier="expected",
                                        provenance=prov, note="not measured (no data connection)"))
            elif state not in observed:
                claims.append(CoreClaim(kind="lifecycle", subject=subject, expected="terminal", tier="expected",
                                        provenance=prov, note="never observed in the data"))
            elif rows_that_left(db, table, column, state):
                n = rows_that_left(db, table, column, state)
                claims.append(CoreClaim(kind="lifecycle", subject=subject, expected="terminal", measured="not terminal",
                                        tier="measured-false", provenance=prov,
                                        note=f"{n} rows left '{state}' — its timestamp is set on rows now in another state"))
            elif state in entity.terminal_states:
                claims.append(CoreClaim(kind="lifecycle", subject=subject, expected="terminal", measured="terminal",
                                        tier="measured-true", provenance=prov,
                                        note=f"observed ({observed[state]} rows) and in the built terminal set"))
            else:
                claims.append(CoreClaim(kind="lifecycle", subject=subject, expected="terminal", tier="expected",
                                        provenance=prov,
                                        note=f"observed ({observed[state]} rows) and NOT in the built terminal set — unconfirmed"))

    for al in po.aliases:
        claims.append(CoreClaim(kind="alias", subject=al.field, expected="business-specific aliases",
                                tier="expected", provenance=prov,
                                note="the core declares the field has aliases and none of their values"))

    graph.core_claims = [c for c in graph.core_claims if c.provenance != prov] + claims
    return ClaimsReport(pack_id=pack_id, claims=claims, matched=matched)


def bound_pack_ids(connection_id: str, schema_name: Optional[str]) -> list[str]:
    """Ids of the active packs DEPLOYED on this connection+schema (the opt-in)."""
    try:
        from aughor.packs.bindings import is_bound
        from aughor.packs.intake import active_packs
        return [p.manifest.id for p in active_packs() if is_bound(p.manifest.id, connection_id, schema_name or "")]
    except Exception:  # noqa: BLE001 — a store hiccup means "no packs", never a failed build
        return []


def bound_end_state_names(connection_id: str, schema_name: Optional[str]) -> Optional[frozenset[str]]:
    names: set[str] = set()
    for pid in bound_pack_ids(connection_id, schema_name):
        names |= end_state_names_for_pack(pid)
    return frozenset(n.lower() for n in names) if names else None


def apply_bound_pack_claims(graph: OntologyGraph, connection_id: str, schema_name: Optional[str],
                            db: Any = None) -> Optional[ClaimsReport]:
    """Evaluate the maps of every pack deployed on the connection; the last report is returned."""
    report = None
    for pid in bound_pack_ids(connection_id, schema_name):
        po = resolve_ontology(pid)
        if po is not None:
            report = apply_core_claims(graph, po, pid, db)
    return report
