"""Wave 5's closing invariant: the tool and the door give the same answer.

`answer_question` wraps the SAME `answer_core` the `/ask` fast path streams from, so
tool/direct parity holds BY CONSTRUCTION — one body, two callers. That is exactly why
this test exists: it is near-tautological today, and it stays one refactor away from
not being true (a reimplemented tool body, a forked prompt, a tool-only shortcut, an
extra post-processing pass on one side). The moment the two paths stop sharing the
body, this fails — and the review conversation happens here instead of in production.

Stubs are the transcript net's (`test_stream_chat_transcript._stub_providers`), so both
sides see the identical scripted coder and narrator against the identical fixture
warehouse. What is compared is the TERMINAL value on each side: the last `headline`
frame is the direct path's authoritative answer (post-grounding, post-currency; the
deltas before it are raw by contract), and the tool's `headline` field is the same slot
in the returned terminal state. Same for `sql`, where the client's contract is
last-write-wins across the up-to-three emissions.
"""
from __future__ import annotations

import json

import pytest

from aughor.agent.converse_tools import answer_question
from aughor.routers import investigations as inv
from tests.integration.test_stream_chat_transcript import _stub_providers


@pytest.mark.anyio
async def test_the_tools_answer_is_the_direct_paths_terminal_headline(
        monkeypatch, builtin_conn_id):
    _stub_providers(monkeypatch)
    question = "How many rows are there?"

    frames: list[tuple[str, dict]] = []
    async for chunk in inv._stream_chat(question, builtin_conn_id, []):
        for line in chunk.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                frames.append((payload.pop("type"), payload))

    headlines = [p["headline"] for t, p in frames if t == "headline"]
    sqls = [p["sql"] for t, p in frames if t == "sql"]
    assert headlines, "the direct path never delivered a terminal headline"
    assert sqls, "the direct path never emitted its SQL"

    out = answer_question(builtin_conn_id, {"question": question})

    assert out["outcome"] == "answered", out.get("error")
    assert out["headline"] == headlines[-1], (
        "the tool and the direct path disagree on the SAME question with the SAME "
        "stubs — the two callers have stopped sharing one body")
    assert out["sql"] == sqls[-1], "same divergence, on the SQL the user is shown"
