"""Briefings by period — the pieces of idea 3 (IDEAS.md 3, ROADMAP §3.27) the range Briefing reads.

A day, week, month or year Briefing is the RANGE Briefing of that period's preset
(``aughor.briefing.ranges``, Arc BR-3): the period is computed, never inferred. What stays here is
what that path shares with the period Briefing it replaced:

* the window — the most recent COMPLETE period whose last day is settled for this source
  (``resolve_window``), and how it is said in ISO dates (``phrases``);
* the code-written note that tells the narrator which version it is writing (``period_note``);
* a measured metric as a sentence (``metric_line``), and the stored findings and monitor alerts
  recorded inside a window (``findings_in_window``, ``alert_findings``);
* the connection's matcache-first reader (``connection_runner``) and the scope's findings and
  profile (``scope_inputs``).

Everything here is deterministic.
"""
from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterator, Optional

from aughor.automations.temporal import PERIODS, PeriodWindow, complete_period, resolve_lag

#: A move smaller than this is reported as steady rather than as a change of that size: the
#: same threshold the standing brief uses to decide a trend is material.
STEADY_REL = 0.02


def refusal(period: str) -> Optional[str]:
    """Why a period briefing cannot be served, or None when it can. Spoken, never implied: a
    brief that silently fell back to the standing one would teach the reader that the
    standing brief IS this week's."""
    if period not in PERIODS:
        return f"period must be one of {', '.join(PERIODS)} (or 'history' for the standing brief)"
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


def period_note(block: dict, today: Optional[date] = None) -> str:
    """The code-written block that tells the narrator which version it is writing."""
    today = today or datetime.now(timezone.utc).date()
    label = block["label"].upper()
    withheld = block.get("compare_withheld")
    lines = [
        "[Briefing period — written by code, not inferred]",
        (f"This is the {label} briefing. It covers {block['covers']} (UTC). It is not compared with an "
         f"earlier period, because {withheld}: state no change against any earlier period."
         if withheld else
         f"This is the {label} briefing. It covers {block['covers']} (UTC) and compares it with "
         f"{block['compared_with']}."),
        f"Speak about that {block['period']} only. Every finding below is from inside it or is a "
        "measurement of it; do not describe anything as happening in it that the findings do not "
        "place there, and do not compare it with any period other than the one named.",
    ]
    lag = int(block.get("lag_days") or 1)
    if block.get("data_ended"):
        # Gap 38 (the Olist run): an unconditional settling sentence was written about a range eight
        # years settled. Data that ENDED has no lag; its figures are final, and that is what is said.
        lines.append(
            f"The data ended on {block.get('data_through')}, more than a month before today "
            f"({today.isoformat()}): this {block['period']} is read as if today were the day after it, "
            "and every figure in it is final. Say so once, plainly. Do not mention settling, late rows "
            "or confirming a figure later.")
    elif lag > 1 and block.get("lag_source") == "beyond_horizon":
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
    if block.get("unreachable"):
        lines.append(f"The data could not be reached for this {block['period']} ({block['unreachable']}), so "
                     "nothing was measured. State no figure for it; say once that the data could not be reached.")
    if block.get("unmeasured"):
        names = ", ".join(u["name"] for u in block["unmeasured"][:6])
        lines.append(f"Not measured for this {block['period']}: {names}. Do not state a value "
                     "for them.")
    return "\n".join(lines)


# ── the measurement ────────────────────────────────────────────────────────────────────────

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
    if m.get("compare_withheld"):
        # The earlier range starts before the data does: not "no rows", which would say it is empty.
        return f"{name} was {cur} in {block['covers']}; it is not compared, because {m['compare_withheld']}."
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


def _in_window(stamp: str, window: PeriodWindow) -> bool:
    try:
        d = date.fromisoformat(str(stamp or "")[:10])
    except ValueError:
        return False
    return window.start <= d < window.end


def alert_findings(conn_id: str, window: PeriodWindow) -> list[dict]:
    """Monitor alerts that fired inside the window, as dated candidate findings."""
    try:
        from aughor.monitors.recovery import RECOVERED
        from aughor.monitors.store import get_alerts
        # a recovery (TC-4) is no alert that fired: "the alert fired: back within its limit" would say the opposite
        alerts = [a for a in get_alerts(conn_id=conn_id, limit=500)
                  if _in_window(a.triggered_at, window) and getattr(a, "alert_on", "") != RECOVERED]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the period brief reads no alerts when the alert store is unreadable",
                 counter="briefing.period.alerts")
        return []
    return [{"id": f"alert::{a.id}", "domain": "Alerts", "angle": "Alert",
             "finding": f"On {a.triggered_at[:10]} the {a.monitor_name or 'monitor'} alert fired: "
                        f"{a.message}",
             "sql": _alert_sql(a.monitor_id), "confidence": 0.9 if a.severity == "critical" else 0.7,
             "novelty": 2, "dated": True}
            for a in alerts]


def _alert_sql(monitor_id: str) -> str:
    """The query the alert's monitor runs — its evidence in the brief; "" when the monitor is gone or resolves to none,
    and the brief then holds the alert back rather than cite it unbacked."""
    try:
        from aughor.monitors.runner import monitor_sql
        from aughor.monitors.store import get_monitor
        monitor = get_monitor(monitor_id)
        return (monitor_sql(monitor) or "") if monitor is not None else ""
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an alert's monitor could not be read; the brief holds the alert back",
                 counter="briefing.period.alert_sql")
        return ""


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
    # a finding that reads a table turned off for analysis is left out, as the Briefing route leaves it out
    from aughor.ontology.visibility import connection_exclusions, findings_left_out
    if connection_exclusions(conn_id):
        from aughor.trust.lineage_edges import dialect_for_connection
        domain_data = findings_left_out(conn_id, domain_data, dialect=dialect_for_connection(conn_id))[0]
    profile = None
    try:
        from aughor.business_profile import store as _pstore
        profile = _pstore.load(conn_id, None)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "no business profile for the period brief; it says no metric was measured",
                 counter="briefing.period.profile")
    return domain_data or {}, profile
