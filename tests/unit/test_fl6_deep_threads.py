"""FL-6 — a deep run belongs to the conversation it was asked in.

CA-0 stamped ``session_id`` on deep runs, but every THREAD READ filtered
``kind = 'chat'`` — so the web's default (Agent) mode produced conversations
that reloaded as blank pages and a rail that listed only quick questions
(measured live 2026-08-28: five sessions, all quick-shaped, agent threads
absent). These tests pin the four seams: the turns read, the rail, the
UIMessage restore shape, and the delete semantics (a thread delete UNFILES
deep runs — they also serve Fleet and agent history — never purges them).

Hermetic: the history DB is the per-session temp store from conftest; no LLM,
no HTTP, no connection.
"""
from __future__ import annotations

import uuid

from aughor.db.history import (
    complete_investigation,
    create_investigation,
    fail_investigation,
    get_session_turns,
    list_chat_sessions,
    reconstruct_session_history,
    save_chat_turn,
)
from aughor.db.purge import purge_chat_session_artifacts

REPORT = {"headline": "Electronics leads", "phases": [{"phase_id": "p1", "findings": []}]}


def _sid() -> str:
    return f"fl6-{uuid.uuid4().hex[:8]}"


def _deep(session_id: str, question: str = "why did sales move?", *,
          conn: str = "c1", finish: str = "complete") -> str:
    inv = create_investigation(question, conn, session_id=session_id)
    if finish == "complete":
        complete_investigation(inv, REPORT, [], [], question=question,
                               connection_id=conn, skip_index=True)
    elif finish == "failed":
        fail_investigation(inv, status="failed")
    return inv


def test_a_terminal_deep_run_is_a_turn_of_its_thread():
    sid = _sid()
    save_chat_turn("how many orders?", "c1", headline="42", sql="SELECT 1",
                   session_id=sid)
    _deep(sid)

    turns = get_session_turns(sid)
    assert [t["kind"] for t in turns] == ["chat", "investigation"]
    deep = turns[1]
    assert deep["deep_report"] == REPORT
    assert deep["headline"] == "Electronics leads"
    # Type stability: every quick field exists and is empty, so resolve_history
    # and every older consumer read a deep turn without branching.
    assert deep["sql"] == "" and deep["columns"] == [] and deep["rows"] == []


def test_a_live_deep_run_stays_out_of_history():
    # The resume hub (FL-1) owns the live one; restoring a running shell would
    # duplicate against the resume stream's synthesized turn.
    sid = _sid()
    _deep(sid, finish="running")
    assert get_session_turns(sid) == []
    assert all(s["session_id"] != sid for s in list_chat_sessions("c1"))


def test_the_rail_lists_a_deep_only_thread_under_its_question():
    sid = _sid()
    _deep(sid, question="where is the leakage concentrated?")
    thread = next(s for s in list_chat_sessions("c1") if s["session_id"] == sid)
    assert thread["title"] == "where is the leakage concentrated?"
    assert thread["turns"] == 1


def test_deep_turns_feed_reconstructed_memory_as_headlines():
    sid = _sid()
    _deep(sid)
    recon = reconstruct_session_history(sid)
    assert len(recon) == 1
    assert recon[0].headline == "Electronics leads"
    assert recon[0].sql == ""  # never a fabricated query


def test_thread_delete_unfiles_deep_runs_rather_than_purging_them():
    sid = _sid()
    inv = _deep(sid)

    counts = purge_chat_session_artifacts(sid)
    assert counts.get("deep_runs_unfiled") == 1

    # The thread is gone from every read…
    assert get_session_turns(sid) == []
    assert all(s["session_id"] != sid for s in list_chat_sessions("c1"))
    # …but the RUN survives, unfiled — it still serves Fleet / agent history.
    from aughor.db.history import get_investigation
    row = get_investigation(inv)
    assert row is not None and row.get("status") == "complete"


def test_deep_turn_restores_as_the_live_wire_shape():
    from aughor.routers.investigations import _turn_to_ui_messages

    sid = _sid()
    _deep(sid, question="what drives the west?")
    [t] = get_session_turns(sid)
    user, assistant = _turn_to_ui_messages(t)

    assert user["parts"] == [{"type": "text", "text": "what drives the west?"}]
    assert user["metadata"] == {"mode": "investigate"}
    [part] = assistant["parts"]
    assert part["type"] == "data-answer_report"
    assert part["data"]["answer_report"] == REPORT
    assert part["data"]["investigation_id"] == t["id"]


def test_a_failed_deep_turn_restores_as_its_question_and_an_honest_error():
    from aughor.routers.investigations import _turn_to_ui_messages

    sid = _sid()
    _deep(sid, finish="failed")
    [t] = get_session_turns(sid)
    _user, assistant = _turn_to_ui_messages(t)

    kinds = [p["type"] for p in assistant["parts"]]
    assert "data-answer_report" not in kinds  # no report-shaped shell around nothing
    assert kinds == ["data-error"]
    assert "failed" in assistant["parts"][0]["data"]["message"]
