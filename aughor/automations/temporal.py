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
        # the last complete Mon–Sun week strictly before the anchor's week
        week_start = anchor - timedelta(days=anchor.weekday())
        if week_start + timedelta(days=6) > anchor:
            week_start -= timedelta(days=7)
        lines.append(
            f"Observe the most recent COMPLETE week: {week_start.isoformat()} to "
            f"{(week_start + timedelta(days=6)).isoformat()} (UTC).")
    elif cadence == "monthly":
        month_end = anchor.replace(day=1) - timedelta(days=1)
        lines.append(
            f"Observe the most recent COMPLETE month: "
            f"{month_end.strftime('%Y-%m')} (UTC).")
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
    return "\n".join(lines)


def previous_report_note(automation_id: str) -> str:
    """The previous fired run's own investigate summary, with the restatement
    instruction — or '' when there is nothing to compare against.

    Read from the run history the engine already persists (`EffectOutcome.data`);
    no new state. Best-effort: an unreadable history degrades to no note, never to
    a failed run."""
    try:
        from aughor.automations.store import get_runs
        for run in get_runs(automation_id=automation_id, limit=25):
            if run.outcome != "fired":
                continue
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


def scheduled_grounding(automation, effect_config: dict,
                        now: Optional[datetime] = None) -> str:
    """The full grounding block for one scheduled investigate dispatch, or ''.

    '' whenever the automation carries no ``schedule`` condition — a webhook-, a
    monitor- or a manually-shaped automation keeps a byte-identical prompt. A
    manual "Run now" of a SCHEDULED automation still grounds: the person is
    rehearsing the scheduled behaviour, and the partial-day trap does not care who
    pressed the button."""
    cron = ""
    for cond in getattr(automation, "conditions", None) or []:
        if getattr(cond, "kind", "") == "schedule":
            cron = str((getattr(cond, "config", None) or {}).get("cron", ""))
            break
    else:
        return ""
    now = now or datetime.now(timezone.utc)
    lag = clamp_lag((effect_config or {}).get("observation_lag_days",
                                              DEFAULT_LAG_DAYS))
    parts = [observation_note(now, cron, lag)]
    prev = previous_report_note(getattr(automation, "id", ""))
    if prev:
        parts.append(prev)
    return "\n\n".join(parts)
