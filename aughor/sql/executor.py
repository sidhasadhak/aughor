"""Shared guarded-SQL runner — WS2 increment 1 (one executor, three call sites).

``execute_guarded`` is the "execute generated SQL with the guard battery + one
self-correction retry" orchestration, extracted VERBATIM from the ADA path's
``aughor.agent.investigate._execute_safe`` (the richest of the three
near-duplicate implementations; explore/nodes repoint in later increments).

Layering: this module lives BELOW the agent layer and must never import from
``aughor.agent``. The two things the original body took from that layer are
therefore parameters:

- ``fix_prompt_template`` — the FIX prompt (investigate passes
  ``aughor.agent.prompts.FIX_SQL_PROMPT``). Without it (and a provider) the
  runner is deterministic-guards-only: no LLM retry is attempted.
- ``provider_factory`` — ``role -> LLM provider`` (investigate passes its
  module-level ``_provider`` so test monkeypatching keeps working).

Everything else — every guard call, tolerate() reason/counter, acceptance
gate — is byte-for-byte the ADA behavior. Counter names intentionally keep
their historical ``ada.*`` prefixes for continuity of the /dev/stats series.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection


def zero_row_suspicious(sql: str) -> str | None:
    """Return a diagnosis string if a zero-row result is likely a bad query, else None."""
    s = sql.lower()
    # Casting an identifier column as a date is the #1 cause of silent zero-row failures
    if "cast(" in s and ("as date" in s or "as timestamp" in s):
        return (
            "Query returned 0 rows. LIKELY CAUSE: CAST(... AS DATE/TIMESTAMP) is being used on "
            "an identifier column (e.g. order_id, invoice_id) which is NOT a date. "
            "Find the real DATE/TIMESTAMP column in the schema (or a joinable table) and use that instead."
        )
    # Filtering on a column that sounds like an ID but treating it as a date range
    import re as _re
    if _re.search(r"where\s+\w*(?:_id|_key|_num|_code)\b.*>=\s*'[0-9]{4}", s):
        return (
            "Query returned 0 rows. LIKELY CAUSE: a WHERE clause is comparing an _id/_key column "
            "to a date string — identifiers are not dates. "
            "Use a proper DATE/TIMESTAMP column for date range filtering."
        )
    return None


def missing_column_hint(err: str):
    """Turn a binder/missing-column error into a strong, specific repair diagnosis.
    Extracts the missing column + the engine's candidate bindings and tells the coder to
    JOIN to the table that actually has the column instead of dropping/renaming it — the
    exact recovery the ADA baseline missed for `invoices.order_ts` (lives in `orders`)."""
    if not err:
        return None
    low = err.lower()
    if "column" not in low and "binder" not in low:
        return None
    m = (re.search(r'does not have a column named\s+"?([A-Za-z0-9_.]+)"?', err, re.I)
         or re.search(r'Referenced column\s+"?([A-Za-z0-9_.]+)"?', err, re.I)
         or re.search(r'column\s+"?([A-Za-z0-9_.]+)"?\s+(?:not found|does not exist)', err, re.I))
    col = m.group(1) if m else "the referenced column"
    cands = re.findall(r'"([A-Za-z0-9_]+\.[A-Za-z0-9_]+)"', err)
    cand_txt = f" The engine offered candidate bindings: {', '.join(dict.fromkeys(cands))[:200]}." if cands else ""
    return (
        f"DIAGNOSIS: column '{col}' is not in the table(s) currently in the FROM/JOIN clause.{cand_txt} "
        f"Find which table in the SCHEMA actually contains '{col}' and JOIN to it using a shared key "
        f"(an *_id column). The timestamp/metric you need likely lives in a parent table (e.g. an orders "
        f"table) that must be joined — do NOT drop the column, rename it, or substitute a different one.\n"
    )


def preflight_harden(conn: "DatabaseConnection", sql: str, schema: str, *,
                     counter_prefix: str = "ada.exec") -> str:
    """The pure, deterministic PRE-execute hardening — de-fan then preflight-repair.

    Both are SQL→SQL rewrites gated on a clean dry-run (a rewrite is adopted only if
    it binds), so on already-correct SQL this is a no-op. Extracted so every answer
    path shares the SAME hardening: the ADA runner (below) and the explore loop (which
    had neither de-fan nor preflight-repair before) both call it. Fail-open — any
    internal hiccup returns the SQL unchanged. ``counter_prefix`` keeps each caller's
    /dev/stats series distinct (``ada.exec_*`` vs ``explore.exec_*``)."""
    if not schema:
        return sql
    # Deterministic de-fan (#1 correctness): a SUM of a parent measure across a
    # one-to-many join over-counts (5x). Replace it with the exact dedup BEFORE
    # executing. Adopt only if it dry-runs clean; silent on anything it can't prove.
    try:
        from aughor.sql.fanout import defan, detect_fanout, dimension_ratio_chasm
        # NB: the platform-side home of the parser (aughor.tools.schema merely
        # re-exports it; importing it there would cross the platform→agent boundary).
        from aughor.db.schema_render import parse_schema_tables
        _dialect = getattr(conn, "dialect", "duckdb")
        _tc = {t: (list(c.keys()) if isinstance(c, dict) else c)
               for t, c in parse_schema_tables(schema).items()}
        _ff = detect_fanout(sql, _tc, dialect=_dialect) or \
            dimension_ratio_chasm(sql, _tc, dialect=_dialect)
        if _ff:
            _rw = defan(sql, _ff, dialect=_dialect)
            if _rw and _rw.strip() != sql.strip() and conn.dry_run(_rw)[0]:
                sql = _rw
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "fan-out de-fan rewrite is advisory; the original SQL executes "
                       "unguarded", counter=f"{counter_prefix}_defan")

    # R2 (mode cross-pollination) — pre-flight through the SHARED safety pipeline
    # (identifier repair -> dry-run -> deterministic candidate substitution -> typed LLM fix)
    # so a binder error is repaired BEFORE execute, not only by the post-execute retry. Fail-open.
    try:
        from aughor.sql.safety import preflight_repair
        sql, _ = preflight_repair(conn, sql, schema)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "pre-flight SQL repair is fail-open; original SQL executes and "
                       "the post-execute retry still applies", counter=f"{counter_prefix}_preflight")
    return sql


def execute_guarded(
    conn: "DatabaseConnection",
    sql: str,
    *,
    query_id: str,
    schema: Optional[str] = None,
    fix_prompt_template: Optional[str] = None,
    provider_factory: Optional[Callable[..., Any]] = None,
):
    """Execute SQL with the guard battery and one self-correction retry. Returns QueryResult.

    Retries on:
    - Hard SQL errors (syntax, missing column/table)
    - Suspicious zero-row results (e.g. CAST of identifier column as DATE)
    - Guard findings (value-disjoint join, unbound filter literal, id-arithmetic)

    `schema` is the canvas-scoped schema for the fix prompt; without it the fix
    LLM would see the full connection schema (every dataset on a multi-dataset
    connection) and could "fix" a query by switching to an out-of-scope table.

    `fix_prompt_template` + `provider_factory` supply the LLM repair loop from
    the caller's layer; when either is missing the deterministic guards still
    run but the LLM retry is skipped (the raw result is returned).
    """
    from pydantic import BaseModel

    # Pre-execute deterministic hardening (de-fan → preflight-repair), shared with the
    # explore path. Byte-identical to the inline version this replaced — same guards,
    # same dry-run gates, same ada.exec_* counters.
    if schema:
        sql = preflight_harden(conn, sql, schema, counter_prefix="ada.exec")

    # AL-01 (behind trust.verify_live) — route the generated SQL through the one Trust plane's
    # decisive read-only gate before execute: the mutation / DDL / disallowed-function BLOCK the
    # generation path never ran (the connection layer is already fail-closed, so this is
    # defence-in-depth at the plane). Conn-less Scope → only the pure readonly + E1 checks run
    # (the preflight/join/grain guards already run inline above/below — no double work). A BLOCK
    # returns a blocked QueryResult (handled downstream like any failed query), never raises.
    from aughor.kernel.flags import flag_enabled
    if flag_enabled("trust.verify_live"):
        try:
            from aughor.trust import verify as _trust_verify, Scope as _TrustScope
            _verdict = _trust_verify(sql, _TrustScope(schema=schema,
                                                      dialect=getattr(conn, "dialect", "duckdb")),
                                     kind="sql")
            if not _verdict.ok:
                from aughor.platform.contracts.execution import QueryResult
                return QueryResult(hypothesis_id=query_id, sql=sql, columns=[], rows=[],
                                   row_count=0, error=f"[BLOCKED] {_verdict.reason}")
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "AL-01 trust.verify live gate (advisory; execute proceeds)",
                     counter="trust.verify_live")

    result = conn.execute(query_id, sql)

    # Determine whether to retry: hard error OR suspicious zero-row result
    _zero_diag = None
    if not result.error and result.row_count == 0:
        _zero_diag = zero_row_suspicious(sql)

    # Value-domain join guard: a join on value-disjoint keys produces an
    # unreliable result (0 rows on inner joins, all-NULL right side on outer)
    # without ever erroring. Detect it and feed the regenerate loop below.
    _domain_warnings = []
    try:
        from aughor.sql.join_guard import check_join_value_domains
        _domain_warnings = check_join_value_domains(conn, sql)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "ada join-guard probe best-effort; query proceeds",
                 counter="join_guard.ada_probe")

    # Filter value-domain guard: a misspelled WHERE/HAVING literal — `status = 'cancelled'`
    # when the data holds 'canceled' — matches (or, with `!=`/`NOT IN`, EXCLUDES) zero rows
    # and silently reports "no cancellations" (the Q29 scar: zero despite 15,737). Probe the
    # column's real domain and feed the same regenerate loop. Chat already does this; ADA didn't.
    _filter_warnings = []
    try:
        from aughor.sql.join_guard import check_filter_value_domains
        _filter_warnings = check_filter_value_domains(conn, sql)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "ada filter-guard probe best-effort; query proceeds",
                 counter="filter_guard.ada_probe")

    # Id-arithmetic guard: SUM(measure * key_id) multiplies a measure by a surrogate key/id — a
    # meaningless inflation (the "SUM(unit_price * order_item_id)" the dimensional planner wrote). It
    # executes without error and returns rows, so the error/zero/domain triggers miss it; ADA only
    # caveated it. Detect it and feed the SAME repair loop, with the specific diagnosis — parity with
    # Insight, which repairs id-arithmetic rather than just flagging it.
    _idmath_warn = ""
    try:
        from aughor.sql.fanout import measure_times_key_arithmetic
        _idmath_warn = measure_times_key_arithmetic(sql, dialect=getattr(conn, "dialect", "duckdb")) or ""
    except Exception:
        _idmath_warn = ""

    if result.error or _zero_diag or _domain_warnings or _filter_warnings or _idmath_warn:
        # No fixer supplied (template or provider missing) → deterministic-only mode:
        # the guards above have run; return the raw result to the caller unchanged.
        if fix_prompt_template is None or provider_factory is None:
            return result

        class _Fix(BaseModel):
            fixed_sql: str
            explanation: str

        try:
            _err = result.error or ""
            # Build targeted diagnosis for the fix LLM
            _col_hint = missing_column_hint(_err)
            if _zero_diag:
                _diag = f"DIAGNOSIS: {_zero_diag}\n"
            elif _col_hint:
                _diag = _col_hint
            elif "does not exist" in _err and "table" in _err.lower():
                _diag = (
                    "DIAGNOSIS: A table name in the query does not exist. "
                    "Use ONLY the table names listed in the SCHEMA above.\n"
                )
            else:
                _diag = ""

            # Append the value-domain mismatch to the diagnosis (it may co-occur
            # with a zero-row diagnosis, or be the sole reason for the retry).
            if _domain_warnings:
                _dw_text = "\n".join(w.to_prompt_text() for w in _domain_warnings)
                _diag = (f"{_diag}\n{_dw_text}" if _diag else f"DIAGNOSIS: {_dw_text}").strip() + "\n"
            if _filter_warnings:
                _fw_text = "\n".join(w.to_prompt_text() for w in _filter_warnings)
                _diag = (f"{_diag}\n{_fw_text}" if _diag else f"DIAGNOSIS: {_fw_text}").strip() + "\n"
            if _idmath_warn:
                _diag = (f"{_diag}\n{_idmath_warn}" if _diag else f"DIAGNOSIS: {_idmath_warn}").strip() + (
                    "\nRemove the multiplication by the id/key column — a measure is never multiplied "
                    "by a row identifier. Aggregate the measure itself (e.g. SUM(unit_price), or "
                    "SUM(unit_price * quantity) only if a real quantity column is intended).\n")

            # Synthesise a fake "error" message so FIX_SQL_PROMPT has something
            # useful in the ERROR MESSAGE field when there was no hard error.
            if _err:
                fix_error = _err
            elif _domain_warnings:
                fix_error = "A join is on value-disjoint columns (see DIAGNOSIS) — the result is unreliable."
            elif _filter_warnings:
                fix_error = "A filter literal is absent from the column's value domain (see DIAGNOSIS) — the result silently includes/excludes the wrong rows."
            elif _idmath_warn:
                fix_error = "A measure is multiplied by an id/key column (see DIAGNOSIS) — the aggregate is meaninglessly inflated."
            else:
                fix_error = "Query returned 0 rows — the SQL logic is likely wrong (see DIAGNOSIS)."

            fix_prompt = fix_prompt_template.format(
                dialect=conn.dialect,
                sql=sql,
                error=fix_error,
                schema=schema if schema else conn.get_schema(),
                kb_patterns_section="",
                metrics_section="",
                error_diagnosis=_diag,
            )
            fix = provider_factory("coder").complete(
                system="Fix this SQL query. Return fixed_sql and a one-line explanation.",
                user=fix_prompt,
                response_model=_Fix,
            )
            retry = conn.execute(query_id, fix.fixed_sql)
            # Accept the fix if: hard error resolved, OR zero-row and fix got rows.
            # For a domain-mismatch retry, additionally require the regeneration to
            # actually CLEAR the mismatch — never replace a query with one that still
            # joins on value-disjoint keys (prevention > recovery; never go backwards).
            _accept = not retry.error and (retry.row_count > 0 or not _zero_diag)
            if _accept and _domain_warnings:
                try:
                    from aughor.sql.join_guard import check_join_value_domains as _cjvd
                    _accept = not _cjvd(conn, fix.fixed_sql)
                except Exception:
                    _accept = False
            # Never replace a query with one that STILL filters on a non-existent literal.
            if _accept and _filter_warnings:
                try:
                    from aughor.sql.join_guard import check_filter_value_domains as _cfvd
                    _accept = not _cfvd(conn, fix.fixed_sql)
                except Exception:
                    _accept = False
            # Never accept a "fix" that still multiplies the measure by a key/id column.
            if _accept and _idmath_warn:
                try:
                    from aughor.sql.fanout import measure_times_key_arithmetic as _mtka
                    _accept = not _mtka(fix.fixed_sql, dialect=getattr(conn, "dialect", "duckdb"))
                except Exception:
                    _accept = False
            if _accept:
                retry.sql = fix.fixed_sql
                result = retry
        except Exception as _exc:
            from aughor.kernel.errors import tolerate
            tolerate(_exc, "post-execute LLM fix is best-effort; returning the raw retry "
                           "result", counter="ada.exec_retry_fix")
    return result
