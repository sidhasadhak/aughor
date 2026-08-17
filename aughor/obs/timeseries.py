"""One time axis, shared by every panel on the Agent Ops surface.

Before this module every fold in the observability plane was **row**-windowed — `scan=5000`
meant "the last five thousand rows", so a quiet week and a busy hour drew the same width and
no two panels could be read against each other. The Overview showed it plainly: the pulse
sparkline bucketed by MINUTE over one hour, client-side, while the fleet table's row sparks
bucketed by HOUR over twenty-four, server-side, in the same table.

So a window is resolved ONCE, here, and everything downstream buckets through it:

    win = resolve_window("24h")          # or explicit from/to
    buckets = bucket_edges(win)          # [(start_iso, end_iso), …] — the x axis
    series  = job_series(win, group="charter")

Three rules this module exists to enforce:

**One format for time, everywhere.** ISO-8601 UTC with a ``T`` and an offset, exactly what
``ledger._now`` writes. SQLite's ``datetime('now')`` renders a SPACE instead of the ``T``,
and because these comparisons are lexical, ``'2026-08-17 21:00' < '2026-08-17T21:00'`` — a
mixed comparison does not error, it silently returns a wider window than asked for. That
cost a measurement in this very program.

**The bucket count is bounded.** A 30-day window at minute resolution is 43,200 points that
no chart can draw and no reader can use; ``resolve_window`` picks a bucket size that keeps
every range at a legible number of bars, and reports which it picked.

**Coverage rides with the answer.** ``event_series`` returns how many rows it scanned and
what share carried the grouping key, because a top-N built from 3% of the traffic is not a
top-N — and a chart of mostly-zero buckets should be readable as "nothing ran", never as
"the query is broken".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

#: Named ranges the UI offers, as (seconds, bucket_seconds). The bucket is chosen so each
#: range draws between 12 and 30 bars: dense enough to show shape, sparse enough to click.
RANGES: dict[str, tuple[int, int]] = {
    "1h":  (3600,        300),      # 12 × 5-minute
    "6h":  (6 * 3600,    1800),     # 12 × 30-minute
    "24h": (24 * 3600,   3600),     # 24 × hourly
    "7d":  (7 * 86400,   6 * 3600), # 28 × 6-hour
    "30d": (30 * 86400,  86400),    # 30 × daily
}

DEFAULT_RANGE = "24h"

#: Bucket sizes an explicit from/to may resolve to, smallest first.
_BUCKET_LADDER = (60, 300, 900, 1800, 3600, 6 * 3600, 12 * 3600, 86400, 7 * 86400)

#: Never draw more than this many buckets, whatever the caller asks for.
MAX_BUCKETS = 200


def now_iso() -> str:
    """The one clock. Matches ``ledger._now`` exactly — same format, same tz."""
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str) -> Optional[datetime]:
    """Lenient ISO parse that never raises. Accepts a trailing ``Z`` and a space where a
    ``T`` belongs (rows written by other tools), and always returns tz-aware UTC."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if len(text) > 10 and text[10] == " ":
        text = text[:10] + "T" + text[11:]
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Window:
    """A resolved time window: half-open ``[since, until)``, with its bucket size."""

    since: str
    until: str
    bucket_seconds: int
    range_key: str = ""

    @property
    def since_dt(self) -> datetime:
        return parse_iso(self.since) or datetime.now(timezone.utc)

    @property
    def until_dt(self) -> datetime:
        return parse_iso(self.until) or datetime.now(timezone.utc)

    @property
    def bucket_count(self) -> int:
        span = (self.until_dt - self.since_dt).total_seconds()
        return max(1, min(MAX_BUCKETS, int(round(span / max(1, self.bucket_seconds)))))

    def index_of(self, at: str) -> Optional[int]:
        """Which bucket ``at`` falls in, or None when it is outside the window."""
        dt = parse_iso(at)
        if dt is None:
            return None
        offset = (dt - self.since_dt).total_seconds()
        if offset < 0:
            return None
        idx = int(offset // self.bucket_seconds)
        return idx if idx < self.bucket_count else None

    def as_dict(self) -> dict:
        return {"since": self.since, "until": self.until,
                "bucket_seconds": self.bucket_seconds, "buckets": self.bucket_count,
                "range": self.range_key}


def _pick_bucket(span_seconds: float) -> int:
    """The smallest ladder step that keeps the bar count under MAX_BUCKETS."""
    for step in _BUCKET_LADDER:
        if span_seconds / step <= MAX_BUCKETS:
            return step
    return _BUCKET_LADDER[-1]


def resolve_window(range_key: str = "", *, since: str = "", until: str = "",
                   bucket_seconds: int = 0) -> Window:
    """Resolve a named range, or an explicit ``since``/``until``, into one Window.

    An unknown range name falls back to the default rather than raising: a stale bookmark
    carrying ``?range=90d`` should show the reader a day of data, not an error page.
    """
    end = parse_iso(until) or datetime.now(timezone.utc)
    start = parse_iso(since)
    if start is None:
        span, bucket = RANGES.get(range_key or DEFAULT_RANGE, RANGES[DEFAULT_RANGE])
        key = range_key if range_key in RANGES else DEFAULT_RANGE
        start = end - timedelta(seconds=span)
        return Window(start.isoformat(), end.isoformat(), bucket_seconds or bucket, key)
    if end <= start:
        end = start + timedelta(seconds=RANGES[DEFAULT_RANGE][0])
    span_s = (end - start).total_seconds()
    return Window(start.isoformat(), end.isoformat(),
                  bucket_seconds or _pick_bucket(span_s), range_key or "")


def bucket_edges(window: Window) -> list[str]:
    """The left edge of every bucket, as ISO strings — the chart's x axis."""
    start = window.since_dt
    return [(start + timedelta(seconds=i * window.bucket_seconds)).isoformat()
            for i in range(window.bucket_count)]


@dataclass
class Series:
    """One line/stack in a chart: a key, its per-bucket counts, and its total."""

    key: str
    label: str = ""
    values: list[float] = field(default_factory=list)
    total: float = 0.0
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label or self.key,
                "values": self.values, "total": round(self.total, 4), **self.meta}


def fold(rows: Iterable[dict], window: Window, *,
         key_of: Callable[[dict], str],
         at_of: Callable[[dict], str],
         value_of: Optional[Callable[[dict], float]] = None,
         labels: Optional[dict[str, str]] = None) -> list[Series]:
    """Bucket ``rows`` into one Series per distinct key. Pure; the read is the caller's.

    Rows outside the window are dropped rather than clamped into the edge buckets — a
    clamped row makes the first bar of every chart a spike that is not real.
    """
    n = window.bucket_count
    out: dict[str, Series] = {}
    for row in rows:
        idx = window.index_of(at_of(row) or "")
        if idx is None:
            continue
        key = key_of(row) or "(unattributed)"
        s = out.get(key)
        if s is None:
            s = out[key] = Series(key=key, label=(labels or {}).get(key, key),
                                  values=[0.0] * n)
        v = 1.0 if value_of is None else float(value_of(row) or 0.0)
        s.values[idx] += v
        s.total += v
    return sorted(out.values(), key=lambda s: s.total, reverse=True)


# ── the two store-backed folds ────────────────────────────────────────────────────

#: Job kinds no charter claims are RUNNERS, not agents (the automation engine's
#: every-minute evaluation tick, eval experiments). They are counted and shown, never
#: summed into the agent totals — measured 2026-08-17 the tick was 1,291 of 1,316 jobs in
#: twenty-four hours, so folding it in makes every agent metric a rounding error on a cron.
RUNNER_CHARTER_ID = "worker"


def job_rows(window: Window, *, limit: int = 5000) -> list[dict]:
    """Jobs created inside the window, newest first, with their charter resolved."""
    from aughor.kernel.agents import charter_for_kind
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().jobs_where(since=window.since, until=window.until, limit=limit)
    for r in rows:
        r["charter_id"] = charter_for_kind(r.get("kind")).id
    return rows


def is_runner(charter_id: str) -> bool:
    return (charter_id or "") == RUNNER_CHARTER_ID


def job_series(window: Window, *, include_runners: bool = False,
               limit: int = 5000) -> dict:
    """Runs per bucket, one series per charter — the Overview's activity chart.

    Returns the runner series separately rather than mixed in, so the caller decides
    whether to draw it and the agent totals never quietly include a cron tick.
    """
    from aughor.kernel.agents import get_charter
    rows = job_rows(window, limit=limit)
    agents = [r for r in rows if not is_runner(r.get("charter_id", ""))]
    runners = [r for r in rows if is_runner(r.get("charter_id", ""))]
    labels = {}
    for r in rows:
        cid = r.get("charter_id") or ""
        if cid and cid not in labels:
            ch = get_charter(cid)
            labels[cid] = ch.name if ch else cid
    series = fold(agents, window, key_of=lambda r: r.get("charter_id") or "",
                  at_of=lambda r: r.get("created_at") or "", labels=labels)
    runner_series = fold(runners, window, key_of=lambda r: r.get("charter_id") or "",
                         at_of=lambda r: r.get("created_at") or "", labels=labels)
    return {
        "window": window.as_dict(),
        "edges": bucket_edges(window),
        "series": [s.as_dict() for s in series],
        "runners": [s.as_dict() for s in runner_series],
        "agent_runs": sum(int(s.total) for s in series),
        "runner_runs": sum(int(s.total) for s in runner_series),
        "include_runners": bool(include_runners),
    }


#: How a session-log row yields its value on each groupable axis. `charter` and `job`
#: exist only because Migration 9 added the columns; before it, model spend could not be
#: attributed to the agent that spent it.
EVENT_GROUPS: dict[str, Callable[[dict], str]] = {
    "model": lambda e: e.get("model") or "",
    "provider": lambda e: e.get("provider") or "",
    "charter": lambda e: e.get("charter_id") or "",
    "agent": lambda e: e.get("agent_id") or "",
    "role": lambda e: e.get("role") or "",
    "kind": lambda e: e.get("kind") or "",
}

#: What a bucket counts. `calls` is rows; the rest are sums over reported values only —
#: a call whose backend omitted usage contributes nothing rather than a zero.
EVENT_MEASURES: dict[str, Optional[Callable[[dict], float]]] = {
    "calls": None,
    "tokens": lambda e: float(e.get("total_tokens") or 0),
    "prompt_tokens": lambda e: float(e.get("prompt_tokens") or 0),
    "duration_ms": lambda e: float(e.get("duration_ms") or 0),
}


def event_series(window: Window, *, group: str = "model", measure: str = "calls",
                 kind: Optional[str] = None, org_id: Optional[str] = None,
                 limit: int = 20000) -> dict:
    """Session events per bucket, one series per group value.

    Unknown group/measure names raise — silently substituting a default would answer a
    different question than the one asked, which is the one thing a usage page cannot do.
    """
    if group not in EVENT_GROUPS:
        raise ValueError(f"unknown group '{group}' — known: {sorted(EVENT_GROUPS)}")
    if measure not in EVENT_MEASURES:
        raise ValueError(f"unknown measure '{measure}' — known: {sorted(EVENT_MEASURES)}")
    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import LLM_CALL
    rows = Ledger.default().session_events(
        kind=kind if kind is not None else LLM_CALL, org_id=org_id,
        since=window.since, until=window.until, limit=limit)
    labels: dict[str, str] = {}
    if group == "charter":
        from aughor.kernel.agents import get_charter
        for r in rows:
            cid = r.get("charter_id") or ""
            if cid and cid not in labels:
                ch = get_charter(cid)
                labels[cid] = ch.name if ch else cid
    series = fold(rows, window, key_of=EVENT_GROUPS[group],
                  at_of=lambda e: e.get("at") or "",
                  value_of=EVENT_MEASURES[measure], labels=labels)
    attributed = sum(1 for r in rows if EVENT_GROUPS[group](r))
    return {
        "window": window.as_dict(),
        "edges": bucket_edges(window),
        "group": group,
        "measure": measure,
        "series": [s.as_dict() for s in series],
        "scanned": len(rows),
        # Coverage is part of the measurement: a top-N built from 3% of the traffic is
        # not a top-N. Stated per response so no caller has to remember to ask.
        "attributed": attributed,
        "coverage": round(attributed / len(rows), 3) if rows else None,
    }
