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

**Cross-type keys.** Keys are compared as canonicalized strings, so an ``INT 101`` on one source
joins a ``DOUBLE 101.0`` on another (``_canon_key`` drops trailing fractional zeros).

**Self-healing keys (Stage 2b).** Cross-source keys are often the *same* entity in a different
format (``bid_123`` here, ``bref_123`` there). When the raw match rate is low and ``reconcile=True``,
the join retries under a small set of deterministic normalizations, each a **paired** Python function
(applied to the materialized left keys) and SQL expression (applied to the right key in the batch
query), so the two sides normalize identically. The first transform that lifts the match rate over a
bar is adopted; otherwise the raw result stands.

Bounds & failure: bounded by the key-chunk size, right-rows fetched, output rows, and transforms
tried. Per-source fetches also inherit the connection layer's own row cap; when the LEFT driver is
capped, the result note is flagged ``PARTIAL`` rather than silently truncated. Fail-safe: a bad/empty
left key returns the LEFT result unchanged; a **right-query error returns an error result** (an inner
join that couldn't read the right side is a failure, not a left-only success) — the primitive never
raises into the query path.
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
# NOTE: the connection layer caps each execute() at its own MAX_ROWS; that lower bound dominates
# these ceilings today, so a very large join is flagged PARTIAL (see _distinct-key truncation below).

# Paired normalizations for self-healing cross-source keys: (name, python fn over the left key,
# SQL expr over the right key {col}). The Python fn and SQL expr MUST compute the same string so the
# two sides align (verified). Ordered cheapest/most-common first; the search stops at the first hit.
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

_NUMERIC_DECIMAL = re.compile(r"^-?\d+\.\d+$")


def _canon_key(s: str) -> str:
    """Canonicalize a join-key string so cross-type numerics match: a decimal like '101.0' / '101.50'
    loses trailing fractional zeros ('101' / '101.5'); everything else is unchanged. Lets an INT on
    one source join a DOUBLE on another (they stringify as '101' vs '101.0')."""
    if _NUMERIC_DECIMAL.match(s):
        return s.rstrip("0").rstrip(".")
    return s


def _sql_literal(v: object) -> str:
    """A single-quoted SQL string literal with embedded quotes escaped (values are data, not text)."""
    s = "" if v is None else str(v)
    return "'" + s.replace("'", "''") + "'"


def _qident(name: str) -> str:
    """Quote a table/column identifier, escaping embedded quotes, and supporting ``schema.table``."""
    return ".".join('"' + p.replace('"', '""') + '"' for p in name.split("."))


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


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _distinct_keys(rows: list, li: int) -> list[str]:
    """Distinct, order-preserving, non-empty RAW key strings from a result's key column."""
    return _dedup([str(row[li]) for row in rows if row[li] is not None])


def _fetch_right(
    right_conn: "DatabaseConnection", from_clause: str, right_cols: list[str] | None,
    jk_expr: str, in_values: list[str], key_chunk: int, max_rows: int, *, canon: bool = True,
) -> tuple[list[str], dict[str, list[list]], int, str | None]:
    """Fetch right rows whose join-key expression ``jk_expr`` is IN ``in_values`` (batched).

    ``from_clause`` is a quoted table or a derived sub-query (``(SELECT ...) AS __rt``). The join key
    is projected as ``__jk`` and keyed on (canonicalized when ``canon``) — so raw and normalized
    fetches share one path; ``__jk`` is stripped from the returned columns/rows."""
    sel = ", ".join(_qident(c) for c in right_cols) if right_cols else "*"
    right_columns: list[str] = []
    by_key: dict[str, list[list]] = {}
    fetched = 0
    for chunk in _chunks(in_values, key_chunk):
        in_list = ", ".join(_sql_literal(v) for v in chunk)
        sql = f"SELECT {sel}, {jk_expr} AS __jk FROM {from_clause} WHERE {jk_expr} IN ({in_list})"
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
            k = _canon_key(str(r[jki])) if canon else str(r[jki])
            by_key.setdefault(k, []).append([v for i, v in enumerate(r) if i != jki])
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
    right_key: str,
    *,
    right_table: str | None = None,
    right_sql: str | None = None,
    right_cols: list[str] | None = None,
    how: str = "inner",                      # "inner" | "left"
    reconcile: bool = False,
    key_chunk: int = _KEY_CHUNK,
    max_right_rows: int = _MAX_RIGHT_ROWS,
    max_out_rows: int = _MAX_OUT_ROWS,
) -> QueryResult:
    """Join an already-executed LEFT result to a RIGHT source on a DIFFERENT connection, N+1-free.

    The right side is either ``right_table`` (a whole table) or ``right_sql`` (a grounded sub-query);
    exactly one is required. Returns a merged :class:`QueryResult` (left columns + right columns, right
    names disambiguated). Fail-safe: a bad/empty left key returns the LEFT result unchanged; a
    right-query error returns an error result (see the module note)."""
    li = _idx(left.columns, left_key)
    if left.error or li < 0 or not left.rows or not (right_table or right_sql):
        return left

    from_clause = f"({right_sql.rstrip().rstrip(';')}) AS __rt" if right_sql else _qident(right_table)

    raw_keys = _distinct_keys(left.rows, li)   # raw strings, so reconcile can normalize them
    if not raw_keys:
        return left if how == "left" else _empty_like(left)

    keys = _dedup([_canon_key(k) for k in raw_keys])   # canonicalized: for the IN-list + match rate
    rk = _qident(right_key)
    right_columns, by_key, fetched, err = _fetch_right(
        right_conn, from_clause, right_cols, rk, keys, key_chunk, max_right_rows, canon=True)
    if err:
        logger.warning("remote_join: right query failed: %s", err)
        return _join_failed(err)

    raw_rate = _match_rate(keys, by_key)
    keyfn: Callable[[str], str] = _canon_key
    chosen_note = f"{len(keys)} keys, raw match {raw_rate:.0%}"

    if reconcile and raw_rate < _RECON_LOW:
        healed = _try_reconcile(right_conn, from_clause, right_cols, right_key,
                                raw_keys, raw_rate, key_chunk, max_right_rows)
        if healed:
            name, pyfn, right_columns, by_key = healed
            keyfn = pyfn                                       # reconcile keys are not canonicalized
            rate = _match_rate(_dedup([pyfn(k) for k in raw_keys]), by_key)
            chosen_note += f" → reconciled on '{name}' ({rate:.0%})"
            from aughor.stats import bump
            bump("federation.remote_join.reconciled")

    out_cols, out_rows = _hash_join(left, li, keyfn, right_columns, by_key, how, max_out_rows)

    partial = ""
    if left.row_count > len(left.rows):     # the connection layer capped the driver — say so, don't hide it
        partial = f"; PARTIAL: left driver capped at {len(left.rows)} of {left.row_count} rows"

    from aughor.stats import bump
    bump("federation.remote_join.executed")
    right_label = right_table or "(subquery)"
    return QueryResult(
        hypothesis_id="__remote_join__",
        sql=(f"-- batched foreach join: left.{left_key} = {right_label}.{right_key} ({how}); "
             f"{chosen_note}, {fetched} right rows, {len(out_rows)} joined{partial}"),
        columns=out_cols, rows=out_rows, row_count=len(out_rows),
    )


def _try_reconcile(
    right_conn: "DatabaseConnection", from_clause: str, right_cols: list[str] | None,
    right_key: str, raw_keys: list[str], raw_rate: float, key_chunk: int, max_rows: int,
) -> tuple[str, Callable[[str], str], list[str], dict[str, list[list]]] | None:
    """Try each paired normalization; return the first that materially lifts the match rate."""
    rk = _qident(right_key)
    for name, pyfn, tmpl in _RECON_TRANSFORMS:
        norm_keys = _dedup([pyfn(k) for k in raw_keys])
        if not norm_keys:
            continue
        right_columns, by_key, _fetched, err = _fetch_right(
            right_conn, from_clause, right_cols, tmpl.format(col=rk), norm_keys,
            key_chunk, max_rows, canon=False)
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


def _join_failed(err: object) -> QueryResult:
    """A right-query failure is a JOIN failure — surface it, don't present left rows as a success."""
    return QueryResult(
        hypothesis_id="__remote_join__", sql="-- cross-source join failed", columns=[], rows=[],
        row_count=0, error=f"cross-source join failed: right query error: {str(err)[:140]}",
    )


def cross_source_join(
    left_conn_id: str,
    left_sql: str,
    left_key: str,
    right_conn_id: str,
    right_key: str,
    *,
    right_table: str | None = None,
    right_sql: str | None = None,
    how: str = "inner",
    right_cols: list[str] | None = None,
    reconcile: bool = False,
) -> QueryResult:
    """Run ``left_sql`` on one connection and batched-foreach-join it to a table/sub-query on another.

    The by-connection-id entry point the planner and API surface call — the right side is either
    ``right_table`` or ``right_sql`` (a grounded sub-query). Fail-safe throughout."""
    from aughor.db.connection import open_connection_for
    left_conn = open_connection_for(left_conn_id)
    left = left_conn.execute("__remote_join_left__", left_sql)
    right_conn = open_connection_for(right_conn_id)
    return batched_foreach_join(
        left, left_key, right_conn, right_key,
        right_table=right_table, right_sql=right_sql,
        right_cols=right_cols, how=how, reconcile=reconcile,
    )
