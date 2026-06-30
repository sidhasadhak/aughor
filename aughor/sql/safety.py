"""Shared SQL-safety pipeline — one validate-and-repair chain every answer mode calls.

The three answer modes (Insight / Deep-ADA / Explorer) had each grown a DIFFERENT subset of the same
safeguards, which is precisely how Insight ended up surfacing a raw binder error that Deep's intake
would have caught. ``preflight_repair`` is the single chain:

    deterministic identifier repair (case/separator)  ->  dry-run  ->  (on bind failure)
    SqlWriter.fix  (which itself substitutes DuckDB's candidate bindings deterministically before
    spending any LLM call)

Fail-open by construction: on any internal hiccup it returns the original SQL, so the caller executes
it and falls back to its own post-execute handling — behaviour only ever improves, never regresses.

See docs/MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md (R2).
"""
from __future__ import annotations

from typing import Optional


def _bump(counter: str) -> None:
    """Observability receipt — record that a safeguard fired (which one, how often), so we can
    confirm the shared pipeline is actually doing work across modes (not silently no-op)."""
    try:
        from aughor.stats import stats
        stats.inc(counter)
    except Exception:
        pass


def preflight_repair(conn, sql: str, schema: Optional[str] = None, *, max_retries: int = 2) -> tuple[str, dict]:
    """Validate ``sql`` against ``conn`` BEFORE the user-facing execute and return
    ``(possibly-repaired sql, receipt)``.

    receipt = {
        "identifiers_repaired": bool,   # a case/separator identifier was deterministically fixed
        "dry_run_ok": bool | None,      # did the (repaired) SQL bind? None if dry_run was unavailable
        "fixed": bool,                  # a binder/parse error was repaired via SqlWriter.fix
        "error_class": str,             # the typed error class when a fix happened ("binder"/…)
    }

    Never raises. Idempotent on already-valid SQL (dry-run passes, nothing changes)."""
    receipt = {"identifiers_repaired": False, "filter_bound": False, "dry_run_ok": None,
               "fixed": False, "error_class": ""}
    if not sql or not sql.strip():
        return sql, receipt
    out = sql
    try:
        # 1 — Deterministic case/separator identifier repair (e.g. customer_id -> customerID).
        #     Adopt only if the rewrite actually binds, so a wrong guess can never make things worse.
        if schema:
            try:
                from aughor.sql.identifiers import repair_identifiers
                from aughor.db.schema_render import parse_schema_tables
                _tc = {t: (list(c.keys()) if isinstance(c, dict) else c)
                       for t, c in parse_schema_tables(schema).items()}
                _ri = repair_identifiers(out, _tc, dialect=getattr(conn, "dialect", "duckdb"))
                if _ri and _ri.strip() != out.strip() and conn.dry_run(_ri)[0]:
                    out = _ri
                    receipt["identifiers_repaired"] = True
                    _bump("sql_safety.identifiers_repaired")
            except Exception:
                pass

        # 1.5 — Active filter-literal binding. A guessed enum literal that matches no row but has a
        #       confirmed near-neighbour in the column's live domain (e.g. 'cancelled' → 'canceled')
        #       is rewritten to the stored value, so the query returns the intended rows instead of
        #       silently zero. Probe-confirmed and dry-run-gated: a wrong rewrite is never adopted.
        try:
            from aughor.sql.join_guard import bind_filter_literals
            _bound, _applied = bind_filter_literals(conn, out, getattr(conn, "dialect", "duckdb"))
            if _applied and _bound.strip() != out.strip() and conn.dry_run(_bound)[0]:
                out = _bound
                receipt["filter_bound"] = True
                _bump("sql_safety.filter_bound")
        except Exception as _e:
            from aughor.kernel.errors import tolerate
            tolerate(_e, "preflight: filter binding skipped", counter="sql_safety.filter_bind_error")

        # 2 — Dry-run. If it binds, we are done (the common, happy path).
        try:
            ok, err = conn.dry_run(out)
        except Exception:
            return out, receipt  # dry_run unavailable on this connection → let the caller execute
        receipt["dry_run_ok"] = bool(ok)
        if ok:
            return out, receipt

        # 3 — Repair the bind/parse error. SqlWriter.fix substitutes DuckDB's candidate bindings
        #     deterministically (no LLM) before falling back to a typed LLM repair, and validates
        #     every candidate with its own internal dry-run.
        try:
            from aughor.sql.writer import SqlWriter
            fixed = SqlWriter(conn, schema_str=schema).fix(out, err or "binder error", max_retries=max_retries)
            if fixed.ok and fixed.sql and fixed.sql.strip() != out.strip():
                out = fixed.sql
                receipt["fixed"] = True
                receipt["dry_run_ok"] = True
                receipt["error_class"] = getattr(fixed, "error_class", "") or ""
                _bump(f"sql_safety.preflight_fixed.{receipt['error_class'] or 'unknown'}")
        except Exception:
            pass
    except Exception:
        return sql, receipt
    return out, receipt
