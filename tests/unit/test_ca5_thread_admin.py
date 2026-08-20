"""CA-5 — a thread is something you can keep: rename it, or delete it outright.

CI-6a made conversations visible; the rail was still read-only, so the only name a
thread could ever have was the first thing the user typed into it — which is reliably
the vaguest sentence in the whole conversation — and the only way to be rid of one was
to stop scrolling far enough to see it.

These tests pin the two writes and, above all, their tenant boundary: a rename and a
delete are keyed by a session id alone, and session ids being random is not an
authorization model (the same argument ``get_session_turns`` carries).
"""
from __future__ import annotations

from aughor.db.history import (
    chat_session_turn_ids,
    get_session_turns,
    list_chat_sessions,
    rename_chat_session,
    save_chat_turn,
)
from aughor.db.purge import purge_chat_session_artifacts
from aughor.org.context import using_org


def _turn(question, session_id, conn="c1"):
    return save_chat_turn(question, conn, headline="h", sql="SELECT 1",
                          session_id=session_id)


def _thread(conn, session_id):
    return next(t for t in list_chat_sessions(conn) if t["session_id"] == session_id)


# ── rename ───────────────────────────────────────────────────────────────────

def test_a_renamed_thread_keeps_the_users_words_not_the_opening_question():
    _turn("uh, revenue thing?", "sess-rename")
    _turn("break it out by region", "sess-rename")

    assert _thread("c1", "sess-rename")["title"] == "uh, revenue thing?"
    assert rename_chat_session("sess-rename", "APAC outage dig") is True

    t = _thread("c1", "sess-rename")
    assert t["title"] == "APAC outage dig"
    assert t["renamed"] is True, "the rail must be able to tell a chosen name from a derived one"
    assert t["turns"] == 2, "renaming is not a mutation of the conversation"


def test_an_empty_name_restores_the_derived_title():
    """Clearing is a real operation, not a way to end up with a blank row in the rail."""
    _turn("why did revenue drop in November?", "sess-clear")
    rename_chat_session("sess-clear", "temporary name")

    assert rename_chat_session("sess-clear", "   ") is True

    t = _thread("c1", "sess-clear")
    assert t["title"] == "why did revenue drop in November?"
    assert t["renamed"] is False


def test_renaming_a_thread_that_does_not_exist_is_a_refusal():
    """The route turns this False into a 404 — never a silently created orphan row."""
    assert rename_chat_session("no-such-session", "anything") is False


def test_rename_is_tenant_scoped(monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    with using_org("org-a"):
        _turn("org A's question", "sess-x-org")

    with using_org("org-b"):
        assert rename_chat_session("sess-x-org", "renamed by a stranger") is False

    with using_org("org-a"):
        assert _thread("c1", "sess-x-org")["title"] == "org A's question"


# ── delete ───────────────────────────────────────────────────────────────────

def test_deleting_a_thread_takes_every_turn_with_it():
    _turn("first", "sess-del")
    _turn("second", "sess-del")
    _turn("a bystander in another thread", "sess-keep")

    assert len(chat_session_turn_ids("sess-del")) == 2
    counts = purge_chat_session_artifacts("sess-del")

    assert counts.get("investigations"), "the history rows must actually go"
    assert get_session_turns("sess-del") == []
    ids = [t["session_id"] for t in list_chat_sessions("c1")]
    assert "sess-del" not in ids, "the deleted thread still lists in the rail"
    assert "sess-keep" in ids
    assert get_session_turns("sess-keep"), "deleting one thread must not touch another"


def test_a_deleted_thread_does_not_bequeath_its_name():
    """The title override is keyed by session id; leaving it behind would let a later
    session that reused the id inherit a stranger's name."""
    _turn("something", "sess-name-ghost")
    rename_chat_session("sess-name-ghost", "Q3 board prep")
    purge_chat_session_artifacts("sess-name-ghost")

    _turn("a brand new conversation", "sess-name-ghost")

    assert _thread("c1", "sess-name-ghost")["title"] == "a brand new conversation"


def test_deleting_an_unknown_thread_reports_nothing_deleted():
    assert not purge_chat_session_artifacts("no-such-session").get("investigations")


def test_delete_is_tenant_scoped(monkeypatch):
    """The turn-id read is the authorization: another tenant collects an empty list,
    so the purge has nothing to run over and the route answers 404."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    with using_org("org-a"):
        _turn("org A's private thread", "sess-del-org")

    with using_org("org-b"):
        assert chat_session_turn_ids("sess-del-org") == []
        assert not purge_chat_session_artifacts("sess-del-org").get("investigations")

    with using_org("org-a"):
        assert get_session_turns("sess-del-org"), "another tenant deleted this org's thread"
