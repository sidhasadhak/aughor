"""Recovery + analytics over the ``task_history`` span table (flag ``obs.task_table``).

The read side of Rec 4 (2026-07-11 platform study): "SELECT over what the agent
actually did." The sink (``aughor.telemetry``) writes one row per node/tool span;
these helpers turn that exhaust into answers the eval harness and operators want:

- :func:`recover_run` / :func:`recover_sql` — the generated SQL and per-node
  latency of a run, recovered by querying the table instead of parsing logs or an
  MLflow trace. This is the eval-recovery leverage (Rec 4 · leverage #1).
- :func:`recent_runs` / :func:`slow_tasks` — the forensic surface ("why were
  yesterday's briefings slow?") that the ``aughor_ops`` self-investigation schema
  (Rec 4 · leverage #2) reads from.

Every helper degrades to empty when the flag is off / nothing has been logged —
never raises. Read-only: they never write.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from aughor.kernel.ledger import Ledger

# Span tasks whose ``input`` is a SQL statement. The executor emits ``sql.execute``
# / ``sql.execute.retry`` (aughor/sql/executor.py); the ``tool.sql`` alias covers
# any future taxonomy-normalised name. Matched case-sensitively against the stored
# task name.
_SQL_TASKS = ("sql.execute", "sql.execute.retry", "tool.sql")


def _is_sql_task(task: str) -> bool:
    return task in _SQL_TASKS or task.startswith("sql.") or task.startswith("tool.sql")


def _iso_span_ms(start_iso: str, end_iso: str) -> Optional[float]:
    """Wall-clock ms between two ISO-8601 timestamps, or None if either is
    unparseable (a non-error fallback, not a swallowed failure)."""
    from datetime import datetime
    try:
        delta = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
    except ValueError:
        return None
    return round(delta.total_seconds() * 1000, 1)


@dataclass
class RunTrace:
    """The recovered spans of one run (``trace_id``), newest-first as stored but
    exposed oldest-first for reading a run top-to-bottom."""

    trace_id: str
    spans: list[dict]

    @property
    def ordered(self) -> list[dict]:
        """Spans in execution order (by ``start_time``)."""
        return sorted(self.spans, key=lambda s: (s.get("start_time") or "", s.get("span_id") or ""))

    @property
    def sql_statements(self) -> list[str]:
        """Every SQL statement the run executed, in execution order — the
        eval-recovery payload (no log parsing)."""
        return [s["input"] for s in self.ordered
                if _is_sql_task(s.get("task", "")) and s.get("input")]

    @property
    def total_ms(self) -> float:
        """Wall-clock span of the run: last end minus first start, falling back to
        the summed root-span durations when timestamps are unusable."""
        starts = [s["start_time"] for s in self.spans if s.get("start_time")]
        ends = [s["end_time"] for s in self.spans if s.get("end_time")]
        if starts and ends:
            # ISO-8601 strings sort chronologically; span = max(end) - min(start).
            span = _iso_span_ms(min(starts), max(ends))
            if span is not None:
                return span
        return round(sum(float(s.get("duration_ms") or 0) for s in self.spans
                         if not s.get("parent_span_id")), 1)

    def latency_by_task(self) -> dict[str, float]:
        """Total ``duration_ms`` per task name — the per-node breakdown evals and
        forensics want (which stage dominated the run)."""
        out: dict[str, float] = {}
        for s in self.spans:
            out[s["task"]] = round(out.get(s["task"], 0.0) + float(s.get("duration_ms") or 0), 1)
        return out

    def errors(self) -> list[dict]:
        """Spans that recorded an error (``error_message`` set)."""
        return [s for s in self.ordered if s.get("error_message")]


def recover_run(trace_id: str, *, org_id: Optional[str] = None, limit: int = 2000) -> RunTrace:
    """All spans of one run, as a :class:`RunTrace`. Empty when the flag was off
    for that run (nothing logged)."""
    rows = Ledger.default().task_history(trace_id=trace_id, org_id=org_id, limit=limit)
    return RunTrace(trace_id=trace_id, spans=rows)


def recover_sql(trace_id: str, *, org_id: Optional[str] = None) -> list[str]:
    """Just the executed SQL of a run, in order — the eval-harness convenience."""
    return recover_run(trace_id, org_id=org_id).sql_statements


def recent_runs(*, org_id: Optional[str] = None, limit: int = 50, scan: int = 2000) -> list[dict]:
    """Distinct runs seen in the most recent ``scan`` spans, newest first: one
    ``{trace_id, spans, sql, errors, total_ms, started}`` summary each (up to
    ``limit``). The "what has the platform been doing" list."""
    rows = Ledger.default().task_history(org_id=org_id, limit=scan)
    order: list[str] = []
    agg: dict[str, dict] = {}
    for r in rows:  # rows are newest-first
        tid = r.get("trace_id")
        if not tid:
            continue
        a = agg.get(tid)
        if a is None:
            a = agg[tid] = {"trace_id": tid, "spans": 0, "sql": 0, "errors": 0,
                            "total_ms": 0.0, "started": r.get("start_time")}
            order.append(tid)
        a["spans"] += 1
        a["total_ms"] = round(a["total_ms"] + float(r.get("duration_ms") or 0), 1)
        if _is_sql_task(r.get("task", "")) and r.get("input"):
            a["sql"] += 1
        if r.get("error_message"):
            a["errors"] += 1
        # rows descend by start_time, so the last one seen for a trace is its earliest span
        if r.get("start_time"):
            a["started"] = r["start_time"]
    return [agg[t] for t in order[:limit]]


def slow_tasks(*, task_prefix: Optional[str] = None, org_id: Optional[str] = None,
               limit: int = 20, scan: int = 5000) -> list[dict]:
    """The slowest task names by mean ``duration_ms`` over the recent window —
    "why were yesterday's briefings slow?" as a ranking. ``task_prefix`` scopes to
    a family (e.g. ``sql.`` or ``briefing.``)."""
    rows = Ledger.default().task_history(org_id=org_id, task_prefix=task_prefix, limit=scan)
    agg: dict[str, dict] = {}
    for r in rows:
        t = r.get("task")
        if not t:
            continue
        a = agg.setdefault(t, {"task": t, "count": 0, "total_ms": 0.0, "max_ms": 0.0})
        d = float(r.get("duration_ms") or 0)
        a["count"] += 1
        a["total_ms"] = round(a["total_ms"] + d, 1)
        a["max_ms"] = max(a["max_ms"], d)
    for a in agg.values():
        a["mean_ms"] = round(a["total_ms"] / a["count"], 1) if a["count"] else 0.0
    return sorted(agg.values(), key=lambda a: a["mean_ms"], reverse=True)[:limit]
