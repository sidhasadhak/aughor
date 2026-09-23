"""Idea 4 · the observations a day's number was read at, per table — and what they say.

One JSON store under the data home (`settling.json`), keyed ``connection:table``. Each entry
keeps the date column the counts were read on and the observations, capped to the last
`KEEP_DAYS` of readings so the file stays small (a table read once a day over a 14-day
horizon is ~14 rows per day). Written only by the sampler, inside the API process — one
writer per ``data/``.

The verdicts are computed on read from the observations, never stored: a stored lag would
be a number that stops being re-derived the day the source changes its habits.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from aughor.settling.learn import Observation, SettlingVerdict, settle_lag

#: Readings older than this are dropped on write; a lag is a property of the recent past.
KEEP_DAYS = 90


def _path() -> Path:
    from aughor.db.paths import state_dir
    return state_dir() / "settling.json"


def _store():
    from aughor.util.json_store import KeyedJsonStore
    return KeyedJsonStore(_path())


def _key(connection_id: str, table: str) -> str:
    return f"{connection_id}:{table}"


def record_observations(connection_id: str, table: str, date_column: str,
                        measured_on: date, day_values: dict[str, float]) -> int:
    """File one reading of each day's value, taken on ``measured_on``. Returns how many
    observations the entry now holds."""
    store = _store()
    key = _key(connection_id, table)
    entry = store.get(key) or {}
    floor = (measured_on - timedelta(days=KEEP_DAYS)).isoformat()
    stamp = measured_on.isoformat()
    # A re-reading replaces exactly the (day, measured_on) pairs it re-reads — never every
    # reading taken that day, or an incremental writer would erase its own earlier work.
    kept = [o for o in (entry.get("observations") or [])
            if str(o.get("measured_on", "")) >= floor
            and not (str(o.get("measured_on")) == stamp and str(o.get("day"))[:10] in day_values)]
    for day, value in sorted(day_values.items()):
        kept.append({"day": str(day)[:10], "measured_on": measured_on.isoformat(),
                     "value": float(value)})
    store.put(key, {"date_column": date_column, "observations": kept,
                    "last_measured_on": measured_on.isoformat()})
    return len(kept)


def observations(connection_id: str, table: str) -> list[Observation]:
    entry = _store().get(_key(connection_id, table)) or {}
    out: list[Observation] = []
    for o in entry.get("observations") or []:
        try:
            out.append(Observation(day=date.fromisoformat(str(o["day"])[:10]),
                                   measured_on=date.fromisoformat(str(o["measured_on"])[:10]),
                                   value=float(o["value"])))
        except (KeyError, TypeError, ValueError) as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a malformed observation is skipped, never read as a value",
                     counter="settling.malformed_observation")
            continue
    return out


def tables(connection_id: str) -> list[str]:
    prefix = f"{connection_id}:"
    data = _store().load() or {}
    return sorted(k[len(prefix):] for k in data if k.startswith(prefix))


def verdicts(connection_id: str) -> dict[str, SettlingVerdict]:
    return {t: settle_lag(observations(connection_id, t)) for t in tables(connection_id)}


def learned_lag_days(connection_id: str) -> Optional[int]:
    """The connection's lag: the LARGEST learned lag among its sampled tables, or None
    when no table has earned a verdict yet. Conservative by construction — a briefing that
    reads three tables waits for the slowest one."""
    if not connection_id:
        return None
    try:
        lags = [v.lag_days for v in verdicts(connection_id).values() if v.lag_days is not None]
    except Exception:
        return None
    return max(lags) if lags else None


def summary(connection_id: str) -> dict:
    """The door's read: every sampled table, its evidence and its verdict."""
    rows = []
    for t in tables(connection_id):
        entry = _store().get(_key(connection_id, t)) or {}
        obs = observations(connection_id, t)
        v = settle_lag(obs)
        last = str(entry.get("last_measured_on", ""))
        rows.append({
            "table": t,
            "date_column": entry.get("date_column", ""),
            "observations": len(obs),
            "days_observed": len({o.day for o in obs}),
            "readings": len({o.measured_on for o in obs}),
            "last_measured_on": last,
            # The newest reading, day by day: on a source that restates, the ramp is
            # visible in a single reading (young days high, older days settled).
            "latest": [{"day": o.day.isoformat(), "age": o.age, "value": o.value}
                       for o in sorted(obs, key=lambda o: o.day)
                       if o.measured_on.isoformat() == last],
            "verdict": {"lag_days": v.lag_days, "reason": v.reason,
                        "evidence_days": v.evidence_days, "horizon_days": v.horizon_days},
        })
    return {"connection_id": connection_id, "tables": rows,
            "learned_lag_days": learned_lag_days(connection_id)}
