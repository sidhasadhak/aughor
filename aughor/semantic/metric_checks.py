"""Whether a definition's SQL can run on its connection — the one check every door that writes a
definition asks: the editor's save (`routers/metrics._require_binds`) and an import's plan, which
used to skip it, so a file could land a formula its warehouse cannot run.

A governed definition was the one artifact nothing validated. Measured on theLook 2026-09-27, the
save door let two definitions be saved AND approved as the organisation's revenue:
`SUM(total_amount)`, naming a column the warehouse does not have, and a statement one paren short.
Both then held every Slack send that stated revenue.

What is refused and what is not, deliberately:

* A parse error is refused always — it needs no warehouse and cannot be a false alarm.
* A bind failure is refused when the connection answered — the engine's own verdict on its schema.
* Unreachable connection, no dry-run support, or a global / organisation definition with no one
  connection to ask: NOT refused — the check fails OPEN, and says so (counter + log), because
  "checked and fine" and "never checked" must not look identical.

The runnable form is what is checked — `as_statement` over the declared tables and filters —
because that is exactly what the value path executes, not the stored text.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

OK, UNCHECKED, REFUSED = "ok", "unchecked", "refused"


def runs_on(sql: str, connection: Optional[str], name: str,
            tables: Iterable[str] = (), filters: Iterable[str] = ()) -> tuple[str, str]:
    """``(verdict, why)`` — ``ok``, ``unchecked`` (and why not), or ``refused`` (and the reason, in
    words a person acts on)."""
    from aughor.semantic.metric_statement import as_statement
    from aughor.semantic.metrics import GLOBAL_CONNECTION, is_org_scope

    text = (sql or "").strip()
    if not text:
        return UNCHECKED, "it has no SQL"
    runnable = as_statement(text, list(tables or []), list(filters or []), name) or text

    def _unchecked(why: str) -> tuple[str, str]:
        from aughor.stats import stats
        stats.inc("metrics.save_unchecked")
        logger.info("metric definition not bind-checked (%s): %s", why, name)
        return UNCHECKED, why

    try:
        import sqlglot
        sqlglot.parse_one(runnable, read="bigquery")
    except ImportError as exc:
        # No parser on this install. The dry run below may still bind it, but "not parsed
        # here" and "parsed clean" must not look alike to whoever reads the counters.
        from aughor.kernel.errors import tolerate
        tolerate(exc, "sqlglot is unavailable, so the definition was not parse-checked; the "
                      "engine's own dry run below still gates it",
                 counter="metrics.save_no_parser")
    except Exception as exc:  # noqa: BLE001 — a parse error IS the verdict
        return REFUSED, f"that SQL does not parse, so it cannot be a definition: {str(exc).splitlines()[0][:200]}"

    if not connection or connection == GLOBAL_CONNECTION:
        return _unchecked("global definition — no connection to ask")
    if is_org_scope(connection):
        return _unchecked("organisation definition — no one connection to ask")
    from aughor.db.connection import open_connection_for
    try:
        db = open_connection_for(connection)
    except Exception as exc:  # noqa: BLE001
        return _unchecked(f"connection unreachable ({type(exc).__name__})")
    try:
        ok, err = db.dry_run(runnable)
    except Exception as exc:  # noqa: BLE001
        return _unchecked(f"dry run unavailable ({type(exc).__name__})")
    finally:
        try:
            db.close()
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a close that fails is logged, not raised over the answer",
                     counter="metrics.save_check_close")
    if not ok:
        from aughor.stats import stats
        stats.inc("metrics.save_refused_bind")
        return REFUSED, (f"{connection} cannot run that SQL, so it cannot be its definition of "
                         f"{name}: {str(err or 'the engine refused it').splitlines()[0][:300]}")
    return OK, ""
