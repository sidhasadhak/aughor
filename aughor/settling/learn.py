"""Idea 4 · learn when a table's numbers stop changing — the learner, pure.

Many sources keep rewriting recent days: late rows arrive, backfills land. On theLook a
day's order count reads about eight times what the same day settles at a week later, and
until the lag was set to 8 by hand (2026-09-08) the daily briefing reported that settling
as a business spike every morning.

The platform can learn the lag itself, because it can read the same day's number on
successive days. This module does only the arithmetic: given observations of a day's value
at several AGES (measured_on − day), it finds the age after which the value stops moving.
It never invents: too few days, too few ages, or a day still moving at the edge of what
was observed all yield ``lag_days=None`` with the reason — a number nobody has checked
must not become a lag somebody schedules a briefing on.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

#: A day's value has settled once consecutive readings differ by less than this share.
DEFAULT_TOLERANCE = 0.01
#: A lag is learned from at least this many days, each read at least this many ages.
MIN_DAYS = 3
MIN_AGES = 3
#: Below this magnitude a relative tolerance is meaningless (a day with 3 rows moving to 4
#: is not "33% restated"); the absolute floor takes over.
MAGNITUDE_FLOOR = 50.0


@dataclass(frozen=True)
class Observation:
    day: date          # the calendar day the number is ABOUT
    measured_on: date  # the day it was read
    value: float

    @property
    def age(self) -> int:
        return (self.measured_on - self.day).days


@dataclass
class SettlingVerdict:
    #: The age (in days) after which a day's number no longer moves; None when not learned.
    lag_days: Optional[int]
    reason: str
    evidence_days: int = 0     # days that met the evidence bar
    horizon_days: int = 0      # the oldest age any day was read at
    tolerance: float = DEFAULT_TOLERANCE
    #: Enough evidence, and a day was still moving at the oldest age read: the lag is at
    #: least ``horizon_days + 1`` — unknown, but not small. Not the same as too little evidence.
    still_moving: bool = False

    @property
    def learned(self) -> bool:
        return self.lag_days is not None


def _by_day(observations: Iterable[Observation]) -> dict[date, dict[int, float]]:
    """day → {age → value}; a later reading at the same age replaces the earlier one."""
    out: dict[date, dict[int, float]] = {}
    for o in observations:
        if o.age <= 0:
            continue   # the day itself, or a future-dated row: not an age a reader can act on
        out.setdefault(o.day, {})[o.age] = float(o.value)
    return out


def _stable(a: float, b: float, tolerance: float) -> bool:
    return abs(b - a) <= tolerance * max(abs(a), MAGNITUDE_FLOOR)


def _settle_age(curve: dict[int, float], tolerance: float) -> Optional[int]:
    """The smallest observed age from which every later reading agrees with the one before
    it, or None when the day was still moving at the oldest age it was read at."""
    ages = sorted(curve)
    if len(ages) < 2:
        return None
    pairs = list(zip(ages, ages[1:]))
    stable_from = None
    for a, b in reversed(pairs):
        if _stable(curve[a], curve[b], tolerance):
            stable_from = a
        else:
            break
    return stable_from


def settle_lag(observations: Iterable[Observation], *, tolerance: float = DEFAULT_TOLERANCE,
               min_days: int = MIN_DAYS, min_ages: int = MIN_AGES) -> SettlingVerdict:
    """The lag a source needs before a day's number can be read as final.

    Conservative on purpose: the verdict is the LARGEST settle age across the qualifying
    days, so a source that usually settles in two days but sometimes takes five is read at
    five. A day still moving at the oldest age it was read at withholds the verdict — the
    horizon must grow before anyone can say where it stops.
    """
    curves = _by_day(observations)
    horizon = max((max(c) for c in curves.values()), default=0)
    qualifying = {d: c for d, c in curves.items() if len(c) >= min_ages}
    if len(qualifying) < min_days:
        return SettlingVerdict(
            None,
            f"insufficient evidence: {len(qualifying)} day{'s' if len(qualifying) != 1 else ''} "
            f"read at {min_ages}+ ages (needs {min_days})",
            evidence_days=len(qualifying), horizon_days=horizon, tolerance=tolerance)
    settle_ages: list[int] = []
    unsettled = 0
    for c in qualifying.values():
        age = _settle_age(c, tolerance)
        if age is None:
            unsettled += 1
        else:
            settle_ages.append(age)
    if unsettled:
        return SettlingVerdict(
            None,
            f"still moving at age {horizon} on {unsettled} of {len(qualifying)} days — "
            f"the observation horizon must grow before a lag can be named",
            evidence_days=len(qualifying), horizon_days=horizon, tolerance=tolerance,
            still_moving=True)
    lag = max(settle_ages)
    return SettlingVerdict(
        lag,
        f"learned from {len(qualifying)} days read at up to {horizon} ages: a day stops "
        f"moving {lag} day{'s' if lag != 1 else ''} after it ends",
        evidence_days=len(qualifying), horizon_days=horizon, tolerance=tolerance)
