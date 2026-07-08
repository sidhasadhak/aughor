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

Everything is bounded (key-chunk size, right-rows fetched, output rows) and fail-safe: on any error
the LEFT result is returned unchanged — the primitive never raises into the query path.

This is Stage 1 of the cross-source federated planner (Rec 2). The planner (which decomposes a
cross-source question into per-source sub-queries and picks the join keys) targets this engine; the
value-domain / key-reconciliation guards (Rec 3) run on the chosen key pair before the join.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aughor.platform.contracts.execution import QueryResult

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

_KEY_CHUNK      = 1000     # distinct keys per IN-list batch — one right query per chunk
_MAX_RIGHT_ROWS = 100_000  # cap total right rows fetched across all chunks
_MAX_OUT_ROWS   = 50_000   # cap merged output rows (a fan-out backstop)


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


def batched_foreach_join(
    left: QueryResult,
    left_key: str,
    right_conn: "DatabaseConnection",
    right_table: str,
    right_key: str,
    *,
    right_cols: list[str] | None = None,
    how: str = "inner",                      # "inner" | "left"
    key_chunk: int = _KEY_CHUNK,
    max_right_rows: int = _MAX_RIGHT_ROWS,
    max_out_rows: int = _MAX_OUT_ROWS,
) -> QueryResult:
    """Join an already-executed LEFT result to ``right_table`` on a DIFFERENT connection, N+1-free.

    Returns a merged :class:`QueryResult` (left columns + right columns, right names disambiguated).
    Fail-safe: if the left result errored / lacks the key / is empty, or any right query fails, the
    LEFT result is returned unchanged rather than raising."""
    li = _idx(left.columns, left_key)
    if left.error or li < 0 or not left.rows:
        return left

    # 1) collect + dedup the left keys (skip NULL/empty — they can't join)
    keys: list[str] = []
    seen: set[str] = set()
    for row in left.rows:
        raw = row[li]
        k = None if raw is None else str(raw)
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    if not keys:
        return left if how == "left" else _empty_like(left)

    # the right_key must come back in the projection so we can join on it
    cols = list(right_cols) if right_cols else None
    if cols is not None and right_key not in cols:
        cols = cols + [right_key]
    sel = ", ".join(_qident(c) for c in cols) if cols else "*"
    rt, rk = _qident(right_table), _qident(right_key)

    # 2) batched foreach — one right query per key-chunk (this is the N+1 avoidance)
    right_columns: list[str] = []
    right_by_key: dict[str, list[list]] = {}
    fetched = 0
    for chunk in _chunks(keys, key_chunk):
        in_list = ", ".join(_sql_literal(v) for v in chunk)
        sql = f"SELECT {sel} FROM {rt} WHERE {rk} IN ({in_list})"
        try:
            res = right_conn.execute("__remote_join__", sql)
        except Exception as exc:  # noqa: BLE001 — fail-safe: never raise into the query path
            logger.warning("remote_join: right query failed — returning left unchanged: %s", exc)
            return left
        if res.error:
            logger.warning("remote_join: right query error — returning left unchanged: %s", res.error)
            return left
        if not right_columns:
            right_columns = list(res.columns)
        rki = _idx(right_columns, right_key)
        if rki < 0:
            logger.warning("remote_join: right_key %r not in right projection — returning left", right_key)
            return left
        for r in res.rows:
            right_by_key.setdefault(str(r[rki]), []).append(list(r))
            fetched += 1
        if fetched >= max_right_rows:
            logger.warning("remote_join: right-row cap %d hit — join is partial", max_right_rows)
            break

    # 3) hash-join in memory
    out_cols = list(left.columns) + _uniquify(left.columns, right_columns)
    out_rows: list[list] = []
    for row in left.rows:
        raw = row[li]
        k = None if raw is None else str(raw)
        matches = right_by_key.get(k, []) if k else []
        if matches:
            for m in matches:
                out_rows.append(list(row) + list(m))
                if len(out_rows) >= max_out_rows:
                    break
        elif how == "left":
            out_rows.append(list(row) + [None] * len(right_columns))
        if len(out_rows) >= max_out_rows:
            break

    from aughor.stats import bump
    bump("federation.remote_join.executed")
    return QueryResult(
        hypothesis_id="__remote_join__",
        sql=(f"-- batched foreach join: left.{left_key} = {right_table}.{right_key} ({how}); "
             f"{len(keys)} distinct keys, {fetched} right rows, {len(out_rows)} joined"),
        columns=out_cols,
        rows=out_rows,
        row_count=len(out_rows),
    )


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
) -> QueryResult:
    """Run ``left_sql`` on one connection and batched-foreach-join it to a table on another (by id).

    The by-connection-id entry point the planner and the API surface call. Fail-safe throughout."""
    from aughor.db.connection import open_connection_for
    left_conn = open_connection_for(left_conn_id)
    left = left_conn.execute("__remote_join_left__", left_sql)
    right_conn = open_connection_for(right_conn_id)
    return batched_foreach_join(
        left, left_key, right_conn, right_table, right_key,
        right_cols=right_cols, how=how,
    )
