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
        import re as _re

        def _valid_lifecycle_state(s: str) -> bool:
            """Same heuristic used by the ontology builder's _is_valid_state."""
            s = s.strip()
            if not s or s == "null":
                return False
            if "/" in s:
                return False
            if _re.fullmatch(r"[A-Z]{2}", s):   # bare ISO-2 codes
                return False
            if len(s) > 30:
                return False
            return True

        def _plausible_lifecycle_states(states: list) -> bool:
            """Reject columns whose states look like descriptions, not process stages."""
            valid = [s for s in states if _valid_lifecycle_state(s)]
            if not valid:
                return False
            avg_len = sum(len(s) for s in valid) / len(valid)
            avg_words = sum(len(s.split()) for s in valid) / len(valid)
            return avg_len <= 15 and avg_words <= 2

        lifecycle_maps: dict = state.get("lifecycle_maps", {})
        if lifecycle_maps:
            for entity in graph.entities.values():
                for src_table in entity.source_tables:
                    if src_table in lifecycle_maps:
                        lm = lifecycle_maps[src_table]
                        col = lm.get("status_column")
                        if not col:
                            break
                        raw_states = lm.get("states", [])
                        if not _plausible_lifecycle_states(raw_states):
                            # Explorer found something that looks like a
                            # description column (KPI names, formula strings,
                            # etc.) — skip silently.
                            break
                        entity.has_lifecycle     = True
                        entity.lifecycle_column  = col
                        entity.lifecycle_states  = [s for s in raw_states if _valid_lifecycle_state(s)]
                        entity.terminal_states   = lm.get("terminal_states", entity.terminal_states)
                        terminal = lm.get("terminal_states", [])
                        if terminal:
                            tl = ", ".join(f"'{s}'" for s in terminal)
                            entity.active_filter = f"{col} NOT IN ({tl})"
                        # Rebuild object sets to reflect the explorer-verified lifecycle
                        try:
                            from aughor.ontology.builder import _build_object_sets
                            entity.object_sets = _build_object_sets(
                                entity_id=entity.id,
                                lifecycle_col=entity.lifecycle_column,
                                lifecycle_states=entity.lifecycle_states,
                                terminal_states=entity.terminal_states,
                                active_filter=entity.active_filter,
                            )
                        except Exception:
                            pass
                        break

        # ── Null meaning merge (phase 3 → EntityProperty.null_meaning) ──────────
        # Explorer state keys are "table:col" (colon-separated).
        null_meanings: dict = state.get("null_meanings", {})
        if null_meanings:
            for entity in graph.entities.values():
                src_table_set = set(entity.source_tables)
                for key, meaning_obj in null_meanings.items():
                    if ":" not in key:
                        continue
                    tbl_part, col_part = key.split(":", 1)
                    if tbl_part not in src_table_set:
                        continue
                    if col_part not in entity.properties:
                        continue
                    prop = entity.properties[col_part]
                    if prop.null_meaning:
                        continue  # already set — don't overwrite
                    if isinstance(meaning_obj, dict):
                        meaning_text = meaning_obj.get("meaning", "")
                    else:
                        meaning_text = str(meaning_obj)
                    if meaning_text and meaning_text not in ("unknown", "Unknown", ""):
                        prop.null_meaning = meaning_text

        # ── Distribution stats merge (phase 6 → EntityProperty numeric fields) ──
        # Explorer state key: "table:col", value: {shape, p25, p50, p75, ...}
        distributions: dict = state.get("distributions", {})
        if distributions:
            for entity in graph.entities.values():
                src_table_set = set(entity.source_tables)
                for key, dist_info in distributions.items():
                    if ":" not in key or not isinstance(dist_info, dict):
                        continue
                    tbl_part, col_part = key.split(":", 1)
                    if tbl_part not in src_table_set:
                        continue
                    if col_part not in entity.properties:
                        continue
                    prop = entity.properties[col_part]
                    shape = dist_info.get("shape", "")
                    if shape:
                        prop.distribution_shape = shape
                    for pct_field in ("p25", "p50", "p75"):
                        raw = dist_info.get(pct_field)
                        if raw is not None:
                            try:
                                setattr(prop, pct_field, float(raw))
                            except (TypeError, ValueError):
                                pass

        # ── Insights merge (phase 8 → OntologyEntity.exploration_insights) ──────
        # Each insight has {entities_involved: list[str], finding: str, novelty: int}.
        # Match by source table name (most reliable — explorer uses table names).
        insights: list = state.get("insights", [])
        if insights:
            sorted_insights = sorted(
                insights, key=lambda x: x.get("novelty", 0) if isinstance(x, dict) else 0,
                reverse=True,
            )
            for entity in graph.entities.values():
                entity_name_set = {t.lower() for t in entity.source_tables}
                entity_name_set.add(entity.id.lower())
                entity_name_set.add(entity.display_name.lower())
                findings: list[str] = []
                seen: set[str] = set()
                for item in sorted_insights:
                    if not isinstance(item, dict):
                        continue
                    involved = {e.lower() for e in item.get("entities_involved", [])}
                    if not (entity_name_set & involved):
                        continue
                    finding = item.get("finding", "").strip()
                    if finding and finding not in seen:
                        findings.append(finding)
                        seen.add(finding)
                entity.exploration_insights = findings[:10]

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

_PG_OID_MAP: dict[int, str] = {
    16: "BOOLEAN", 21: "SMALLINT", 23: "INTEGER", 20: "BIGINT",
    700: "REAL", 701: "DOUBLE PRECISION", 1700: "NUMERIC",
    1082: "DATE", 1083: "TIME", 1266: "TIMETZ",
    1114: "TIMESTAMP", 1184: "TIMESTAMPTZ", 1186: "INTERVAL",
    25: "TEXT", 1042: "CHAR", 1043: "VARCHAR",
    18: "CHAR", 19: "NAME", 114: "JSON", 3802: "JSONB",
    17: "BYTEA", 2950: "UUID",
}


def _pg_type_name(oid: int) -> str:
    return _PG_OID_MAP.get(oid, f"TYPE({oid})")

class DatabaseConnection(ABC):
    dialect: str = "duckdb"
    poolable: bool = True  # may this connection be reused via the pool? (see db/pool.py)
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
        """Fast schema introspection — returns immediately. Never blocks on profiles, ontology, or LLM calls."""
        from aughor.tools.schema import build_schema_context

        base = build_schema_context(
            self._conn,
            schema_name=self._schema_name,
            connection_id=self._connection_id or "fixture",
        )

        # Append exploration intelligence block (reads from disk — no DB calls)
        try:
            from aughor.explorer.store import render_exploration_annotations
            expl_block = render_exploration_annotations(self._connection_id or "fixture")
            if expl_block:
                base += "\n\n" + expl_block
        except Exception:
            pass

        return base

    def build_intelligence(self) -> str:
        """Heavy path: profiles + ontology + enrichment. Call this from a background task, never on the hot path."""
        from aughor.tools.schema import build_schema_context, _compute_join_map, _parse_schema_tables
        from aughor.tools.profile_cache import get_or_build_profiles
        from aughor.tools.profiler import render_profile_annotations

        base = build_schema_context(
            self._conn,
            schema_name=self._schema_name,
            connection_id=self._connection_id or "fixture",
        )

        # Extract table list and fk hints from the join map
        if self._schema_name:
            tables = [
                row[0] for row in self._conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' ORDER BY table_name",
                    [self._schema_name],
                ).fetchall()
            ]
        else:
            tables = [
                row[0] for row in self._conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'temp') "
                    "AND table_type = 'BASE TABLE' ORDER BY table_name",
                ).fetchall()
            ]
        table_cols = _parse_schema_tables(base)
        jmap = _compute_join_map(table_cols)
        fk_hints: dict[str, set[str]] = {t: set() for t in tables}
        for j in jmap.get("joins", []):
            fk_hints.setdefault(j["t1"], set()).add(j["c1"])

        # Record the build outcome so a failure surfaces as an actionable status (which
        # stage failed + why) instead of a silent "empty Hub". Schema loading still never
        # blocks — we record the failure and carry on.
        self.last_build = {"ok": True, "stage": None, "error": None}
        _stage = "profiling"
        try:
            tp, cp = get_or_build_profiles(self, self._connection_id or "fixture", tables, fk_hints)
            from aughor.tools.schema import inject_value_annotations
            base = inject_value_annotations(base, cp)
            annotation = render_profile_annotations(tp, cp)
            if annotation:
                base += "\n\n" + annotation

            from aughor.ontology.store import get_or_build_ontology, save_ontology
            from aughor.ontology.builder import render_ontology_annotations
            from aughor.semantic.glossary import load_merged_glossary
            _glossary = load_merged_glossary()
            _schema_label = self._schema_name or "default"
            _stage = "ontology"
            graph = get_or_build_ontology(
                connection_id=self._connection_id or "fixture",
                schema_name=_schema_label,
                table_profiles=tp,
                column_profiles=cp,
                join_map=jmap,
                glossary=_glossary,
            )
            if graph is None:
                # Fatal for domain intelligence: Phase 8 has no object model to reason over.
                self.last_build = {
                    "ok": False, "stage": "ontology",
                    "error": "the object model could not be built from this schema — it may "
                             "be too sparse to model (no entities/relationships inferred).",
                }
            if graph is not None:
                from aughor.ontology.enricher import ENRICHMENT_VERSION
                from aughor.stats import stats as _st
                if not graph.enriched or graph.enrichment_version < ENRICHMENT_VERSION:
                    _st.inc("enrichment_runs")
                    _stage = "enrichment"
                    try:
                        from aughor.ontology.enricher import enrich_ontology_semantics
                        from aughor.llm.provider import get_provider
                        graph = enrich_ontology_semantics(
                            graph, get_provider("coder"), _glossary, base
                        )
                        save_ontology(graph.connection_id, graph.schema_name, graph.schema_fingerprint, graph)
                    except Exception as _enr_exc:
                        # Non-fatal — the ontology still exists, so Phase 8 can run — but
                        # record it (the descriptions/formulas just won't be enriched).
                        self.last_build = {
                            "ok": True, "stage": "enrichment",
                            "error": f"semantic enrichment failed (ontology still usable): {str(_enr_exc)[:200]}",
                        }
                    _stage = "ontology"
                else:
                    _st.inc("enrichment_cache_hits")
                # M24c: self-validate enriched semantics against the live DB once
                # per fingerprint, persisting the verified flags. Only verified
                # formulas reach the NL2SQL prompt with authority.
                from aughor.ontology.validator import VALIDATION_VERSION
                if not graph.validated or graph.validation_version < VALIDATION_VERSION:
                    try:
                        from aughor.ontology.validator import validate_semantics
                        graph = validate_semantics(graph, self)
                        save_ontology(graph.connection_id, graph.schema_name, graph.schema_fingerprint, graph)
                    except Exception as _val_exc:
                        # Best-effort — never block schema loading — but visible, not silent.
                        from aughor.kernel.errors import tolerate
                        tolerate(_val_exc, "semantic validation is best-effort; ontology still usable "
                                 "unvalidated", counter="ontology.validation",
                                 conn_id=self._connection_id or None)
                _apply_explorer_to_ontology(graph, self._connection_id or "fixture")
                self._ontology = graph
                onto_block = render_ontology_annotations(graph)
                if onto_block:
                    base += "\n\n" + onto_block
        except Exception as _build_exc:
            # Record which stage broke so the explorer can surface an actionable status.
            self.last_build = {"ok": False, "stage": _stage, "error": str(_build_exc)[:400]}

        # Append exploration intelligence block
        try:
            from aughor.explorer.store import render_exploration_annotations
            expl_block = render_exploration_annotations(self._connection_id or "fixture")
            if expl_block:
                base += "\n\n" + expl_block
        except Exception as _expl_exc:
            from aughor.kernel.errors import tolerate
            tolerate(_expl_exc, "exploration annotation block is additive; schema loads without it",
                     counter="ontology.exploration_block", conn_id=self._connection_id or None)

        # Journal the build outcome (K2 event spine) — the original "ontology
        # silently doesn't build" symptom becomes a queryable event with the
        # failing stage + entity count, instead of a dead in-memory last_build.
        try:
            from aughor.kernel.ledger import Ledger
            from aughor.kernel.jobs import current_job_id
            _ents = len(getattr(self._ontology, "entities", {}) or {}) if getattr(self, "_ontology", None) else 0
            _lb = getattr(self, "last_build", {}) or {}
            Ledger.default().emit(
                "ontology.build",
                {"ok": bool(_lb.get("ok", True)) and _ents > 0,
                 "entities": _ents, "stage": _lb.get("stage"), "error": _lb.get("error")},
                conn_id=self._connection_id or None, job_id=current_job_id(),
            )
        except Exception as _j_exc:
            # The ONE place we don't use tolerate() — it journals, which would
            # recurse if the ledger is the thing that's broken. Log and move on.
            import logging as _logging
            _logging.getLogger(__name__).debug("ontology.build journal emit failed: %s", _j_exc)

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
            _schema_label = self._schema_name or "public"
            graph = get_or_build_ontology(
                connection_id=self._connection_id or "postgres",
                schema_name=_schema_label,
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
                        save_ontology(graph.connection_id, graph.schema_name, graph.schema_fingerprint, graph)
                    except Exception:
                        pass  # structural ontology still works
                else:
                    _st.inc("enrichment_cache_hits")
                # M24c: self-validate enriched semantics against the live DB once
                # per fingerprint, persisting the verified flags.
                from aughor.ontology.validator import VALIDATION_VERSION
                if not graph.validated or graph.validation_version < VALIDATION_VERSION:
                    try:
                        from aughor.ontology.validator import validate_semantics
                        graph = validate_semantics(graph, self)
                        save_ontology(graph.connection_id, graph.schema_name, graph.schema_fingerprint, graph)
                    except Exception:
                        pass
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
