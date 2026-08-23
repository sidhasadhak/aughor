"""VA-7 — an agent's configuration history has to be readable as a CHANGE.

The plane itself shipped in Wave H6 and works: create records revision 1, an edit records
the next, a rename records nothing. The routes exist, the UI exists, restore exists. What
it could not do is say what an edit DID — the history rendered a truncated copy of the
instructions, so two revisions differing in schema scope looked identical and two
differing in one sentence of a long prompt looked identical too.

Measured against the live install on 2026-08-24: both custom agents had ZERO revisions.
The plane records revision 1 at creation and nothing ever backfilled the agents that
predate it, so for every agent that actually existed the first edit produced a one-sided
history — one entry, no predecessor, nothing to diff — under a UI that hides itself below
two entries. Complete, wired, and unreachable.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def agents(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_AGENTS_DB", str(tmp_path / "agents.db"))
    from aughor.custom_agents import store as s
    importlib.reload(s)
    from aughor.custom_agents import revisions as r
    return s, r


def test_a_new_agent_starts_with_the_configuration_it_was_born_with(agents):
    store, revisions = agents
    a = store.create_agent("A", instructions="v1", connection_id="c1")

    history = revisions.list_revisions(a.id)

    assert [h["version"] for h in history] == [1]
    assert history[0]["changed"] == [], "revision 1 changed nothing — it IS the beginning"


def test_an_edit_names_the_fields_it_moved(agents):
    store, revisions = agents
    a = store.create_agent("A", instructions="v1", connection_id="c1", schema_scope="public")
    store.update_agent(a.id, instructions="v2 rewritten", schema_scope="sales")

    head = revisions.list_revisions(a.id)[0]

    assert head["changed"] == ["instructions", "schema_scope"], (
        "without this the history shows two rows and no way to tell what an edit did")


def test_the_changed_list_follows_the_declared_field_order(agents):
    """The same edit must read the same way every time it is shown."""
    store, revisions = agents
    from aughor.custom_agents.models import GOVERNING_FIELDS
    a = store.create_agent("A", instructions="v1", connection_id="c1", schema_scope="public")
    store.update_agent(a.id, schema_scope="sales", instructions="v2")

    changed = revisions.list_revisions(a.id)[0]["changed"]
    assert changed == [f for f in GOVERNING_FIELDS if f in changed]


def test_a_list_field_that_did_not_move_is_not_reported_as_a_change(agents):
    """`doc_ids` and `pack_ids` come back from the store through `json.loads`, so they are
    a new list object on every read. Identity comparison would report every edit as
    touching them."""
    store, revisions = agents
    a = store.create_agent("A", instructions="v1", connection_id="c1", doc_ids=["d1", "d2"])
    store.update_agent(a.id, instructions="v2")

    assert revisions.list_revisions(a.id)[0]["changed"] == ["instructions"]


def test_a_truncated_window_says_unknown_rather_than_nothing_changed(agents):
    """The oldest entry of a LIMITED window has a predecessor that was not fetched.
    Reporting `[]` there would tell the reader that edit did nothing."""
    store, revisions = agents
    a = store.create_agent("A", instructions="v1", connection_id="c1")
    for i in range(3):
        store.update_agent(a.id, instructions=f"v{i + 2}")

    window = revisions.list_revisions(a.id, limit=2)

    assert len(window) == 2
    assert window[0]["changed"] == ["instructions"]
    assert window[1]["changed"] is None, "a truncated predecessor is unknown, not unchanged"


def test_an_agent_that_predates_the_plane_gets_a_baseline_on_its_first_edit(agents):
    """The measured case: every agent on the live install had no history at all.

    The row is inserted directly, which is exactly how those agents came to exist — they
    were created before anything recorded revisions.
    """
    store, revisions = agents
    from aughor.custom_agents.store import _connect, _now
    with _connect() as conn:
        conn.execute(
            "INSERT INTO user_agents (id, name, instructions, connection_id, doc_ids, "
            "owner, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("ua_legacy", "Legacy", "born before the plane", "c1", "[]", "", 1,
             _now(), _now()))

    assert revisions.list_revisions("ua_legacy") == [], "the premise of this test is gone"

    store.update_agent("ua_legacy", instructions="edited today")

    history = revisions.list_revisions("ua_legacy")
    assert [h["version"] for h in history] == [2, 1]
    assert history[1]["config"]["instructions"] == "born before the plane"
    assert history[1]["author"] == "baseline"
    assert history[0]["config"]["instructions"] == "edited today"
    assert history[0]["changed"] == ["instructions"], (
        "the first edit of a pre-existing agent must be readable as a change, not as a "
        "single orphan entry")


def test_the_baseline_is_written_once_not_on_every_edit(agents):
    store, revisions = agents
    a = store.create_agent("A", instructions="v1", connection_id="c1")
    store.update_agent(a.id, instructions="v2")
    store.update_agent(a.id, instructions="v3")

    history = revisions.list_revisions(a.id)
    assert [h["version"] for h in history] == [3, 2, 1]
    assert [h["author"] for h in history].count("baseline") == 0, (
        "an agent created through the plane already has revision 1; a baseline on top "
        "would duplicate it")


def test_a_rename_still_records_nothing(agents):
    """The rule the plane already had, kept honest while the write path changed."""
    store, revisions = agents
    a = store.create_agent("A", instructions="v1", connection_id="c1")
    store.update_agent(a.id, name="Renamed")

    assert [h["version"] for h in revisions.list_revisions(a.id)] == [1]
