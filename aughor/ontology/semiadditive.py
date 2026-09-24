"""PENDING item 27 — measures that must not be summed across periods.

A stock level, an account balance, a headcount is a reading AT a moment. Within one moment the readings add up (the
stock of every product on 1 March); across moments they do not (the stock on 1, 2 and 3 March is not three times the
stock). O5 named the kind — a semiadditive measure (`aughor.ontology.window_measures`) — and built the reduction a
timeseries binding's latest value is read through; but no property could be DECLARED one, so `SUM(on_hand)` over a
month compiled, and was written by the SQL writer, and answered a number three to thirty times too large.

A person now declares it — the property, and the time property its readings are taken `over` — and one law reads the
declaration on every path that could add it up:

* the object compiler (`_Compiler.semiadditive_check`) refuses a sum that spans more than one moment — through a
  measure, a metric's formula, a link, a formula that reads it (`declared_reading`: a stock's value is still a stock),
  the readings of a timeseries binding, or a frame that sums them;
* the ENTITY MODEL block tells the SQL writer, on every chat and deep-analysis prompt;
* the trust checks flag a written SUM of it that neither groups by nor pins its moment
  (`aughor.sql.semiadditive`, read through the readings registry the agent fills from `connection_declared_columns`)
  — a caveat on the headline and a receipt, on every path that runs `run_trust_checks` on its final SQL.

Checked against the graph at the door (the property must be one the compiler reads; `over` a date or timestamp of the
type's own), the verdict recorded on the override, and rebuilt by the overlay without a database — the law every other
declaration lives under.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from aughor.ontology.models import OntologyEntity, OntologyGraph, SemiAdditive


def normalized_semiadditive(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {"over": str(raw.get("over") or "").strip(), "note": str(raw.get("note") or "").strip()}


def semiadditive_problem(graph: Optional[OntologyGraph], entity: OntologyEntity, prop: str, spec: dict) -> str:
    """Why ``prop`` cannot be declared semiadditive over ``spec['over']`` on ``entity``, or ""."""
    from aughor.semantic.object_query import ObjectQueryRefused, is_temporal, property_at
    if not spec.get("over"):
        return "name the time property its readings are taken over (`over`)"
    try:
        _, measured, _ = property_at(graph, entity.api_name, prop, purpose="the semiadditive measure")
        _, clock, hops = property_at(graph, entity.api_name, spec["over"], purpose="its `over`")
    except ObjectQueryRefused as exc:
        return exc.reason
    if hops:
        return f"`over` must be {entity.id}'s own time property — '{spec['over']}' is reached through a link"
    if not is_temporal(clock):
        return (f"'{spec['over']}' on {entity.id} is not a date or timestamp "
                f"({clock.data_type or clock.semantic_type or 'untyped'}) — a reading is taken at a moment")
    if is_temporal(measured):
        return f"'{prop}' is itself a moment, not a quantity"
    return ""


def declared_semiadditive(specs: Any, verdicts: Any) -> dict[str, SemiAdditive]:
    """The semiadditive declarations that bound, rebuilt from their specs and verdicts — one that never bound reaches
    no reader (it is listed on the override with why)."""
    verdicts = verdicts if isinstance(verdicts, dict) else {}
    out: dict[str, SemiAdditive] = {}
    for prop, raw in (specs.items() if isinstance(specs, dict) else []):
        spec, verdict = normalized_semiadditive(raw), verdicts.get(prop) or {}
        if verdict.get("bound") is True and verdict.get("over") == spec["over"]:
            out[prop] = SemiAdditive(over=spec["over"], note=spec["note"])
    return out


# ── a reading, as a query reaches it ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reading:
    """A property that is a reading at a moment, as a query reaches it: the type that declares it (``owner``), the
    declared property, its declaration, the links crossed to reach it, and the formulas it was read through, outermost
    first (empty when the query names the declared property itself)."""
    owner: OntologyEntity
    prop: str
    decl: SemiAdditive
    hops: tuple = ()
    via: tuple[str, ...] = ()

    def said(self, entity: OntologyEntity, name: str) -> str:
        """`StockSnapshot.on_hand is` — or, through a formula, `StockSnapshot.stock_value reads StockSnapshot.on_hand,
        which is` — the subject of every refusal."""
        declared = f"{self.owner.id}.{self.prop}"
        return f"{entity.id}.{name} reads {declared}, which is" if self.via else f"{declared} is"

    def why(self) -> str:
        return f" ({self.decl.note})" if self.decl.note else ""


def _formula_of(entity: OntologyEntity, name: str) -> Optional[str]:
    """The per-row formula behind ``name`` on ``entity`` — an expression property, or a builder's verified computed
    property — or None when it names neither."""
    low = (name or "").lower()
    expression = next((x for k, x in (entity.expressions or {}).items() if k.lower() == low), None)
    if expression is not None:
        return expression.expression
    computed = next((c for c in entity.computed_properties or [] if c.id.lower() == low and c.verified), None)
    return computed.formula_sql if computed is not None else None


def declared_reading(graph: Optional[OntologyGraph], entity: OntologyEntity, name: str,
                     _seen: frozenset = frozenset()) -> Optional[Reading]:
    """``entity.name`` as a reading at a moment: declared so itself, or a formula that reads one — through its own
    names or through links, each name resolved by the compiler's own path law (`property_at`). A formula carries its
    reading's law: a stock's value (`on_hand * unit_cost`) is still a stock. None when it is neither — and at once
    when nothing in the graph declares a reading, so an ontology without one compiles exactly as it did."""
    if graph is None or not any(e.semiadditive for e in graph.entities.values()):
        return None
    low = (name or "").lower()
    declared = next((k for k in (entity.semiadditive or {}) if k.lower() == low), None)
    if declared is not None:
        return Reading(owner=entity, prop=declared, decl=entity.semiadditive[declared])
    formula = _formula_of(entity, name)
    if formula is None or (entity.id, low) in _seen:
        return None
    from aughor.semantic.object_query import ObjectQueryRefused, formula_paths, property_at
    try:
        paths = formula_paths(formula)
    except ObjectQueryRefused:
        return None                     # a formula the compiler cannot read is refused when it is read
    seen = _seen | {(entity.id, low)}
    for path in paths:
        try:
            landing, prop, hops = property_at(graph, entity.api_name, path, purpose="a formula's name")
        except ObjectQueryRefused:
            continue
        inner = declared_reading(graph, landing, prop.name, seen)
        if inner is not None:
            return Reading(owner=inner.owner, prop=inner.prop, decl=inner.decl, hops=tuple(hops) + inner.hops,
                           via=(f"{entity.id}.{name}",) + inner.via)
    return None


def one_value(f: Any) -> bool:
    """Whether a condition keeps ONE value of its path: `=` a value, or `in` a single one. A comparison with another
    property (`value_path`) carries no value — the compiler refuses a condition naming both — so it keeps none: each
    row compares with its own."""
    if f.op == "=":
        return f.value is not None and not isinstance(f.value, list)
    if f.op == "in":
        values = list(f.values or (f.value if isinstance(f.value, list) else []))
        return len({str(v) for v in values}) == 1
    return False


# ── the SQL writer's side: what it is told, and what the trust checks read ─────────────────

def semiadditive_lines(entity: OntologyEntity) -> list[str]:
    """The ENTITY MODEL lines for ``entity``'s declared readings — one per property, the law in the SQL writer's
    terms."""
    out = []
    for prop, decl in sorted((entity.semiadditive or {}).items()):
        note = f" ({decl.note})" if decl.note else ""
        out.append(f"    READING AT A MOMENT: {prop}, taken over {decl.over}{note} — SUM it only within one "
                   f"{decl.over} (GROUP BY {decl.over}, or WHERE {decl.over} = one value such as the latest); across "
                   f"{decl.over} use AVG, MIN or MAX, or SUM(...) / COUNT(DISTINCT {decl.over})")
    return out


def declared_columns(graph: Optional[OntologyGraph]) -> dict[str, dict[str, dict]]:
    """``{table: {column: {"over", "note"}}}`` (names lower-cased) — the declared readings a written statement can
    name, on each type's own backing table, as the plain data the platform's check reads
    (`aughor.sql.semiadditive`). A reading supplied by a binding or a formula, or taken over one, is not a column of
    that table: the check stays silent on it rather than guess (the compiler still holds it to the law)."""
    out: dict[str, dict[str, dict]] = {}
    for entity in (graph.entities.values() if graph is not None else []):
        if not entity.semiadditive:
            continue
        b = entity.backing
        table = (b.table if b is not None else "") or (entity.source_tables[0] if entity.source_tables else "")
        table = (table or "").rsplit(".", 1)[-1].strip('"`').lower()
        own = {k.lower() for k in (entity.properties or {})}
        for prop, decl in entity.semiadditive.items():
            if table and prop.lower() in own and decl.over.lower() in own:
                out.setdefault(table, {})[prop.lower()] = {"over": decl.over, "note": decl.note}
    return out


#: How long a connection's declarations are served from memory to the trust checks, which read them on every
#: statement an answer runs. The door that declares or withdraws one clears the entry (`forget_declared`).
_TTL_S = 30.0
_DECLARED: dict[str, tuple[float, dict]] = {}


def forget_declared(connection_id: str = "") -> None:
    if connection_id:
        _DECLARED.pop(connection_id, None)
    else:
        _DECLARED.clear()


def connection_declared_columns(connection_id: str) -> dict:
    """Every declared reading on the connection's served ontologies — each scope it has a graph for, human
    declarations overlaid (`load_latest_ontology`) — as `declared_columns` reads them, held for `_TTL_S`. The loader
    the agent registers for the platform's trust checks (`aughor.kernel.registries.readings`). Never raises: a graph
    that cannot be read declares nothing, and the statement is checked for nothing more."""
    if not connection_id:
        return {}
    hit = _DECLARED.get(connection_id)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    found: dict = {}
    try:
        from aughor.ontology.store import cached_ontology_scopes, load_latest_ontology
        for conn, schema in cached_ontology_scopes():
            if conn == connection_id:
                for table, columns in declared_columns(load_latest_ontology(conn, schema)).items():
                    found.setdefault(table, {}).update(columns)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the declared readings are read from the served ontology; unreadable, none are declared",
                 counter="readings.load")
        found = {}
    _DECLARED[connection_id] = (time.monotonic() + _TTL_S, found)
    return found
