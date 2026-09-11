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
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from aughor.ontology.cardinality import quote_ident, quote_table
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph, OntologyMetric, OntologyRelationship

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

    def to_dict(self) -> dict:
        return {"path": "compiled", "sql": self.sql, "dialect": self.dialect,
                "object_type": self.object_type, "columns": list(self.columns),
                "dimensions": list(self.dimensions), "measures": list(self.measures),
                "plan": list(self.plan), "links": list(self.links), "caveats": list(self.caveats),
                "overlay": list(self.overlay)}


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


def find_property(entity: OntologyEntity, name: str) -> Optional[EntityProperty]:
    props = entity.properties or {}
    if name in props:
        return props[name]
    low = name.lower()
    return next((p for k, p in props.items() if k.lower() == low), None)


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


def backing_from(entity: OntologyEntity, alias: str) -> str:
    b = entity.backing
    if b is not None and b.kind == "query" and b.sql:
        return f"({b.sql.strip().rstrip(';')}) AS {alias}"
    table = (b.table if b is not None else None) or (entity.source_tables[0] if entity.source_tables else "")
    if not table:
        raise ObjectQueryRefused(f"object type {entity.id} has no backing to read from")
    return f"{quote_table(table)} AS {alias}"


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


@dataclass
class _ManyLink:
    """One to-many link, pre-aggregated per its key: every measure over it becomes a column."""
    hop: ObjectLink
    outer_alias: str
    alias: str
    inner: _Scope
    columns: list[tuple[str, str]] = field(default_factory=list)

    def column(self, expr: str) -> str:
        for name, existing in self.columns:
            if existing == expr:
                return name
        name = f"v{len(self.columns) + 1}"
        self.columns.append((name, expr))
        return name

    def join_sql(self) -> str:
        key = f"{self.inner.alias}.{quote_ident(self.hop.remote_col)}"
        cols = ", ".join(f"{expr} AS {name}" for name, expr in self.columns)
        joins = "".join(f" {j}" for j in self.inner.joins)
        return (f"LEFT JOIN (SELECT {key} AS k, {cols} FROM {backing_from(self.hop.target, self.inner.alias)}{joins} "
                f"GROUP BY {key}) AS {self.alias} "
                f"ON {self.outer_alias}.{quote_ident(self.hop.local_col)} = {self.alias}.k")


class _Compiler:
    def __init__(self, graph: OntologyGraph, query: ObjectQuery, dialect: str, fiscal_start_month: int,
                 overlay: Optional[list] = None):
        self.g = graph
        #: ON-4 — the accepted property edits on this connection's objects, merged at read time.
        self.overlay_edits = list(overlay or [])
        self.overlay: list[dict] = []
        self._overlay_noted: set = set()
        self.q = query
        self.dialect = dialect
        self.fiscal = fiscal_start_month
        self.plan: list[str] = []
        self.links: list[dict] = []
        self.caveats: list[str] = []
        self._n = 0
        self._many: dict[tuple, _ManyLink] = {}
        self._noted: set = set()
        #: Time columns typed DATE: a truncation over one must render as DATE_TRUNC, not
        #: TIMESTAMP_TRUNC, on dialects that tell the two apart (BigQuery).
        self._date_cols: set[str] = set()

    def _alias(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    # ── names ──
    def entity(self, name: str) -> OntologyEntity:
        return find_object_type(self.g, name)

    def prop(self, entity: OntologyEntity, name: str, path: str) -> EntityProperty:
        p = find_property(entity, name) or self.virtual_prop(entity, name)
        if p is not None:
            return p
        names = sorted(entity.properties or {}) + sorted(overlay_properties(entity, self.overlay_edits))
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

    def colref(self, scope: _Scope, alias: str, entity: OntologyEntity, p: EntityProperty) -> str:
        """The SQL for a property of ``entity`` under ``alias``: its column or — for an overlay property —
        the accepted values joined on the object's key. The source is read, never written."""
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
        alias = self._alias("j")
        scope.joins.append(f"LEFT JOIN {backing_from(h.target, alias)} "
                           f"ON {from_alias}.{quote_ident(h.local_col)} = {alias}.{quote_ident(h.remote_col)}")
        scope.join_alias[key] = alias
        self.note_link(h, "joined", f"link {h.describe()}: joined — to-one by measurement, so it cannot "
                                    f"multiply {h.source.id} rows")
        return alias

    def column(self, scope: _Scope, path: str, purpose: str) -> tuple[str, EntityProperty, list[ObjectLink]]:
        """A property reached through to-one links only."""
        segs = _split(path, purpose)
        entity, alias, hops = scope.entity, scope.alias, []
        for seg in segs[:-1]:
            h = self.need_hop(entity, seg, path)
            if not h.to_one:
                raise ObjectQueryRefused(
                    f"{purpose} '{path}' crosses {h.describe()}, a to-many link — it would repeat each "
                    f"{scope.entity.id} once per {h.target.id}. A to-many link belongs in a measure "
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
        wants_link = f.op in ("exists", "not_exists")
        for i, seg in enumerate(segs):
            last = i == len(segs) - 1
            if last and not wants_link:
                p = self.prop(entity, seg, f.path)
                return _predicate(self.colref(scope, alias, entity, p), p, f)
            h = self.need_hop(entity, seg, f.path)
            if h.to_one and not (last and wants_link):
                alias = self.join_one(scope, alias, h)
                entity = h.target
                continue
            return self.exists(alias, h, ".".join(segs[i + 1:]), f)
        raise ObjectQueryRefused(f"filter path '{f.path}' did not resolve")

    def exists(self, outer_alias: str, h: ObjectLink, rest: str, f: ObjectFilter) -> str:
        inner = _Scope(entity=h.target, alias=self._alias("e"))
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

    def where(self, scope: _Scope, filters: list[ObjectFilter]) -> str:
        return " AND ".join(f"({self.condition(scope, f)})" for f in filters)

    def segment(self, scope: _Scope, name: str) -> str:
        segs = scope.entity.segments or {}
        low = name.strip().lower()
        seg = next((s for k, s in segs.items() if low in (k.lower(), (s.display_name or "").lower())), None)
        verified = sorted(k for k, s in segs.items() if s.verified)
        if seg is None:
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
            raise ObjectQueryRefused(f"no metric '{name}' on {scope.entity.id}{_did_you_mean(low, mine)}", mine)
        if not m.verified:
            raise ObjectQueryRefused(f"metric '{m.id}' is not verified ({m.verification_note or 'no note'}) — "
                                     "the compiler measures only with verified formulas", mine)
        if not metric_on(m, scope.entity):
            raise ObjectQueryRefused(f"metric '{m.id}' is defined on {m.entity or ', '.join(m.tables)}, not "
                                     f"{scope.entity.id} — anchor the query on its object type", mine)
        self.plan.append(f"metric {m.id} (verified): {m.formula_sql}")
        return _qualify(m.formula_sql, scope.alias, self.dialect, what=f"metric {m.id}", expression=True)

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
        for i, seg in enumerate(segs):
            last = i == len(segs) - 1
            if last:
                p = find_property(entity, seg) or self.virtual_prop(entity, seg)
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

    def prop_measure(self, scope: _Scope, alias: str, p: EntityProperty, hops: list[ObjectLink],
                     t: MeasureTerm, label: str, entity: Optional[OntologyEntity] = None) -> str:
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
        value = self.colref(scope, alias, entity, p) if entity is not None else f"{alias}.{quote_ident(p.name)}"
        if t.agg in ("sum", "avg") and _is_bool(p):
            value = f"CAST({value} AS INTEGER)"
        self.plan.append(f"{label}: {t.agg}({t.path}) over {scope.entity.id} rows"
                         + (" matching its where" if cond else ""))
        return _agg_sql(t.agg, value, cond)

    def many_measure(self, scope: _Scope, h: ObjectLink, rest: str, t: MeasureTerm, label: str) -> str:
        agg = t.agg
        if agg == "count_distinct":
            raise ObjectQueryRefused(
                f"{label}: count_distinct across {h.describe()} does not add up over {scope.entity.id} objects "
                f"(one value can sit under two of them) — anchor the query on {h.target.id} instead")
        key = (scope.alias, h.rel.id, h.name)
        ml = self._many.get(key)
        if ml is None:
            ml = _ManyLink(hop=h, outer_alias=scope.alias, alias=self._alias("a"),
                           inner=_Scope(entity=h.target, alias=self._alias("m")))
            self._many[key] = ml
            self.note_link(h, "pre-aggregated",
                           f"link {h.describe()}: pre-aggregated per {h.remote_col} before the join — 1:N by "
                           f"measurement, so each {h.source.id} meets at most one aggregate row")
        cond = self.where(ml.inner, t.where)
        if not rest:
            if agg != "count":
                raise ObjectQueryRefused(f"{label}: {agg} over the link {h.name} needs a property of "
                                         f"{h.target.id} ('{h.name}.<property>')")
            v = ml.column(_agg_sql("count", None, cond))
            self.plan.append(f"{label}: {h.target.id} objects counted per {h.source.id}, then summed")
            return f"COALESCE(SUM({ml.alias}.{v}), 0)"
        col, p, inner_hops = self.column(ml.inner, rest, "measure")
        _check_aggregate(agg, p, f"{h.name}.{rest}", self.caveats)
        if agg in ("sum", "avg", "count") and any(h.label != "1:1" for h in inner_hops):
            raise ObjectQueryRefused(
                f"{label}: {agg} over '{t.path}' would repeat {inner_hops[-1].target.id}'s value once per "
                f"{h.target.id} row — anchor the query on {inner_hops[-1].target.id} instead")
        value = f"CAST({col} AS INTEGER)" if agg in ("sum", "avg") and _is_bool(p) else col
        if agg == "count":
            out = f"COALESCE(SUM({ml.alias}.{ml.column(_agg_sql('count', value, cond))}), 0)"
        elif agg == "sum":
            out = f"SUM({ml.alias}.{ml.column(_agg_sql('sum', value, cond))})"
        elif agg in ("min", "max"):
            out = f"{agg.upper()}({ml.alias}.{ml.column(_agg_sql(agg, value, cond))})"
        else:   # avg over the linked rows — a ratio of sums, never an average of per-object averages
            s = ml.column(_agg_sql("sum", value, cond))
            n = ml.column(_agg_sql("count", value, cond))
            out = f"1.0 * SUM({ml.alias}.{s}) / NULLIF(SUM({ml.alias}.{n}), 0)"
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
            self.plan.append(f"filter {f.path} {f.op}" + ("" if f.value is None else f" {f.value!r}"))

        select: list[str] = []
        names: list[str] = []
        dims: list[str] = []
        measure_names: list[str] = []
        time_col = ""
        if q.grain or q.start or q.end:
            time_col, time_path = self.time_column(scope)
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
            expr = self.term(scope, m, label)
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
        sql += "".join(f" {ml.join_sql()}" for ml in self._many.values())
        if where:
            sql += " WHERE " + " AND ".join(f"({w})" for w in where)
        if grouped:
            sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(grouped))
        order = self.order(names, grouped)
        if order:
            sql += f" ORDER BY {order}"
        if q.limit is not None:
            sql += f" LIMIT {int(q.limit)}"
        return CompiledObjectQuery(sql=self.render(sql), dialect=self.dialect, object_type=anchor.api_name,
                                   columns=names, plan=self.plan, links=self.links, caveats=self.caveats,
                                   dimensions=dims, measures=measure_names, overlay=self.overlay)

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
        links = []
        for h in object_links(graph, e):
            problem = link_problem(h)
            links.append({"name": h.name, "business_name": h.business, "verb": h.rel.verb, "to": h.target.api_name,
                          "cardinality": h.label, "on": f"{h.local_col} = {h.remote_col}", "usable": not problem,
                          **({"why_not": problem} if problem else {})})
        b = e.backing
        types.append({
            "object_type": e.api_name, "id": e.id, "display_name": e.display_name,
            "display_property": display_of(e)["property"],
            "key": (b.primary_key if b is not None else "") or e.identity_key,
            "key_unique": b.verified if b is not None else None,
            "time": e.created_at_col or "",
            "properties": roles,
            "links": links,
            "segments": sorted(k for k, s in (e.segments or {}).items() if s.verified and (s.filter_sql or "").strip()),
            "metrics": sorted(mid for mid, m in graph.metrics.items() if m.verified and metric_on(m, e)),
            "overlay_properties": sorted(edits[0].column for edits in overlay_properties(e, overlay).values()),
        })
    return {"connection_id": graph.connection_id, "schema_name": graph.schema_name, "object_types": types}


def render_object_catalog(catalog: dict, *, max_chars: int = 8000) -> str:
    """The catalog as compact text for a model: one block per object type."""
    lines: list[str] = []
    for t in catalog.get("object_types", []):
        key = f"key {t['key']}" + (" ✓unique" if t.get("key_unique") else "")
        lines.append(f"{t['object_type']} ({t['id']}; {key}" + (f"; time {t['time']}" if t.get("time") else "") + ")")
        for role in ("measure", "ordinal", "flag", "dimension", "timestamp", "key"):
            if t["properties"].get(role):
                lines.append(f"  {role}: {', '.join(t['properties'][role][:24])}")
        usable = [f"{link['name']} → {link['to']} [{link['cardinality']}]" for link in t["links"] if link["usable"]]
        if usable:
            lines.append(f"  links: {'; '.join(usable)}")
        unusable = [f"{link['name']} [{link['cardinality']}]" for link in t["links"] if not link["usable"]]
        if unusable:
            lines.append(f"  not traversable: {'; '.join(unusable)}")
        if t.get("segments"):
            lines.append(f"  segments: {', '.join(t['segments'])}")
        if t.get("metrics"):
            lines.append(f"  metrics: {', '.join(t['metrics'])}")
        if t.get("overlay_properties"):
            lines.append(f"  overlay properties (accepted edits): {', '.join(t['overlay_properties'])}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars].rsplit("\n", 1)[0] + "\n  …(truncated)"
