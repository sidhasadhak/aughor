"""CB-2 (2026-09-22) — one connection, one measurement.

``run_sql_for(connection_id)`` returns a ``run_sql(sql) -> (columns, rows, error)`` on that
connection, with the platform's canonical SQL declared DuckDB to the connection's door, which
renders it for the engine (GM-1, `db.dialects.sql_for_engine`). `playbook.outcomes` takes the
callable and never imports the DB layer; the outcome door and the heartbeat both build it here,
so a review measures exactly the way an acceptance did.
"""
from __future__ import annotations

from typing import Callable

RunSql = Callable[[str], tuple[list, list, object]]


def run_sql_for(connection_id: str, *, internal: bool, label: str = "cb2_review") -> RunSql:
    """``internal`` is the caller's to say, because the callers differ (GM-5): the settling sampler, an outcome's
    measurement and the sentinel's series are the platform's own statements; a monitor's backtest evaluates the
    monitor's SQL, which is somebody's, and is audited under its own ``label``."""
    from aughor.db.connection import open_connection_for
    db = open_connection_for(connection_id)

    def run_sql(sql: str):
        res = db.execute(label, sql, sql_dialect="duckdb", internal=internal)
        return (list(getattr(res, "columns", []) or []), list(getattr(res, "rows", []) or []),
                getattr(res, "error", None))
    return run_sql
