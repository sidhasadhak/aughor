"""Each dataset's exploration program — what ran, what it found, what reopened it, what was read (2026-10-08).

The exploration principles (§2–§4, §11 item 4): the Explorer does three jobs, each on its own trigger —
learn the STRUCTURE when the schema changes, map the QUESTIONS until the dataset is mature, WATCH each
settled period over time. Deciding the next job needs a dataset's history: when each job last ran and
how many new findings it made (two runs that found almost nothing new is maturity), the named event
that reopened a mature dataset, the newest settled period its metrics were read for, and the failures
waiting to be retried.

Kept apart from the exploration state (`explorer/store.py`) on purpose: a running explorer holds that
state in memory and writes it back whole, so an event recorded beside it mid-run — a metric approved,
a figure that moved — would be overwritten by the run's next save. Keyed like that state: ``{conn}``
or ``{conn}__{schema}``.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from aughor.db.paths import state_dir
from aughor.util.json_store import KeyedJsonStore

#: How many runs a dataset's history keeps.
MAX_RUNS = 20
#: The jobs (`job` on a run record).
STRUCTURE, QUESTIONS, FULL = "structure", "questions", "full"
_lock = threading.Lock()


def _store() -> KeyedJsonStore:
    # Per call: `state_dir()` is the seam tests redirect (db/paths.py), as the exploration store does.
    return KeyedJsonStore(state_dir() / "exploration_program.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def key_for(conn_id: str, schema: Optional[str]) -> str:
    return f"{conn_id}__{schema}" if schema else conn_id


def load(key: str) -> dict:
    got = _store().get(key) or {}
    return {"runs": list(got.get("runs") or []), "reopened": got.get("reopened"),
            "watch": dict(got.get("watch") or {}), "failures": int(got.get("failures") or 0),
            "next_retry_at": got.get("next_retry_at"), "held": got.get("held"),
            "unanswered": list(got.get("unanswered") or []), "health": dict(got.get("health") or {}),
            "values": dict(got.get("values") or {})}


def _update(key: str, fn) -> dict:
    with _lock:
        data = load(key)
        fn(data)
        _store().put(key, data)
        return data


def record_run(key: str, *, job: str, outcome: str, new_findings: int, started_at: str = "",
               reason: str = "") -> None:
    """A run of one job ended: ``outcome`` complete | failed | stopped."""
    def _do(d: dict) -> None:
        d["runs"] = (d["runs"] + [{"job": job, "outcome": outcome, "new_findings": int(new_findings),
                                   "started_at": started_at, "ended_at": _now(), "reason": reason}])[-MAX_RUNS:]
        if outcome == "complete":
            d["failures"], d["next_retry_at"] = 0, None
    _update(key, _do)


def record_failure(key: str, next_retry_at: str) -> None:
    def _do(d: dict) -> None:
        d["failures"] = d["failures"] + 1
        d["next_retry_at"] = next_retry_at
    _update(key, _do)


def last_run(program: dict, *jobs: str) -> Optional[dict]:
    for r in reversed(program.get("runs") or []):
        if not jobs or r.get("job") in jobs:
            return r
    return None


def reopen(key: str, reason: str) -> None:
    """A named event reopened the dataset's questions (§3): a new table or column, a newly approved
    metric, a question it could not ground, a figure that really moved. The first reason holds
    until a questions run takes it."""
    def _do(d: dict) -> None:
        if not d.get("reopened"):
            d["reopened"] = {"at": _now(), "reason": str(reason)}
    _update(key, _do)


def take_reopen(key: str) -> Optional[dict]:
    """The pending reopen, cleared — a questions run is taking it."""
    taken: dict = {}

    def _do(d: dict) -> None:
        taken["r"] = d.get("reopened")
        d["reopened"] = None
    _update(key, _do)
    return taken.get("r")


def record_watch(key: str, grain: str, reading: dict) -> None:
    """The newest settled period of a metric grain was read (the watch job)."""
    def _do(d: dict) -> None:
        d["watch"][grain] = {**reading, "read_at": _now()}
    _update(key, _do)


def hold(key: str, why: str) -> None:
    """Say why the platform did not run a job it wanted to (a spent budget), until it next runs one."""
    def _do(d: dict) -> None:
        d["held"] = {"at": _now(), "why": str(why)}
    _update(key, _do)


def clear_hold(key: str) -> None:
    def _do(d: dict) -> None:
        d["held"] = None
    _update(key, _do)


def dataset_key(conn_id: str, schema: Optional[str]) -> str:
    """The program key a question asked against ``schema`` belongs to: the dataset's own key on a
    connection explored per dataset, else the connection's."""
    from aughor.explorer import store as expl_store
    if schema and expl_store.schema_run_keys(conn_id):
        return f"{conn_id}__{schema}"
    return conn_id


#: Questions a dataset could not answer that reopen its questions, within this many days (§3's event).
UNANSWERED_REOPEN = 2
UNANSWERED_DAYS = 7


def note_unanswered(key: str, why: str) -> bool:
    """A question asked of this dataset that it could not answer — the query failed, or an analytical
    question came back empty. Two in a week reopen the dataset's questions. Returns whether it reopened."""
    from datetime import timedelta
    reopened: dict = {}

    def _do(d: dict) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=UNANSWERED_DAYS)).isoformat()
        recent = [x for x in (d.get("unanswered") or []) if str(x.get("at") or "") >= cutoff]
        recent.append({"at": _now(), "why": str(why)[:200]})
        d["unanswered"] = recent[-20:]
        if len(recent) >= UNANSWERED_REOPEN and not d.get("reopened"):
            d["reopened"] = {"at": _now(), "reason": f"{len(recent)} questions it could not answer "
                                                     f"in the last {UNANSWERED_DAYS} days"}
            reopened["yes"] = True
    _update(key, _do)
    return bool(reopened)


def record_health(key: str, reading: dict) -> None:
    """A raw dataset's daily pipeline-health reading (`explorer/health.py`): per table, and what changed."""
    def _do(d: dict) -> None:
        d["health"] = {**reading, "read_at": _now()}
    _update(key, _do)


def record_values(key: str, values: dict, news: list[str]) -> None:
    """A business dataset's known dimension values, and the new ones the last reading found."""
    def _do(d: dict) -> None:
        d["values"] = {**values, "_read": {"read_at": _now(), "news": list(news)}}
    _update(key, _do)


def record_story(key: str, grain: str, story: dict) -> None:
    """The model-written explanation of a grain's newest move (`explorer/move_story.py`), or why it was withheld."""
    def _do(d: dict) -> None:
        if grain in d["watch"]:
            d["watch"][grain] = {**d["watch"][grain], "story": story}
    _update(key, _do)
