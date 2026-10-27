"""Arc SV-2 — the retention rule, a port of Grist's ``shouldKeepSnapshots`` (``aughor/db/retention.py``).

The first half is Grist's own test file (grist-core ``test/server/lib/DocSnapshots.ts``, Apache-2.0), ported case for
case under Grist's caps: if the port drifted from the original, these are the strings that would say so. The second
half holds Aughor's caps — newest 5, 24 hours, 14 days, 8 weeks, nothing older, a labelled backup kept 30 days.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.db.retention import AUGHOR, GRIST, LABELLED_ONLY, Policy, should_keep


def _parse(entry: str) -> tuple[datetime, str | None]:
    """``"+2000-09-09 09:30Z | label"`` → (time, label) — the sign is the expectation, not part of the snapshot."""
    when, _, label = entry[1:].partition(" | ")
    return datetime.fromisoformat(when), (label or None)


def _check(times: list[str], policy: Policy = GRIST, **kw) -> None:
    """Grist's ``checkDecisions``: strip each sign, classify, and the signs must come back as they went in."""
    kept = should_keep([_parse(t) for t in times], policy, **kw)
    assert [("+" if k else "-") + t[1:] for t, k in zip(times, kept)] == times


def _remaining(snapshots: list[datetime], policy: Policy = GRIST) -> list[datetime]:
    return [s for s, k in zip(snapshots, should_keep([(s, None) for s in snapshots], policy)) if k]


def _max_gap(times: list[datetime]) -> timedelta:
    return max((a - b for a, b in zip(times, times[1:])), default=timedelta(0))


# ── Grist's tests, under Grist's caps ─────────────────────────────────────────────

def test_grist_a_10_day_history_at_minute_intervals():
    # `new Date(1600000000 + t * 60 * 1000)` — milliseconds, as JavaScript counts them.
    snaps = [datetime.fromtimestamp((1600000000 + t * 60 * 1000) / 1000, timezone.utc)
             for t in reversed(range(10 * 24 * 60))]
    remaining = _remaining(snaps)
    assert len(remaining) == 39                         # "Here's what it is in tests."
    assert _max_gap(remaining) <= timedelta(days=1)
    assert remaining[0] == snaps[0]
    assert remaining[-1] - snaps[-1] <= timedelta(days=1)


def test_grist_a_100_day_history_at_hourly_intervals():
    snaps = [datetime.fromtimestamp((1404040400 + t * 60 * 60 * 1000) / 1000, timezone.utc)
             for t in reversed(range(100 * 24))]
    remaining = _remaining(snaps)
    assert len(remaining) == 66
    assert _max_gap(remaining) <= timedelta(days=31)
    assert remaining[0] == snaps[0]
    assert remaining[-1] - snaps[-1] <= timedelta(days=31)


def test_grist_selects_versions_that_allow_gaps():
    times = [
        "+2000-09-09 09:30Z",  # most recent five versions will be kept
        "+2000-09-09 09:29Z",
        "+2000-09-09 09:28Z",
        "+2000-09-09 09:27Z",
        "+2000-09-09 09:26Z",
        "-2000-09-09 09:25Z",  # dropped since same hour as a kept version
        "+2000-09-09 08:59Z",  # kept since in a new hour - first use of this rule.
        "-2000-09-09 08:58Z",  # dropped since same hour as a kept version
    ]
    times += [f"+2000-09-08 {23 - i:02d}:15Z" for i in range(12)]   # twelve hours the day before
    times += [f"+2000-05-08 {23 - i:02d}:15Z" for i in range(12)]   # twelve hours many days ago
    times.append("-2000-05-08 00:15Z")                                # but that's it: 25 hours used
    _check(times)


def test_grist_matches_a_human_reading_of_the_rules():
    _check([
        # 2000-09-09 was a Saturday.
        "+2000-09-09 09:30Z", "+2000-09-09 09:29Z", "+2000-09-09 09:28Z", "+2000-09-09 09:27Z",
        "+2000-09-09 09:26Z", "-2000-09-09 09:25Z", "-2000-09-09 09:24Z", "-2000-09-09 09:23Z",
        "-2000-09-09 09:00Z",
        "+2000-09-09 08:59Z",  # because: new hour
        "-2000-09-09 08:58Z", "-2000-09-09 08:01Z",
        "+2000-09-09 07:30Z",  # because: new hour
        "-2000-09-09 07:20Z",
        "+2000-09-09 00:10Z",  # because: new hour
        "-2000-09-09 00:00Z",
        "+2000-09-08 23:59Z",  # because: new hour, day
        "-2000-09-08 23:50Z", "-2000-09-08 23:20Z",
        "+2000-09-08 18:50Z",  # because: new hour
        "-2000-09-08 18:20Z",
        "+2000-09-08 09:00Z", "+2000-09-08 08:00Z", "+2000-09-08 07:00Z", "+2000-09-08 00:30Z",
        "+2000-09-07 23:45Z",  # because: new hour, day
        "-2000-09-07 23:44Z",
        "+2000-09-07 05:44Z", "+2000-09-06 05:44Z",
        "+2000-09-03 12:00Z",  # because: new hour, day, isoWeek
        "+2000-09-03 06:00Z",
        "+2000-08-31 15:44Z",  # because: new hour, day, month
        "+2000-08-31 12:00Z", "+2000-08-22 15:44Z", "+2000-08-09 15:44Z", "+2000-08-08 07:44Z",
        "+2000-08-07 15:44Z", "+2000-08-06 15:44Z", "+2000-08-05 15:44Z", "+2000-08-01 15:44Z",
        "+2000-07-31 15:44Z", "+2000-07-30 15:44Z",
        "+2000-07-28 15:44Z",  # because: new day (the 25 hours are spent)
        "+2000-07-24 15:44Z", "+2000-07-23 15:44Z", "+2000-07-14 15:44Z", "+2000-07-11 15:44Z",
        "+2000-07-01 15:44Z", "+2000-06-28 15:44Z", "+2000-06-26 00:00Z", "+2000-06-19 00:00Z",
        "+2000-06-02 00:00Z", "+2000-05-25 00:00Z", "+2000-05-15 00:00Z", "+2000-05-05 00:00Z",
        "+2000-04-30 23:59Z", "+2000-04-15 00:00Z", "+2000-04-01 00:00Z", "+2000-03-10 12:00Z",
        "+2000-02-01 12:00Z",
        "+2000-01-20 12:00Z",  # because: new month (the 32 days are spent)
        "-2000-01-01 00:00Z",
        "+1999-12-31 23:59Z",  # because: new month, year
        "-1999-12-03 23:59Z",
        "+1999-11-20 23:59Z", "+1999-06-20 23:59Z",
        "-1999-06-01 00:00Z",
        "+1999-01-20 23:59Z",
        "-1999-01-05 00:00Z",
        "+1998-12-15 23:59Z", "+1998-06-15 23:59Z", "+1998-02-15 23:59Z",
        "-1998-02-03 23:59Z",
        "+1997-10-03 23:59Z", "+1997-09-12 23:59Z", "+1997-08-03 23:59Z", "+1997-05-05 23:59Z",
        "+1997-01-01 00:00Z", "+1996-01-01 00:00Z", "+1995-05-01 00:00Z", "+1995-01-01 00:00Z",
        "+1990-04-05 00:00Z", "+1990-01-02 00:00Z",
        "+1980-04-05 07:50Z",  # because: new month, year
        "-1980-04-05 07:40Z",
    ])


def test_grist_respects_the_timezone():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        five_ahead = zoneinfo.ZoneInfo("Etc/GMT-5")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("no timezone database on this machine")
    times = ["+2000-09-08 09:30Z", "+2000-09-08 09:29Z", "+2000-09-08 09:28Z", "+2000-09-08 09:27Z",
             "+2000-09-08 09:26Z", "+2000-09-08 08:26Z"]
    times += [f"+2000-09-07 {i:02d}:12Z" for i in range(23, -1, -1)]
    times += ["+2000-09-05 01:00Z", "+2000-09-04 23:00Z", "-2000-09-04 12:00Z"]
    _check(times)                                       # the decisions hold in UTC
    times[-2:] = ["-2000-09-04 23:00Z", "+2000-09-04 12:00Z"]
    _check(times, tz=five_ahead)                        # five hours ahead, the day boundary moves


def test_grist_favours_labelled_versions():
    _check(["+2000-09-08 09:30Z", "+2000-09-08 09:29Z", "+2000-09-08 09:28Z", "+2000-09-08 09:27Z",
            "+2000-09-08 09:26Z", "+2000-09-08 08:26Z", "+2000-09-08 08:25Z | save", "-2000-09-08 08:24Z",
            "+2000-09-08 08:23Z | me", "-2000-09-08 08:22Z"])


def test_grist_eventually_discards_labelled_versions():
    _check(["+2000-09-08 09:30Z", "+2000-09-08 09:29Z", "+2000-09-08 09:28Z", "+2000-09-08 09:27Z",
            "+2000-09-08 09:26Z", "+1990-09-09 08:25Z", "-1990-09-09 08:24Z | save"])


def test_grist_enforces_the_window():
    # Grist's window is `{count: 1, unit: "month"}`; a timedelta here, and August has 31 days.
    _check(["+2000-09-08 09:30Z", "+2000-09-08 09:29Z", "+2000-09-01 09:28Z", "-2000-08-08 09:27Z",
            "-2000-08-08 09:26Z", "-1990-09-09 08:25Z", "-1990-09-09 08:24Z"],
           Policy(keep=5, hour=25, day=32, iso_week=12, month=96, year=1000, label_days=32,
                  window=timedelta(days=31)))


# ── Aughor's caps ─────────────────────────────────────────────────────────────────

def test_aughor_keeps_the_newest_five_then_one_an_hour_day_and_week():
    # 2026-10-27 is a Tuesday; its ISO week began on Monday 2026-10-26.
    _check([
        "+2026-10-27 14:00Z",
        "+2026-10-27 13:59Z", "+2026-10-27 13:58Z", "+2026-10-27 13:57Z", "+2026-10-27 13:56Z",  # the newest five
        "+2026-10-27 13:40Z | before-restore",   # labelled: kept although its hour is used
        "-2026-10-27 13:30Z",                    # same hour as one kept
        "+2026-10-27 12:10Z",                    # a new hour
        "+2026-10-26 23:00Z",                    # a new hour and a new day
        "+2026-10-20 12:00Z",                    # a new hour, day and ISO week
        "+2026-09-01 15:00Z",                    # 55 days 23 hours back: inside the eight weeks
        "-2026-09-01 12:00Z",                    # 56 days 2 hours back: outside them
        "-2026-08-01 00:00Z",
    ], AUGHOR)


def test_aughor_keeps_24_hours_and_no_25th():
    newest = datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc)
    snaps = [(newest - timedelta(hours=h), None) for h in range(30)]
    kept = should_keep(snaps, AUGHOR)
    # 22:00 back to 2026-10-26 23:00 spend the 24 hours (the last of them opens a new day too); 22:00 the day
    # before is the 25th hour, in a day already kept.
    assert kept == [True] * 25 + [False] * 5


def test_aughor_keeps_a_labelled_backup_30_days_and_not_31():
    now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    labelled = [(now - timedelta(days=d), "v1-before-v12") for d in (1, 29, 31, 45)]
    assert should_keep(labelled, LABELLED_ONLY, now=now, protect_newest=False) == [True, True, False, False]


def test_a_copy_before_a_migration_goes_at_30_days_even_when_it_is_the_newest():
    """The live store is the current version, not its newest copy — so SV-1's series does not protect its newest."""
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    old = [(now - timedelta(days=40), "v1-before-v2")]
    assert should_keep(old, LABELLED_ONLY, now=now, protect_newest=False) == [False]
    assert should_keep(old, LABELLED_ONLY, now=now) == [True]          # Grist's guard, had it not been turned off


def test_the_window_is_measured_from_the_clock_when_now_is_given():
    """A quiet install takes no new backup, so measured from the newest a removal would last as long as the quiet."""
    newest = datetime(2026, 6, 1, tzinfo=timezone.utc)
    snaps = [(newest, None), (newest - timedelta(days=1), None), (newest - timedelta(days=2), None)]
    assert should_keep(snaps, AUGHOR) == [True, True, True]
    later = newest + timedelta(weeks=9)
    assert should_keep(snaps, AUGHOR, now=later) == [True, False, False]   # the newest is still the present state


def test_hourly_backups_pruned_every_hour_for_four_months_stay_bounded():
    """What the platform actually does: one backup an hour, pruned after each. The caps bound what survives."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    kept: list[datetime] = []
    for h in range(24 * 120):
        now = start + timedelta(hours=h)
        kept.insert(0, now)
        decisions = should_keep([(t, None) for t in kept], AUGHOR, now=now)
        kept = [t for t, k in zip(kept, decisions) if k]
    now = kept[0]
    assert len(kept) <= 5 + 24 + 14 + 8
    assert now - kept[-1] <= timedelta(weeks=8), "nothing older than eight weeks"
    for hours_back in range(24):                       # one in each of the last 24 hours
        assert any(now - timedelta(hours=hours_back + 1) < t <= now - timedelta(hours=hours_back) for t in kept)
    for days_back in range(1, 14):                     # one on each of the last 14 days
        day = (now - timedelta(days=days_back)).date()
        assert any(t.date() == day for t in kept), day
    for weeks_back in range(1, 7):                     # one in each of the last weeks the window holds
        week = (now - timedelta(weeks=weeks_back)).isocalendar()[:2]
        assert any(t.isocalendar()[:2] == week for t in kept), week


def test_nothing_in_nothing_out():
    assert should_keep([], AUGHOR) == []
