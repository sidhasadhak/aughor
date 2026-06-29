"""Dialect-agnostic closed-loop execute → observe → repair, plus evaluator-faithful
CSV materialization.

Why this exists
---------------
Aughor's production answer path validates that SQL *binds* (``safety.preflight_repair`` →
``conn.dry_run`` / ``EXPLAIN``) but never closes the loop on the *actual result*. Every
top-of-leaderboard text-to-SQL system (Spider 2.0, BIRD) does the opposite: it **executes the
candidate against the real engine, reads the error or the result, and repairs** — for several
rounds — then materializes the output in the evaluator's exact CSV contract.

This module lifts that loop into the product as a **backend-agnostic primitive**: it takes plain
callables, so the same code drives a SQLite reader, a Snowflake cursor, or BigQuery. It is
deliberately dependency-light and side-effect free (no LLM imports, no global state) so it is
trivially unit-testable and safe to call from any mode.

Two pieces:
  * ``execute_with_repair`` — the loop. Real execution, repair-on-error, recover-on-empty.
    Adopts a rewrite ONLY if it executes (and returns rows when recovering), so it can correct
    but never regress — the same fail-closed discipline as ``preflight_repair``.
  * ``rows_to_csv`` — output-contract conformance. Matches the Spider2 evaluator's
    ``pd.DataFrame(rows, columns=cols).to_csv(path, index=False)`` byte-for-byte: real ``None`` →
    empty cell (NOT the literal string ``"NULL"``), column order from the cursor, no row cap.
    This is exactly what ``SnowflakeConnection.execute`` got wrong (``"NULL"`` stringify +
    ``MAX_ROWS=2000`` truncation) and why a correct query could still score 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Any


# execute_fn(sql) -> (ok, rows_or_count, error)
#   ok    : did the query run?
#   rows  : a list of rows (preferred) OR an int row-count
#   error : error string when not ok (else "")
ExecuteFn = Callable[[str], tuple[bool, Any, str]]
RepairFn = Callable[[str, str], Optional[str]]          # (bad_sql, error) -> new_sql | None
RecoverFn = Callable[[str], Optional[str]]              # (empty_sql)      -> new_sql | None


@dataclass
class LoopResult:
    sql: str                      # best SQL found (original if nothing better executed)
    ok: bool                      # did the final SQL execute?
    row_count: int                # rows the final SQL returned (-1 if unknown)
    rounds: int                   # repair/recover rounds spent
    receipt: dict = field(default_factory=dict)


def _row_count(rows: Any) -> int:
    if rows is None:
        return -1
    if isinstance(rows, int):
        return rows
    try:
        return len(rows)
    except TypeError:
        return -1


def execute_with_repair(
    sql: str,
    execute_fn: ExecuteFn,
    repair_fn: Optional[RepairFn] = None,
    recover_empty_fn: Optional[RecoverFn] = None,
    *,
    max_rounds: int = 2,
    expect_rows: bool = True,
) -> LoopResult:
    """Run ``sql`` through a closed execute → observe → repair loop.

    1. Execute. If it errors and ``repair_fn`` is given, ask for a fix from the *real* error text,
       adopt the fix only if it executes, and repeat (up to ``max_rounds``).
    2. If it executes but returns zero rows and ``expect_rows`` and ``recover_empty_fn`` is given,
       ask for a recovery (usually a wrong/over-tight filter), adopt only if it executes AND
       returns rows.

    Never raises (callable exceptions are swallowed and treated as a failed attempt). Idempotent on
    already-good SQL: a query that executes and returns rows is returned unchanged with zero rounds.
    """
    receipt: dict = {"repaired": False, "recovered": False, "error_class": "", "errors": []}
    current = (sql or "").strip()
    if not current:
        return LoopResult(sql=sql, ok=False, row_count=-1, rounds=0, receipt=receipt)

    def _safe_exec(s: str) -> tuple[bool, Any, str]:
        try:
            return execute_fn(s)
        except Exception as e:  # a callable that throws == a failed attempt, not a crash
            return False, None, str(e)

    ok, rows, err = _safe_exec(current)
    rounds = 0

    # ── error-repair rounds ──
    while not ok and repair_fn is not None and rounds < max_rounds:
        rounds += 1
        receipt["errors"].append((err or "")[:200])
        try:
            cand = repair_fn(current, err or "")
        except Exception:
            cand = None
        if not cand or cand.strip() == current:
            break
        c_ok, c_rows, c_err = _safe_exec(cand.strip())
        if c_ok:
            current, ok, rows, err = cand.strip(), True, c_rows, ""
            receipt["repaired"] = True
            break
        # adopt the new error so the next round repairs the *new* failure, not the stale one
        current, err = cand.strip(), c_err

    # ── empty-result recovery (one shot; only adopt if it returns rows) ──
    if ok and expect_rows and recover_empty_fn is not None and _row_count(rows) == 0:
        try:
            cand = recover_empty_fn(current)
        except Exception:
            cand = None
        if cand and cand.strip() != current:
            c_ok, c_rows, _ = _safe_exec(cand.strip())
            if c_ok and _row_count(c_rows) > 0:
                current, rows = cand.strip(), c_rows
                receipt["recovered"] = True
                rounds += 1

    return LoopResult(sql=current, ok=ok, row_count=_row_count(rows), rounds=rounds, receipt=receipt)


def rows_to_csv(columns: Sequence[str], rows: Sequence[Sequence[Any]], path) -> None:
    """Materialize a result table to CSV matching the Spider2 evaluator's contract.

    The evaluator does ``pd.DataFrame(rows, columns=columns).to_csv(path, index=False)`` and then
    compares column vectors with ``abs_tol=1e-2``. To match it we MUST:
      * preserve the cursor's column order and names (header row),
      * write real ``None`` as an EMPTY cell — never the literal ``"NULL"``,
      * emit every row — never truncate.

    Uses pandas when available (byte-identical to the evaluator); falls back to the stdlib ``csv``
    module otherwise (None → '' is the stdlib default, so the contract still holds).
    """
    cols = list(columns)
    data = [list(r) for r in rows]
    try:
        import pandas as pd  # the eval suite uses pandas; matching it removes dtype/format drift
        pd.DataFrame(data, columns=cols).to_csv(path, index=False)
        return
    except Exception as e:
        # Not a silent swallow: record the fall-through to the stdlib path with a trail.
        from aughor.kernel.errors import tolerate
        tolerate(e, "rows_to_csv: pandas path unavailable, using stdlib csv",
                 counter="closed_loop.csv_pandas_fallback")
    import csv
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in data:
            w.writerow(["" if v is None else v for v in r])
