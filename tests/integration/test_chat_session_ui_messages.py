"""CA-1 — the thread as `UIMessage[]`: persisted form == streamed form.

The web client restores a thread with `setMessages` over
`GET /chat-sessions/{id}/messages`, and its `projectTurn` derives the turn from
these parts exactly as it does from a live stream. What these tests pin is the
SHAPE CONTRACT: each stored turn becomes a user/assistant pair, prose rides as a
channel-stamped text part plus its settled data part, structure rides as typed
`data-*` parts, and an interrupted turn carries the shared uncertainty sentence
as a `data-error` part — a partial presented as complete is a worse lie than not
restoring it.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor.db.history import save_chat_turn
from aughor.kernel.jobs import UNCERTAIN_RESULT
from aughor.routers.investigations import get_chat_session_messages


def _parts_by_type(msg: dict) -> dict:
    return {p["type"]: p for p in msg["parts"]}


def test_thread_maps_to_ui_message_pairs():
    session = "ca1-uimsg-basic"
    inv_id = save_chat_turn(
        question="which region leads?",
        connection_id="conn-ca1",
        headline="West leads at 10",
        sql="SELECT region, SUM(x) FROM t GROUP BY 1",
        session_id=session,
        columns=["region", "total"],
        rows=[["West", 10], ["East", 7]],
        chart_type="bar",
        tables_used=["t"],
        intent="compare regions",
        approach=["group", "sum"],
        insight={"narrative": "West is ahead.", "anomalies": ["East dipped"],
                 "trend": "up", "confidence": "high"},
    )

    msgs = get_chat_session_messages(session)
    assert [m["role"] for m in msgs] == ["user", "assistant"]

    user, assistant = msgs
    assert user["parts"] == [{"type": "text", "text": "which region leads?"}]
    assert user["id"] != assistant["id"], "the pair must not share a message id"

    parts = _parts_by_type(assistant)
    # Prose: a channel-stamped text part (the streamed form) + its settled data part.
    assert parts["text"]["text"] == "West leads at 10"
    assert parts["text"]["providerMetadata"] == {"aughor": {"channel": "headline"}}
    assert parts["data-headline"]["data"] == {"headline": "West leads at 10"}
    # Structure: the typed parts the projection reads.
    assert "GROUP BY" in parts["data-sql"]["data"]["sql"]
    assert parts["data-columns"]["data"]["columns"] == ["region", "total"]
    assert len(parts["data-rows"]["data"]["rows"]) == 2
    assert parts["data-chart_type"]["data"]["chart_type"] == "bar"
    assert parts["data-tables_used"]["data"]["tables"] == ["t"]
    assert parts["data-analysis"]["data"] == {"intent": "compare regions",
                                              "steps": ["group", "sum"]}
    # The stored key is `insight`; the wire part is `narrative`.
    assert parts["data-narrative"]["data"]["anomalies"] == ["East dipped"]
    # The turn id is the receipt key.
    assert parts["data-done"]["data"] == {"has_receipt": True, "inv_id": inv_id}


def test_interrupted_turn_carries_the_uncertainty_sentence_not_a_receipt():
    session = "ca1-uimsg-interrupted"
    save_chat_turn(
        question="what happened?",
        connection_id="conn-ca1",
        headline="partial words",
        sql="SELECT 1",
        session_id=session,
        status="interrupted",
    )

    (_, assistant) = get_chat_session_messages(session)
    parts = _parts_by_type(assistant)
    assert UNCERTAIN_RESULT in parts["data-error"]["data"]["message"]
    assert "data-done" not in parts, \
        "an interrupted turn must not claim a completed answer's receipt"
    # The partial it produced still renders.
    assert parts["text"]["text"] == "partial words"


def test_unknown_session_is_404():
    with pytest.raises(HTTPException) as e:
        get_chat_session_messages("ca1-uimsg-nope")
    assert e.value.status_code == 404
