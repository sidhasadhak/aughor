"""CK-0.2 insight token-streaming on the REAL /chat runtime (flag ask.stream_text).

Hermetic: coder AND narrator providers are stubbed (no LLM). Drives the actual
`_stream_chat` SSE endpoint via the TestClient and asserts the dual-emit contract:
  flag ON  → `insight_delta` frames (growing partial narrative, replace semantics)
             strictly BEFORE the authoritative terminal `insight` event; `followups`
             after — the pre-existing order untouched.
  flag OFF → zero `insight_delta` frames; the core event-type sequence is otherwise
             identical (byte-identical blocking path).
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

# Three growing partials, each ≥12 chars longer than the last so the call-site
# throttle (grew ≥12 chars OR >150ms) deterministically emits every one.
_PARTIALS = [
    "Category **A** leads overall",
    "Category **A** leads overall with **57%** of the total",
    "Category **A** leads overall with **57%** of the total; **B** trails far behind.",
]
_FINAL = _PARTIALS[-1]
_QUESTIONS = ["How does B compare monthly?", "Which SKU drives A?", "What changed last week?"]


def _stream_events(client, conn_id, question, *, timeout=60):
    """POST /chat and collect every parsed SSE event (in order) until done/error."""
    events = []
    with client.stream("POST", "/chat", json={
        "connection_id": conn_id, "question": question, "mode": "ask",
    }) as r:
        assert r.status_code == 200, r.text
        t0 = time.monotonic()
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except Exception:
                    continue
            if time.monotonic() - t0 > timeout:
                pytest.fail("/chat did not finish in time")
    return events


def _stub_providers(monkeypatch):
    """Stub get_provider for every role. The coder returns 2 rows (so the insight is
    worth narrating); the narrator streams _PARTIALS then returns the final object."""
    import aughor.llm.provider as prov
    from aughor.routers.investigations import _ChatAnswer, _PostAnswer

    class FakeCoder:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _ChatAnswer:
                return _ChatAnswer(sql="SELECT * FROM (VALUES (1, 2), (3, 4)) AS t(x, y)",
                                   headline="stub answer")
            return response_model()   # any auxiliary call: benign defaults

    class FakeNarrator:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _PostAnswer:
                return _PostAnswer(narrative=_FINAL, anomalies=[], trend="stable",
                                   confidence="high", questions=list(_QUESTIONS))
            return response_model()

        def complete_streaming(self, *, system, user, response_model, temperature=0.0,
                               text_field, on_text):
            assert text_field == "narrative"
            for p in _PARTIALS:
                on_text(p)
            return _PostAnswer(narrative=_FINAL, anomalies=[], trend="stable",
                               confidence="high", questions=list(_QUESTIONS))

    fakes = {"coder": FakeCoder()}
    monkeypatch.setattr(prov, "get_provider",
                        lambda role="coder", **kw: fakes.get(role, FakeNarrator()))


# The deterministic pipeline events this feature touches — receipts (learning /
# activations) can legitimately differ between runs as resolutions crystallize,
# so the cross-run sequence comparison filters to this core set.
_CORE = ("sql", "columns", "rows", "headline", "done",
         "insight_delta", "insight", "followups", "error")


def _core_types(events):
    return [e["type"] for e in events if e.get("type") in _CORE]


def test_flag_on_dual_emits_deltas_before_terminal_insight(client: TestClient, builtin_conn_id: str, monkeypatch):
    monkeypatch.setenv("AUGHOR_ASK_STREAM_TEXT", "1")
    _stub_providers(monkeypatch)

    events = _stream_events(client, builtin_conn_id, "total value split by group")
    types = [e["type"] for e in events]
    assert "error" not in types, events

    # Every partial made it out as a parseable delta frame, in order, growing.
    deltas = [e for e in events if e["type"] == "insight_delta"]
    assert [d["narrative"] for d in deltas] == _PARTIALS
    # Order contract: done → all deltas → terminal insight → followups.
    i_done = types.index("done")
    i_insight = types.index("insight")
    delta_idx = [i for i, t in enumerate(types) if t == "insight_delta"]
    assert delta_idx and all(i_done < i < i_insight for i in delta_idx), types
    assert i_insight < types.index("followups"), types

    # The terminal event stays authoritative — full final narrative + followups.
    insight = next(e for e in events if e["type"] == "insight")
    assert insight["narrative"] == _FINAL
    followups = next(e for e in events if e["type"] == "followups")
    assert followups["questions"] == _QUESTIONS


def test_flag_off_is_the_blocking_path_with_identical_core_sequence(client: TestClient, builtin_conn_id: str, monkeypatch):
    _stub_providers(monkeypatch)

    monkeypatch.setenv("AUGHOR_ASK_STREAM_TEXT", "1")
    on_events = _stream_events(client, builtin_conn_id, "total value split by group")
    monkeypatch.setenv("AUGHOR_ASK_STREAM_TEXT", "0")
    off_events = _stream_events(client, builtin_conn_id, "total value split by group")

    # Zero delta frames when the flag is off…
    off_types = _core_types(off_events)
    assert "insight_delta" not in off_types, off_types
    # …but the terminal insight/followups arrive exactly as before, same content.
    insight = next(e for e in off_events if e["type"] == "insight")
    assert insight["narrative"] == _FINAL
    # And the core event-type sequence matches the flag-on run minus the deltas.
    on_types_sans_deltas = [t for t in _core_types(on_events) if t != "insight_delta"]
    assert off_types == on_types_sans_deltas, (off_types, on_types_sans_deltas)
