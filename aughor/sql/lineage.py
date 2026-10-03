"""DE-4 (ROADMAP §3.51) — column lineage over a statement the platform runs.

Which table columns an answer's columns come from, and which columns the statement filtered,
joined and grouped on — from sqlglot's `qualify` and `lineage`, not from text. Every edge says
how it was resolved:

* ``certain`` — the parser bound the column to a table, with the schema or an explicit alias;
* ``likely``  — bound through a derived table: a CTE or a subquery stands between the output and
  the table, so the column is the table's by the parser's reading of that intermediate select;
* ``possible`` — attributed by name only: no schema was available and the statement reads one
  source, so the column is taken to be that source's.

An output the lineage cannot trace to any table column — ``COUNT(*)``, a literal, a constant
expression — is kept with no sources, so a receipt can say "this number rests on no column"
rather than drop it. When the statement cannot be qualified at all (no schema and a ``SELECT *``
over several tables, a parse the dialect refuses), the result falls back to TABLE level and says
so in ``note``: the tables are still named, the columns are not guessed.

Nothing here runs SQL. The schema, when given, is ``{schema: {table: {column: type}}}`` as
sqlglot takes it (a two-level ``{table: {column: type}}`` is accepted too).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.lineage import Node, lineage
from sqlglot.optimizer.qualify import qualify

Confidence = Literal["certain", "likely", "possible"]
Role = Literal["output", "filter", "join", "group"]

# Dialect names the door records that sqlglot spells otherwise, or does not know. An unknown
# dialect parses generically rather than failing: the door already proved it parses (DE-1).
_DIALECT_ALIASES = {"postgresql": "postgres", "mssql": "tsql", "sqlserver": "tsql", "generic": None, "": None}


def sqlglot_dialect(name: str | None) -> str | None:
    if name is None:
        return None
    key = name.lower()
    if key in _DIALECT_ALIASES:
        return _DIALECT_ALIASES[key]
    try:
        sqlglot.Dialect.get_or_raise(key)
    except Exception:
        return None
    return key


@dataclass(frozen=True)
class ColumnRef:
    """A physical column: the table as the statement named it (schema-qualified when it was),
    and the column."""
    table: str
    column: str

    def as_dict(self) -> dict[str, str]:
        return {"table": self.table, "column": self.column}


@dataclass(frozen=True)
class OutputColumn:
    name: str
    expression: str
    sources: tuple[ColumnRef, ...]
    confidence: Confidence
    """For an output with no column source — ``COUNT(*)``, a literal — the tables the select
    that produced it reads: the number rests on those tables and on no column, and the
    receipt says so rather than drop the output."""
    tables: tuple[str, ...] = ()


def is_bare_column(expression: str) -> bool:
    """True when an output expression is a column reference and nothing more — `c.name`, `name AS who`,
    `"t"."c"` — so the output's values ARE that column's. False for any expression over it (`total * 2`,
    `CAST(x AS INT)`, `COUNT(*)`), whose values are its own."""
    import re
    text = re.sub(r'\s+AS\s+[\w"`\[\]]+\s*$', "", expression or "", flags=re.I).strip()
    return bool(text) and bool(re.match(r'^(?:[\w"`\[\]]+\s*\.\s*)*[\w"`\[\]]+$', text))


@dataclass
class ColumnLineage:
    dialect: str | None
    tables: list[str]
    outputs: list[OutputColumn] = field(default_factory=list)
    filters: list[tuple[ColumnRef, Confidence]] = field(default_factory=list)
    joins: list[tuple[ColumnRef, Confidence]] = field(default_factory=list)
    groups: list[tuple[ColumnRef, Confidence]] = field(default_factory=list)
    level: Literal["column", "table"] = "column"
    note: str | None = None

    def edges(self) -> list[dict[str, Any]]:
        """The edges as the receipt carries them — flat, JSON-ready, one per (role, column). An output edge says
        whether the output IS the column (`direct`: `c.name`, `name AS who`) or an expression over it (`total * 2`):
        the values of the first are the column's, the values of the second are not, and a reader that looks a
        column up live needs the difference."""
        out: list[dict[str, Any]] = []
        for o in self.outputs:
            direct = is_bare_column(o.expression)
            for s in o.sources:
                out.append({"role": "output", "as": o.name, "table": s.table, "column": s.column,
                            "confidence": o.confidence, "direct": direct})
            if not o.sources and o.tables:
                for t in o.tables:
                    out.append({"role": "output", "as": o.name, "table": t, "column": None,
                                "confidence": o.confidence, "note": "a row count or a constant: no column"})
            elif not o.sources:
                out.append({"role": "output", "as": o.name, "table": None, "column": None,
                            "confidence": None, "expression": o.expression})
        for role, refs in (("filter", self.filters), ("join", self.joins), ("group", self.groups)):
            seen: set[tuple[str, str]] = set()
            for ref, conf in refs:
                if (ref.table, ref.column) in seen:
                    continue
                seen.add((ref.table, ref.column))
                out.append({"role": role, "table": ref.table, "column": ref.column, "confidence": conf})
        return out

    def columns_read(self) -> set[ColumnRef]:
        """Every physical column the statement reads, whatever its role."""
        cols = {s for o in self.outputs for s in o.sources}
        cols.update(r for r, _ in self.filters)
        cols.update(r for r, _ in self.joins)
        cols.update(r for r, _ in self.groups)
        return cols

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "dialect": self.dialect, "tables": list(self.tables),
                "note": self.note, "edges": self.edges()}


# ── helpers ───────────────────────────────────────────────────────────────────────

def _table_name(t: exp.Table) -> str:
    parts = [p for p in (t.catalog, t.db, t.name) if p]
    return ".".join(parts)


def _unquote(name: str) -> str:
    return name.strip('"`[]')


def _leaf_ref(node: Node) -> ColumnRef | None:
    """A lineage leaf that is a table column, as (table, column); None for anything else."""
    if not isinstance(node.expression, exp.Table):
        return None
    col = node.name.rsplit(".", 1)[-1] if "." in node.name else node.name
    return ColumnRef(_table_name(node.expression), _unquote(col))


def _direct_aliases(q: exp.Expression) -> set[str]:
    """Aliases (or names) of the physical tables the OUTERMOST select reads directly — a leaf
    from any other table came through a CTE or a subquery."""
    root = q if isinstance(q, exp.Select) else q.find(exp.Select)
    out: set[str] = set()
    if root is None:
        return out
    for t in root.find_all(exp.Table):
        # Skip tables that sit inside a nested select of the root (a derived table's own FROM).
        parent_select = t.find_ancestor(exp.Select)
        if parent_select is root:
            out.add(t.alias_or_name)
    return out


def _confidence(leaves: Iterable[Node], direct: set[str], with_schema: bool, explicit: bool) -> Confidence:
    via_derived = any(
        isinstance(n.expression, exp.Table) and n.expression.alias_or_name not in direct for n in leaves
    )
    if via_derived:
        return "likely"
    return "certain" if (with_schema or explicit) else "possible"


def _explicit_columns(parsed: exp.Expression) -> set[tuple[str, str]]:
    """(table-qualifier, column) pairs the AUTHOR wrote qualified — the parser's binding of those
    does not rest on a schema."""
    return {(c.table, c.name) for c in parsed.find_all(exp.Column) if c.table}


def _clause_columns(q: exp.Expression, kinds: tuple[type, ...]) -> list[exp.Column]:
    cols: list[exp.Column] = []
    for kind in kinds:
        for clause in q.find_all(kind):
            cols.extend(clause.find_all(exp.Column))
    return cols


# ── the one entry point ──────────────────────────────────────────────────────────

def column_lineage(sql: str, *, dialect: str | None = None, schema: dict | None = None) -> ColumnLineage:
    """Trace one statement. Never raises for a statement the door already ran: a failure to
    qualify falls back to table level and says why."""
    d = sqlglot_dialect(dialect)
    try:
        parsed = sqlglot.parse_one(sql, read=d)
    except SqlglotError as exc:
        return ColumnLineage(dialect=d, tables=[], level="table",
                             note=f"not parsed by sqlglot ({type(exc).__name__}): columns not traced")
    tables = sorted({_table_name(t) for t in parsed.find_all(exp.Table) if t.name}
                    - {c.alias for c in parsed.find_all(exp.CTE)})
    if not isinstance(parsed, (exp.Select, exp.Union, exp.Subquery)) and not parsed.find(exp.Select):
        return ColumnLineage(dialect=d, tables=tables, level="table", note="not a SELECT: columns not traced")

    explicit = _explicit_columns(parsed)
    with_schema = bool(schema)
    try:
        q = qualify(parsed.copy(), schema=schema, dialect=d, validate_qualify_columns=False)
    except SqlglotError as exc:
        why = "no schema: " if not with_schema else ""
        return ColumnLineage(dialect=d, tables=tables, level="table",
                             note=f"{why}columns could not be qualified ({type(exc).__name__}); tables only")

    # A star the schema could not expand is not a column: the statement's columns are unknown,
    # and the honest answer is the tables, with the reason.
    if any(isinstance(s, exp.Star) or (isinstance(s, exp.Column) and isinstance(s.this, exp.Star))
           for sel in q.find_all(exp.Select) for s in sel.expressions):
        return ColumnLineage(dialect=d, tables=tables, level="table",
                             note="no schema: SELECT * could not be expanded; tables only")

    direct = _direct_aliases(q)
    out = ColumnLineage(dialect=d, tables=tables)
    cte_aliases = {c.alias for c in q.find_all(exp.CTE)}
    derived_selects: dict[str, exp.Expression] = {s.alias: s.this for s in q.find_all(exp.Subquery) if s.alias}
    derived_selects.update({c.alias: c.this for c in q.find_all(exp.CTE)})

    def select_tables(select: exp.Expression, depth: int = 0) -> list[tuple[str, Confidence]]:
        """The physical tables a select reads — directly (certain), or through a CTE or a
        derived table (likely), followed a few levels down."""
        found: list[tuple[str, Confidence]] = []
        if depth > 4:
            return found
        for t in select.find_all(exp.Table):
            if t.find_ancestor(exp.Select) is not select and not isinstance(select, exp.Union):
                continue
            if t.name in cte_aliases or t.alias_or_name in derived_selects and t.name not in {
                    x.name for x in q.find_all(exp.Table) if x.db}:
                inner = derived_selects.get(t.name) or derived_selects.get(t.alias_or_name)
                if inner is not None:
                    found.extend((n, "likely") for n, _c in select_tables(inner, depth + 1))
                continue
            if t.name:
                found.append((_table_name(t), "certain"))
        return found

    # Outputs: one lineage walk per named select.
    for name in q.named_selects:
        expr_sql = ""
        for sel in q.selects:
            if sel.alias_or_name == name:
                expr_sql = sel.sql(dialect=d)
                break
        try:
            node = lineage(name, q, schema=schema, dialect=d)
        except SqlglotError:
            out.outputs.append(OutputColumn(name, expr_sql, (), "possible"))
            continue
        leaves = [n for n in node.walk() if not n.downstream]
        refs = tuple(dict.fromkeys(r for r in (_leaf_ref(n) for n in leaves) if r))
        if not refs:
            # No column feeds this output — a row count, a constant. It rests on the tables the
            # producing select reads: directly (certain) or through a CTE or a subquery (likely).
            own: list[tuple[str, Confidence]] = []
            for n in leaves:
                src = n.source if isinstance(n.source, (exp.Select, exp.Union)) else None
                if src is not None:
                    own.extend(select_tables(src))
            if not own:
                own = [(t, "likely") for t in tables]
            conf: Confidence = "certain" if own and all(c == "certain" for _t, c in own) else "likely"
            out.outputs.append(OutputColumn(name, expr_sql, (), conf, tuple(dict.fromkeys(t for t, _c in own))))
            continue
        leaf_pairs = [(_unquote(n.name.rsplit(".", 1)[0]) if "." in n.name else "", r)
                      for n in leaves for r in (_leaf_ref(n),) if r]
        was_explicit = bool(explicit) and all((alias, r.column) in explicit for alias, r in leaf_pairs)
        out.outputs.append(OutputColumn(name, expr_sql, refs, _confidence(leaves, direct, with_schema, was_explicit)))

    # Filters, joins, groups: each column resolved to its physical column, through a CTE or a
    # subquery when the alias is one.
    cte_names = {c.alias for c in q.find_all(exp.CTE)}
    derived = {s.alias: s.this for s in q.find_all(exp.Subquery) if s.alias}
    derived.update({c.alias: c.this for c in q.find_all(exp.CTE)})
    alias_to_table = {t.alias_or_name: t for t in q.find_all(exp.Table)
                      if t.name and t.name not in cte_names and t.alias_or_name not in derived}

    def resolve(col: exp.Column) -> list[tuple[ColumnRef, Confidence]]:
        if not col.table:
            return []
        t = alias_to_table.get(col.table)
        if t is not None:
            conf: Confidence = "certain" if (with_schema or (col.table, col.name) in explicit) else "possible"
            return [(ColumnRef(_table_name(t), col.name), conf)]
        # A CTE or a derived table: trace the column inside it, and say it came through one.
        target = derived.get(col.table)
        if target is None or not isinstance(target, (exp.Select, exp.Union)):
            return []
        try:
            node = lineage(col.name, target, schema=schema, dialect=d)
        except SqlglotError:
            return []
        refs = [r for r in (_leaf_ref(n) for n in node.walk() if not n.downstream) if r]
        return [(r, "likely") for r in dict.fromkeys(refs)]

    for col in _clause_columns(q, (exp.Where, exp.Having, exp.Qualify)):
        out.filters.extend(resolve(col))
    for join in q.find_all(exp.Join):
        for col in join.find_all(exp.Column):
            out.joins.extend(resolve(col))
    for col in _clause_columns(q, (exp.Group,)):
        out.groups.extend(resolve(col))

    if not with_schema and any(o.confidence == "possible" for o in out.outputs):
        out.note = "no schema: columns attributed by name"
    return out
