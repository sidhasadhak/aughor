"""VA-5 — the trace surface an agent can actually read.

`GET /traces/{id}` returns the whole log: measured at **1.2 MB for a 1,140-event run**
on this store, roughly 300k tokens. Exposing that to a coding agent is not a trace
surface, it is a way to exhaust the context that was going to read it — which is why
the roadmap's own risk note says to page by span rather than load whole.

These tests pin the two properties that make the summary worth having: it answers a
question the log cannot (where the time went, over the union of intervals rather than a
sum of gaps), and it does NOT carry payloads — the drill-down is per span, and audited.
"""
from __future__ import annotations

import json

import pytest

from aughor.obs import session_log
from aughor.obs.trace_summary import build_summary, span_payload


def _events() -> list[dict]:
    """A small run with the shape that matters: a long span with short work inside it,
    a real gap, a model call with usage, and a failure."""
    return [
        {"seq": 1, "kind": session_log.USER_REQUEST, "at": "2026-08-23T10:00:00.000Z",
         "span_id": None, "parent_span_id": None, "name": "",
         "payload": {"question": "Why did revenue drop?"}},
        {"seq": 2, "kind": session_log.TOOL_CALL, "at": "2026-08-23T10:00:00.000Z",
         "span_id": "s1", "parent_span_id": None, "name": "cross_section",
         "payload": {"span_kind": "node", "input": "SELECT 1"}},
        {"seq": 3, "kind": session_log.LLM_CALL, "at": "2026-08-23T10:00:01.000Z",
         "span_id": None, "parent_span_id": None, "name": "m", "model": "gemini-x",
         "provider": "gemini", "duration_ms": 900.0,
         "prompt_tokens": 1200, "completion_tokens": 40, "payload": {"role": "coder"}},
        {"seq": 4, "kind": session_log.TOOL_CALL, "at": "2026-08-23T10:00:02.000Z",
         "span_id": "s2", "parent_span_id": "s1", "name": "sql.execute",
         "payload": {"span_kind": "sql", "input": "SELECT category FROM orders"}},
        {"seq": 5, "kind": session_log.TOOL_CALL_RESULT, "at": "2026-08-23T10:00:02.100Z",
         "span_id": "s2", "parent_span_id": "s1", "name": "sql.execute",
         "ok": True, "duration_ms": 100.0, "row_count": 17,
         "payload": {"span_kind": "sql", "output": "17 rows"}},
        # …a long wait here, which is the thing a summary must name…
        {"seq": 6, "kind": session_log.TOOL_CALL_RESULT, "at": "2026-08-23T10:00:10.000Z",
         "span_id": "s1", "parent_span_id": None, "name": "cross_section",
         "ok": False, "duration_ms": 10000.0, "error_class": "TimeoutError",
         "payload": {"span_kind": "node", "error": "TimeoutError: upstream"}},
        {"seq": 7, "kind": session_log.FINAL_RESPONSE, "at": "2026-08-23T10:00:10.100Z",
         "span_id": None, "parent_span_id": None, "name": "", "ok": False,
         "payload": {"headline": "could not answer"}},
    ]


# ── the summary ──────────────────────────────────────────────────────────────────

def test_the_digest_answers_where_the_time_went():
    d = build_summary("t1", _events())
    assert d["trace_id"] == "t1"
    assert d["question"] == "Why did revenue drop?"
    assert d["counts"]["events"] == 7
    assert d["time"]["wall_ms"] and d["time"]["busy_ms"] is not None
    slowest = d["slowest_spans"][0]
    assert slowest["name"] == "cross_section"
    assert slowest["duration_ms"] == 10000.0
    assert slowest["pct_of_run"] is not None


def test_idle_is_the_union_reading_not_a_sum_of_gaps():
    """The discriminating shape is a LONG node with short ones inside it: summing
    per-node gaps double-counts the parent's own duration and calls concurrent work
    dead time. On a real 157-node run that proxy overstated idle by 75 seconds."""
    d = build_summary("t1", _events())
    t = d["time"]
    assert t["busy_ms"] <= t["wall_ms"], "busy time cannot exceed the wall clock"
    assert t["idle_ms"] == pytest.approx(t["wall_ms"] - t["busy_ms"], abs=1.0)
    assert t["concurrent_nodes"] >= 1, "the fixture nests work inside a long span"
    assert 0 <= (t["idle_pct"] or 0) <= 100


def test_usage_and_models_are_totalled():
    d = build_summary("t1", _events())
    assert d["usage"].get("prompt_tokens") == 1200
    assert d["models"]["gemini-x"]["calls"] == 1
    assert d["models"]["gemini-x"]["input_tokens"] == 1200
    assert d["models"]["gemini-x"]["provider"] == "gemini"


def test_failures_are_named_with_the_span_to_open_next():
    d = build_summary("t1", _events())
    assert d["counts"]["errors"] == 1
    (err,) = d["errors"]
    assert err["error_class"] == "TimeoutError"
    assert err["span_id"] == "s1", "an error with no span id cannot be drilled into"


def test_the_digest_carries_NO_payloads():
    """The whole point. A summary that leaks the log is the log."""
    d = build_summary("t1", _events())
    blob = json.dumps(d)
    assert "SELECT category FROM orders" not in blob
    assert "could not answer" not in blob
    assert "not included" in d["note"], \
        "a reader who cannot tell a summary from a full trace concludes payloads do not exist"


def test_the_digest_is_much_smaller_than_the_log_it_summarises():
    events = _events() * 60          # ~420 events, the shape of a real deep run
    d = build_summary("t1", events)
    assert len(json.dumps(d)) < len(json.dumps(events)) / 8, \
        "the summary grew with the log — the ranked lists are not bounded"


def test_ranked_lists_are_bounded_by_top_n():
    d = build_summary("t1", _events() * 60, top_n=3)
    assert len(d["slowest_spans"]) <= 3
    assert len(d["longest_gaps"]) <= 3
    assert len(d["errors"]) <= 3


def test_an_empty_run_does_not_explode():
    d = build_summary("t-empty", [])
    assert d["counts"]["events"] == 0 and d["slowest_spans"] == []


# ── the paged drill-down ────────────────────────────────────────────────────────

def test_a_span_read_returns_that_spans_input_and_output():
    sp = span_payload("t1", _events(), "s2")
    assert sp["name"] == "sql.execute"
    assert sp["input"]["input"] == "SELECT category FROM orders"
    assert sp["output"]["output"] == "17 rows"
    assert sp["ok"] is True and sp["row_count"] == 17


def test_an_unknown_span_is_None_not_the_nearest_match():
    """A payload returned for a span the caller did not ask about is worse than
    nothing, because it will be read as the one they did."""
    assert span_payload("t1", _events(), "no-such-span") is None


def test_a_span_read_reports_masking_and_content_flags():
    events = _events()
    events[3]["credentials_masked"] = 2
    events[3]["content_captured"] = True
    sp = span_payload("t1", events, "s2")
    assert sp["credentials_masked"] == 2 and sp["content_captured"] is True


# ── the routes, and their audit ─────────────────────────────────────────────────

def _fake_ledger(emitted: list):
    class _L:
        def emit(self, kind, payload=None, **kw):
            emitted.append((kind, payload))
            return 1
    return _L()


@pytest.mark.parametrize("call", ["summary", "span"])
def test_both_trace_reads_are_audited(monkeypatch, call):
    """Decision ③ is about who read whose run, not about how much they got back — a
    reader who only ever fetched summaries must not be invisible in the audit trail."""
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: _events())
    emitted: list = []
    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _fake_ledger(emitted))
    try:
        if call == "summary":
            out = obs.get_trace_summary("t1")
            assert out["trace_id"] == "t1"
        else:
            out = obs.get_trace_span("t1", "s2")
            assert out["span_id"] == "s2"
    finally:
        _led.Ledger.default = orig
    assert "trace.payload_access" in [k for k, _ in emitted], \
        f"the {call} read journalled nothing"


def test_an_unknown_span_route_is_a_404(monkeypatch):
    from fastapi import HTTPException
    from aughor.routers import obs
    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: _events())
    with pytest.raises(HTTPException) as exc:
        obs.get_trace_span("t1", "nope")
    assert exc.value.status_code == 404


# ── the MCP surface ─────────────────────────────────────────────────────────────

def test_the_trace_tools_are_REGISTERED_not_merely_defined():
    """A tool defined and never registered is the built-but-not-wired shape: the module
    imports, the function exists, and no client can call it."""
    import asyncio
    import aughor.mcp.server as srv
    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    assert {"list_runs", "inspect_run", "read_run_span"} <= names


def test_there_is_no_whole_trace_tool():
    """Deliberate absence, pinned. A tool whose SUCCESS case is 1.2 MB exhausts the
    context that was going to read it."""
    import asyncio
    import aughor.mcp.server as srv
    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    assert "get_trace" not in names and "fetch_trace" not in names


def test_the_client_calls_the_digest_and_span_paths():
    """The tools are thin wrappers; if the path is wrong they fail only against a live
    API, which is the slowest possible place to find out."""
    import asyncio
    from aughor.mcp.client import AughorClient

    seen: list = []
    c = AughorClient.__new__(AughorClient)

    async def _get(path, params=None):
        seen.append((path, params))
        return {}
    c._get = _get
    asyncio.run(c.inspect_run("t1", top=5))
    asyncio.run(c.run_span("t1", "s2"))
    asyncio.run(c.list_runs(limit=3))
    paths = [p for p, _ in seen]
    assert paths == ["/traces/t1/summary", "/traces/t1/spans/s2", "/traces"]
    assert seen[0][1]["top"] == 5


# ── trace feedback ──────────────────────────────────────────────────────────────

def test_a_run_judgement_is_recorded_with_who_clicked(monkeypatch):
    from aughor.routers import obs
    from aughor.org import context as octx
    import aughor.kernel.ledger as _led

    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: _events())
    emitted: list = []
    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _fake_ledger(emitted))
    tok = octx.set_user_id("reviewer-2")
    try:
        out = obs.post_trace_feedback(
            "t1", obs._TraceFeedbackRequest(verdict="unhelpful", note="answered the wrong question"))
    finally:
        octx._current_user.reset(tok)
        _led.Ledger.default = orig
    assert out["recorded"] is True
    kind, payload = emitted[0]
    assert kind == "trace.feedback"
    assert payload["verdict"] == "unhelpful"
    assert payload["by"] == "reviewer-2"
    assert payload["trace_id"] == "t1"


def test_an_unidentified_install_records_an_empty_actor_not_a_guess(monkeypatch):
    """`user_id` is 0 of 8,198 rows on this store — the measurement that stopped
    OA·LF-2. Recording "" is the true answer; inventing an actor would make the trail
    assert something it does not know."""
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: _events())
    emitted: list = []
    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _fake_ledger(emitted))
    try:
        obs.post_trace_feedback("t1", obs._TraceFeedbackRequest(verdict="helpful"))
    finally:
        _led.Ledger.default = orig
    assert emitted[0][1]["by"] == ""


def test_an_unknown_verdict_is_a_400_not_a_silently_stored_string(monkeypatch):
    from fastapi import HTTPException
    from aughor.routers import obs
    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: _events())
    with pytest.raises(HTTPException) as exc:
        obs.post_trace_feedback("t1", obs._TraceFeedbackRequest(verdict="meh"))
    assert exc.value.status_code == 400


def test_feedback_on_a_trace_that_does_not_exist_is_a_404(monkeypatch):
    from fastapi import HTTPException
    from aughor.routers import obs
    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: [])
    with pytest.raises(HTTPException) as exc:
        obs.post_trace_feedback("nope", obs._TraceFeedbackRequest(verdict="helpful"))
    assert exc.value.status_code == 404


def test_the_run_vocabulary_is_NOT_the_finding_vocabulary():
    """A thumbs-down on a run that was slow but right is not a rejected finding.
    Folding them together would teach the planner's close-the-loop signal to read
    latency complaints as wrong answers."""
    from aughor.routers.obs import TRACE_VERDICTS
    from aughor.feedback.verdicts import VERDICTS as FINDING_VERDICTS
    assert set(TRACE_VERDICTS) == {"helpful", "unhelpful"}
    assert not set(TRACE_VERDICTS) & set(FINDING_VERDICTS)


def test_disagreement_is_kept_rather_than_collapsed(monkeypatch):
    """Two people disagreeing about a run is the fact worth keeping; the latest
    opinion is not the answer."""
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    rows = [{"at": "t2", "payload": {"verdict": "unhelpful", "note": "slow", "by": "b"}},
            {"at": "t1", "payload": {"verdict": "helpful", "note": "", "by": "a"}}]

    class _L:
        def events(self, **kw):
            return rows

    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _L())
    try:
        out = obs.get_trace_feedback("t1")
    finally:
        _led.Ledger.default = orig
    assert out["count"] == 2 and out["helpful"] == 1 and out["unhelpful"] == 1
    assert [i["by"] for i in out["items"]] == ["b", "a"]


def test_a_broken_journal_does_not_error_at_someone_trying_to_help(monkeypatch):
    """Fail-open, like `chat.feedback`. But it reports `recorded: False` rather than
    claiming success — a thumbs that silently vanished is worse than one that says so."""
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    monkeypatch.setattr(session_log, "recover_session", lambda *a, **k: _events())

    class _Broken:
        def emit(self, *a, **k):
            raise RuntimeError("ledger down")

    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _Broken())
    try:
        out = obs.post_trace_feedback("t1", obs._TraceFeedbackRequest(verdict="helpful"))
    finally:
        _led.Ledger.default = orig
    assert out["ok"] is False and out["recorded"] is False


# ── trace logs ──────────────────────────────────────────────────────────────────

def _ledger_rows():
    return [
        {"seq": 9, "at": "2026-08-23T10:00:03Z", "kind": "error.tolerated",
         "payload": {"error": "NameError: name 'x' is not defined",
                     "reason": "grain-bug lint is best-effort", "counter": "explorer.grain_lint_failed"}},
        {"seq": 8, "at": "2026-08-23T10:00:01Z", "kind": "node.span",
         "payload": {"name": "cross_section", "ms": 120.0}},
    ]


def _ledger_with(rows):
    class _L:
        def events(self, **kw):
            return rows
    return _L()


def test_a_swallowed_error_is_visible_in_the_runs_logs(monkeypatch):
    """A tolerated error is invisible in the waterfall BY CONSTRUCTION — the span it
    happened inside succeeded. The journal is the only place it exists."""
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _ledger_with(_ledger_rows()))
    try:
        out = obs.get_trace_logs("t1")
    finally:
        _led.Ledger.default = orig

    assert out["count"] == 2 and out["tolerated_errors"] == 1
    swallowed = next(line for line in out["lines"] if line["tolerated"])
    assert "NameError" in swallowed["error"]
    assert swallowed["reason"], (
        "without the reason a reader cannot tell a designed degradation from a bug "
        "nobody noticed")
    assert swallowed["counter"] == "explorer.grain_lint_failed"


def test_ordinary_journal_lines_keep_their_payload_and_are_not_flagged(monkeypatch):
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _ledger_with(_ledger_rows()))
    try:
        out = obs.get_trace_logs("t1")
    finally:
        _led.Ledger.default = orig
    plain = next(line for line in out["lines"] if not line["tolerated"])
    assert plain["kind"] == "node.span"
    assert plain["payload"]["name"] == "cross_section"
    assert plain["error"] is None


def test_the_logs_are_scoped_to_ONE_run(monkeypatch):
    """The scoping is the safety property, not a convenience. Read in aggregate this
    journal is misleading: `explorer.grain_lint_failed` shows 959 NameErrors, which reads
    as a live dead guard until you notice the last was 2026-06-30 and the import has since
    been added. A run's own lines cannot mislead that way."""
    from aughor.routers import obs
    import aughor.kernel.ledger as _led

    seen: list = []

    class _L:
        def events(self, **kw):
            seen.append(kw)
            return []

    orig = _led.Ledger.default
    _led.Ledger.default = classmethod(lambda cls: _L())
    try:
        obs.get_trace_logs("t-scoped", limit=5000)
    finally:
        _led.Ledger.default = orig
    assert seen[0]["trace_id"] == "t-scoped", "the read was not scoped to the run"
    assert seen[0]["limit"] <= 1000, "an unbounded limit makes this the whole journal again"
