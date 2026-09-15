"""ON-8 — an object query whose sources live on more than one connection (ROADMAP §3.15, the second movement).

The compiler (`aughor.semantic.object_query`) assembles one statement for one connection. In an organisation's ontology
a query may cross to a type or a binding that lives on another connection, and no statement sees two. So the compiler
marks each such source as a KEYED READ — a to-one link to a type on another connection; a binding read from one (static
as it stands, timeseries as its latest row, detail as its rollups); a to-many link or a binding's readings pre-aggregated
per key; the keys an EXISTS tests — hanging off the query's own FROM level, or off another keyed read's rows when a path
continues past a type read by key. This module runs what it assembled in three parts:

1. **Home.** Everything that does not touch another connection runs on the anchor's connection as one statement: the
   filters, the joins and pre-aggregated links that stay on that connection, and each value an aggregate or a group
   reads, computed per row — with the keys every keyed read needs projected beside them. When the answer aggregates,
   those rows are grouped there at the key's grain (`_pre_aggregate`): every value the stage reads outside an
   aggregate, and every key, keys a group; an aggregate over home values alone is computed per group and rolled up in
   the stage, and one that reads a far value is weighted by how many rows its group holds.
2. **Keyed reads.** Each far source is read through the batched-foreach engine by exactly the distinct keys the home
   rows hold — or, past a type read by key, the keys that read's rows hold — one query per chunk of keys
   (`remote_join.fetch_by_keys`), every value typed as its source holds it. A type or binding a path reaches past a
   keyed read on that read's own connection is joined inside it, so it is still one read.
3. **Stage.** Both land in an in-process DuckDB for this one answer, joined on the canonical key form the engine and
   the measurement both key on, and the compiler's own SELECT, WHERE, GROUP BY and ORDER BY run there, each home value
   read from the column it was computed into.

Correct by construction for the reasons the single statement is. Every keyed read is one row per key — a link
measured N:1 or 1:1 from where the query stands, a binding measured one row per object, or a latest row, rollups, a
pre-aggregation or distinct keys by construction — so the stage's join cannot multiply the home rows, and a far key that now meets two rows is refused rather than joined. The aggregation is the
compiler's own over the same rows, so an average is still a ratio of sums and a distinct count still counts values.

Grouping is correct for the same reason the join is: a group holds one value of every key, and a keyed read is one
row per key, so every far value is constant inside a group — a far condition keeps or drops a whole group, and a count
or sum weighted by the group's rows is the count or sum over those rows.

Bounded and honest: the home rows (`MAX_HOME_ROWS`, groups when grouped) and a keyed read's rows (`MAX_KEYED_ROWS`) are capped, and a query
that would pass a cap is answered with the reason and its count, never from part of its data; a connector that hands
back no typed values is answered the same way. Nothing is kept — the stage is dropped once the answer is read (§3.15's
law: live resolution, never a copy of the warehouse) — and the answer passes the PII, audit and budget post-pass a
single statement passes, on the anchor's connection. Every read is timed and the timings ride the answer, which is how
the latency of a cross-source hop is measured.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from aughor.ontology.cardinality import quote_ident, quote_table

#: Home rows one cross-source answer is computed from, at the object's grain.
MAX_HOME_ROWS = 250_000
#: Rows one keyed read returns, across all its chunks of keys.
MAX_KEYED_ROWS = 250_000
#: Distinct keys per keyed query — one query per chunk, never one per row.
KEY_CHUNK = 1_000
#: Both reads are platform plumbing whose rows never leave the process (`DatabaseConnection.read_typed_rows`); the
#: ANSWER is what passes the post-pass.
_HOME_LABEL = "__objects_home__"
_FAR_LABEL = "__objects_far__"


class CrossSourceRefused(ValueError):
    """A statement that cannot be split at its keyed reads as written; the compiler answers with it as its refusal."""


@dataclass
class KeyedRead:
    """One source the compiler reads by key from another connection than the anchor's."""
    #: The alias its columns carry in the assembled statement.
    alias: str
    #: `link` — a type reached by a to-one link; `binding` — a static binding read onto the object.
    kind: str
    connection_id: str
    table: Optional[str]
    sql: Optional[str]
    #: Its column that holds the key it is read by.
    key: str
    #: The home expression that holds that key (`t0.customer_id`).
    local: str
    #: What the plan and an error call it.
    label: str
    #: The type it reads (a link's target, or the type a binding belongs to).
    target: str
    #: The columns the query reads from it.
    columns: list[str] = field(default_factory=list)
    #: The keyed read whose rows hold the keys this one is read by — a type or a binding reached past a type that is
    #: itself read by key — or "" when the home rows hold them.
    via: str = ""
    #: The aliased (`__r`) FROM fragment its rows come from when they are not its table or keyed SELECT as they stand: a
    #: timeseries binding's latest row per key, a detail binding's rollups, a to-many link or a binding's readings
    #: pre-aggregated per key, the distinct keys an EXISTS tests. One row per key by construction, always.
    base: str = ""
    #: The joins inside its own statement, to the types and bindings a path reaches past it on its connection.
    joins: list[str] = field(default_factory=list)
    #: ``(output name, expression)`` for each column one of those joins supplies.
    projections: list[tuple[str, str]] = field(default_factory=list)

    def need(self, column: str) -> None:
        if column not in self.columns:
            self.columns.append(column)

    def project(self, name: str, expression: str) -> str:
        """A column a join inside this read supplies, read under ``name``; returns the name."""
        if all(existing != name for existing, _ in self.projections):
            self.projections.append((name, expression))
        self.need(name)
        return name

    def from_clause(self) -> str:
        """The FROM fragment a keyed query reads it through, on its own connection."""
        sql = (self.sql or "").strip().rstrip(";").strip()
        if self.joins or self.projections:
            source = self.base or (f"({sql}) AS __r" if sql else f"{quote_table(self.table or '')} AS __r")
            projected = {name for name, _ in self.projections}
            select = [f"__r.{quote_ident(self.key)} AS {quote_ident(self.key)}",
                      *(f"__r.{quote_ident(c)} AS {quote_ident(c)}" for c in self.columns
                        if c != self.key and c not in projected),
                      *(f"{expression} AS {quote_ident(name)}" for name, expression in self.projections)]
            return f"(SELECT {', '.join(select)} FROM {source}{''.join(' ' + j for j in self.joins)}) AS __far"
        if self.base:
            return self.base
        return f"({sql}) AS __far" if sql else quote_table(self.table or "")

    def display(self) -> str:
        """It as a reader sees it in the statement: the connection, schema and table — or its SELECT."""
        sql = (self.sql or "").strip().rstrip(";").strip()
        if self.base or self.joins:
            return f"({self.from_clause()} on {self.connection_id})"
        return f"({sql})" if sql else quote_table(f"{self.connection_id}.{self.table}")


@dataclass
class CrossSourcePlan:
    """A compiled object query split at its keyed reads."""
    #: The statement for the anchor's connection, in its dialect.
    home_sql: str
    #: Each keyed read's alias → the home column that holds the key it is read by.
    key_columns: dict[str, str]
    #: The answer's aggregation, in DuckDB, over `__home` and `__far_<alias>`.
    stage_sql: str
    reads: list[KeyedRead]
    #: Whether the home rows arrive grouped at the key's grain, each with how many rows it holds in `__n`.
    grouped: bool = False

    def to_dict(self) -> dict:
        return {"home_sql": self.home_sql, "stage_sql": self.stage_sql, "grouped": self.grouped,
                "reads": [{"alias": r.alias, "kind": r.kind, "label": r.label, "connection_id": r.connection_id,
                           "source": r.table or "a keyed SELECT", "key": r.key, "by": r.local,
                           "columns": list(r.columns)} for r in self.reads]}


def split(sql: str, reads: dict[str, KeyedRead], *, dialect: str, date_cols: set[str]) -> CrossSourcePlan:
    """Split the statement the compiler assembled (DuckDB, each keyed read joined as ``__far_<alias>``) into the home
    statement and the stage's. Every expression that reads no far column and holds no aggregate is computed at home, as
    its own column; what reads a far column or aggregates stays in the stage, reading those columns."""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception as exc:  # noqa: BLE001 — a statement the compiler assembled and cannot re-read is a defect to name
        raise CrossSourceRefused(f"the assembled query did not parse — a compiler defect, not a query error ({exc})") from exc
    for node in list(tree.find_all(exp.TimestampTrunc)):
        if node.this is not None and node.this.sql(dialect="duckdb") in date_cols:
            node.replace(exp.DateTrunc(this=node.this.copy(), unit=node.args.get("unit")))
    far = set(reads)

    def touches_far(node: exp.Expression) -> bool:
        return any(col.table in far for col in node.find_all(exp.Column))

    home_select: list[exp.Expression] = []
    named: dict[str, str] = {}

    def home_value(node: exp.Expression) -> exp.Column:
        text = node.sql(dialect="duckdb")
        if text not in named:
            named[text] = f"__h{len(named) + 1}"
            home_select.append(exp.alias_(node.copy(), named[text]))
        return exp.column(named[text], table="h")

    def rewrite(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Column) and node.table in far:
            return node
        if (isinstance(node, exp.Condition) and node.find(exp.AggFunc) is None and not touches_far(node)
                and node.find(exp.Column, exp.Subquery, exp.Exists) is not None):
            return home_value(node)
        for key, child in list(node.args.items()):
            if isinstance(child, exp.Expression):
                node.set(key, rewrite(child))
            elif isinstance(child, list):
                node.set(key, [rewrite(c) if isinstance(c, exp.Expression) else c for c in child])
        return node

    key_columns: dict[str, str] = {}
    for alias, read in reads.items():
        if read.via:
            continue                  # keyed by the rows another keyed read returns, never by a home value
        try:
            key_columns[alias] = home_value(sqlglot.parse_one(read.local, read="duckdb")).name
        except Exception as exc:  # noqa: BLE001
            raise CrossSourceRefused(f"{read.label} is read by {read.local!r}, which did not parse ({exc})") from exc
    select = [rewrite(e.copy()) for e in tree.expressions]
    where = tree.args.get("where")
    conjuncts = ([] if where is None else list(where.this.flatten()) if isinstance(where.this, exp.And)
                 else [where.this])
    stage_where = [rewrite(c.copy()) for c in conjuncts if touches_far(c)]
    home_where = [c.copy() for c in conjuncts if not touches_far(c)]

    home = tree.copy()
    home.set("expressions", home_select)
    home.set("joins", [j.copy() for j in tree.args.get("joins") or [] if j.this.alias_or_name not in far])
    home.set("where", exp.Where(this=exp.and_(*home_where)) if home_where else None)
    for arg in ("group", "order", "limit", "having", "qualify", "distinct"):
        home.set(arg, None)

    # a read keyed by another read's rows joins on the key column staged beside that read's rows; reads are in the order
    # the compiler made them, so a read's parent is always joined before it
    shell = sqlglot.parse_one("SELECT 1 FROM __home AS h" + "".join(
        f" LEFT JOIN __far_{alias} AS {alias} ON {read.via or 'h'}.__jk_{alias} = {alias}.__jk"
        for alias, read in reads.items()), read="duckdb")
    stage = tree.copy()
    stage.set("expressions", select)
    stage.set("from_", shell.args["from_"])
    stage.set("joins", shell.args.get("joins"))
    stage.set("where", exp.Where(this=exp.and_(*stage_where)) if stage_where else None)
    grouped = _pre_aggregate(stage, far, set(key_columns.values()))
    if grouped is not None:
        stage, grain, partials = grouped
        # names only: the row-level statement computes every value once, and the groups are keyed by the names it gave
        home = exp.select(*(exp.column(name) for name in grain), *(exp.alias_(e, name) for name, e in partials),
                          exp.alias_(exp.Count(this=exp.Star()), "__n")).from_(home.subquery("r"))
        if grain:
            home = home.group_by(*(exp.column(name) for name in grain))
    try:
        home_sql, stage_sql = home.sql(dialect=dialect or "duckdb"), stage.sql(dialect="duckdb")
    except Exception as exc:  # noqa: BLE001
        raise CrossSourceRefused(f"the split query could not be rendered for {dialect} ({exc})") from exc
    return CrossSourcePlan(home_sql=home_sql, key_columns=key_columns, stage_sql=stage_sql, reads=list(reads.values()),
                           grouped=grouped is not None)


def _pre_aggregate(stage: Any, far: set[str], keys: set[str]) -> Optional[tuple[Any, list[str], list[tuple[str, Any]]]]:
    """The home rows grouped at the key's grain, when the stage can read the answer from groups (O4).

    The grain is every home value the stage reads outside an aggregate — a group, an order, a condition the stage
    applies before it aggregates — and every key a read is joined on. An aggregate over home values alone (COUNT, SUM,
    MIN, MAX, AVG) is computed per group at home and rolled up in the stage: a count or a sum as the sum of the groups', a
    minimum or maximum as itself, an average as the ratio of the summed sums and counts. One that reads a far value, or
    counts distinct values, keeps its home values in the grain; inside a group every one of them is constant — and so is
    every far value, each keyed read being one row per key — so a SUM or COUNT is weighted by the group's rows (`__n`),
    and a MIN, MAX or distinct count reads as it stands.

    Returns ``(the stage rewritten to read groups, the grain's home column names, (name, per-group aggregate) for each
    one computed at home)``, or None — the home rows stay one per object — when the stage aggregates nothing, reads a
    DISTINCT, a window or a FILTER clause, or holds an aggregate no group rolls up."""
    import sqlglot
    from sqlglot import exp
    stage = stage.copy()
    if stage.args.get("distinct") or stage.find(exp.Window) or stage.find(exp.Filter):
        return None
    rolled = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
    aggregates = [node for node in stage.find_all(exp.AggFunc) if node.find_ancestor(exp.AggFunc) is None]
    if not aggregates or not all(isinstance(node, rolled) for node in aggregates):
        return None

    def home_columns(node: Any) -> set[str]:
        return {c.name for c in node.find_all(exp.Column) if c.table == "h"}

    grain = set(keys)
    for column in stage.find_all(exp.Column):
        # a read's join key (`h.__jk_<alias>`) is staged beside the rows from the key column, which is in the grain
        if column.table == "h" and not column.name.startswith("__jk_") and column.find_ancestor(exp.AggFunc) is None:
            grain.add(column.name)
    pushed, weighted = [], []
    for node in aggregates:
        distinct = isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct)
        if distinct or any(c.table in far for c in node.find_all(exp.Column)):
            grain |= home_columns(node)
            weighted.append(node)
        else:
            pushed.append(node)

    partials: list[tuple[str, Any]] = []

    def partial(expression: Any) -> str:
        name = f"__a{len(partials) + 1}"
        unqualified = expression.copy()
        for column in list(unqualified.find_all(exp.Column)):
            column.set("table", None)
        partials.append((name, unqualified))
        return f"h.{name}"

    for node in pushed:
        if isinstance(node, exp.Avg):
            total, count = partial(exp.Sum(this=node.this.copy())), partial(exp.Count(this=node.this.copy()))
            text = f"(CAST(SUM({total}) AS DOUBLE) / NULLIF(SUM({count}), 0))"
        elif isinstance(node, exp.Count):
            text = f"COALESCE(SUM({partial(node)}), 0)"
        else:
            text = f"{node.key.upper()}({partial(node)})"
        node.replace(sqlglot.parse_one(text, read="duckdb"))
    for node in weighted:
        if isinstance(node, (exp.Min, exp.Max)) or (isinstance(node, exp.Count) and isinstance(node.this, exp.Distinct)):
            continue
        argument = node.this.sql(dialect="duckdb")
        if isinstance(node, exp.Sum):
            text = f"SUM(({argument}) * h.__n)"
        elif isinstance(node, exp.Count):
            text = f"COALESCE(SUM(CASE WHEN ({argument}) IS NOT NULL THEN h.__n END), 0)"
        else:
            text = (f"(CAST(SUM(({argument}) * h.__n) AS DOUBLE) / "
                    f"NULLIF(SUM(CASE WHEN ({argument}) IS NOT NULL THEN h.__n END), 0))")
        node.replace(sqlglot.parse_one(text, read="duckdb"))
    order = sorted(grain, key=lambda name: (len(name), name))
    return stage, order, partials


def execute_plan(plan: CrossSourcePlan, *, home_connection_id: str, home_db: Any, open_source: Callable[[str], Any],
                 label: str = "objects", display_sql: str = "") -> tuple[Any, list[dict]]:
    """Run a split query: the home statement, each keyed read, then the answer's aggregation in the stage.

    Returns ``(the answer as a QueryResult, one timing row per read and one for the stage)``. The answer is an error
    result carrying the reason when a gate blocks a connection, a read fails, a cap would be passed, or a far key now
    meets more than one row. ``open_source(connection_id)`` opens a far connection, which is closed here; the home
    connection is the caller's."""
    from aughor.connectors.remote_join import canon_key, fetch_by_keys
    from aughor.db.connection import security_post, security_pre
    started = time.monotonic()
    timings: list[dict] = []
    for connection_id in dict.fromkeys([home_connection_id, *(r.connection_id for r in plan.reads)]):
        blocked = security_pre(connection_id, label, display_sql)
        if blocked is not None:
            return blocked, timings

    clock = time.monotonic()
    # the cap rides the statement, so a query past it stops one row past it instead of reading every row first
    bounded = f"SELECT * FROM ({plan.home_sql}) AS home LIMIT {MAX_HOME_ROWS + 1}"
    result, payload = home_db.read_typed_rows(_HOME_LABEL, bounded, MAX_HOME_ROWS + 1)
    if result.error:
        return _failed(label, display_sql, f"the read on {home_connection_id} failed: {result.error}"), timings
    if payload is None:
        return _failed(label, display_sql, f"{home_connection_id} hands back no typed values, so its rows cannot be "
                                           "joined with another connection's"), timings
    rows = list(payload.get("rows") or [])
    if payload.get("truncated") or len(rows) > MAX_HOME_ROWS:
        # a connection with a cap of its own stops before MAX_HOME_ROWS, and the reason names where it stopped
        what = "groups of the objects" if plan.grouped else "objects"
        where = (f"the {what} this query reads on {home_connection_id} number more than {MAX_HOME_ROWS:,}"
                 if len(rows) > MAX_HOME_ROWS else
                 f"{home_connection_id} stopped at {len(rows):,} of the objects this query reads, a cap of its own")
        return _failed(label, display_sql, f"{where}, and a cross-source answer is never taken from part of them — "
                                           "narrow the query"), timings
    columns = list(result.columns)
    types = [str(t or "") for t in payload.get("types") or []]
    home_timing = {"read": "home", "connection_id": home_connection_id, "rows": len(rows), "ms": _ms(clock)}
    if plan.grouped:
        # how many objects the groups hold — the rows the home read would have carried one by one
        at_n = columns.index("__n")
        home_timing["objects"] = sum(int(row[at_n] or 0) for row in rows)
    timings.append(home_timing)

    index = {name: i for i, name in enumerate(columns)}
    staged: dict[str, tuple[list[str], list[str], list[list]]] = {}
    children: dict[str, list[KeyedRead]] = {}
    for read in plan.reads:
        if read.via:
            children.setdefault(read.via, []).append(read)
    for read in plan.reads:
        if read.via:
            # keyed by the values its parent's rows hold, which were staged before it
            parent_columns, _, parent_rows = staged[read.via]
            at = parent_columns.index(read.local)
            keys = sorted({canon_key(str(row[at])) for row in parent_rows if row[at] is not None})
        else:
            at = index[plan.key_columns[read.alias]]
            keys = sorted({canon_key(str(row[at])) for row in rows if row[at] is not None})
        clock = time.monotonic()
        db = open_source(read.connection_id)
        try:
            far_columns, far_types, far_rows, error = fetch_by_keys(db, read.from_clause(), read.key, read.columns, keys,
                                                                    label=_FAR_LABEL, key_chunk=KEY_CHUNK,
                                                                    max_rows=MAX_KEYED_ROWS)
        finally:
            db.close()
        if error:
            return _failed(label, display_sql, f"{read.label} could not be read on {read.connection_id}: {error}"), timings
        seen: set[str] = set()
        repeated = 0
        for row in far_rows:
            key = canon_key(str(row[0]))
            repeated += key in seen
            seen.add(key)
        if repeated:
            return _failed(label, display_sql, (
                f"{read.label} was measured one row per key, but {repeated:,} of the keys it was read by now meet more "
                "than one row on its connection — measure it again before reading through it")), timings
        staged_columns, staged_types = ["__jk", *far_columns], ["VARCHAR", *far_types]
        staged_rows = [[canon_key(str(row[0])), *row] for row in far_rows]
        for child in children.get(read.alias, []):
            # the key each read past this one is read by, in the form the stage joins on
            at_child = staged_columns.index(child.local)
            staged_columns.append(f"__jk_{child.alias}")
            staged_types.append("VARCHAR")
            staged_rows = [[*row, None if row[at_child] is None else canon_key(str(row[at_child]))] for row in staged_rows]
        staged[read.alias] = (staged_columns, staged_types, staged_rows)
        timings.append({"read": read.alias, "kind": read.kind, "label": read.label, "connection_id": read.connection_id,
                        "source": read.table or "a keyed SELECT", "keys": len(keys), "rows": len(far_rows),
                        "queries": max(1, -(-len(keys) // KEY_CHUNK)), "ms": _ms(clock),
                        **({"via": read.via} if read.via else {})})

    clock = time.monotonic()
    # only a read keyed by the home rows joins on a home key column; a read past another is joined on that read's rows
    home_reads = [read for read in plan.reads if not read.via]
    home_columns = columns + [f"__jk_{read.alias}" for read in home_reads]
    home_types = types + ["VARCHAR"] * len(home_reads)
    at_keys = [index[plan.key_columns[read.alias]] for read in home_reads]
    home_rows = [[*row, *(None if row[at] is None else canon_key(str(row[at])) for at in at_keys)] for row in rows]
    import duckdb
    stage = duckdb.connect(":memory:")
    try:
        stage.register("__home", _arrow_table(home_columns, home_types, home_rows))
        for alias, (far_columns, far_types, far_rows) in staged.items():
            stage.register(f"__far_{alias}", _arrow_table(far_columns, far_types, far_rows))
        cursor = stage.execute(plan.stage_sql)
        out_rows = cursor.fetchall()
        out_columns = [d[0] for d in cursor.description or []]
    except Exception as exc:  # noqa: BLE001 — a stage that cannot run is the answer's error, with the reason
        return _failed(label, display_sql, f"the answer could not be aggregated across its sources: {exc}"[:400]), timings
    finally:
        stage.close()
    timings.append({"read": "stage", "rows": len(out_rows), "ms": _ms(clock)})

    from aughor.control_plane.contracts.execution import QueryResult
    answer = QueryResult(hypothesis_id=label, sql=display_sql, columns=out_columns,
                         rows=[[str(v) if v is not None else "NULL" for v in row] for row in out_rows],
                         row_count=len(out_rows))
    return security_post(home_connection_id, label, display_sql, answer, (time.monotonic() - started) * 1000,
                         also_read=[read.connection_id for read in plan.reads]), timings


def _ms(since: float) -> float:
    return round((time.monotonic() - since) * 1000, 1)


def _failed(label: str, sql: str, error: str) -> Any:
    from aughor.control_plane.contracts.execution import QueryResult
    return QueryResult(hypothesis_id=label, sql=sql, columns=[], rows=[], row_count=0, error=error)


_DECIMAL = re.compile(r"^DECIMAL\((\d+),\s*(\d+)\)$")
_INTEGER_TYPES = frozenset({"BIGINT", "INTEGER", "INT", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT", "UINTEGER",
                            "INT64", "INT8", "INT4"})
_FLOAT_TYPES = frozenset({"DOUBLE", "FLOAT", "REAL", "FLOAT64", "FLOAT8"})


def _empty_type(reported: str) -> Any:
    """The Arrow type of a column that holds no value, from the type its source reported — so an aggregate over it still
    sees a number, a date or a string rather than a column of nothing."""
    import pyarrow as pa
    t = (reported or "").strip().upper()
    decimal = _DECIMAL.match(t)
    if decimal and int(decimal.group(1)) <= 38:
        return pa.decimal128(int(decimal.group(1)), int(decimal.group(2)))
    if t in _INTEGER_TYPES:
        return pa.int64()
    if t in _FLOAT_TYPES:
        return pa.float64()
    if t in ("BOOLEAN", "BOOL"):
        return pa.bool_()
    if t == "DATE":
        return pa.date32()
    if t.startswith("TIMESTAMP"):
        return pa.timestamp("us")
    return pa.string()


def _arrow_column(values: list, reported: str) -> Any:
    import pyarrow as pa
    if all(v is None for v in values):
        return pa.array(values, type=_empty_type(reported))
    try:
        return pa.array(values)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError, OverflowError):
        # a value Arrow cannot type as it stands (a UUID, a mixed column) is staged as its text — an aggregate over it
        # then fails with the engine's own reason instead of adding up something that is not a number
        return pa.array([None if v is None else str(v) for v in values], type=pa.string())


def _arrow_table(columns: list[str], types: list[str], rows: list[list]) -> Any:
    import pyarrow as pa
    arrays = [_arrow_column([row[i] for row in rows], types[i] if i < len(types) else "") for i in range(len(columns))]
    return pa.Table.from_arrays(arrays, names=list(columns))
