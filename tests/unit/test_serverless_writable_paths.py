"""Four stores wrote to the bundle's `data/`, which is read-only on serverless.

Every write failed, loudly, on every boot. Measured over one 30-minute window in
production: 43 boots, each logging a failed playbook seed, plus 14 `doctree: persist
failed` and 12 `column-config save is best-effort`. The LLM runtime config was the
one with a user-visible symptom — a model chosen in Settings reverted on the next
cold start, so the app half-worked depending on which instance answered.

Redirecting them loses nothing: `.vercelignore` excludes `/data/*` apart from five
named files, so those paths ship EMPTY. The writes were failing against a directory
that is not in the bundle at all.

`/tmp` is per-instance, so this makes the stores work WITHIN an instance and stops
the noise. It is NOT durability — anything that must survive a cold start needs a
real store, which for the LLM binding means the env vars every instance reads
identically.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aughor.control_plane.writable_paths import WRITABLE_STORES, writable_store_paths


@pytest.fixture
def _clean_env(monkeypatch):
    for v in ("VERCEL", "AUGHOR_STATE_DIR", "AUGHOR_UPLOAD_DIR", "AUGHOR_LLM_CONFIG_PATH",
              "AUGHOR_ONTOLOGY_DOCS_DIR", "AUGHOR_COLUMN_CONFIG_ROOT",
              "AUGHOR_PLAYBOOK_PATH"):
        monkeypatch.delenv(v, raising=False)


REDIRECTED = (
    "AUGHOR_LLM_CONFIG_PATH",
    "AUGHOR_ONTOLOGY_DOCS_DIR",
    "AUGHOR_COLUMN_CONFIG_ROOT",
    "AUGHOR_PLAYBOOK_PATH",
)


def test_every_writable_store_lands_under_the_state_dir(tmp_path):
    """The mapping is asserted directly: importing `aughor.api` dials Postgres at
    import time, so a unit test cannot reach the block through the module."""
    got = writable_store_paths(tmp_path / "state")

    assert set(got) == set(REDIRECTED), "a store that writes files was left unredirected"
    for var, path in got.items():
        assert path.startswith(str(tmp_path / "state")), f"{var} points outside the state dir"


def test_applying_it_never_clobbers_an_operator_override(_clean_env, monkeypatch, tmp_path):
    """`setdefault`, not assignment — a deployment that has pointed a store at
    durable storage must keep its own value. This mirrors what api.py does."""
    monkeypatch.setenv("AUGHOR_PLAYBOOK_PATH", "/mnt/durable/playbook.json")

    for var, path in writable_store_paths(tmp_path / "state").items():
        os.environ.setdefault(var, path)

    assert os.environ["AUGHOR_PLAYBOOK_PATH"] == "/mnt/durable/playbook.json"
    assert os.environ["AUGHOR_LLM_CONFIG_PATH"].startswith(str(tmp_path / "state"))


def test_each_redirected_store_actually_reads_that_variable(_clean_env, tmp_path):
    """A rot guard, and the reason this file exists at all.

    Redirecting `AUGHOR_WRONG_NAME` would set an environment variable no store
    consults: every write would keep failing while the config looked right. So each
    name is checked against the store that owns it — three by resolving a path, and
    the LLM one by source, because `provider._CONFIG_PATH` is bound at IMPORT (api.py
    sets the variable before the provider is imported, which is why that ordering
    matters and why this is asserted rather than assumed).
    """
    import inspect

    from aughor.llm import provider
    from aughor.ontology import column_config, doctree
    from aughor.playbook import store

    # Iterates the REAL mapping, not a copy of it — a copy would keep passing while
    # the thing it claims to guard drifted underneath.
    owners = (provider, column_config, doctree, store)
    sources = "\n".join(inspect.getsource(m) for m in owners)
    for var in WRITABLE_STORES:
        assert var in sources, (
            f"{var} is redirected but no store reads it — the redirect is a silent no-op")

    # Stronger still where the store resolves at call time: set it and see it land.
    for var, resolve, target in (
        ("AUGHOR_PLAYBOOK_PATH", store._default_path, tmp_path / "pb.json"),
        ("AUGHOR_COLUMN_CONFIG_ROOT", column_config._root, tmp_path / "cc"),
    ):
        os.environ[var] = str(target)
        try:
            assert Path(resolve()) == target, f"{var} is not the variable that store reads"
        finally:
            os.environ.pop(var, None)


def test_the_playbook_resolves_its_path_at_call_time(_clean_env, monkeypatch, tmp_path):
    """It was the only store with no override at all, and resolving at IMPORT would
    freeze the bundle path before the serverless block could redirect it."""
    from aughor.playbook import store

    target = tmp_path / "pb.json"
    monkeypatch.setenv("AUGHOR_PLAYBOOK_PATH", str(target))
    assert store._default_path() == target
    assert store._versions_path() == tmp_path / "playbook_versions.json"

    monkeypatch.delenv("AUGHOR_PLAYBOOK_PATH")
    assert store._default_path() == store._BUNDLED_PATH


def test_the_playbook_round_trips_through_the_redirected_path(_clean_env, monkeypatch, tmp_path):
    """Not just the path — a write and a read-back, since the point is that the store
    can actually persist where it was pointed."""
    from aughor.playbook import store
    from aughor.playbook.models import PlaybookEntry

    monkeypatch.setenv("AUGHOR_PLAYBOOK_PATH", str(tmp_path / "pb.json"))
    entry = PlaybookEntry(id="p1", trigger_metric="m", trigger_condition="above",
                          recommendation="r")
    store.save_entry(entry)

    assert Path(tmp_path / "pb.json").exists(), "the play was not written where it was pointed"
    assert store.count_entries() == 1
    assert (tmp_path / "playbook_versions.json").exists(), "the version log went elsewhere"
