"""A scheduled investigation knows what time it is — and what it said last time.

The model correction behind the theLook briefing incident (2026-09-05, measured):
a schedule-fired ``investigate`` effect handed the agent a bare question ("what
changed in the last day?") and nothing else. Two failure classes followed, on the
very first automation anyone pointed at a daily cadence:

* the agent chose the IN-PROGRESS day as its observation period (9 hours of data
  against a full prior day: "orders fell 97.5%");
* the source restated its own history between runs (theLook's generator rewrites
  its trailing days), and each run narrated the restatement as business change —
  "a 76% spike", every single morning, forever.

Neither is that automation's fault, and neither is fixable by editing that
automation. The model was missing two things every scheduled run should carry:

1. **A deterministic observation note** — code-written, from the run clock and the
   cron cadence: which period is COMPLETE and should be observed, which is partial
   and must not be. ``observation_lag_days`` on the effect config (default 1 = the
   last complete UTC day) is the one setting, for sources whose recent days are
   known to restate.
2. **The previous run's own report** — read back from the run history the engine
   already keeps, with one instruction: when current measurements contradict
   numbers previously reported for the same periods, say the source restates
   history instead of narrating the difference as change.

Everything here is pure or reads the existing run store; no model call, no new
loop, no new table. A non-scheduled automation composes NOTHING — its prompts stay
byte-identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

#: Bounds for ``observation_lag_days``. 1 = the last complete UTC day (the default
#: every calendar-day comparison should want); the cap keeps a typo from anchoring
#: a "daily" briefing a month in the past.
DEFAULT_LAG_DAYS = 1
MAX_LAG_DAYS = 30

#: How much of the previous report is quoted back. Summaries are a paragraph; the
#: cap only guards against something pathological riding the prompt.
_PREVIOUS_SUMMARY_CAP = 1200


def cadence_of(cron: str) -> str:
    """``daily`` | ``weekly`` | ``monthly`` from a 5-field cron, best-effort.

    A fixed day-of-month reads as monthly, a fixed day-of-week as weekly, anything
    else (including shapes this doesn't understand) as daily — the safest default,
    because a daily note about complete days is still TRUE under any cadence."""
    fields = (cron or "").split()
    if len(fields) != 5:
        return "daily"
    _minute, _hour, dom, _month, dow = fields
    if dom not in ("*", "?"):
        return "monthly"
    if dow not in ("*", "?"):
        return "weekly"
    return "daily"


def clamp_lag(raw) -> int:
    try:
        lag = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LAG_DAYS
    return max(1, min(MAX_LAG_DAYS, lag))


#: The periods a window can be cut for — the vocabulary brief subscriptions already speak
#: ("day" | "week"), extended by idea 3 (briefings by period) to the month and the year.
PERIODS: tuple[str, ...] = ("day", "week", "month", "year")

_CADENCE_PERIOD = {"daily": "day", "weekly": "week", "monthly": "month"}


@dataclass(frozen=True)
class PeriodWindow:
    """One complete period and the period it is compared with. ``end`` and
    ``previous_end`` are EXCLUSIVE (the day after the last day), so a window filters as
    ``start <= d < end`` on every dialect without a timezone-sensitive ``<=``.

    The comparison is chosen per period, not mechanically "the one before": a day is
    compared with the same weekday a week earlier, because most businesses run a weekly
    rhythm and a Monday against a Sunday is a calendar fact, not a business move."""
    period: str
    start: date
    end: date
    previous_start: date
    previous_end: date
    lag_days: int

    @property
    def last_day(self) -> date:
        return self.end - timedelta(days=1)

    def to_dict(self) -> dict:
        return {"period": self.period, "start": self.start.isoformat(),
                "last_day": self.last_day.isoformat(), "end": self.end.isoformat(),
                "previous_start": self.previous_start.isoformat(),
                "previous_last_day": (self.previous_end - timedelta(days=1)).isoformat(),
                "previous_end": self.previous_end.isoformat(), "lag_days": self.lag_days}


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:            # 29 Feb into a non-leap year
        return d.replace(year=d.year + years, day=28)


def complete_period(period: str, today: date, lag_days: int = DEFAULT_LAG_DAYS,
                    fiscal_start_month: int = 1) -> PeriodWindow:
    """The most recent COMPLETE ``period`` whose last day is no later than the anchor
    (``today - lag``: the newest day whose numbers are settled), and its comparison.

    A period is complete when its last day is on or before the anchor — so a monthly run
    on 1 October (lag 1, anchor 30 September) observes September. The rule this replaced
    took "the month before the anchor's month" and told that run to observe August,
    skipping the month that had just ended (measured 2026-09-23). The year is the FISCAL
    year when ``fiscal_start_month`` says so (org settings), otherwise the calendar year.
    Pure: no clock, no store."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}; got {period!r}")
    lag = clamp_lag(lag_days)
    anchor = today - timedelta(days=lag)
    if period == "day":
        start = anchor
        end = anchor + timedelta(days=1)
        return PeriodWindow(period, start, end, start - timedelta(days=7),
                            end - timedelta(days=7), lag)
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        if start + timedelta(days=6) > anchor:
            start -= timedelta(days=7)
        return PeriodWindow(period, start, start + timedelta(days=7),
                            start - timedelta(days=7), start, lag)
    if period == "month":
        next_day = anchor + timedelta(days=1)
        # the anchor's month is complete only when the anchor is its last day
        end = next_day.replace(day=1) if next_day.day == 1 else anchor.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
        previous_start = (start - timedelta(days=1)).replace(day=1)
        return PeriodWindow(period, start, end, previous_start, start, lag)
    month = fiscal_start_month if 1 <= int(fiscal_start_month or 1) <= 12 else 1
    # the fiscal year containing the anchor starts on the most recent 1st of `month`
    year_start = date(anchor.year, month, 1)
    if year_start > anchor:
        year_start = date(anchor.year - 1, month, 1)
    next_year_start = _add_years(year_start, 1)
    end = next_year_start if anchor + timedelta(days=1) == next_year_start else year_start
    start = _add_years(end, -1)
    return PeriodWindow(period, start, end, _add_years(start, -1), start, lag)


def observation_note(now: datetime, cron: str, lag_days: int = DEFAULT_LAG_DAYS) -> str:
    """The code-written sentence naming what a scheduled run should observe."""
    now = now.astimezone(timezone.utc)
    today: date = now.date()
    lag = clamp_lag(lag_days)
    cadence = cadence_of(cron)
    anchor = today - timedelta(days=lag)

    lines = [
        "[Scheduled-run context — written by code, not inferred]",
        f"This is a scheduled {cadence} run at {now.strftime('%Y-%m-%dT%H:%M')}Z.",
    ]
    if cadence == "weekly":
        week = complete_period(_CADENCE_PERIOD[cadence], today, lag)
        lines.append(
            f"Observe the most recent COMPLETE week: {week.start.isoformat()} to "
            f"{week.last_day.isoformat()} (UTC).")
    elif cadence == "monthly":
        month = complete_period(_CADENCE_PERIOD[cadence], today, lag)
        lines.append(
            f"Observe the most recent COMPLETE month: "
            f"{month.start.strftime('%Y-%m')} (UTC).")
    else:
        lines.append(
            f"Observe {anchor.isoformat()} (UTC), the most recent complete day"
            + ("" if lag == 1 else
               f" given this automation's observation lag of {lag} days — periods "
               "younger than that are configured as not yet reliable for this source")
            + ".")
    lines.append(
        f"Never treat the current, in-progress period (today is {today.isoformat()} "
        "UTC and it is partial by construction) as an observation period, and never "
        "compare a partial period against a complete one.")
    if lag > 1:
        # Without this the reader gets a correctly-lagged report that LOOKS stale: the
        # theLook briefing posted "On September 5th..." on September 8 with nothing
        # saying why, and the first thing its owner said was "today's date is wrong".
        lines.append(
            f"Say in the report which period you observed AND that it is {lag} days "
            f"behind today ({today.isoformat()} UTC), because this source restates its "
            "most recent days. A reader must never have to guess why the newest figure "
            "you quote is dated earlier than today — undated, a lagged report is "
            "indistinguishable from a broken one.")
    return "\n".join(lines)


def previous_report_note(automation_id: str) -> str:
    """The previous fired run's own investigate summary, with the restatement
    instruction — or '' when there is nothing to compare against.

    Read from the run history the engine already persists (`EffectOutcome.data`);
    no new state. Best-effort: an unreadable history degrades to no note, never to
    a failed run."""
    try:
        from aughor.automations.store import get_runs
        # outcomes= at the STORE, never a Python filter over the newest N rows: a daily
        # cron ticks once a minute, so the newest 25 rows are 25 minutes of `not_fired`
        # and the previous report sits ~1,440 rows behind them. Measured 2026-09-08 —
        # this note had returned '' on every production run since it shipped.
        for run in get_runs(automation_id=automation_id, outcomes=("fired",), limit=25):
            for eff in run.effects or []:
                data = getattr(eff, "data", None) or {}
                kind = getattr(eff, "kind", "")
                text = str(data.get("summary") or data.get("answer") or "").strip()
                if kind == "investigate" and text:
                    started = str(getattr(run, "started_at", "") or "")[:16]
                    return (
                        "[Previous scheduled report — for consistency checking]\n"
                        f"The previous run of this automation ({started}Z) reported:\n"
                        f"\"{text[:_PREVIOUS_SUMMARY_CAP]}\"\n"
                        "If your current measurements DISAGREE with numbers that report "
                        "states for the same periods, the SOURCE has restated its own "
                        "history — say that explicitly, with both values, instead of "
                        "narrating the difference as a business change.")
        return ""
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "previous-report grounding is best-effort; the run proceeds "
                      "without it", counter="automations.previous_report_note")
        return ""


def resolve_lag(effect_config: dict, learned_lag: Optional[int] = None) -> int:
    """The lag this dispatch observes at: a person's ``observation_lag_days`` on the step
    wins; otherwise the lag the platform LEARNED for the connection (idea 4 — the age after
    which a day's numbers stop moving, read off successive daily counts); otherwise the
    one-day default. theLook's 8 was set by hand on 2026-09-08 after a week of fake
    morning spikes; the learned value is what makes the next source not need a hand."""
    explicit = (effect_config or {}).get("observation_lag_days")
    if explicit is not None:
        return clamp_lag(explicit)
    if learned_lag:
        return clamp_lag(learned_lag)
    return clamp_lag(DEFAULT_LAG_DAYS)


def scheduled_grounding(automation, effect_config: dict,
                        now: Optional[datetime] = None,
                        learned_lag: Optional[int] = None) -> str:
    """The full grounding block for one scheduled investigate dispatch, or ''.

    '' whenever the automation carries no ``schedule`` condition — a webhook-, a
    monitor- or a manually-shaped automation keeps a byte-identical prompt. A
    manual "Run now" of a SCHEDULED automation still grounds: the person is
    rehearsing the scheduled behaviour, and the partial-day trap does not care who
    pressed the button. ``learned_lag`` is the connection's learned settling lag
    (`settling.learned_lag_days`), read only when the step sets no lag of its own."""
    cron = ""
    for cond in getattr(automation, "conditions", None) or []:
        if getattr(cond, "kind", "") == "schedule":
            cron = str((getattr(cond, "config", None) or {}).get("cron", ""))
            break
    else:
        return ""
    now = now or datetime.now(timezone.utc)
    lag = resolve_lag(effect_config, learned_lag)
    parts = [observation_note(now, cron, lag)]
    prev = previous_report_note(getattr(automation, "id", ""))
    if prev:
        parts.append(prev)
    return "\n\n".join(parts)
