"""Entity-binding resolver — proposal engine (P1, the grounding crux).

A pack declares ROLES (customer, event, cohort_anchor, …), never table names. At deploy this
resolver proposes a concrete mapping role → table/column for a specific warehouse, with
evidence and a confidence, so the same pack is portable across connections.

This module is the PURE proposal half: it scores roles against a connection-agnostic
``SchemaFacts`` contract (tables, identity columns, FK edges, date columns, business model).
Two pieces are deliberately deferred because they need a live connection:
  • the adapter that builds ``SchemaFacts`` from ``aughor/profile`` + the entity graph, and
  • the dry-run/EXPLAIN verification of each metric recipe against the proposed binding.
Keeping the contract explicit means this engine is fully unit-testable today and the live
adapter slots in behind it without reshaping the logic. See DOMAIN_EXPERTISE_PACKS.md §5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aughor.packs.models import RoleSpec


# ── Connection-agnostic facts the proposal engine reasons over ────────────────

@dataclass
class ColumnFact:
    name: str
    dtype: str = ""
    is_date: bool = False
    is_identity: bool = False        # a stable per-row key (PK / unique id)


@dataclass
class TableFact:
    name: str
    columns: list[ColumnFact] = field(default_factory=list)
    # fk column on THIS table → target table name (e.g. {"customer_id": "dim_customers"})
    references: dict[str, str] = field(default_factory=dict)
    row_count: int = 0

    def date_columns(self) -> list[ColumnFact]:
        return [c for c in self.columns if c.is_date]

    def identity_columns(self) -> list[ColumnFact]:
        return [c for c in self.columns if c.is_identity]


@dataclass
class SchemaFacts:
    tables: list[TableFact] = field(default_factory=list)
    business_model: str = ""          # "subscription" | "transactional" | "" (unknown)

    def table(self, name: str) -> Optional[TableFact]:
        return next((t for t in self.tables if t.name == name), None)


@dataclass
class BindingCandidate:
    role: str
    table: Optional[str] = None
    column: Optional[str] = None
    value: Optional[str] = None        # for value-roles (e.g. active_definition default)
    confidence: float = 0.0            # 0-1
    evidence: str = ""
    bound: bool = False                # did we resolve anything at all?


def _referencer_count(facts: SchemaFacts, target_table: str) -> int:
    return sum(1 for t in facts.tables for tgt in t.references.values() if tgt == target_table)


def _resolve_entity(facts: SchemaFacts) -> BindingCandidate:
    """The entity is the identity table other tables reference most — that's the hub the
    rest of the model hangs off (e.g. dim_customers, referenced by orders/sessions/…)."""
    best: Optional[TableFact] = None
    best_score = -1.0
    best_refs = 0
    for t in facts.tables:
        ids = t.identity_columns()
        if not ids:
            continue
        refs = _referencer_count(facts, t.name)
        score = refs * 10 + 1            # +1 so a lone identity table still beats nothing
        if score > best_score:
            best, best_score, best_refs = t, score, refs
    if best is None:
        return BindingCandidate(role="", evidence="no table has a stable identity column")
    idcol = best.identity_columns()[0].name
    conf = 0.55 + min(best_refs, 4) * 0.1     # more referencers → more certain
    return BindingCandidate(
        role="", table=best.name, column=idcol, confidence=round(min(conf, 0.95), 3),
        evidence=f"{best.name}.{idcol} is a stable id referenced by {best_refs} table(s)",
        bound=True,
    )


def _resolve_event(facts: SchemaFacts, entity_table: Optional[str]) -> BindingCandidate:
    """The event is a dated fact that references the entity — proof a party was 'active'."""
    best: Optional[TableFact] = None
    best_score = -1.0
    for t in facts.tables:
        if not t.date_columns():
            continue
        refs_entity = entity_table in t.references.values() if entity_table else False
        score = (5 if refs_entity else 0) + min(t.row_count, 1) + len(t.date_columns()) * 0.1
        if t.name == entity_table:
            score -= 3                    # the entity table itself is rarely the event fact
        if score > best_score:
            best, best_score = t, score
    if best is None:
        return BindingCandidate(role="", evidence="no dated fact table found")
    refs_entity = entity_table in best.references.values() if entity_table else False
    datecol = best.date_columns()[0].name
    conf = (0.8 if refs_entity else 0.4)
    return BindingCandidate(
        role="", table=best.name, column=datecol, confidence=conf,
        evidence=(f"{best.name} is a dated fact"
                  + (f" referencing {entity_table}" if refs_entity else " (no FK to the entity — verify)")),
        bound=True,
    )


def _resolve_date_anchor(facts: SchemaFacts, entity_table: Optional[str],
                         spec: RoleSpec, event: BindingCandidate) -> BindingCandidate:
    """A cohort anchor is a date ON the entity (signup/created); else fall back to the
    role's default (commonly 'first_event' → derive from the event's first timestamp)."""
    t = facts.table(entity_table) if entity_table else None
    if t:
        for c in t.date_columns():
            return BindingCandidate(
                role="", table=t.name, column=c.name, confidence=0.75,
                evidence=f"{t.name}.{c.name} is a date on the entity", bound=True)
    if (spec.default or "") == "first_event" and event.bound:
        return BindingCandidate(
            role="", value="first_event", confidence=0.5,
            evidence=f"no date on the entity — derive from first {event.table} timestamp", bound=True)
    return BindingCandidate(role="", evidence="no entity date and no usable default")


def _resolve_value_role(spec: RoleSpec, facts: SchemaFacts) -> BindingCandidate:
    """A choice role (e.g. active_definition with one_of) — pick by business model, else the
    declared default."""
    bm = (facts.business_model or "").lower()
    choice = None
    evidence = ""
    if "subscription" in bm and "subscription_open" in spec.one_of:
        choice, evidence = "subscription_open", "business model is subscription"
    elif bm and "purchased_in_window" in spec.one_of:
        choice, evidence = "purchased_in_window", f"business model is {bm}"
    if choice is None:
        choice = spec.default or (spec.one_of[0] if spec.one_of else None)
        evidence = "declared default" if spec.default else "first allowed option"
    if choice is None:
        return BindingCandidate(role="", evidence="no options to choose from")
    return BindingCandidate(role="", value=choice, confidence=0.6, evidence=evidence, bound=True)


def propose_bindings(entities: dict[str, RoleSpec], facts: SchemaFacts) -> dict[str, BindingCandidate]:
    """Propose a concrete binding for every declared role against `facts`. Resolved in
    dependency order (entity → event → date anchor) so later roles can lean on earlier ones.
    Every candidate carries evidence + confidence; an unresolved role is returned `bound=False`
    (surfaced to the deployer, never silently guessed). Pure; never raises."""
    out: dict[str, BindingCandidate] = {}

    def kind(spec: RoleSpec) -> str:
        return str((spec.expects or {}).get("kind", "")).lower()

    # 1) entity roles
    entity_table = None
    for name, spec in entities.items():
        if kind(spec) == "entity":
            cand = _resolve_entity(facts)
            cand.role = name
            out[name] = cand
            if cand.bound and entity_table is None:
                entity_table = cand.table

    # 2) event roles
    event_cand = BindingCandidate(role="")
    for name, spec in entities.items():
        if kind(spec) == "event":
            cand = _resolve_event(facts, entity_table)
            cand.role = name
            out[name] = cand
            if cand.bound:
                event_cand = cand

    # 3) date / choice / leftover roles
    for name, spec in entities.items():
        if name in out:
            continue
        if kind(spec) == "date":
            cand = _resolve_date_anchor(facts, entity_table, spec, event_cand)
        elif spec.one_of:
            cand = _resolve_value_role(spec, facts)
        else:
            cand = BindingCandidate(role="", evidence=f"no resolver rule for role kind {kind(spec)!r}")
        cand.role = name
        out[name] = cand

    return out


def binding_report(entities: dict[str, RoleSpec], facts: SchemaFacts) -> dict:
    """Convenience summary: the proposals plus how many roles bound (the deployer's at-a-glance
    'is this pack groundable here?'). The dry-run verification of recipes is a separate P1b step."""
    props = propose_bindings(entities, facts)
    bound = sum(1 for c in props.values() if c.bound)
    return {
        "proposals": props,
        "bound": bound,
        "total": len(props),
        "fully_bound": bound == len(props) and len(props) > 0,
    }
