"""Connector ABC — extends DatabaseConnection with category + namespace.

All Sprint-25 connectors inherit from this instead of DatabaseConnection
directly. Existing DuckDB and Postgres connections remain in db/connection.py
and are handled by open_connection() as before; they gain `connector_category`
and `namespace` through monkey-patching at the registry layer.
"""
from __future__ import annotations

from typing import Literal

from aughor.db.connection import DatabaseConnection
from aughor.db.single_flight import single_flight_build


ConnectorCategory = Literal["warehouse", "file", "api", "knowledge"]

_INTEGER_KINDS = frozenset({"INTEGER", "INT", "INT64", "BIGINT", "SMALLINT", "TINYINT", "LONG", "LONGLONG", "SHORT",
                            "TINY", "INT24", "YEAR"})
_FLOAT_KINDS = frozenset({"FLOAT", "FLOAT64", "DOUBLE", "REAL"})
_DECIMAL_KINDS = frozenset({"NUMERIC", "BIGNUMERIC", "DECIMAL", "NEWDECIMAL", "FIXED", "NUMBER"})


def stage_type(kind: object, precision: object = None, scale: object = None) -> str:
    """A driver's column type in the names the cross-source stage reads — BIGINT, DOUBLE, DECIMAL(p,s), BOOLEAN, DATE,
    TIMESTAMP, VARCHAR. The stage types a column from its values, so this name decides only a column holding no value,
    which would otherwise be staged as text."""
    k = str(kind or "").strip().upper()
    if k in _INTEGER_KINDS:
        return "BIGINT"
    if k in _FLOAT_KINDS:
        return "DOUBLE"
    if k in _DECIMAL_KINDS:
        places = scale if isinstance(scale, int) else (9 if k in ("NUMERIC", "BIGNUMERIC") else 0)
        if places == 0:
            return "BIGINT"
        digits = precision if isinstance(precision, int) and precision > 0 else 38
        return f"DECIMAL({digits},{places})"
    if k in ("BOOLEAN", "BOOL"):
        return "BOOLEAN"
    if k in ("DATE", "NEWDATE"):
        return "DATE"
    if k.startswith("TIMESTAMP") or k == "DATETIME":
        return "TIMESTAMP"
    return "VARCHAR" if k else ""


class Connector(DatabaseConnection):
    """Base class for all pluggable connectors.

    Sub-classes must:
      - implement the DatabaseConnection ABC (execute, get_schema, test, close)
      - set `connector_category` class variable
      - set `dialect` class variable (usually "duckdb" for file connectors)
      - set `param_style` + `_bind_execute` if the driver can bind values (see below)
    """

    connector_category: ConnectorCategory = "warehouse"

    #: How this connector's DRIVER spells a bind placeholder — see `sql.params`. ``None``
    #: means it cannot bind, and `execute_with_params` keeps the base class's visible
    #: refusal rather than falling back to anything that builds the statement by
    #: concatenation. Deliberately a DRIVER fact, not a dialect one: `ExasolConnection`
    #: declares ``dialect = "postgres"`` for transpile and `pyexasol` accepts none of
    #: Postgres's placeholder syntax.
    param_style: str | None = None

    #: Row cap for a bound run, matching what every connector's `execute` already applies.
    max_rows: int = 2000

    def _duckdb_read(self, handle, hypothesis_id: str, sql: str, max_rows: int):
        """The read every DuckDB-backed connector runs — MotherDuck, S3, Google Sheets, the federated connection and
        the REST syncs: the security gates and the row policy, DuckDB's JULIANDAY refusal healed, the rows kept up to
        ``max_rows`` and counted in full, typed values offered to a caller that asked for them, and the post-pass.

        It lives here once because it was copied five times, and no copy had grown what `DuckDBConnection` has since:
        typed capture, a bounded read, the heal. So a cross-source object query refused every one of them as a side."""
        import time

        from aughor.control_plane.contracts.execution import QueryResult
        from aughor.db.connection import (
            enforce_row_policy, heal_duckdb_refusal, offer_typed_rows, security_post, security_pre,
        )

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked
        sql, _rp = enforce_row_policy(self, hypothesis_id, sql)   # RBAC row-policy (Rec 7); no-op off
        if _rp is not None:
            return _rp

        started = time.monotonic()

        def _attempt(statement: str) -> QueryResult:
            try:
                handle.execute(statement)
                rows_raw = handle.fetchall()
                description = handle.description or []
                offer_typed_rows(rows_raw[:max_rows], truncated=len(rows_raw) > max_rows,
                                 types=[str(d[1]) for d in description])
                return QueryResult(
                    hypothesis_id=hypothesis_id, sql=statement, columns=[d[0] for d in description],
                    rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows_raw[:max_rows]],
                    row_count=len(rows_raw),
                )
            except Exception as exc:  # noqa: BLE001 — an engine error is the result's error, never a raise
                return QueryResult(hypothesis_id=hypothesis_id, sql=statement, columns=[], rows=[], row_count=0,
                                   error=str(exc))

        result = heal_duckdb_refusal(_attempt(sql), sql, _attempt)
        return security_post(self._connection_id, hypothesis_id, result.sql, result,
                             (time.monotonic() - started) * 1000)

    @single_flight_build
    def build_intelligence(self) -> str:
        """Heavy schema build: run the registered HEAVY annotators (value profiles +
        the structural/semantic ontology + enrichment) over this connector's schema.

        The method existed only on the DuckDB-family connectors, so the ontology —
        and with it domain intelligence and the briefing — could never be built for
        any warehouse engine: the explorer's ontology gate and the birth rite both
        call ``db.build_intelligence()`` and hit AttributeError. The annotator
        pipeline itself is connection-agnostic (profiles via ``conn.execute``, the
        object model from profiles + the join map), so the base default is the same
        thin wrapper the file connectors use. They keep their overrides (their raw
        structure comes from ``_schema_string()`` before annotation).
        """
        base = self.get_schema()
        if not base or base.startswith("No tables") or base.startswith("Schema unavailable"):
            return base
        from aughor.kernel.registries.schema_annotators import run_annotators
        return run_annotators(self, base, phase="heavy")

    def _driver_handle(self):
        """`self._conn`, or `self._duckdb` for the connectors that keep it there.

        Six connectors — S3, Federated, Google Sheets and the three REST mirrors — hold
        their DuckDB handle as ``self._duckdb``, so the base `interrupt()` found nothing and
        returned False on every one of them: honest, but it meant Cancel did nothing on six
        connectors whose engine supports it perfectly well. This is SE-3 F again, and it
        stayed hidden because the guard looked for the substring ``self._conn`` in the class
        source, which ``self._connection_id`` contains — every one of them matched a field
        that has nothing to do with a driver.
        """
        # Explicit None checks, not `or`: a driver object that defines __bool__ or __len__
        # and happens to be falsy would otherwise be skipped in favour of an attribute that
        # is not the driver at all.
        handle = getattr(self, "_conn", None)
        return handle if handle is not None else getattr(self, "_duckdb", None)

    def _bind_execute(self, sql: str, params: dict) -> tuple[list[str], list]:
        """Run already-rendered `sql` with `params` as bind values; return (columns, rows).

        The ONE piece that differs per driver. Everything around it — the safety pre-check,
        the row policy, the row cap, the value formatting, the post-check — is identical in
        every connector here and lives in `execute_with_params`, so adding binding to one is
        a six-line method rather than a copy of an envelope that then drifts from the others.
        """
        raise NotImplementedError

    def execute_with_params(self, hypothesis_id: str, sql: str, params: dict):
        """Run `sql` with `:name` parameters as real bind values.

        Order matters and follows `DuckDBConnection._run`: the safety pre-check and the row
        policy see the ``:name`` form, which sqlglot parses as a Placeholder in every
        dialect we validate against — so the guards read the same statement shape the engine
        will run. The rewrite to the driver's own spelling happens at the driver call and
        NOWHERE earlier; Postgres's ``%(name)s``, translated up here, fails sqlglot outright.
        """
        import time
        from aughor.control_plane.contracts.execution import QueryResult
        from aughor.db.connection import enforce_row_policy, security_pre, security_post
        from aughor.sql.params import ParamRenderError, expand_list_params, render_for_engine

        if not self.param_style:
            return super().execute_with_params(hypothesis_id, sql, params)

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked
        sql, _rp = enforce_row_policy(self, hypothesis_id, sql)
        if _rp is not None:
            return _rp

        try:
            # SE-8C — a LIST value (a multiselect widget) becomes a parenthesised group
            # of scalar binds here, after the guards saw the `:name` form and before
            # the driver, which can only bind scalars.
            exec_sql, bind_params = expand_list_params(sql, params or {})
            rendered = render_for_engine(exec_sql, self.param_style)
        except ParamRenderError as exc:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[],
                               row_count=0, error=str(exc))

        _t0 = time.monotonic()
        try:
            columns, rows_raw = self._bind_execute(rendered, bind_params)
            rows = [[str(v) if v is not None else "NULL" for v in row]
                    for row in rows_raw[:self.max_rows]]
            result = QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=columns,
                                 rows=rows, row_count=len(rows_raw))
        except Exception as e:
            result = QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[],
                                 row_count=0, error=str(e))
        # `sql` and not `rendered`: every downstream reader of a receipt — the guards, the
        # editor header, the ledger — was written against the statement the USER wrote.
        elapsed_ms = (time.monotonic() - _t0) * 1000
        return security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    @property
    def namespace(self) -> str:
        """Short prefix used in federated queries (14d). Defaults to connection_id."""
        return getattr(self, "_connection_id", "")

    # ── Helpers every connector gets for free ─────────────────────────────────

    @classmethod
    def dep_check(cls, package: str, install: str) -> None:
        """Raise ImportError with a helpful message if `package` is not installed."""
        try:
            __import__(package)
        except ImportError:
            raise ImportError(
                f"{cls.__name__} requires '{package}'. "
                f"Install it with:  uv pip install '{install}'"
            ) from None

    def ingest_file(self, file_path, table_name: str) -> None:  # type: ignore[override]
        """Optional: file connectors override this to accept uploaded files."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support file ingestion")
