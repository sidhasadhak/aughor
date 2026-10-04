"""CP-1b — the treatment levers, and a shadow that cannot cost a turn.

Arc CP's census measured that `deep_analysis` is chosen 0 times in 60 tool uses, so the
interactive quick/deep split is not being made. This wave names the criteria and records
what a typed judgement WOULD have picked, beside what actually ran. It routes nothing.

The properties that matter are mostly about restraint:

* it is OFF by default, because a classification is a model call per settled turn and the
  spending is the operator's to start;
* it cannot fail a turn — every path swallows, because an experiment that breaks answers is
  not an experiment;
* the state carries only what is UNCERTAIN. The connection, the destination and the asker
  are known to the caller, and a lever that re-infers a known fact is a lever that can be
  wrong about one;
* `agreed` is computed at write time, because the arc's falsifier ("the shadow agrees with
  what ran on essentially every ask") has to be one fold over one column;
* it cannot stop the SERVER. It runs on a thread of its own, never on the event loop: called
  from the door's `finally` it froze a live install twice in an hour, for minutes, while its
  model's reply stalled.
"""
from __future__ import annotations

import pytest

from aughor.judgment import treatment as T
from aughor.judgment.seam import Answer, CHOICE, NOUL, SCORE


class _Judge:
    """A seam-shaped backend: answers every lever without a model."""

    def __init__(self, treatment="multi_query", p=0.72):
        self.treatment, self.p, self.states = treatment, p, []

    def judge(self, state, questions):
        self.states.append(state)
        out = {}
        for q in questions:
            if q.id == "treatment":
                out[q.id] = Answer(q.id, CHOICE, True, value=self.treatment, probability=self.p,
                                   distribution={o: 0.25 for o in q.options})
            elif hasattr(q, "options"):
                out[q.id] = Answer(q.id, CHOICE, True, value=q.options[0], probability=0.5,
                                   distribution={o: 0.5 for o in q.options})
            elif hasattr(q, "levels"):
                out[q.id] = Answer(q.id, SCORE, True, value=q.levels[1], probability=0.6,
                                   distribution={n: 0.5 for n in q.levels}, score=1.4)
            else:
                out[q.id] = Answer(q.id, NOUL, True, value=True, probability=0.8,
                                   distribution={"true": 0.8, "false": 0.2})
        return out


@pytest.fixture()
def on(monkeypatch):
    """Flag on, emit captured."""
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == T.SHADOW_FLAG)
    seen = []
    monkeypatch.setattr("aughor.obs.session_log.emit",
                        lambda kind, **kw: seen.append((kind, kw)))
    return seen


# ── the bundle ───────────────────────────────────────────────────────────────────────────

def test_nine_levers_in_one_bundle():
    """Latency scales with tokens, not question count, so the levers are asked together —
    a round trip per lever would make the cheap thing expensive."""
    j = _Judge()
    got = T.classify("why did revenue fall?", provider=j)
    assert len(j.states) == 1, "one bundle, one call"
    assert set(got) == {q.id for q in T.LEVERS} and len(T.LEVERS) == 9


def test_the_state_carries_only_what_is_UNCERTAIN(monkeypatch):
    """The rule that keeps the bundle small: the connection, the destination and the asker
    are known at call time, and inferring a known fact only adds a way to be wrong."""
    j = _Judge()
    T.classify("why did revenue fall?", provider=j)
    state = j.states[0]
    assert "why did revenue fall?" in state
    for known in ("8233e4fd", "slack", "#revenue", "theLook"):
        assert known not in state


def test_a_prior_turn_rides_along_because_two_levers_need_it():
    """`from_last_result` and `follow_up` are unanswerable without the previous turn, and an
    unanswerable question gets a confident guess rather than an abstention."""
    j = _Judge()
    T.classify("and by region?", prior_turn="Revenue fell 8% in September.", provider=j)
    assert "Revenue fell 8%" in j.states[0]
    assert "no previous turn" in T.state_for("first question")


# ── the row ──────────────────────────────────────────────────────────────────────────────

def test_a_row_keeps_confidence_and_a_scores_continuous_position():
    """CP-2 calibrates ON the confidence and CP-3 escalates on it, so a row that recorded
    only the winning value would be a corpus you cannot measure calibration against."""
    row = T.as_row(T.classify("why?", provider=_Judge()))
    assert row["treatment"] == "multi_query" and row["treatment_p"] == 0.72
    assert row["steps_implied_score"] == 1.4, "1.4 is a different budget from 2"
    assert "treatment_score" not in row, "a choice has no ordered position"


def test_an_unavailable_lever_records_its_reason_not_a_silent_blank():
    class _Broken:
        def judge(self, state, questions):
            return {q.id: Answer(q.id, "noul", False, reason="the judgment call failed: boom")
                    for q in questions}
    row = T.as_row(T.classify("why?", provider=_Broken()))
    assert row["treatment"] is None
    assert "boom" in row["treatment_unavailable"]


# ── the shadow ───────────────────────────────────────────────────────────────────────────

def test_OFF_by_default_writes_nothing(monkeypatch):
    """The spending switch. A classification is a model call per settled turn, so the
    default must be silence — not a sample, not a percentage."""
    called = []
    monkeypatch.setattr("aughor.obs.session_log.emit", lambda *a, **k: called.append(a))
    assert T.shadow("why?", ran="converse", provider=_Judge()) is None
    assert called == []


def test_on_it_records_the_treatment_beside_what_ran(on):
    row = T.shadow("why?", ran="deep", conn_id="c1", provider=_Judge(),
                   observed={"body": "analyst"})
    kind, kw = on[0]
    assert kind == T.TREATMENT_SHADOW and kw["conn_id"] == "c1"
    assert row["ran"] == "deep" and row["treatment"] == "multi_query"
    assert row["agreed"] is False, "a multi-query is a light turn; the analyst is the heavy body"


def test_agreement_is_computed_at_write_time(on):
    """The arc's falsifier is "the shadow agrees with what ran on essentially every ask", so
    it has to be one fold over one column rather than a join per read."""
    row = T.shadow("why?", ran="quick", provider=_Judge(treatment="multi_query"),
                   observed={"body": "converse"})
    assert row["agreed"] is True


def test_agreement_is_taken_in_ONE_vocabulary(on):
    """`agreed` used to be `treatment == ran`: "multi_query" against "deep". The two share no
    word, so it read 0 of 109 on the live corpus and the arc's falsifier could not fire. It is
    the judged treatment's TIER against the tier that served."""
    for treatment, body, want in (("investigation", "analyst", True),
                                  ("single_query", "analyst", False),
                                  ("lookup", "quick", True),
                                  ("investigation", "converse", False)):
        row = T.shadow("why?", ran="deep", provider=_Judge(treatment=treatment),
                       observed={"body": body})
        assert row["agreed"] is want, (treatment, body)


def test_agreement_is_unknown_when_the_row_does_not_say_what_served(on):
    """No body, no verdict — never a False that reads as disagreement."""
    row = T.shadow("why?", ran="deep", provider=_Judge(treatment="investigation"))
    assert row["agreed"] is None


def test_a_shadow_NEVER_costs_a_turn(on):
    """Every path swallows. The corpus is worth nothing if collecting it breaks answers."""
    class _Explodes:
        def judge(self, state, questions):
            raise RuntimeError("the judge is on fire")

    # A dead JUDGE is not a dead turn: the seam converts the failure into unavailable
    # answers, so a row is still written and it records that the classification did not
    # happen — which is a different fact from "it had no opinion".
    row = T.shadow("why?", ran="converse", provider=_Explodes())
    assert row is not None and row["treatment"] is None
    assert "on fire" in row["treatment_unavailable"]

    # A dead LEDGER is not a dead turn either. This asserts the return value rather than
    # merely that nothing raised — `pytest` would pass a bare call even if it returned a
    # half-built row, and None is the contract for "wrote nothing".
    import aughor.obs.session_log as sl
    original = sl.emit
    sl.emit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger down"))
    try:
        assert T.shadow("why?", ran="converse", provider=_Judge()) is None
    finally:
        sl.emit = original


# ── the hook ─────────────────────────────────────────────────────────────────────────────

def _flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == T.SHADOW_FLAG)


def _settled(timeout: float = 5.0) -> None:
    """Wait for every shadow the door has scheduled. The door does not wait; a test must."""
    import threading

    from aughor.routers.investigations import SHADOW_THREAD
    for t in [t for t in threading.enumerate() if t.name == SHADOW_THREAD]:
        t.join(timeout)
        assert not t.is_alive(), "a shadow was still running after the wait"


def test_the_ask_door_actually_calls_the_shadow(monkeypatch):
    """The wire, not the function. `shadow` is thoroughly tested above and would still have
    been dead code: nothing referenced `stream_with_session_log` in the suite, so a hook
    dropped from it would have been invisible. This drives the real wrapper.

    It also pins WHERE the call sits — after the answer has streamed — because a
    classification is a model call and putting one in front of a user's answer to collect
    data for a later wave would spend the very thing the wave exists to save.
    """
    import asyncio

    from aughor.obs import session_log
    from aughor.routers import investigations as I

    monkeypatch.setattr(session_log, "enabled", lambda: True)
    monkeypatch.setattr(session_log, "emit", lambda *a, **k: None)
    _flag_on(monkeypatch)
    calls = []
    monkeypatch.setattr("aughor.judgment.treatment.shadow",
                        lambda q, **kw: calls.append((q, kw)))

    yielded = []

    async def _drive():
        async def _stream():
            yield 'data: {"kind":"token","text":"hi"}\n\n'
        async for ev in I.stream_with_session_log(
            _stream(), question="why did revenue fall?", conn_id="c1", door="ask"):
            yielded.append(ev)

    asyncio.run(_drive())
    _settled()

    assert yielded, "the answer must still reach the caller"
    assert len(calls) == 1, "the door calls the shadow exactly once, when the turn settles"
    question, kw = calls[0]
    assert question == "why did revenue fall?"
    assert kw["conn_id"] == "c1"
    assert kw["ran"] == "quick", "no depth and no investigation id is a quick turn"


def test_the_hook_reports_a_deep_turn_as_deep(monkeypatch):
    """`ran` is the column CP-2 compares the judged treatment against, so a deep turn
    recorded as quick would corrupt the corpus in the direction that matters most."""
    import asyncio

    from aughor.obs import session_log
    from aughor.routers import investigations as I

    monkeypatch.setattr(session_log, "enabled", lambda: True)
    monkeypatch.setattr(session_log, "emit", lambda *a, **k: None)
    _flag_on(monkeypatch)
    calls = []
    monkeypatch.setattr("aughor.judgment.treatment.shadow",
                        lambda q, **kw: calls.append(kw))

    async def _drive():
        async def _stream():
            yield 'data: {"kind":"token","text":"hi"}\n\n'
        async for _ in I.stream_with_session_log(
            _stream(), question="why?", conn_id="c1", door="ask", depth="deep"):
            pass

    asyncio.run(_drive())
    _settled()
    assert calls[0]["ran"] == "deep"


# ── the server is not the shadow's to stop ───────────────────────────────────────────────

def _drain(monkeypatch, *, shadow, beside=None):
    """Drive the real wrapper over a one-frame answer, with `shadow` standing in for the
    model call. Returns (seconds the stream took to end, what `beside` returned)."""
    import asyncio
    import time

    from aughor.obs import session_log
    from aughor.routers import investigations as I

    monkeypatch.setattr(session_log, "enabled", lambda: True)
    monkeypatch.setattr(session_log, "emit", lambda *a, **k: None)
    monkeypatch.setattr("aughor.judgment.treatment.shadow", shadow)

    async def _drive():
        async def _stream():
            yield 'data: {"type":"headline","headline":"hi"}\n\n'
        other = asyncio.ensure_future(beside()) if beside else None
        t0 = time.monotonic()
        async for _ in I.stream_with_session_log(
                _stream(), question="why did revenue fall?", conn_id="c1", door="ask"):
            pass
        took = time.monotonic() - t0
        return took, (await other if other else None)

    return asyncio.run(_drive())


def test_the_stream_ends_without_waiting_for_the_shadow(monkeypatch):
    """The measured failure, in small: a model whose reply has begun and does not end.

    The stand-in waits on an event nobody sets until the stream is over. Called on the event
    loop, as it was, the stream could not end before the wait did — and on the install it
    was not only this stream that waited, it was the server.
    """
    import threading

    _flag_on(monkeypatch)
    release, ran_on, seen = threading.Event(), [], []

    def stalled(question, **kw):
        ran_on.append(threading.current_thread())
        seen.append((question, kw))
        release.wait(5.0)

    took, _ = _drain(monkeypatch, shadow=stalled)
    try:
        assert took < 1.0, f"the stream waited {took:.2f}s on the shadow's model"
        assert not release.is_set()
    finally:
        release.set()
    _settled()

    [thread] = ran_on
    assert thread is not threading.main_thread()
    assert thread.name == "treatment-shadow" and thread.daemon is True
    assert seen == [("why did revenue fall?",
                     {"ran": "quick", "conn_id": "c1", "prior_turn": "",
                      "observed": {"ok": True, "investigation": False}})]


def test_the_server_goes_on_serving_while_the_shadow_waits(monkeypatch):
    """Not only this stream. While the shadow waits, another coroutine on the same loop must
    go on running: on the install it was health checks and six automations that did not."""
    import asyncio
    import threading
    import time

    _flag_on(monkeypatch)
    waiting, release = threading.Event(), threading.Event()

    def stalled(question, **kw):
        waiting.set()
        release.wait(5.0)

    async def heartbeat():
        """Beats for as long as the shadow is waiting, up to a second."""
        beats, t0 = 0, time.monotonic()
        while time.monotonic() - t0 < 1.0:
            await asyncio.sleep(0.01)
            if waiting.is_set() and not release.is_set():
                beats += 1
            if beats >= 20:
                break
        return beats

    try:
        _took, beats = _drain(monkeypatch, shadow=stalled, beside=heartbeat)
        assert beats >= 20, f"the loop beat {beats} times while the shadow waited"
    finally:
        release.set()
    _settled()


def test_the_shadows_row_is_filed_under_the_runs_own_trace(monkeypatch):
    """The thread carries the request's context. Without it the session log drops the row —
    it keeps no event that has no trace — and the experiment would collect nothing, quietly."""
    from aughor import telemetry
    from aughor.org.context import current_session_id, reset_session_id, set_session_id

    _flag_on(monkeypatch)
    seen = []
    token = set_session_id("session-7")
    try:
        _drain(monkeypatch, shadow=lambda q, **kw: seen.append(
            (telemetry.current_trace_id(), current_session_id())))
    finally:
        reset_session_id(token)
    _settled()

    [(trace, session)] = seen
    assert trace and len(trace) == 8, "the run's own trace id, as the wrapper minted it"
    assert session == "session-7"
    assert not telemetry.current_trace_id(), "and it is bound to the run, not left on the caller"


def test_with_the_flag_off_no_thread_is_started(monkeypatch):
    """Off is the default, and off nothing is different: no shadow, and no thread for one."""
    import threading

    from aughor.routers.investigations import SHADOW_THREAD

    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    started = []
    real = threading.Thread

    class Watched(real):
        def start(self):
            started.append(self.name)
            return super().start()

    monkeypatch.setattr(threading, "Thread", Watched)
    calls = []
    _drain(monkeypatch, shadow=lambda q, **kw: calls.append(q))
    assert calls == [] and SHADOW_THREAD not in started


def test_a_shadow_that_cannot_be_scheduled_costs_the_turn_nothing(monkeypatch):
    import threading

    _flag_on(monkeypatch)

    def no_threads(*a, **kw):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading, "Thread", no_threads)
    took, _ = _drain(monkeypatch, shadow=lambda q, **kw: None)
    assert took < 1.0


# ── what the turn did is read from its own trace ────────────────────────────────────────

def _emit_turn(trace, *, steps=(), statements=0, marker=""):
    """Write a turn's events the way the bodies do, under one trace."""
    from aughor.obs import session_log
    if marker:
        session_log.emit(session_log.TOOL_CALL, name=marker, trace_id=trace)
    for name, rows in steps:
        session_log.emit(session_log.STEP, name=name, trace_id=trace, ok=True, row_count=rows,
                         payload={"tool": name})
    for _ in range(statements):
        session_log.emit(session_log.TOOL_CALL, name="sql.execute", trace_id=trace)


def test_the_queries_a_turn_ran_are_read_from_its_trace():
    """A loop step that returned rows is a query, and so is one of the analyst's own
    investigation tools; a schema read is not. Statements count everything that reached the
    warehouse, guards included."""
    _emit_turn("cp2-analyst", marker="ask.analyst", statements=7,
               steps=(("list_tables", None), ("run_sql", 12), ("run_sql", 0),
                      ("decompose", None), ("describe_table", None)))
    assert T.observed_for_trace("cp2-analyst") == {"queries": 3, "statements": 7,
                                                   "body": "analyst"}


def test_a_turn_with_no_loop_ran_one_query_when_a_statement_ran():
    _emit_turn("cp2-quick", statements=2)
    assert T.observed_for_trace("cp2-quick") == {"queries": 1, "statements": 2, "body": "quick"}
    _emit_turn("cp2-converse", marker="ask.converse", steps=(("list_tables", None),))
    assert T.observed_for_trace("cp2-converse") == {"queries": 0, "statements": 0,
                                                    "body": "converse"}


def test_an_unreadable_trace_leaves_the_row_unlabelled_not_zero():
    assert T.observed_for_trace("") == {}
    assert T.observed_for_trace("cp2-never-written") == {}


def test_the_row_the_door_writes_carries_what_the_turn_DID(monkeypatch):
    """The wire, with nothing standing in for the count. The label was dead for eleven days
    while every test here passed: each one handed `observed` to the fold, and none asked the
    wrapper what it had counted. This drives the real wrapper and the real `shadow`, with
    only the model replaced, over a turn that ran two queries — and reads the row back.
    """
    import asyncio

    from aughor import telemetry
    from aughor.kernel.ledger import Ledger
    from aughor.obs import session_log
    from aughor.routers import investigations as I

    _flag_on(monkeypatch)
    judge = _Judge(treatment="single_query")
    monkeypatch.setattr(T, "classify", lambda q, **kw: judge.judge(
        T.state_for(q, prior_turn=kw.get("prior_turn", "")), T.LEVERS))
    seen = {}

    async def _drive():
        async def _stream():
            seen["trace"] = telemetry.current_trace_id()
            session_log.emit(session_log.TOOL_CALL, name="ask.analyst")
            for rows in (5, 9):
                session_log.emit(session_log.STEP, name="run_sql", ok=True, row_count=rows,
                                 payload={"tool": "run_sql"})
            yield 'data: {"type":"columns","columns":["a"]}\n\n'
            yield 'data: {"type":"headline","headline":"two queries"}\n\n'
        async for _ in I.stream_with_session_log(
                _stream(), question="how many orders, by month?", conn_id="c1", door="ask",
                depth="deep", prior_turn="what sold best?\nSocks did."):
            pass

    asyncio.run(_drive())
    _settled()

    [ev] = Ledger.default().session_events(trace_id=seen["trace"], kind=T.TREATMENT_SHADOW)
    row = ev["payload"]
    assert row["observed_queries"] == 2, "the two queries the turn ran, not a frame count"
    assert row["observed_body"] == "analyst" and row["ran"] == "deep"
    assert row["agreed"] is False, "a single query judged; the heavy body served"
    assert "observed_grids" not in row
    assert "PREVIOUS TURN" in judge.states[0] and "Socks did." in judge.states[0]


def test_the_corpus_reader_labels_an_older_row_from_its_trace():
    """A row written before the fix carries the dead count and no body. While its trace is in
    the log it is scored on what the turn did; the fold then has a real outcome to read."""
    from aughor.judgment.calibration import calibrate
    from aughor.obs import session_log

    _emit_turn("cp2-old", marker="ask.analyst", steps=(("run_sql", 4), ("run_sql", 4)))
    session_log.emit(T.TREATMENT_SHADOW, name="treatment_shadow", trace_id="cp2-old",
                     payload={"treatment": "investigation", "treatment_p": 0.9, "ran": "deep",
                              "agreed": False, "observed_grids": 0, "observed_ok": True,
                              "steps_implied": "two or three", "steps_implied_p": 0.9,
                              "steps_implied_score": 2.0})
    [row] = [r for r in T.shadow_corpus() if r.get("observed_body") == "analyst"
             and r.get("treatment") == "investigation" and r.get("observed_grids") == 0]
    assert row["observed_queries"] == 2
    assert row["agreed"] is True, "investigation judged, the analyst served: retaken, not kept"
    got = calibrate([row])
    assert got["rows_with_an_observed_outcome"] == 1
    assert got["levers"]["steps_implied"]["available"] is True
