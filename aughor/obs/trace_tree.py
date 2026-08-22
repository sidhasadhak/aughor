"""VA-5 — one run laid out on a time axis: the waterfall and the flow.

The span tree that existed before this module answered "what nested inside what", and it
answered it only for rows that carry a `span_id`. Measured on a real store, that excludes
the richest rows we have: **2,506 `llm_call` events, every one with a duration and 2,402
with token counts, and not one with a span id.** A waterfall of a run that omits every
model call is a waterfall of the run's plumbing.

So the timeline is assembled at READ time from everything the run recorded, not only from
what happened to be stamped. This is the same choice the fleet chart made when write-time
attribution turned out to be empty for all history: derive it on read and it is complete
back to the first row; stamp it on write and it is complete only going forward, which for
a debugging surface means it is empty exactly when you need it.

What a laid-out node carries beyond the raw row:

- ``offset_ms`` — where the bar starts, relative to the trace's first event. Without it a
  waterfall cannot be drawn at all; with it, the shape of a run is visible at a glance.
- ``gap_ms`` — dead time since the previous node ended, per node, for the label drawn
  between two bars. It is a SEQUENTIAL reading, and summing it is wrong the moment a run
  does anything in parallel: on a real 157-node trace, 53 nodes start before the previous
  ends, and the naive sum claimed 386.5s of dead time against a true 311.9s. The aggregate
  therefore ships as ``busy_ms`` / ``idle_ms`` / ``wall_ms`` over the UNION of intervals,
  with ``concurrent_nodes`` naming why the two differ.
- ``usage`` — prompt / completion / total, on the node, because "which call spent the
  tokens" is the first question anyone asks of a slow run.
- ``depth`` — nesting from ``parent_span_id`` where it exists, 0 where it does not. Not
  invented: an event with no parent is drawn at the root, and the module never fabricates a
  hierarchy the data does not support.
- ``critical`` — on the longest single node. A humble stand-in for a true critical path,
  and named narrowly so nobody reads more into it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

#: Event kinds that are model calls. They carry duration and usage but no span id.
_MODEL_KINDS = {"llm_call"}
#: Kinds that bracket a run rather than doing work inside it.
_FRAME_KINDS = {"user_request", "final_response"}


def _parse(ts: object) -> Optional[datetime]:
    """ISO-8601 → datetime, tolerantly.

    ⚠️ These strings are written with a ``T`` separator; SQLite's own ``datetime('now')``
    renders a space, and the two compare wrong lexically. Parsing rather than comparing
    strings is how this module stays out of that trap.
    """
    if not ts:
        return None
    s = str(ts).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _ms_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() * 1000.0, 3)


def _usage(row: dict) -> Optional[dict]:
    p, c, t = row.get("prompt_tokens"), row.get("completion_tokens"), row.get("total_tokens")
    if p is None and c is None and t is None:
        return None
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": t}


def _node_kind(row: dict) -> str:
    kind = row.get("kind") or ""
    if kind in _MODEL_KINDS:
        return "model"
    if kind in _FRAME_KINDS:
        return "frame"
    if kind == "execution_error":
        return "error"
    if row.get("span_id"):
        return (row.get("payload") or {}).get("span_kind") or "tool"
    return "event"


def build_timeline(events: Iterable[dict]) -> dict:
    """Lay a run's events out on a time axis. Pure — the read is the caller's.

    Tool spans are paired: a `tool_call` opens the node and its `tool_call_result` closes
    it, carrying the outcome. Everything else contributes one node. Ordering is by `seq`,
    which is the store's own monotonic write order and therefore the only ordering that
    cannot disagree with itself when two events share a timestamp.
    """
    rows = sorted(events, key=lambda r: r.get("seq") or 0)
    if not rows:
        return {"nodes": [], "started_at": None, "total_ms": None,
                "span_count": 0, "usage": {}, "gap_ms": 0.0}

    t0 = next((_parse(r.get("at")) for r in rows if _parse(r.get("at"))), None)

    by_span: dict[str, dict] = {}
    nodes: list[dict] = []

    for r in rows:
        sid = r.get("span_id")
        kind = r.get("kind") or ""

        # A result row closes the node its call opened, rather than adding a second one.
        if sid and kind == "tool_call_result" and sid in by_span:
            node = by_span[sid]
            node["ok"] = r.get("ok")
            node["error_class"] = r.get("error_class")
            node["row_count"] = r.get("row_count")
            node["duration_ms"] = r.get("duration_ms") or node.get("duration_ms")
            node["ended_at"] = r.get("at")
            if node.get("usage") is None:
                node["usage"] = _usage(r)
            continue

        at = _parse(r.get("at"))
        node = {
            "id": sid or f"seq-{r.get('seq')}",
            "seq": r.get("seq"),
            "span_id": sid,
            "parent_span_id": r.get("parent_span_id"),
            "name": r.get("name") or kind,
            "event_kind": kind,
            "kind": _node_kind(r),
            "at": r.get("at"),
            "ended_at": None,
            "offset_ms": _ms_between(t0, at) if t0 else None,
            "duration_ms": r.get("duration_ms"),
            "ok": r.get("ok"),
            "error_class": r.get("error_class"),
            "row_count": r.get("row_count"),
            "model": r.get("model"),
            "provider": r.get("provider"),
            "role": r.get("role"),
            "fallback": r.get("fallback"),
            "usage": _usage(r),
            "depth": 0,
            "gap_ms": None,
            "critical": False,
        }
        if sid:
            by_span[sid] = node
        nodes.append(node)

    # Depth from real parentage only. An event with no parent sits at the root; this
    # module does not invent a hierarchy the data cannot support.
    def _depth(node: dict, seen: frozenset = frozenset()) -> int:
        pid = node.get("parent_span_id")
        if not pid or pid in seen or pid not in by_span:
            return 0
        return 1 + _depth(by_span[pid], seen | {pid})

    for node in nodes:
        node["depth"] = _depth(node)

    # Gaps: dead time since the previous node ENDED. The number that makes a waterfall
    # diagnostic — a slow run made of fast work is a gap problem, and this names it.
    prev_end: Optional[float] = None
    for node in nodes:
        start = node.get("offset_ms")
        if start is not None and prev_end is not None:
            node["gap_ms"] = round(max(0.0, start - prev_end), 3)
        if start is not None:
            prev_end = start + float(node.get("duration_ms") or 0.0)

    # ── busy vs idle, over the UNION of intervals, never a sum of gaps ──────────
    # Measured on a real 157-node run: 53 nodes start before the previous one ends, so
    # this trace is concurrent. Summing per-node gaps called it 386.5s of dead time when
    # the truth was 311.9s — a proxy overstating the real measure by 75 seconds. The
    # union is the only reading that survives concurrency.
    spans_iv = sorted((n["offset_ms"], n["offset_ms"] + float(n.get("duration_ms") or 0.0))
                      for n in nodes if n.get("offset_ms") is not None)
    merged: list[list[float]] = []
    concurrent = 0
    running_end: Optional[float] = None
    for start, end in spans_iv:
        if running_end is not None and start < running_end - 1e-6:
            concurrent += 1
        running_end = max(running_end or 0.0, end)
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    busy_ms = round(sum(e - s for s, e in merged), 3)
    wall_ms = round(merged[-1][1] - merged[0][0], 3) if merged else 0.0
    idle_ms = round(max(0.0, wall_ms - busy_ms), 3)

    longest = max((n for n in nodes if n.get("duration_ms")),
                  key=lambda n: n["duration_ms"], default=None)
    if longest is not None:
        longest["critical"] = True

    totals: dict[str, int] = {}
    for node in nodes:
        for k, v in (node.get("usage") or {}).items():
            if isinstance(v, int):
                totals[k] = totals.get(k, 0) + v

    ends = [n["offset_ms"] + float(n.get("duration_ms") or 0.0)
            for n in nodes if n.get("offset_ms") is not None]

    return {
        "nodes": nodes,
        "started_at": rows[0].get("at"),
        "total_ms": round(max(ends), 3) if ends else None,
        "span_count": len(nodes),
        "model_calls": sum(1 for n in nodes if n["kind"] == "model"),
        "usage": totals,
        # Per-node `gap_ms` is a SEQUENTIAL reading and is kept for the waterfall's
        # between-bar labels. These three are the aggregate truth.
        "busy_ms": busy_ms,
        "idle_ms": idle_ms,
        "wall_ms": wall_ms,
        #: Nodes that start before the previous one ends. Non-zero means this run ran
        #: work in parallel, and any sequential reading of it is wrong.
        "concurrent_nodes": concurrent,
    }


def flow_edges(timeline: dict) -> list[dict]:
    """Node-to-node edges for the flow view, each carrying the latency between them.

    The reference product renders that number ON the edge ("0ms", "12ms", "62ms"), which
    is the detail that turns a boxes-and-arrows picture into a reading of where a run
    actually spent its time.
    """
    nodes: list[dict[str, Any]] = timeline.get("nodes") or []
    out: list[dict] = []
    for prev, node in zip(nodes, nodes[1:]):
        out.append({"from": prev["id"], "to": node["id"],
                    "latency_ms": node.get("gap_ms")})
    return out
