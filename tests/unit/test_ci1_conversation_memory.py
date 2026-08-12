"""CI-1 — conversation memory belongs to the SESSION, not to whichever client holds it.

The premise check found memory already existed (build_history_section injects prior
turns into both the quick and converse bodies) — but only from what the CLIENT sends.
CI-1 makes the server reconstruct it from the session store when the client sends none,
windows it deterministically past the old 3-turn cap, and measures it on the route
receipt. Failure is always the pre-CI-1 behaviour: inject nothing.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.routers.investigations import (
    build_history_section,
    resolve_history,
)


def _turn(q, sql="SELECT 1", cols=None, head="", key_rows=None):
    return SimpleNamespace(question=q, sql=sql, columns=cols or ["a"],
                           headline=head, key_rows=key_rows or [])


# ── windowing: recent verbatim, older summarized (no LLM) ────────────────────────

def test_window_keeps_recent_verbatim_and_summarizes_the_rest(monkeypatch):
    monkeypatch.setenv("AUGHOR_CHAT_HISTORY_WINDOW", "2")
    hist = [_turn(f"q{i}", sql=f"SELECT {i}") for i in range(6)]
    section = build_history_section(hist)
    # the two most recent turns render with their SQL
    assert "SELECT 4" in section and "SELECT 5" in section
    # older turns do NOT render verbatim, but their questions survive as a summary
    assert "SELECT 1" not in section
    assert "Earlier in this conversation (4 prior turn(s))" in section
    assert "q0" in section and "q3" in section


def test_short_history_has_no_summary_line(monkeypatch):
    monkeypatch.setenv("AUGHOR_CHAT_HISTORY_WINDOW", "4")
    section = build_history_section([_turn("only question")])
    assert "Earlier in this conversation" not in section
    assert "only question" in section


def test_empty_history_is_empty_string():
    assert build_history_section([]) == ""


# ── resolve: client wins; else reconstruct from the store ────────────────────────

def test_client_history_is_preferred(monkeypatch):
    called = {"n": 0}

    def _recon(sid, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr("aughor.db.history.reconstruct_session_history", _recon)
    client = [_turn("client turn")]
    assert resolve_history(client, "sess-1") is client
    assert called["n"] == 0, "the store is not touched when the client sent history"


def test_empty_client_reconstructs_from_the_session(monkeypatch):
    reconstructed = [_turn("stored turn")]
    monkeypatch.setattr("aughor.db.history.reconstruct_session_history",
                        lambda sid, **k: reconstructed)
    assert resolve_history([], "sess-42") is reconstructed


def test_no_session_and_no_client_stays_empty():
    assert resolve_history([], "") == []


def test_reconstruction_failure_falls_back_to_client_value(monkeypatch):
    def _boom(sid, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("aughor.db.history.reconstruct_session_history", _boom)
    # fail-open: the pre-CI-1 behaviour is to inject nothing, never to error the turn
    assert resolve_history([], "sess-x") == []


# ── the store reader shapes turns the section builder can read ───────────────────

def test_reconstruct_session_history_shapes_and_filters(monkeypatch):
    from aughor.db import history as H

    turns = [
        {"question": "where are we losing money?", "headline": "West leads",
         "sql": "SELECT region", "columns": ["region", "loss"],
         "rows": [["West", "12"], ["East", "8"]], "status": "complete"},
        {"question": "half-finished", "headline": "", "sql": "", "columns": [],
         "rows": [], "status": "interrupted"},
        {"question": "", "headline": "blank", "sql": "", "columns": [],
         "rows": [], "status": "complete"},
    ]
    monkeypatch.setattr(H, "get_session_turns", lambda sid: turns)
    out = H.reconstruct_session_history("s1")
    assert len(out) == 1, "interrupted and question-less turns are dropped"
    t = out[0]
    assert t.question == "where are we losing money?"
    assert t.key_rows == [["West", "12"], ["East", "8"]]
    # the reconstructed turn is duck-type compatible with build_history_section
    section = build_history_section(out)
    assert "West leads" in section and "SELECT region" in section


def test_reconstruct_unknown_session_is_empty(monkeypatch):
    from aughor.db import history as H
    monkeypatch.setattr(H, "get_session_turns", lambda sid: [])
    assert H.reconstruct_session_history("nope") == []
    assert H.reconstruct_session_history("") == []
