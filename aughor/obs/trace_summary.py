"""A run, small enough to reason about — VA-5's trace surface for an agent.

`GET /traces/{id}` returns the whole log. Measured on this store: **1.2 MB for a
1,140-event run**, roughly 300k tokens. Handing that to a coding agent is not
"exposing the trace", it is exhausting the context that was supposed to read it,
and the roadmap's own risk note says so — *virtualize and page by span, never load
whole*.

So the surface an agent gets is a summary, and the difference is not only size. The
full log answers "what events occurred", which a reader must then aggregate by hand
to learn anything. The summary answers the question people actually open a trace to
ask — **where did the time go, what did it cost, and what failed** — and it answers
it in a few kilobytes. The measured finding that motivated the waterfall in the
first place (a deep run is ~60% idle: 511.8s wall against 199.9s of work) is a
property of the run, not of any single event, so no amount of scrolling the log
surfaces it.

Drill-down stays paged: :func:`span_payload` returns ONE span's input and output,
so an agent that has found the slow step pays for that step alone. That read is
audited like every other payload read (decision ③).

Pure functions over already-fetched events — the store read belongs to the caller,
same as :mod:`aughor.obs.trace_tree`.
"""
from __future__ import annotations

from typing import Iterable, Optional

#: How many entries each ranked list carries. Small on purpose: a "top 25 slowest"
#: is a log again, and the point of a ranking is that the tail is not worth reading.
TOP_N = 8


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    if not whole or part is None:
        return None
    return round(100.0 * float(part) / float(whole), 1)


def build_summary(trace_id: str, events: list[dict], *, top_n: int = TOP_N) -> dict:
    """The run in a few KB: shape, cost, the slow parts, and what broke."""
    from aughor.obs import session_log
    from aughor.obs.trace_tree import build_timeline

    timeline = build_timeline(events)
    nodes = timeline["nodes"]
    wall = timeline.get("wall_ms")

    first = events[0] if events else {}
    question = ""
    if first.get("kind") == session_log.USER_REQUEST:
        question = str((first.get("payload") or {}).get("question") or "")
    final = next((e for e in reversed(events)
                  if e.get("kind") == session_log.FINAL_RESPONSE), None)

    # Ranked by duration, then by gap. Two different questions: "what took long" and
    # "what were we waiting on", and a run can be dominated by either.
    timed = [n for n in nodes if n.get("duration_ms")]
    slowest = sorted(timed, key=lambda n: n["duration_ms"], reverse=True)[:top_n]
    gapped = [n for n in nodes if (n.get("gap_ms") or 0) > 0]
    gaps = sorted(gapped, key=lambda n: n["gap_ms"], reverse=True)[:top_n]

    by_model: dict[str, dict] = {}
    for n in nodes:
        if n.get("kind") != "model":
            continue
        key = str(n.get("model") or "unknown")
        agg = by_model.setdefault(key, {"provider": n.get("provider"), "calls": 0,
                                        "input_tokens": 0, "output_tokens": 0,
                                        "duration_ms": 0.0})
        agg["calls"] += 1
        agg["duration_ms"] = round(agg["duration_ms"] + float(n.get("duration_ms") or 0), 1)
        usage = n.get("usage") or {}
        agg["input_tokens"] += int(usage.get("prompt_tokens") or 0)
        agg["output_tokens"] += int(usage.get("completion_tokens") or 0)

    # The run's own outcome is reported as `ok` above, so the final-response node is
    # excluded here: counting it would make every failed run show a phantom extra
    # error beside the thing that actually broke, and "2 errors" when one span failed
    # sends a reader looking for a second cause that does not exist.
    def _is_failure(n: dict) -> bool:
        if n.get("event_kind") == session_log.FINAL_RESPONSE:
            return False
        return n.get("ok") is False or bool(n.get("error_class"))

    failures = [n for n in nodes if _is_failure(n)]
    errors = [
        {"name": n.get("name"), "kind": n.get("kind"),
         "error_class": n.get("error_class"), "at": n.get("at"),
         "span_id": n.get("span_id")}
        for n in failures
    ][:top_n]

    return {
        "trace_id": trace_id,
        "question": question,
        "ok": final.get("ok") if final else None,
        "started_at": timeline.get("started_at"),
        "counts": {
            "events": len(events),
            "spans": timeline.get("span_count"),
            "model_calls": timeline.get("model_calls"),
            "errors": len(failures),
        },
        # The headline this surface exists for. `idle` is the union-of-intervals
        # reading, never a sum of per-node gaps — on a concurrent run those disagree
        # by 75 seconds, and only one of them is a fact about the run.
        "time": {
            "wall_ms": wall,
            "busy_ms": timeline.get("busy_ms"),
            "idle_ms": timeline.get("idle_ms"),
            "idle_pct": _pct(timeline.get("idle_ms"), wall),
            "concurrent_nodes": timeline.get("concurrent_nodes"),
        },
        "usage": timeline.get("usage") or {},
        "models": by_model,
        "slowest_spans": [
            {"name": n.get("name"), "kind": n.get("kind"), "span_id": n.get("span_id"),
             "duration_ms": n.get("duration_ms"),
             "pct_of_run": _pct(n.get("duration_ms"), wall),
             "model": n.get("model"), "depth": n.get("depth")}
            for n in slowest
        ],
        "longest_gaps": [
            {"before": n.get("name"), "gap_ms": n.get("gap_ms"),
             "pct_of_run": _pct(n.get("gap_ms"), wall)}
            for n in gaps
        ],
        "errors": errors,
        # Said explicitly rather than implied by absence: a reader who cannot tell a
        # summary from a full trace will conclude the payloads do not exist.
        "note": ("Summary only — span inputs/outputs are not included. Fetch one span "
                 "with GET /traces/{trace_id}/spans/{span_id}; that read is audited."),
    }


def span_payload(trace_id: str, events: Iterable[dict], span_id: str) -> Optional[dict]:
    """One span's call and result rows — the paged drill-down.

    Returns ``None`` when the span is not in this trace, which the caller turns into a
    404. Deliberately not "the nearest match": a payload returned for a span the caller
    did not ask about is worse than nothing, because it will be read as the one they did.
    """
    call: Optional[dict] = None
    result: Optional[dict] = None
    for e in events:
        if e.get("span_id") != span_id:
            continue
        if e.get("kind") == "tool_call_result":
            result = e
        elif call is None:
            call = e
    if call is None and result is None:
        return None
    src = call or result or {}
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "name": src.get("name"),
        "kind": (src.get("payload") or {}).get("span_kind"),
        "at": src.get("at"),
        "ok": (result or {}).get("ok"),
        "duration_ms": (result or {}).get("duration_ms"),
        "error_class": (result or {}).get("error_class"),
        "row_count": (result or {}).get("row_count"),
        "input": (call or {}).get("payload"),
        "output": (result or {}).get("payload"),
        # Carried through so a reader knows the payload was altered on the way out.
        "credentials_masked": (int((call or {}).get("credentials_masked") or 0)
                               + int((result or {}).get("credentials_masked") or 0)),
        "content_captured": bool((call or {}).get("content_captured")
                                 or (result or {}).get("content_captured")),
    }

