"""The seam between the sync answer core and the SSE wrapper.

`_stream_chat` used to BE the pipeline. Now it runs `_answer_core` on a worker thread and
relays what the core emits over an `asyncio.Queue`, which makes the queue a real piece of
concurrency design rather than plumbing — so it gets its own net, separate from the frame
transcript.

Seven properties, each one a way the seam could be wrong while every existing test stayed
green:

  * ORDER AND COMPLETENESS. The core writes from a thread; the consumer reads on the loop.
    If a single frame is dropped or reordered by the hop, the transcript test would only
    notice on the handful of frames it names.
  * RAISED IS NOT FINISHED. The sentinel terminates the STREAM; it carries no outcome. The
    wrapper learns the outcome by awaiting the future, which is what keeps the old
    `except Exception -> error` frame working from a thread it no longer runs on.
  * A `BaseException` STILL CROSSES. `BudgetExceeded` unwinds past the answer path's
    fail-open handlers by not being an `Exception`. It now also has to survive a thread
    boundary and stay uncaught by the wrapper, or the budget stops being enforceable.
    `_CoreCancelled` sits outside `Exception` for the same reason, and is pinned there.
  * THE TURN STOPS WHEN THE CLIENT DOES. `emit` raising covers only the phases that emit;
    the prelude is silent, so its checkpoints are what keep a gone client from buying the
    context gather plus provider round-trips. On cancel: no frames, and the db closed.
  * WHAT THE DOOR WAS HANDED IS WHAT THE CORE RECEIVES. The wrapper forwards six keyword
    arguments; dropping any one of them (schema_scope was the near-miss) changes answer
    behaviour while every direct-call test stays green.
  * FAILURE HAS ONE ENVELOPE. Deliberate terminal states return; infrastructure failures
    raise — into the wrapper's terminal `error` frame on a 200 stream — and the `finally`
    closes the connection on every path, including the preamble that once leaked it.
  * THE CORE IS ACTUALLY SYNC. The point of the split is that a plain function call can
    reach the answer path — no loop, no bridge, no `asyncio.run`. Asserted by calling it.
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from types import SimpleNamespace

import pytest

from aughor.routers import investigations as inv


def _frames(chunks: list[str]) -> list[tuple[str, dict]]:
    out = []
    for c in chunks:
        for line in c.splitlines():
            if line.startswith("data:"):
                p = json.loads(line[5:].strip())
                out.append((p.pop("type"), p))
    return out


async def _drain(**kw) -> list[str]:
    return [c async for c in inv._stream_chat("q", "fixture", [], **kw)]


def _fake_core(monkeypatch, fn):
    """Swap the core for a scripted one. The wrapper is what is under test here."""
    monkeypatch.setattr(inv, "_answer_core", fn)


def _stub_scope(monkeypatch) -> list:
    """A scope whose `.open()` hands back a recording stub connection.

    For the tests about the core's OWN try/finally discipline: the returned list gets a
    True appended when `close()` runs, so "the connection was closed on that path" is an
    observation, not an inference."""
    closed: list = []
    db = SimpleNamespace(
        dialect="duckdb",
        get_schema=lambda: "TABLE: t\n  x  BIGINT\n",
        close=lambda: closed.append(True),
    )
    scope = SimpleNamespace(
        connection_id="fixture", declared_schema=None, tables=[],
        is_full_schema=True, eff_schema=None, schema_context="",
        open=lambda: db,
    )
    import aughor.canvas.scope as scope_mod
    monkeypatch.setattr(scope_mod, "resolve_execution_scope", lambda *a, **k: scope)
    return closed


@pytest.mark.anyio
async def test_a_thousand_frames_arrive_in_order_and_none_are_lost(monkeypatch):
    """E2 — the sentinel/ordering property, at a volume where a race would show.

    One producer thread and `call_soon_threadsafe` callbacks running FIFO on the loop is
    what makes emission order survive; a `queue.SimpleQueue` drained through an executor
    hop per frame would too, at the cost this design exists to avoid. Either way the
    guarantee has to be checked, not assumed.
    """
    def core(*a, emit, **kw):
        for i in range(1000):
            emit("headline_delta", {"headline": str(i)})
        return inv._AnswerCoreResult(outcome="answered")

    _fake_core(monkeypatch, core)
    frames = _frames(await _drain())

    assert [t for t, _ in frames] == ["headline_delta"] * 1000
    assert [p["headline"] for _, p in frames] == [str(i) for i in range(1000)]


@pytest.mark.anyio
async def test_a_core_that_raises_still_delivers_what_it_already_said(monkeypatch):
    """The frames emitted before the raise are the user's evidence of how far it got.

    They are already on the queue when the exception unwinds, so the consumer must drain
    them BEFORE the future is awaited — the error frame comes last, exactly where the
    `yield` used to put it.
    """
    def core(*a, emit, **kw):
        emit("sql", {"sql": "SELECT 1"})
        emit("columns", {"columns": ["x"]})
        raise RuntimeError("the coder fell over")

    _fake_core(monkeypatch, core)
    frames = _frames(await _drain())

    assert [t for t, _ in frames] == ["sql", "columns", "error"]
    assert "the coder fell over" in frames[-1][1]["message"]


@pytest.mark.anyio
async def test_a_base_exception_is_not_swallowed_by_the_wrapper(monkeypatch):
    """E5 — `BudgetExceeded` is a `BaseException` on purpose.

    The wrapper catches `Exception`, so a budget stop must pass straight through it to
    `_metered_stream`, which is the only place that knows how to phrase it. If the thread
    boundary or the `except` clause ate it, the budget would silently stop being enforced
    and the turn would end on a generic red line instead.
    """
    from aughor.kernel import metering

    def core(*a, emit, **kw):
        emit("sql", {"sql": "SELECT 1"})
        raise metering.BudgetExceeded("token budget")

    _fake_core(monkeypatch, core)
    with pytest.raises(metering.BudgetExceeded):
        await _drain()

    # And the composed stream still turns it into the typed frame it always did.
    _fake_core(monkeypatch, core)
    chunks = [c async for c in inv._metered_stream(
        inv._stream_chat("q", "fixture", []), budget=None)]
    frames = _frames(chunks)
    assert [t for t, _ in frames] == ["sql", "error"]
    assert frames[-1][1]["reason"] == "budget_exceeded"


@pytest.mark.anyio
async def test_a_client_that_leaves_stops_the_core_at_its_next_checkpoint(monkeypatch):
    """Cancellation is cooperative and this is its granularity.

    Nothing interrupts a blocking call mid-flight — there is no cancel primitive on any of
    these connections — so the honest guarantee is: once the consumer goes away, the next
    `emit` raises and the core unwinds through its own `finally`. This asserts the loop
    that used to run forever now stops, and that it stops by raising rather than by being
    politely asked.
    """
    emitted = threading.Event()
    stopped: dict = {}

    def core(*a, emit, **kw):
        try:
            for i in range(100_000):
                emit("headline_delta", {"headline": str(i)})
                emitted.set()
        except inv._CoreCancelled:
            stopped["at"] = i
            raise
        finally:
            stopped["unwound"] = True

    _fake_core(monkeypatch, core)
    gen = inv._stream_chat("q", "fixture", [])
    await gen.__anext__()
    await gen.aclose()

    assert emitted.wait(5), "the core never started emitting"
    for _ in range(500):                       # the core is on another thread
        if stopped.get("unwound"):
            break
        await asyncio.sleep(0.01)

    assert stopped.get("unwound"), "the core ran on after the client left"
    assert "at" in stopped, "the core stopped, but not by raising _CoreCancelled"
    assert stopped["at"] < 100_000 - 1, "it only stopped because it ran out of work"


@pytest.mark.anyio
async def test_the_wrapper_forwards_every_door_argument_to_the_core(monkeypatch):
    """Deleting `schema_scope=schema_scope` from the wrapper's core call left every test
    green: the tripwire in test_ask_quick_schema_scope reads `_answer_core`'s source, and
    the core's own tests call it directly — so the one hop that actually carries the
    argument was unguarded. Pin the forwarding functionally, for the whole two-door
    contract (`/chat` passes two of these, `/ask` all six), not just the argument that
    was once dropped."""
    got: dict = {}

    def core(question, connection_id, history, *, emit, cancelled, **kw):
        got.update(kw, question=question, connection_id=connection_id)
        return inv._AnswerCoreResult(outcome="answered")

    _fake_core(monkeypatch, core)
    await _drain(session_id="s-1", canvas_id="cv-1", skip_clarify=True,
                 purpose="starter", schema_scope="pinned_schema", assumed_default=True)

    assert got["question"] == "q" and got["connection_id"] == "fixture"
    assert got["schema_scope"] == "pinned_schema", "the argument that was once dropped"
    assert got["session_id"] == "s-1"
    assert got["canvas_id"] == "cv-1"
    assert got["skip_clarify"] is True
    assert got["purpose"] == "starter"
    assert got["assumed_default"] is True


def test_core_cancelled_is_a_base_exception_and_must_stay_one():
    """The pin, because the subtlety is one refactor away from being lost: the core is
    riddled with fail-open `except Exception: tolerate(...)` blocks (the narration loop
    alone has one around its whole body), so an `Exception`-derived cancellation would be
    swallowed by the nearest handler and the turn would run to completion for a client
    that already left. Same reasoning, and same pin, as `BudgetExceeded`."""
    assert issubclass(inv._CoreCancelled, BaseException)
    assert not issubclass(inv._CoreCancelled, Exception)


def test_a_disconnect_during_the_prelude_stops_before_any_provider_call(monkeypatch):
    """The prelude emits nothing, so `emit`'s own raise never fires there — a client that
    disconnected before the first frame used to buy the whole context gather plus up to
    three provider round-trips (ambiguity probe, resolver, compiler). The checkpoints are
    what stop that; the recording stubs below are append-only on purpose, because a
    fail-loud stub raising inside those phases' `except Exception: tolerate` blocks would
    be swallowed and the test would lie."""
    closed = _stub_scope(monkeypatch)
    paid: list[str] = []

    import aughor.llm.provider as prov
    monkeypatch.setattr(prov, "get_provider", lambda *a, **k: paid.append("provider"))
    import aughor.semantic.answer_resolution as res
    monkeypatch.setattr(res, "resolve", lambda *a, **k: paid.append("resolve"))
    import aughor.semantic.compiler as comp
    monkeypatch.setattr(comp, "compile_question", lambda *a, **k: paid.append("compile"))

    frames: list[str] = []
    with pytest.raises(inv._CoreCancelled):
        inv._answer_core("q", "fixture", [], emit=lambda t, p: frames.append(t),
                         cancelled=lambda: True)

    assert frames == [], "a cancelled turn must not emit partial terminal frames"
    assert closed == [True], "the connection must be closed AT the checkpoint, not later"
    assert paid == [], "a gone client still bought a provider/resolver/compiler call"


def test_a_currency_resolution_failure_no_longer_leaks_the_connection(monkeypatch):
    """The one statement that ran between `_es.open()` and the try whose `finally` closes
    `db` — a raise there leaked the connection (instrumented opened=1 closed=0, and the
    leak predates the split). It lives inside the block now, so the close is owed and
    paid on this path too."""
    closed = _stub_scope(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("currency store fell over")
    monkeypatch.setattr(inv, "_resolve_currency_symbol", _boom)

    with pytest.raises(RuntimeError, match="currency store fell over"):
        inv._answer_core("q", "fixture", [], emit=lambda t, p: None)

    assert closed == [True]


def test_an_unexpected_failure_raises_and_still_closes_the_connection(monkeypatch):
    """`_AnswerCoreResult.outcome` enumerates the DELIBERATE terminal states, and an
    infrastructure failure is not one of them: the core raises — the wrapper's
    `except Exception` renders the terminal `error` frame, the tool loop records a
    failed step — and the `finally` still closes the connection on the way out. Stated
    on the dataclass; pinned here so the ambiguity cannot quietly return as a catch-all
    outcome that only one of the two callers knows about."""
    closed = _stub_scope(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("infra fell over")
    monkeypatch.setattr(inv, "build_history_section", _boom)

    with pytest.raises(RuntimeError, match="infra fell over"):
        inv._answer_core("q", "fixture", [], emit=lambda t, p: None)

    assert closed == [True]


def test_a_preamble_failure_is_an_error_frame_and_a_200_not_an_escaping_exception(
        monkeypatch, client):
    """Scope resolution runs before the core's own except-ladder. Before the split, a
    raise there escaped the async generator; now it unwinds into the wrapper, which
    renders the terminal `error` frame on a normal 200 stream — the same envelope every
    other failure gets. That widening is KEPT deliberately, and this test is what stops
    the next refactor from reverting it silently."""
    import aughor.canvas.scope as scope_mod

    def _boom(*a, **k):
        raise RuntimeError("scope resolver fell over")
    monkeypatch.setattr(scope_mod, "resolve_execution_scope", _boom)

    types: list[str] = []
    with client.stream("POST", "/chat", json={
            "connection_id": "fixture", "question": "q"}) as r:
        assert r.status_code == 200, r.text
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                types.append(json.loads(line[5:].strip()).get("type"))

    assert types and types[-1] == "error", f"expected a terminal error frame, got {types}"
    assert "done" not in types, "a failed preamble must not look like a finished turn"


def _stub_providers_with_ungrounded_headline(monkeypatch):
    """The transcript stubs, except the coder claims a number the rows cannot support —
    the exact contradiction `headline_grounding` exists to catch. The receipt test below
    used to run on a turn where NO guard fired, so its `len(...) == count(...)` equality
    held as 0 == 0 and proved nothing about the plumbing it names."""
    import aughor.llm.provider as prov
    from tests.integration.test_stream_chat_transcript import _stub_providers

    _stub_providers(monkeypatch)
    stubbed = prov.get_provider

    class LyingCoder:
        def complete(self, system=None, user=None, response_model=None, **kw):
            if response_model is inv._ChatAnswer:
                return inv._ChatAnswer(
                    sql="SELECT * FROM (VALUES (1, 2), (3, 4)) AS t(x, y)",
                    headline="Revenue reached **$987,654** this quarter")
            return response_model()

        def complete_streaming(self, *, system, user, response_model, temperature=0.0,
                               text_field, on_text):
            on_text("Revenue reached")
            return self.complete(system=system, user=user, response_model=response_model)

    monkeypatch.setattr(
        prov, "get_provider",
        lambda role="coder", **kw: LyingCoder() if role == "coder" else stubbed(role, **kw))


def test_the_core_answers_with_no_event_loop_anywhere(monkeypatch, builtin_conn_id):
    """The reason the split exists, asserted as a plain function call.

    Not `async def`, no bridge, no `asyncio.run` — a sync caller (the converse
    `answer_question` tool is the one this is for) reaches the real answer path and gets
    the terminal state back, including the guard receipts that a no-op `emit` would
    otherwise throw away. Its sibling tool `run_sql` returns those; without them in the
    RETURN the richer tool would be the weaker one.

    The coder stub lies on purpose (a number matching no cell, sum or mean), so at least
    one receipt MUST exist and the frame/return equality is proven on a non-empty turn.
    """
    _stub_providers_with_ungrounded_headline(monkeypatch)

    seen: list[tuple[str, dict]] = []
    result = inv._answer_core("How many rows are there?", builtin_conn_id, [],
                              emit=lambda t, p: seen.append((t, p)))

    assert result.outcome == "answered", result.error
    assert result.sql and result.columns and result.headline
    # The guard fired, and the receipt reached BOTH sides of the seam — same payloads,
    # same order — so the emission log and the returned receipts describe the same turn.
    emitted = [p for t, p in seen if t == "guard_receipt"]
    assert emitted, "headline_grounding did not fire — the equality below would be 0 == 0"
    assert result.guard_receipts == emitted
    assert any(r.get("guard") == "headline_grounding" for r in result.guard_receipts)
    assert result.receipt["grounded"] is True
    assert "987,654" not in result.headline, "the fabricated number survived grounding"
    assert set(result.receipt) >= {"compiled", "defan", "grounded", "lint", "assumed"}


# ── what an interrupted turn leaves behind ────────────────────────────────────

def test_an_interrupted_turn_persists_what_the_user_already_saw(monkeypatch, builtin_conn_id):
    """Stopping a turn used to throw the answer away.

    The persist at the end of the happy path was the only writer, and every cancellation
    checkpoint raises long before it — so a turn the user interrupted left no trace at
    all: not in History, not in the session, nowhere. Reloading lost an answer they had
    already partly read, and the "partial answers survive stop" promise had nothing
    behind it on the server side.

    The partial is recorded off the FRAMES rather than gathered from the core's locals at
    cancel time, because the partial the user is looking at *is* the frames; reading it
    anywhere else would build a second version of it that can disagree.

    Filed as `interrupted`, never `complete`. A stopped turn has no verified answer, and
    `complete` would both claim one and be counted as one by every reader that filters on
    it.
    """
    from aughor.db.history import get_session_turns

    _stub_providers_with_ungrounded_headline(monkeypatch)

    session = "interrupted-session-" + uuid.uuid4().hex[:8]
    seen: list[tuple[str, dict]] = []

    # Walk away the moment the turn has produced something worth keeping. The first frame
    # is a `headline_delta`, so cancelling on it is the case that matters — there IS a
    # partial, and it used to be discarded. It also has to be a frame with checkpoints
    # still AHEAD of it: `emit` here is a plain recorder that never raises, so the raise
    # comes from `_checkpoint()`, and cancelling after the last one would simply let the
    # turn finish (which is how this test first failed).
    def cancelled() -> bool:
        return any(t == "headline_delta" for t, _ in seen)

    with pytest.raises(inv._CoreCancelled):
        inv._answer_core("How many rows are there?", builtin_conn_id, [],
                         emit=lambda t, p: seen.append((t, p)),
                         cancelled=cancelled, session_id=session)

    turns = get_session_turns(session)
    assert len(turns) == 1, "the interrupted turn was not persisted at all"
    turn = turns[0]
    assert turn["status"] == "interrupted", (
        f"filed as {turn['status']!r} — a stopped turn must not claim to be complete")
    assert turn["question"] == "How many rows are there?"

    last_headline = [p["headline"] for t, p in seen if t == "headline_delta"][-1]
    assert turn["headline"] == last_headline, (
        "the partial headline the user was reading is not what was stored")


def test_a_turn_interrupted_before_it_produced_anything_is_not_persisted(
        monkeypatch, builtin_conn_id):
    """The other half: silence is not a partial answer.

    A turn cancelled during the prelude — context gather, resolution, compilation, all of
    which emit nothing — has produced nothing to survive. Writing a row for it would fill
    History with empty questions that look like answers that failed, which is a worse lie
    than the one this change fixes.
    """
    from aughor.db.history import get_session_turns

    _stub_providers_with_ungrounded_headline(monkeypatch)

    session = "empty-interrupt-" + uuid.uuid4().hex[:8]

    with pytest.raises(inv._CoreCancelled):
        inv._answer_core("How many rows are there?", builtin_conn_id, [],
                         emit=lambda t, p: None,
                         cancelled=lambda: True, session_id=session)

    assert get_session_turns(session) == [], (
        "a turn that produced nothing should leave no history row")


def test_a_turn_that_already_saved_does_not_also_save_an_interrupted_copy(
        monkeypatch, builtin_conn_id):
    """The gap between `done` and the end of the function is a real place to be cancelled.

    The answer path keeps working after it emits `done` — narrative, insight and
    follow-ups are all post-answer — so a client that leaves during that tail cancels a
    turn the user considers finished, and which has already written its history row. The
    first version of the interrupted flush wrote a SECOND row for it, and reloading came
    back with the answer followed by a phantom interrupted copy of the same question.

    Found by reloading the browser mid-enrichment, not by a unit test: nothing would have
    thought to pose it, because the window only exists between the last frame the user
    sees and the last line the function runs.
    """
    from aughor.db.history import get_session_turns

    _stub_providers_with_ungrounded_headline(monkeypatch)

    session = "post-done-cancel-" + uuid.uuid4().hex[:8]
    seen: list[tuple[str, dict]] = []

    # Walk away only once the turn has emitted `done` — i.e. after its own persist ran.
    def cancelled() -> bool:
        return any(t == "done" for t, _ in seen)

    try:
        inv._answer_core("How many rows are there?", builtin_conn_id, [],
                         emit=lambda t, p: seen.append((t, p)),
                         cancelled=cancelled, session_id=session)
    except inv._CoreCancelled:
        pass   # whether the tail reaches a checkpoint is timing; either way one row.

    turns = get_session_turns(session)
    assert len(turns) == 1, (
        f"expected exactly one row for one turn, got {len(turns)}: "
        f"{[(t['question'], t['status']) for t in turns]}")
    assert turns[0]["status"] == "complete", (
        "the turn answered before the client left — it must not be filed as interrupted")
