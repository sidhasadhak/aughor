"""DE-3c (ROADMAP §3.51) — typed metadata: columns, primary keys, foreign keys, comments.

Every engine answers each of the four facts *supported*, *unsupported* or *unknown* — the row
is on its declaration (`connectors/declarations.py`, `metadata_facts`) — and this module READS
what is supported: declared keys and comments, through the connection's own door, in the
engine's own catalog spelling. Before DE-3c no engine read a declared key or a comment at all;
SQLite and DuckDB fetched the key flag and dropped it (finding 8 of the dbx study).

The answer is typed so a reader can tell the three apart: a result with no keys from an engine
that *supports* them means the schema declares none; from one that does not, that the engine
has no such fact; from one *unknown*, that the platform has not read it — and a read that
failed says so, with the error, rather than coming back empty.

Declared foreign keys are the join inference's strongest signal (`tools/schema.join_map_for`)
and are still checked against values, like every other edge.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from aughor.connectors.declarations import BY_TYPE, ENGINES, METADATA_FACTS

KEY_FACTS = ("primary_keys", "foreign_keys")


@dataclass(frozen=True)
class DeclaredKey:
    table: str
    columns: tuple[str, ...]
    kind: str                                   # "primary" | "foreign"
    ref_table: Optional[str] = None
    ref_columns: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"table": self.table, "columns": list(self.columns), "kind": self.kind,
                "ref_table": self.ref_table, "ref_columns": list(self.ref_columns)}


@dataclass
class MetadataRead:
    engine: str
    strategy: str
    facts: dict[str, str]                       # fact → supported | unsupported | unknown
    detail: dict[str, str]                      # fact → why, when not supported or when the read failed
    keys: list[DeclaredKey] = field(default_factory=list)
    comments: dict[str, str] = field(default_factory=dict)   # "table" or "table.column" → text

    @property
    def primary_keys(self) -> list[DeclaredKey]:
        return [k for k in self.keys if k.kind == "primary"]

    @property
    def foreign_keys(self) -> list[DeclaredKey]:
        return [k for k in self.keys if k.kind == "foreign"]

    def as_dict(self) -> dict:
        return {"engine": self.engine, "strategy": self.strategy, "facts": dict(self.facts),
                "detail": {k: v for k, v in self.detail.items() if v},
                "keys": [k.as_dict() for k in self.keys], "comments": dict(self.comments)}


# ── which engine a connection is ──────────────────────────────────────────────────

_TYPE_BY_CLASS: dict[str, str] = {d.connector.rsplit(":", 1)[1]: d.type for d in ENGINES if d.connector}
_TYPE_BY_CLASS.update({"DuckDBConnection": "duckdb", "AughorOpsConnection": "duckdb", "PostgresConnection": "postgres"})


def engine_type_of(conn) -> Optional[str]:
    """The declared engine type of a connection object, by its class (the registered name, or
    the two built-ins); None when the class is unknown — a dialect alone does not say whose
    catalog is behind it, so an unknown class is answered `unknown`, not guessed."""
    for cls in type(conn).__mro__:
        if cls.__name__ in _TYPE_BY_CLASS:
            return _TYPE_BY_CLASS[cls.__name__]
    return None


# ── the read ─────────────────────────────────────────────────────────────────────

def _rows(conn, sql: str) -> list[list]:
    """Run a catalog read through the connection's door as the platform's own statement, and
    give back rows with SQL NULL as None. No dialect hint: the door takes a hint only as
    `duckdb` (the platform's authored spelling), and each recipe below is already spelled for
    its engine's catalog and survives the door's translation step (measured on SQLite)."""
    res = conn.execute("__metadata__", sql, internal=True)
    if getattr(res, "error", None):
        raise RuntimeError(res.error)
    return [[None if v in (None, "NULL") else v for v in row] for row in (res.rows or [])]


def _name(schema: Optional[str], table: str) -> str:
    return f"{schema}.{table}" if schema and schema not in ("main", "public") else table


def _split(csv: Optional[str]) -> tuple[str, ...]:
    return tuple(c for c in (csv or "").split(",") if c)


def _read_duckdb(conn, read: MetadataRead) -> None:
    for schema, table, kind, cols, ref_t, ref_cols in _rows(conn, """
        SELECT schema_name, table_name, constraint_type, array_to_string(constraint_column_names, ','),
               coalesce(referenced_table, ''), array_to_string(referenced_column_names, ',')
        FROM duckdb_constraints()
        WHERE constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
          AND schema_name NOT IN ('information_schema', 'pg_catalog')
        ORDER BY 1, 2, 3"""):
        read.keys.append(DeclaredKey(_name(schema, table), _split(cols),
                                     "primary" if str(kind).startswith("PRIMARY") else "foreign",
                                     ref_t or None, _split(ref_cols)))
    for schema, table, col, comment in _rows(conn, """
        SELECT schema_name, table_name, column_name, comment FROM duckdb_columns()
        WHERE comment IS NOT NULL AND schema_name NOT IN ('information_schema', 'pg_catalog')"""):
        read.comments[f"{_name(schema, table)}.{col}"] = str(comment)
    for schema, table, comment in _rows(conn, """
        SELECT schema_name, table_name, comment FROM duckdb_tables()
        WHERE comment IS NOT NULL AND schema_name NOT IN ('information_schema', 'pg_catalog')"""):
        read.comments[_name(schema, table)] = str(comment)


def _read_sqlite(conn, read: MetadataRead) -> None:
    pk: dict[str, list[tuple[int, str]]] = {}
    for table, col, pos in _rows(conn, """
        SELECT m.name, p.name, p.pk FROM sqlite_master m JOIN pragma_table_info(m.name) p
        WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%' AND p.pk > 0 ORDER BY m.name, p.pk"""):
        pk.setdefault(str(table), []).append((int(pos), str(col)))
    for table, cols in pk.items():
        read.keys.append(DeclaredKey(table, tuple(c for _p, c in sorted(cols)), "primary"))
    fk: dict[tuple[str, int], dict] = {}
    for table, fid, seq, col, ref_t, ref_c in _rows(conn, """
        SELECT m.name, f.id, f.seq, f."from", f."table", f."to" FROM sqlite_master m
        JOIN pragma_foreign_key_list(m.name) f WHERE m.type = 'table' ORDER BY m.name, f.id, f.seq"""):
        slot = fk.setdefault((str(table), int(fid)), {"cols": [], "ref": str(ref_t), "ref_cols": []})
        slot["cols"].append(str(col))
        slot["ref_cols"].append(str(ref_c) if ref_c is not None else "")
    for (table, _fid), slot in fk.items():
        read.keys.append(DeclaredKey(table, tuple(slot["cols"]), "foreign", slot["ref"],
                                     tuple(c for c in slot["ref_cols"] if c)))


def _read_postgres(conn, read: MetadataRead) -> None:
    grouped: dict[tuple, dict] = {}
    for schema, table, kind, cname, col, _pos, ref_t, ref_c in _rows(conn, """
        SELECT tc.table_schema, tc.table_name, tc.constraint_type, tc.constraint_name, kcu.column_name,
               kcu.ordinal_position, ccu.table_name, ccu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name AND tc.constraint_type = 'FOREIGN KEY'
        WHERE tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
          AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY 1, 2, 4, 6"""):
        slot = grouped.setdefault((schema, table, cname), {"kind": kind, "cols": [], "ref": ref_t, "ref_cols": []})
        if col not in slot["cols"]:
            slot["cols"].append(str(col))
        if ref_c and ref_c not in slot["ref_cols"]:
            slot["ref_cols"].append(str(ref_c))
    for (schema, table, _c), slot in grouped.items():
        read.keys.append(DeclaredKey(_name(schema, table), tuple(slot["cols"]),
                                     "primary" if str(slot["kind"]).startswith("PRIMARY") else "foreign",
                                     slot["ref"] or None, tuple(slot["ref_cols"])))
    for schema, table, col, comment in _rows(conn, """
        SELECT n.nspname, c.relname, a.attname, col_description(a.attrelid, a.attnum)
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r', 'v', 'm', 'p')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND col_description(a.attrelid, a.attnum) IS NOT NULL"""):
        read.comments[f"{_name(schema, table)}.{col}"] = str(comment)
    for schema, table, comment in _rows(conn, """
        SELECT n.nspname, c.relname, obj_description(c.oid, 'pg_class')
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'v', 'm', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND obj_description(c.oid, 'pg_class') IS NOT NULL"""):
        read.comments[_name(schema, table)] = str(comment)


def _read_mysql(conn, read: MetadataRead) -> None:
    grouped: dict[tuple, dict] = {}
    for schema, table, kind, cname, col, _pos, ref_t, ref_c in _rows(conn, """
        SELECT kcu.TABLE_SCHEMA, kcu.TABLE_NAME, tc.CONSTRAINT_TYPE, kcu.CONSTRAINT_NAME, kcu.COLUMN_NAME,
               kcu.ORDINAL_POSITION, kcu.REFERENCED_TABLE_NAME, kcu.REFERENCED_COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE kcu
        JOIN information_schema.TABLE_CONSTRAINTS tc
          ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
         AND tc.TABLE_NAME = kcu.TABLE_NAME
        WHERE tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'FOREIGN KEY') AND kcu.TABLE_SCHEMA = DATABASE()
        ORDER BY 1, 2, 4, 6"""):
        slot = grouped.setdefault((table, cname), {"kind": kind, "cols": [], "ref": ref_t, "ref_cols": []})
        slot["cols"].append(str(col))
        if ref_c:
            slot["ref_cols"].append(str(ref_c))
    for (table, _c), slot in grouped.items():
        read.keys.append(DeclaredKey(str(table), tuple(slot["cols"]),
                                     "primary" if str(slot["kind"]).startswith("PRIMARY") else "foreign",
                                     slot["ref"] or None, tuple(slot["ref_cols"])))
    for table, col, comment in _rows(conn, """
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_COMMENT FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_COMMENT <> ''"""):
        read.comments[f"{table}.{col}"] = str(comment)
    for table, comment in _rows(conn, """
        SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_COMMENT <> ''"""):
        read.comments[str(table)] = str(comment)


#: dialect → the recipe that reads what the declaration marks supported.
_RECIPES = {"duckdb": _read_duckdb, "sqlite": _read_sqlite, "postgres": _read_postgres, "mysql": _read_mysql}


def read_declared_metadata(conn, *, cache_key: Optional[str] = None, ttl: float = 300.0) -> MetadataRead:
    """The typed read for one connection. Never raises: a recipe that fails turns the facts it
    was to supply into ``unknown`` with the error as the detail."""
    if cache_key:
        hit = _CACHE.get(cache_key)
        if hit and (time.monotonic() - hit[0]) < ttl:
            return hit[1]
    etype = engine_type_of(conn)
    decl = BY_TYPE.get(etype) if etype else None
    facts = dict(decl.metadata_facts) if decl else {f: "unknown" for f in METADATA_FACTS}
    why = decl.metadata_detail if decl else "no declaration for this connection's class"
    detail = {f: ("" if facts[f] == "supported" else why) for f in METADATA_FACTS}
    read = MetadataRead(engine=etype or str(getattr(conn, "dialect", "") or "unknown"),
                        strategy=(decl.metadata_strategy if decl else "unknown"), facts=facts, detail=detail)

    wanted = [f for f in (*KEY_FACTS, "comments") if facts[f] == "supported"]
    if wanted:
        recipe = _RECIPES.get(str(decl.dialect)) if decl else None
        if recipe is None:
            for f in wanted:
                read.facts[f] = "unknown"
                read.detail[f] = f"declared supported but no recipe reads the {decl.dialect!r} catalog"
        else:
            try:
                recipe(conn, read)
            except Exception as exc:
                read.keys.clear()
                read.comments.clear()
                for f in wanted:
                    read.facts[f] = "unknown"
                    read.detail[f] = f"read failed: {type(exc).__name__}: {str(exc)[:160]}"
    if cache_key:
        _CACHE[cache_key] = (time.monotonic(), read)
    return read


_CACHE: dict[str, tuple[float, MetadataRead]] = {}


def invalidate(cache_key: str) -> None:
    _CACHE.pop(cache_key, None)


def declared_join_candidates(read: MetadataRead, table_cols: dict[str, list[str]]) -> list[dict]:
    """Declared foreign keys as join-map edges — ``{t1, c1, t2, c2, match: "declared"}``, the FK
    side first as every consumer reads it — for the tables in ``table_cols`` (matched by bare
    name, since a schema text may spell tables bare or qualified)."""
    def bare(t: str) -> str:
        return str(t).split(".")[-1].strip('"').lower()

    by_bare: dict[str, str] = {}
    for t in table_cols:
        by_bare.setdefault(bare(t), t)
    out: list[dict] = []
    for k in read.foreign_keys:
        if not k.ref_table or not k.ref_columns or len(k.ref_columns) != len(k.columns):
            continue
        t1 = by_bare.get(bare(k.table))
        t2 = by_bare.get(bare(k.ref_table))
        if not t1 or not t2 or t1 == t2:
            continue
        cols1 = {c.lower(): c for c in table_cols.get(t1, [])}
        cols2 = {c.lower(): c for c in table_cols.get(t2, [])}
        for c1, c2 in zip(k.columns, k.ref_columns):
            if c1.lower() in cols1 and c2.lower() in cols2:
                out.append({"t1": t1, "c1": cols1[c1.lower()], "t2": t2, "c2": cols2[c2.lower()], "match": "declared"})
    return out
