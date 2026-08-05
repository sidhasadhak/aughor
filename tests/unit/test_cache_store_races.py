"""The shared-file cache race, and the per-key store that ends it.

`briefing_cache.json` / `patterns_cache.json` / `schema_cache.json` were each ONE
file for every connection, updated by load→mutate→save of the whole dict. Two
writers working on DIFFERENT keys each rewrote the entire file, so the last write
silently dropped the other's work — no error, no missing-file symptom, just a
briefing that cost an LLM fan-out evaporating. The kernel Ledger's own docstring
names this race as the class it was built to end; these caches simply hadn't been
moved onto it.

The first test demonstrates the defect against the raw-file pattern; the rest pin
the store-backed behaviour that replaces it. Same philosophy as
test_llm_coordination.py: the problem is demonstrated, not described.
"""
from __future__ import annotations

import json
import threading

import pytest


# ── the defect, demonstrated against the raw pattern ─────────────────────────

def test_whole_file_rewrite_loses_a_concurrent_writers_key(tmp_path):
    """Two writers, two different keys, interleaved as load→mutate→save: the last
    save wins and the first writer's key is gone. This is what every one of these
    caches did."""
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({}))

    # Deterministic interleave: both load BEFORE either saves.
    a_view = json.loads(path.read_text())
    b_view = json.loads(path.read_text())
    a_view["briefing:conn_a"] = {"narrative": "A's expensive briefing"}
    path.write_text(json.dumps(a_view))
    b_view["briefing:conn_b"] = {"narrative": "B's expensive briefing"}
    path.write_text(json.dumps(b_view))

    survived = json.loads(path.read_text())
    assert "briefing:conn_a" not in survived      # ← A's work silently dropped


# ── the fix: per-key upserts through the facade ──────────────────────────────

@pytest.fixture
def briefing_store(tmp_path, monkeypatch):
    from aughor.knowledge import briefing
    monkeypatch.setattr(briefing, "_CACHE_PATH", tmp_path / "briefing_cache.json")
    return briefing


def test_concurrent_scope_writes_both_survive(briefing_store):
    """The same interleave through the store: neither writer carries the whole
    cache, so neither can drop the other's key. Threads make it a real interleave,
    not a staged one."""
    store = briefing_store._store()
    barrier = threading.Barrier(2)

    def write(scope: str):
        barrier.wait()
        store.put(scope, {"narrative": f"{scope}'s briefing"})

    threads = [threading.Thread(target=write, args=(s,))
               for s in ("conn_a", "conn_b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert set(briefing_store._store().load()) == {"conn_a", "conn_b"}


def test_invalidate_leaves_a_concurrent_scopes_entry(briefing_store):
    """The 2026-08-03 lesson — purge per-key, never wholesale — now holds by
    construction: invalidating one connection cannot rewrite (and race) the rest."""
    b = briefing_store
    st = b._store()
    st.put("conn_a", {"narrative": "a"})
    st.put("conn_a:main", {"narrative": "a-main"})
    st.put("conn_b", {"narrative": "b"})
    assert b.invalidate("conn_a") == 2
    assert set(b._store().load()) == {"conn_b"}
    assert b.invalidate("conn_a") == 0            # idempotent, counts real removals


def test_legacy_file_imports_once_then_rests(briefing_store, tmp_path):
    """Migration contract: an existing briefing_cache.json is read into the store on
    first use and the file is never rewritten — its mtime-era content stays as the
    on-disk record it was."""
    legacy = {"conn_legacy": {"narrative": "from the file era"}}
    briefing_store._CACHE_PATH.write_text(json.dumps(legacy))
    assert briefing_store.peek_briefing("conn_legacy")["narrative"] == "from the file era"
    briefing_store._store().put("conn_new", {"narrative": "post-migration"})
    # The file still holds ONLY the legacy content; new writes go to the store.
    assert json.loads(briefing_store._CACHE_PATH.read_text()) == legacy


def test_schema_cache_mru_eviction_holds_through_the_store(tmp_path, monkeypatch):
    """The eviction contract the module used to hand-roll survives the move: oldest
    entry out past the cap, most-recently-touched retained."""
    from aughor.db import schema_cache
    monkeypatch.setattr(schema_cache, "_CACHE_PATH", tmp_path / "schema_cache.json")
    monkeypatch.setattr(schema_cache, "_MAX_ENTRIES", 3)
    for fp in ("fp1", "fp2", "fp3"):
        schema_cache.mark_complete(fp)
    schema_cache.mark_complete("fp1")     # touch: fp1 becomes most-recent
    schema_cache.mark_complete("fp4")     # over cap → oldest (fp2) evicted
    assert schema_cache.is_complete("fp1")
    assert schema_cache.is_complete("fp4")
    assert not schema_cache.is_complete("fp2")
