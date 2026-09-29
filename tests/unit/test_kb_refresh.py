"""A corrected KB entry reaches what was built from it — the plays seeded from it and the vectors
indexed from it — and nothing a person changed (the user, 2026-09-28: the AOV, return and refund
entries were corrected, and the install went on reading the old words until something was rebuilt).
"""
from __future__ import annotations

import pytest

from aughor.playbook import builder, store
from aughor.semantic import kb_retriever
from aughor.semantic.kb_loader import KBEntry

ENTRY = {
    "id": "ec_return_rate", "title": "Return Rate", "intent_tags": ["return rate"],
    "causal_relationships": [{"symptom": "returns rose", "check_in_order": ["category", "size"]}],
    "inflation_causes": [{"cause": "exchanges counted as returns"}],
    "deflation_causes": [{"cause": "returns table lags a week"}],
}


@pytest.fixture()
def playbook(tmp_path, monkeypatch):
    path = tmp_path / "playbook.json"
    monkeypatch.setenv("AUGHOR_PLAYBOOK_PATH", str(path))
    return path


def _kb(monkeypatch, **changed):
    monkeypatch.setattr(builder, "_load_all_kb", lambda: [{**ENTRY, **changed}])


def _seed(path) -> list:
    plays = [p.model_copy(update={"status": "active"}) for p in builder._build_entries_for_kb(ENTRY)]
    store.save_entries(plays, path)
    return plays


def test_a_corrected_entry_reaches_the_plays_built_from_it_as_their_next_version(playbook, monkeypatch):
    seeded = _seed(playbook)
    _kb(monkeypatch, title="Order Return Rate")
    assert builder.refresh_from_kb(playbook) == {"updated": 2, "kept_changed": 0}   # the two that name it
    now = {p.id: p for p in store.list_entries(playbook)}
    assert set(now) == {p.id for p in seeded}                                     # same plays, same ids
    inflated = next(p for p in now.values() if "inflation" in p.id)
    assert inflated.trigger_condition == "Order Return Rate appears inflated"
    assert inflated.status == "active" and inflated.version == 2
    assert store.get_version(inflated.id, 1, playbook)["content"]["trigger_condition"] == "Return Rate appears inflated"
    assert builder.refresh_from_kb(playbook) == {"updated": 0, "kept_changed": 0}   # idempotent


def test_a_play_a_person_reworded_keeps_their_words(playbook, monkeypatch):
    seeded = _seed(playbook)
    mine = next(p for p in seeded if "inflation" in p.id)
    store.save_entries([mine.model_copy(update={"recommendation": "Ask the warehouse team first."})], playbook)
    _kb(monkeypatch, title="Order Return Rate")
    assert builder.refresh_from_kb(playbook) == {"updated": 1, "kept_changed": 1}
    assert store.get_entry(mine.id, playbook).recommendation == "Ask the warehouse team first."


def test_a_play_a_person_deleted_is_not_brought_back(playbook, monkeypatch):
    seeded = _seed(playbook)
    gone = next(p for p in seeded if "inflation" in p.id)
    store._save_raw([p.model_dump() for p in store.list_entries(playbook) if p.id != gone.id], playbook)
    _kb(monkeypatch, title="Order Return Rate")
    builder.refresh_from_kb(playbook)
    assert gone.id not in {p.id for p in store.list_entries(playbook)}


def test_a_play_from_before_the_log_kept_content_is_refreshed_only_while_never_saved_again(playbook, monkeypatch):
    seeded = _seed(playbook)
    (playbook.parent / "playbook_versions.json").write_text("[]")                   # a log without content
    raw = store._load_raw(playbook)
    raw[[r["id"] for r in raw].index(next(p.id for p in seeded if "deflation" in p.id))]["version"] = 3
    store._save_raw(raw, playbook)
    _kb(monkeypatch, title="Order Return Rate")
    assert builder.refresh_from_kb(playbook) == {"updated": 1, "kept_changed": 1}


# ── the index ─────────────────────────────────────────────────────────────────────────────────

def _entry(pid: str, title: str) -> KBEntry:
    return KBEntry(pattern_id=pid, title=title, tier=2, source_file="ec.json", embed_text=title,
                   payload={"pattern_id": pid, "title": title, "source_file": "ec.json"})


@pytest.fixture()
def index(monkeypatch):
    """A stand-in index holding two entries, and a record of what gets embedded."""
    state = {"stored": [_entry("ec_aov", "AOV").payload, _entry("ec_return_rate", "Return Rate").payload],
             "embedded": []}
    monkeypatch.setattr(kb_retriever, "KB_ENABLED", True)
    monkeypatch.setattr(kb_retriever, "KB_PATH", "")
    monkeypatch.setattr("aughor.semantic.vector_store.collection_count", lambda c: len(state["stored"]))
    monkeypatch.setattr("aughor.semantic.vector_store.scroll_payloads", lambda c, limit=10_000: list(state["stored"]))
    monkeypatch.setattr(kb_retriever, "_embed_and_upsert",
                        lambda entries: state["embedded"].extend(e.pattern_id for e in entries) or len(entries))
    return state


def _packages(monkeypatch, *entries):
    monkeypatch.setattr("aughor.semantic.kb_loader.load_package_kb_entries", lambda: list(entries))


def test_only_the_entries_that_changed_are_embedded_again(index, monkeypatch):
    _packages(monkeypatch, _entry("ec_aov", "AOV"), _entry("ec_return_rate", "Order Return Rate"),
              _entry("ec_refund_rate", "Refund Rate"))                                  # one changed, one new
    assert kb_retriever.refresh_changed() == {"checked": 3, "refreshed": 2, "why": ""}
    assert index["embedded"] == ["ec_return_rate", "ec_refund_rate"]


def test_an_unchanged_index_embeds_nothing(index, monkeypatch):
    _packages(monkeypatch, _entry("ec_aov", "AOV"), _entry("ec_return_rate", "Return Rate"))
    assert kb_retriever.refresh_changed()["refreshed"] == 0 and index["embedded"] == []


def test_an_empty_or_unreadable_index_is_left_to_its_first_use_and_says_so(index, monkeypatch):
    _packages(monkeypatch, _entry("ec_aov", "AOV"))
    index["stored"] = []
    assert "empty" in kb_retriever.refresh_changed()["why"]
    monkeypatch.setattr("aughor.semantic.vector_store.collection_count", lambda c: 2)
    got = kb_retriever.refresh_changed()                                                # held, but none readable
    assert got["refreshed"] == 0 and "none could be read" in got["why"] and index["embedded"] == []


def test_more_changed_than_a_correction_is_a_reindex_and_is_not_done_at_startup(index, monkeypatch):
    _packages(monkeypatch, *[_entry(f"e{i}", "x") for i in range(kb_retriever.MAX_REFRESH + 1)])
    got = kb_retriever.refresh_changed()
    assert got["refreshed"] == 0 and "re-index" in got["why"] and index["embedded"] == []
