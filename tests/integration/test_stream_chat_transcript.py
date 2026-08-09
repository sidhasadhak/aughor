"""The parity net for the `_answer_core` extraction — step 1 of Wave 5's closure plan.

`_stream_chat` is about to be split into a sync core that calls `emit(type, payload)` and
a thin async wrapper that yields frames. The frame-parity guard added in #280 catches a
frame that stops being SENT. Nothing catches a frame that stops being sent *in the right
place* — and the extraction map found the ordering is load-bearing in ways that are not
obvious from reading the function:

  * `done` is NOT terminal. Six frames legitimately follow it on the happy path
    (the narration phase), by deliberate design.
  * `sql` fires up to three times — generation, execution, repair — and the client takes
    last-write-wins.
  * The post-execution caveat guards MUTATE values that later frames carry, so their
    receipts fire before the values ship. Hoisting emission drops caveats silently.
  * `headline_delta` carries the RAW pre-grounding headline; the terminal `headline` is
    authoritative. Same self-healing contract for `narrative_delta` vs `narrative`.

So this records the ORDER, not just the membership, and it does it against the real `/chat`
runtime with stubbed providers. It is written to fail loudly during the extraction rather
than to be quietly updated: if a sequence changes, that is the review conversation.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient


_HEADLINE = "Group **A** leads with **57%** of the total value"
_NARRATIVE = "Category **A** leads overall with **57%**; **B** trails far behind."


def _stub_providers(monkeypatch):
    """Hermetic: no LLM. Same shape as tests/integration/test_insight_stream.py, so the
    two files exercise the same runtime with the same stubs — a transcript recorded here
    describes the pipeline, not this fixture."""
    import aughor.llm.provider as prov
    from aughor.routers.investigations import _ChatAnswer, _PostAnswer

    class FakeCoder:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _ChatAnswer:
                return _ChatAnswer(sql="SELECT * FROM (VALUES (1, 2), (3, 4)) AS t(x, y)",
                                   headline=_HEADLINE)
            return response_model()

        def complete_streaming(self, *, system, user, response_model, temperature=0.0,
                               text_field, on_text):
            on_text(_HEADLINE)
            return self.complete(system=system, user=user, response_model=response_model)

    class FakeNarrator:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _PostAnswer:
                return _PostAnswer(narrative=_NARRATIVE, anomalies=[], trend="stable",
                                   confidence="high", questions=["A?", "B?"])
            return response_model()

        def complete_streaming(self, *, system, user, response_model, temperature=0.0,
                               text_field, on_text):
            on_text(_NARRATIVE)
            return _PostAnswer(narrative=_NARRATIVE, anomalies=[], trend="stable",
                               confidence="high", questions=["A?", "B?"])

    fakes = {"coder": FakeCoder()}
    monkeypatch.setattr(prov, "get_provider",
                        lambda role="coder", **kw: fakes.get(role, FakeNarrator()))


def _transcript(client, conn_id, question, **body) -> list[str]:
    """The ordered frame-type sequence for one /chat turn — the thing under protection."""
    types: list[str] = []
    with client.stream("POST", "/chat", json={
        "connection_id": conn_id, "question": question, "mode": "ask", **body,
    }) as r:
        assert r.status_code == 200, r.text
        t0 = time.monotonic()
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                try:
                    types.append(json.loads(line[5:].strip()).get("type"))
                except Exception:
                    continue
            if time.monotonic() - t0 > 60:
                pytest.fail("/chat did not finish in time")
    return types


def test_an_unknown_connection_ends_on_error_with_no_done(client: TestClient):
    """Termination path 1 (`investigations.py:1313`). It returns from OUTSIDE the outer
    try, so the `finally` never runs — and it emits `error` with NO `done` after it.

    Pinned because the extraction moves the body inside a thread, where that early return
    is the easiest of the six to accidentally route through the normal terminal path.
    """
    types = _transcript(client, "no-such-connection-id", "how many rows?")

    assert types, "the stream produced no frames at all"
    assert types[-1] == "error", f"expected to end on error, got {types}"
    assert "done" not in types, (
        f"a `done` appeared on the not_found path; it emits error only. Sequence: {types}")


def test_the_happy_path_order_is_recorded_and_stable(client: TestClient, builtin_conn_id: str, monkeypatch):
    """The golden transcript. Not a fixed literal — the pipeline's frame set legitimately
    varies with what the guards find — but the ORDERING INVARIANTS below are the contract
    the extraction must preserve, and each one is a real hazard the map identified.
    """
    _stub_providers(monkeypatch)
    types = _transcript(client, builtin_conn_id, "How many rows are there?")
    assert types, "no frames"

    # This test is only meaningful on a turn that actually reached the terminal phase.
    assert "done" in types, (
        f"the turn never reached its terminal phase ({types[-1]}) — with providers stubbed "
        f"this must complete, or the net protects nothing. Sequence: {types}")

    done = types.index("done")

    # 1. `sql` precedes `done`, and may repeat (generation → execute → repair).
    if "sql" in types:
        assert types.index("sql") < done, "sql must be emitted before done"

    # 2. Result frames ship BEFORE done. The caveat guards mutate the values these carry,
    #    so moving them after done would silently drop the corrections.
    for frame in ("columns", "rows", "headline"):
        if frame in types:
            assert types.index(frame) < done, f"{frame} must ship before done"

    # 3. `done` is NOT the last frame when narration runs — the deliberate exception.
    #    Asserted as a permitted fact so an extraction that "fixes" it fails here.
    after = types[done + 1:]
    for frame in after:
        assert frame in {"narrative", "narrative_delta", "insight", "insight_delta",
                         "followups", "inspect_warning", "learning", "activations",
                         "receipt_id", "error"}, (
            f"unexpected frame {frame!r} after done — the post-done phase is narration "
            f"only. Full sequence: {types}")

    # 4. Deltas precede their authoritative terminal frame (the self-healing contract).
    for delta, final in (("headline_delta", "headline"),
                         ("narrative_delta", "narrative"),
                         ("insight_delta", "insight")):
        if delta in types and final in types:
            assert types.index(delta) < types.index(final), (
                f"{delta} must precede {final} — the terminal frame is authoritative")


def test_the_transcript_helper_would_notice_a_reordering(client: TestClient, builtin_conn_id: str, monkeypatch):
    """The vacuous-pass guard. If `_transcript` ever returns an empty or single-frame
    sequence, every ordering assertion above passes while protecting nothing."""
    _stub_providers(monkeypatch)
    types = _transcript(client, builtin_conn_id, "How many rows are there?")

    assert len(types) >= 3, (
        f"only {len(types)} frame(s) captured ({types}) — the ordering assertions in this "
        "file cannot fail, which makes them worse than absent")
