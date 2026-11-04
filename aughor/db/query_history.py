"""Arc NV-3 — a warehouse's OWN query history, read as statement text, or withheld and said.

Snowflake, ClickHouse, BigQuery and the lakehouse engine's system tables each keep what people ran there. NVIDIA's Auto-Ontology reads
three of those and mines them into reusable SQL attributes (`docs/NVIDIA_AUTO_ONTOLOGY_STUDY_2026-11-04.md` §5.1);
Aughor's miner (`aughor.sql.query_log_miner`) is as capable and read only Aughor's own executed SQL. This module
is the SOURCE it lacked: one shape for a history read, so the candidate door (`aughor.ontology.candidates`) mines
every engine the same way, and an engine with no readable history says so instead of returning an empty list a
reader would take for "nobody queries this warehouse".

Three rules:

* **Statement text only, never rows.** A history read returns the SQL people wrote and when it finished. It is still
  a whole-workspace read of other people's work, so it runs only when the organisation allows it
  (`aughor.orgsettings.allows("read_query_history")`, off by default) — the door checks, not this module.
* **Through the connection's own door**, as every platform read is (`internal=True`): the read-only gate, the trail
  and the typed error stand. A failed read is a `QueryHistory` with `error` set — a value, never a raise.
* **Withheld is said.** `supported=False` with a `note` names the engine that has no history to read (DuckDB, a
  file, Postgres — whose `pg_stat_activity` is the moment's activity, not a log, and is deliberately not read).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: How far back a history read looks, and how many statements it keeps — bounded on every engine.
DEFAULT_HOURS = 24 * 14
DEFAULT_LIMIT = 2000


@dataclass(frozen=True)
class HistoryRow:
    """One statement from the warehouse's history."""
    ended_at: str      # the engine's end time as text (ISO where the engine gives one)
    sql: str
    user: str = ""     # the engine's user or principal, when it carries one — never a row's value


@dataclass
class QueryHistory:
    """What a history read returned, or why it did not."""
    engine: str = ""
    supported: bool = False
    rows: list[HistoryRow] = field(default_factory=list)
    hours: int = DEFAULT_HOURS
    limit: int = DEFAULT_LIMIT
    note: str = ""      # why nothing is here, when nothing is — the sentence a reader gets
    error: str = ""     # the engine's refusal, when the read ran and failed
    source: str = ""    # the view or table the read came from

    @property
    def statements(self) -> list[str]:
        return [r.sql for r in self.rows if r.sql and r.sql.strip()]

    def to_dict(self) -> dict:
        return {"engine": self.engine, "supported": self.supported, "count": len(self.rows), "hours": self.hours,
                "limit": self.limit, "note": self.note, "error": self.error, "source": self.source}


def unsupported(engine: str, why: str = "") -> QueryHistory:
    """The answer for an engine with no readable history: said, so an empty report never means 'nobody queries it'."""
    return QueryHistory(engine=engine, supported=False,
                        note=why or f"{engine or 'this engine'} keeps no query history the platform can read")


def rows_from_result(result: Any, engine: str, *, source: str, hours: int, limit: int) -> QueryHistory:
    """A connection's `QueryResult` of ``(ended_at, sql[, user])`` rows → a `QueryHistory`; the engine's error kept."""
    if getattr(result, "error", None):
        return QueryHistory(engine=engine, supported=True, hours=hours, limit=limit, source=source,
                            error=str(result.error), note=f"the history read on {source} failed")
    out: list[HistoryRow] = []
    for row in getattr(result, "rows", None) or []:
        if not row or len(row) < 2:
            continue
        sql = str(row[1] or "").strip()
        if not sql or sql.upper() == "NULL":
            continue
        out.append(HistoryRow(ended_at=str(row[0] or ""), sql=sql,
                              user=str(row[2]) if len(row) > 2 and row[2] not in (None, "NULL") else ""))
    note = "" if out else f"no finished SELECT statements in the last {hours} hours on {source}"
    return QueryHistory(engine=engine, supported=True, rows=out, hours=hours, limit=limit, source=source, note=note)


def read_query_history(conn: Any, *, hours: int = DEFAULT_HOURS, limit: int = DEFAULT_LIMIT) -> QueryHistory:
    """Read ``conn``'s history through its own method, or say the engine has none."""
    reader = getattr(conn, "query_history", None)
    if reader is None:
        return unsupported(str(getattr(conn, "dialect", "") or type(conn).__name__))
    return reader(hours=hours, limit=limit)


def not_platform_statement(sql: str) -> bool:
    """Whether a statement is somebody's question rather than a catalog read: the platform's own metadata and history
    reads, and an engine's system views, teach the miner nothing about how the business is queried."""
    low = sql.lower()
    return not any(marker in low for marker in (
        "information_schema", "system.query_log", "system.columns", "system.tables", "query_history(",
        "system.query.history", "pg_catalog", "pg_stat", "show tables", "describe ", "summarize ",
    ))
