"""DATA-06 for conversation memory: recalled turns never cross tenants.

CI-1 made the SERVER reconstruct a session's history and recall answers from earlier
sessions — both reads land straight in a model prompt, which makes an unscoped read a
disclosure with an extra step: another tenant's questions and results would arrive as
this tenant's own memory. Session ids are random, but "unguessable" is not an
authorization model.

Same conventions as test_data06_depth.py: identity ON, unique org ids per test,
localhost mode (identity off) stays unfiltered.
"""
from __future__ import annotations

from aughor.db.history import (
    find_prior_answers,
    get_session_turns,
    reconstruct_session_history,
    save_chat_turn,
)
from aughor.org.context import using_org


def _seed(org: str, session: str, question: str, headline: str, conn: str):
    with using_org(org):
        return save_chat_turn(question=question, connection_id=conn, headline=headline,
                              sql="SELECT 1", session_id=session, columns=["n"],
                              rows=[["42"]])


def test_session_turns_are_org_scoped(monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    _seed("memscope_a", "sess-shared-id", "what is revenue?", "A's answer", "conn-a")

    with using_org("memscope_a"):
        assert [t["headline"] for t in get_session_turns("sess-shared-id")] == ["A's answer"]
    with using_org("memscope_b"):
        assert get_session_turns("sess-shared-id") == [], \
            "a leaked/guessed session id must not return another org's turns"


def test_reconstruction_is_org_scoped(monkeypatch):
    """The CI-1a path: an empty client history + a session id rebuilds memory from the
    store. It must rebuild only the caller's own."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    _seed("memrec_a", "sess-rec", "where are we losing money?", "West leads", "conn-r")

    with using_org("memrec_a"):
        assert len(reconstruct_session_history("sess-rec")) == 1
    with using_org("memrec_b"):
        assert reconstruct_session_history("sess-rec") == [], \
            "another org's conversation must never be injected as this org's memory"


def test_cross_session_recall_is_org_scoped(monkeypatch):
    """The CI-1b path: recall crosses SESSIONS, so it must not cross tenants."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    _seed("memrecall_a", "sess-old-a", "total revenue?", "A: 12M", "conn-shared")
    _seed("memrecall_b", "sess-old-b", "total revenue?", "B: 99M", "conn-shared")

    with using_org("memrecall_a"):
        heads = [p["headline"] for p in find_prior_answers("total revenue?", "conn-shared")]
    assert "A: 12M" in heads
    assert "B: 99M" not in heads, "another tenant's prior answer must not be recalled"


def test_localhost_mode_is_unscoped(monkeypatch):
    """Identity OFF (the default local posture): one operator owns every row, and
    filtering would hide their own history."""
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    _seed("memlocal_a", "sess-local", "a local question?", "local answer", "conn-l")
    assert len(get_session_turns("sess-local")) >= 1
    assert len(reconstruct_session_history("sess-local")) >= 1
