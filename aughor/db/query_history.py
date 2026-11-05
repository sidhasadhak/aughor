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
  file). Postgres reads `pg_stat_statements` where the extension is installed — an AGGREGATE of every normalised
  statement with its call count since the last reset, so a row stands for `calls` runs and literals read as `$1` —
  and says so when it is not; `pg_stat_activity` is the moment's activity, not a log, and is never read.
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
    calls: int = 1     # how many runs this row stands for: 1 from a log, the call count from an aggregate


#: How many runs one aggregated statement may count for when the miner weighs it — a statement run ten thousand
#: times by a dashboard is "how the warehouse is queried", and it is also one statement; the cap keeps it from
#: drowning every other fact while still letting it clear the miner's floor.
CALLS_CAP = 100


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

    @property
    def calls(self) -> int:
        return sum(max(1, r.calls) for r in self.rows if r.sql and r.sql.strip())

    def weighted_statements(self, cap: int = CALLS_CAP) -> list[str]:
        """Each statement once per run it stands for (at most ``cap``), so the miner's frequencies read as calls:
        a log row counts once, an aggregate's row its call count."""
        out: list[str] = []
        for r in self.rows:
            if r.sql and r.sql.strip():
                out.extend([r.sql] * max(1, min(int(r.calls or 1), cap)))
        return out

    def to_dict(self) -> dict:
        return {"engine": self.engine, "supported": self.supported, "count": len(self.rows), "calls": self.calls,
                "hours": self.hours, "limit": self.limit, "note": self.note, "error": self.error, "source": self.source}


def unsupported(engine: str, why: str = "") -> QueryHistory:
    """The answer for an engine with no readable history: said, so an empty report never means 'nobody queries it'."""
    return QueryHistory(engine=engine, supported=False,
                        note=why or f"{engine or 'this engine'} keeps no query history the platform can read")


def rows_from_result(result: Any, engine: str, *, source: str, hours: int, limit: int,
                     aggregate_note: str = "") -> QueryHistory:
    """A connection's `QueryResult` of ``(ended_at, sql[, user[, calls]])`` rows → a `QueryHistory`; the engine's
    error kept. ``aggregate_note`` is what a source that counts runs rather than logging them says of itself."""
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
        calls = 1
        if len(row) > 3 and row[3] not in (None, "NULL"):
            try:
                calls = max(1, int(float(row[3])))
            except (TypeError, ValueError):
                calls = 1
        out.append(HistoryRow(ended_at=str(row[0] or ""), sql=sql,
                              user=str(row[2]) if len(row) > 2 and row[2] not in (None, "NULL") else "", calls=calls))
    if not out:
        note = f"no finished SELECT statements in the last {hours} hours on {source}"
    else:
        note = aggregate_note
    return QueryHistory(engine=engine, supported=True, rows=out, hours=hours, limit=limit, source=source, note=note)


def read_query_history(conn: Any, *, hours: int = DEFAULT_HOURS, limit: int = DEFAULT_LIMIT) -> QueryHistory:
    """Read ``conn``'s history through its own method, or say the engine has none."""
    reader = getattr(conn, "query_history", None)
    if reader is None:
        return unsupported(str(getattr(conn, "dialect", "") or type(conn).__name__))
    return reader(hours=hours, limit=limit)


# ── Arc NV-5 — a feature's prerequisite on the engine, said with its fix and provisioned where the platform can ──

#: What each engine needs before its history can be read, in the words an admin acts on. An engine absent here keeps
#: no history the platform reads, and the readiness says so.
PREREQUISITES: dict[str, str] = {
    "postgres": ("the pg_stat_statements extension: `shared_preload_libraries = 'pg_stat_statements'` on the server "
                 "(a restart), then CREATE EXTENSION pg_stat_statements — the platform creates it itself once the "
                 "library is preloaded"),
    "bigquery": ("the connection's service account granted `bigquery.jobs.list` on the project (BigQuery User or "
                 "BigQuery Resource Viewer; a dataset-level grant cannot carry it) — the principal is the key file's "
                 "client_email"),
    "snowflake": "the connection's role allowed to read INFORMATION_SCHEMA.QUERY_HISTORY (MONITOR on the warehouse, "
                 "or ACCOUNT_USAGE access)",
    "clickhouse": "`system.query_log` kept by the server (on by default) and readable by the connection's user",
    "databricks": "the workspace's system tables enabled by an account admin (`system.query.history`)",
}


@dataclass
class Readiness:
    """Whether a connection's history can be read now — and when not, exactly what makes it readable."""
    engine: str = ""
    ok: bool = False
    source: str = ""        # the view read when ok
    note: str = ""          # what was found: a count, or why nothing could be read
    fix: str = ""           # the admin's step, in the engine's own terms; "" when ok or when the engine keeps none
    can_enable: bool = False   # the platform can provision it itself, now (`POST …/prerequisites/enable`)
    applies: bool = True    # False for an engine that keeps no history the platform reads

    def sentence(self) -> str:
        """One line for a Test button or a birth step."""
        if not self.applies:
            return f"Query history: {self.note}"
        if self.ok:
            return f"Query history: ready — {self.note}"
        head = "Query history: not readable yet"
        tail = (" — the platform can enable it" if self.can_enable else f" — needs {self.fix}") if self.fix else ""
        return f"{head}: {self.note}{tail}"

    def as_dict(self) -> dict:
        return {"engine": self.engine, "ok": self.ok, "source": self.source, "note": self.note, "fix": self.fix,
                "can_enable": self.can_enable, "applies": self.applies, "sentence": self.sentence()}


def _fix_from_error(engine: str, error: str) -> str:
    low = (error or "").lower()
    if engine == "bigquery" and ("jobs.list" in low or "access denied" in low):
        return PREREQUISITES["bigquery"]
    if engine == "snowflake" and ("insufficient privileges" in low or "not authorized" in low):
        return PREREQUISITES["snowflake"]
    return PREREQUISITES.get(engine, "")


def check_query_history(conn: Any) -> Readiness:
    """Probe a connection's history once (one row) and say what stands between the platform and it.

    Three answers: ready (with how much is there); not readable yet, with the admin's step in the engine's words and
    whether the platform can take it itself; or not applicable — this engine keeps none, which is a fact, not a gap.
    Never raises: a failed probe is a not-ready verdict carrying the engine's words."""
    engine = str(getattr(conn, "dialect", "") or type(conn).__name__)
    try:
        h = read_query_history(conn, limit=1)
    except Exception as exc:  # noqa: BLE001 — the verdict carries the failure
        return Readiness(engine=engine, ok=False, note=f"the probe failed: {exc}", fix=PREREQUISITES.get(engine, ""))
    if not h.supported:
        if engine not in PREREQUISITES:
            return Readiness(engine=engine, ok=False, applies=False, note=h.note)
        can_enable = False
        note = h.note
        probe = getattr(conn, "query_history_prerequisite", None)
        if probe is not None:
            try:
                state = probe()
            except Exception as exc:  # noqa: BLE001 — the probe's failure is part of the verdict
                state = {"error": str(exc)}
            if state.get("error"):
                note = f"{h.note} (the prerequisite probe failed: {state['error']})"
            elif not state.get("available", True):
                note = "pg_stat_statements is not available on this server (the contrib package is not installed)"
            elif not state.get("preloaded"):
                note = ("pg_stat_statements is available but not preloaded: `shared_preload_libraries` must name it and "
                        "the server restart, before CREATE EXTENSION can run")
            elif not state.get("created"):
                note = "pg_stat_statements is preloaded and not yet created on this database"
                can_enable = True
        return Readiness(engine=engine, ok=False, note=note, fix=PREREQUISITES[engine], can_enable=can_enable)
    if h.error:
        return Readiness(engine=engine, ok=False, source=h.source, note=f"the engine refused: {h.error.strip().splitlines()[0][:300]}",
                         fix=_fix_from_error(engine, h.error))
    what = (f"{h.rows[0].calls:,}+ runs on record in {h.source}" if h.rows and h.rows[0].calls > 1
            else f"statements on record in {h.source}") if h.rows else f"readable; nothing on record yet in {h.source}"
    return Readiness(engine=engine, ok=True, source=h.source, note=what)


def not_platform_statement(sql: str) -> bool:
    """Whether a statement is somebody's question rather than a catalog read: the platform's own metadata and history
    reads, and an engine's system views, teach the miner nothing about how the business is queried."""
    low = sql.lower()
    return not any(marker in low for marker in (
        "information_schema", "system.query_log", "system.columns", "system.tables", "query_history(",
        "system.query.history", "pg_catalog", "pg_stat", "pg_roles", "pg_database", "pg_namespace", "pg_class",
        "show tables", "describe ", "summarize ",
    ))
