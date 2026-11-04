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

from aughor.settling.learn import Observation, SettlingVerdict, rewrites_history, settle_lag

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
    kept = _merged(entry.get("observations") or [], measured_on, day_values)
    store.put(key, {**entry, "date_column": date_column, "observations": kept,
                    "last_measured_on": measured_on.isoformat()})
    return len(kept)


def record_old_readings(connection_id: str, table: str, measured_on: date, day_values: dict[str, float]) -> int:
    """File one reading of days far older than the horizon (`sampler.OLD_DAYS`). Kept apart from ``observations``: the
    verdict's horizon is the oldest age read, and a reading at age 180 would make theLook's lag floor 181."""
    store = _store()
    key = _key(connection_id, table)
    entry = store.get(key) or {}
    kept = _merged(entry.get("old_readings") or [], measured_on, day_values)
    store.put(key, {**entry, "old_readings": kept})
    return len(kept)


def _merged(readings: list, measured_on: date, day_values: dict[str, float]) -> list:
    floor = (measured_on - timedelta(days=KEEP_DAYS)).isoformat()
    stamp = measured_on.isoformat()
    # A re-reading replaces exactly the (day, measured_on) pairs it re-reads — never every
    # reading taken that day, or an incremental writer would erase its own earlier work.
    kept = [o for o in readings
            if str(o.get("measured_on", "")) >= floor
            and not (str(o.get("measured_on")) == stamp and str(o.get("day"))[:10] in day_values)]
    for day, value in sorted(day_values.items()):
        kept.append({"day": str(day)[:10], "measured_on": stamp, "value": float(value)})
    return kept


def observations(connection_id: str, table: str) -> list[Observation]:
    return _parsed((_store().get(_key(connection_id, table)) or {}).get("observations"))


def old_readings(connection_id: str, table: str) -> list[Observation]:
    return _parsed((_store().get(_key(connection_id, table)) or {}).get("old_readings"))


def _parsed(readings: Optional[list]) -> list[Observation]:
    out: list[Observation] = []
    for o in readings or []:
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
    return {t: settle_lag(observations(connection_id, t)) for t in _still_read(connection_id)}


def _still_read(connection_id: str) -> list[str]:
    """The tables whose readings still speak for this connection. Readings age out only when a table is written, so one the
    sampler has stopped reading (a metric's table took its place) would hold the connection's answer for good."""
    stamps = {t: str((_store().get(_key(connection_id, t)) or {}).get("last_measured_on") or "") for t in tables(connection_id)}
    newest = max(stamps.values(), default="")
    if not newest:
        return list(stamps)
    floor = (date.fromisoformat(newest) - timedelta(days=KEEP_DAYS)).isoformat()
    return [t for t, stamp in stamps.items() if not stamp or stamp >= floor]


def connection_lag(connection_id: str) -> dict:
    """The connection's lag and where it came from: ``{"days", "source", "still_moving",
    "horizon", "rewrites"}``. ``source`` is ``"learned"`` (every sampled table with enough evidence
    has settled), ``"beyond_horizon"`` (a table was still moving at the oldest age read, so
    ``days`` is a FLOOR — its horizon plus one — and the table is named), or ``None`` (no
    table has earned a verdict yet, ``days`` is None). ``rewrites`` names the tables still moving
    because the source keeps rewriting their old days (`learn.rewrites_history`).

    Before 2026-09-25 a table still moving at the horizon was simply left out of the max:
    theLook read "13 days, learned" while ``order_items`` — the table the headline amounts
    and returns come from — had not settled at 14 (Arc BR's survey, ROADMAP §3.48)."""
    out: dict = {"days": None, "source": None, "still_moving": [], "horizon": 0, "rewrites": []}
    if not connection_id:
        return out
    try:
        vs = verdicts(connection_id)
    except Exception:
        return out
    lags = [v.lag_days for v in vs.values() if v.lag_days is not None]
    # Old days moving says it directly, where recent days cannot: between a redraw and the next they hold still and read as
    # settled (measured in simulation, for a refresh every 3 days or more). A table is still moving whatever they show.
    rewriting = sorted(t for t in vs if rewrites_history(old_readings(connection_id, t)))
    moving = sorted({t for t, v in vs.items() if v.still_moving} | set(rewriting))
    floors = [vs[t].horizon_days + 1 for t in moving]
    if not lags and not floors:
        return out
    out["days"] = max(lags + floors)
    out["source"] = "beyond_horizon" if floors else "learned"
    out["still_moving"] = moving
    out["horizon"] = max((vs[t].horizon_days for t in moving or vs), default=0)
    out["rewrites"] = rewriting
    return out


def learned_lag_days(connection_id: str) -> Optional[int]:
    """The connection's lag: the LARGEST learned lag among its sampled tables — and, for a
    table still moving at the oldest age read, that age plus one (a floor, not a guess) — or
    None when no table has earned a verdict yet. Conservative by construction: a briefing
    that reads three tables waits for the slowest one, including one that has not stopped."""
    return connection_lag(connection_id)["days"]


def summary(connection_id: str) -> dict:
    """The door's read: every sampled table, its evidence and its verdict."""
    rows = []
    lag = connection_lag(connection_id)
    for t in tables(connection_id):
        entry = _store().get(_key(connection_id, t)) or {}
        obs = observations(connection_id, t)
        v = settle_lag(obs)
        reason = ("its old days keep being rewritten, so no age settles and no horizon will name a lag"
                  if t in lag["rewrites"] else v.reason)
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
            "verdict": {"lag_days": v.lag_days, "reason": reason,
                        "evidence_days": v.evidence_days, "horizon_days": v.horizon_days,
                        "still_moving": v.still_moving},
        })
    return {"connection_id": connection_id, "tables": rows,
            "learned_lag_days": lag["days"], "lag_source": lag["source"],
            "still_moving": lag["still_moving"], "rewrites": lag["rewrites"]}
