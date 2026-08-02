"""Wave V3 — artifact lifecycle: save≠publish, versions, changelog, revert.

Pre-registered gate, all four parts asserted here:
* an editor's unpublished edit is invisible to a viewer (``test_gate_save_is_not_publish``);
* publish makes it visible (same test);
* revert restores **byte-identical** prior content (``test_gate_revert_is_byte_identical``);
* the changelog names a moved element a **move** (``test_gate_changelog_names_a_move``).
"""
from __future__ import annotations

import pytest

from aughor.kernel.lifecycle import (
    PROJECTIONS,
    changelog,
    diff_versions,
    history,
    publication_state,
    publish,
    resolve,
    revert,
    revision,
    save_draft,
)

KIND, NK = "savedquery", "savedquery:q1"


@pytest.fixture
def _on(monkeypatch, tmp_path):
    # Ledger.default() is keyed on AUGHOR_SYSTEM_DB, so a per-test path gives each test a
    # fresh artifact table — without this, versions written by one test are history in the
    # next and every version assertion drifts.
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))


# ── The flag contract ─────────────────────────────────────────────────────────

def test_gate_save_is_not_publish(_on):
    """A viewer must never see an in-progress draft — the whole point of the wave."""
    v1 = save_draft(KIND, NK, {"title": "published copy"})
    published = publish(KIND, NK)
    assert published.is_published

    # an editor now saves an unfinished edit
    save_draft(KIND, NK, {"title": "WIP — do not ship"})

    viewer = resolve(KIND, NK, audience="viewer")
    editor = resolve(KIND, NK, audience="editor")
    assert viewer.body == {"title": "published copy"}      # unchanged
    assert editor.body == {"title": "WIP — do not ship"}   # working copy
    assert viewer.version < editor.version
    assert v1.version == 1

    # publishing promotes the draft; now the viewer sees it
    publish(KIND, NK)
    assert resolve(KIND, NK, audience="viewer").body == {"title": "WIP — do not ship"}


def test_gate_revert_is_byte_identical(_on):
    original = {"sql": "SELECT 1", "spec": {"dims": ["a", "b"], "limit": 10}}
    save_draft(KIND, NK, original)
    publish(KIND, NK)
    save_draft(KIND, NK, {"sql": "SELECT 2", "spec": {"dims": ["z"], "limit": 99}})

    reverted = revert(KIND, NK, to_version=1)
    assert reverted.body == original                       # byte-identical content
    assert reverted.version > 3, "revert writes FORWARD, never rewinds history"
    assert revision(KIND, NK, version=1).body == original  # history intact


def test_gate_changelog_names_a_move():
    """Reordering is the commonest edit; a differ without move detection reports it as a
    pile of deletes and adds."""
    before = {"cards": ["revenue", "orders", "returns"]}
    after = {"cards": ["returns", "revenue", "orders"]}

    changes = changelog(before, after)
    kinds = {c.kind for c in changes}
    assert "move" in kinds, [c.describe() for c in changes]
    assert "delete" not in kinds and "add" not in kinds, [c.describe() for c in changes]
    assert any("moved" in c.describe() for c in changes)


# ── Changelog behaviour ───────────────────────────────────────────────────────

def test_changelog_reports_add_delete_change_distinctly():
    changes = {c.kind: c for c in changelog(
        {"keep": 1, "gone": 2, "edit": "a"},
        {"keep": 1, "edit": "b", "fresh": 3},
    )}
    assert set(changes) == {"delete", "change", "add"}
    assert changes["change"].before == "a" and changes["change"].after == "b"
    assert changes["delete"].path == "gone"
    assert changes["add"].path == "fresh"


def test_changelog_identical_bodies_have_no_changes():
    body = {"a": [1, 2, {"b": "c"}]}
    assert changelog(body, dict(body)) == []


def test_changelog_move_matches_dicts_regardless_of_key_order():
    """A moved object is recognised by CONTENT, not serialisation order — so a renamed key
    holding the same object reads as one move, not a delete plus an unrelated add."""
    before = {"old_name": {"x": 1, "y": 2}}
    after = {"new_name": {"y": 2, "x": 1}}
    changes = changelog(before, after)
    assert [c.kind for c in changes] == ["move"], [c.describe() for c in changes]
    assert changes[0].to_path == "new_name"


def test_changelog_reordered_list_of_objects_is_moves_not_rewrites():
    """The dashboard-card case: objects, not scalars."""
    before = {"cards": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
    after = {"cards": [{"id": "c"}, {"id": "a"}, {"id": "b"}]}
    kinds = [c.kind for c in changelog(before, after)]
    assert kinds and set(kinds) == {"move"}, kinds


def test_changelog_edit_in_place_names_the_field_not_a_replacement():
    """An element edited at its own index should report the changed FIELD, not
    delete-plus-add of the whole object."""
    before = {"cards": [{"id": "a", "title": "old"}]}
    after = {"cards": [{"id": "a", "title": "new"}]}
    changes = changelog(before, after)
    assert [(c.kind, c.path) for c in changes] == [("change", "cards[0].title")]


def test_changelog_append_is_an_add_only():
    changes = changelog({"cards": ["a"]}, {"cards": ["a", "b"]})
    assert [(c.kind, c.path) for c in changes] == [("add", "cards[1]")]


def test_changelog_removal_is_a_delete_only():
    changes = changelog({"cards": ["a", "b"]}, {"cards": ["a"]})
    assert [(c.kind, c.path) for c in changes] == [("delete", "cards[1]")]


def test_changelog_a_deleted_and_a_different_add_are_not_a_move():
    changes = {c.kind for c in changelog({"a": "one"}, {"b": "two"})}
    assert changes == {"change"} or changes == {"delete", "add"}, changes


def test_changelog_nested_path_is_reported():
    changes = changelog({"spec": {"limit": 10}}, {"spec": {"limit": 20}})
    assert [c.path for c in changes] == ["spec.limit"]


def test_diff_versions_summarises(_on):
    save_draft(KIND, NK, {"n": 1, "keep": True})
    save_draft(KIND, NK, {"n": 2, "keep": True})
    d = diff_versions(KIND, NK, 1, 2)
    assert d.summary == {"change": 1}
    assert d.from_version == 1 and d.to_version == 2


def test_diff_versions_missing_version_is_none(_on):
    save_draft(KIND, NK, {"n": 1})
    assert diff_versions(KIND, NK, 1, 99) is None


# ── History / versioning ──────────────────────────────────────────────────────

def test_history_is_newest_first_and_versions_increment(_on):
    for i in range(3):
        save_draft(KIND, NK, {"n": i})
    versions = [r.version for r in history(KIND, NK)]
    assert versions == sorted(versions, reverse=True)
    assert len(versions) == 3


def test_viewer_sees_nothing_until_something_is_published(_on):
    save_draft(KIND, NK, {"n": 1})
    assert resolve(KIND, NK, audience="viewer") is None
    assert resolve(KIND, NK, audience="editor") is not None


def test_publish_a_specific_older_version(_on):
    save_draft(KIND, NK, {"pick": "me"})
    save_draft(KIND, NK, {"pick": "not me"})
    published = publish(KIND, NK, version=1)
    assert published.body == {"pick": "me"}
    assert resolve(KIND, NK, audience="viewer").body == {"pick": "me"}


def test_publish_with_no_artifact_is_none(_on):
    assert publish(KIND, "savedquery:never-saved") is None


def test_revert_can_publish_immediately(_on):
    save_draft(KIND, NK, {"v": "one"})
    publish(KIND, NK)
    save_draft(KIND, NK, {"v": "two"})
    publish(KIND, NK)
    r = revert(KIND, NK, to_version=1, publish_now=True)
    assert r.is_published
    assert resolve(KIND, NK, audience="viewer").body == {"v": "one"}


# ── Convergence by projection ─────────────────────────────────────────────────

@pytest.mark.parametrize("vocab,status,expected", [
    ("governance", "draft", "draft"),
    ("governance", "proposed", "draft"),       # proposing is not publishing
    ("governance", "approved", "published"),
    ("governance", "deprecated", "archived"),
    ("playbook", "active", "published"),
    ("playbook", "draft", "draft"),
    ("packs", "active", "published"),
    ("lifecycle", "published", "published"),
])
def test_projection_table(vocab, status, expected):
    assert publication_state(vocab, status) == expected


def test_unknown_status_projects_to_draft_not_published():
    """routers/metrics.py accepts a free-form status with no gate, so the default must be
    the conservative direction: show a viewer nothing rather than something unreadable."""
    assert publication_state("governance", "banana") == "draft"
    assert publication_state("nonexistent-vocabulary", "approved") == "draft"
    assert publication_state("governance", None) == "draft"


def test_every_projection_lands_on_the_publication_axis():
    valid = {"draft", "published", "archived"}
    for vocab, table in PROJECTIONS.items():
        for status, projected in table.items():
            assert projected in valid, f"{vocab}.{status} → {projected}"


def test_projections_cover_the_real_state_machines():
    """If a store adds a state, its projection must be decided rather than defaulted."""
    from aughor.packs.models import _STATUSES
    from aughor.semantic.governance import STATES

    assert set(STATES) <= set(PROJECTIONS["governance"])
    assert set(_STATUSES) <= set(PROJECTIONS["packs"])


# ── The savedquery wiring ─────────────────────────────────────────────────────

def test_savedquery_update_records_a_revision(_on, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_SAVEDQUERY_DB", str(tmp_path / "sq.db"))
    import importlib

    from aughor.savedquery import store as sq
    importlib.reload(sq)

    q = sq.create_saved_query(connection_id="c1", name="v1", sql="SELECT 1", spec={"a": 1})
    sq.update_saved_query(q.id, name="v2", sql="SELECT 2")

    revs = history("savedquery", f"savedquery:{q.id}")
    assert len(revs) == 1, "the UPDATE is what creates the first revision"
    assert revs[0].body["sql"] == "SELECT 2"
    assert revs[0].state == "draft", "an edit is a draft until published"


