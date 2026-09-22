"""CB-2 (2026-09-22) — one connection, one measurement.

``run_sql_for(connection_id)`` returns a ``run_sql(sql) -> (columns, rows, error)`` on that
connection, with the platform's canonical SQL rendered native for the connection's dialect
(`db.dialects.native_sql`, the one seam for dialect differences). `playbook.outcomes` takes the
callable and never imports the DB layer; the outcome door and the heartbeat both build it here,
so a review measures exactly the way an acceptance did.
"""
from __future__ import annotations

from typing import Callable

RunSql = Callable[[str], tuple[list, list, object]]


def run_sql_for(connection_id: str) -> RunSql:
    from aughor.db.connection import open_connection_for
    from aughor.db.dialects import native_sql
    db = open_connection_for(connection_id)

    def run_sql(sql: str):
        res = db.execute("cb2_review", native_sql(db, sql))
        return (list(getattr(res, "columns", []) or []), list(getattr(res, "rows", []) or []),
                getattr(res, "error", None))
    return run_sql
