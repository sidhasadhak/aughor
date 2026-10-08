"""Pipeline health and new values — what a dataset's own rows say each day, SQL only (exploration principles §3, §5).

Two readings the principles name and the first build left out:

* **Pipeline health** for a dataset a person set to the RAW layer (§5: "pipeline health only: arrival, row
  counts, schema drift, empty-value spikes"). Each day, per table: the rows it holds against the last
  reading, the newest date it has (arrival), and the share of empty values in each column against the
  last reading. What changed is said as a note — no rows arrived, rows fell, a column's empty share
  jumped — and kept on the dataset's program for the Catalog to show. Schema drift is the structure job's
  fingerprint, already compared every hour.
* **A new value in a known dimension** for a BUSINESS dataset (§3's fourth reopen event). Each day, the
  distinct values of a few low-cardinality dimension columns the profiler knows are read and compared with
  the values seen before; a value never seen reopens the dataset's questions. The first reading is the
  baseline, never news.

Bounded on purpose — a warehouse bills by what it scans: at most ``MAX_TABLES`` tables and ``MAX_COLUMNS``
columns a table for health, empty shares read only over the newest week where a table has a date (whole
tables only under ``FULL_SCAN_ROWS`` rows), and ``MAX_DIMENSIONS`` dimensions a day for new values.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from aughor.explorer import program as P

MAX_TABLES = 20
MAX_COLUMNS = 30
MAX_DIMENSIONS = 6
MAX_VALUES = 60
#: A table under this many rows has its empty shares read whole when it has no date to bound them by.
FULL_SCAN_ROWS = 1_000_000
#: An empty share that rose at least this much since the last reading is a spike.
EMPTY_SPIKE = 0.10
#: A table whose rows fell by more than this share since the last reading is said.
ROWS_FELL = 0.05
#: One reading a day.
EVERY_SECONDS = 86_400.0

RunSql = Callable[[str], tuple]


def due(reading: Optional[dict], now: Optional[datetime] = None) -> bool:
    if not reading or not reading.get("read_at"):
        return True
    try:
        at = datetime.fromisoformat(str(reading["read_at"]))
    except ValueError:
        return True
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - at).total_seconds() >= EVERY_SECONDS


def _first_row(run_sql: RunSql, sql: str) -> Optional[list]:
    cols, rows, error = run_sql(sql)
    if error or not rows:
        return None
    r = rows[0]
    return list(r.values()) if isinstance(r, dict) else list(r)


def _num(v) -> Optional[float]:
    try:
        return float(v) if v is not None and str(v).strip().upper() not in ("", "NULL") else None
    except (TypeError, ValueError):
        return None


def table_health(table: str, columns: list[str], *, run_sql: RunSql, q: Callable[[str], str], ref: str,
                 date_col: str = "", rows_hint: Optional[int] = None) -> dict:
    """One table's reading: ``{"rows", "newest", "empty": {column: share}, "scope"}``. Each part is None
    when its query could not answer — said by the caller, never read as zero."""
    out: dict[str, Any] = {"rows": None, "newest": None, "empty": {}, "scope": ""}
    got = _first_row(run_sql, f"SELECT COUNT(*) FROM {ref}")
    out["rows"] = int(_num(got[0]) or 0) if got else None
    where = ""
    if date_col:
        got = _first_row(run_sql, f"SELECT MAX({q(date_col)}) FROM {ref}")
        newest = str(got[0])[:10] if got and got[0] is not None else None
        out["newest"] = newest
        if newest:
            try:
                since = date.fromisoformat(newest) - timedelta(days=7)
                where = f" WHERE {q(date_col)} >= '{since.isoformat()}'"
                out["scope"] = f"the week to {newest}"
            except ValueError:
                where = ""
    rows = out["rows"] if out["rows"] is not None else rows_hint
    if not where and (rows is None or rows > FULL_SCAN_ROWS):
        out["scope"] = "not read — the table is large and has no date to bound it"
        return out
    out["scope"] = out["scope"] or "the whole table"
    cols = [c for c in columns if c][:MAX_COLUMNS]
    if not cols:
        return out
    select = ", ".join(["COUNT(*)"] + [f"COUNT({q(c)})" for c in cols])
    got = _first_row(run_sql, f"SELECT {select} FROM {ref}{where}")
    if got and _num(got[0]):
        n = _num(got[0]) or 0.0
        for c, filled in zip(cols, got[1:]):
            f = _num(filled)
            if f is not None and n:
                out["empty"][c] = round(1 - f / n, 4)
    return out


def health_notes(now: dict, before: dict) -> list[str]:
    """What changed since the last reading, as sentences — the health findings."""
    notes: list[str] = []
    for t, cur in sorted((now or {}).items()):
        prev = (before or {}).get(t) or {}
        r, pr = cur.get("rows"), prev.get("rows")
        if r is not None and pr is not None:
            if r == pr and cur.get("newest") == prev.get("newest"):
                notes.append(f"{t}: no new rows since the last reading ({r:,})")
            elif pr and r < pr * (1 - ROWS_FELL):
                notes.append(f"{t}: rows fell from {pr:,} to {r:,}")
        for c, share in (cur.get("empty") or {}).items():
            before_share = (prev.get("empty") or {}).get(c)
            if before_share is not None and share - before_share >= EMPTY_SPIKE:
                notes.append(f"{t}.{c}: empty in {share:.0%} of rows, was {before_share:.0%}")
    return notes


def dimensions_of(profile_entry: dict, tables: list[str]) -> list[tuple[str, str]]:
    """``[(table, column)]`` — the low-cardinality, non-key, non-date columns the profiler knows on these
    tables, the ones a new value in means something."""
    want = {t.split(".")[-1].lower(): t for t in tables}
    out = []
    for prof in ((profile_entry or {}).get("columns") or {}).values():
        if not isinstance(prof, dict):
            continue
        t = str(prof.get("table") or "").split(".")[-1].lower()
        if t not in want or prof.get("is_fk") or not prof.get("is_low_cardinality"):
            continue
        dtype = str(prof.get("dtype") or "").lower()
        if "date" in dtype or "time" in dtype:
            continue
        out.append((want[t], str(prof.get("column") or "")))
    return sorted(out)[:MAX_DIMENSIONS]


def new_values(dims: list[tuple[str, str]], known: dict, *, run_sql: RunSql, q: Callable[[str], str],
               ref_of: Callable[[str], str]) -> tuple[dict, list[str]]:
    """Read each dimension's distinct values; ``(values, news)`` — every dimension's values now, and a
    sentence for each value never seen before. A dimension read for the first time is a baseline."""
    values = dict(known or {})
    news: list[str] = []
    for table, col in dims:
        cols, rows, error = run_sql(f"SELECT DISTINCT {q(col)} FROM {ref_of(table)} LIMIT {MAX_VALUES + 1}")
        if error:
            continue
        seen = {str((list(r.values()) if isinstance(r, dict) else list(r))[0]) for r in rows or []
                if (list(r.values()) if isinstance(r, dict) else list(r))[0] is not None}
        if len(seen) > MAX_VALUES:
            continue                       # not a category any more — nothing to compare
        key = f"{table.split('.')[-1]}.{col}"
        before = values.get(key)
        if before is not None:
            fresh = sorted(seen - set(before))
            if fresh:
                news.append(f"a new value in {key}: {', '.join(repr(v) for v in fresh[:3])}")
        values[key] = sorted(set(before or []) | seen)
    return values, news


def read_dataset(conn_id: str, schema: Optional[str], *, layer: str, reopen_questions: bool,
                 now: Optional[datetime] = None, db: Any = None) -> dict:
    """Read one dataset's health (raw layer) or its dimensions' values (business layer), once a day.
    Returns what it read; records it on the dataset's program; reopens on a new value."""
    from aughor.db.connection import open_connection_for, open_connection_for_with_schema
    from aughor.db.quoting import qualified_table, quote_ident
    from aughor.db.schema_render import parse_schema_tables
    from aughor.semantic.metric_time import primary_date
    from aughor.tools.profile_cache import merged_profile_entry

    key = P.key_for(conn_id, schema)
    prog = P.load(key)
    kind = "health" if layer == "raw" else "values"
    if not due((prog.get("health") or {}) if kind == "health" else (prog.get("values") or {}).get("_read"), now):
        return {}
    own = db is None
    db = db or (open_connection_for_with_schema(conn_id, schema) if schema else open_connection_for(conn_id))
    try:
        tables = parse_schema_tables(db.get_schema())        # the tables a person turned off are not here
        names = sorted(tables)[:MAX_TABLES]
        profile = merged_profile_entry(conn_id) or {}
        q = lambda c: quote_ident(db, c)  # noqa: E731
        sch = schema or getattr(db, "_schema_name", None)

        def ref_of(t: str) -> str:
            parts = t.split(".")
            return qualified_table(db, parts[-1], parts[-2] if len(parts) > 1 else sch)

        def run_sql(sql: str):
            r = db.execute("__health__", sql, internal=True)
            return r.columns, r.rows, r.error

        if kind == "health":
            reading = {}
            for t in names:
                bare = t.split(".")[-1]
                tp = (profile.get("tables") or {}).get(bare) or (profile.get("tables") or {}).get(t) or {}
                reading[bare] = table_health(bare, list(tables[t]), run_sql=run_sql, q=q, ref=ref_of(t),
                                             date_col=primary_date(profile, bare),
                                             rows_hint=tp.get("row_count") if isinstance(tp, dict) else None)
            notes = health_notes(reading, (prog.get("health") or {}).get("tables") or {})
            P.record_health(key, {"tables": reading, "notes": notes})
            return {"kind": "health", "notes": notes, "tables": len(reading)}
        known = {k: v for k, v in (prog.get("values") or {}).items() if k != "_read"}
        values, news = new_values(dimensions_of(profile, names), known, run_sql=run_sql, q=q, ref_of=ref_of)
        P.record_values(key, values, news)
        if news and reopen_questions:
            P.reopen(key, news[0])
        return {"kind": "values", "news": news, "dimensions": len(values)}
    finally:
        if own:
            db.close()
