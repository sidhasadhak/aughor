"""Wave CR0 — deterministic evidence for `obs.session_log`.

**The claim this flag graduates on.** Not "answers get better" (nothing about a
log can), and not L4-style equivalence between two implementations — it is that
turning the log on is **observationally free on the answer path**: every frame a
door yields is byte-identical flag-on vs flag-off, the only diff is rows in
``data/system.db``, a store failure never surfaces to the run it observes, the
prompt-content flag stays independently off, retention actually bounds the
table, and the per-event write cost clears the bar E1 pre-registered (p95 under
5 ms). Each of those is decidable without a warehouse, an LLM, or a sampled run
— so, like N3, the receipt splits:

- **The invariants are proven here, hermetically.** The door wrapper is driven
  with a synthetic frame stream against a throwaway ledger, so the receipt does
  not depend on whatever happened to be in ``data/`` on the day it was run.
- **The magnitude is measured on the real store** (:func:`measured_effect`):
  rows/day at observed volume, what fraction of the retention budget that
  spends, and which kinds are actually being emitted — because an invariant
  that holds over a fixture proves safety, not what enabling it costs.

The evaluator and ``Comparison`` shape are L4's, imported rather than
re-derived. The wider behavioural surface (full-run reconstructibility, the
chat door, entry-side tool_call, span-id joins) is already pinned by
``tests/integration/test_session_log.py``; this suite pins the *graduation
claim*, not a second copy of the test suite.

No LLM, no warehouse, no network. Scenario ledgers are temp files.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from aughor.evals.equivalence import Comparison, DeterministicEquivalenceEvaluator
from aughor.evals.evaluator import EvalCase, EvalObservation

#: Suite name — looked up by name so creating the suite is idempotent across runs.
SUITE_NAME = "session log — observationally free on the answer path (CR0)"

#: The flag this suite is evidence for.

#: E1's pre-registered overhead bar (docs/WAVE_E_SESSIONS_EVALS_ARC.md): the
#: per-span write must clear p95 < 5 ms or the sink must go async before shipping.
P95_BAR_MS = 5.0

Scenario = Callable[[], Comparison]
SCENARIOS: dict[str, Scenario] = {}


def scenario(name: str) -> Callable[[Scenario], Scenario]:
    def _register(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return _register


# ── the throwaway ledger ─────────────────────────────────────────────────────────

@contextmanager
def _temp_ledger() -> Iterator[Any]:
    """A real :class:`~aughor.kernel.ledger.Ledger` on a temp file, installed as
    ``Ledger.default()`` for the scenario's duration.

    Swapping the classmethod rather than the env var keeps the swap scoped to
    this process and this ``with`` block — the suite runs from a bare script, so
    nothing else in the process is reading the default ledger concurrently.
    """
    from aughor.kernel.ledger import Ledger

    tmpdir = tempfile.mkdtemp(prefix="aughor-cr0-")
    ledger = Ledger(Path(tmpdir) / "system.db")
    original = Ledger.default
    Ledger.default = classmethod(lambda cls: ledger)  # type: ignore[method-assign]
    try:
        yield ledger
    finally:
        Ledger.default = original  # type: ignore[method-assign]
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


#: The synthetic answer stream — one of each frame kind the door wrapper sniffs,
#: plus the high-frequency delta frame it must not tax.
_FRAMES = (
    'data: {"type": "start", "investigation_id": "inv-cr0"}\n\n',
    'data: {"type": "token", "text": "hello"}\n\n',
    'data: {"type": "headline", "headline": "Revenue fell 12% in March"}\n\n',
    'data: {"type": "receipt_id", "receipt_id": "rcpt-cr0"}\n\n',
    'data: {"type": "done"}\n\n',
)


def _drive_door(*, frames: tuple = _FRAMES,
                explode_after: int | None = None) -> list[str]:
    """Run the REAL door wrapper over a synthetic stream and return what it yielded.

    ``explode_after=n`` makes the source raise after n frames — the crashed-run
    case. The wrapper re-raises, and the frames delivered up to that point are
    returned.
    """
    from aughor.routers.investigations import stream_with_session_log

    async def _run() -> list[str]:
        async def _source():
            for i, frame in enumerate(frames):
                if explode_after is not None and i >= explode_after:
                    raise RuntimeError("synthetic mid-stream crash (CR0)")
                yield frame

        out: list[str] = []
        try:
            async for event in stream_with_session_log(
                    _source(), question="cr0 receipt probe", conn_id="cr0-conn"):
                out.append(event)
        except RuntimeError as exc:
            # Only OUR synthetic crash may be absorbed — the evidence the
            # scenario asserts on is in the ledger, not the raise.
            if "synthetic mid-stream crash" not in str(exc):
                raise
        return out

    return asyncio.run(_run())


def _rows(ledger: Any) -> list[dict]:
    return ledger.session_events(limit=1000, ascending=True)


# ── the invariants ───────────────────────────────────────────────────────────────

@scenario("frames_are_delivered_untouched")
def _frames_are_delivered_untouched() -> Comparison:
    """The claim that outlived the flag: recording never changes the answer.

    The wrapper sniffs frames to correlate the run but yields the ORIGINAL strings —
    compared byte-for-byte here, so a future edit that mutates a frame in passing
    fails this receipt rather than shipping.
    """
    with _temp_ledger() as ledger:
        delivered = _drive_door(frames=_FRAMES)
        rows = _rows(ledger)

    kinds = [r["kind"] for r in rows]
    final = next((r for r in rows if r["kind"] == "final_response"), {})
    traces = {r["trace_id"] for r in rows}
    return Comparison(
        scenario="frames_are_delivered_untouched",
        expected={"identical": True, "kinds": ["user_request", "final_response"],
                  "one_trace": True, "final_ok": True, "final_carries_answer": True},
        observed={"identical": delivered == list(_FRAMES), "kinds": kinds,
                  "one_trace": len(traces) == 1,
                  "final_ok": bool(final.get("ok")),
                  "final_carries_answer": (final.get("payload") or {}).get("headline")
                  == "Revenue fell 12% in March"},
        oracle="declared (the CR0 gate, now unconditional: recording never edits an answer)",
        note="one synthetic run: identical frames out, and the run reconstructible from rows",
    )


@scenario("crashed_run_leaves_evidence")
def _crashed_run_leaves_evidence() -> Comparison:
    """A stream that dies mid-run still leaves the request, the error and a
    closed final_response — the log's most interesting runs must not be the
    ones missing from it. (Entry-side tool_call evidence for hangs is pinned by
    tests/integration/test_session_log.py; this pins the door.)"""
    with _temp_ledger() as ledger:
        delivered = _drive_door( explode_after=2)
        rows = _rows(ledger)

    by_kind = {r["kind"]: r for r in rows}
    err = by_kind.get("execution_error", {})
    final = by_kind.get("final_response", {})
    return Comparison(
        scenario="crashed_run_leaves_evidence",
        expected={"frames_delivered": 2,
                  "kinds": ["execution_error", "final_response", "user_request"],
                  "error_class": "RuntimeError", "final_ok": False},
        observed={"frames_delivered": len(delivered),
                  "kinds": sorted(by_kind),
                  "error_class": err.get("error_class"),
                  "final_ok": bool(final.get("ok"))},
        oracle="declared (E1: a cancelled/crashed run leaves the same evidence)",
        note="the wrapper's except/finally emits survive a mid-stream crash",
    )


@scenario("store_failure_never_reaches_the_answer")
def _store_failure_never_reaches_the_answer() -> Comparison:
    """Fail-open: a broken store must cost the run nothing — the sink is
    best-effort by contract, and this is the contract's proof."""
    from aughor.kernel.ledger import Ledger

    with _temp_ledger():
        original = Ledger.session_event_insert

        def _explode(self, row):  # noqa: ANN001 — signature mirrors the method
            raise RuntimeError("synthetic store failure (CR0)")

        Ledger.session_event_insert = _explode  # type: ignore[method-assign]
        try:
            delivered = _drive_door()
        finally:
            Ledger.session_event_insert = original  # type: ignore[method-assign]

    return Comparison(
        scenario="store_failure_never_reaches_the_answer",
        expected={"frames": list(_FRAMES)},
        observed={"frames": delivered},
        oracle="declared (the sink is best-effort; the run it observes proceeds)",
        note="every emit raised; every frame was still delivered unchanged",
    )


@scenario("content_capture_stays_off")
def _content_capture_stays_off() -> Comparison:
    """Permanent metadata recording must not drag prompt CONTENT along: with no
    capture WINDOW open, capture returns nothing; inside a window it caps and MARKS
    truncation, and the window closes itself once its budget is spent. Content is
    never a standing state."""
    from aughor.obs import prompt_window
    from aughor.obs.session_log import capture_prompt

    prompt_window.close_window()
    metadata_only = capture_prompt(system="s" * 10, user="u" * 10, output="o" * 10)

    prompt_window.open_window(calls=1, minutes=5, opened_by="receipt")
    captured = capture_prompt(system="s" * 3000, user="short", output=None)
    after_budget = capture_prompt(system="s" * 10, user="u" * 10, output=None)
    window_closed = not prompt_window.active()
    prompt_window.close_window()

    return Comparison(
        scenario="content_capture_stays_off",
        expected={"metadata_only": {}, "captured_keys": ["system_prompt",
                  "system_prompt_truncated", "user_prompt"],
                  "system_capped": True, "truncation_marked": True,
                  "after_budget": {}, "window_closed": True},
        observed={"metadata_only": metadata_only, "captured_keys": sorted(captured),
                  "system_capped": len(captured.get("system_prompt", "")) <= 2000,
                  "truncation_marked": captured.get("system_prompt_truncated") is True,
                  "after_budget": after_budget, "window_closed": window_closed},
        oracle="declared (content capture is a bounded, self-expiring window, not a flag)",
        note="metadata is always recorded; content needs a window that closes itself",
    )


@scenario("retention_bounds_the_table")
def _retention_bounds_the_table() -> Comparison:
    """`AUGHOR_SESSION_LOG_KEEP_DAYS` and `_MAX_ROWS` actually delete: age prunes
    the old row and keeps the fresh one; the row cap keeps the newest N."""
    from datetime import datetime, timedelta, timezone

    with _temp_ledger() as ledger:
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        ledger.session_event_insert({"trace_id": "t-old", "kind": "llm_call", "at": old})
        ledger.session_event_insert({"trace_id": "t-new", "kind": "llm_call"})
        by_age = ledger.session_events_prune(keep_days=14, max_rows=0)
        survivors_after_age = [r["trace_id"] for r in _rows(ledger)]

        for i in range(50):
            ledger.session_event_insert({"trace_id": f"t-{i}", "kind": "llm_call"})
        by_cap = ledger.session_events_prune(keep_days=0, max_rows=10)
        left = _rows(ledger)

    return Comparison(
        scenario="retention_bounds_the_table",
        expected={"pruned_by_age": 1, "survivors_after_age": ["t-new"],
                  "pruned_by_cap": 41, "rows_left": 10, "newest_kept": "t-49"},
        observed={"pruned_by_age": by_age, "survivors_after_age": survivors_after_age,
                  "pruned_by_cap": by_cap, "rows_left": len(left),
                  "newest_kept": left[-1]["trace_id"] if left else None},
        oracle="declared (retention is enforced on write, amortised — E1)",
        note="both halves of retention delete what they claim to and nothing else",
    )


@scenario("write_latency_clears_e1_bar")
def _write_latency_clears_e1_bar() -> Comparison:
    """The per-event write clears E1's pre-registered bar: p95 < 5 ms.

    Measured on a temp ledger on the same disk the real store lives on, over
    500 inserts with a realistic payload — the shape a busy span emits.
    """
    payload = {"question": "why did revenue fall in the north region last quarter?",
               "depth": "quick", "schema": "analytics"}
    timings: list[float] = []
    with _temp_ledger() as ledger:
        for i in range(500):
            t0 = time.perf_counter()
            ledger.session_event_insert({
                "trace_id": f"bench-{i % 7}", "kind": "tool_call", "name": "sql.execute",
                "span_id": f"s{i}", "duration_ms": 1.2, "payload": payload,
            })
            timings.append((time.perf_counter() - t0) * 1000)
    timings.sort()
    p50 = timings[len(timings) // 2]
    p95 = timings[int(len(timings) * 0.95)]
    return Comparison(
        scenario="write_latency_clears_e1_bar",
        expected={"p95_under_bar": True, "bar_ms": P95_BAR_MS},
        observed={"p95_under_bar": p95 < P95_BAR_MS, "bar_ms": P95_BAR_MS},
        oracle="measured (500 inserts, temp WAL SQLite, realistic payload)",
        note="E1 pre-registered this bar: clear it or make the sink async before shipping",
        detail={"p50_ms": round(p50, 3), "p95_ms": round(p95, 3),
                "max_ms": round(timings[-1], 3)},
    )


# ── the measured magnitude (the other half of the receipt) ───────────────────────

def measured_effect() -> dict[str, Any]:
    """What the flag has actually been writing, measured on the REAL store.

    Read-only. Reports ``{"available": False, ...}`` on a bare clone rather
    than a flattering zero — rows/day measured over zero active days is not a
    measurement.
    """
    import os

    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import keep_days

    try:
        ledger = Ledger.default()
        rows = ledger.session_events(limit=100_000, ascending=True)
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not rows:
        return {"available": False,
                "reason": "no session events on this store — the flag has never "
                          "been on while the API server ran"}

    kinds: dict[str, int] = {}
    days: set[str] = set()
    attributed = 0
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        days.add(str(r["at"])[:10])
        if r.get("agent_id"):
            attributed += 1
    max_rows = int(os.environ.get("AUGHOR_SESSION_LOG_MAX_ROWS", "200000") or 0)
    rows_per_day = round(len(rows) / max(len(days), 1), 1)
    try:
        db_bytes = Path(ledger.path).stat().st_size
    except Exception:
        db_bytes = None
    return {
        "available": True,
        "rows": len(rows),
        "distinct_traces": len({r["trace_id"] for r in rows}),
        "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "active_days": len(days),
        "rows_per_active_day": rows_per_day,
        "first_at": rows[0]["at"], "last_at": rows[-1]["at"],
        "agent_attributed_rows": attributed,
        "retention": {"keep_days": keep_days(), "max_rows": max_rows,
                      "days_to_row_cap_at_observed_rate":
                          round(max_rows / rows_per_day) if rows_per_day else None},
        "store_bytes_total": db_bytes,
    }


# ── the target, suite and graduation ─────────────────────────────────────────────

def receipt_target() -> Callable[[EvalCase], EvalObservation]:
    """Run the scenario named in ``case.expected["scenario"]``; unknown is an ERROR."""
    def target(case: EvalCase) -> EvalObservation:
        name = str((case.expected or {}).get("scenario") or case.id)
        fn = SCENARIOS.get(name)
        if fn is None:
            return EvalObservation(error=f"unknown session-log scenario: {name!r}")
        comparison = fn()
        return EvalObservation(narrative=comparison.note, meta=comparison.to_meta())

    return target


def ensure_suite() -> str:
    """Create the suite (idempotent by name) with one case per scenario; return its id."""
    from aughor.evals import store

    existing = next((s for s in store.list_suites(200) if s["name"] == SUITE_NAME), None)
    if existing is None:
        existing = store.create_suite(
            SUITE_NAME,
            description=("Wave CR0 — `obs.session_log` claims to be observationally free: "
                         "byte-identical answer frames on vs off, fail-open writes, content "
                         "capture independently off, retention that actually bounds the "
                         "table, and a per-event write under E1's 5 ms p95 bar. Each case "
                         "asserts one invariant hermetically: no warehouse, no LLM, temp "
                         "ledgers only."),
            target="session_log_receipt")
    suite_id = existing["id"]

    have = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    missing = [n for n in SCENARIOS if n not in have]
    if missing:
        store.add_cases(suite_id, [
            {"question": f"Does {n} hold?", "expected": {"scenario": n},
             "tags": ["cr0", "session_log"]}
            for n in missing
        ])
    return suite_id


def run_suite(*, iterations: int = 1, persist: bool = True):
    """Run every scenario and return the :class:`~aughor.evals.runner.RunSummary`."""
    from aughor.evals import runner
    from aughor.evals.registry import get_evaluator, register_evaluator

    if get_evaluator(DeterministicEquivalenceEvaluator.name) is None:
        register_evaluator(DeterministicEquivalenceEvaluator())

    suite_id = ensure_suite()
    return runner.run_suite(
        suite_id, receipt_target(), iterations=iterations, persist=persist,
        evaluators=[DeterministicEquivalenceEvaluator.name])
