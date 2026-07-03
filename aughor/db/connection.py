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

import duckdb
import sqlglot

from aughor.platform.contracts.execution import QueryResult

# Security baseline — imported lazily to avoid circular imports at module load

# Internal/metadata queries the platform issues to inspect its OWN plumbing
# (catalog browse, schema filter, column probes, freshness checks, profiler scans).
# These are not user activity and must NOT be safety-scored or audit-logged —
# otherwise the audit trail is flooded with `current_database()` /
# `information_schema` noise flagged SUSPICIOUS, drowning out real user queries.
# Two shapes: dunder labels (`__catalog__`, `__profiler__`, …) and a small
# allowlist of bare metadata labels used at older call sites.
_INTERNAL_HYPO_IDS = frozenset({
    "scan", "_catalog", "sample", "freshness", "columns", "alter_column",
    "skill_dry_run", "benchmark", "process_map_nodes", "process_map_edges",
    "lifecycle_counts", "list_schemas",
})


def _is_internal_query(hypothesis_id: str | None) -> bool:
    """True for platform-internal/metadata queries that should bypass the
    security audit (dunder labels like ``__catalog__`` or a known metadata id)."""
    if not hypothesis_id:
        return False
    h = hypothesis_id.strip()
    if len(h) >= 4 and h.startswith("__") and h.endswith("__"):
        return True
    return h in _INTERNAL_HYPO_IDS


def _security_pre(connection_id: str, hypothesis_id: str, sql: str) -> QueryResult | None:
    """Run safety check. Returns a blocked QueryResult if the query is not allowed, else None."""
    if _is_internal_query(hypothesis_id):
        return None  # platform plumbing — never block or audit
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
    except Exception as exc:
        # Fail CLOSED: a safety control that errors must DENY, not allow (SEC-02).
        # K4-honest — the failure is observable (counter + journal), not silent.
        from aughor.kernel.errors import tolerate
        tolerate(exc, "safety gate errored; failing closed", counter="security.gate_error")
        return QueryResult(
            hypothesis_id=hypothesis_id,
            sql=sql,
            columns=[],
            rows=[],
            row_count=0,
            error="[BLOCKED] safety check unavailable",
        )
    return None


def gate_user_sql(connection_id: str, label: str, sql: str) -> QueryResult | None:
    """Safety gate for **user-issued** SQL (Query Builder / bulk read).

    Runs SafetyChecker + audit on the RAW user SQL and returns a BLOCKED
    QueryResult to surface to the client, or None when the query is allowed.

    This must be called at the endpoint, before the SQL is wrapped or
    dispatched, for two reasons:
      1. ``bulk_read()`` reaches ConnectorX directly and never passes through
         ``execute()`` / ``_security_pre`` at all.
      2. The runner wraps user SQL as ``SELECT * FROM (<raw>) __q LIMIT n``,
         which demotes a first-token ``DELETE``/``DROP`` to a body token and
         slips it under the block threshold — so the inner gate can't be
         trusted for the user surface.

    ``label`` must NOT be a dunder internal id, or the check is bypassed.
    """
    return _security_pre(connection_id, label, sql)


def _security_post(
    connection_id: str,
    hypothesis_id: str,
    sql: str,
    result: QueryResult,
    duration_ms: float,
) -> QueryResult:
    """PII redaction + audit logging + budget enforcement. Returns (possibly modified) result."""
    if _is_internal_query(hypothesis_id):
        return result  # platform plumbing — skip PII/audit, but still return rows
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
    except Exception as exc:
        # Post-exec (PII redaction / budget / audit) stays best-effort: it must
        # NOT drop already-safe rows on a hiccup. But make the swallow observable
        # per K4 instead of a bare pass.
        from aughor.kernel.errors import tolerate
        tolerate(exc, "post-exec security best-effort (PII/budget/audit)", counter="security.post_error")
    # Per-run compute metering — best-effort, no-op outside a metered run.
    try:
        from aughor.kernel import metering
        metering.record_query(getattr(result, "row_count", 0) or 0, duration_ms)
    except Exception as _m_exc:
        from aughor.kernel.errors import tolerate
        tolerate(_m_exc, "query metering", counter="metering")
    # Post-execute hooks (agent-registered): e.g. the in-SQL AI-column Trust-Receipt
    # (R8 provenance for a governed prompt()/embedding() UDF). No-op if none registered.
    from aughor.kernel.registries.execution_hooks import run_post_execute_hooks
    run_post_execute_hooks(sql, result, connection_id)
    return result


# ── Public security gate (stable interface for out-of-module connectors) ──────
# Connectors living outside this module (aughor/connectors/**) should gate
# execution through these, rather than reaching for the leading-underscore
# internals. Thin forwarders — the policy lives in _security_pre/_security_post.

def security_pre(connection_id: str, hypothesis_id: str, sql: str) -> "QueryResult | None":
    """Pre-execution safety gate. Returns a blocked QueryResult, or None to proceed."""
    return _security_pre(connection_id, hypothesis_id, sql)


def security_post(connection_id: str, hypothesis_id: str, sql: str,
                  result: "QueryResult", duration_ms: float) -> "QueryResult":
    """Post-execution PII redaction + audit + budget. Returns the (possibly modified) result."""
    return _security_post(connection_id, hypothesis_id, sql, result, duration_ms)


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


def _validate(sql: str, dialect: str = "duckdb") -> tuple[bool, str]:
    sql = sql.strip().rstrip(";")
    if _FORBIDDEN.search(sql):
        return False, "Only SELECT statements are permitted"
    try:
        # Parse in the connection's own dialect — a Postgres connection must not
        # be validated as DuckDB, or valid Postgres-only syntax gets rejected.
        parsed = sqlglot.parse_one(sql, read=dialect or "duckdb", error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as e:
        return False, f"SQL parse error: {e}"
    if not isinstance(parsed, (sqlglot.exp.Select, sqlglot.exp.Union)):
        return False, f"Only SELECT is allowed, got {type(parsed).__name__}"
    return True, "ok"


# ── Explorer → Ontology in-memory merge ──────────────────────────────────────

def _pg_type_name(oid: int) -> str:
    return _PG_OID_MAP.get(oid, f"TYPE({oid})")

class DatabaseConnection(ABC):
    dialect: str = "duckdb"
    poolable: bool = True  # may this connection be reused via the pool? (see db/pool.py)
    # True ⇒ execute() runs the LLM's SQL verbatim (native dialect); False ⇒ it
    # transpiles read=duckdb→dialect via translate(), so the LLM writes DuckDB.
    # Drives the SQL-writer's dialect rules (aughor/db/dialects.py:writer_rules).
    writes_native_sql: bool = False
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

    # ── Convenience adapters ──────────────────────────────────────────────────
    # Replace the ad-hoc "execute → check .error → pull .rows/.rows[0][0]" wrappers
    # scattered across the codebase. Best-effort: any error returns []/None, never raises.

    def rows(self, sql: str, *, label: str = "__adapter__") -> list:
        """Run SQL and return its rows; [] on error."""
        try:
            res = self.execute(label, sql)
            if getattr(res, "error", None):
                return []
            return list(getattr(res, "rows", None) or [])
        except Exception:
            return []

    def scalar(self, sql: str, *, label: str = "__adapter__", cast=float):
        """Run SQL and return the first cell coerced via ``cast`` (default float), or None."""
        rs = self.rows(sql, label=label)
        if not rs:
            return None
        row = rs[0]
        val = list(row.values())[0] if isinstance(row, dict) else row[0]
        if val is None:
            return None
        try:
            return cast(val)
        except (TypeError, ValueError):
            return None

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
        ok, reason = _validate(sql, getattr(self, "dialect", "duckdb"))
        return ok, reason

    def translate(self, sql: str) -> str:
        """Rewrite SQL from any dialect to this backend's dialect."""
        if self.dialect == "duckdb":
            return sql
        try:
            return sqlglot.transpile(sql, read="duckdb", write=self.dialect)[0]
        except Exception:
            return sql  # best-effort — fall back to original

    def make_reader(self) -> "DatabaseConnection":
        """Return a connection clone safe for use in a parallel thread.

        Base implementation returns self (serial-safe fallback). Subclasses that
        support concurrent reads override this to open a fresh connection so
        multiple threads can run SELECT queries simultaneously.
        """
        return self


# ── DuckDB ────────────────────────────────────────────────────────────────────

def _duckdb_motherduck_db(dsn: str) -> str | None:
    """Extract the database name from a MotherDuck DSN, e.g. 'md:my_database' -> 'my_database'."""
    d = str(dsn).strip()
    if d.lower().startswith("md:"):
        db = d[3:].strip().split("/")[0]
        return db if db else None
    return None


def _duckdb_is_local(path: str | Path) -> bool:
    """Return True if the DuckDB path is a local file, False for remote URLs."""
    p = str(path).lower()
    return not any(p.startswith(prefix) for prefix in ("md:", "s3://", "http://", "https://", "gs://", "azure://", "memory:"))

def _apply_lane_envelope(duck_conn, connection_id: str) -> None:
    """Apply the connection's per-workspace DuckDB resource envelope (R6 — aughor/db/lanes.py):
    PRAGMA memory_limit + threads, so a workspace's queries run inside a fixed compute budget.
    No-op at defaults (nothing emitted unless an operator configured a limit); fail-open — a
    lane never breaks a connection open."""
    if not connection_id:
        return
    try:
        from aughor.db.lanes import lane_for_connection
        lane_for_connection(connection_id).apply_envelope(duck_conn)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).debug("lane envelope skipped (%s): %s", connection_id, _exc)


def apply_lane_envelope(duck_conn, connection_id: str) -> None:
    """Public: apply the per-workspace DuckDB resource envelope (R6) — for out-of-module
    connection lanes (e.g. DuckLake) that open their own handle, rather than reaching into
    the leading-underscore internal."""
    _apply_lane_envelope(duck_conn, connection_id)


def _maybe_register_ai_udfs(duck_conn, md_db) -> None:
    """Register the governed ``prompt()``/``embedding()`` AI-column UDFs (R8) when
    ``AUGHOR_AI_SQL`` is on, so agent-generated SQL can compute an AI column in-query.
    Skipped for MotherDuck-backed connections (they have NATIVE prompt()/embedding() — don't
    shadow them) and a strict no-op when the flag is off. Fail-open — never breaks a connect."""
    # On-connect hooks (agent-registered): e.g. installing the AI prompt()/embedding()
    # UDFs when AUGHOR_AI_SQL is on. No-op if nothing is registered.
    from aughor.kernel.registries.execution_hooks import run_on_connect_hooks
    run_on_connect_hooks(duck_conn, is_motherduck=bool(md_db))


class DuckDBConnection(DatabaseConnection):
    dialect = "duckdb"

    def __init__(self, path: str | Path, schema_name: str | None = None, connection_id: str = ""):
        self._path = Path(path)
        # Remote DuckDB backends (MotherDuck, S3, etc.) often fail with read_only=True.
        _is_local = _duckdb_is_local(self._path)
        self._conn = duckdb.connect(str(self._path), read_only=_is_local)
        self._connection_id = connection_id
        self._schema_name = schema_name or None
        # For MotherDuck, explicitly switch to the target database so that
        # SHOW TABLES and duckdb_tables() return tables from that DB, not the default.
        _md_db = _duckdb_motherduck_db(str(self._path))
        if _md_db:
            try:
                self._conn.execute(f'USE "{_md_db}"')
            except Exception:
                pass  # best-effort
        if schema_name and not _md_db:
            # Point the execution context at the requested schema so queries
            # land in the right namespace without requiring fully-qualified names.
            try:
                self._conn.execute(f"SET search_path = '{schema_name}'")
            except Exception:
                pass  # best-effort — don't fail the connection over schema routing
        # R6: bound this workspace's compute (memory_limit + threads). No-op at defaults.
        _apply_lane_envelope(self._conn, connection_id)
        # R8: optionally expose the governed AI-column UDFs to generated SQL (opt-in, no-op off).
        _maybe_register_ai_udfs(self._conn, _md_db)

    def make_reader(self) -> "DuckDBConnection":
        """Open a fresh read-only DuckDB connection for use in a parallel thread.

        DuckDB allows multiple concurrent readers on the same database file via
        separate connections. Each connection has its own internal cursor state,
        so there are no shared-state races between threads.
        """
        clone = DuckDBConnection.__new__(DuckDBConnection)
        clone._path = self._path
        clone._schema_name = self._schema_name
        clone._connection_id = self._connection_id
        clone._ontology = self._ontology
        clone._conn = duckdb.connect(str(self._path), read_only=_duckdb_is_local(self._path))
        _md_db = _duckdb_motherduck_db(str(self._path))
        if _md_db:
            try:
                clone._conn.execute(f'USE "{_md_db}"')
            except Exception:
                pass
        if self._schema_name and not _md_db:
            try:
                clone._conn.execute(f"SET search_path = '{self._schema_name}'")
            except Exception:
                pass
        # R6: a reader runs in the same workspace lane → same resource envelope.
        _apply_lane_envelope(clone._conn, clone._connection_id)
        # R8: a reader runs the same generated SQL → same governed AI-column UDFs.
        _maybe_register_ai_udfs(clone._conn, _md_db)
        return clone

    def raw_execute(self, sql: str) -> tuple[list[str], list, list[str]]:
        """Execute a raw SQL query bypassing validation and security checks.
        For metadata queries only. Returns (column_names, rows, types)."""
        self._conn.execute(sql)
        rows = self._conn.fetchall()
        desc = self._conn.description or []
        columns = [d[0] for d in desc]
        types = [str(d[1]) for d in desc]
        return columns, rows, types

    def dry_run(self, sql: str) -> tuple[bool, str]:
        """Run EXPLAIN against DuckDB — catches bad column/table names without returning rows."""
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql, getattr(self, "dialect", "duckdb"))
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
            result = sqlglot.transpile(sql, read="duckdb", write="duckdb", error_level=sqlglot.ErrorLevel.IGNORE)
            return result[0] if result and result[0] else sql
        except Exception:
            return sql

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        import time as _time
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql, getattr(self, "dialect", "duckdb"))
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
        """Fast schema introspection — returns immediately. Never blocks on profiles, ontology, or LLM calls.

        Renders the raw schema (platform) and runs the registered FAST schema
        annotators (agent: glossary/joins/metrics enrichment + exploration). Returns
        the raw schema unchanged if no annotators are registered."""
        from aughor.db.schema_render import render_raw_schema
        from aughor.kernel.registries.schema_annotators import run_annotators
        base = render_raw_schema(self._conn, self._schema_name, self._connection_id or "fixture")
        return run_annotators(self, base, phase="fast")

    def build_intelligence(self) -> str:
        """Heavy path: profiles + ontology + enrichment. Call this from a background task, never on the hot path.

        Renders the raw schema (platform) and runs the registered HEAVY schema
        annotators (agent: enrichment + value profiles + the structural/semantic
        ontology + exploration), which set self._ontology / self.last_build."""
        from aughor.db.schema_render import render_raw_schema
        from aughor.kernel.registries.schema_annotators import run_annotators
        base = render_raw_schema(self._conn, self._schema_name, self._connection_id or "fixture")
        return run_annotators(self, base, phase="heavy")

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
        # Enforce read-only at the SESSION level (SEC-02 / INV-2). Aughor is a
        # read-only analyst over Postgres; the SQL safety gate is defence-in-depth,
        # but the connection itself must reject writes. `options=` applies BEFORE
        # any statement runs — even under autocommit each implicit txn inherits it,
        # so a write raises "cannot execute ... in a read-only transaction". (SET
        # search_path is a session command, not DML, so it is still permitted.)
        self._conn = psycopg2.connect(self._dsn, options="-c default_transaction_read_only=on")
        self._conn.autocommit = True
        # Set search_path so unqualified table names resolve to the right schema
        if self._schema_name != "public":
            with self._conn.cursor() as cur:
                cur.execute(f"SET search_path = {self._schema_name}")

    def make_reader(self) -> "PostgresConnection":
        """Open a fresh psycopg2 connection for use in a parallel thread.

        psycopg2 connections are not thread-safe, so each parallel worker needs
        its own connection. We reuse the same DSN and schema settings.
        """
        clone = PostgresConnection.__new__(PostgresConnection)
        clone._dsn = self._dsn
        clone._schema_name = self._schema_name
        clone._connection_id = self._connection_id
        clone._varchar_ts_cols = self._varchar_ts_cols
        clone._ontology = self._ontology
        clone._connect()
        return clone

    def raw_execute(self, sql: str) -> tuple[list[str], list, list[str]]:
        """Execute a raw SQL query bypassing validation and security checks.
        For metadata queries only. Returns (column_names, rows, types)."""
        self._conn.execute(sql)
        rows = self._conn.fetchall()
        desc = self._conn.description or []
        columns = [d[0] for d in desc]
        types = [_pg_type_name(d[1]) for d in desc]
        return columns, rows, types

    def dry_run(self, sql: str) -> tuple[bool, str]:
        """Run EXPLAIN against Postgres — catches bad column/table names without returning rows."""
        sql = sql.strip().rstrip(";")
        ok, reason = _validate(sql, getattr(self, "dialect", "duckdb"))
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
        ok, reason = _validate(sql, getattr(self, "dialect", "duckdb"))
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

        from aughor.db.annotations import load_annotations, inject_into_schema_parts
        _ann = load_annotations(self._connection_id or "postgres")

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
                inject_into_schema_parts(parts, table, None, _ann)
                current_table = table
            parts.append(f"  {col}  {dtype}")
            inject_into_schema_parts(parts, table, col, _ann)

        schema_str = "\n".join(parts)
        hints = self._detect_sql_hints(rows)  # also populates self._varchar_ts_cols
        if hints:
            schema_str += "\n\n" + hints

        from aughor.kernel.registries.schema_annotators import run_annotators
        return run_annotators(self, schema_str, phase="heavy")

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

    def is_healthy(self) -> bool:
        """Cheap liveness probe so the pool never hands out a dropped connection."""
        try:
            if self._conn is None or getattr(self._conn, "closed", 1):
                return False
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception:
            return False


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
    """Open (or reuse a pooled) registered connection with stored metadata applied."""
    from aughor.db.registry import get_dsn, get_meta
    from aughor.db import pool
    conn_type, dsn = get_dsn(conn_id)
    meta = get_meta(conn_id)
    schema_name = meta.get("schema_name")
    key = f"{conn_id}|{schema_name or ''}"
    return pool.acquire(key, lambda: open_connection(
        conn_type, dsn,
        schema_name=schema_name,
        connection_id=conn_id,
        meta=meta,
    ))


def open_connection_for_with_schema(conn_id: str, schema_name: str | None = None) -> DatabaseConnection:
    """Open a registered connection with an optional schema override.

    Used by Canvas-scoped flows so that the connection resolves tables in the
    Canvas's selected schema even when the underlying connection was registered
    without one.
    """
    from aughor.db.registry import get_dsn, get_meta
    from aughor.db import pool
    conn_type, dsn = get_dsn(conn_id)
    meta = get_meta(conn_id)
    eff_schema = schema_name or meta.get("schema_name")
    key = f"{conn_id}|{eff_schema or ''}"
    return pool.acquire(key, lambda: open_connection(
        conn_type, dsn,
        schema_name=eff_schema,
        connection_id=conn_id,
        meta=meta,
    ))
