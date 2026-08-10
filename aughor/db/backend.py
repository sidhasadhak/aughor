"""One connection seam for every platform store — sqlite today, Postgres by env var.

Every platform store opened its own SQLite file with ``tune(sqlite3.connect(path))``;
the serving architecture (docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md §2) needs the same
stores on a shared Postgres, because a serverless function has no durable disk. This
module is the seam: :func:`connect_store` returns exactly today's tuned SQLite
connection until ``AUGHOR_DB_URL`` names a ``postgres://`` DSN, at which point it
returns a wrapper that presents the *sqlite3 surface the stores already speak* —
``conn.execute`` with ``?`` params, ``sqlite3.Row``-style rows, ``with conn:``
transactions, ``executescript`` — over psycopg2.

**Dialect is translated at the seam, not at 420 call sites.** Store SQL stays written
in SQLite dialect; the wrapper transpiles each statement once via sqlglot (cached) and
patches the constructs sqlglot passes through verbatim (measured on the full 420-
statement corpus, 2026-08-05):

- ``INSERT OR IGNORE`` → ``ON CONFLICT DO NOTHING`` (3 sites)
- ``INSERT OR REPLACE`` → ``ON CONFLICT (pk…) DO UPDATE SET col=EXCLUDED.col`` —
  the conflict target is the table's primary key, read from the catalog once (6 sites)
- bare ``ORDER BY rowid`` → ``ORDER BY ctid`` (1 site; ⚠️ ctid is physical order, so
  a row UPDATE can reorder it where SQLite's rowid would not — acceptable for the
  small registry listing that uses it, recorded here so nobody rediscovers it)
- literal ``%`` doubled so psycopg2's format-paramstyle never reads a stray ``%``
  in SQL text as a directive

**Declared types are mapped to preserve SQLite's string-first semantics.** The house
convention stores ISO strings in ``TIMESTAMP`` columns and ``json.dumps`` text in
``JSON`` columns; on real Postgres those types return ``datetime``/``dict`` objects
and every consumer's ``json.loads``/string comparison breaks. So DDL keeps the
*storage* semantics, not the nominal types: JSON/TIMESTAMP/DATETIME → TEXT,
NUMERIC/BOOLEAN → DOUBLE PRECISION/SMALLINT, and bool params adapt to ints exactly
as sqlite3 adapts them.

**Isolation maps files to schemas.** Each store's own file becomes its own Postgres
schema, derived from the store's *default* filename so production names are stable
across hosts. When a path env var overrides the default — the test suite's isolation
mechanism — the schema name gains a hash of the override, so redirected stores stay
isolated on Postgres exactly as redirected files are on disk.

The 3 ``lastrowid`` call sites use :func:`insert_returning_id`, because Postgres only
answers that question through ``RETURNING``.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

from aughor.db.sqlite_util import default_for_path, tune

#: Env var carrying the shared-database DSN. Unset (or non-postgres) → SQLite files,
#: today's behaviour, byte for byte.
DB_URL_ENV = "AUGHOR_DB_URL"


def is_postgres() -> bool:
    url = os.environ.get(DB_URL_ENV, "")
    return url.startswith("postgres://") or url.startswith("postgresql://")


def connect_store(
    path: Union[str, Path],
    default: Union[str, Path, None] = None,
    *,
    row_factory: bool = False,
    check_same_thread: bool = True,
):
    """A connection to one platform store — the drop-in for ``tune(sqlite3.connect(…))``.

    ``path`` is the store's RESOLVED location (its module ``_DB_PATH``, which tests
    monkeypatch). ``default`` — the store's shipped location — is looked up from
    :func:`aughor.db.sqlite_util.default_for_path` when omitted, because every store
    already declares it through ``resolve_db_path``; pass it only for a store that
    resolves its path some other way. The pair is what lets the Postgres schema
    name be stable in production and isolated under test — see :func:`_schema_name`.
    ``row_factory=True`` applies the store's ``sqlite3.Row`` convention (dict-style
    rows) on either backend.
    """
    if not is_postgres():
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = tune(sqlite3.connect(str(p), check_same_thread=check_same_thread))
        if row_factory:
            conn.row_factory = sqlite3.Row
        return conn
    if default is None:
        default = default_for_path(path)
    return PgConnection(
        os.environ[DB_URL_ENV],
        schema=_schema_name(path, default),
        dict_rows=row_factory,
    )


def _schema_name(path: Union[str, Path], default: Union[str, Path, None]) -> str:
    """The Postgres schema this store lives in.

    ``resolved == default`` — the production case, nothing redirected — names the
    schema from the default's FILENAME alone (``store_monitors``): stable across
    hosts and deploy directories by construction, because the comparison is with
    itself. A redirected path (env var, or a test's monkeypatched ``_DB_PATH``,
    which never passed through resolve_db_path and so has no known default)
    appends a hash of the redirect, so two tests pointing one store at two temp
    paths get two schemas — the same isolation contract the files gave them. A
    Postgres deployment should redirect store paths only knowing this."""
    if default is not None and Path(path) == Path(default):
        stem = re.sub(r"[^a-z0-9_]", "_", Path(default).stem.lower())
        return f"store_{stem}"
    stem = re.sub(r"[^a-z0-9_]", "_", Path(path).stem.lower())
    return f"store_{stem}_{hashlib.sha1(str(path).encode()).hexdigest()[:10]}"


def insert_returning_id(conn, sql: str, params: Sequence = (), *, pk: str = "id") -> int:
    """Run an INSERT and return the new row's integer key on either backend.

    The seam for the ``cursor.lastrowid`` idiom: SQLite answers it from the cursor,
    Postgres only through ``RETURNING`` — and a wrapper cannot know at execute time
    that the caller will want the id, so the want is stated here explicitly."""
    if isinstance(conn, PgConnection):
        cur = conn.execute(f"{sql.rstrip().rstrip(';')} RETURNING {pk}", params)
        return int(cur.fetchone()[0])
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


# ── SQL translation (sqlite dialect → executable-on-postgres) ─────────────────

_XLATE_CACHE: dict[str, str] = {}
_OR_REPLACE_RX = re.compile(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+", re.I)
_OR_IGNORE_RX = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", re.I)
# Any bare/quoted `rowid` reference — no store declares a column of that name, so
# every occurrence is sqlite's implicit key, and mid-ORDER-BY uses exist
# (`ORDER BY start_time DESC, rowid DESC` in the ledger's task_history).
_ROWID_RX = re.compile(r'"?\browid\b"?', re.I)
_INSERT_COLS_RX = re.compile(r'^\s*INSERT\s+INTO\s+("?[\w.]+"?)\s*\(([^)]*)\)', re.I)

# Declared type → what preserves sqlite's storage semantics on Postgres. Keyed by
# sqlglot's DType enum VALUE (dt.this.value), never by rendered SQL — the sqlite
# generator normalizes on render (BOOLEAN prints as INTEGER), which would dodge
# the map and let a real BOOLEAN column reach Postgres.
_TYPE_MAP = {
    "JSON": "TEXT", "JSONB": "TEXT", "TIMESTAMP": "TEXT", "TIMESTAMPTZ": "TEXT",
    "DATETIME": "TEXT", "DECIMAL": "DOUBLE PRECISION", "BOOLEAN": "SMALLINT",
    "FLOAT": "DOUBLE PRECISION", "DOUBLE": "DOUBLE PRECISION",
}


_NAMED_PH_RX = re.compile(r"%\((\w+)\)s")


def _pg_escape_percents(sql: str) -> str:
    """Double every ``%`` that is not a placeholder, literal-aware.

    psycopg2's format paramstyle reads any ``%`` in the statement as a directive, so
    a ``LIKE '%…%'`` literal (or a modulo) that survives transpile intact would raise
    at execute. Two placeholder shapes must survive: ``%s`` (from qmark params) and
    ``%(name)s`` (sqlglot's rendering of sqlite's ``:name`` params). Inside
    single-quoted literals every ``%`` doubles — a placeholder-shaped sequence there
    is text, not a placeholder."""
    out: list[str] = []
    in_str = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            # '' inside a literal is an escaped quote, not a close
            if in_str and i + 1 < n and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_str = not in_str
            out.append(ch)
        elif ch == "%":
            if not in_str:
                if i + 1 < n and sql[i + 1] == "s":
                    out.append("%s")
                    i += 2
                    continue
                m = _NAMED_PH_RX.match(sql, i)
                if m:
                    out.append(m.group(0))
                    i = m.end()
                    continue
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _map_types(expression):
    """Rewrite declared column types on a parsed statement (see _TYPE_MAP)."""
    from sqlglot import exp

    for dt in expression.find_all(exp.DataType):
        mapped = _TYPE_MAP.get(str(getattr(dt.this, "value", "")).upper())
        if mapped:
            dt.replace(exp.DataType.build(mapped, dialect="postgres"))
    return expression


def _qualify_on_conflict(expression):
    """Qualify bare columns on the RHS of ``ON CONFLICT … DO UPDATE SET``.

    SQLite reads ``SET count = count + 1`` as the current row's value; Postgres
    rejects the bare name as ambiguous (current row vs the EXCLUDED proposal). The
    sqlite meaning is the table's — so that is the qualification written. LHS names
    stay bare, as Postgres requires."""
    from sqlglot import exp

    if not isinstance(expression, exp.Insert):
        return expression
    conflict = expression.find(exp.OnConflict)
    if conflict is None:
        return expression
    table = expression.find(exp.Table)
    if table is None or not table.name:
        return expression
    for eq in conflict.args.get("expressions") or []:
        rhs = eq.args.get("expression")
        if rhs is None:
            continue
        for col in rhs.find_all(exp.Column):
            if not col.table:
                col.set("table", exp.to_identifier(table.name))
    return expression


def translate(sql: str) -> str:
    """One sqlite-dialect statement (or script) → executable Postgres SQL. Cached."""
    hit = _XLATE_CACHE.get(sql)
    if hit is not None:
        return hit

    import sqlglot

    or_replace = bool(_OR_REPLACE_RX.match(sql))
    work = _OR_REPLACE_RX.sub("INSERT INTO ", sql)
    or_ignore = bool(_OR_IGNORE_RX.match(work))
    work = _OR_IGNORE_RX.sub("INSERT INTO ", work)

    statements = []
    for parsed in sqlglot.parse(work, read="sqlite"):
        if parsed is None:
            continue
        # identify=True quotes every identifier, which retires the whole
        # reserved-word class at once — the overlay store has a column literally
        # named `column`, legal bare in sqlite and a syntax error bare in Postgres.
        # Store identifiers are snake_case throughout, so quoting cannot change
        # which object a name resolves to.
        statements.append(
            _qualify_on_conflict(_map_types(parsed)).sql(dialect="postgres", identify=True))
    out = ";\n".join(statements)

    if or_ignore:
        out = f"{out} ON CONFLICT DO NOTHING"
    elif or_replace:
        out = f"{out} {_ON_CONFLICT_SENTINEL}"
    out = _ROWID_RX.sub("ctid", out)
    out = _pg_escape_percents(out)
    _XLATE_CACHE[sql] = out
    return out


#: Placeholder the connection expands per-table once it can read the primary key —
#: translate() is deliberately connection-free so its cache stays global.
_ON_CONFLICT_SENTINEL = "/*AUGHOR_ON_CONFLICT_REPLACE*/"


# ── the Postgres connection, wearing sqlite3's interface ─────────────────────

class PgRow(list):
    """A row that answers both ``row[0]`` and ``row["col"]`` — the sqlite3.Row
    contract the stores rely on — plus ``.keys()`` for dict(row)."""

    __slots__ = ("_index",)

    def __init__(self, values: Sequence, index: dict[str, int]):
        super().__init__(values)
        self._index = index

    def __getitem__(self, key):
        if isinstance(key, str):
            return super().__getitem__(self._index[key])
        return super().__getitem__(key)

    def keys(self):
        return list(self._index)


class PgCursor:
    """The slice of sqlite3.Cursor the stores use: execute-and-fetch, iteration,
    ``rowcount``, ``description``. ``lastrowid`` deliberately raises — the portable
    seam for that idiom is :func:`insert_returning_id`."""

    def __init__(self, conn: "PgConnection", cursor):
        self._conn = conn
        self._cur = cursor

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    @property
    def lastrowid(self):
        raise NotImplementedError(
            "lastrowid is a SQLite-ism; use aughor.db.backend.insert_returning_id()")

    def _wrap(self, row):
        if row is None or not self._conn._dict_rows:
            return row
        index = {d[0]: i for i, d in enumerate(self._cur.description or [])}
        return PgRow(row, index)

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [self._wrap(r) for r in self._cur.fetchall()]

    def fetchmany(self, size: int = 1000):
        return [self._wrap(r) for r in self._cur.fetchmany(size)]

    def __iter__(self) -> Iterator:
        for row in self._cur:
            yield self._wrap(row)

    def close(self) -> None:
        self._cur.close()


class _StaticCursor:
    """A cursor over precomputed rows — what PRAGMA answers become on Postgres."""

    rowcount = 0
    description = None

    def __init__(self, rows: Optional[list] = None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class PgConnection:
    """One store's connection to the shared Postgres, speaking sqlite3's dialect
    and interface. Each instance pins ``search_path`` to the store's own schema, so
    two stores' identically-named tables can never collide — files kept stores
    apart on disk; schemas keep them apart in one database."""

    _pk_cache: dict[str, list[str]] = {}
    _pk_lock = threading.Lock()

    def __init__(self, url: str, *, schema: str, dict_rows: bool = False):
        import psycopg2

        from aughor.db.dsn import split_dsn

        self._dict_rows = dict_rows
        self._schema = schema
        # Query params lifted into kwargs — psycopg2's URI parser rejects a value
        # containing `=` and any parameter it does not know, and this is the connection
        # the whole platform's state rides on. See aughor/db/dsn.py.
        base, params, _dropped = split_dsn(url)
        self._pg = psycopg2.connect(base, **params)
        with self._pg.cursor() as cur:
            # Identifier built from a sanitized stem + hex hash — not user input —
            # but quote it anyway so nothing depends on that remaining true.
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
        self._pg.commit()

    # -- sqlite3.Connection surface --------------------------------------------

    def execute(self, sql: str, params: Sequence = ()) -> PgCursor:
        stripped = sql.lstrip()
        if stripped.upper().startswith("PRAGMA"):
            return self._pragma(stripped)  # type: ignore[return-value]
        translated = translate(sql)
        if _ON_CONFLICT_SENTINEL in translated:
            translated = self._expand_on_conflict(translated)
        cur = self._pg.cursor()
        try:
            cur.execute(translated, _adapt_params(params))
        except Exception:
            cur.close()
            raise
        return PgCursor(self, cur)

    def executemany(self, sql: str, seq_of_params) -> PgCursor:
        translated = translate(sql)
        if _ON_CONFLICT_SENTINEL in translated:
            translated = self._expand_on_conflict(translated)
        cur = self._pg.cursor()
        try:
            cur.executemany(translated, [_adapt_params(ps) for ps in seq_of_params])
        except Exception:
            cur.close()
            raise
        return PgCursor(self, cur)

    def executescript(self, script: str) -> None:
        # sqlite3.executescript commits the open transaction first; matching that
        # exactly keeps DDL-at-open behaviour identical across backends.
        self._pg.commit()
        for statement in [s for s in translate(script).split(";\n") if s.strip()]:
            self.execute(statement)
        self._pg.commit()

    def commit(self) -> None:
        self._pg.commit()

    def rollback(self) -> None:
        self._pg.rollback()

    def close(self) -> None:
        self._pg.close()

    def cursor(self) -> PgCursor:
        return PgCursor(self, self._pg.cursor())

    @property
    def row_factory(self):
        return sqlite3.Row if self._dict_rows else None

    @row_factory.setter
    def row_factory(self, value) -> None:
        # Stores assign `conn.row_factory = sqlite3.Row` after connecting; honour it.
        self._dict_rows = value is not None

    def __enter__(self) -> "PgConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # sqlite3 semantics: commit on success, roll back on error — never close.
        if exc_type is None:
            self._pg.commit()
        else:
            self._pg.rollback()

    # -- PRAGMA: two are load-bearing, the rest no-op ---------------------------

    _UV_READ_RX = re.compile(r"PRAGMA\s+user_version\s*$", re.I)
    _UV_WRITE_RX = re.compile(r"PRAGMA\s+user_version\s*=\s*(\d+)", re.I)
    _TABLE_INFO_RX = re.compile(r"PRAGMA\s+table_info\s*\(\s*[\"']?(\w+)[\"']?\s*\)", re.I)

    def _pragma(self, stripped: str) -> _StaticCursor:
        """Most PRAGMAs are SQLite tuning and no-op here — but two carry state the
        migration framework runs on, and a silent no-op for those is a wrong answer,
        not a harmless one: ``user_version`` read as 0 forever re-applies every
        migration on every connect, and an empty ``table_info`` makes
        ``add_column_if_missing`` re-ALTER into a duplicate-column crash. Both are
        answered truthfully — the version from a per-schema meta table, the columns
        from the catalog in sqlite's row shape."""
        m = self._UV_WRITE_RX.match(stripped)
        if m:
            cur = self._pg.cursor()
            try:
                cur.execute("CREATE TABLE IF NOT EXISTS _aughor_meta (k TEXT PRIMARY KEY, v TEXT)")
                cur.execute(
                    "INSERT INTO _aughor_meta (k, v) VALUES ('user_version', %s) "
                    "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v", (m.group(1),))
            finally:
                cur.close()
            return _StaticCursor()
        if self._UV_READ_RX.match(stripped):
            cur = self._pg.cursor()
            try:
                # Existence probed with to_regclass, not try/except — a failed SELECT
                # aborts the enclosing transaction, and this read must never cost the
                # caller whatever else that transaction holds.
                cur.execute(f"SELECT to_regclass('\"{self._schema}\"._aughor_meta')")
                row = None
                if cur.fetchone()[0] is not None:
                    cur.execute("SELECT v FROM _aughor_meta WHERE k = 'user_version'")
                    row = cur.fetchone()
            finally:
                cur.close()
            return _StaticCursor([(int(row[0]) if row else 0,)])
        m = self._TABLE_INFO_RX.match(stripped)
        if m:
            table = m.group(1)
            cur = self._pg.cursor()
            try:
                cur.execute(
                    """SELECT ordinal_position - 1, column_name, data_type,
                              CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END,
                              column_default
                       FROM information_schema.columns
                       WHERE table_schema = %s AND table_name = %s
                       ORDER BY ordinal_position""", (self._schema, table))
                cols = cur.fetchall()
            finally:
                cur.close()
            pk = self._primary_key(table, missing_ok=True) if cols else []
            rows = [(cid, name, dtype, notnull, dflt,
                     pk.index(name) + 1 if name in pk else 0)
                    for cid, name, dtype, notnull, dflt in cols]
            return _StaticCursor(rows)
        return _StaticCursor()

    # -- INSERT OR REPLACE expansion -------------------------------------------

    def _expand_on_conflict(self, translated: str) -> str:
        """Fill the OR-REPLACE sentinel with this table's real conflict clause.

        SQLite's REPLACE upserts on the primary key; the equivalent needs that key
        named. Read once per table from the catalog (all six OR REPLACE statements
        in the codebase name their column lists, so EXCLUDED covers every column
        the statement sets)."""
        m = _INSERT_COLS_RX.match(translated)
        if not m:
            raise ValueError(f"INSERT OR REPLACE without a column list: {translated[:80]}")
        table = m.group(1).strip('"')
        cols = [c.strip().strip('"') for c in m.group(2).split(",")]
        pk = self._primary_key(table)
        updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in pk)
        target = ", ".join(f'"{c}"' for c in pk)
        clause = (f"ON CONFLICT ({target}) DO UPDATE SET {updates}" if updates
                  else f"ON CONFLICT ({target}) DO NOTHING")
        return translated.replace(_ON_CONFLICT_SENTINEL, clause)

    def _primary_key(self, table: str, *, missing_ok: bool = False) -> list[str]:
        key = f"{self._schema}.{table}"
        with self._pk_lock:
            hit = self._pk_cache.get(key)
        if hit is not None:
            return hit
        cur = self._pg.cursor()
        try:
            cur.execute(
                """SELECT a.attname
                   FROM pg_index i
                   JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                   WHERE i.indrelid = %s::regclass AND i.indisprimary
                   ORDER BY a.attnum""",
                (f'"{self._schema}"."{table}"',),
            )
            pk = [r[0] for r in cur.fetchall()]
        finally:
            cur.close()
        if not pk:
            if missing_ok:
                return []
            raise ValueError(f"INSERT OR REPLACE on {table}, which has no primary key")
        with self._pk_lock:
            self._pk_cache[key] = pk
        return pk


def _adapt(value: Any) -> Any:
    """Match sqlite3's parameter adaptation: bools are stored as integers."""
    if isinstance(value, bool):
        return int(value)
    return value


def _adapt_params(params) -> Any:
    """Adapt a parameter set, keeping its SHAPE — sqlite's ``:name`` style becomes
    psycopg2's ``%(name)s``, whose params must stay a dict; iterating one as a
    sequence would silently bind its keys."""
    if isinstance(params, dict):
        return {k: _adapt(v) for k, v in params.items()}
    return tuple(_adapt(p) for p in params)
