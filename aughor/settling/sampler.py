"""Idea 4 · the daily reading: count each recent day, per table, and file it.

Once a day, for every profiled table that has a primary timestamp, the sampler counts the
rows of each of the last `HORIZON_DAYS` days and files the counts as observations taken
today. Tomorrow's reading of the same days is what the learner compares them with. No
model call: one `GROUP BY day` per table, on the timestamp column alone.

The count is the measure on purpose. A backfill or a late row changes the row count of
the day it belongs to whatever the metric, so the count is the settling signal every
metric on the table inherits — and it needs no definition to be right.

Dates are Python literals, never `CURRENT_DATE`: the reading is stamped with THIS clock,
and the same clock names the days it asks for, so a warehouse in another timezone cannot
make "yesterday" mean two different things in one observation.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from aughor.settling.store import record_observations

logger = logging.getLogger(__name__)

#: How many recent days each reading counts. Long enough to see a source that settles a
#: week out; short enough that the daily query stays a scan of one column over two weeks.
HORIZON_DAYS = 14
#: The largest tables carry the signal; a lookup table's count never moves.
MAX_TABLES_PER_CONNECTION = 8

RunSql = Callable[[str], tuple[list, list, Optional[str]]]


def _ident(name: str) -> str:
    """One identifier, double-quoted in DuckDB's dialect — `native_sql` translates the
    quoting for engines that write their own (BigQuery's backticks). Found by the first
    live tick: an unquoted "Order Date" is two tokens, and the reading failed on every
    upload whose columns carry spaces."""
    return '"' + name.replace('"', '""') + '"'


def _table_ref(table: str) -> str:
    """A table reference with each dotted part quoted on its own, so `schema.table` stays
    two identifiers rather than one name with a dot in it."""
    return ".".join(_ident(p) for p in table.split(".") if p)


def count_by_day_sql(table: str, date_column: str, start: date, stop: date) -> str:
    """Rows per day in [start, stop) — the shape CB-2's `measurement_sql` reads, one day at
    a time; here grouped so one query reads the whole horizon."""
    col, tbl = _ident(date_column), _table_ref(table)
    return (f"SELECT CAST({col} AS DATE) AS day, COUNT(*) AS n FROM {tbl} "
            f"WHERE CAST({col} AS DATE) >= DATE '{start.isoformat()}' "
            f"AND CAST({col} AS DATE) < DATE '{stop.isoformat()}' "
            f"GROUP BY 1 ORDER BY 1")


def time_tables(connection_id: str) -> list[tuple[str, str, int]]:
    """(table, primary timestamp, row count) for every profiled table that has a
    timestamp, largest first, capped. From the profiler's most recent cache entry."""
    try:
        from aughor.tools.profile_cache import latest_profile_entry
        latest = latest_profile_entry(connection_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "no profile cache means no time tables to read", counter="settling.profile_cache")
        return []
    out: list[tuple[str, str, int]] = []
    for name, tp in ((latest or {}).get("tables") or {}).items():
        if not isinstance(tp, dict):
            continue
        col = str(tp.get("primary_timestamp") or "").strip()
        if not col:
            continue
        try:
            rows = int(tp.get("row_count") or 0)
        except (TypeError, ValueError):
            rows = 0
        out.append((str(name), col, rows))
    out.sort(key=lambda t: (-t[2], t[0]))
    return out[:MAX_TABLES_PER_CONNECTION]


def _as_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def sample_connection(connection_id: str, run_sql: RunSql, *, today: Optional[date] = None,
                      horizon_days: int = HORIZON_DAYS) -> dict:
    """Read every time table once and file today's counts. Returns what happened per table;
    a table whose query fails is reported and skipped, never guessed."""
    today = today or datetime.now(timezone.utc).date()
    stop = today
    sampled: list[str] = []
    errors: dict[str, str] = {}
    # A table still moving at the oldest age read cannot name its lag until the horizon
    # grows — so read it twice as far back (theLook's order_items was still moving at 14 on
    # 2026-09-25). One wider scan of one column a day; the others keep the short horizon.
    try:
        from aughor.settling.store import verdicts
        moving = {t for t, v in verdicts(connection_id).items() if v.still_moving}
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "unreadable verdicts: every table is read at the short horizon",
                 counter="settling.horizon_verdicts")
        moving = set()
    for table, col, _rows in time_tables(connection_id):
        span = horizon_days * 2 if table in moving else horizon_days
        start = today - timedelta(days=span)
        try:
            columns, rows, error = run_sql(count_by_day_sql(table, col, start, stop))
        except Exception as exc:
            error, rows = str(exc), []
        if error:
            errors[table] = str(error)[:200]
            continue
        counts: dict[str, float] = {}
        for r in rows or []:
            vals = list(r.values()) if isinstance(r, dict) else list(r)
            if len(vals) < 2:
                continue
            day = _as_date(vals[0])
            if day is None or not (start <= day < stop):
                continue
            try:
                counts[day.isoformat()] = float(vals[1] or 0)
            except (TypeError, ValueError) as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "a count that is not a number is not a reading; the day is left out",
                         counter="settling.unreadable_count")
                continue
        # A day with no rows is a reading too — zero is a value, and a day that later
        # gains rows is exactly a day that was still settling.
        for i in range(span):
            counts.setdefault((start + timedelta(days=i)).isoformat(), 0.0)
        record_observations(connection_id, table, col, today, counts)
        sampled.append(table)
    return {"connection_id": connection_id, "sampled": sampled, "errors": errors,
            "measured_on": today.isoformat()}


_last_sample_day: str = ""


def run_settling_samples_daily(*, now: Optional[datetime] = None, force: bool = False) -> int:
    """Read every connection once per UTC day. Returns how many tables were sampled (0 when
    today's reading was already taken). ``force`` is for an external clock."""
    global _last_sample_day
    today = (now or datetime.now(timezone.utc)).date()
    if not force and _last_sample_day == today.isoformat():
        return 0
    _last_sample_day = today.isoformat()
    try:
        from aughor.db.registry import list_connections
        connections = list_connections()
    except Exception as exc:
        logger.warning("settling sampler could not list connections: %s", exc)
        return 0
    from aughor.db.measure import run_sql_for
    total = 0
    for conn in connections:
        cid = str((conn or {}).get("id") or "")
        if not cid or not time_tables(cid):
            continue
        try:
            result = sample_connection(cid, run_sql_for(cid), today=today)
        except Exception as exc:
            logger.warning("settling sample failed on %s: %s", cid, exc)
            continue
        total += len(result["sampled"])
        if result["errors"]:
            logger.info("settling sample on %s skipped %s", cid, result["errors"])
    return total
