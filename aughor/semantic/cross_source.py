"""ON-8 — an object query whose sources live on more than one connection (ROADMAP §3.15, the second movement).

The compiler (`aughor.semantic.object_query`) assembles one statement for one connection. In an organisation's ontology
a query may cross to a type or a binding that lives on another connection, and no statement sees two. So the compiler
marks each such source as a KEYED READ — a to-one link to a type on another connection, or a static binding read from
one — hanging off the query's own FROM level, and this module runs what it assembled in three parts:

1. **Home.** Everything that does not touch another connection runs on the anchor's connection as one statement, at
   the object's grain: the filters, the joins and pre-aggregated links that stay on that connection, and each value an
   aggregate or a group reads, computed per row — with the keys every keyed read needs projected beside them.
2. **Keyed reads.** Each far source is read through the batched-foreach engine by exactly the distinct keys the home
   rows hold, one query per chunk of keys (`remote_join.fetch_by_keys`), every value typed as its source holds it.
3. **Stage.** Both land in an in-process DuckDB for this one answer, joined on the canonical key form the engine and
   the measurement both key on, and the compiler's own SELECT, WHERE, GROUP BY and ORDER BY run there, each home value
   read from the column it was computed into.

Correct by construction for the reasons the single statement is. Every keyed read is to-one by measurement — a link
measured N:1 or 1:1 from where the query stands, a binding measured one row per object — so the stage's join cannot
multiply the home rows, and a far key that now meets two rows is refused rather than joined. The aggregation is the
compiler's own over the same rows, so an average is still a ratio of sums and a distinct count still counts values.

Bounded and honest: the home rows (`MAX_HOME_ROWS`) and a keyed read's rows (`MAX_KEYED_ROWS`) are capped, and a query
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

from aughor.ontology.cardinality import quote_table

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

    def need(self, column: str) -> None:
        if column not in self.columns:
            self.columns.append(column)

    def from_clause(self) -> str:
        """The FROM fragment a keyed query reads it through, on its own connection."""
        sql = (self.sql or "").strip().rstrip(";").strip()
        return f"({sql}) AS __far" if sql else quote_table(self.table or "")

    def display(self) -> str:
        """It as a reader sees it in the statement: the connection, schema and table — or its SELECT."""
        sql = (self.sql or "").strip().rstrip(";").strip()
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

    def to_dict(self) -> dict:
        return {"home_sql": self.home_sql, "stage_sql": self.stage_sql,
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

    shell = sqlglot.parse_one("SELECT 1 FROM __home AS h" + "".join(
        f" LEFT JOIN __far_{alias} AS {alias} ON h.__jk_{alias} = {alias}.__jk" for alias in reads), read="duckdb")
    stage = tree.copy()
    stage.set("expressions", select)
    stage.set("from_", shell.args["from_"])
    stage.set("joins", shell.args.get("joins"))
    stage.set("where", exp.Where(this=exp.and_(*stage_where)) if stage_where else None)
    try:
        home_sql, stage_sql = home.sql(dialect=dialect or "duckdb"), stage.sql(dialect="duckdb")
    except Exception as exc:  # noqa: BLE001
        raise CrossSourceRefused(f"the split query could not be rendered for {dialect} ({exc})") from exc
    return CrossSourcePlan(home_sql=home_sql, key_columns=key_columns, stage_sql=stage_sql, reads=list(reads.values()))


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
        return _failed(label, display_sql, f"the objects this query reads on {home_connection_id} number more than "
                                           f"{MAX_HOME_ROWS:,}, and a cross-source answer is never taken from part of "
                                           "them — narrow the query"), timings
    columns = list(result.columns)
    types = [str(t or "") for t in payload.get("types") or []]
    timings.append({"read": "home", "connection_id": home_connection_id, "rows": len(rows), "ms": _ms(clock)})

    index = {name: i for i, name in enumerate(columns)}
    staged: dict[str, tuple[list[str], list[str], list[list]]] = {}
    for read in plan.reads:
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
        staged[read.alias] = (["__jk", *far_columns], ["VARCHAR", *far_types],
                              [[canon_key(str(row[0])), *row] for row in far_rows])
        timings.append({"read": read.alias, "kind": read.kind, "label": read.label, "connection_id": read.connection_id,
                        "source": read.table or "a keyed SELECT", "keys": len(keys), "rows": len(far_rows),
                        "queries": max(1, -(-len(keys) // KEY_CHUNK)), "ms": _ms(clock)})

    clock = time.monotonic()
    home_columns = columns + [f"__jk_{read.alias}" for read in plan.reads]
    home_types = types + ["VARCHAR"] * len(plan.reads)
    at_keys = [index[plan.key_columns[read.alias]] for read in plan.reads]
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
