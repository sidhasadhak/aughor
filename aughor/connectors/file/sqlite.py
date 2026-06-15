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

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        # Gate through the public security interface; the read-only connection
        # also blocks any write at the engine.
        from aughor.db.connection import security_pre, security_post

        sql = sql.strip().rstrip(";")
        conn_id = getattr(self, "_connection_id", "")
        if (blocked := security_pre(conn_id, hypothesis_id, sql)):
            return blocked

        sql = self.translate(sql)  # DuckDB-flavoured SQL → SQLite, best-effort
        t0 = time.monotonic()
        try:
            cur = self._conn.execute(sql)
            rows = cur.fetchmany(MAX_ROWS)
            columns = [d[0] for d in cur.description] if cur.description else []
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
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            for col in cols:
                name = col[1]
                dtype = (col[2] or "").strip() or "TEXT"
                parts.append(f"  {name}  {dtype}")
                inject_into_schema_parts(parts, table, name, _ann)
        return "\n".join(parts)

    def get_schema(self) -> str:
        """Fast hot-path schema: structure + glossary + joins + exploration. No
        DB profiling or LLM — heavy intelligence lives in build_intelligence()."""
        base = self._schema_string()
        if base.startswith("No tables") or base.startswith("Schema unavailable"):
            return base
        try:
            from aughor.semantic.autoseed import seed_missing_tables
            from aughor.semantic.glossary import apply_glossary
            from aughor.tools.schema import infer_joins
            seed_missing_tables(base)
            base = apply_glossary(base)
            join_hints = infer_joins(base)
            if join_hints:
                base += "\n\n" + join_hints
        except Exception as exc:
            tolerate(exc, "sqlite get_schema: glossary/join enrichment is additive — schema loads without it",
                     counter="sqlite.schema_enrich", conn_id=self._connection_id or None)

        try:
            from aughor.explorer.store import render_exploration_annotations
            expl_block = render_exploration_annotations(self._connection_id or "sqlite")
            if expl_block:
                base += "\n\n" + expl_block
        except Exception as exc:
            tolerate(exc, "sqlite get_schema: exploration annotations are additive — schema loads without them",
                     counter="sqlite.schema_exploration", conn_id=self._connection_id or None)
        return base

    def build_intelligence(self) -> str:
        """Heavy path: value profiles + structural/semantic ontology. Engine-agnostic
        pipeline (operates on self + the schema string), reused via public helpers."""
        from aughor.tools.schema import (
            compute_join_map, parse_schema_tables, infer_joins, inject_value_annotations,
        )
        from aughor.tools.profile_cache import get_or_build_profiles
        from aughor.tools.profiler import render_profile_annotations
        from aughor.semantic.glossary import apply_glossary

        base = apply_glossary(self._schema_string())
        tables = self._list_tables()
        join_hints = infer_joins(base)
        if join_hints:
            base += "\n\n" + join_hints

        table_cols = parse_schema_tables(base)
        jmap = compute_join_map(table_cols)
        fk_hints: dict[str, set[str]] = {t: set() for t in tables}
        for j in jmap.get("joins", []):
            fk_hints.setdefault(j["t1"], set()).add(j["c1"])

        self.last_build = {"ok": True, "stage": None, "error": None}
        _stage = "profiling"
        try:
            tp, cp = get_or_build_profiles(self, self._connection_id or "sqlite", tables, fk_hints)
            base = inject_value_annotations(base, cp)
            annotation = render_profile_annotations(tp, cp)
            if annotation:
                base += "\n\n" + annotation

            from aughor.ontology.store import get_or_build_ontology, save_ontology
            from aughor.ontology.builder import render_ontology_annotations
            from aughor.semantic.glossary import load_merged_glossary
            _glossary = load_merged_glossary()
            _stage = "ontology"
            graph = get_or_build_ontology(
                connection_id=self._connection_id or "sqlite",
                schema_name=self._schema_name or "main",
                table_profiles=tp,
                column_profiles=cp,
                join_map=jmap,
                glossary=_glossary,
            )
            if graph is None:
                self.last_build = {
                    "ok": False, "stage": "ontology",
                    "error": "the object model could not be built from this schema — it may "
                             "be too sparse to model (no entities/relationships inferred).",
                }
            else:
                from aughor.ontology.enricher import ENRICHMENT_VERSION
                if not graph.enriched or graph.enrichment_version < ENRICHMENT_VERSION:
                    _stage = "enrichment"
                    try:
                        from aughor.ontology.enricher import enrich_ontology_semantics
                        from aughor.llm.provider import get_provider
                        graph = enrich_ontology_semantics(graph, get_provider("coder"), _glossary, base)
                        save_ontology(graph.connection_id, graph.schema_name, graph.schema_fingerprint, graph)
                    except Exception as _enr_exc:
                        self.last_build = {
                            "ok": True, "stage": "enrichment",
                            "error": f"semantic enrichment failed (ontology still usable): {str(_enr_exc)[:200]}",
                        }
                    _stage = "ontology"
                self._ontology = graph
                onto_block = render_ontology_annotations(graph)
                if onto_block:
                    base += "\n\n" + onto_block
        except Exception as _build_exc:
            self.last_build = {"ok": False, "stage": _stage, "error": str(_build_exc)[:400]}

        try:
            from aughor.explorer.store import render_exploration_annotations
            expl_block = render_exploration_annotations(self._connection_id or "sqlite")
            if expl_block:
                base += "\n\n" + expl_block
        except Exception as exc:
            tolerate(exc, "sqlite build_intelligence: exploration block is additive — intelligence builds without it",
                     counter="sqlite.intel_exploration", conn_id=self._connection_id or None)
        return base

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
