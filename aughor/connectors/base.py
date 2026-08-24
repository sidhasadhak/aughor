"""Connector ABC — extends DatabaseConnection with category + namespace.

All Sprint-25 connectors inherit from this instead of DatabaseConnection
directly. Existing DuckDB and Postgres connections remain in db/connection.py
and are handled by open_connection() as before; they gain `connector_category`
and `namespace` through monkey-patching at the registry layer.
"""
from __future__ import annotations

from typing import Literal

from aughor.db.connection import DatabaseConnection


ConnectorCategory = Literal["warehouse", "file", "api", "knowledge"]


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
        from aughor.sql.params import ParamRenderError, render_for_engine

        if not self.param_style:
            return super().execute_with_params(hypothesis_id, sql, params)

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked
        sql, _rp = enforce_row_policy(self, hypothesis_id, sql)
        if _rp is not None:
            return _rp

        try:
            rendered = render_for_engine(sql, self.param_style)
        except ParamRenderError as exc:
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[],
                               row_count=0, error=str(exc))

        _t0 = time.monotonic()
        try:
            columns, rows_raw = self._bind_execute(rendered, params or {})
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
