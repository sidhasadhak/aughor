"""Arc TC, TC-5 — search the lines every run wrote, across runs (``GET /obs/logs``).

A run's lines were readable one trace at a time (``GET /traces/{id}/logs``): the kernel journal's
state transitions and, above all, its *tolerated errors* — failures deliberately swallowed so the
run could go on, invisible in the waterfall because the span they happened in succeeded. Finding
the same swallowed error across a week of runs meant opening the runs one by one. This reads the
same rows across runs: **no new store and no copy of the lines** — the journal's own ``events``
rows that carry a run's trace id, newest first, from a cursor.

What a search says about itself, because a search that hides its reach is a claim about all of
history nobody checked: the window it was asked for (thirty days), how many runs and lines that
window holds, and the oldest line actually kept in it — the journal sweeps some kinds sooner
(``job.state`` and ``automation.run`` after two days by default), so the oldest line kept can be
much younger than the window, and the answer says so rather than implying thirty days were read.

The level is read from the line, never stored: ``error`` — the line records a failure (a job that
failed, a step or tick that did not do its work); ``warning`` — a failure the run survived (a
tolerated error) or a job cut off by a restart; ``info`` — everything else. The kind of run is the
kind of the job the line was written under, and ``request`` for a line written outside any job (a
quick answer, answered at the door).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

#: The window a search reads, in days.
SEARCH_DAYS = 30
#: The most lines one page returns.
PAGE_MAX = 200
#: Rows read per batch, and the most rows one page examines before it returns what it found with
#: a cursor to go on from. A text match is pushed to the store; level and kind of run are read
#: from each row, so a narrow filter over a busy journal may need several pages.
BATCH = 500
SCAN_BUDGET = 20_000
LEVELS: tuple[str, ...] = ("error", "warning", "info")
#: The kind of run of a line written outside any job.
REQUEST = "request"

_FAILED_WORDS = frozenset({"failed", "error", "dispatch_error", "invalid_params"})


class BadCursor(ValueError):
    """A cursor this module did not write, or one that has been altered."""


def level_of(line: dict) -> str:
    """``error`` · ``warning`` · ``info``, read from the line as it was kept."""
    kind = str(line.get("kind") or "")
    p = line.get("payload") if isinstance(line.get("payload"), dict) else {}
    if kind == "error.tolerated" or kind == "job.orphaned":
        return "warning"
    state = str(p.get("state") or "").upper()
    if state == "FAILED" or p.get("ok") is False:
        return "error"
    if str(p.get("outcome") or "").lower() in _FAILED_WORDS or str(p.get("status") or "").lower() in _FAILED_WORDS:
        return "error"
    if state == "INTERRUPTED":
        return "warning"
    return "info"


def encode_cursor(seq: int, since: str) -> str:
    raw = json.dumps({"s": int(seq), "f": since}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        pad = "=" * (-len(cursor) % 4)
        d = json.loads(base64.urlsafe_b64decode(cursor + pad).decode())
        return int(d["s"]), str(d["f"])
    except Exception as exc:
        raise BadCursor("this cursor was not written by the log search; start again without one") from exc


def _kept_sooner() -> dict:
    """The kinds the journal sweeps before the window ends, and after how many days — asked of
    the sweep's own settings, never restated here."""
    from aughor.kernel.ledger import events_swept_sooner
    kinds, days = events_swept_sooner()
    return {"kinds": list(kinds), "keep_days": days} if kinds and days else {}


def search(*, q: str = "", level: Optional[str] = None, run_kind: Optional[str] = None,
           cursor: Optional[str] = None, limit: int = 50, org_id: Optional[str] = None,
           now: Optional[datetime] = None) -> dict:
    """One page of run lines matching the words, level and kind of run, newest first.

    ``next_cursor`` is set when there may be more — the page filled, or it examined its budget
    of rows first (``stopped_early`` says which); ``None`` means the window is exhausted."""
    from aughor.kernel.ledger import Ledger

    if level and level not in LEVELS:
        raise ValueError(f"unknown level {level!r} — use one of {list(LEVELS)}")
    limit = max(1, min(int(limit), PAGE_MAX))
    before: Optional[int] = None
    if cursor:
        before, since = decode_cursor(cursor)
    else:
        since = ((now or datetime.now(timezone.utc)) - timedelta(days=SEARCH_DAYS)
                 ).strftime("%Y-%m-%dT%H:%M:%S")
    ledger = Ledger.default()
    text = (q or "").strip()

    kinds_of_jobs: dict[str, str] = {}

    def run_kind_of(job_id: Any) -> str:
        if not job_id:
            return REQUEST
        jid = str(job_id)
        if jid not in kinds_of_jobs:
            job = ledger.job_get(jid)
            kinds_of_jobs[jid] = str((job or {}).get("kind") or "") or "unknown"
        return kinds_of_jobs[jid]

    found: list[dict] = []
    examined = 0
    last_seq: Optional[int] = None
    exhausted = False
    while len(found) < limit and examined < SCAN_BUDGET:
        want = min(BATCH, SCAN_BUDGET - examined)
        rows = ledger.run_lines(since=since, before_seq=before, text=text, org_id=org_id, limit=want)
        used = 0
        for r in rows:
            used += 1
            last_seq = before = int(r["seq"])
            lvl = level_of(r)
            kind_of_run = run_kind_of(r.get("job_id"))
            if (level and lvl != level) or (run_kind and kind_of_run != run_kind):
                continue
            found.append(_line(r, lvl, kind_of_run))
            if len(found) >= limit:
                break
        examined += used
        if len(rows) < want and used == len(rows):
            exhausted = True        # the store ran out, and every row it gave was read
            break

    extent = ledger.run_lines_extent(since=since, org_id=org_id)
    run_kinds = sorted({k or REQUEST for k in extent["run_kinds"]})
    stopped_early = not exhausted and len(found) < limit
    out = {
        "lines": found,
        "count": len(found),
        "next_cursor": None if exhausted or last_seq is None else encode_cursor(last_seq, since),
        "stopped_early": stopped_early,
        "examined": examined,
        "searched": {
            "window_days": SEARCH_DAYS,
            "since": since,
            "runs": extent["runs"],
            "lines": extent["lines"],
            "oldest_line_at": extent["oldest_at"],
        },
        "levels": list(LEVELS),
        "run_kinds": run_kinds,
    }
    sooner = _kept_sooner()
    if sooner:
        out["searched"]["kept_sooner"] = sooner
    if stopped_early:
        out["note"] = (f"examined {examined:,} lines without filling the page; "
                       "the cursor goes on from the last line examined")
    return out


def _line(r: dict, lvl: str, kind_of_run: str) -> dict:
    """A line as ``/traces/{id}/logs`` serves it, with its run, level and kind of run."""
    payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    tolerated = r.get("kind") == "error.tolerated"
    return {
        "at": r.get("at"), "seq": r.get("seq"), "kind": r.get("kind"),
        "trace_id": r.get("trace_id"), "job_id": r.get("job_id") or None,
        "conn_id": r.get("conn_id") or None,
        "level": lvl, "run_kind": kind_of_run,
        "tolerated": tolerated,
        "error": payload.get("error") if tolerated else None,
        "reason": payload.get("reason") if tolerated else None,
        "counter": payload.get("counter") if tolerated else None,
        "payload": None if tolerated else r.get("payload"),
    }
