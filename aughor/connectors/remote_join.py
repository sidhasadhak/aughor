"""Batched foreach remote joins across heterogeneous connections (Hasura NDC pattern).

The :class:`~aughor.connectors.federated.FederatedConnection` materializes whole member tables
into one DuckDB namespace. That's great when data co-locates, but it copies everything and can't
reach a *live* Snowflake/BigQuery without pulling the full table. The batched-foreach join is the
complement and the correct-by-construction path for true cross-engine joins:

  1. execute the LEFT sub-query on its own connection (already done by the caller),
  2. collect the join-key values and **dedup** them,
  3. issue ONE keyed batch query per key-chunk to the RIGHT connection — ``WHERE right_key IN (...)`` —
     never one query per left row, so **N+1 is avoided structurally** (Hasura's variables/RowSet
     mechanism expressed in SQL), and
  4. hash-join the two result sets in memory.

**Self-healing keys (Stage 2b).** Cross-source keys are often the *same* entity in a different
format (``bid_123`` here, ``bref_123`` there — DataAgentBench's #3 axis, now *across sources*). When
the raw join's match rate is low and ``reconcile=True``, the join retries under a small set of
deterministic normalizations, each expressed as a **paired Python function** (applied to the
materialized left keys) and **SQL expression** (applied to the right key in the batch query), so the
two sides normalize identically. If a transform lifts the match rate over a bar the join adopts it;
otherwise the raw result stands. This is the cross-source twin of the in-source key-reconciliation
guard (Rec 3), gated by the same ``join.key_reconciliation`` flag at the call site.

Everything is bounded (key-chunk size, right-rows fetched, output rows, transforms tried) and
fail-safe: on any error the LEFT result is returned unchanged — the primitive never raises.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Callable

from aughor.platform.contracts.execution import QueryResult

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

_KEY_CHUNK      = 1000     # distinct keys per IN-list batch — one right query per chunk
_MAX_RIGHT_ROWS = 100_000  # cap total right rows fetched across all chunks
_MAX_OUT_ROWS   = 50_000   # cap merged output rows (a fan-out backstop)

# Paired normalizations for self-healing cross-source keys: (name, python fn over the left key,
# SQL expr over the right key {col}). The Python fn and SQL expr MUST compute the same string so the
# two sides align. Ordered cheapest/most-common first; the search stops at the first that reconciles.
_RECON_TRANSFORMS: list[tuple[str, Callable[[str], str], str]] = [
    ("digits",       lambda s: re.sub(r"[^0-9]", "", s),
                     "regexp_replace(CAST({col} AS VARCHAR), '[^0-9]', '', 'g')"),
    ("strip_prefix", lambda s: re.sub(r"^[A-Za-z_]+", "", s),
                     "regexp_replace(CAST({col} AS VARCHAR), '^[A-Za-z_]+', '')"),
    ("trim_lower",   lambda s: s.strip().lower(),
                     "lower(trim(CAST({col} AS VARCHAR)))"),
    ("strip_zeros",  lambda s: re.sub(r"^0+", "", s.strip()),
                     "regexp_replace(trim(CAST({col} AS VARCHAR)), '^0+', '')"),
    ("alnum_lower",  lambda s: re.sub(r"[^A-Za-z0-9]", "", s).lower(),
                     "lower(regexp_replace(CAST({col} AS VARCHAR), '[^A-Za-z0-9]', '', 'g'))"),
]
_RECON_LOW       = 0.15   # attempt reconciliation only when the raw match rate is this low
_RECON_MIN_MATCH = 0.60   # a normalization must reach this match rate to be adopted
_RECON_MIN_GAIN  = 0.30   # ... and beat the raw rate by at least this much


def _sql_literal(v: object) -> str:
    """A single-quoted SQL string literal with embedded quotes escaped.

    Keys come from executed result cells, not user text, but they are still data — escape ``'`` so a
    value like ``O'Brien`` can't break (or inject into) the IN-list."""
    s = "" if v is None else str(v)
    return "'" + s.replace("'", "''") + "'"


def _qident(name: str) -> str:
    """Quote a table/column identifier, supporting schema-qualified ``schema.table``."""
    if '"' in name:
        return name
    return ".".join(f'"{p}"' for p in name.split("."))


def _idx(cols: list[str], name: str) -> int:
    return cols.index(name) if name in cols else -1


def _uniquify(existing: list[str], new: list[str]) -> list[str]:
    """Disambiguate ``new`` column names against ``existing`` and each other (id → id_2)."""
    seen = set(existing)
    out: list[str] = []
    for name in new:
        candidate, n = name, 2
        while candidate in seen:
            candidate, n = f"{name}_{n}", n + 1
        seen.add(candidate)
        out.append(candidate)
    return out


def _chunks(items: list, size: int):
    for start in range(0, len(items), max(1, size)):
        yield items[start:start + size]


def _distinct_keys(rows: list, li: int, keyfn: Callable[[str], str] | None = None) -> list[str]:
    """Distinct, order-preserving, non-empty (normalized) key strings from a result's key column."""
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw = row[li]
        if raw is None:
            continue
        k = keyfn(str(raw)) if keyfn else str(raw)
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _fetch_right(
    right_conn: "DatabaseConnection", right_table: str, right_cols: list[str] | None,
    jk_expr: str, in_values: list[str], key_chunk: int, max_rows: int,
) -> tuple[list[str], dict[str, list[list]], int, str | None]:
    """Fetch right rows whose join-key expression ``jk_expr`` is IN ``in_values`` (batched).

    Returns (right_columns, rows_by_join_key, fetched, error). The join key is projected as ``__jk``
    and keyed on — so raw (``jk_expr`` = the column) and normalized (``jk_expr`` = a transform) share
    one path. ``__jk`` is stripped from the returned columns/rows."""
    sel = ", ".join(_qident(c) for c in right_cols) if right_cols else "*"
    rt = _qident(right_table)
    right_columns: list[str] = []
    by_key: dict[str, list[list]] = {}
    fetched = 0
    for chunk in _chunks(in_values, key_chunk):
        in_list = ", ".join(_sql_literal(v) for v in chunk)
        sql = f"SELECT {sel}, {jk_expr} AS __jk FROM {rt} WHERE {jk_expr} IN ({in_list})"
        try:
            res = right_conn.execute("__remote_join__", sql)
        except Exception as exc:  # noqa: BLE001 — fail-safe: never raise into the query path
            return [], {}, 0, str(exc)
        if res.error:
            return [], {}, 0, res.error
        cols = list(res.columns)
        jki = _idx(cols, "__jk")
        if jki < 0:
            return [], {}, 0, "join-key expression missing from projection"
        if not right_columns:
            right_columns = [c for i, c in enumerate(cols) if i != jki]
        for r in res.rows:
            by_key.setdefault(str(r[jki]), []).append([v for i, v in enumerate(r) if i != jki])
            fetched += 1
        if fetched >= max_rows:
            logger.warning("remote_join: right-row cap %d hit — join is partial", max_rows)
            break
    return right_columns, by_key, fetched, None


def _match_rate(keys: list[str], by_key: dict[str, list[list]]) -> float:
    return (sum(1 for k in keys if k in by_key) / len(keys)) if keys else 0.0


def _hash_join(
    left: QueryResult, li: int, keyfn: Callable[[str], str],
    right_columns: list[str], by_key: dict[str, list[list]], how: str, max_out: int,
) -> tuple[list[str], list[list]]:
    out_cols = list(left.columns) + _uniquify(left.columns, right_columns)
    out_rows: list[list] = []
    for row in left.rows:
        raw = row[li]
        k = keyfn(str(raw)) if raw is not None else None
        matches = by_key.get(k, []) if k else []
        if matches:
            for m in matches:
                out_rows.append(list(row) + list(m))
                if len(out_rows) >= max_out:
                    break
        elif how == "left":
            out_rows.append(list(row) + [None] * len(right_columns))
        if len(out_rows) >= max_out:
            break
    return out_cols, out_rows


def batched_foreach_join(
    left: QueryResult,
    left_key: str,
    right_conn: "DatabaseConnection",
    right_table: str,
    right_key: str,
    *,
    right_cols: list[str] | None = None,
    how: str = "inner",                      # "inner" | "left"
    reconcile: bool = False,
    key_chunk: int = _KEY_CHUNK,
    max_right_rows: int = _MAX_RIGHT_ROWS,
    max_out_rows: int = _MAX_OUT_ROWS,
) -> QueryResult:
    """Join an already-executed LEFT result to ``right_table`` on a DIFFERENT connection, N+1-free.

    Returns a merged :class:`QueryResult` (left columns + right columns, right names disambiguated).
    With ``reconcile=True``, a low raw match rate triggers a self-healing retry under key
    normalizations (see the module note). Fail-safe: on a bad/empty left key or any right-query
    error, the LEFT result is returned unchanged rather than raising."""
    li = _idx(left.columns, left_key)
    if left.error or li < 0 or not left.rows:
        return left

    keys = _distinct_keys(left.rows, li)
    if not keys:
        return left if how == "left" else _empty_like(left)

    rk = _qident(right_key)
    right_columns, by_key, fetched, err = _fetch_right(
        right_conn, right_table, right_cols, rk, keys, key_chunk, max_right_rows)
    if err:
        logger.warning("remote_join: right query failed — returning left unchanged: %s", err)
        return left

    raw_rate = _match_rate(keys, by_key)
    keyfn: Callable[[str], str] = lambda s: s
    chosen_note = f"{len(keys)} keys, raw match {raw_rate:.0%}"

    if reconcile and raw_rate < _RECON_LOW:
        healed = _try_reconcile(right_conn, right_table, right_cols, right_key,
                                keys, raw_rate, key_chunk, max_right_rows)
        if healed:
            name, pyfn, right_columns, by_key = healed
            keyfn = pyfn
            chosen_note += f" → reconciled on '{name}' ({_match_rate(_distinct_keys(left.rows, li, pyfn), by_key):.0%})"
            from aughor.stats import bump
            bump("federation.remote_join.reconciled")

    out_cols, out_rows = _hash_join(left, li, keyfn, right_columns, by_key, how, max_out_rows)

    from aughor.stats import bump
    bump("federation.remote_join.executed")
    return QueryResult(
        hypothesis_id="__remote_join__",
        sql=(f"-- batched foreach join: left.{left_key} = {right_table}.{right_key} ({how}); "
             f"{chosen_note}, {fetched} right rows, {len(out_rows)} joined"),
        columns=out_cols, rows=out_rows, row_count=len(out_rows),
    )


def _try_reconcile(
    right_conn: "DatabaseConnection", right_table: str, right_cols: list[str] | None,
    right_key: str, left_keys: list[str], raw_rate: float, key_chunk: int, max_rows: int,
) -> tuple[str, Callable[[str], str], list[str], dict[str, list[list]]] | None:
    """Try each paired normalization; return the first that materially lifts the match rate."""
    rk = _qident(right_key)
    for name, pyfn, tmpl in _RECON_TRANSFORMS:
        norm_keys: list[str] = []
        seen: set[str] = set()
        for k in left_keys:
            nk = pyfn(k)
            if nk and nk not in seen:
                seen.add(nk)
                norm_keys.append(nk)
        if not norm_keys:
            continue
        right_columns, by_key, _fetched, err = _fetch_right(
            right_conn, right_table, right_cols, tmpl.format(col=rk), norm_keys, key_chunk, max_rows)
        if err:
            continue
        rate = _match_rate(norm_keys, by_key)
        if rate >= _RECON_MIN_MATCH and rate - raw_rate >= _RECON_MIN_GAIN:
            return name, pyfn, right_columns, by_key
    return None


def _empty_like(left: QueryResult) -> QueryResult:
    """An empty result carrying the left columns — an inner join with no keys yields no rows."""
    return QueryResult(
        hypothesis_id="__remote_join__", sql="-- remote join: no join keys",
        columns=list(left.columns), rows=[], row_count=0,
    )


def cross_source_join(
    left_conn_id: str,
    left_sql: str,
    left_key: str,
    right_conn_id: str,
    right_table: str,
    right_key: str,
    *,
    how: str = "inner",
    right_cols: list[str] | None = None,
    reconcile: bool = False,
) -> QueryResult:
    """Run ``left_sql`` on one connection and batched-foreach-join it to a table on another (by id).

    The by-connection-id entry point the planner and API surface call. Fail-safe throughout."""
    from aughor.db.connection import open_connection_for
    left_conn = open_connection_for(left_conn_id)
    left = left_conn.execute("__remote_join_left__", left_sql)
    right_conn = open_connection_for(right_conn_id)
    return batched_foreach_join(
        left, left_key, right_conn, right_table, right_key,
        right_cols=right_cols, how=how, reconcile=reconcile,
    )
