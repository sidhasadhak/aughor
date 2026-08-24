"""SQLite connector — read-only access to a local SQLite database file.

Unlike the DuckDB-backed file connectors, this is a *genuine* SQLite engine
(``dialect = "sqlite"``): it reads through Python's stdlib ``sqlite3`` so schema
introspection (``sqlite_master`` / ``PRAGMA table_info``) and query execution
behave exactly as the file does natively — including SQLite's dynamic typing.
DuckDB-flavoured SQL the agent generates is transpiled to SQLite via sqlglot in
``translate()`` before execution.

The connector mirrors DuckDBConnection's two-tier schema design:
  - get_schema():        fast, hot-path — structural schema + glossary + joins
                         + annotations + exploration findings (no DB profiling,
                         no LLM).
  - build_intelligence(): heavy, background — value profiles + structural/semantic
                         ontology, reusing the same engine-agnostic pipeline.

DSN forms accepted: ``/path/to/file.sqlite``, ``file.db``, or ``sqlite:///path``.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from aughor.db.single_flight import single_flight_build
from aughor.connectors.base import Connector
from aughor.db.connection import MAX_ROWS, QueryResult
from aughor.kernel.errors import tolerate


def _dsn_to_path(dsn: str) -> str:
    """Normalise a DSN to a filesystem path (or ':memory:')."""
    d = (dsn or "").strip()
    for prefix in ("sqlite:///", "sqlite://", "file:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
            break
    return d or ":memory:"


class SQLiteConnection(Connector):
    connector_category = "file"
    dialect = "sqlite"

    def __init__(
        self,
        dsn: str = "",
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self._dsn = dsn
        self._path = _dsn_to_path(dsn)
        # SQLite's only real namespace is the attached-database name ('main').
        self._schema_name = schema_name or "main"
        self._connection_id = connection_id
        self._conn: sqlite3.Connection | None = None
        self.last_build: dict = {"ok": True, "stage": None, "error": None}
        self._connect()

    def _connect(self) -> None:
        p = self._path
        if p == ":memory:":
            self._conn = sqlite3.connect(p, check_same_thread=False)
        elif Path(p).exists():
            # Open read-only so the agent can never mutate the source file.
            self._conn = sqlite3.connect(
                f"file:{Path(p).as_posix()}?mode=ro", uri=True, check_same_thread=False
            )
        else:
            # Never create a database for a missing path — a reader must not
            # materialise an empty file. test()/get_schema() report it cleanly.
            self._conn = None

    def make_reader(self) -> "SQLiteConnection":
        """Fresh connection for a parallel thread — sqlite3 connections are not
        safe to share across threads even with check_same_thread=False."""
        clone = SQLiteConnection.__new__(SQLiteConnection)
        clone._dsn = self._dsn
        clone._path = self._path
        clone._schema_name = self._schema_name
        clone._connection_id = self._connection_id
        clone._ontology = self._ontology
        clone.last_build = self.last_build
        clone._connect()
        return clone

    # ── execution ─────────────────────────────────────────────────────────────

    def raw_execute(self, sql: str) -> tuple[list[str], list, list[str]]:
        """Run metadata SQL bypassing validation/security. Returns (cols, rows, types)."""
        cur = self._conn.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        # sqlite3 does not expose column types on the cursor description.
        types = ["" for _ in columns]
        return columns, rows, types

    def dry_run(self, sql: str) -> tuple[bool, str]:
        """Validate via EXPLAIN — SQLite prepares the statement, so bad table/
        column names are caught without returning rows. The read-only connection
        rejects any non-SELECT at the engine, so EXPLAIN alone is a safe gate."""
        sql = self.translate(sql.strip().rstrip(";"))
        try:
            self._conn.execute(f"EXPLAIN {sql}")
            return True, ""
        except Exception as e:
            return False, str(e)

    #: sqlite3's named style is already `:name`, so `render_for_engine` is the identity
    #: here — the editor's syntax reaches this driver verbatim.
    param_style = "named"

    #: This connector caps at the SHARED `MAX_ROWS` (500), not the 2000 every other
    #: connector module declares for itself. Stated here so the bound path and `execute`
    #: return the same population — two caps over one query is how a tile ends up
    #: disagreeing with the chart beside it.
    max_rows = MAX_ROWS

    def _bind_execute(self, sql: str, params: dict):
        # `translate` runs HERE and not in the shared envelope because it is this
        # connector's own DuckDB→SQLite step; sqlglot reads `:name` as a Placeholder, so it
        # survives the rewrite exactly as it does on the unparameterised path.
        cur = self._conn.execute(self.translate(sql), params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(self.max_rows)
        # This connector's `execute` captures typed rows, so its bound path has to as
        # well — otherwise adding a parameter to a query silently drops the per-column
        # types, which is the asymmetry the route-level fix exists to remove. Offered
        # from the same slice the result will carry: `_security_post` mirrors its budget
        # slice and PII redaction onto this sink POSITIONALLY.
        from aughor.db.connection import offer_typed_rows
        offer_typed_rows(rows, truncated=len(rows) >= self.max_rows, types=[])
        return cols, rows

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        # Gate through the public security interface; the read-only connection
        # also blocks any write at the engine.
        from aughor.db.connection import enforce_row_policy, security_pre, security_post

        sql = sql.strip().rstrip(";")
        conn_id = getattr(self, "_connection_id", "")
        if (blocked := security_pre(conn_id, hypothesis_id, sql)):
            return blocked
        sql, _rp = enforce_row_policy(self, hypothesis_id, sql)   # RBAC row-policy (Rec 7); no-op off
        if _rp is not None:
            return _rp

        sql = self.translate(sql)  # DuckDB-flavoured SQL → SQLite, best-effort
        t0 = time.monotonic()
        try:
            cur = self._conn.execute(sql)
            rows = cur.fetchmany(MAX_ROWS)
            columns = [d[0] for d in cur.description] if cur.description else []
            from aughor.db.connection import offer_typed_rows
            # sqlite3's description carries no types (d[1] is always None) — pass
            # none and let the caller infer per-column types from the values.
            offer_typed_rows(rows, truncated=len(rows) >= MAX_ROWS, types=[])
            result = QueryResult(
                hypothesis_id=hypothesis_id,
                sql=sql,
                columns=columns,
                rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows],
                row_count=len(rows),
            )
        except Exception as e:
            result = QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=str(e))

        elapsed_ms = (time.monotonic() - t0) * 1000
        return security_post(conn_id, hypothesis_id, sql, result, elapsed_ms)

    # ── schema introspection ────────────────────────────────────────────────────

    def _list_tables(self) -> list[str]:
        try:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _schema_string(self) -> str:
        """Structural schema in the house 'TABLE: x (n rows)\\n  col type' format."""
        tables = self._list_tables()
        if not tables:
            return f"No tables found in '{self._path}'."

        from aughor.db.annotations import load_annotations, inject_into_schema_parts
        _ann = load_annotations(self._connection_id or "sqlite")

        parts: list[str] = []
        for i, table in enumerate(tables):
            if i:
                parts.append("")
            try:
                count = self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                count_str = f"{count:,}"
            except Exception:
                count_str = "?"
            parts.append(f"TABLE: {table}  ({count_str} rows)")
            inject_into_schema_parts(parts, table, None, _ann)
            try:
                cols = self._conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            except Exception:
                cols = []
            # A2: one head scan makes every column self-describing (what it HOLDS,
            # not just its declared type — sqlite affinity makes this matter more).
            from aughor.db.schema_render import column_head_samples
            _samples = column_head_samples(
                lambda sql: self._conn.execute(sql).fetchall(),
                '"' + table.replace('"', '""') + '"', [c[1] for c in cols])
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            for col in cols:
                name = col[1]
                dtype = (col[2] or "").strip() or "TEXT"
                parts.append(f"  {name}  {dtype}" + _samples.get(name, ""))
                inject_into_schema_parts(parts, table, name, _ann)
        return "\n".join(parts)

    def get_schema(self) -> str:
        """Fast hot-path schema: raw structure + the registered FAST schema annotators
        (glossary/joins/metrics enrichment + exploration). No DB profiling or LLM."""
        base = self._schema_string()
        if base.startswith("No tables") or base.startswith("Schema unavailable"):
            return base
        from aughor.kernel.registries.schema_annotators import run_annotators
        return run_annotators(self, base, phase="fast")

    @single_flight_build
    def build_intelligence(self) -> str:
        """Heavy path: raw structure + the registered HEAVY schema annotators
        (enrichment + value profiles + the structural/semantic ontology + exploration)."""
        base = self._schema_string()
        if base.startswith("No tables") or base.startswith("Schema unavailable"):
            return base
        from aughor.kernel.registries.schema_annotators import run_annotators
        return run_annotators(self, base, phase="heavy")

    # ── misc ────────────────────────────────────────────────────────────────────

    def ibis_connection(self):
        """Return an ibis SQLite backend bound to this file. None if ibis unavailable."""
        if self._path == ":memory:":
            return None
        try:
            import ibis
            return ibis.sqlite.connect(str(self._path))
        except ImportError:
            return None

    def test(self) -> tuple[bool, str]:
        if self._path != ":memory:" and not Path(self._path).exists():
            return False, f"File not found: {self._path}"
        try:
            self._conn.execute("SELECT 1").fetchone()
            n = len(self._list_tables())
            return True, f"Connected ({n} tables)"
        except Exception as e:
            return False, str(e)

    def is_healthy(self) -> bool:
        try:
            if self._conn is None:
                return False
            self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def close(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception as exc:
            tolerate(exc, "sqlite close: connection teardown is best-effort",
                     counter="sqlite.close", conn_id=self._connection_id or None)
