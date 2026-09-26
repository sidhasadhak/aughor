"""Briefings by period — a daily, weekly, monthly or yearly Briefing, each written for its window.

IDEAS.md 3 (PENDING.md item 7). Measured 2026-09-23 before a line of this was written:

* the Briefing had NO window at all — ``get_briefing`` took no period, read every stored
  finding (each measured inside the explorer's own ≤12-month window, so not "the whole
  history" either), and led with north-star moves taken first→last over whatever buckets a
  model-written chart happened to have;
* the day/week *subscriptions* sent the alert summary (``monitors/alert_summary``), not a
  briefing, and only its alert section honoured the period.

A period briefing is a different question from the standing one — "what happened in THIS
week, against the week before" — so it is built from different evidence, not the same
evidence with a different heading:

1. **The window is computed, never inferred** (``automations.temporal.complete_period``): the
   most recent COMPLETE period whose last day is settled for this source — the lag the
   platform learned (``aughor.settling``, idea 4) when it has one, else one day — and the
   period it is compared with (a day against the same weekday a week earlier; a week, month
   or year against the one before; the year is the fiscal year when org settings say so).
2. **Each headline metric is MEASURED for the window**: its own trend query is cut to the two
   windows (``sql.trend_window.period_split``) and re-run, so a monthly revenue chart yields
   a correct week of revenue and a rate is recomputed over the window at its own grain. A
   metric that cannot be cut says why, in the brief (``unmeasured``) — withheld is said.
3. **Alerts that fired and findings the platform recorded in the window** join as dated
   records. The standing findings stay with the standing Briefing: a finding first recorded
   in June is not this week's news, and presenting it as such is the failure this avoids.
4. **The narrator is told which version it is writing** (``period_note``): the period, its
   dates, its comparison, and — when the source's lag is more than a day — that the newest
   days are not yet settled and the brief must say so.

A scheduled send departs as a SHEET (``sheet_lines``): the measured lines, the dated records
and the narrative's paragraphs, each judged at the departure gate on its own, with law 1
re-measuring the headline numbers at send time (``fresh_measurement``).

Everything here is deterministic except the one narrator call ``get_briefing`` already makes.
"""
from __future__ import annotations

import contextlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterator, Optional

from aughor.automations.temporal import PERIODS, PeriodWindow, complete_period, resolve_lag

#: The flag that turns briefings by period on. Off → the period doors refuse, saying so, and
#: every existing brief, alert summary and subscription behaves exactly as before.
FLAG = "briefing.by_period"

LABEL = {"day": "Daily", "week": "Weekly", "month": "Monthly", "year": "Yearly"}

#: How many headline metrics are measured per brief — the standing brief's own cap.
MAX_METRICS = 8

#: A move smaller than this is reported as steady rather than as a change of that size: the
#: same threshold the standing brief uses to decide a trend is material.
STEADY_REL = 0.02


def enabled() -> bool:
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled(FLAG)
    except Exception:  # noqa: BLE001 — an unreadable flag registry is "off"
        return False


def refusal(period: str) -> Optional[str]:
    """Why a period briefing cannot be served, or None when it can. Spoken, never implied: a
    brief that silently fell back to the standing one would teach the reader that the
    standing brief IS this week's."""
    if period not in PERIODS:
        return f"period must be one of {', '.join(PERIODS)} (or 'history' for the standing brief)"
    if not enabled():
        return (f"briefings by period are off on this install — the {LABEL[period].lower()} "
                f"briefing needs the '{FLAG}' flag")
    return None


# ── the window ─────────────────────────────────────────────────────────────────────────────

def resolve_window(conn_id: str, period: str, *, workspace_id: Optional[str] = None,
                   today: Optional[date] = None) -> tuple[PeriodWindow, str, list[str]]:
    """The window this connection's ``period`` brief covers, where its lag came from
    (``"learned"`` — idea 4's settling verdict; ``"beyond_horizon"`` — a table was still
    moving at the oldest age read, so the lag is a floor; or ``"default"``, one day), and the
    tables still moving."""
    learned, source, moving = None, None, []
    try:
        from aughor.settling.store import connection_lag
        lag = connection_lag(conn_id)
        learned, source, moving = lag["days"], lag["source"], list(lag["still_moving"])
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the learned lag is unreadable; the brief anchors on the one-day default",
                 counter="briefing.period.lag")
    fiscal = 1
    try:
        from aughor.orgsettings import effective_settings
        fiscal = int(getattr(effective_settings(workspace_id), "fiscal_year_start_month", 1) or 1)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "org settings unreadable; the yearly brief uses the calendar year",
                 counter="briefing.period.fiscal")
    today = today or datetime.now(timezone.utc).date()
    window = complete_period(period, today, resolve_lag({}, learned), fiscal_start_month=fiscal)
    return window, (source if learned and source else "default"), moving


def _d(d: date) -> str:
    return d.isoformat()


def phrases(window: PeriodWindow) -> tuple[str, str]:
    """(what the brief covers, what it is compared with), in words a reader checks against
    a calendar — ISO dates, never "last week", which is ambiguous the day after."""
    p, last, prev_last = window.period, window.last_day, window.previous_end - timedelta(days=1)
    if p == "day":
        return (f"{_d(window.start)} ({window.start.strftime('%A')})",
                f"the same weekday a week earlier, {_d(window.previous_start)}")
    if p == "week":
        return (f"the week {_d(window.start)} to {_d(last)}",
                f"the week before, {_d(window.previous_start)} to {_d(prev_last)}")
    if p == "month":
        return (window.start.strftime("%B %Y"), window.previous_start.strftime("%B %Y"))
    if window.start.month == 1:
        return (f"the year {window.start.year}", f"{window.previous_start.year}")
    return (f"the fiscal year {_d(window.start)} to {_d(last)}",
            f"the fiscal year before, {_d(window.previous_start)} to {_d(prev_last)}")


def window_block(window: PeriodWindow, lag_source: str, still_moving: Optional[list] = None) -> dict:
    """The period block every period brief carries: what it covers, why it ends where it
    does, and (filled on a build) what was measured and what could not be."""
    covers, against = phrases(window)
    return {**window.to_dict(), "label": LABEL[window.period], "covers": covers,
            "compared_with": against, "lag_source": lag_source,
            "still_moving": list(still_moving or []), "measured": [], "unmeasured": []}


def period_note(block: dict, today: Optional[date] = None) -> str:
    """The code-written block that tells the narrator which version it is writing."""
    today = today or datetime.now(timezone.utc).date()
    label = block["label"].upper()
    lines = [
        "[Briefing period — written by code, not inferred]",
        f"This is the {label} briefing. It covers {block['covers']} (UTC) and compares it with "
        f"{block['compared_with']}.",
        f"Speak about that {block['period']} only. Every finding below is from inside it or is a "
        "measurement of it; do not describe anything as happening in it that the findings do not "
        "place there, and do not compare it with any period other than the one named.",
    ]
    lag = int(block.get("lag_days") or 1)
    if lag > 1 and block.get("lag_source") == "beyond_horizon":
        moving = list(block.get("still_moving") or [])
        tables, verb, it = (", ".join(moving) or "a table",
                            *(("were", "them") if len(moving) > 1 else ("was", "it")))
        lines.append(
            f"The {block['period']} ends {lag} days before today ({today.isoformat()}) because "
            f"{tables} {verb} still changing {lag - 1} days after a day ended, and the platform has "
            f"not yet seen {it} stop: figures read from {it} may still move. Say so in one plain "
            "sentence, and do not call any of those figures final.")
    elif lag > 1:
        why = ("the platform measured" if block.get("lag_source") == "learned"
               else "this source is configured with")
        lines.append(
            f"The {block['period']} ends {lag} days before today ({today.isoformat()}) because "
            f"{why} a {lag}-day settling lag: newer days are still changing as late rows arrive. "
            "Say so in one plain sentence, so the reader never has to guess why the newest "
            "figure is dated before today.")
    if block.get("unmeasured"):
        names = ", ".join(u["name"] for u in block["unmeasured"][:6])
        lines.append(f"Not measured for this {block['period']}: {names}. Do not state a value "
                     "for them.")
    return "\n".join(lines)


# ── the measurement ────────────────────────────────────────────────────────────────────────

def _attr(m: Any, key: str) -> str:
    return str((m.get(key) if isinstance(m, dict) else getattr(m, key, "")) or "")


def _value(row) -> Optional[float]:
    """The metric's value in a ``period_split`` row: the first number after the label and
    before the two coverage days the split appends."""
    from aughor.knowledge.metric_moves import parse_number
    cells = list(row.values()) if isinstance(row, dict) else list(row)
    for cell in cells[1:-2] if len(cells) > 3 else cells[1:]:
        v = parse_number(cell)
        if v is not None:
            return v
    return None


#: How many days a window's rows may start late or end early before its value stops being
#: that period's: a week missing a quiet Sunday is still the week; a "year" the data only
#: reaches in September is not a year, and its "+200%" is the data's start, not a move.
_COVERAGE_SLACK = {"day": 0, "week": 2, "month": 7, "year": 31}


def _as_date(cell) -> Optional[date]:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    try:
        return date.fromisoformat(str(cell)[:10])
    except ValueError:
        return None


def partial_span(first, last, start: date, end: date, slack: int) -> Optional[str]:
    """``"<first> to <last>"`` when the rows cover less of the window than the slack allows."""
    lo, hi = _as_date(first), _as_date(last)
    if lo is None or hi is None:
        return None
    if (lo - start).days > slack or ((end - timedelta(days=1)) - hi).days > slack:
        return f"{lo.isoformat()} to {hi.isoformat()}"
    return None


def measure_period(metrics: list, run_sql: Callable[[str], tuple], window: PeriodWindow,
                   dialect: str = "duckdb") -> tuple[list[dict], list[dict]]:
    """Each headline metric measured for the window and its comparison. Returns
    ``(measured, unmeasured)``; every metric lands in exactly one of them, the second with
    the reason in words. ``run_sql(sql) -> (columns, rows, error)``, injected."""
    from aughor.sql.trend_window import period_split
    measured: list[dict] = []
    unmeasured: list[dict] = []
    for m in (metrics or [])[:MAX_METRICS]:
        name = _attr(m, "name")
        if not name:
            continue
        sql, why = period_split(_attr(m, "chart_sql"), start=window.start, end=window.end,
                                previous_start=window.previous_start,
                                previous_end=window.previous_end, dialect=dialect)
        if sql is None:
            unmeasured.append({"name": name, "reason": why})
            continue
        try:
            _cols, rows, error = run_sql(sql)
        except Exception as exc:  # noqa: BLE001
            error, rows = f"{type(exc).__name__}", []
        if error:
            unmeasured.append({"name": name, "reason": f"its period query failed: {str(error)[:160]}"})
            continue
        got: dict[str, tuple] = {}
        for row in rows or []:
            cells = list(row.values()) if isinstance(row, dict) else list(row)
            v = _value(row)
            if len(cells) >= 4 and v is not None:
                got[str(cells[0])] = (v, cells[-2], cells[-1])
        if "current" not in got:
            unmeasured.append({"name": name, "reason": "its data has no rows in this period"})
            continue
        slack = _COVERAGE_SLACK.get(window.period, 0)
        current, c_first, c_last = got["current"]
        previous, p_first, p_last = got.get("previous", (None, None, None))
        current_partial = partial_span(c_first, c_last, window.start, window.end, slack)
        previous_partial = (partial_span(p_first, p_last, window.previous_start, window.previous_end, slack)
                            if previous is not None else None)
        rel = ((current - previous) / abs(previous)
               if previous not in (None, 0) and not (current_partial or previous_partial) else None)
        measured.append({"name": name, "unit": _attr(m, "unit_or_range"), "current": current,
                         "previous": previous, "rel": rel, "sql": sql,
                         "current_partial": current_partial, "previous_partial": previous_partial})
    return measured, unmeasured


def _fmt(value: Optional[float], name: str, unit: str, currency_code: Optional[str]) -> str:
    if value is None:
        return "no value"
    from aughor.knowledge.metric_moves import format_value
    from aughor.knowledge.triage import currency_symbol
    text = format_value(value, name, unit, currency_symbol(currency_code))
    # a plain count comes back as `{:g}` — "1.19e+06" for 1,190,000 — which no reader parses
    # and no grounding check matches; a plain magnitude is written in full, with separators
    try:
        plain = float(text)
    except ValueError:
        return text
    return f"{plain:,.0f}" if abs(plain) >= 1000 else text


def metric_line(m: dict, block: dict, currency_code: Optional[str]) -> str:
    """One measured metric as a sentence. "from X to Y" is the phrasing the triage reads a
    change from, so a period move competes for the lead on its real size."""
    name, unit = m["name"], m.get("unit") or ""
    cur = _fmt(m["current"], name, unit, currency_code)
    prev = _fmt(m.get("previous"), name, unit, currency_code)
    rel = m.get("rel")
    if m.get("previous") is None:
        return (f"{name} was {cur} in {block['covers']}; {block['compared_with']} has no rows "
                "to compare with.")
    if m.get("current_partial") or m.get("previous_partial"):
        which, span = ((block["covers"], m["current_partial"]) if m.get("current_partial")
                       else (block["compared_with"], m["previous_partial"]))
        return (f"{name} was {cur} in {block['covers']}, against {prev} in "
                f"{block['compared_with']}; the data covers only {span} of {which}, so no "
                "change is stated.")
    if rel is None:
        return f"{name} was {cur} in {block['covers']}, against {prev} in {block['compared_with']}."
    if abs(rel) < STEADY_REL:
        return (f"{name} held steady at {cur} in {block['covers']}, against {prev} in "
                f"{block['compared_with']}.")
    return (f"{name} moved from {prev} to {cur} ({rel * 100:+.0f}%): {block['covers']} against "
            f"{block['compared_with']}.")


def period_findings(measured: list[dict], block: dict, currency_code: Optional[str]) -> list[dict]:
    """The measured metrics as candidate findings, shaped like explorer findings so the
    standing triage ranks them. The biggest period move leads on its size."""
    out = []
    for m in measured:
        slug = re.sub(r"[^a-z0-9]+", "_", m["name"].lower()).strip("_")[:40]
        out.append({"id": f"period-move::{block['period']}::{slug}", "domain": "Key Metrics",
                    "angle": "Period", "finding": metric_line(m, block, currency_code),
                    "sql": m["sql"], "confidence": 0.8, "novelty": 3, "period_move": True})
    return out


def _in_window(stamp: str, window: PeriodWindow) -> bool:
    try:
        d = date.fromisoformat(str(stamp or "")[:10])
    except ValueError:
        return False
    return window.start <= d < window.end


def alert_findings(conn_id: str, window: PeriodWindow) -> list[dict]:
    """Monitor alerts that fired inside the window, as dated candidate findings."""
    try:
        from aughor.monitors.store import get_alerts
        alerts = [a for a in get_alerts(conn_id=conn_id, limit=500)
                  if _in_window(a.triggered_at, window)]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the period brief reads no alerts when the alert store is unreadable",
                 counter="briefing.period.alerts")
        return []
    return [{"id": f"alert::{a.id}", "domain": "Alerts", "angle": "Alert",
             "finding": f"On {a.triggered_at[:10]} the {a.monitor_name or 'monitor'} alert fired: "
                        f"{a.message}",
             "sql": "", "confidence": 0.9 if a.severity == "critical" else 0.7,
             "novelty": 2, "dated": True}
            for a in alerts]


def findings_in_window(domain_data: dict, window: PeriodWindow) -> dict:
    """The stored findings the platform RECORDED inside the window — the only standing
    findings a period brief may call this period's news."""
    kept: dict = {}
    for domain, payload in (domain_data or {}).items():
        rows = payload if isinstance(payload, list) else (payload or {}).get("rows", [])
        mine = [i for i in rows or []
                if isinstance(i, dict) and _in_window(i.get("generated_at", ""), window)]
        if mine:
            kept[domain] = mine
    return kept


# ── running it ─────────────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def connection_runner(conn_id: str, *, cached: bool = True) -> Iterator[tuple[Callable[[str], tuple], str]]:
    """``(run_sql, dialect)`` over the connection, matcache-first — the same reader the
    standing brief's metric moves use, so a period query cached by one path serves both.
    ``cached=False`` reads the warehouse itself: the send-time re-measurement, which must never
    be handed back the very numbers the brief was built from."""
    from aughor.db.connection import open_connection_for, result_cache_tenancy
    from aughor.db.matcache import get_cached, put_cache
    db = open_connection_for(conn_id)

    def run_sql(sql: str):
        tenancy = result_cache_tenancy()
        hit = get_cached(conn_id, sql, tenancy=tenancy) if cached else None
        if hit is not None:
            return hit.columns, hit.rows, None
        res = db.execute("__brief_period__", sql)
        err = getattr(res, "error", None)
        if not err:
            try:
                put_cache(conn_id, sql, res, tenancy=tenancy)
            except Exception as exc:  # noqa: BLE001
                from aughor.kernel.errors import tolerate
                tolerate(exc, "period brief: matcache put", counter="briefing.period.cache_put")
        return res.columns, res.rows, err

    try:
        yield run_sql, str(getattr(db, "dialect", "") or "duckdb")
    finally:
        try:
            db.close()
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "period brief: best-effort connection close",
                     counter="briefing.period.close")


def build_period_briefing(conn_id: str, period: str, *, scope_key: str, domain_data: dict,
                          profile: Any, workspace_id: Optional[str] = None,
                          col_types: Optional[dict] = None, force_refresh: bool = False,
                          runner: Optional[Callable[[], Any]] = None,
                          today: Optional[date] = None) -> dict:
    """The ``period`` brief for one scope. ``domain_data`` is the scope's stored findings
    (all of them — the window filter is applied here); ``runner`` opens ``(run_sql,
    dialect)`` and defaults to the connection's own. Cached per scope and period, and rebuilt
    whenever the window moves, so yesterday's daily brief is never served as today's."""
    from aughor.knowledge.briefing import get_briefing
    window, lag_source, still_moving = resolve_window(conn_id, period, workspace_id=workspace_id,
                                                      today=today)
    block = window_block(window, lag_source, still_moving)
    metrics = list(getattr(profile, "north_star_metrics", None) or []) if profile is not None else []
    from aughor.orgsettings import resolve_currency
    currency = resolve_currency(getattr(profile, "currency_code", None) or "", workspace_id)

    def measure() -> dict:
        if not metrics:
            return {"findings": [], "measured": [],
                    "unmeasured": [{"name": "headline metrics",
                                    "reason": "this scope has no business profile with headline metrics"}]}
        try:
            with (runner or (lambda: connection_runner(conn_id)))() as (run_sql, dialect):
                measured, unmeasured = measure_period(metrics, run_sql, window, dialect)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the period measurement could not open the connection",
                     counter="briefing.period.measure")
            return {"findings": [], "measured": [],
                    "unmeasured": [{"name": "headline metrics",
                                    "reason": f"the connection could not be opened ({type(exc).__name__})"}]}
        for m in measured:   # the screen shows the SAME text the lines and the narrator read
            m["current_text"] = _fmt(m["current"], m["name"], m["unit"], currency)
            m["previous_text"] = _fmt(m.get("previous"), m["name"], m["unit"], currency)
        return {"findings": period_findings(measured, block, currency), "measured": measured,
                "unmeasured": unmeasured}

    candidates = findings_in_window(domain_data, window)
    alerts = alert_findings(conn_id, window)
    if alerts:
        candidates = {**candidates, "Alerts": alerts + list(candidates.get("Alerts", []))}
    return get_briefing(
        connection_id=conn_id, domain_data=candidates, patterns=[],
        force_refresh=force_refresh, scope_key=scope_key, profile=profile,
        workspace_id=workspace_id, col_types=col_types, period=block, period_measure=measure,
        period_note_today=today)


def scope_inputs(conn_id: str, schema: Optional[str] = None) -> tuple[dict, Any]:
    """The findings and business profile for a scope — the connection's findings, and the
    SCHEMA's profile when one is named (Arc BR-5: a subscription and the Briefing tab share one
    snapshot only if they read the same scope)."""
    domain_data, profile = connection_inputs(conn_id)
    if schema:
        try:
            from aughor.business_profile import store as _pstore
            profile = _pstore.load(conn_id, schema) or profile
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "no profile for the schema; the connection's is used",
                     counter="briefing.period.scope_profile")
    return domain_data, profile


def connection_inputs(conn_id: str) -> tuple[dict, Any]:
    """The connection-wide scope's findings and profile — what a subscription (which has no
    schema) briefs on. The same dispatch the Briefing route makes for "no schema selected"."""
    from aughor.explorer import store as _s
    domain_data = (_s.get_aggregate_domain_findings(conn_id) if _s.schema_run_keys(conn_id)
                   else _s.get_domain_findings(conn_id))
    profile = None
    try:
        from aughor.business_profile import store as _pstore
        profile = _pstore.load(conn_id, None)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "no business profile for the period brief; it says no metric was measured",
                 counter="briefing.period.profile")
    return domain_data or {}, profile


# ── departure ──────────────────────────────────────────────────────────────────────────────

def sheet_lines(brief: dict, currency_code: Optional[str] = None) -> list[tuple[str, list[str]]]:
    """The brief as the sections a scheduled send departs with, in order: the measured
    headline metrics, what could not be measured (and why), the alerts and recorded findings
    it cited, then the narrative's paragraphs. Each line is judged at the gate on its own."""
    block = brief.get("period") or {}
    currency_code = currency_code or brief.get("currency_code")
    sections: list[tuple[str, list[str]]] = []
    measured = [metric_line(m, block, currency_code) for m in block.get("measured") or []]
    if measured:
        sections.append(("measured", measured))
    unmeasured = [f"{u['name']}: not measured — {u['reason']}" for u in block.get("unmeasured") or []]
    if unmeasured:
        sections.append(("unmeasured", unmeasured))
    cited = [(c.get("domain"), str(c.get("finding") or "").strip())
             for c in brief.get("citations") or [] if str(c.get("finding") or "").strip()]
    alerts = [text for domain, text in cited if domain == "Alerts"]
    if alerts:
        sections.append(("alerts", alerts))
    records = [text for domain, text in cited if domain not in ("Alerts", "Key Metrics")]
    if records:
        sections.append(("records", records))
    paragraphs = [p.strip() for p in str(brief.get("narrative") or "").split("\n\n") if p.strip()]
    if paragraphs:
        sections.append(("narrative", paragraphs))
    return sections


def fresh_measurement(conn_id: str, brief: dict, *,
                      runner: Optional[Callable[[], Any]] = None):
    """Law 1's basis for a send: the brief's own period queries RE-RUN now, never the cached
    values the brief was written from. A number that moved since the brief was built fails
    to ground and its line is held — which is the point."""
    from aughor.govern.departure import Measurement
    block = brief.get("period") or {}
    values: list[float] = []
    try:
        with (runner or (lambda: connection_runner(conn_id, cached=False)))() as (run_sql, _dialect):
            for m in block.get("measured") or []:
                _c, rows, error = run_sql(m["sql"])
                if error:
                    continue
                values.extend(v for v in (_value(r) for r in rows or []) if v is not None)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the period measurement could not be re-run at departure; its lines hold",
                 counter="briefing.period.remeasure")
    return Measurement(source=f"the {block.get('label', '').lower()} briefing's period queries",
                       values=values,
                       measured_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                       as_of=str(block.get("last_day") or ""),
                       definition="each headline metric's own trend query, cut to the period")
