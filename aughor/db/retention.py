"""Which backups to keep — a port of Grist's ``shouldKeepSnapshots`` (Arc SV-2, ROADMAP §3.63).

Ported from grist-core, ``app/server/lib/DocSnapshots.ts`` (``shouldKeepSnapshots`` and ``updateAndCheckRange``),
Copyright Grist Labs, licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
Changes from the original: the caps are a ``Policy`` argument rather than environment variables, the window is a
``timedelta`` rather than a count of calendar units, and ``now`` and ``protect_newest`` are added (below). Its tests are
ported in ``tests/unit/test_backups_retention.py`` as the same ``+t1 -t2`` strings.

The rule, read from the newest backup to the oldest: keep the newest ``keep``; keep the newest backup in each distinct
hour, day, ISO week (Monday first), month and year until that range has kept its cap; keep a labelled backup for
``label_days``; drop anything further back than ``window``. One backup can use several ranges at once — Grist's own
comment says other variations "have results that feel counter-intuitive". The newest is always kept.

Aughor's caps (decided 2026-10-27, §3.63): the newest 5, 24 hours, 14 days, 8 weeks, no months, no years, nothing
older than 8 weeks, and a labelled backup — a copy taken before a migration (SV-1) or before a restore — kept 30 days.
So a removal is gone from every backup within eight weeks. Grist's caps keep monthly backups for 8 years and yearly
ones for 1,000, because a Grist document's history is its product; here a backup outliving a removal is the cost.

Two additions, each off by default so Grist's own tests run unchanged:

* ``now`` — Grist measures the window and a label's age from the newest snapshot. Measured that way, a quiet install
  (no change, so no new backup) would keep a removal for as long as it stays quiet; ``now`` measures from the clock.
* ``protect_newest`` — Grist always keeps the newest, because it is the document's current version. SV-1's copies
  before a migration are not anybody's current version (the live store is), so their series turns it off and each one
  goes at 30 days.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional, Sequence


@dataclass(frozen=True)
class Policy:
    """How many backups each rule may keep."""
    keep: int = 5                       # the newest N, whatever their times
    hour: int = 24                      # distinct hours
    day: int = 14                       # distinct days
    iso_week: int = 8                   # distinct ISO weeks
    month: int = 0                      # distinct months
    year: int = 0                       # distinct years
    label_days: int = 30                # a labelled backup is kept this long
    window: Optional[timedelta] = timedelta(weeks=8)   # nothing further back than this


#: Grist's defaults (``GRIST_SNAPSHOT_KEEP`` and ``GRIST_SNAPSHOT_TIME_CAP`` unset), for the ported tests.
GRIST = Policy(keep=5, hour=25, day=32, iso_week=12, month=96, year=1000, label_days=32, window=None)

#: Aughor's, decided 2026-10-27.
AUGHOR = Policy()

#: SV-1's copies before a migration: kept for their label's 30 days and nothing else.
LABELLED_ONLY = Policy(keep=0, hour=0, day=0, iso_week=0, month=0, year=0, label_days=30, window=None)


def _key(t: datetime, rng: str) -> tuple:
    """The calendar range ``t`` falls in — two times in the same range have the same key (moment's ``isSame``)."""
    if rng == "hour":
        return (t.year, t.month, t.day, t.hour)
    if rng == "day":
        return (t.year, t.month, t.day)
    if rng == "isoWeek":
        iso = t.isocalendar()
        return (iso[0], iso[1])
    if rng == "month":
        return (t.year, t.month)
    return (t.year,)


class _Bucket:
    __slots__ = ("range", "prev", "usage", "cap")

    def __init__(self, rng: str, prev: datetime, cap: int):
        self.range, self.prev, self.usage, self.cap = rng, prev, 0, cap

    def update_and_check(self, t: datetime) -> bool:
        """Grist's ``updateAndCheckRange``: true, and ``t`` remembered, when ``t`` opens a new range and the bucket has
        kept fewer than its cap."""
        if self.usage < self.cap and _key(t, self.range) != _key(self.prev, self.range):
            self.prev = t
            self.usage += 1
            return True
        return False


def should_keep(snapshots: Sequence[tuple[datetime, Optional[str]]], policy: Policy = AUGHOR, *,
                tz: Optional[tzinfo] = None, now: Optional[datetime] = None,
                protect_newest: bool = True) -> list[bool]:
    """For each ``(time, label)`` — newest first, as Grist expects — whether to keep it.

    ``tz`` is the calendar ranges are counted in (UTC by default). ``now``, when given, is what the window and a label's
    age are measured from; otherwise the newest snapshot, as Grist does."""
    if not snapshots:
        return []
    zone = tz or timezone.utc
    start = snapshots[0][0].astimezone(zone)
    ref = now.astimezone(zone) if now is not None else start
    buckets = [_Bucket("hour", start, policy.hour), _Bucket("day", start, policy.day),
               _Bucket("isoWeek", start, policy.iso_week), _Bucket("month", start, policy.month),
               _Bucket("year", start, policy.year)]
    out: list[bool] = []
    for index, (when, label) in enumerate(snapshots):
        # Just to make extra sure we don't delete everything (Grist's comment).
        if index == 0 and protect_newest:
            out.append(True)
            continue
        date = when.astimezone(zone)
        if policy.window is not None and ref - date > policy.window:
            out.append(False)
            continue
        keep = index < policy.keep
        for bucket in buckets:              # every bucket is consulted: one backup may use several ranges
            if bucket.update_and_check(date):
                keep = True
        # moment's `diff(…, "days") < 32` truncates toward zero, which is a plain `< 32 days`.
        if label and ref - date < timedelta(days=policy.label_days):
            keep = True
        out.append(keep)
    return out
