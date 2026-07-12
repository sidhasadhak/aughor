"""task_213affac — the glossary / metrics file stores must be test-isolated.

These were hardcoded to data/glossary.yaml and data/metrics.json with no env override, so the
autoseed / knowledge-sync WRITE path (no `path=` arg) mutated the LIVE files during the suite — a
glossary edit leaked into two commits before this was fixed. The stores now resolve
AUGHOR_GLOSSARY_PATH / AUGHOR_METRICS_PATH (conftest points them at a throwaway temp COPY of the real
file), mirroring the SQLite-store isolation. These tests pin the isolation and the read-content parity.
"""
from __future__ import annotations

import pathlib

from aughor.semantic import glossary, metrics


def test_glossary_and_metrics_paths_are_isolated():
    for p in (str(glossary._default_path()), str(metrics._default_path())):
        assert "aughor-test-stores" in p          # the conftest temp dir, not the repo data/ dir
    assert str(glossary._default_path()).endswith("glossary.yaml")
    assert str(metrics._default_path()).endswith("metrics.json")


def test_reads_still_see_the_real_content_via_the_copy():
    # The temp copy preserves content, so enrichment / metric grounding behave as in production.
    assert isinstance(glossary.load_glossary(), dict)
    assert isinstance(metrics.list_metrics(), list)


def test_no_path_glossary_write_never_touches_the_repo_file():
    repo_file = pathlib.Path(glossary._DEFAULT_PATH)          # the real data/glossary.yaml
    temp_file = glossary._default_path()                      # the isolated session copy
    before_repo = repo_file.read_bytes() if repo_file.exists() else None
    before_temp = temp_file.read_bytes() if temp_file.exists() else None
    try:
        glossary.update_table("__hermeticity_probe__", description="must not hit the repo file")
        assert (repo_file.read_bytes() if repo_file.exists() else None) == before_repo   # repo untouched
        assert "__hermeticity_probe__" in (glossary.load_glossary().get("tables") or {})  # landed in temp
    finally:
        if before_temp is not None:
            temp_file.write_bytes(before_temp)               # restore the shared session copy


# ── WP-4: the four stores that had no env override (matcache / episodes / memory /
# actions). Each was hardcoded to the live data/ dir, so the suite wrote (or, for a
# canvas clear, DELETED) a developer's real files. Every one now resolves an AUGHOR_*
# env the conftest points at the throwaway temp dir. ─────────────────────────────────

def test_matcache_path_is_isolated():
    from aughor.db import matcache
    assert "aughor-test-stores" in str(matcache._CACHE_PATH)
    assert str(matcache._CACHE_PATH).endswith("mat_cache.duckdb")


def test_episodes_dir_is_isolated():
    from aughor.explorer.episodes import episodes_dir
    assert "aughor-test-stores" in str(episodes_dir())


def test_memory_paths_are_isolated():
    from aughor.memory.paths import agent_runs_path, learned_actions_path
    assert "aughor-test-stores" in agent_runs_path()
    assert "aughor-test-stores" in learned_actions_path()


def test_actions_paths_are_isolated():
    from aughor.actions import store as astore
    assert "aughor-test-stores" in str(astore._TRIGGERS_PATH)
    assert "aughor-test-stores" in str(astore._LOGS_PATH)


def test_agents_db_default_is_under_data_not_repo_root():
    # The default path (used when AUGHOR_AGENTS_DB is unset) must live under data/ so it
    # is covered by data/'s gitignore — the bare "agents.db" default escaped it and got
    # a live runtime DB tracked in git.
    from aughor.user_agents import store
    assert store._DEFAULT_DB_PATH == pathlib.Path("data") / "agents.db"
