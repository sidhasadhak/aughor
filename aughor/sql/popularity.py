"""R14 — query popularity: per-table and per-column usage mined from real history.

The Databricks ``TableMetadataPreviewPopularityData`` analog (wire study #2):
what people actually query is a notability signal the whole platform should
share. The pieces existed but were disconnected — ``query_log_miner`` computes
``column_usage`` per schema build and throws it away; ``tables_used`` is stored
per chat turn and never aggregated. This module mines the history ONCE into a
small persisted counter store and serves it to four consumers:

  • R11 column-config defaults — a queried column is protected from default
    hiding (popularity never hides; it only keeps visible);
  • R8 doc-tree — table facts carry ``query_popularity`` (Merkle-tracked) and
    the schema summary ranks by it before row_count;
  • overview seed priority — merged into the existing learned-prior fold
    (``overview/drills`` shape: the same saturating, capped boost);
  • starter-question relevance — a "most-queried tables" block for /suggestions.

Sources mined (each best-effort; whichever exists contributes):
  A. the SQL-examples vector store (successful executed SQL, via
     ``query_log_miner.collect_logged_sql``);
  B. ``task_history`` span inputs (flag ``obs.task_table``) — raw SQL captured
     in the ``input`` column by the telemetry sink.

Store mirrors ``overview/drills.py``: one tiny SQLite table keyed
(connection_id, kind, key), env-overridable path (``AUGHOR_POPULARITY_DB``) so
tests stay hermetic. All consumption is gated by the ``obs.popularity`` flag
(default-off, byte-identical when off); mining runs from the R12 birth job.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "popularity.db"

# Bound the mining pass — history stores are unbounded; the signal saturates fast.
_MAX_SQLS = 5000


def _db_path() -> str:
    return os.environ.get("AUGHOR_POPULARITY_DB") or str(_DEFAULT_DB)


@dataclass
class PopularitySignal:
    """One connection's mined usage counts."""
    connection_id: str
    table_counts: dict[str, int] = field(default_factory=dict)     # bare table -> n
    column_counts: dict[str, int] = field(default_factory=dict)    # "table.column" -> n
    n_queries: int = 0
    mined_at: float = 0.0


# ── store (the overview_drills pattern: tiny, keyed, replace-on-refresh) ─────

def _connect() -> sqlite3.Connection:
    from aughor.db.sqlite_util import tune
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = tune(sqlite3.connect(path, timeout=5))
    con.execute(
        "CREATE TABLE IF NOT EXISTS popularity ("
        " connection_id TEXT NOT NULL,"
        " kind TEXT NOT NULL,"            # 'table' | 'column'
        " key TEXT NOT NULL,"
        " count INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (connection_id, kind, key))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS popularity_meta ("
        " connection_id TEXT PRIMARY KEY,"
        " mined_at REAL NOT NULL,"
        " n_queries INTEGER NOT NULL)"
    )
    return con


def save_popularity(sig: PopularitySignal) -> None:
    """Replace the connection's counts with a fresh mining pass. Best-effort."""
    try:
        con = _connect()
        with con:
            con.execute("DELETE FROM popularity WHERE connection_id = ?", (sig.connection_id,))
            con.executemany(
                "INSERT INTO popularity (connection_id, kind, key, count) VALUES (?,?,?,?)",
                [(sig.connection_id, "table", k, v) for k, v in sig.table_counts.items()]
                + [(sig.connection_id, "column", k, v) for k, v in sig.column_counts.items()],
            )
            con.execute(
                "INSERT OR REPLACE INTO popularity_meta (connection_id, mined_at, n_queries) "
                "VALUES (?,?,?)",
                (sig.connection_id, sig.mined_at or time.time(), sig.n_queries),
            )
        con.close()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "popularity save is best-effort",
                 counter="obs.popularity", conn_id=sig.connection_id or None)


def load_popularity(connection_id: str) -> dict[str, dict[str, int]]:
    """Read-only counts: ``{"table": {t: n}, "column": {"t.c": n}}``; {} buckets on any error."""
    out: dict[str, dict[str, int]] = {"table": {}, "column": {}}
    try:
        if not Path(_db_path()).exists():
            return out
        con = _connect()
        rows = con.execute(
            "SELECT kind, key, count FROM popularity WHERE connection_id = ?",
            (connection_id,),
        ).fetchall()
        con.close()
        for kind, key, count in rows:
            if kind in out:
                out[kind][key] = int(count)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "popularity load is best-effort",
                 counter="obs.popularity", conn_id=connection_id or None)
    return out


# ── mining ───────────────────────────────────────────────────────────────────

def _sqls_from_task_history(connection_id: str, limit: int) -> list[str]:
    """Raw SQL captured in task_history span inputs (flag ``obs.task_table``).
    The sink lifts a span's ``sql``/``query`` attribute into the ``input`` column;
    a non-SQL input (a question, a JSON blob) is filtered by a cheap looks-like-SQL
    test — the miner's parser is the real gate anyway."""
    try:
        from aughor.kernel.ledger import Ledger
        rows = Ledger.default().task_history(limit=limit)
    except Exception:
        return []
    out: list[str] = []
    for r in rows:
        raw = (r.get("input") or "").strip()
        if not raw.startswith(("{", "[")) and raw[:30].upper().lstrip().startswith(
                ("SELECT", "WITH")):
            labels = r.get("labels")
            if connection_id and isinstance(labels, str):
                try:
                    lbl_conn = json.loads(labels).get("connection_id") or connection_id
                except Exception:
                    lbl_conn = connection_id   # unparseable labels → keep the row
                if lbl_conn != connection_id:
                    continue
            out.append(raw)
    return out


def mine_popularity(connection_id: str, *, dialect: str = "duckdb",
                    sqls: list[str] | None = None) -> PopularitySignal:
    """Mine the history sources into a PopularitySignal (pure given ``sqls``).

    Table counts come from ``sql/tables.extract_tables`` (scope-aware, CTEs
    excluded); column counts from the miner's ``column_usage`` — the counter that
    was previously computed and discarded every schema build."""
    if sqls is None:
        sqls = []
        try:
            from aughor.sql.query_log_miner import collect_logged_sql
            sqls.extend(collect_logged_sql(connection_id, limit=_MAX_SQLS))
        except Exception:
            logger.debug("popularity: vector-store SQL source unavailable", exc_info=True)
        if len(sqls) < _MAX_SQLS:
            sqls.extend(_sqls_from_task_history(connection_id, _MAX_SQLS - len(sqls)))
    sqls = sqls[:_MAX_SQLS]

    sig = PopularitySignal(connection_id=connection_id, mined_at=time.time())
    if not sqls:
        return sig

    from aughor.sql.query_log_miner import mine_query_log
    facts = mine_query_log(sqls, dialect=dialect)
    sig.n_queries = facts.n_parsed
    sig.column_counts = {k: int(v) for k, v in facts.column_usage.items()}

    from aughor.sql.tables import extract_tables
    table_counts: dict[str, int] = {}
    for sql in sqls:
        try:
            refs = extract_tables(sql, dialect)
        except Exception:
            refs = set()   # un-enumerable SQL contributes nothing
        for ref in refs:
            bare = getattr(ref, "table", "") or ""
            if bare:
                table_counts[bare] = table_counts.get(bare, 0) + 1
    sig.table_counts = table_counts
    return sig


def refresh_popularity(connection_id: str, *, dialect: str = "duckdb") -> PopularitySignal:
    """Mine + persist in one call — the R12 birth-job step body."""
    sig = mine_popularity(connection_id, dialect=dialect)
    save_popularity(sig)
    return sig


# ── consumer helpers ─────────────────────────────────────────────────────────

def merge_popularity_into_priors(priors: dict, connection_id: str) -> dict:
    """Fold query popularity into the overview's learned-prior dict (the
    ``{"lens": {...}, "table": {...}}`` shape from ``overview/drills``). Additive:
    drill counts and query counts sum per table; ``_prior_boost``'s saturation +
    cap keep the nudge bounded no matter how hot a table is. Returns a NEW dict;
    the input is never mutated. No-op (input returned) when nothing was mined."""
    pop = load_popularity(connection_id)
    if not pop.get("table"):
        return priors
    merged = dict((priors or {}).get("table") or {})
    for t, n in pop["table"].items():
        merged[t] = merged.get(t, 0) + n
    out = dict(priors or {})
    out["table"] = merged
    return out


def most_queried_block(connection_id: str, *, top: int = 6) -> str:
    """A compact 'what people actually query' block for the /suggestions prompt.
    Empty string when nothing was mined (caller appends nothing)."""
    pop = load_popularity(connection_id)
    tables = sorted(pop.get("table", {}).items(), key=lambda kv: -kv[1])[:top]
    if not tables:
        return ""
    lines = ["MOST-QUERIED TABLES (from real query history — favor these in suggestions):"]
    lines += [f"  {t}  ({n} queries)" for t, n in tables]
    return "\n".join(lines)
