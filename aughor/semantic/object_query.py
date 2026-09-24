"""ON-2 — objects at runtime: the compiled door (ROADMAP §3.15).

The v1 compiler beside this module (`compiler.py`) assembles one aggregate over ONE table and
hands everything with a join back to free-form generation — rightly, because cross-table joins
are where generated SQL goes wrong. This module is the object-set algebra the wave names:

    objects(T).filter(segment | predicate).link(L).measure(metric | agg(property))
              .by(dimension).over(grain)

compiled deterministically to SQL over each type's backing (ON-1), with the join guard's law
applied BY CONSTRUCTION instead of checked afterwards:

* **A link is traversed only when its cardinality was MEASURED** (ON-0a). An inferred label is
  refused, never trusted — §3.15's risk (a): the algebra is exactly where a wrong cardinality
  would corrupt a number silently.
* **To-one** (N:1 or 1:1 from where the query stands) is a LEFT JOIN, which cannot multiply the
  anchor's rows. It carries dimensions, filters, and the aggregates repetition cannot change
  (COUNT DISTINCT, MIN, MAX). A SUM, AVG or COUNT across it is REFUSED: the one side's value
  would be counted once per anchor row — the ON-0 hard set's `l13` miss, order GMV summed per
  line.
* **To-many** (1:N) is PRE-AGGREGATED per key before the join, so a measure over it is computed
  at the linked grain and rolled up; the chasm trap cannot be written. An average rolls up as a
  ratio of sums, never an average of averages; a COUNT DISTINCT across it is refused, because
  distinct counts do not add. A condition through a to-many link keeps the objects with at least
  one matching linked row (EXISTS) — the set is filtered, never multiplied.
* **N:N is refused both ways** — no join or pre-aggregation over it is safe.
* **A ratio is a ratio of aggregates** (`divide_by`), never an average of row ratios.
* **A property from a further binding (ON-1b) is read through a LEFT JOIN on the object's key** — and only when the
  binding was measured one row per object; an unmeasured or refuted binding is refused. A TIMESERIES binding is
  joined as each object's LATEST row (ON-5, `aughor.ontology.timeseries`): the reduction is one row per object by
  construction, so the same law holds, and the filter and the measure then read a value whose time semantics are
  declared rather than improvised.
* **A timeseries binding's READINGS are reachable as a SET** under the binding's own name (`price_history.price_eur`
  against the bare `price_eur`, which is the latest value). They are the same shape as a to-many link and are
  treated the same way, by the same code: pre-aggregated per the object's key before the join for a measure, and
  EXISTS for a condition. `where` on such a measure reads the READING's own columns, which is how "only the
  readings since March" is asked.

Coverage-gated as v1 is: every name resolves against the served graph or the compiler REFUSES
with the reason and the names that do exist. It never guesses, and a refusal is an answer —
`run_sql` stays the escape hatch under the guard battery (§6 item 14(b)). The compiled SQL still
executes through `execute_guarded`: construction is the promise, the battery is the audit.
"""
from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from aughor.ontology.backing import object_from
from aughor.ontology.bindings import binding_from, binding_problem, column_of, property_binding
from aughor.ontology.derived import derived_for, find_derived_metric, find_derived_property, find_derived_segment
from aughor.ontology.parts import backing_table, detail_from, part_of, parts_of, rollup_note
from aughor.ontology.sources import binding_source, entity_source
from aughor.ontology.timeseries import latest_from, latest_note
from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import (
    Binding,
    EntityProperty,
    OntologyEntity,
    OntologyGraph,
    OntologyMetric,
    OntologyRelationship,
)
from aughor.semantic.cross_source import KeyedRead

AggName = Literal["count", "count_distinct", "sum", "avg", "min", "max"]
FilterOp = Literal["=", "!=", ">", ">=", "<", "<=", "in", "not_in", "between",
                   "is_null", "not_null", "exists", "not_exists"]
Grain = Literal["", "hour", "day", "week", "month", "quarter", "year"]

_MAX_LIMIT = 10_000
_MAX_IN = 1_000
_MAX_HOPS = 3
#: The most links one path may cross — public for the path finder (ON-3b), which marks a longer path as
#: one the compiler would not take even when every hop on it is traversable.
MAX_LINK_HOPS = _MAX_HOPS
_COMPARE = {"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<="}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")
#: Profile roles whose values add up: a measure, a count-like ordinal, and a 0/1 flag (whose SUM
#: is a count and whose AVG is a share).
_SUMMABLE = frozenset({"measure", "ordinal", "flag"})
_NUMERIC_TYPES = ("INT", "DECIMAL", "NUMERIC", "DOUBLE", "FLOAT", "REAL", "NUMBER")


# ── the IR ──────────────────────────────────────────────────────────────────────────────

class ObjectFilter(BaseModel):
    """One condition. `path` is a property of the object type (`status`), a property reached
    through links (`customer.country`), or — for `exists` / `not_exists` — a link (`shipment`).
    A condition through a TO-MANY link keeps the objects that have at least one linked row
    matching it."""
    path: str
    op: FilterOp = "="
    value: Any = None
    #: The list for `in` / `not_in` / `between` (a list in `value` is read the same way).
    values: list[Any] = Field(default_factory=list)
    #: ON-9 — compare with ANOTHER property of the same object instead of a value (`=`, `!=`, `>`, `>=`, `<`, `<=`):
    #: a path read through to-one links only, of a comparable type. "Handed to the carrier after the line's shipping
    #: limit" is `order_item_to_order.order_delivered_carrier_date > shipping_limit_date`.
    value_path: str = ""


class MeasureTerm(BaseModel):
    """One aggregate: a verified named `metric` of the object type, or `agg` over `path`. An
    empty path with `count` counts the objects; a link with `count` counts linked objects.
    `where` restricts the rows THIS measure aggregates, read from the object it aggregates —
    it never changes the object set."""
    agg: AggName = "count"
    path: str = ""
    metric: str = ""
    where: list[ObjectFilter] = Field(default_factory=list)


class ObjectMeasure(MeasureTerm):
    name: str = ""
    #: A ratio of AGGREGATES: this term ÷ that term, each aggregated first.
    divide_by: Optional[MeasureTerm] = None
    scale: float = 1.0                     # 100 for a percentage
    decimals: Optional[int] = None


class ObjectQuery(BaseModel):
    """`objects(object_type).filter(segment, filters).measure(measures).by(by).over(grain)`."""
    object_type: str
    segment: str = ""
    filters: list[ObjectFilter] = Field(default_factory=list)
    measures: list[ObjectMeasure] = Field(min_length=1)
    by: list[str] = Field(default_factory=list)
    time: str = ""                         # the time property a grain or window reads
    grain: Grain = ""
    start: str = ""                        # ISO date, inclusive
    end: str = ""                          # ISO date, EXCLUSIVE — a quarter ends where the next begins
    order_by: str = ""
    descending: bool = True
    limit: Optional[int] = None


class ObjectQueryRefused(ValueError):
    """The compiler cannot vouch for this query. Never a guess: `reason` names what failed and
    `available` the names that do exist, so a caller can repair the query or fall back to
    `run_sql` under the guard battery."""

    def __init__(self, reason: str, available: Optional[list[str]] = None):
        super().__init__(reason)
        self.reason = reason
        self.available = list(available or [])


@dataclass
class CompiledObjectQuery:
    sql: str
    dialect: str
    object_type: str
    columns: list[str]
    #: One line per decision the compiler made — the body of the Trust Receipt's compiled path.
    plan: list[str]
    #: Every link the query relied on, with the measured cardinality and how it was treated.
    links: list[dict]
    caveats: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)     # the output columns that group
    measures: list[str] = field(default_factory=list)       # the output columns that aggregate
    #: ON-4 — every accepted edit an overlay property merged into this read, with its provenance.
    overlay: list[dict] = field(default_factory=list)
    #: ON-1b — every further binding the query joined, with what it was measured to hold.
    bindings: list[dict] = field(default_factory=list)
    #: ON-8 — set when the query reads a source by key from another connection than its anchor's: the statement split
    #: into what runs at home, what each other connection is read for, and the aggregation over both
    #: (`aughor.semantic.cross_source`). ``sql`` is then the statement as written, for a reader, and is not run.
    cross_source: Optional[Any] = None

    def to_dict(self) -> dict:
        return {"path": "compiled", "sql": self.sql, "dialect": self.dialect,
                "object_type": self.object_type, "columns": list(self.columns),
                "dimensions": list(self.dimensions), "measures": list(self.measures),
                "plan": list(self.plan), "links": list(self.links), "caveats": list(self.caveats),
                "overlay": list(self.overlay), "bindings": list(self.bindings),
                **({"cross_source": self.cross_source.to_dict()} if self.cross_source is not None else {})}


# ── links, read from where the query stands ─────────────────────────────────────────────

@dataclass(frozen=True)
class ObjectLink:
    rel: OntologyRelationship
    source: OntologyEntity
    target: OntologyEntity
    name: str
    local_col: str
    remote_col: str
    label: str                             # cardinality read source → target
    #: ON-3b — the relationship's business-verb name (`order_item_is_for_product`), accepted beside the
    #: mechanical `name` wherever a link is named; "" when the verb on record names nothing.
    business: str = ""

    @property
    def to_one(self) -> bool:
        return self.label.endswith(":1")

    def describe(self) -> str:
        return f"{self.name} ({self.source.id} → {self.target.id}, {self.label})"


def find_object_type(graph: OntologyGraph, name: str) -> OntologyEntity:
    """An object type by its api name, id, display name or backing table — or a refusal naming the
    types that exist. The one lookup the compiler, the instance reader and every door share."""
    want = (name or "").strip()
    low = want.lower()
    for e in graph.entities.values():
        if low in {e.id.lower(), e.api_name.lower(), (e.display_name or "").lower()}:
            return e
    for e in graph.entities.values():
        if any(low in (t.lower(), t.lower().rsplit(".", 1)[-1]) for t in e.source_tables):
            return e
    names = sorted(e.api_name for e in graph.entities.values())
    raise ObjectQueryRefused(f"no object type '{name}'{_did_you_mean(low, names)}", names)


def object_links(graph: OntologyGraph, entity: OntologyEntity) -> list[ObjectLink]:
    out: list[ObjectLink] = []
    for r in graph.relationships.values():
        label = r.measured_cardinality or r.cardinality
        if r.from_entity == entity.id and r.to_entity in graph.entities:
            out.append(ObjectLink(r, entity, graph.entities[r.to_entity], r.api_name, r.from_col, r.to_col, label,
                                  business=r.business_name()))
        if r.to_entity == entity.id and r.from_entity in graph.entities and r.from_entity != r.to_entity:
            left, right = label.split(":")
            out.append(ObjectLink(r, entity, graph.entities[r.from_entity], r.reverse_api_name,
                                  r.to_col, r.from_col, f"{right}:{left}", business=r.business_name()))
    return out


def link_problem(h: ObjectLink) -> str:
    """Why this link may not be traversed, or "" when it may."""
    if h.rel.measured_cardinality is None:
        return (f"link {h.describe()} has never been measured — its label was inferred "
                f"({h.rel.join_confidence} join evidence), never counted against the rows, and the compiler "
                "does not traverse an uncounted label (POST /ontology/measure measures it without a model call)")
    for e in (h.source, h.target):
        if e.backing is not None and e.backing.kind == "query":
            return (f"link {h.describe()} was measured on tables, and {e.id} is read through a query "
                    "backing — its cardinality over that SELECT is unmeasured")
    if h.label == "N:N":
        return (f"link {h.describe()} is N:N by measurement — neither {h.source.id}.{h.local_col} nor "
                f"{h.target.id}.{h.remote_col} is unique, so no join or pre-aggregation over it is safe")
    if h.rel.value_overlap is not None and h.rel.value_overlap <= 0:
        # ON-7 — a declared link is measured on how many of its keys meet; none is a join that reads every
        # linked value as NULL, and a NULL is not an answer. (The builder drops a found link like this at build.)
        return (f"link {h.describe()} was measured and its keys never meet — no {h.source.id}.{h.local_col} value "
                f"is held by {h.target.id}.{h.remote_col}; check the columns the link was declared on")
    return ""


# ── small helpers ───────────────────────────────────────────────────────────────────────

def _did_you_mean(word: str, names: list[str]) -> str:
    close = difflib.get_close_matches(word, names, n=3, cutoff=0.6)
    return f" — did you mean {', '.join(repr(c) for c in close)}?" if close else ""


def _split(path: str, purpose: str) -> list[str]:
    segs = [s.strip() for s in (path or "").split(".")]
    if not path or any(not s for s in segs):
        raise ObjectQueryRefused(f"{purpose} path '{path}' is empty or malformed")
    if len(segs) > _MAX_HOPS + 1:
        raise ObjectQueryRefused(f"{purpose} path '{path}' crosses more than {_MAX_HOPS} links")
    return segs


def _is_bool(p: EntityProperty) -> bool:
    return "BOOL" in (p.data_type or "").upper()


def _is_numeric(p: EntityProperty) -> bool:
    return any(t in (p.data_type or "").upper() for t in _NUMERIC_TYPES)


def _is_temporal(p: EntityProperty) -> bool:
    return (p.semantic_type or "") == "timestamp" or any(t in (p.data_type or "").upper() for t in ("DATE", "TIME"))


#: Public: a declaration's anchors are checked with the compiler's own reading of a property's kind (ON-9).
is_temporal = _is_temporal


def _family(p: EntityProperty) -> str:
    """The kind of value a property holds, for a comparison between two properties (ON-9)."""
    if _is_temporal(p):
        return "point in time"
    if _is_bool(p):
        return "boolean"
    if _is_numeric(p) or (p.semantic_type or "") in _SUMMABLE:
        return "number"
    return "text"


def find_computed(entity: OntologyEntity, name: str):
    """A builder computed property of the type by name (`ComputedProperty`), or None."""
    low = (name or "").lower()
    return next((c for c in entity.computed_properties or [] if c.id.lower() == low), None)


def find_property(entity: OntologyEntity, name: str) -> Optional[EntityProperty]:
    """A property of the type by name: one its backing supplies, else one a further binding supplies (ON-1b)."""
    props = entity.properties or {}
    if name in props:
        return props[name]
    low = name.lower()
    found = next((p for k, p in props.items() if k.lower() == low), None)
    for binding in entity.bindings or []:
        if found is not None:
            break
        found = next((p for k, p in binding.properties.items() if k.lower() == low), None)
    return found


def _type_word(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def overlay_properties(entity: OntologyEntity, overlay: Optional[list]) -> dict[str, list]:
    """ON-4 — an object type's overlay properties, ``{property (lower): [edit, …]}``, from the accepted
    property edits on its objects. A name the type reads from its source is never one: an edit adds a
    property, it does not shadow a column."""
    words = {_type_word(entity.api_name), _type_word(entity.id)}
    out: dict[str, list] = {}
    for e in overlay or []:
        if getattr(e, "kind", "") != "property" or _type_word(getattr(e, "object_type", "")) not in words:
            continue
        if not e.column or find_property(entity, e.column) is not None:
            continue
        out.setdefault(e.column.lower(), []).append(e)
    return out


def _literal(v: Any, path: str) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ObjectQueryRefused(f"filter on '{path}': {v} is not a finite number")
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    raise ObjectQueryRefused(f"filter on '{path}': a value must be a string, number or boolean, "
                             f"not {type(v).__name__}")


def typed_literal(v: Any, p: EntityProperty, path: str) -> str:
    """A literal typed by the column it meets: a numeric string to a numeric column is a number, "true"
    to a boolean column is TRUE — so `"400"` and `400` compile alike on every dialect (BigQuery will not
    compare INT64 with STRING). A string that does not read as the column's type stays a string: whether
    the value exists is the battery's value-domain question, never the compiler's guess."""
    if isinstance(v, str):
        s = v.strip()
        if _is_bool(p) and s.lower() in ("true", "false"):
            return s.upper()
        if _is_numeric(p) and _NUMBER.match(s):
            return s
    return _literal(v, path)


def _predicate(col: str, p: EntityProperty, f: ObjectFilter) -> str:
    op = f.op
    if op == "is_null":
        return f"{col} IS NULL"
    if op == "not_null":
        return f"{col} IS NOT NULL"
    if op in _COMPARE:
        if f.value is None or isinstance(f.value, (list, dict)):
            raise ObjectQueryRefused(f"filter '{f.path} {op}' needs one value (is_null / not_null for NULL, "
                                     "in for a list)")
        return f"{col} {_COMPARE[op]} {typed_literal(f.value, p, f.path)}"
    vals = f.values or (f.value if isinstance(f.value, list) else [])
    if op in ("in", "not_in"):
        if not vals or len(vals) > _MAX_IN:
            raise ObjectQueryRefused(f"filter '{f.path} {op}' needs `values`: a list of 1–{_MAX_IN}")
        rendered = ", ".join(typed_literal(v, p, f.path) for v in vals)
        return f"{col} {'IN' if op == 'in' else 'NOT IN'} ({rendered})"
    if op == "between":
        if len(vals) != 2:
            raise ObjectQueryRefused(f"filter '{f.path} between' needs `values`: [low, high]")
        return f"{col} BETWEEN {typed_literal(vals[0], p, f.path)} AND {typed_literal(vals[1], p, f.path)}"
    raise ObjectQueryRefused(f"filter '{f.path}': {op} takes a link, not a property")


def _rollup(agg: str, alias: str, add: Callable[[str], str], value: Optional[str], cond: str) -> str:
    """How a per-key aggregate rolls up to the object set — ONE law for a to-many LINK (ON-2) and for a
    timeseries binding's READINGS (ON-5), because a second copy of it is exactly where an average of averages
    would get in. `add` registers a column on the pre-aggregation and returns its name."""
    if agg == "count":
        return f"COALESCE(SUM({alias}.{add(_agg_sql('count', value, cond))}), 0)"
    if agg == "sum":
        return f"SUM({alias}.{add(_agg_sql('sum', value, cond))})"
    if agg in ("min", "max"):
        return f"{agg.upper()}({alias}.{add(_agg_sql(agg, value, cond))})"
    # an average rolls up as a ratio of sums, never an average of per-key averages
    s = add(_agg_sql("sum", value, cond))
    n = add(_agg_sql("count", value, cond))
    return f"1.0 * SUM({alias}.{s}) / NULLIF(SUM({alias}.{n}), 0)"


def _agg_sql(agg: str, value: Optional[str], cond: str) -> str:
    """One aggregate, restricted to the rows `cond` admits. `value=None` counts rows."""
    if value is None:
        return f"COUNT(CASE WHEN {cond} THEN 1 END)" if cond else "COUNT(*)"
    if agg == "count_distinct":
        return f"COUNT(DISTINCT CASE WHEN {cond} THEN {value} END)" if cond else f"COUNT(DISTINCT {value})"
    return f"{agg.upper()}(CASE WHEN {cond} THEN {value} END)" if cond else f"{agg.upper()}({value})"


def _check_aggregate(agg: str, p: EntityProperty, path: str, caveats: list[str]) -> None:
    """Refuse the aggregates whose number would mean nothing (a SUM of an id, an AVG of a date,
    a SUM of a category). Read from the profile's role; a lone per-unit tag is a caveat, not a
    refusal — one witness is a hint, and nothing acts on a hint."""
    if agg not in ("sum", "avg"):
        return
    role = (p.semantic_type or "").lower()
    if p.is_primary_key or role in ("key", "identifier"):
        raise ObjectQueryRefused(f"{agg} of '{path}' is not a quantity — it is an identifier; use count_distinct")
    if _is_temporal(p):
        raise ObjectQueryRefused(f"{agg} of '{path}' is not a quantity — it is a point in time; use min / max, "
                                 "or a grain")
    if role in ("dimension", "text"):
        raise ObjectQueryRefused(f"{agg} of '{path}' is not a quantity — it is a {role}; group by it instead")
    if role not in _SUMMABLE and not _is_numeric(p) and not _is_bool(p):
        raise ObjectQueryRefused(f"{agg} of '{path}' ({p.data_type or 'untyped'}, {role or 'unclassified'}) "
                                 "is not a known quantity")
    if agg == "sum" and (p.measure_grain or "") == "per_unit":
        caveats.append(f"'{path}' is profiled per unit: its SUM counts one unit per row — multiply by a "
                       "quantity for a line total")


def metric_on(m: OntologyMetric, entity: OntologyEntity) -> bool:
    tables = {t.lower().rsplit(".", 1)[-1] for t in (m.tables or []) if t}
    mine = {t.lower().rsplit(".", 1)[-1] for t in entity.source_tables}
    if m.entity == entity.id:
        return not tables or tables <= mine
    return bool(tables) and tables <= mine


def _qualify(fragment: str, alias: str, read: str, *, what: str, expression: bool = False) -> str:
    """Anchor an authored fragment (a segment's WHERE, a metric's formula) on `alias`: every
    unqualified column gets the alias, so a join cannot make a bare name mean another table."""
    import sqlglot
    from sqlglot import exp
    try:
        if expression:
            node = sqlglot.parse_one(f"SELECT {fragment} FROM _t", read=read).expressions[0]
        else:
            node = sqlglot.parse_one(f"SELECT 1 FROM _t WHERE {fragment}", read=read).args["where"].this
    except Exception as exc:  # noqa: BLE001 — an unparseable fragment is a refusal, never a guess
        raise ObjectQueryRefused(f"{what} could not be parsed to anchor it on the object ({exc})") from exc
    if node.find(exp.Select) is not None:
        raise ObjectQueryRefused(f"{what} holds a subquery; the compiler re-anchors only flat expressions")
    if expression and node.find(exp.AggFunc) is None:
        raise ObjectQueryRefused(f"{what} is not an aggregate, so it cannot be a measure")
    for col in node.find_all(exp.Column):
        if not col.table:
            col.set("table", exp.to_identifier(alias))
    return node.sql(dialect="duckdb")


def _row_formula(fragment: str, read: str, *, what: str):
    """A per-row formula (an expression property, or a builder's computed property) as a parsed SELECT expression —
    refused when it holds a subquery, an aggregate or a window: a property is per row, an aggregate is a metric."""
    import sqlglot
    from sqlglot import exp
    try:
        node = sqlglot.parse_one(f"SELECT {fragment} FROM _t", read=read).expressions[0]
    except Exception as exc:  # noqa: BLE001 — an unparseable fragment is a refusal, never a guess
        raise ObjectQueryRefused(f"{what} could not be parsed to anchor it on the object ({exc})") from exc
    if node.find(exp.Select) is not None:
        raise ObjectQueryRefused(f"{what} holds a subquery; a formula property is a flat expression")
    if node.find(exp.AggFunc) is not None or node.find(exp.Window) is not None:
        raise ObjectQueryRefused(f"{what} holds an aggregate or a window; a formula property is per row")
    return node


def formula_paths(fragment: str, read: str = "duckdb") -> list[str]:
    """The property paths a per-row formula reads — a bare name is a property of the type, a dotted one reaches it
    through to-one links (`customer.tier`). What the door checks each one against (`property_at`)."""
    from sqlglot import exp
    node = _row_formula(fragment, read, what="the formula")
    return list(dict.fromkeys(".".join(p.name for p in col.parts) for col in node.find_all(exp.Column)))


def _within(formula: str, condition: str) -> str:
    """A measure's formula with every aggregate restricted to the rows ``condition`` admits (ON-9 — a rule that scopes a
    metric): COUNT(*) counts only them, and every other aggregate reads its argument on them alone, so the rule scopes
    this measure and nothing else the query measures beside it."""
    import sqlglot
    from sqlglot import exp
    node = sqlglot.parse_one(f"SELECT {formula} FROM _t", read="duckdb").expressions[0]
    admitted = sqlglot.parse_one(f"SELECT 1 FROM _t WHERE {condition}", read="duckdb").args["where"].this
    for agg in [a for a in node.find_all(exp.AggFunc) if a.find_ancestor(exp.AggFunc) is None]:
        argument = agg.this
        if isinstance(argument, exp.Distinct):
            argument.set("expressions", [exp.Case(ifs=[exp.If(this=admitted.copy(), true=e.copy())])
                                         for e in argument.expressions])
        elif argument is None or isinstance(argument, exp.Star):
            agg.set("this", exp.Case(ifs=[exp.If(this=admitted.copy(), true=exp.Literal.number(1))]))
        else:
            agg.set("this", exp.Case(ifs=[exp.If(this=admitted.copy(), true=argument.copy())]))
    return node.sql(dialect="duckdb")


def backing_from(entity: OntologyEntity, alias: str) -> str:
    source = object_from(entity, alias)
    if not source:
        raise ObjectQueryRefused(f"object type {entity.id} has no backing to read from")
    return source


def _output_name(taken: list[str], *candidates: str) -> str:
    for c in candidates:
        if c and c not in taken:
            return c
    base, n = candidates[-1] or "value", 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def _org_fiscal_start() -> int:
    try:
        from aughor.orgsettings import effective_settings
        return int(effective_settings(None).fiscal_year_start_month or 1)
    except Exception:  # noqa: BLE001 — calendar quarters are the documented default
        return 1


# ── the compiler ────────────────────────────────────────────────────────────────────────

@dataclass
class _Scope:
    """A FROM level: one object type under an alias, with the to-one joins hung off it."""
    entity: OntologyEntity
    alias: str
    joins: list[str] = field(default_factory=list)
    join_alias: dict = field(default_factory=dict)
    #: The connection this level's rows live on — "" for the query's home. A level built inside an EXISTS or a
    #: pre-aggregation read by key from another connection lives there, and joins on that connection as it would at home.
    source: str = ""


@dataclass
class _Readings:
    """ON-5 — one timeseries binding's readings, pre-aggregated per the object's key. The same shape as a
    to-many link (`_ManyLink`) and rolled up by the same law (`_rollup`): its source holds many rows per
    object, so it is reduced to one row per object BEFORE the join and can never multiply the object set."""
    binding: Binding
    entity_key: str
    outer_alias: str
    alias: str
    inner_alias: str
    columns: list[tuple[str, str]] = field(default_factory=list)
    #: The connection the readings live on, and whether that is another than the object's (O3: read by key).
    source: str = ""
    far: bool = False

    def column(self, expr: str) -> str:
        for name, existing in self.columns:
            if existing == expr:
                return name
        name = f"v{len(self.columns) + 1}"
        self.columns.append((name, expr))
        return name

    def pre_aggregate(self) -> str:
        key = f"{self.inner_alias}.{quote_ident(self.binding.key)}"
        cols = ", ".join(f"{expr} AS {name}" for name, expr in self.columns)
        return f"SELECT {key} AS k, {cols} FROM {binding_from(self.binding, self.inner_alias)} GROUP BY {key}"

    def join_sql(self) -> str:
        return (f"LEFT JOIN ({self.pre_aggregate()}) AS {self.alias} "
                f"ON {self.outer_alias}.{quote_ident(self.entity_key)} = {self.alias}.k")


@dataclass
class _ManyLink:
    """One to-many link, pre-aggregated per its key: every measure over it becomes a column."""
    hop: ObjectLink
    outer_alias: str
    alias: str
    inner: _Scope
    columns: list[tuple[str, str]] = field(default_factory=list)
    #: Whether the link's target lives on another connection than the query's rows (O3: the pre-aggregation is read by
    #: key from there).
    far: bool = False

    def column(self, expr: str) -> str:
        for name, existing in self.columns:
            if existing == expr:
                return name
        name = f"v{len(self.columns) + 1}"
        self.columns.append((name, expr))
        return name

    def pre_aggregate(self) -> str:
        key = f"{self.inner.alias}.{quote_ident(self.hop.remote_col)}"
        cols = ", ".join(f"{expr} AS {name}" for name, expr in self.columns)
        joins = "".join(f" {j}" for j in self.inner.joins)
        return f"SELECT {key} AS k, {cols} FROM {backing_from(self.hop.target, self.inner.alias)}{joins} GROUP BY {key}"

    def join_sql(self) -> str:
        return (f"LEFT JOIN ({self.pre_aggregate()}) AS {self.alias} "
                f"ON {self.outer_alias}.{quote_ident(self.hop.local_col)} = {self.alias}.k")


class _Compiler:
    def __init__(self, graph: OntologyGraph, query: ObjectQuery, dialect: str, fiscal_start_month: int,
                 overlay: Optional[list] = None):
        self.g = graph
        #: ON-4 — the accepted property edits on this connection's objects, merged at read time.
        self.overlay_edits = list(overlay or [])
        self.overlay: list[dict] = []
        self._overlay_noted: set = set()
        #: ON-1b — the further bindings joined, one row each, and the (type, binding) pairs already planned.
        self.bindings: list[dict] = []
        self._bindings_noted: set = set()
        self.q = query
        self.dialect = dialect
        self.fiscal = fiscal_start_month
        self.plan: list[str] = []
        self.links: list[dict] = []
        self.caveats: list[str] = []
        self._n = 0
        self._many: dict[tuple, _ManyLink] = {}
        #: ON-5 — one pre-aggregation per (object alias, timeseries binding) read as a set.
        self._readings: dict[tuple, _Readings] = {}
        self._noted: set = set()
        #: Time columns typed DATE: a truncation over one must render as DATE_TRUNC, not
        #: TIMESTAMP_TRUNC, on dialects that tell the two apart (BigQuery).
        self._date_cols: set[str] = set()
        #: ON-9 — the derived properties being compiled right now (a derivation may not read itself), and those planned.
        self._deriving: set = set()
        self._derived_noted: set = set()
        #: ON-8 — the connection the query runs on (its anchor's; every type of a per-connection graph reads the graph's
        #: own, so nothing there is ever far), the FROM level a keyed read may hang off, and each keyed read by alias.
        self.home = graph.connection_id
        self.top: Optional[_Scope] = None
        self.far: dict[str, KeyedRead] = {}
        #: O2 — each alias a path through a keyed read stands for: the read, and the alias its rows carry inside the
        #: read's own statement (``__r`` for the read's own type, another for a type or binding joined inside it).
        self.far_paths: dict[str, tuple[KeyedRead, str]] = {}
        self._far_joined: dict[tuple, str] = {}
        #: PENDING item 27 — the formula properties being resolved right now, so one that reaches itself is refused.
        self._open_formulas: list[tuple[str, str]] = []
        #: PENDING item 27 — what keeps a sum of a reading at a moment to one moment beyond `by` and `filters`: the
        #: path a grain or window reads, and the path the measure being compiled is divided by the distinct count of.
        self.time_path = ""
        self._per_moment = ""

    def _alias(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def at(self, scope: _Scope) -> str:
        """The connection ``scope``'s rows live on."""
        return scope.source or self.home

    # ── names ──
    def entity(self, name: str) -> OntologyEntity:
        return find_object_type(self.g, name)

    def prop(self, entity: OntologyEntity, name: str, path: str) -> EntityProperty:
        p = (find_property(entity, name) or self.virtual_prop(entity, name) or self.derived_prop(entity, name)
             or self.computed_prop(entity, name))
        if p is not None:
            return p
        bound = sorted(name for binding in entity.bindings or [] for name in binding.properties)
        derived = sorted(d.name for d in derived_for(self.g, entity).properties)
        computed = sorted(c.id for c in entity.computed_properties or [] if c.verified)
        names = (sorted(entity.properties or {}) + bound + sorted(overlay_properties(entity, self.overlay_edits))
                 + derived + computed)
        links = sorted(h.name for h in object_links(self.g, entity))
        raise ObjectQueryRefused(f"{entity.id} has no property '{name}' (in '{path}'){_did_you_mean(name, names + links)}",
                                 names + links)

    def virtual_prop(self, entity: OntologyEntity, name: str) -> Optional[EntityProperty]:
        """ON-4 — an overlay property of ``entity``, as a property: BOOLEAN when every accepted value reads
        true/false, text otherwise. None when no accepted edit sets it."""
        edits = overlay_properties(entity, self.overlay_edits).get((name or "").strip().lower())
        if not edits:
            return None
        boolean = {str(e.body).strip().lower() for e in edits} <= {"true", "false"}
        return EntityProperty(name=edits[0].column, data_type="BOOLEAN" if boolean else "VARCHAR",
                              semantic_type="flag" if boolean else "dimension",
                              description="an overlay property — set by accepted edits, merged at read time")

    def computed_prop(self, entity: OntologyEntity, name: str) -> Optional[EntityProperty]:
        """PENDING item 27 — a computed property the builder VERIFIED on the type (`Customer.days_since_signup`), as a
        property: the prompt has cited these with authority all along, and the object door could not read one. An
        unverified one is not a name it accepts; one whose formula aggregates is refused when read (a metric)."""
        computed = find_computed(entity, name)
        if computed is None or not computed.verified:
            return None
        return EntityProperty(name=computed.id, display_name=computed.label or computed.id,
                              semantic_type="measure", unit=computed.unit or "", is_derived=True,
                              description=f"a computed property: {computed.formula_sql}")

    def derived_prop(self, entity: OntologyEntity, name: str) -> Optional[EntityProperty]:
        """ON-9 — a property a declared process derives on ``entity`` (`dispatch_lag_days`): the whole calendar days
        between two of the object's moments. None when nothing derives the name here."""
        d = find_derived_property(self.g, entity, name)
        if d is None:
            return None
        return EntityProperty(name=d.name, display_name=d.name, data_type="DOUBLE" if d.unit == "hours" else "BIGINT",
                              semantic_type="measure", unit=d.unit,
                              is_derived=True, description=f"{d.description} — derived from {d.source}")

    def colref(self, scope: _Scope, alias: str, entity: OntologyEntity, p: EntityProperty) -> str:
        """The SQL for a property of ``entity`` under ``alias``: its column, a further binding's column joined on
        the object's key (ON-1b), or — for an overlay property — the accepted values joined on the object's key.
        The source is read, never written."""
        if alias in self.far_paths:
            return self.far_column(scope, alias, entity, p)
        expression = (entity.expressions or {}).get(p.name)
        if expression is not None:
            return self.expression_column(scope, alias, entity, p.name, expression)
        computed = find_computed(entity, p.name) if find_property(entity, p.name) is None else None
        if computed is not None:
            self.plan.append(f"{entity.id}.{p.name}: = {computed.formula_sql} (a computed property)")
            return self.formula_column(scope, alias, entity, p.name, computed.formula_sql,
                                       what=f"{entity.id}.{p.name} (a computed property)")
        binding = property_binding(entity, p.name)
        if binding is not None:
            return self.binding_column(scope, alias, entity, binding, p)
        if p.is_derived and find_property(entity, p.name) is None:
            derived = find_derived_property(self.g, entity, p.name)
            if derived is not None:
                return self.derived_column(scope, alias, entity, derived)
        edits = None if find_property(entity, p.name) is not None else (
            overlay_properties(entity, self.overlay_edits).get(p.name.lower()))
        if not edits:
            return f"{alias}.{quote_ident(p.name)}"
        slot = ("overlay", alias, p.name.lower())
        ov = scope.join_alias.get(slot)
        if ov is None:
            b = entity.backing
            key = (b.primary_key if b is not None else "") or entity.identity_key
            if not key:
                raise ObjectQueryRefused(f"{entity.id} declares no key, so its overlay property '{p.name}' has "
                                         "nothing to join on")
            if len(edits) > _MAX_IN:
                raise ObjectQueryRefused(f"'{p.name}' on {entity.id} carries {len(edits)} accepted edits — more "
                                         f"than the {_MAX_IN} a read-time merge carries inline")
            ov = self._alias("ov")
            rows = " UNION ALL ".join(f"SELECT {_literal(str(e.row_key), p.name)} AS k, "
                                      f"{_literal(str(e.body), p.name)} AS v" for e in edits)
            scope.joins.append(f"LEFT JOIN ({rows}) AS {ov} "
                               f"ON CAST({alias}.{quote_ident(key)} AS VARCHAR) = {ov}.k")
            scope.join_alias[slot] = ov
            self.note_overlay(entity, p.name, edits)
        return f"CAST({ov}.v AS BOOLEAN)" if _is_bool(p) else f"{ov}.v"

    def expression_column(self, scope: _Scope, alias: str, entity: OntologyEntity, name: str, expression) -> str:
        """2026-09-22 — a property a person mapped to an expression: refused while unverified — a wrong expression
        must not become a silent column — and read through `formula_column`."""
        if expression.verified is not True:
            raise ObjectQueryRefused(f"{entity.id}.{name} is an expression that did not bind: "
                                     f"{expression.note or 'not yet verified'}")
        self.plan.append(f"{entity.id}.{name}: = {expression.expression} (an expression property)")
        return self.formula_column(scope, alias, entity, name, expression.expression, what=f"{entity.id}.{name}")

    def formula_column(self, scope: _Scope, alias: str, entity: OntologyEntity, name: str, formula: str, *,
                       what: str) -> str:
        """PENDING item 27 — a per-row formula, every name in it read by the compiler's own path law (`column_at`):
        the type's own column, a property a binding supplies (a linked table, joined on the object's key), another
        formula, or a property through to-one links (`customer.tier`). It read the backing's own columns only, so a
        formula could not use a type's linked tables. A formula that reaches itself is refused, never looped."""
        from sqlglot import exp
        slot = (entity.id, name.lower())
        if slot in self._open_formulas:
            chain = " → ".join(f"{e}.{n}" for e, n in self._open_formulas[self._open_formulas.index(slot):] + [slot])
            raise ObjectQueryRefused(f"{what} reaches itself ({chain}) — a formula cannot be defined by itself")
        node = _row_formula(formula, self.dialect, what=what)
        self._open_formulas.append(slot)
        try:
            def read(column):
                if not isinstance(column, exp.Column):
                    return column
                path = ".".join(part.name for part in column.parts)
                sql, _, _ = self.column_at(scope, entity, alias, path, what)
                return exp.maybe_parse(sql, dialect=self.dialect)
            return f"({node.transform(read).sql(dialect=self.dialect)})"
        finally:
            self._open_formulas.pop()

    def derived_column(self, scope: _Scope, alias: str, entity: OntologyEntity, d) -> str:
        """ON-9 — a derived lag: the calendar days between two of the object's moments, each read under the compiler's
        own path law (to-one links only), so a moment on a linked object is joined once. Both moments are cast to DATE
        first, so "days" means calendar days on every dialect. Refused while the process it comes from is unmeasured or
        measured false."""
        if not d.usable:
            raise ObjectQueryRefused(f"{entity.id}.{d.name} is derived from {d.source}, which {d.why_not}")
        slot = (entity.id, d.name.lower())
        if slot in self._deriving:
            raise ObjectQueryRefused(f"{entity.id}.{d.name} is derived from itself — its moments must be properties "
                                     "the data holds")
        self._deriving.add(slot)
        try:
            start, sp, _ = self.column_at(scope, entity, alias, d.start, f"derived {d.name}")
            end, ep, _ = self.column_at(scope, entity, alias, d.end, f"derived {d.name}")
        finally:
            self._deriving.discard(slot)
        for path, q in ((d.start, sp), (d.end, ep)):
            if not _is_temporal(q):
                raise ObjectQueryRefused(f"{entity.id}.{d.name} counts {d.unit} to '{path}', which is not a date or "
                                         f"timestamp ({q.data_type or q.semantic_type or 'untyped'})")
        if slot not in self._derived_noted:
            self._derived_noted.add(slot)
            self.plan.append(f"derived property {d.name} on {entity.id}: {d.description} — from {d.source}, measured")
        if d.unit == "hours":
            # the hours that pass between the two moments, to the second — never the hour boundaries they cross
            return f"DATE_DIFF('second', CAST({start} AS TIMESTAMP), CAST({end} AS TIMESTAMP)) / 3600.0"
        return f"DATE_DIFF('day', CAST({start} AS DATE), CAST({end} AS DATE))"

    def binding_column(self, scope: _Scope, alias: str, entity: OntologyEntity, binding: Binding,
                       p: EntityProperty) -> str:
        """ON-1b — a property a further binding supplies: the binding LEFT JOINed once per object alias on the
        object's key. The join is taken only for a binding measured one row per object, so it can neither multiply
        nor drop an object; any other binding is a refusal naming why. ON-5 — a TIMESERIES binding is joined
        through its latest-row reduction, which is one row per object again."""
        frame = (binding.frames or {}).get(p.name)
        if frame is not None:
            self.frame_check(entity, binding, p.name, frame)
        problem = binding_problem(entity, binding)
        if problem:
            raise ObjectQueryRefused(f"{entity.id}.{p.name} is read from the binding {binding.name}, which the compiler "
                                     f"does not join: {problem}")
        if alias in self.far_paths:
            return self.far_binding_column(scope, alias, entity, binding, p)
        source = binding_source(self.g, entity, binding)
        if source != self.at(scope):
            return self.far_binding(scope, alias, entity, binding, p, source)
        slot = ("binding", alias, binding.name)
        joined = scope.join_alias.get(slot)
        if joined is None:
            b = entity.backing
            key = (b.primary_key if b is not None else "") or entity.identity_key
            joined = self._alias("b")
            source = self.binding_rows(binding, joined)
            if not source:
                raise ObjectQueryRefused(f"{entity.id}.{p.name} is read from the binding {binding.name}, which names "
                                         "no source to read it from")
            scope.joins.append(f"LEFT JOIN {source} "
                               f"ON {alias}.{quote_ident(key)} = {joined}.{quote_ident(binding.key)}")
            scope.join_alias[slot] = joined
            self.note_binding(entity, binding, key)
        return f"{joined}.{quote_ident(column_of(binding, p.name))}"

    @staticmethod
    def binding_rows(binding: Binding, alias: str) -> str:
        """The aliased FROM fragment a binding is joined through, one row per object: its latest row for a timeseries
        binding, its rollups for a detail binding, its rows as they stand for a static one."""
        return (latest_from(binding, alias) if binding.kind == "timeseries"
                else detail_from(binding, alias) if binding.kind == "detail"
                else binding_from(binding, alias))

    def object_key(self, entity: OntologyEntity) -> str:
        """The column that holds an object's key — what every binding joins on."""
        b = entity.backing
        return (b.primary_key if b is not None else "") or entity.identity_key

    def readings_binding(self, entity: OntologyEntity, name: str) -> Optional[Binding]:
        """ON-5 — the timeseries binding ``name`` names on ``entity``, whose READINGS a path reaches as a set
        (`price_history.price_eur`), as against the bare property name, which is the object's LATEST value.
        None when nothing of that name binds here. A name that is both a link and a binding is refused rather
        than resolved one way in silence."""
        low = (name or "").strip().lower()
        binding = next((b for b in entity.bindings or [] if b.name.lower() == low), None)
        if binding is None:
            return None
        if self._link_hop(entity, low) is not None:
            raise ObjectQueryRefused(f"'{name}' names both a link and a binding on {entity.id} — the compiler "
                                     "will not guess which one a path means; rename one of them")
        if binding.kind == "detail":
            if self._part_hop(entity, low) is not None:
                return None                     # its rows are a type's: the path walks the link to them (`hop`)
            supplied = ", ".join(sorted(binding.properties)) or "none"
            raise ObjectQueryRefused(f"{binding.name} on {entity.id} is a detail binding — many rows per object — "
                                     f"read at the object's grain through its rollups ({supplied}); the rows "
                                     f"themselves are reached at their own grain through the link to their type",
                                     sorted(binding.properties))
        if binding.kind != "timeseries":
            supplied = ", ".join(sorted(binding.properties)) or "none"
            raise ObjectQueryRefused(f"{binding.name} on {entity.id} is a static binding — one row per object — "
                                     f"so what it supplies is read by its own name ({supplied}), not through "
                                     f"'{name}.'", sorted(binding.properties))
        problem = binding_problem(entity, binding)
        if problem:
            raise ObjectQueryRefused(f"the readings of {binding.name} on {entity.id} cannot be read: {problem}")
        if not self.object_key(entity):
            raise ObjectQueryRefused(f"{entity.id} declares no key, so its {binding.name} readings have nothing "
                                     "to hang off")
        return binding

    def readings_property(self, binding: Binding, name: str, path: str) -> EntityProperty:
        """One column of a reading. A reading has no links of its own, so this is a single name."""
        segs = _split(name, "reading")
        supplied = sorted(binding.properties)
        if len(segs) > 1:
            raise ObjectQueryRefused(f"a reading of {binding.name} has no links — '{path}' must name one of its "
                                     f"columns{_did_you_mean(segs[0], supplied)}", supplied)
        low = segs[0].lower()
        found = next((p for k, p in binding.properties.items() if k.lower() == low), None)
        if found is None:
            raise ObjectQueryRefused(f"{binding.name} supplies no '{segs[0]}' (in '{path}')"
                                     f"{_did_you_mean(low, supplied)}", supplied)
        return found

    def readings_condition(self, alias: str, binding: Binding, f: ObjectFilter) -> str:
        p = self.readings_property(binding, f.path, f.path)
        return _predicate(f"{alias}.{quote_ident(column_of(binding, p.name))}", p, f)

    def readings_exists(self, scope: _Scope, binding: Binding, rest: str, f: ObjectFilter) -> str:
        """ON-5 — a condition on the READINGS keeps the objects with at least one reading that matches it. The
        set is filtered, never multiplied, exactly as a to-many link's condition is."""
        key = self.object_key(scope.entity)
        inner = self._alias("e")
        source = binding_source(self.g, scope.entity, binding)
        across = source != self.at(scope)
        if across and scope is not self.top:
            raise ObjectQueryRefused(f"the readings of {binding.name} on {scope.entity.id} live on another connection "
                                     f"({source}) and are tested from inside a pre-aggregated link or an EXISTS — "
                                     f"readings are read by key from the query's own level; anchor the query on "
                                     f"{scope.entity.id}")
        conds = [] if across else [f"{inner}.{quote_ident(binding.key)} = {scope.alias}.{quote_ident(key)}"]
        negate = False
        if rest:
            conds.append(self.readings_condition(inner, binding,
                                                 ObjectFilter(path=rest, op=f.op, value=f.value, values=f.values)))
        elif f.op in ("exists", "not_exists"):
            negate = f.op == "not_exists"
        else:
            raise ObjectQueryRefused(f"'{binding.name}' is a set of readings — name one of its columns "
                                     f"('{binding.name}.<column>'), or ask whether any reading exists at all "
                                     "with op 'exists' / 'not_exists'")
        self.note_readings(scope.entity, binding, "anti-join" if negate else "semi-join",
                           f"readings of {binding.name} on {scope.entity.id}: "
                           f"{'NOT EXISTS' if negate else 'EXISTS'} over {binding.table or 'a keyed SELECT'} — "
                           f"keeps {scope.entity.id} objects {'without' if negate else 'with'} a matching "
                           "reading; the set is filtered, never multiplied")
        if across:
            alias = self._alias("x")
            where = f" WHERE {' AND '.join(conds)}" if conds else ""
            read = KeyedRead(alias=alias, kind="exists", connection_id=source, table=None, sql=None, key="k",
                             local=f"{scope.alias}.{quote_ident(key)}", target=scope.entity.id,
                             label=f"readings of {binding.name} on {scope.entity.id}",
                             base=(f"(SELECT DISTINCT {inner}.{quote_ident(binding.key)} AS k, 1 AS __present "
                                   f"FROM {binding_from(binding, inner)}{where}) AS __r"))
            read.need("__present")
            self.far[alias] = read
            self.far_paths[alias] = (read, "__r")
            scope.joins.append(f"LEFT JOIN __far_{alias} AS {alias} ON {scope.alias}.{quote_ident(key)} = {alias}.k")
            self.plan.append(f"readings of {binding.name} on {scope.entity.id}: cross-source — the {binding.key} values "
                             f"with a matching reading on {source} are read by key, one row per key")
            return f"{alias}.__present IS {'NULL' if negate else 'NOT NULL'}"
        sql = f"EXISTS (SELECT 1 FROM {binding_from(binding, inner)} WHERE {' AND '.join(conds)})"
        return f"NOT {sql}" if negate else sql

    def readings_measure(self, scope: _Scope, binding: Binding, rest: str, t: MeasureTerm, label: str) -> str:
        """ON-5 — an aggregate over a timeseries binding's READINGS: computed per object over its own rows,
        then rolled up over the object set by the same law a to-many link's measure rolls up by. The bare
        property is the object's LATEST value (`latest_from`); this is its history."""
        if t.agg == "count_distinct":
            raise ObjectQueryRefused(f"{label}: count_distinct over the readings of {binding.name} does not add "
                                     f"up over {scope.entity.id} objects (one value can sit under two of them)")
        source = binding_source(self.g, scope.entity, binding)
        if source != self.at(scope) and scope is not self.top:
            raise ObjectQueryRefused(f"{label}: the readings of {binding.name} on {scope.entity.id} live on another "
                                     f"connection ({source}) and are aggregated from inside a pre-aggregated link or an "
                                     f"EXISTS — readings are read by key from the query's own level; anchor the query "
                                     f"on {scope.entity.id}")
        slot = (scope.alias, binding.name)
        r = self._readings.get(slot)
        if r is None:
            r = _Readings(binding=binding, entity_key=self.object_key(scope.entity), outer_alias=scope.alias,
                          alias=self._alias("r"), inner_alias=self._alias("s"), source=source,
                          far=source != self.at(scope))
            self._readings[slot] = r
            self.note_readings(scope.entity, binding, "pre-aggregated",
                               f"readings of {binding.name} on {scope.entity.id}: "
                               f"{binding.table or 'a keyed SELECT'} aggregated per {binding.key} BEFORE the "
                               f"join — many rows per {scope.entity.id} over {binding.time_column}, so each "
                               f"{scope.entity.id} meets at most one aggregate row")
        cond = " AND ".join(f"({self.readings_condition(r.inner_alias, binding, w)})" for w in t.where)
        if not rest:
            if t.agg != "count":
                raise ObjectQueryRefused(f"{label}: {t.agg} over the readings of {binding.name} needs one of its "
                                         f"columns ('{binding.name}.<column>')")
            out = _rollup("count", r.alias, r.column, None, cond)
            self.plan.append(f"{label}: readings of {binding.name} counted per {scope.entity.id}, then summed"
                             + (" (its where applied to the readings)" if cond else ""))
            return out
        p = self.readings_property(binding, rest, t.path)
        if t.agg == "sum":
            self.readings_semiadditive_check(scope, binding, p.name, t.where, label)
        _check_aggregate(t.agg, p, t.path, self.caveats)
        value = f"{r.inner_alias}.{quote_ident(column_of(binding, p.name))}"
        if t.agg in ("sum", "avg") and _is_bool(p):
            value = f"CAST({value} AS INTEGER)"
        out = _rollup(t.agg, r.alias, r.column, value, cond)
        self.plan.append(f"{label}: {t.agg}({t.path}) over the readings of {binding.name}, per "
                         f"{scope.entity.id}, rolled up" + (" (a ratio of sums)" if t.agg == "avg" else "")
                         + (" — its where applied to the readings" if cond else ""))
        return out

    def readings_semiadditive_check(self, scope: _Scope, binding: Binding, name: str, where: list[ObjectFilter],
                                    label: str) -> None:
        """PENDING item 27 — a SUM over the READINGS of a reading at a moment (the history of a balance) adds it across
        moments: refused unless the measure's own where keeps one moment of the readings — their time column, or the
        declaration's `over`, `=` one value."""
        from aughor.ontology.semiadditive import declared_reading, one_value
        reading = declared_reading(self.g, scope.entity, name)
        if reading is None:
            return
        clock_col = (binding.time_column or "").lower()
        clock = {clock_col, reading.decl.over.lower()} | {
            k.lower() for k in binding.properties if column_of(binding, k).lower() == clock_col}
        if any(one_value(f) and f.path.strip().lower() in clock for f in where):
            self.plan.append(f"{label}: {reading.owner.id}.{reading.prop} is a reading at a moment — its readings of "
                             f"{binding.name} summed within one {binding.time_column} (the measure's where)")
            return
        raise ObjectQueryRefused(
            f"{label}: {reading.said(scope.entity, name)} a reading at a moment, taken over {reading.decl.over}"
            f"{reading.why()} — the readings of {binding.name} are many moments per {scope.entity.id} over "
            f"{binding.time_column}, so their sum counts the same quantity once per reading. Keep the measure's where "
            f"to one {binding.time_column}, take the readings' avg, min or max, or read {name} itself — its latest "
            "reading")

    def note_readings(self, entity: OntologyEntity, binding: Binding, treatment: str, line: str) -> None:
        key = (entity.id, binding.name, treatment)
        if key in self._bindings_noted:
            return
        self._bindings_noted.add(key)
        self.plan.append(line)
        self.bindings.append({"binding": binding.name, "object_type": entity.api_name, "kind": binding.kind,
                              "source": binding.table or "a keyed SELECT",
                              "on": f"{self.object_key(entity)} = {binding.key}", "rows": binding.rows,
                              "objects": binding.objects, "covered": binding.covered, "treatment": treatment,
                              "time_column": binding.time_column or None})

    def note_binding(self, entity: OntologyEntity, binding: Binding, key: str) -> None:
        if (entity.id, binding.name) in self._bindings_noted:
            return
        self._bindings_noted.add((entity.id, binding.name))
        source = binding.table or "a keyed SELECT"
        if binding.kind == "timeseries":
            self.plan.append(f"binding {binding.name} on {entity.id}: {source} joined on {key} = {binding.key}, "
                             f"{latest_note(binding)} — one row per {entity.id} by construction, so it cannot "
                             f"multiply {entity.id} rows ({binding.note})")
        elif binding.kind == "detail":
            self.plan.append(f"binding {binding.name} on {entity.id}: {source} joined on {key} = {binding.key}, "
                             f"{rollup_note(binding)} ({binding.note})")
        else:
            self.plan.append(f"binding {binding.name} on {entity.id}: {source} joined on {key} = {binding.key} — one "
                             f"row per {entity.id} by measurement ({binding.note}), so it cannot multiply "
                             f"{entity.id} rows")
        self.bindings.append({"binding": binding.name, "object_type": entity.api_name, "kind": binding.kind,
                              "source": source, "on": f"{key} = {binding.key}", "rows": binding.rows,
                              "objects": binding.objects, "covered": binding.covered,
                              "treatment": ("latest" if binding.kind == "timeseries"
                                            else "rolled up" if binding.kind == "detail" else "joined"),
                              "time_column": binding.time_column or None})

    def note_overlay(self, entity: OntologyEntity, name: str, edits: list) -> None:
        if (entity.id, name.lower()) in self._overlay_noted:
            return
        self._overlay_noted.add((entity.id, name.lower()))
        self.plan.append(f"overlay property {name} on {entity.id}: {len(edits)} accepted edit(s) merged at read "
                         "time, keyed on the object — the source is never written")
        for e in edits:
            self.overlay.append({"object_type": entity.api_name, "pk": e.row_key, "property": e.column,
                                 "value": e.body, "by": e.actor or e.source, "at": e.created_at,
                                 "note": e.note, "origin": e.origin, "provenance": e.provenance()})

    def hop(self, entity: OntologyEntity, seg: str) -> Optional[ObjectLink]:
        """A link by its name, its business name or the type it reaches — or, when none is, the link a detail
        binding's name stands for: the binding reads the rows of a type the object links to, so a path through the
        binding's name reaches those rows at their own grain, through that one link."""
        return self._link_hop(entity, seg) or self._part_hop(entity, seg)

    def _link_hop(self, entity: OntologyEntity, seg: str) -> Optional[ObjectLink]:
        hops = object_links(self.g, entity)
        low = seg.lower()
        # a link answers to its mechanical name and, beside it, to its business-verb name (ON-3b)
        named = [h for h in hops if low in (h.name.lower(), h.business.lower())]
        if len(named) > 1:
            raise ObjectQueryRefused(f"'{seg}' names {len(named)} links from {entity.id} "
                                     f"({', '.join(h.rel.id for h in named)}) — the ontology must tell them apart")
        if named:
            return named[0]
        reaching = [h for h in hops if low in (h.target.api_name.lower(), h.target.id.lower())]
        if len(reaching) > 1:
            names = [h.name for h in reaching]
            raise ObjectQueryRefused(f"{len(reaching)} links reach {reaching[0].target.id} from {entity.id} — "
                                     f"name one: {', '.join(names)}", names)
        return reaching[0] if reaching else None

    def _part_hop(self, entity: OntologyEntity, seg: str) -> Optional[ObjectLink]:
        """The one link from ``entity`` to the type whose own rows the detail binding named ``seg`` reads — None when
        no detail binding has that name, its source is no other type's table, or not exactly one link reaches it."""
        low = (seg or "").strip().lower()
        binding = next((b for b in entity.bindings or [] if b.kind == "detail" and b.name.lower() == low), None)
        table = (binding.table or "").rsplit(".", 1)[-1].lower() if binding is not None else ""
        if not table:
            return None
        owner = next((e for e in self.g.entities.values()
                      if e.id != entity.id and backing_table(e).lower() == table), None)
        if owner is None:
            return None
        reaching = [h for h in object_links(self.g, entity) if h.target.id == owner.id]
        if len(reaching) != 1:
            return None
        if ("part", entity.id, low) not in self._noted:
            self._noted.add(("part", entity.id, low))
            self.plan.append(f"'{seg}' on {entity.id} is a detail binding over {owner.id}'s rows — read at their own "
                             f"grain through the link {reaching[0].name}")
        return reaching[0]

    def need_hop(self, entity: OntologyEntity, seg: str, path: str) -> ObjectLink:
        h = self.hop(entity, seg)
        if h is None:
            links = sorted(x.name for x in object_links(self.g, entity))
            tail = (f" — its links: {', '.join(links)}" if links else f" — {entity.id} has no links in this ontology")
            raise ObjectQueryRefused(f"no link '{seg}' from {entity.id} (in '{path}'){tail}", links)
        problem = link_problem(h)
        if problem:
            raise ObjectQueryRefused(problem)
        return h

    def note_link(self, h: ObjectLink, treatment: str, line: str) -> None:
        key = (h.rel.id, h.name, treatment)
        if key in self._noted:
            return
        self._noted.add(key)
        self.links.append({"link": h.name, "from": h.source.id, "to": h.target.id, "cardinality": h.label,
                           "measured": True, "on": f"{h.local_col} = {h.remote_col}", "treatment": treatment})
        self.plan.append(line)

    # ── joins and columns ──
    def join_one(self, scope: _Scope, from_alias: str, h: ObjectLink) -> str:
        key = (from_alias, h.rel.id, h.name)
        if key in scope.join_alias:
            return scope.join_alias[key]
        if from_alias in self.far_paths:
            return self.far_hop(scope, from_alias, h)
        if entity_source(self.g, h.target) != self.at(scope):
            return self.far_link(scope, from_alias, h)
        alias = self._alias("j")
        scope.joins.append(f"LEFT JOIN {backing_from(h.target, alias)} "
                           f"ON {from_alias}.{quote_ident(h.local_col)} = {alias}.{quote_ident(h.remote_col)}")
        scope.join_alias[key] = alias
        self.note_link(h, "joined", f"link {h.describe()}: joined — to-one by measurement, so it cannot "
                                    f"multiply {h.source.id} rows")
        return alias

    # ── ON-8: sources on another connection, read by key ──
    def far_link(self, scope: _Scope, from_alias: str, h: ObjectLink) -> str:
        """ON-8 — a to-one link to a type on another connection. No statement joins two connections, so the type's
        rows are READ BY KEY — the distinct keys the query's own rows hold — through the batched-foreach engine, and
        joined beside them in the stage (`aughor.semantic.cross_source`). Only from the query's own FROM level, and
        only for the columns the type's backing holds."""
        source = entity_source(self.g, h.target)
        if scope is not self.top:
            raise ObjectQueryRefused(
                f"link {h.describe()} crosses to {h.target.id} on another connection ({source}) from inside a "
                f"pre-aggregated link or an EXISTS — a cross-source link is read by key from the query's own level; "
                f"anchor the query on {h.source.id}")
        b = h.target.backing
        table = (b.table if b is not None and b.kind == "table" else None) or ""
        if not table:
            raise ObjectQueryRefused(f"link {h.describe()} crosses to {h.target.id} on another connection ({source}), "
                                     "which is read through a keyed SELECT — a cross-source link reads a table")
        alias = self._alias("x")
        self.far[alias] = KeyedRead(alias=alias, kind="link", connection_id=source, table=table, sql=None,
                                    key=h.remote_col, local=f"{from_alias}.{quote_ident(h.local_col)}",
                                    label=f"link {h.name} ({h.source.id} → {h.target.id})", target=h.target.id)
        self.far_paths[alias] = (self.far[alias], "__r")
        scope.joins.append(f"LEFT JOIN __far_{alias} AS {alias} "
                           f"ON {from_alias}.{quote_ident(h.local_col)} = {alias}.{quote_ident(h.remote_col)}")
        scope.join_alias[(from_alias, h.rel.id, h.name)] = alias
        self.note_link(h, "read by key",
                       f"link {h.describe()}: cross-source — {h.target.id} lives on {source}, so its rows are read by "
                       f"key through the batched-foreach engine and joined beside the {h.source.id} rows; to-one by "
                       f"measurement, so it cannot multiply {h.source.id} rows")
        return alias

    def far_value(self, read: KeyedRead, inner: str, column: str) -> str:
        """O2 — the name the keyed read ``read`` returns ``inner``'s column under: the column itself for the read's own
        rows, a projection for a type or binding joined inside its statement."""
        if inner == "__r":
            read.need(column)
            return column
        return read.project(f"{inner}__{column}", f"{inner}.{quote_ident(column)}")

    def far_column(self, scope: _Scope, alias: str, entity: OntologyEntity, p: EntityProperty) -> str:
        """ON-8 — a property of a type this query reads by key from another connection: a column its backing holds, or
        (O2) one a binding of that type supplies."""
        read, inner = self.far_paths[alias]
        if p.name in (entity.expressions or {}) or find_computed(entity, p.name) is not None:
            # PENDING item 27 — a formula is minted into the type's properties by name, and was read here as a column
            # the other connection's table would hold; it holds none of that name
            raise ObjectQueryRefused(
                f"{entity.id}.{p.name} is a formula, and {entity.id} is read by key from another connection — a type "
                "read that way is read for its own columns and bindings; anchor the query on it to evaluate the formula")
        column = next((k for k in entity.properties or {} if k.lower() == p.name.lower()), None)
        if column is None:
            binding = property_binding(entity, p.name)
            if binding is not None:
                return self.binding_column(scope, alias, entity, binding, p)
            names = sorted(entity.properties or {})
            raise ObjectQueryRefused(
                f"{entity.id}.{p.name} is neither a column of {entity.id}'s backing nor one a binding of it supplies — "
                f"a type read by key from another connection is read for its own columns and bindings, not for what an "
                f"edit or a derivation supplies ({', '.join(names)[:200]})", names)
        return f"{read.alias}.{quote_ident(self.far_value(read, inner, column))}"

    def far_hop(self, scope: _Scope, from_alias: str, h: ObjectLink) -> str:
        """O2 — a to-one link followed past a type this query reads by key from another connection. A target on that
        same connection is joined inside the keyed read's own statement — to-one by measurement, so the read still
        returns one row per key. A target anywhere else is a second keyed read, keyed by the values the first one's
        rows hold."""
        read, inner = self.far_paths[from_alias]
        target_source = entity_source(self.g, h.target)
        slot = (from_alias, h.rel.id, h.name)
        if target_source == read.connection_id:
            joined = self._alias("__q")
            read.joins.append(f"LEFT JOIN {backing_from(h.target, joined)} "
                              f"ON {inner}.{quote_ident(h.local_col)} = {joined}.{quote_ident(h.remote_col)}")
            alias = self._alias("x")
            self.far_paths[alias] = (read, joined)
            scope.join_alias[slot] = alias
            self.note_link(h, "joined inside a keyed read",
                           f"link {h.describe()}: joined inside the keyed read of {read.target} on {read.connection_id} "
                           "— to-one by measurement, so that read still returns one row per key")
            return alias
        if scope is not self.top:
            raise ObjectQueryRefused(
                f"link {h.describe()} crosses to {h.target.id} on another connection ({target_source}) from inside a "
                f"pre-aggregated link or an EXISTS — a cross-source link is read by key from the query's own level; "
                f"anchor the query on {h.source.id}")
        b = h.target.backing
        table = (b.table if b is not None and b.kind == "table" else None) or ""
        if not table:
            raise ObjectQueryRefused(f"link {h.describe()} crosses to {h.target.id} on another connection "
                                     f"({target_source}), which is read through a keyed SELECT — a cross-source link "
                                     "reads a table")
        local = self.far_value(read, inner, h.local_col)
        alias = self._alias("x")
        child = KeyedRead(alias=alias, kind="link", connection_id=target_source, table=table, sql=None,
                          key=h.remote_col, local=local, via=read.alias, target=h.target.id,
                          label=f"link {h.name} ({h.source.id} → {h.target.id})")
        self.far[alias] = child
        self.far_paths[alias] = (child, "__r")
        scope.joins.append(f"LEFT JOIN __far_{alias} AS {alias} "
                           f"ON {read.alias}.{quote_ident(local)} = {alias}.{quote_ident(h.remote_col)}")
        scope.join_alias[slot] = alias
        self.note_link(h, "read by key",
                       f"link {h.describe()}: cross-source — {h.target.id} lives on {target_source}, so its rows are read "
                       f"by key from the {h.local_col} values the keyed read of {read.target} on {read.connection_id} "
                       "returns; to-one by measurement, so it cannot multiply those rows")
        return alias

    def far_binding(self, scope: _Scope, alias: str, entity: OntologyEntity, binding: Binding, p: EntityProperty,
                    source: str) -> str:
        """ON-8 — a property a binding reads from another connection: the binding is READ BY KEY — the objects' own
        keys — and joined beside them in the stage. One row per object by measurement, so only a static binding, and
        only from the query's own FROM level."""
        if scope is not self.top:
            raise ObjectQueryRefused(
                f"{entity.id}.{p.name} is read from the binding {binding.name} on another connection ({source}) from "
                "inside a pre-aggregated link or an EXISTS — a cross-source binding is read from the query's own level")
        slot = ("binding", alias, binding.name)
        joined = scope.join_alias.get(slot)
        if joined is None:
            key = self.object_key(entity)
            joined = self._alias("x")
            self.far[joined] = KeyedRead(alias=joined, kind="binding", connection_id=source, table=binding.table,
                                         sql=binding.sql, key=binding.key, local=f"{alias}.{quote_ident(key)}",
                                         label=f"binding {binding.name} on {entity.id}", target=entity.id,
                                         base=self.binding_base(binding))
            scope.joins.append(f"LEFT JOIN __far_{joined} AS {joined} "
                               f"ON {alias}.{quote_ident(key)} = {joined}.{quote_ident(binding.key)}")
            scope.join_alias[slot] = joined
            if (entity.id, binding.name) not in self._bindings_noted:
                self._bindings_noted.add((entity.id, binding.name))
                read = binding.table or "a keyed SELECT"
                self.plan.append(f"binding {binding.name} on {entity.id}: cross-source — {read} lives on {source}, so "
                                 f"it is read by key ({key} = {binding.key}) through the batched-foreach engine; one row "
                                 f"per {entity.id} by measurement ({binding.note}), so it cannot multiply "
                                 f"{entity.id} rows")
                self.bindings.append({"binding": binding.name, "object_type": entity.api_name, "kind": binding.kind,
                                      "source": read, "connection_id": source, "on": f"{key} = {binding.key}",
                                      "rows": binding.rows, "objects": binding.objects, "covered": binding.covered,
                                      "treatment": "read by key", "time_column": None})
        column = column_of(binding, p.name)
        self.far[joined].need(column)
        return f"{joined}.{quote_ident(column)}"

    def binding_base(self, binding: Binding) -> str:
        """O3 — the one-row-per-object FROM fragment a binding read by key reads through: its latest row per key for a
        timeseries binding, its rollups per key for a detail binding; "" for a static one, read as it stands."""
        return "" if binding.kind == "static" else self.binding_rows(binding, "__r")

    def far_binding_column(self, scope: _Scope, alias: str, entity: OntologyEntity, binding: Binding,
                           p: EntityProperty) -> str:
        """O2 — a property a binding supplies to a type this query reads by key from another connection. A binding on
        that same connection is joined inside the keyed read's statement, one row per object by measurement; a binding
        anywhere else is a second keyed read, keyed by the object keys the first one returns."""
        read, inner = self.far_paths[alias]
        source = binding_source(self.g, entity, binding)
        column = column_of(binding, p.name)
        key = self.object_key(entity)
        if source == read.connection_id:
            slot = (alias, binding.name)
            joined = self._far_joined.get(slot)
            if joined is None:
                joined = self._alias("__q")
                read.joins.append(f"LEFT JOIN {self.binding_rows(binding, joined)} "
                                  f"ON {inner}.{quote_ident(key)} = {joined}.{quote_ident(binding.key)}")
                self._far_joined[slot] = joined
                self.plan.append(f"binding {binding.name} on {entity.id}: joined inside the keyed read of {read.target} "
                                 f"on {read.connection_id} ({key} = {binding.key}) — one row per {entity.id} by "
                                 f"measurement ({binding.note})")
            name = read.project(f"{joined}__{column}", f"{joined}.{quote_ident(column)}")
            return f"{read.alias}.{quote_ident(name)}"
        if scope is not self.top:
            raise ObjectQueryRefused(
                f"{entity.id}.{p.name} is read from the binding {binding.name} on another connection ({source}) from "
                "inside a pre-aggregated link or an EXISTS — a cross-source binding is read from the query's own level")
        slot = (alias, binding.name, "read")
        child = self._far_joined.get(slot)
        if child is None:
            local = self.far_value(read, inner, key)
            child = self._alias("x")
            self.far[child] = KeyedRead(alias=child, kind="binding", connection_id=source, table=binding.table,
                                        sql=binding.sql, key=binding.key, local=local, via=read.alias,
                                        base=self.binding_base(binding), target=entity.id,
                                        label=f"binding {binding.name} on {entity.id}")
            scope.joins.append(f"LEFT JOIN __far_{child} AS {child} "
                               f"ON {read.alias}.{quote_ident(local)} = {child}.{quote_ident(binding.key)}")
            self._far_joined[slot] = child
            self.plan.append(f"binding {binding.name} on {entity.id}: cross-source — read by key on {source} from the "
                             f"{key} values the keyed read of {read.target} on {read.connection_id} returns; one row per "
                             f"{entity.id} by measurement ({binding.note})")
        self.far[child].need(column)
        return f"{child}.{quote_ident(column)}"

    def column(self, scope: _Scope, path: str, purpose: str) -> tuple[str, EntityProperty, list[ObjectLink]]:
        """A property reached through to-one links only."""
        return self.column_at(scope, scope.entity, scope.alias, path, purpose)

    def column_at(self, scope: _Scope, entity: OntologyEntity, alias: str, path: str,
                  purpose: str) -> tuple[str, EntityProperty, list[ObjectLink]]:
        """A property reached through to-one links only, starting from ``entity`` under ``alias`` — the anchor, or an
        object the query already joined (ON-9: a derived property's moments are read from the object that carries it).
        The joins land on ``scope``."""
        segs = _split(path, purpose)
        start, hops = entity, []
        for seg in segs[:-1]:
            h = self.need_hop(entity, seg, path)
            if not h.to_one:
                raise ObjectQueryRefused(
                    f"{purpose} '{path}' crosses {h.describe()}, a to-many link — it would repeat each "
                    f"{start.id} once per {h.target.id}. A to-many link belongs in a measure "
                    "(pre-aggregated) or a filter (exists).")
            alias = self.join_one(scope, alias, h)
            entity = h.target
            hops.append(h)
        p = self.prop(entity, segs[-1], path)
        return self.colref(scope, alias, entity, p), p, hops

    # ── conditions ──
    def condition(self, scope: _Scope, f: ObjectFilter) -> str:
        segs = _split(f.path, "filter")
        entity, alias = scope.entity, scope.alias
        if f.value_path and f.op not in _COMPARE:
            raise ObjectQueryRefused(f"filter '{f.path} {f.op}' compares with another property ('{f.value_path}') — "
                                     "that takes =, !=, >, >=, < or <=")
        # ON-5 — the first segment may name a timeseries binding, and then the path is about its READINGS
        # rather than about a link or a property of the object. Readings hang off the object they bind to, so
        # only here, at the anchor.
        readings = self.readings_binding(entity, segs[0])
        if readings is not None:
            if f.value_path:
                raise ObjectQueryRefused(f"filter '{f.path} {f.op} {f.value_path}': two properties are compared at the "
                                         f"object's own grain, never over the readings of {readings.name}")
            return self.readings_exists(scope, readings, ".".join(segs[1:]), f)
        wants_link = f.op in ("exists", "not_exists")
        for i, seg in enumerate(segs):
            last = i == len(segs) - 1
            if last and not wants_link:
                p = self.prop(entity, seg, f.path)
                left = self.colref(scope, alias, entity, p)
                return self.comparison(scope, left, p, f) if f.value_path else _predicate(left, p, f)
            h = self.need_hop(entity, seg, f.path)
            if h.to_one and not (last and wants_link):
                alias = self.join_one(scope, alias, h)
                entity = h.target
                continue
            if f.value_path:
                raise ObjectQueryRefused(
                    f"filter '{f.path} {f.op} {f.value_path}' crosses {h.describe()}, a to-many link — two properties "
                    f"are compared at the object's own grain; anchor the query on {h.target.id} and reach "
                    f"{h.source.id} through its link")
            return self.exists(scope, alias, h, ".".join(segs[i + 1:]), f)
        raise ObjectQueryRefused(f"filter path '{f.path}' did not resolve")

    def exists(self, scope: _Scope, outer_alias: str, h: ObjectLink, rest: str, f: ObjectFilter) -> str:
        target_source = entity_source(self.g, h.target)
        if outer_alias in self.far_paths or (target_source != self.at(scope) and scope is not self.top):
            raise ObjectQueryRefused(
                f"a condition through {h.describe()} would test rows on another connection from inside a type read by "
                "key, a pre-aggregated link or an EXISTS — a keyed EXISTS is read from the query's own level; anchor the "
                f"query on {h.source.id}")
        if target_source != self.at(scope):
            return self.far_exists(scope, outer_alias, h, rest, f, target_source)
        inner = _Scope(entity=h.target, alias=self._alias("e"), source=scope.source)
        conds = [f"{inner.alias}.{quote_ident(h.remote_col)} = {outer_alias}.{quote_ident(h.local_col)}"]
        negate = False
        if rest:
            conds.append(self.condition(inner, ObjectFilter(path=rest, op=f.op, value=f.value, values=f.values)))
        else:
            negate = f.op == "not_exists"
        joins = "".join(f" {j}" for j in inner.joins)
        treatment = "anti-join" if negate else "semi-join"
        self.note_link(h, treatment, f"link {h.describe()}: {'NOT EXISTS' if negate else 'EXISTS'} — keeps "
                                     f"{h.source.id} objects {'without' if negate else 'with'} a matching "
                                     f"{h.target.id}; the set is filtered, never multiplied")
        sql = f"EXISTS (SELECT 1 FROM {backing_from(h.target, inner.alias)}{joins} WHERE {' AND '.join(conds)})"
        return f"NOT {sql}" if negate else sql

    def far_exists(self, scope: _Scope, outer_alias: str, h: ObjectLink, rest: str, f: ObjectFilter,
                   source: str) -> str:
        """O3 — a condition through a to-many link to a type on another connection. The keys there with a matching row
        are read by key, one row per key, and tested beside the query's rows: the set is filtered, never multiplied,
        exactly as an EXISTS filters it."""
        inner = _Scope(entity=h.target, alias=self._alias("e"), source=source)
        conds: list[str] = []
        negate = False
        if rest:
            conds.append(self.condition(inner, ObjectFilter(path=rest, op=f.op, value=f.value, values=f.values)))
        else:
            negate = f.op == "not_exists"
        joins = "".join(f" {j}" for j in inner.joins)
        where = f" WHERE {' AND '.join(conds)}" if conds else ""
        alias = self._alias("x")
        read = KeyedRead(alias=alias, kind="exists", connection_id=source, table=None, sql=None, key=h.remote_col,
                         local=f"{outer_alias}.{quote_ident(h.local_col)}", target=h.target.id,
                         label=f"link {h.name} ({h.source.id} → {h.target.id})",
                         base=(f"(SELECT DISTINCT {inner.alias}.{quote_ident(h.remote_col)} AS {quote_ident(h.remote_col)}, "
                               f"1 AS __present FROM {backing_from(h.target, inner.alias)}{joins}{where}) AS __r"))
        read.need("__present")
        self.far[alias] = read
        self.far_paths[alias] = (read, "__r")
        scope.joins.append(f"LEFT JOIN __far_{alias} AS {alias} "
                           f"ON {outer_alias}.{quote_ident(h.local_col)} = {alias}.{quote_ident(h.remote_col)}")
        self.note_link(h, "anti-join, read by key" if negate else "semi-join, read by key",
                       f"link {h.describe()}: cross-source {'NOT EXISTS' if negate else 'EXISTS'} — the {h.remote_col} "
                       f"values with a matching {h.target.id} on {source} are read by key, one row per key, and keep "
                       f"{h.source.id} objects {'without' if negate else 'with'} one; the set is filtered, never "
                       "multiplied")
        return f"{alias}.__present IS {'NULL' if negate else 'NOT NULL'}"

    def where(self, scope: _Scope, filters: list[ObjectFilter]) -> str:
        return " AND ".join(f"({self.condition(scope, f)})" for f in filters)

    def comparison(self, scope: _Scope, left: str, p: EntityProperty, f: ObjectFilter) -> str:
        """ON-9 — one property compared with another of the same object: the right side is a path from the filter's
        own object, through to-one links only, of the same kind of value (two moments, two numbers, two texts)."""
        if f.value is not None or f.values:
            raise ObjectQueryRefused(f"filter '{f.path} {f.op}' names a value AND value_path '{f.value_path}' — name one")
        right, q, _ = self.column(scope, f.value_path, "comparison")
        if _family(p) != _family(q):
            raise ObjectQueryRefused(f"filter '{f.path} {f.op} {f.value_path}' compares a {_family(p)} with a "
                                     f"{_family(q)}")
        return f"{left} {_COMPARE[f.op]} {right}"

    def segment(self, scope: _Scope, name: str) -> str:
        segs = scope.entity.segments or {}
        low = name.strip().lower()
        seg = next((s for k, s in segs.items() if low in (k.lower(), (s.display_name or "").lower())), None)
        verified = sorted(k for k, s in segs.items() if s.verified)
        if seg is None:
            derived = find_derived_segment(self.g, scope.entity, name)
            if derived is not None:
                return self.derived_segment(scope, derived)
            verified += sorted(d.name for d in derived_for(self.g, scope.entity).segments if d.usable)
            raise ObjectQueryRefused(f"{scope.entity.id} has no segment '{name}'{_did_you_mean(low, verified)}", verified)
        if not seg.verified:
            raise ObjectQueryRefused(f"segment '{seg.id}' on {scope.entity.id} is not verified "
                                     f"({seg.verification_note or 'no note'}) — the compiler filters only by "
                                     "verified segments", verified)
        if not (seg.filter_sql or "").strip():
            self.plan.append(f"segment {seg.id} (verified): every {scope.entity.id}")
            return ""
        self.plan.append(f"segment {seg.id} (verified): {seg.filter_sql}")
        return _qualify(seg.filter_sql, scope.alias, self.dialect, what=f"segment {seg.id}")

    # ── measures ──
    def metric(self, scope: _Scope, name: str) -> str:
        low = name.strip().lower()
        m = next((m for mid, m in self.g.metrics.items()
                  if low in (mid.lower(), m.id.lower(), (m.display_name or "").lower())), None)
        mine = sorted(mid for mid, x in self.g.metrics.items() if x.verified and metric_on(x, scope.entity))
        if m is None:
            derived = find_derived_metric(self.g, scope.entity, name)
            if derived is not None:
                return self.derived_metric(scope, derived)
            mine += sorted(d.name for d in derived_for(self.g, scope.entity).metrics if d.usable)
            raise ObjectQueryRefused(f"no metric '{name}' on {scope.entity.id}{_did_you_mean(low, mine)}", mine)
        if not m.verified:
            raise ObjectQueryRefused(f"metric '{m.id}' is not verified ({m.verification_note or 'no note'}) — "
                                     "the compiler measures only with verified formulas", mine)
        if not metric_on(m, scope.entity):
            raise ObjectQueryRefused(f"metric '{m.id}' is defined on {m.entity or ', '.join(m.tables)}, not "
                                     f"{scope.entity.id} — anchor the query on its object type", mine)
        formula = _qualify(m.formula_sql, scope.alias, self.dialect, what=f"metric {m.id}", expression=True)
        self.semiadditive_formula_check(scope, m.formula_sql, f"metric {m.id}")
        # ON-9 — a verified rule on this type that scopes the metric restricts every aggregate its formula holds
        scoping = [r for _, r in sorted((self.g.rules or {}).items())
                   if r.verified is True and r.entity == scope.entity.id and m.id in (r.scopes or [])]
        if not scoping:
            self.plan.append(f"metric {m.id} (verified): {m.formula_sql}")
            return formula
        from aughor.ontology.derived import rule_filters
        try:
            filters = [ObjectFilter.model_validate(f) for r in scoping for f in rule_filters(r)]
        except ValidationError as exc:
            raise ObjectQueryRefused(f"metric '{m.id}' is scoped by a rule whose filters are malformed "
                                     f"({exc.errors()[0]['msg']})") from exc
        self.plan.append(f"metric {m.id} (verified), within {', '.join(r.id for r in scoping)}: {m.formula_sql}")
        return _within(formula, self.where(scope, filters))

    def _derived_filters(self, d, filters, what: str) -> list[ObjectFilter]:
        try:
            return [ObjectFilter.model_validate(f) for f in filters]
        except ValidationError as exc:
            raise ObjectQueryRefused(f"{what} '{d.name}' is derived from {d.source}, whose filters are malformed "
                                     f"({exc.errors()[0]['msg']})") from exc

    def derived_segment(self, scope: _Scope, d) -> str:
        """ON-9 — a segment a declared promise or rule derives: its filters, in the door's own shape, compiled under
        the door's own laws. Refused while the declaration is unmeasured or measured false."""
        if not d.usable:
            raise ObjectQueryRefused(f"segment '{d.name}' on {scope.entity.id} is derived from {d.source}, which "
                                     f"{d.why_not}")
        self.plan.append(f"segment {d.name} (derived from {d.source}, measured): {d.description}")
        self.caveats.extend(c for c in d.caveats if c not in self.caveats)
        return self.where(scope, self._derived_filters(d, d.filters, "segment"))

    def derived_metric(self, scope: _Scope, d) -> str:
        """ON-9 — the rate a declared promise derives: the objects that broke it over the objects that reached the
        stage with it in force, each counted over the object set by the door's own law — a ratio of two counts, never
        an average of per-object flags."""
        if not d.usable:
            raise ObjectQueryRefused(f"metric '{d.name}' on {scope.entity.id} is derived from {d.source}, which "
                                     f"{d.why_not}")
        label = f"metric {d.name}"
        broke = self.term(scope, MeasureTerm(agg="count", where=self._derived_filters(d, d.breach, "metric")),
                          f"{label} (broke the promise)")
        reached = self.term(scope, MeasureTerm(agg="count", where=self._derived_filters(d, d.reached, "metric")),
                            f"{label} (reached the stage with the promise in force)")
        self.plan.append(f"{label} (derived from {d.source}, measured): {d.description} — a ratio of two counts")
        self.caveats.extend(c for c in d.caveats if c not in self.caveats)
        return f"1.0 * ({broke}) / NULLIF({reached}, 0)"

    def term(self, scope: _Scope, t: MeasureTerm, label: str) -> str:
        if t.metric:
            if t.path or t.where:
                raise ObjectQueryRefused(f"{label}: a named metric carries its own formula — drop `path` and "
                                         "`where`, or measure a property with `agg`")
            return self.metric(scope, t.metric)
        if not t.path:
            if t.agg != "count":
                raise ObjectQueryRefused(f"{label}: {t.agg} needs a property path")
            cond = self.where(scope, t.where)
            self.plan.append(f"{label}: count of {scope.entity.id} objects" + (" matching its where" if cond else ""))
            return _agg_sql("count", None, cond)
        segs = _split(t.path, "measure")
        entity, alias, hops = scope.entity, scope.alias, []
        readings = self.readings_binding(entity, segs[0])            # ON-5 — over its readings, not its latest
        if readings is not None:
            return self.readings_measure(scope, readings, ".".join(segs[1:]), t, label)
        for i, seg in enumerate(segs):
            last = i == len(segs) - 1
            if last:
                p = (find_property(entity, seg) or self.virtual_prop(entity, seg) or self.derived_prop(entity, seg)
                     or self.computed_prop(entity, seg))
                if p is not None:
                    return self.prop_measure(scope, alias, p, hops, t, label, entity=entity)
                if self.hop(entity, seg) is None:
                    self.prop(entity, seg, t.path)          # raises, naming what exists
            h = self.need_hop(entity, seg, t.path)
            if h.to_one:
                alias = self.join_one(scope, alias, h)
                if last:                                    # a to-one linked object: its key
                    key = find_property(h.target, h.remote_col) or EntityProperty(name=h.remote_col, semantic_type="key")
                    return self.prop_measure(scope, alias, key, hops + [h], t, label)
                entity = h.target
                hops.append(h)
                continue
            if hops:
                raise ObjectQueryRefused(
                    f"{label}: '{t.path}' reaches the to-many link {h.describe()} through a to-one link — its "
                    f"rows would repeat once per {scope.entity.id}; anchor the query on {entity.id} instead")
            return self.many_measure(scope, h, ".".join(segs[i + 1:]), t, label)
        raise ObjectQueryRefused(f"{label}: measure path '{t.path}' did not resolve")

    def semiadditive_check(self, scope: _Scope, entity: OntologyEntity, name: str, hops: list, label: str,
                           where: Optional[list[ObjectFilter]] = None) -> None:
        """PENDING item 27 — a SUM of a reading at a moment (a balance, a stock, a headcount — declared so, or a formula
        that reads one) is refused unless the query keeps it to ONE moment (`one_moment`) — and only on the type that
        declares it, never through a link, where the rows summed are readings from many moments. Summed across
        moments, the same quantity is counted once per reading."""
        from aughor.ontology.semiadditive import declared_reading
        reading = declared_reading(self.g, entity, name)
        if reading is None:
            return
        decl, owner = reading.decl, reading.owner
        if hops or reading.hops or scope is not self.top:
            raise ObjectQueryRefused(
                f"{label}: {reading.said(entity, name)} a reading at a moment, taken over {decl.over}{reading.why()} — "
                f"a sum of it through a link adds readings from many moments. Anchor the query on {owner.id} "
                f"(object_type '{owner.api_name}') and group by {decl.over}, or take its avg, min or max")
        latest = property_binding(owner, reading.prop)
        if latest is not None and latest.kind == "timeseries":
            # ON-5 reads a timeseries property as each object's LATEST reading — one moment per object already; it
            # is the readings behind it (`readings_semiadditive_check`) and a frame over them that span moments.
            self.plan.append(f"{label}: {owner.id}.{reading.prop} is a reading at a moment — each {owner.id}'s "
                             f"latest reading of {latest.name}, one per {owner.id}")
            return
        how = self.one_moment(decl.over, where or [])
        if not how:
            raise ObjectQueryRefused(
                f"{label}: {reading.said(entity, name)} a reading at a moment, taken over {decl.over}{reading.why()} — "
                f"summed across {decl.over} it counts the same quantity once per reading. Group by {decl.over}, filter "
                f"to one {decl.over}, divide by the count of distinct {decl.over}, or take its avg, min or max")
        self.plan.append(f"{label}: {owner.id}.{reading.prop} is a reading at a moment over {decl.over} — summed "
                         f"within one {decl.over} ({how})")

    def one_moment(self, over: str, where: list[ObjectFilter]) -> str:
        """How the query keeps a sum at the anchor to one moment of ``over`` — "" when it does not. Grouped by ``over``
        or by the anchor's key measured unique (one row per group); filtered — the query, or the measure's own
        `where` — to one value of either; a day or hour grain on ``over`` when it is a DATE; or the measure divided by
        the count of distinct ``over`` (an average per moment)."""
        top = self.top.entity
        want = over.strip().lower()
        b = top.backing
        key = self.object_key(top).lower() if (b.verified if b is not None else top.grain_verified) is True else ""

        def names(path: str) -> str:
            path = (path or "").strip()
            if not path or "." in path:
                return ""
            p = find_property(top, path)
            return (p.name if p is not None else path).lower()

        for path in self.q.by:
            if names(path) == want:
                return f"grouped by {over}"
            if key and names(path) == key:
                return f"grouped by {top.id}'s key {key}"
        from aughor.ontology.semiadditive import one_value
        for f in [*self.q.filters, *where]:
            if one_value(f) and names(f.path) == want:
                return f"filtered to one {over}"
            if one_value(f) and key and names(f.path) == key:
                return f"filtered to one {top.id}"
        if self.q.grain in ("day", "hour") and names(self.time_path) == want:
            p = find_property(top, over)
            dtype = ((p.data_type if p is not None else "") or "").upper()
            if "DATE" in dtype and "TIME" not in dtype:
                return f"a {self.q.grain} grain on the date {over}"
        if self._per_moment and names(self._per_moment) == want:
            return f"divided by the count of distinct {over} — an average per {over}"
        return ""

    def semiadditive_formula_check(self, scope: _Scope, formula: str, label: str) -> None:
        """A metric whose formula SUMs a reading at a moment is held to the same law as a sum measure — except the one
        shape that is itself an average per moment, `SUM(x) / COUNT(DISTINCT <over>)`."""
        if not scope.entity.semiadditive:
            return
        import sqlglot
        from sqlglot import exp

        from aughor.ontology.semiadditive import declared_reading
        from aughor.sql.semiadditive import per_moment
        try:
            node = sqlglot.parse_one(f"SELECT {formula} FROM _t", read=self.dialect)
        except Exception:  # noqa: BLE001 — `_qualify` already refused what cannot parse
            return
        for total in node.find_all(exp.Sum):
            for column in total.find_all(exp.Column):
                reading = declared_reading(self.g, scope.entity, column.name)
                if reading is not None and per_moment(total, reading.decl.over.lower(), exp):
                    self.plan.append(f"{label}: SUM({column.name}) / COUNT(DISTINCT {reading.decl.over}) — an "
                                     f"average per {reading.decl.over} of a reading at a moment")
                    continue
                self.semiadditive_check(scope, scope.entity, column.name, [], label)

    def frame_check(self, entity: OntologyEntity, binding: Binding, name: str, frame) -> None:
        """PENDING item 27 — a frame that SUMS the readings of a reading at a moment adds it across moments, whatever
        reads the frame: refused, naming the frame and the declaration. A frame over the current reading only, or
        one that reads a reading back (`offset`), is one moment."""
        if frame.offset or frame.agg != "sum" or frame.range == "current":
            return
        from aughor.ontology.semiadditive import declared_reading
        column = frame.column.lower()
        supplied = next((k for k in binding.properties
                         if k not in binding.frames and column_of(binding, k).lower() == column), frame.column)
        reading = declared_reading(self.g, entity, supplied)
        if reading is None:
            return
        raise ObjectQueryRefused(
            f"{entity.id}.{name} is {frame.describe()} — and {reading.said(entity, supplied)} a reading at a moment, "
            f"taken over {reading.decl.over}{reading.why()}, so that sum counts the same quantity once per reading. "
            f"Declare the frame an avg, min or max")

    def prop_measure(self, scope: _Scope, alias: str, p: EntityProperty, hops: list[ObjectLink],
                     t: MeasureTerm, label: str, entity: Optional[OntologyEntity] = None) -> str:
        if t.agg == "sum":
            self.semiadditive_check(scope, entity or (hops[-1].target if hops else scope.entity), p.name, hops, label,
                                    t.where)
        _check_aggregate(t.agg, p, t.path, self.caveats)
        # A 1:1 hop cannot repeat a value (both keys are unique); an N:1 hop repeats the one
        # side once per matching row, and that is what a SUM, AVG or COUNT would count.
        repeating = next((h for h in hops if h.label != "1:1"), None)
        if repeating is not None and t.agg in ("sum", "avg", "count"):
            one = hops[-1].target
            raise ObjectQueryRefused(
                f"{label}: {t.agg} over '{t.path}' would count each {one.id}'s value once per "
                f"{scope.entity.id} row ({repeating.describe()} is to-one from here) — that is the fan-out. "
                f"Anchor the query on {one.id} (object_type '{one.api_name}') and reach {scope.entity.id} "
                "through its link, or use count_distinct / min / max, which repetition cannot change.")
        cond = self.where(scope, t.where)
        if entity is not None:
            value = self.colref(scope, alias, entity, p)
        elif alias in self.far_paths:
            read, inner = self.far_paths[alias]            # ON-8 — a linked object's key, read by key; O2 — at any depth
            value = f"{read.alias}.{quote_ident(self.far_value(read, inner, p.name))}"
        else:
            value = f"{alias}.{quote_ident(p.name)}"
        if t.agg in ("sum", "avg") and _is_bool(p):
            value = f"CAST({value} AS INTEGER)"
        self.plan.append(f"{label}: {t.agg}({t.path}) over {scope.entity.id} rows"
                         + (" matching its where" if cond else ""))
        return _agg_sql(t.agg, value, cond)

    def many_measure(self, scope: _Scope, h: ObjectLink, rest: str, t: MeasureTerm, label: str) -> str:
        source = entity_source(self.g, h.target)
        across = source != self.at(scope)
        if across and scope is not self.top:
            raise ObjectQueryRefused(
                f"{label}: {h.describe()} is to-many and crosses to another connection ({source}) from inside a "
                "pre-aggregated link or an EXISTS — a pre-aggregation is read by key from the query's own level; anchor "
                f"the query on {h.source.id}")
        agg = t.agg
        if agg == "count_distinct":
            raise ObjectQueryRefused(
                f"{label}: count_distinct across {h.describe()} does not add up over {scope.entity.id} objects "
                f"(one value can sit under two of them) — anchor the query on {h.target.id} instead")
        key = (scope.alias, h.rel.id, h.name)
        ml = self._many.get(key)
        if ml is None:
            ml = _ManyLink(hop=h, outer_alias=scope.alias, alias=self._alias("a"),
                           inner=_Scope(entity=h.target, alias=self._alias("m"), source=source), far=across)
            self._many[key] = ml
            self.note_link(h, "pre-aggregated, read by key" if across else "pre-aggregated",
                           f"link {h.describe()}: pre-aggregated per {h.remote_col} before the join — 1:N by "
                           f"measurement, so each {h.source.id} meets at most one aggregate row"
                           + (f"; {h.target.id} lives on {source}, so the pre-aggregation runs there and is read by "
                              "key" if across else ""))
        cond = self.where(ml.inner, t.where)
        if not rest:
            if agg != "count":
                raise ObjectQueryRefused(f"{label}: {agg} over the link {h.name} needs a property of "
                                         f"{h.target.id} ('{h.name}.<property>')")
            v = ml.column(_agg_sql("count", None, cond))
            self.plan.append(f"{label}: {h.target.id} objects counted per {h.source.id}, then summed")
            return f"COALESCE(SUM({ml.alias}.{v}), 0)"
        col, p, inner_hops = self.column(ml.inner, rest, "measure")
        if agg == "sum":
            self.semiadditive_check(ml.inner, inner_hops[-1].target if inner_hops else h.target, p.name,
                                    [h, *inner_hops], label)
        _check_aggregate(agg, p, f"{h.name}.{rest}", self.caveats)
        if agg in ("sum", "avg", "count") and any(h.label != "1:1" for h in inner_hops):
            raise ObjectQueryRefused(
                f"{label}: {agg} over '{t.path}' would repeat {inner_hops[-1].target.id}'s value once per "
                f"{h.target.id} row — anchor the query on {inner_hops[-1].target.id} instead")
        value = f"CAST({col} AS INTEGER)" if agg in ("sum", "avg") and _is_bool(p) else col
        out = _rollup(agg, ml.alias, ml.column, value, cond)
        self.plan.append(f"{label}: {agg}({h.name}.{rest}) over {h.target.id} rows, per {h.source.id}, rolled up"
                         + (" (a ratio of sums)" if agg == "avg" else ""))
        return out

    # ── assembly ──
    def time_column(self, scope: _Scope) -> tuple[str, str]:
        path = self.q.time.strip()
        e = scope.entity
        if not path:
            if e.created_at_col and find_property(e, e.created_at_col) is not None:
                path = e.created_at_col
            else:
                stamps = [n for n, p in (e.properties or {}).items() if (p.semantic_type or "") == "timestamp"]
                if len(stamps) != 1:
                    raise ObjectQueryRefused(
                        f"a grain or window on {e.id} needs `time` — "
                        + (f"name one of: {', '.join(stamps)}" if stamps else f"{e.id} has no time property"), stamps)
                path = stamps[0]
        col, p, _ = self.column(scope, path, "time")
        if not _is_temporal(p):
            raise ObjectQueryRefused(f"`time` '{path}' is not a date or timestamp ({p.data_type or p.semantic_type})")
        dtype = (p.data_type or "").upper()
        if "DATE" in dtype and "TIME" not in dtype:
            self._date_cols.add(col)
        return col, path

    def order(self, names: list[str], grouped: int) -> str:
        q = self.q
        if q.order_by:
            want = q.order_by.strip().lower()
            hit = next((n for n in names if n.lower() in (want, want.replace(".", "_"), want.rsplit(".", 1)[-1])), None)
            if hit is None:
                raise ObjectQueryRefused(f"order_by '{q.order_by}' is not an output column", names)
            return f"{quote_ident(hit)} {'DESC' if q.descending else 'ASC'}"
        if q.grain:
            return "1"
        return f"{grouped + 1} DESC" if grouped else ""

    def build(self) -> CompiledObjectQuery:
        q = self.q
        anchor = self.entity(q.object_type)
        scope = _Scope(entity=anchor, alias="t0")
        self.home, self.top = entity_source(self.g, anchor), scope
        b = anchor.backing
        key = (b.primary_key if b is not None else "") or anchor.identity_key
        verdict = {True: "unique, measured", False: "NOT unique, measured", None: "unmeasured"}[
            b.verified if b is not None else None]
        self.plan.append(f"objects({anchor.api_name}): {anchor.id} read from "
                         f"{(b.from_clause() if b is not None else '') or anchor.source_tables[0]}, key {key} ({verdict})")
        if b is not None and b.verified is False:
            self.caveats.append(f"{anchor.id}'s key {key} is not unique ({b.verification_note}) — a count of "
                                f"{anchor.id} counts rows, not distinct objects")

        where: list[str] = []
        if q.segment:
            frag = self.segment(scope, q.segment)
            if frag:
                where.append(frag)
        for f in q.filters:
            where.append(self.condition(scope, f))
            self.plan.append(f"filter {f.path} {f.op}" + ("" if f.value is None else f" {f.value!r}")
                             + (f" {f.value_path} (another property of the same object)" if f.value_path else ""))

        select: list[str] = []
        names: list[str] = []
        dims: list[str] = []
        measure_names: list[str] = []
        time_col = ""
        if q.grain or q.start or q.end:
            time_col, time_path = self.time_column(scope)
            self.time_path = time_path
        if q.grain:
            from aughor.sql.fiscal import fiscal_period_expr
            select.append(f"{fiscal_period_expr(q.grain, time_col, self.fiscal, 'duckdb')} AS period")
            names.append("period")
            where.append(f"{time_col} IS NOT NULL")
            self.plan.append(f"over({q.grain}) on {time_path}")
        for path in q.by:
            col, _, _ = self.column(scope, path, "dimension")
            name = _output_name(names, path.rsplit(".", 1)[-1], path.replace(".", "_"))
            select.append(f"{col} AS {quote_ident(name)}")
            names.append(name)
            dims.append(name)
            self.plan.append(f"by {path}")
        grouped = len(select)
        for bound, op, text in (("start", ">=", q.start), ("end", "<", q.end)):
            if text:
                if not _ISO_DATE.match(text.strip()):
                    raise ObjectQueryRefused(f"`{bound}` must be an ISO date (YYYY-MM-DD), got {text!r}")
                where.append(f"{time_col} {op} {_literal(text.strip(), bound)}")
        if q.start or q.end:
            self.plan.append(f"window on {time_path}: [{q.start or '…'}, {q.end or '…'})")

        for m in q.measures:
            label = f"measure {m.name or m.metric or (m.agg + ('(' + m.path + ')' if m.path else ''))}"
            d = m.divide_by
            self._per_moment = d.path if (d is not None and d.agg == "count_distinct" and not d.where) else ""
            try:
                expr = self.term(scope, m, label)
            finally:
                self._per_moment = ""
            if m.divide_by is not None:
                den = self.term(scope, m.divide_by, f"{label} ÷")
                expr = f"1.0 * ({expr}) / NULLIF({den}, 0)"
                self.plan.append(f"{label}: a ratio of the two aggregates, never an average of row ratios")
            if m.scale != 1:
                if not math.isfinite(m.scale):
                    raise ObjectQueryRefused(f"{label}: scale must be a finite number")
                expr = f"({expr}) * {m.scale!r}"
            if m.decimals is not None:
                expr = f"ROUND({expr}, {max(0, min(int(m.decimals), 12))})"
            base = m.metric or (f"{m.agg}_{m.path.rsplit('.', 1)[-1]}" if m.path else "count")
            name = _output_name(names, m.name, base + ("_ratio" if m.divide_by is not None else ""))
            select.append(f"{expr} AS {quote_ident(name)}")
            names.append(name)
            measure_names.append(name)

        sql = f"SELECT {', '.join(select)} FROM {backing_from(anchor, 't0')}"
        sql += "".join(f" {j}" for j in scope.joins)
        for ml in self._many.values():
            sql += " " + (self.pre_aggregated(ml.alias, ml.pre_aggregate(), ml.inner.source, ml.outer_alias,
                                              ml.hop.local_col, ml.columns, ml.hop.target.id,
                                              f"link {ml.hop.name} ({ml.hop.source.id} → {ml.hop.target.id}), "
                                              "pre-aggregated") if ml.far else ml.join_sql())
        for r in self._readings.values():
            sql += " " + (self.pre_aggregated(r.alias, r.pre_aggregate(), r.source, r.outer_alias, r.entity_key,
                                              r.columns, r.binding.name,
                                              f"readings of {r.binding.name}, pre-aggregated") if r.far else r.join_sql())
        if where:
            sql += " WHERE " + " AND ".join(f"({w})" for w in where)
        if grouped:
            sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(grouped))
        order = self.order(names, grouped)
        if order:
            sql += f" ORDER BY {order}"
        if q.limit is not None:
            sql += f" LIMIT {int(q.limit)}"
        cross = self.split_far(sql) if self.far else None
        return CompiledObjectQuery(sql=self.render(sql) if cross is None else self.display_far(sql), dialect=self.dialect,
                                   object_type=anchor.api_name,
                                   columns=names, plan=self.plan, links=self.links, caveats=self.caveats,
                                   dimensions=dims, measures=measure_names, overlay=self.overlay,
                                   bindings=self.bindings, cross_source=cross)

    def pre_aggregated(self, alias: str, select: str, source: str, outer: str, local: str,
                       columns: list[tuple[str, str]], target: str, label: str) -> str:
        """O3 — a pre-aggregation whose rows live on another connection: it runs there, one row per key by construction,
        is read by the keys the query's rows hold, and is joined beside them in the stage."""
        read = KeyedRead(alias=alias, kind="aggregate", connection_id=source, table=None, sql=None, key="k",
                         local=f"{outer}.{quote_ident(local)}", label=label, target=target, base=f"({select}) AS __r")
        for name, _ in columns:
            read.need(name)
        self.far[alias] = read
        self.far_paths[alias] = (read, "__r")
        return f"LEFT JOIN __far_{alias} AS {alias} ON {outer}.{quote_ident(local)} = {alias}.k"

    def split_far(self, sql: str):
        """ON-8 — the assembled statement split at its keyed reads: what runs on the anchor's connection, what each
        other connection is read for, and the aggregation that runs over both."""
        from aughor.semantic.cross_source import CrossSourceRefused, split
        try:
            plan = split(sql, self.far, dialect=self.dialect, date_cols=self._date_cols)
        except CrossSourceRefused as exc:
            raise ObjectQueryRefused(str(exc)) from exc
        sources = sorted({r.connection_id for r in self.far.values()})
        self.plan.append(f"cross-source: {len(self.far)} read(s) by key on {', '.join(sources)}; everything else runs on "
                         f"{self.home} as one statement at the object's grain, and the answer is aggregated over both in "
                         "an in-process stage that is dropped once it is read")
        return plan

    def display_far(self, sql: str) -> str:
        """The statement as written, each keyed read named by the connection, schema and table it reads."""
        text = self.render(sql)
        for alias, read in self.far.items():
            text = re.sub(rf"\b__far_{alias}\b", lambda _m, shown=read.display(): shown, text)
        return text

    def render(self, sql: str) -> str:
        import sqlglot
        from sqlglot import exp
        try:
            tree = sqlglot.parse_one(sql, read="duckdb")
        except Exception as exc:  # noqa: BLE001
            raise ObjectQueryRefused(f"the assembled query did not parse — a compiler defect, not a query "
                                     f"error ({exc})") from exc
        for node in list(tree.find_all(exp.TimestampTrunc)):
            if node.this is not None and node.this.sql(dialect="duckdb") in self._date_cols:
                node.replace(exp.DateTrunc(this=node.this.copy(), unit=node.args.get("unit")))
        try:
            return tree.sql(dialect=self.dialect if self.dialect else "duckdb")
        except Exception as exc:  # noqa: BLE001
            raise ObjectQueryRefused(f"the query could not be rendered for {self.dialect} ({exc})") from exc


def compile_object_query(query: ObjectQuery | dict, graph: Optional[OntologyGraph], *, dialect: str = "duckdb",
                         fiscal_start_month: Optional[int] = None,
                         overlay: Optional[list] = None) -> CompiledObjectQuery:
    """Compile an object query over the served graph, or raise `ObjectQueryRefused` with why. ``overlay``
    is the connection's accepted property edits (ON-4): a property they set reads like a column."""
    if isinstance(query, dict):
        try:
            query = ObjectQuery.model_validate(query)
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
            raise ObjectQueryRefused(f"the object query is malformed — {detail}") from exc
    if graph is None or not graph.entities:
        raise ObjectQueryRefused("no ontology is built for this scope — there are no object types to compile against")
    if query.limit is not None and not 1 <= query.limit <= _MAX_LIMIT:
        raise ObjectQueryRefused(f"limit must be between 1 and {_MAX_LIMIT}")
    fiscal = fiscal_start_month if fiscal_start_month is not None else _org_fiscal_start()
    return _Compiler(graph, query, (dialect or "duckdb").lower(), fiscal, overlay).build()


def property_at(graph: Optional[OntologyGraph], object_type: str, path: str, *,
                purpose: str = "path") -> tuple[OntologyEntity, EntityProperty, list[ObjectLink]]:
    """ON-9 — the property ``path`` names from ``object_type``, resolved by the compiler's own law (to-one links only;
    a backing's, a binding's or a derived property), with the type it lands on and the links crossed — or
    `ObjectQueryRefused` with why. What a declaration's anchors are checked against, so a stage the compiler could not
    read is refused before it is written."""
    if graph is None or not graph.entities:
        raise ObjectQueryRefused("no ontology is built for this scope — there are no object types to resolve against")
    compiler = _Compiler(graph, ObjectQuery(object_type=object_type, measures=[ObjectMeasure()]), "duckdb", 1)
    anchor = compiler.entity(object_type)
    scope = _Scope(entity=anchor, alias="t0")
    compiler.home, compiler.top = entity_source(graph, anchor), scope
    _, prop, hops = compiler.column(scope, path, purpose)
    return (hops[-1].target if hops else anchor), prop, hops


# ── the catalog a caller chooses names from ─────────────────────────────────────────────

def object_catalog(graph: OntologyGraph, overlay: Optional[list] = None) -> dict:
    """Every object type with its properties by role, its links (usable or why not), its verified
    segments and metrics — the names `compile_object_query` accepts, and nothing else."""
    from aughor.ontology.display import display_of
    types = []
    for e in sorted(graph.entities.values(), key=lambda x: x.api_name):
        roles: dict[str, list[str]] = {}
        for name, p in (e.properties or {}).items():
            roles.setdefault(p.semantic_type or "other", []).append(name)
        bindings = []
        for binding in e.bindings or []:
            problem = binding_problem(e, binding)
            if not problem:          # a property the compiler would refuse is not a name it accepts
                for name, p in binding.properties.items():
                    roles.setdefault(p.semantic_type or "other", []).append(name)
            bindings.append({"name": binding.name, "kind": binding.kind, "source": binding.table or "a keyed SELECT",
                             "key": binding.key, "properties": sorted(binding.properties), "usable": not problem,
                             **({"why_not": problem} if problem else {})})
        links = []
        for h in object_links(graph, e):
            problem = link_problem(h)
            links.append({"name": h.name, "business_name": h.business, "verb": h.rel.verb, "to": h.target.api_name,
                          "cardinality": h.label, "on": f"{h.local_col} = {h.remote_col}", "usable": not problem,
                          **({"why_not": problem} if problem else {})})
        # ON-9 — what a declared process or rule derives on this type is a name the compiler accepts, once measured.
        derived = derived_for(graph, e)
        for d in derived.properties:
            if d.usable:
                roles.setdefault("measure", []).append(d.name)
        # R2 — a part stays a type the compiler accepts by name, and is listed under its parent as the map lists it.
        parent = part_of(graph, e)
        b = e.backing
        types.append({
            "object_type": e.api_name, "id": e.id, "display_name": e.display_name,
            "display_property": display_of(e)["property"],
            "key": (b.primary_key if b is not None else "") or e.identity_key,
            "key_unique": b.verified if b is not None else None,
            "time": e.created_at_col or "",
            "properties": roles,
            "bindings": bindings,
            "links": links,
            "segments": (sorted(k for k, s in (e.segments or {}).items() if s.verified and (s.filter_sql or "").strip())
                         + sorted(d.name for d in derived.segments if d.usable)),
            "metrics": (sorted(mid for mid, m in graph.metrics.items() if m.verified and metric_on(m, e))
                        + sorted(d.name for d in derived.metrics if d.usable)),
            "overlay_properties": sorted(edits[0].column for edits in overlay_properties(e, overlay).values()),
            "part_of": parent.api_name if parent is not None else None,
            "parts": [{"object_type": part.api_name, "binding": through.name} for part, through in parts_of(graph, e)],
        })
    return {"connection_id": graph.connection_id, "schema_name": graph.schema_name, "object_types": types}


def catalog_names(graph: OntologyGraph, *, limit: int = 30) -> str:
    """The object types a tool description names, in api-name order — a part listed under its parent (`order (parts:
    order_item)`) as the map lists it, and still a name the compiler accepts. Reads as before where nothing is a part."""
    names = []
    for e in sorted(graph.entities.values(), key=lambda x: x.api_name):
        if part_of(graph, e) is not None:
            continue
        parts = [part.api_name for part, _ in parts_of(graph, e)]
        names.append(f"{e.api_name} (parts: {', '.join(parts)})" if parts else e.api_name)
    return ", ".join(names[:limit])


def _parts_after_parents(types: list[dict]) -> list[dict]:
    """The catalog's types in its own order, each part moved to follow its parent. A part whose parent the catalog does
    not hold keeps its place."""
    present = {t["object_type"] for t in types}
    under: dict[str, list[dict]] = {}
    for t in types:
        if t.get("part_of") in present:
            under.setdefault(t["part_of"], []).append(t)
    out: list[dict] = []
    for t in types:
        if t.get("part_of") in present:
            continue
        out.append(t)
        out.extend(under.get(t["object_type"], []))
    return out


def render_object_catalog(catalog: dict, *, max_chars: int = 8000) -> str:
    """The catalog as compact text for a model: one block per object type, each part right after its parent and
    marked as one (R2) — a model reads a part as the map shows it, not as a peer type."""
    lines: list[str] = []
    types = catalog.get("object_types", [])
    through = {p["object_type"]: p["binding"] for t in types for p in t.get("parts") or []}
    for t in _parts_after_parents(types):
        key = f"key {t['key']}" + (" ✓unique" if t.get("key_unique") else "")
        head = f"{t['object_type']} ({t['id']}; {key}" + (f"; time {t['time']}" if t.get("time") else "") + ")"
        if t.get("part_of"):
            head += f" — a part of {t['part_of']}" + (f", read through its binding {through[t['object_type']]}"
                                                     if t["object_type"] in through else "")
        lines.append(head)
        if t.get("parts"):
            listed = ", ".join(f"{p['object_type']} (through {p['binding']})" for p in t["parts"])
            lines.append(f"  parts: {listed}")
        for role in ("measure", "ordinal", "flag", "dimension", "timestamp", "key"):
            if t["properties"].get(role):
                lines.append(f"  {role}: {', '.join(t['properties'][role][:24])}")
        usable = [f"{link['name']} → {link['to']} [{link['cardinality']}]" for link in t["links"] if link["usable"]]
        if usable:
            lines.append(f"  links: {'; '.join(usable)}")
        unusable = [f"{link['name']} [{link['cardinality']}]" for link in t["links"] if not link["usable"]]
        if unusable:
            lines.append(f"  not traversable: {'; '.join(unusable)}")
        unread = [f"{b['name']} ({b['kind']})" for b in t.get("bindings", []) if not b["usable"]]
        if unread:
            lines.append(f"  bindings not read: {'; '.join(unread)}")
        if t.get("segments"):
            lines.append(f"  segments: {', '.join(t['segments'])}")
        if t.get("metrics"):
            lines.append(f"  metrics: {', '.join(t['metrics'])}")
        if t.get("overlay_properties"):
            lines.append(f"  overlay properties (accepted edits): {', '.join(t['overlay_properties'])}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars].rsplit("\n", 1)[0] + "\n  …(truncated)"
