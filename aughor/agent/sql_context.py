"""What every SQL-writing prompt is told about the engine and the clock.

Measured 2026-09-29 on five Agent-mode runs against theLook (BigQuery), prompts captured:
no prompt that asked a model for SQL named the engine, today's date or how far the data
runs. What that cost, run by run:

- the intake placed "last 6 months" in 2024, because a model that is not told the date
  guesses it from the sample values; code re-anchored the window on the temporal path
  and not on the cross-sectional one, and one re-run answered June–November 2024;
- the analyst wrote ``created_at <= '2026-07-31'`` on a TIMESTAMP column, which drops
  the last day of the period (July published 3.6% under);
- an intake that returned nothing left the analyst with no window at all; it anchored on
  ``CURRENT_DATE``, and the "biggest rise" it reported was a month still filling, with
  rows dated a week into the future;
- the analyst wrote ``DATEADD(month, -13, CURRENT_DATE)`` and ``DATE_TRUNC('month', x)``
  and lost two statements to the engine before finding BigQuery's spelling by trial;
- the writer scheduled a recommendation for "Q1 2026", nine months in the past.

Each prompt now carries the same short block: the dialect to write, the date, and the
last SETTLED day of the data — the day up to which a period is complete — and every
window is handed over as a half-open filter, ready to paste, so the end bound is never
the model's to spell.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

#: The engine's name as a person writing SQL for it would say it. An unlisted dialect is
#: named as sqlglot names it — never left out.
#: DE-3b: derived from each engine's declaration (`sql_name`, else its label), so the prompt
#: names a new engine the day it is declared.
from aughor.connectors.declarations import derive_engine_names  # noqa: E402

_ENGINE_NAMES = derive_engine_names()


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def engine_dialect(conn) -> str:
    """The dialect a statement written for ``conn`` is in — the engine's own where it runs
    SQL as written, DuckDB's where the door translates (GM-1's `authored_dialect`)."""
    if conn is None:
        return ""
    try:
        from aughor.db.dialects import authored_dialect
        return str(authored_dialect(conn) or "")
    except Exception:
        return str(getattr(conn, "dialect", "") or "")


def settled_day(today: str, coverage_end: str = "", settle_days: int = 1) -> str:
    """The last day whose rows are complete. ``settle_days`` before today when the data
    reaches that far (a source that restates its recent days is "in progress" for longer
    than one day — `settling.learned_lag_days`); the data's own last day when it stops
    earlier (a closed dataset's final day is as complete as it will ever be)."""
    try:
        t = date.fromisoformat((today or "")[:10])
    except ValueError:
        return (coverage_end or "")[:10]
    last = (t - timedelta(days=max(1, int(settle_days or 1)))).isoformat()
    end = (coverage_end or "")[:10]
    return min(end, last) if end else last


def sql_context(conn=None, *, dialect: str = "", today: str = "", coverage_end: str = "",
                settle_days: int = 1) -> str:
    """The block: one line for the engine, one for the clock. Either half is left out
    only when nothing is known for it, never guessed."""
    lines: list[str] = []
    d = (dialect or engine_dialect(conn) or "").strip().lower()
    if d:
        lines.append(f"SQL DIALECT: {_ENGINE_NAMES.get(d, d)} — write every statement for this "
                     "engine, in its own spelling.")
    t = (today or "")[:10] or today_utc()
    settled = settled_day(t, coverage_end, settle_days)
    clock = f"TODAY: {t} (UTC)."
    if coverage_end:
        clock += (f" The data runs to {(coverage_end or '')[:10]}; its last SETTLED day is {settled} — "
                  "rows dated after it are still arriving, so no period ending later is complete.")
    else:
        clock += f" The last settled day is {settled}."
    clock += (" A relative period (\"last 6 months\", \"recent\") counts back from the settled day, "
              "never from a sample value. Never anchor a window on CURRENT_DATE or NOW(): use "
              "the literal dates you are given.")
    lines.append(clock)
    return "\n".join(lines)


def window_filter(column: str, start: str, end: str) -> str:
    """A period as the filter to paste: ``col >= 'start' AND col < 'day after end'``.

    Half-open, with plain quoted dates: the end bound is the day AFTER the period's last
    day, so a TIMESTAMP column keeps that whole day (``<= '2026-07-31'`` keeps only its
    first instant), and a quoted date compares with DATE and TIMESTAMP columns alike on
    every engine here, where ``DATE '…'`` against a TIMESTAMP does not. Empty when the
    period or the column is unknown."""
    col, s, e = (column or "").strip(), (start or "")[:10], (end or "")[:10]
    if not (col and s and e):
        return ""
    try:
        after = (date.fromisoformat(e) + timedelta(days=1)).isoformat()
    except ValueError:
        return ""
    return f"{col} >= '{s}' AND {col} < '{after}'"


def window_text(label: str, start: str, end: str, column: str = "") -> str:
    """How a period is written into a prompt: its label, its inclusive dates, and — when
    the date column is known — the filter that selects exactly it."""
    s, e = (start or "")[:10], (end or "")[:10]
    head = f"{label} ({s} to {e} inclusive)" if s and e else (label or "")
    f = window_filter(column, s, e)
    return f"{head} — filter: {f}" if f else head


def learned_settle_days(connection_id: Optional[str]) -> int:
    """How many days back this source's rows stop moving (1 when nothing is learned)."""
    try:
        from aughor.settling.store import learned_lag_days
        return int(learned_lag_days(connection_id or "") or 1)
    except Exception:
        return 1
