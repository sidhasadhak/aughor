"""CI-6a — the threads rail's read: recent chat sessions, resumable, tenant-scoped.

The rail is the visible half of the memory CI-1 built: the store already held every
turn under a session_id; what was missing was a way to SEE the threads. These tests
pin the read's contract — newest activity first, the OPENING question as the title,
a connection filter, and the same org predicate the turns read uses (a rail that
listed another tenant's thread titles would leak questions, which are content).
"""
from __future__ import annotations

from aughor.db.history import list_chat_sessions, save_chat_turn
from aughor.org.context import using_org


def _turn(question, session_id, conn="c1"):
    return save_chat_turn(question, conn, headline="h", sql="SELECT 1",
                          session_id=session_id)


def test_threads_list_newest_activity_first_titled_by_opening_question():
    _turn("first question of session A", "sess-a")
    _turn("follow-up in session A", "sess-a")
    _turn("first question of session B", "sess-b")

    threads = list_chat_sessions("c1")
    ids = [t["session_id"] for t in threads]

    assert ids.index("sess-b") < ids.index("sess-a"), "newest activity first"
    by_id = {t["session_id"]: t for t in threads}
    assert by_id["sess-a"]["title"] == "first question of session A", (
        "the OPENING question names the thread, not the latest")
    assert by_id["sess-a"]["turns"] == 2
    assert by_id["sess-a"]["last_at"]


def test_the_connection_filter_scopes_the_rail():
    _turn("about warehouse one", "sess-c1", conn="conn-one")
    _turn("about warehouse two", "sess-c2", conn="conn-two")

    ids = [t["session_id"] for t in list_chat_sessions("conn-one")]

    assert "sess-c1" in ids
    assert "sess-c2" not in ids


def test_turns_without_a_session_never_surface():
    """Pre-CI-1 rows (no session_id) are turns, not threads — a rail entry that
    cannot be restored would be a dead link."""
    save_chat_turn("orphan turn", "c1", headline="h", sql="SELECT 1", session_id="")

    assert all(t["session_id"] for t in list_chat_sessions("c1"))


def test_the_rail_is_tenant_scoped(monkeypatch):
    """The same predicate the turns read uses: with identity enabled, one org's
    thread titles never reach another — titles are the user's own questions."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    with using_org("org-a"):
        _turn("org A's confidential question", "sess-org-a")
    with using_org("org-b"):
        _turn("org B's question", "sess-org-b")

    with using_org("org-b"):
        threads = list_chat_sessions("c1")

    ids = [t["session_id"] for t in threads]
    assert "sess-org-b" in ids
    assert "sess-org-a" not in ids, "another tenant's thread titles leaked"
