"""
Database connection abstraction.

Each backend implements execute() and get_schema() so the agent
works identically regardless of what's underneath.
SQLGlot handles dialect translation transparently.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import duckdb
import sqlglot

from aughor.agent.state import QueryResult

# Security baseline — imported lazily to avoid circular imports at module load
def _security_pre(connection_id: str, hypothesis_id: str, sql: str) -> QueryResult | None:
    """Run safety check. Returns a blocked QueryResult if the query is not allowed, else None."""
    try:
        from aughor.security.safety import SafetyChecker, SafetyVerdict
        from aughor.security.audit  import AuditLogger
        result = SafetyChecker.check(sql)
        if result.verdict == SafetyVerdict.BLOCKED:
            AuditLogger.log(
                connection_id=connection_id,
                hypothesis_id=hypothesis_id,
                sql=sql,
                verdict="blocked",
                error=result.reason,
            )
            return QueryResult(
                hypothesis_id=hypothesis_id,
                sql=sql,
                columns=[],
                rows=[],
                row_count=0,
                error=f"[BLOCKED] {result.reason}",
            )
        if result.verdict == SafetyVerdict.SUSPICIOUS:
            # Log but allow — the query still runs
            AuditLogger.log(
                connection_id=connection_id,
                hypothesis_id=hypothesis_id,
                sql=sql,
                verdict="suspicious",
            )
    except Exception:
        pass  # security failures must never break query execution
    return None


def _security_post(
    connection_id: str,
    hypothesis_id: str,
    sql: str,
    result: QueryResult,
    duration_ms: float,
) -> QueryResult:
    """PII redaction + audit logging + budget enforcement. Returns (possibly modified) result."""
    import time as _time
    try:
        from aughor.security.pii     import PiiScanner
        from aughor.security.audit   import AuditLogger
        from aughor.security.sandbox import get_budget

        # 1. Row budget — truncate silently
        budget = get_budget(connection_id)
        if len(result.rows) > budget.max_rows:
            result = QueryResult(
                hypothesis_id=result.hypothesis_id,
                sql=result.sql,
                columns=result.columns,
                rows=result.rows[:budget.max_rows],
                row_count=result.row_count,
                error=result.error,
            )

        # 2. PII redaction
        pii_count = 0
        if result.columns and result.rows:
            scan = PiiScanner.scan_and_redact(result.columns, result.rows)
            if scan.redacted_count > 0:
                result = QueryResult(
                    hypothesis_id=result.hypothesis_id,
                    sql=result.sql,
                    columns=result.columns,
                    rows=scan.rows,
                    row_count=result.row_count,
                    error=result.error,
                )
                pii_count = scan.redacted_count

        # 3. Audit log
        AuditLogger.log(
            connection_id=connection_id,
            hypothesis_id=hypothesis_id,
            sql=sql,
            verdict="safe",
            row_count=result.row_count,
            duration_ms=duration_ms,
            pii_redacted=pii_count,
            error=result.error,
        )
    except Exception:
        pass  # security failures must never break query execution
    return result

# ── Proactive PostgreSQL dialect transforms ───────────────────────────────────
# Applied to every Postgres query *before* execution to prevent the most
# common class of type errors without needing a retry round-trip.

# Locates each ROUND( token so the paren-aware rewriter can take over.
_ROUND_OPEN = re.compile(r"\bROUND\s*\(", re.IGNORECASE)

# (col1 - col2)::numeric  where operands look like timestamp columns
# → EXTRACT(EPOCH FROM (col1 - col2)) / 86400.0
_INTERVAL_NUMERIC = re.compile(
    r"\(([^()]+?)\s*-\s*([^()]+?)\)\s*::\s*(?:numeric|integer|float)",
    re.IGNORECASE,
)
_TS_HINT = re.compile(
    r"date|time|_at\b|timestamp|created|updated|delivered|approved|purchase|shipping",
    re.IGNORECASE,
)


def _find_top_level_comma(s: str) -> int | None:
    """Return the index of the last comma at paren-depth 0, or None."""
    depth = 0
    last = None
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            last = i
    return last


def _pg_fix_round(sql: str) -> str:
    """
    Rewrite every two-argument ROUND(expr, N) → ROUND((expr)::numeric, N).

    PostgreSQL's ROUND(double precision, integer) does not exist — only the
    numeric overload accepts a precision argument.  Arithmetic expressions
    (100.0 * x / y, SUM(a)/COUNT(*), etc.) silently return double precision,
    so we unconditionally cast the first argument to numeric.  The cast is a
    no-op when the expression is already numeric, so this is always safe.
    """
    parts: list[str] = []
    pos = 0
    for m in _ROUND_OPEN.finditer(sql):
        parts.append(sql[pos:m.end()])   # everything up to and including "ROUND("
        # Walk forward tracking paren depth to find the matching ")"
        depth = 1
        j = m.end()
        while j < len(sql) and depth > 0:
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
            j += 1
        # sql[m.end() : j-1] is the raw content inside ROUND(...)
        inner = sql[m.end(): j - 1]
        pos = j  # character after the closing ")"

        comma = _find_top_level_comma(inner)
        if comma is not None:
            precision = inner[comma + 1:].strip()
            if re.match(r"^\d+$", precision):          # second arg is a plain integer
                first_arg = inner[:comma].strip()
                # Don't double-cast if already ::numeric
                if not re.search(r"::numeric\s*$", first_arg, re.IGNORECASE):
                    first_arg = f"({first_arg})::numeric"
                parts.append(f"{first_arg}, {precision})")
                continue
        # Not a two-arg ROUND, or precision isn't a plain literal — leave untouched
        parts.append(inner + ")")

    parts.append(sql[pos:])
    return "".join(parts)


def _pg_fix_nullif_timestamps(sql: str, varchar_ts_cols: list[tuple[str, str]]) -> str:
    """col::TIMESTAMP → NULLIF(col, '')::TIMESTAMP for known VARCHAR timestamp columns."""
    for _table, col in varchar_ts_cols:
        pat = re.compile(
            rf"\b{re.escape(col)}\s*::\s*TIMESTAMP\b", re.IGNORECASE
        )
        sql = pat.sub(f"NULLIF({col}, '')::TIMESTAMP", sql)
    return sql


def _pg_fix_interval_arithmetic(sql: str) -> str:
    """(ts_col - ts_col)::numeric → EXTRACT(EPOCH FROM (...)) / 86400.0."""
    def _replace(m: re.Match) -> str:
        a, b = m.group(1).strip(), m.group(2).strip()
        if _TS_HINT.search(a) or _TS_HINT.search(b):
            return f"EXTRACT(EPOCH FROM ({a} - {b})) / 86400.0"
        return m.group(0)  # not timestamp-looking — leave as-is
    return _INTERVAL_NUMERIC.sub(_replace, sql)


# ── Safety ────────────────────────────────────────────────────────────────────

_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|COPY|ATTACH|DETACH)\b",
    re.IGNORECASE,
)

MAX_ROWS = 500


def _validate(sql: str) -> tuple[bool, str]:
    sql = sql.strip().rstrip(";")
    if _FORBIDDEN.search(sql):
        return False, "Only SELECT statements are permitted"
    try:
        parsed = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as e:
        return False, f"SQL parse error: {e}"
    if not isinstance(parsed, (sqlglot.exp.Select, sqlglot.exp.Union)):
        return False, f"Only SELECT is allowed, got {type(parsed).__name__}"
    return True, "ok"


# ── Explorer → Ontology in-memory merge ──────────────────────────────────────

def _apply_explorer_to_ontology(graph, connection_id: str) -> None:
    """
    Merge verified exploration findings into an already-built ontology graph,
    in-memory only.  Not persisted — re-applied each time get_schema() renders.

    Upgrades:
      • lifecycle_states / terminal_states / active_filter from explorer's
        verified state-machine maps (overrides the profiler's heuristic values).
      • join_confidence from "inferred" to "verified" for joins confirmed by
        the orphan-count check in Phase 4.
    """
    try:
        from aughor.explorer.store import load as _load_exploration
        state = _load_exploration(connection_id)
        phase = state.get("phase", "pending")
        if phase in ("pending", "failed"):
            return

        # ── Lifecycle merge ───────────────────────────────────────────────────
        lifecycle_maps: dict = state.get("lifecycle_maps", {})
        if lifecycle_maps:
            for entity in graph.entities.values():
                for src_table in entity.source_tables:
                    if src_table in lifecycle_maps:
                        lm = lifecycle_maps[src_table]
                        col = lm.get("status_column")
                        if not col:
                            break
                        entity.has_lifecycle     = True
                        entity.lifecycle_column  = col
                        entity.lifecycle_states  = lm.get("states", entity.lifecycle_states)
                        entity.terminal_states   = lm.get("terminal_states", entity.terminal_states)
                        terminal = lm.get("terminal_states", [])
                        if terminal:
                            tl = ", ".join(f"'{s}'" for s in terminal)
                            entity.active_filter = f"{col} NOT IN ({tl})"
                        break

        # ── Join confidence upgrade ───────────────────────────────────────────
        verifications: list = state.get("join_verifications", [])
        verified_keys = {
            (j["from_table"], j["from_col"], j["to_table"], j["to_col"])
            for j in verifications
            if j.get("verified")
        }
        if verified_keys:
            for rel in graph.relationships.values():
                if (rel.from_table, rel.from_col, rel.to_table, rel.to_col) in verified_keys:
                    rel.join_confidence = "verified"
    except Exception:
        pass  # exploration data is best-effort — never block schema rendering


# ── Base class ────────────────────────────────────────────────────────────────

class DatabaseConnection(ABC):
    dialect: str = "duckdb"
    _ontology = None  # Optional[OntologyGraph] — set by get_schema()

    @abstractmethod
    def execute(self, hypothesis_id: str, sql: str) -> QueryResult: ...

    @abstractmethod
    def get_schema(self) -> str: ...

    @abstractmethod
    def test(self) -> tuple[bool, str]:
        """Return (ok, message)."""
        ...

    @abstractmethod
    def close(self) -> None: ...

    def get_ontology(self):
        """Return the OntologyGraph built during the last get_schema() call, or None."""
        return self._ontology

    def ibis_connection(self):
        """Return an ibis backend for this connection, or None if ibis is not installed.

        Subclasses override this. The base implementation always returns None so
        callers can guard with a simple ``if conn.ibis_connection() is not None``.
        """
        return None

    def execute_ibis(self, hypothesis_id: str, expr) -> "QueryResult":
        """Execute an ibis expression by compiling it to SQL and running via execute().

        Falls back to execute() with an error message if ibis is not available or
        the expression cannot be compiled.
        """
        try:
            import ibis
            sql_str = str(ibis.to_sql(expr, dialect=self.dialect))
            return self.execute(hypothesis_id, sql_str)
        except ImportError:
            return QueryResult(
                hypothesis_id=hypothesis_id,
                sql="",
                columns=[],
                rows=[],
                row_count=0,
                error="ibis-framework not installed — run: uv pip install 'aughor[warehouse]'",
            )
        except Exception as exc:
            return QueryResult(
                hypothesis_id=hypothesis_id,
                sql="",
                columns=[],
                rows=[],
                row_count=0,
                error=f"ibis compile error: {exc}",
            )

    def bulk_read(self, sql: str, limit: int = 10_000) -> "QueryResult":
        """Bulk-read result set, potentially via Arrow/ConnectorX for speed.

        The base implementation delegates to execute() with a LIMIT injected.
        PostgresConnection overrides this with ConnectorX for columnar Arrow reads.
        """
        bounded = f"SELECT * FROM ({sql.strip().rstrip(';')}) __q LIMIT {limit}" if limit > 0 else sql
        return self.execute("__bulk__", bounded)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        """Validate SQL without returning rows. Returns (ok, error_message).

        Default implementation uses sqlglot parse-only validation. Subclasses
        override with a real EXPLAIN query against the live engine so column
        and table names are checked, not just syntax.
        """
        ok, reason = _validate(sql)
        return ok, reason

    def translate(self, sql: str) -> str:
        """Rewrite SQL from any dialect to this backend's dialect."""
        if self.dialect == "duckdb":
            return sql
        try:
            return sqlglot.transpile(sql, read="duckdb", write=self.dialect)[0]
        except Exception:
            return sql  # best-effort — fall back to original


# ── DuckDB ────────────────────────────────────────────────────────────────────

class DuckDBConnection(DatabaseConnection):
    dialect = "duckdb"

    def __init__(self, path: str | Path, schema_name: str | None = None, connection_id: str = ""):
        self._path = Path(path)
        self._conn = duckdb.connect(str(self._path), read_only=True)
        self._connection_id = connection_id
        self._schema_name = schema_name or None
        if schema_name:
            # Point the execution context at the requested schema so queries
            # land in the right namespace without requiring fully-qualified names.
            try:
                self._conn.execute(f"SET search_path = '{schema_name}'")
            except Exception:
                pass  # best-effort — don't fail the connection over schema routing

    def dry_run(self, sql: str) -> tuple[bool, str]:
        """Run EXPLAIN against DuckDB — catches bad column/table names without returning rows."""
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql)
        if not ok:
            return False, reason
        sql = self._normalize_to_duckdb(sql)
        try:
            self._conn.execute(f"EXPLAIN {sql}")
            return True, ""
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _normalize_to_duckdb(sql: str) -> str:
        """Transpile any-dialect SQL to DuckDB syntax via SQLGlot. Silent no-op on failure."""
        try:
            result = sqlglot.transpile(sql, write="duckdb", error_level=sqlglot.ErrorLevel.IGNORE)
            return result[0] if result and result[0] else sql
        except Exception:
            return sql

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        import time as _time
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql)
        if not ok:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=reason)

        # Security pre-check
        conn_id = getattr(self, "_connection_id", "")
        if (blocked := _security_pre(conn_id, hypothesis_id, sql)):
            return blocked

        sql = self._normalize_to_duckdb(sql)
        _t0 = _time.monotonic()
        try:
            self._conn.execute(sql)
            rows = self._conn.fetchall()
            columns = [d[0] for d in self._conn.description] if self._conn.description else []
            result = QueryResult(
                hypothesis_id=hypothesis_id,
                sql=sql,
                columns=columns,
                rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows[:MAX_ROWS]],
                row_count=len(rows),
            )
        except Exception as e:
            result = QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=str(e))

        elapsed_ms = (_time.monotonic() - _t0) * 1000
        return _security_post(conn_id, hypothesis_id, sql, result, elapsed_ms)

    def get_schema(self) -> str:
        from aughor.tools.schema import build_schema_context, _compute_join_map, _parse_schema_tables
        from aughor.tools.profile_cache import get_or_build_profiles
        from aughor.tools.profiler import render_profile_annotations

        # Build base schema string first (needed for join inference + fk_hints)
        base = build_schema_context(self._conn, schema_name=self._schema_name)

        # Extract table list and fk hints from the join map — filter by schema if known
        if self._schema_name:
            tables = [
                row[0] for row in self._conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' ORDER BY table_name",
                    [self._schema_name],
                ).fetchall()
            ]
        else:
            # No schema configured — scan all user schemas (handles multi-schema
            # DuckDB files like samples.duckdb where tables are in 'ecommerce').
            tables = [
                row[0] for row in self._conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'temp') "
                    "AND table_type = 'BASE TABLE' ORDER BY table_name",
                ).fetchall()
            ]
        table_cols = _parse_schema_tables(base)
        from aughor.tools.schema import _compute_join_map
        jmap = _compute_join_map(table_cols)
        fk_hints: dict[str, set[str]] = {t: set() for t in tables}
        for j in jmap.get("joins", []):
            fk_hints.setdefault(j["t1"], set()).add(j["c1"])
            # t2.c2 is the PK target — do NOT mark it as FK

        try:
            tp, cp = get_or_build_profiles(self, self._connection_id or "fixture", tables, fk_hints)
            from aughor.tools.schema import inject_value_annotations
            base = inject_value_annotations(base, cp)
            annotation = render_profile_annotations(tp, cp)
            if annotation:
                base += "\n\n" + annotation

            # Build structural ontology from profiles + join map + glossary
            from aughor.ontology.store import get_or_build_ontology, save_ontology
            from aughor.ontology.builder import render_ontology_annotations
            from aughor.semantic.glossary import load_merged_glossary
            _glossary = load_merged_glossary()
            graph = get_or_build_ontology(
                connection_id=self._connection_id or "fixture",
                table_profiles=tp,
                column_profiles=cp,
                join_map=jmap,
                glossary=_glossary,
            )
            if graph is not None:
                # M12b: semantic enrichment — re-run when prompt/schema version changes
                from aughor.ontology.enricher import ENRICHMENT_VERSION
                from aughor.stats import stats as _st
                if not graph.enriched or graph.enrichment_version < ENRICHMENT_VERSION:
                    _st.inc("enrichment_runs")
                    try:
                        from aughor.ontology.enricher import enrich_ontology_semantics
                        from aughor.llm.provider import get_provider
                        graph = enrich_ontology_semantics(
                            graph, get_provider("coder"), _glossary, base
                        )
                        save_ontology(graph.connection_id, graph.schema_fingerprint, graph)
                    except Exception:
                        pass  # structural ontology still works
                else:
                    _st.inc("enrichment_cache_hits")
                # Merge verified exploration findings (lifecycle + join confidence)
                _apply_explorer_to_ontology(graph, self._connection_id or "fixture")
                self._ontology = graph
                onto_block = render_ontology_annotations(graph)
                if onto_block:
                    base += "\n\n" + onto_block
        except Exception:
            pass  # profiler + ontology are best-effort — never block schema loading

        # Append exploration intelligence block (null meanings, insights, broken joins)
        try:
            from aughor.explorer.store import render_exploration_annotations
            expl_block = render_exploration_annotations(self._connection_id or "fixture")
            if expl_block:
                base += "\n\n" + expl_block
        except Exception:
            pass

        return base

    def ibis_connection(self):
        """Return an ibis DuckDB backend bound to this file. None if ibis unavailable."""
        try:
            import ibis
            return ibis.duckdb.connect(str(self._path), read_only=True)
        except ImportError:
            return None

    def test(self) -> tuple[bool, str]:
        if not self._path.exists():
            return False, f"File not found: {self._path}"
        try:
            self._conn.execute("SELECT 1")
            return True, "Connected"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ── Postgres ──────────────────────────────────────────────────────────────────

class PostgresConnection(DatabaseConnection):
    dialect = "postgres"

    def __init__(self, dsn: str, schema_name: str | None = None, connection_id: str = ""):
        self._dsn = dsn
        self._schema_name = schema_name or "public"
        self._connection_id = connection_id
        self._conn = None
        # Populated by get_schema() — used by proactive dialect transforms
        self._varchar_ts_cols: list[tuple[str, str]] = []
        self._connect()

    def _connect(self):
        import psycopg2
        self._conn = psycopg2.connect(self._dsn)
        self._conn.autocommit = True
        # Set search_path so unqualified table names resolve to the right schema
        if self._schema_name != "public":
            with self._conn.cursor() as cur:
                cur.execute(f"SET search_path = {self._schema_name}")

    def dry_run(self, sql: str) -> tuple[bool, str]:
        """Run EXPLAIN against Postgres — catches bad column/table names without returning rows."""
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql)
        if not ok:
            return False, reason
        sql = self.translate(sql)
        sql = self._apply_dialect_fixes(sql)
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"EXPLAIN {sql}")
            return True, ""
        except Exception as e:
            try:
                self._connect()
            except Exception:
                pass
            return False, str(e)

    def _apply_dialect_fixes(self, sql: str) -> str:
        """
        Three sequential proactive transforms for PostgreSQL.
        Catches predictable type errors before they reach the database,
        avoiding a FIX_SQL retry round-trip.
        """
        sql = _pg_fix_round(sql)
        sql = _pg_fix_nullif_timestamps(sql, self._varchar_ts_cols)
        sql = _pg_fix_interval_arithmetic(sql)
        return sql

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        import time as _time
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql)
        if not ok:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=reason)

        # Security pre-check
        conn_id = getattr(self, "_connection_id", "")
        if (blocked := _security_pre(conn_id, hypothesis_id, sql)):
            return blocked

        # Translate DuckDB-flavoured SQL → Postgres, then apply proactive fixes
        sql = self.translate(sql)
        sql = self._apply_dialect_fixes(sql)

        _t0 = _time.monotonic()
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchmany(MAX_ROWS)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                # row_count from cursor (may be -1 for some queries)
                total = cur.rowcount if cur.rowcount >= 0 else len(rows)
                result = QueryResult(
                    hypothesis_id=hypothesis_id,
                    sql=sql,
                    columns=columns,
                    rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows],
                    row_count=total,
                )
        except Exception as e:
            # Reconnect on broken pipe
            try:
                self._connect()
            except Exception:
                pass
            result = QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0, error=str(e))

        elapsed_ms = (_time.monotonic() - _t0) * 1000
        return _security_post(conn_id, hypothesis_id, sql, result, elapsed_ms)

    def get_schema(self) -> str:
        """Introspect information_schema and return a Hermes-formatted schema string with SQL hints."""
        try:
            with self._conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    ORDER BY table_name, ordinal_position
                """, (self._schema_name,))
                rows = cur.fetchall()
        except Exception as e:
            return f"Schema unavailable: {e}"

        if not rows:
            return f"No tables found in schema '{self._schema_name}'."

        parts: list[str] = []
        current_table = None
        for table, col, dtype in rows:
            if table != current_table:
                if current_table:
                    parts.append("")
                try:
                    with self._conn.cursor() as cur2:
                        cur2.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cur2.fetchone()[0]
                except Exception:
                    count = "?"
                parts.append(f"TABLE: {table}  ({count:,} rows)")
                current_table = table
            parts.append(f"  {col}  {dtype}")

        schema_str = "\n".join(parts)
        hints = self._detect_sql_hints(rows)  # also populates self._varchar_ts_cols
        if hints:
            schema_str += "\n\n" + hints

        from aughor.semantic.autoseed import seed_missing_tables
        from aughor.semantic.glossary import apply_glossary
        from aughor.tools.schema import infer_joins
        from aughor.tools.profile_cache import get_or_build_profiles
        from aughor.tools.profiler import render_profile_annotations
        seed_missing_tables(schema_str)
        enriched = apply_glossary(schema_str)
        join_hints = infer_joins(enriched)
        if join_hints:
            enriched += "\n\n" + join_hints

        # Build fk_hints from the join map.
        # Use information_schema.tables (BASE TABLE only) so this list matches
        # what _load_profiler_data() finds — identical table sets → same profile
        # fingerprint → ontology builder gets grain-detected profiles.
        try:
            with self._conn.cursor() as _tcur:
                _tcur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name",
                    (self._schema_name,),
                )
                tables = [r[0] for r in _tcur.fetchall()]
        except Exception:
            tables = list({table for table, _, _ in rows})  # fallback
        from aughor.tools.schema import _parse_schema_tables, _compute_join_map
        table_cols_map = _parse_schema_tables(enriched)
        jmap = _compute_join_map(table_cols_map)
        fk_hints: dict[str, set[str]] = {t: set() for t in tables}
        for j in jmap.get("joins", []):
            fk_hints.setdefault(j["t1"], set()).add(j["c1"])
            # t2.c2 is the PK target — do NOT mark it as FK

        try:
            tp, cp = get_or_build_profiles(self, self._connection_id or "postgres", tables, fk_hints)
            from aughor.tools.schema import inject_value_annotations
            enriched = inject_value_annotations(enriched, cp)
            annotation = render_profile_annotations(tp, cp)
            if annotation:
                enriched += "\n\n" + annotation

            # Build structural ontology from profiles + join map + glossary
            from aughor.ontology.store import get_or_build_ontology, save_ontology
            from aughor.ontology.builder import render_ontology_annotations
            from aughor.semantic.glossary import load_merged_glossary
            _glossary = load_merged_glossary()
            graph = get_or_build_ontology(
                connection_id=self._connection_id or "postgres",
                table_profiles=tp,
                column_profiles=cp,
                join_map=jmap,
                glossary=_glossary,
            )
            if graph is not None:
                # M12b: semantic enrichment — re-run when prompt/schema version changes
                from aughor.ontology.enricher import ENRICHMENT_VERSION
                from aughor.stats import stats as _st
                if not graph.enriched or graph.enrichment_version < ENRICHMENT_VERSION:
                    _st.inc("enrichment_runs")
                    try:
                        from aughor.ontology.enricher import enrich_ontology_semantics
                        from aughor.llm.provider import get_provider
                        graph = enrich_ontology_semantics(
                            graph, get_provider("coder"), _glossary, enriched
                        )
                        save_ontology(graph.connection_id, graph.schema_fingerprint, graph)
                    except Exception:
                        pass  # structural ontology still works
                else:
                    _st.inc("enrichment_cache_hits")
                # Merge verified exploration findings (lifecycle + join confidence)
                _apply_explorer_to_ontology(graph, self._connection_id or "postgres")
                self._ontology = graph
                onto_block = render_ontology_annotations(graph)
                if onto_block:
                    enriched += "\n\n" + onto_block
        except Exception:
            pass  # profiler + ontology are best-effort — never block schema loading

        # Append exploration intelligence block (null meanings, insights, broken joins)
        try:
            from aughor.explorer.store import render_exploration_annotations
            expl_block = render_exploration_annotations(self._connection_id or "postgres")
            if expl_block:
                enriched += "\n\n" + expl_block
        except Exception:
            pass

        return enriched

    def _detect_sql_hints(self, columns: list) -> str:
        """
        Scan for common data quality issues and return a SQL hints block.
        This runs once at schema-load time so the LLM sees it in every prompt.
        """
        hints: list[str] = []

        # Find VARCHAR columns whose names suggest they hold timestamps/dates
        timestamp_pattern = (
            "timestamp", "date", "_at", "_on", "time", "created", "updated",
            "delivered", "approved", "purchase", "shipping",
        )
        varchar_ts_cols: list[tuple[str, str]] = [
            (t, c) for t, c, dtype in columns
            if dtype == "character varying"
            and any(c.lower().endswith(p) or p in c.lower() for p in timestamp_pattern)
        ]
        # Store for use by _apply_dialect_fixes on every subsequent execute() call
        self._varchar_ts_cols = varchar_ts_cols

        if varchar_ts_cols:
            sample = ", ".join(f"{t}.{c}" for t, c in varchar_ts_cols[:5])
            hints.append(
                "⚠ TIMESTAMP COLUMNS STORED AS VARCHAR — cast before any date arithmetic:\n"
                f"  Affected: {sample}\n"
                "  Correct cast:  CAST(col AS TIMESTAMP)\n"
                "  Date diff (days):  EXTRACT(EPOCH FROM (\n"
                "      CAST(end_col AS TIMESTAMP) - CAST(start_col AS TIMESTAMP)\n"
                "  )) / 86400\n"
                "  Never subtract VARCHAR columns directly — it will fail."
            )

        # Check for empty strings in VARCHAR timestamp columns (up to 5, fast COUNT queries)
        empty_str_notes: list[str] = []
        for table, col in varchar_ts_cols[:5]:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {col} = ''", # noqa: S608
                    )
                    n = cur.fetchone()[0]
                if n > 0:
                    empty_str_notes.append(
                        f"  {table}.{col}: {n:,} empty strings — filter with WHERE {col} != ''"
                    )
            except Exception:
                pass

        if empty_str_notes:
            hints.append(
                "⚠ EMPTY STRINGS (not NULL) in timestamp columns — always filter:\n"
                + "\n".join(empty_str_notes)
            )

        if not hints:
            return ""
        return "SQL HINTS FOR THIS DATABASE:\n" + "\n\n".join(hints)

    def ibis_connection(self):
        """Return an ibis Postgres backend. None if ibis unavailable."""
        try:
            import ibis
            return ibis.connect(self._dsn)
        except ImportError:
            return None

    def bulk_read(self, sql: str, limit: int = 10_000) -> QueryResult:
        """Fast columnar bulk read via ConnectorX → Polars → QueryResult.

        ConnectorX reads Postgres data as Arrow batches (bypassing row-by-row
        psycopg2 fetching), then converts to Polars for zero-copy column access.
        Falls back to execute() if ConnectorX is not installed or errors.
        """
        bounded = (
            f"SELECT * FROM ({sql.strip().rstrip(';')}) __q LIMIT {limit}"
            if limit > 0
            else sql.strip().rstrip(";")
        )
        try:
            import connectorx as cx  # type: ignore
            import polars as pl

            df: pl.DataFrame = cx.read_sql(self._dsn, bounded, return_type="polars")
            columns = list(df.columns)
            rows = [
                [str(v) if v is not None else "NULL" for v in row]
                for row in df.iter_rows()
            ]
            return QueryResult(
                hypothesis_id="__bulk__",
                sql=bounded,
                columns=columns,
                rows=rows,
                row_count=len(rows),
            )
        except ImportError:
            # ConnectorX not installed — fall back to regular execute
            return self.execute("__bulk__", bounded)
        except Exception:
            # Any error (auth, SQL) — fall back to regular execute
            return self.execute("__bulk__", bounded)

    def test(self) -> tuple[bool, str]:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
            return True, version.split(",")[0]
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ── Factory ───────────────────────────────────────────────────────────────────

def open_connection(
    conn_type: str,
    dsn: str,
    schema_name: str | None = None,
    connection_id: str = "",
    meta: dict | None = None,
) -> DatabaseConnection:
    if conn_type == "duckdb":
        return DuckDBConnection(dsn, schema_name=schema_name, connection_id=connection_id)
    elif conn_type == "postgres":
        return PostgresConnection(dsn, schema_name=schema_name, connection_id=connection_id)
    else:
        # Delegate to the pluggable connector registry (Sprint 25+)
        from aughor.connectors.registry import build_connector
        return build_connector(
            conn_type,
            dsn=dsn,
            schema_name=schema_name,
            connection_id=connection_id,
            meta=meta or {},
        )


def open_connection_for(conn_id: str) -> DatabaseConnection:
    """Open a registered connection with all stored metadata applied (schema_name, connection_id etc.)."""
    from aughor.db.registry import get_dsn, get_meta
    conn_type, dsn = get_dsn(conn_id)
    meta = get_meta(conn_id)
    return open_connection(
        conn_type, dsn,
        schema_name=meta.get("schema_name"),
        connection_id=conn_id,
        meta=meta,
    )
