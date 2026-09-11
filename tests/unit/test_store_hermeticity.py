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
    from aughor.notifications import store as astore
    assert "aughor-test-stores" in str(astore._TRIGGERS_PATH)
    assert "aughor-test-stores" in str(astore._LOGS_PATH)


def test_agents_db_default_is_under_data_not_repo_root():
    # The default path (used when AUGHOR_AGENTS_DB is unset) must live under data/ so it
    # is covered by data/'s gitignore — the bare "agents.db" default escaped it and got
    # a live runtime DB tracked in git.
    from aughor.custom_agents import store
    assert store._DEFAULT_DB_PATH == pathlib.Path("data") / "agents.db"

# ── 2026-07-21: the family WP-4 MISSED — per-connection GENERATED state. Each of these
# hardcoded Path("data") with no override, so the suite wrote and DELETED a developer's real
# files. A full-suite run destroyed a live exploration_workspace.json holding 89 findings;
# data/*.json is gitignored, so there was nothing to recover from. All now resolve
# AUGHOR_STATE_DIR (aughor/db/paths.py), which the conftest points at the temp dir. ────────

def test_exploration_store_dir_is_isolated():
    from aughor.explorer import store
    assert "aughor-test-stores" in str(store._DATA_DIR)


def test_profile_store_dir_is_isolated():
    from aughor.business_profile import store as profile_store
    assert "aughor-test-stores" in str(profile_store._DATA_DIR)


def test_briefing_and_patterns_caches_are_isolated():
    from aughor.knowledge import briefing, patterns
    assert "aughor-test-stores" in str(briefing._CACHE_PATH)
    assert "aughor-test-stores" in str(patterns._CACHE_PATH)


def test_explore_watermark_is_isolated():
    from aughor.explorer import watermark
    assert "aughor-test-stores" in str(watermark._PATH)


def test_schema_fingerprint_cache_is_isolated():
    """Found by the whole-directory canary, not by reasoning about which stores exist —
    it was a repo-absolute Path(__file__)…/data/ with no override, so it never appeared in
    any AUGHOR_* audit."""
    from aughor.db import schema_cache
    assert "aughor-test-stores" in str(schema_cache._CACHE_PATH)


def test_ontology_overrides_and_export_trees_are_isolated():
    """ON-1b — the overrides tree had no override, so a measure-door test that cached a graph under a real
    connection id wrote that connection's live override file: LuxExperience's Order bindings came back counted
    over a three-row fixture. The tree and its export sibling now resolve AUGHOR_* dirs the conftest points at
    the temp dir, and `resolve_db_path` puts both in front of the generic guard below."""
    from aughor.ontology import filetree, overrides, recommendations
    assert "aughor-test-stores" in str(overrides.overrides_root())
    assert str(overrides.overrides_root()).endswith("ontology_overrides")
    assert "aughor-test-stores" in str(filetree._EXPORT_ROOT)
    assert "aughor-test-stores" in str(recommendations._ROOT)      # the family's third writer, same fix


def test_embedded_qdrant_path_is_isolated():
    """S1 — the embedded semantic index is a lock-holding DIRECTORY, so a leak here
    is worse than dirty data: local mode's exclusive lock would also contend with a
    running API. Resolved per call (never captured at import), so the conftest
    assignment is what every open sees."""
    from aughor.semantic import vector_store
    assert "aughor-test-stores" in vector_store._embedded_path()


def test_purge_resolves_the_SAME_dir_as_the_stores_it_deletes_from():
    """The second half of the incident: purge.py held its own Path("data"), so it UNLINKED
    from the live dir even when the store it was purging had been redirected. A redirect that
    the deleter doesn't share isn't isolation — it just moves the writes and keeps the
    deletes on the real files."""
    from aughor.db import purge
    from aughor.explorer import store
    from aughor.business_profile import store as profile_store
    assert "aughor-test-stores" in str(purge._DATA_DIR)
    assert purge._DATA_DIR == store._DATA_DIR == profile_store._DATA_DIR


def test_state_dir_defaults_to_data_when_env_unset(monkeypatch):
    """Unset → data/, i.e. production behaviour is byte-identical to before the fix."""
    from aughor.db.paths import STATE_DIR_ENV, state_dir
    monkeypatch.delenv(STATE_DIR_ENV, raising=False)
    assert state_dir() == pathlib.Path("data")


def test_no_generated_state_store_still_hardcodes_the_data_dir():
    """Ratchet: a NEW per-connection store must resolve the shared dir, not re-hardcode it.
    Scoped to the modules in this family — authored-file readers legitimately use data/."""
    import re
    root = pathlib.Path(__file__).resolve().parents[2] / "aughor"
    offenders = [
        str(p.relative_to(root))
        for p in [root / "explorer" / "store.py", root / "explorer" / "watermark.py",
                  root / "explorer" / "revalidate_live.py", root / "business_profile" / "store.py",
                  root / "knowledge" / "briefing.py", root / "knowledge" / "patterns.py",
                  root / "db" / "purge.py", root / "routers" / "exploration.py",
                  root / "db" / "schema_cache.py"]
        if re.search(r'Path\(\s*["\']data["\']\s*\)|parent\s*/\s*["\']data["\']', p.read_text())
    ]
    assert offenders == [], f"re-hardcoded data/ instead of state_dir(): {offenders}"


def test_no_store_path_is_left_to_the_inherited_environment():
    """Every isolation path is ASSIGNED in conftest, never `setdefault`.

    The sibling guard above asks where a store RESOLVES, and answers "not inside the repo's
    `data/`" — which a reused `/tmp/throwaway.db` satisfies. So an inherited override that
    points somewhere harmless passes it, and the suite quietly becomes stateful across runs:
    four modules accumulate ledger rows and fail on the second run against one file, with
    the same code that passes on a fresh one.

    That is the likelier mistake rather than an exotic one, because exporting a throwaway
    ledger is the RIGHT habit for a bare script — which would otherwise open
    `data/system.db` beside a running API. This asserts the mechanism, because the runtime
    property cannot tell `setdefault` from assignment in a clean environment: in the only
    environment where they differ, the guard would already be running against the wrong
    store.

    Behaviour flags (`AUGHOR_API_KEY`, `AUGHOR_AUTOSEED`, `AUGHOR_SKIP_DOTENV`) are
    deliberately NOT covered — inheriting those is sometimes exactly what a developer wants,
    and none of them decides where a byte gets written.
    """
    import ast

    conftest = pathlib.Path(__file__).resolve().parents[1] / "conftest.py"
    source = conftest.read_text()
    tree = ast.parse(source)

    #: A `setdefault` mentioning any of these is pointing at the suite's own temp dirs, so
    #: it is an isolation path wearing an escape hatch.
    ISOLATION_MARKERS = ("_test_stores_dir", "_test_registry_dir", "tempfile.mkdtemp",
                         "_packs_dst", "_dst")

    offenders, seen_any = [], False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "setdefault":
            continue
        value = getattr(node.func, "value", None)
        if not (isinstance(value, ast.Attribute) and value.attr == "environ"):
            continue
        seen_any = True
        text = ast.get_source_segment(source, node) or ""
        if any(marker in text for marker in ISOLATION_MARKERS):
            offenders.append(text.replace("\n", " ")[:100])

    assert seen_any, "found no os.environ.setdefault calls in conftest — this guard is blind"
    assert not offenders, (
        "these conftest lines let an inherited environment variable choose where a store "
        f"lives: {offenders}. Assign them (`os.environ[X] = ...`) so the suite always gets "
        f"its own. A test that needs a specific store uses monkeypatch.setenv, which runs "
        f"later and still wins.")


def test_every_store_env_override_is_pointed_at_the_test_dir():
    """The generic guard the per-store tests above cannot be: find the overrides in the
    CODE, then check the environment the suite is actually running in.

    Every test in this file names one store, which means each was written after that store
    leaked — the list only ever grows by costing somebody their data. `resolve_db_path` is
    the one seam every SQLite store passes through, so the call sites are enumerable, and a
    store added tomorrow without a conftest line fails here instead of quietly writing to
    the developer's `data/` directory for a whole suite run.

    Checked against `os.environ` rather than by parsing conftest: what matters is where the
    path RESOLVES, not whether a line appears in a list. And the property asserted is "not
    inside the repo's data/", not "inside one named temp dir" — the ledger and the registry
    each get their own temp directory, and a guard that insisted on one prefix would have
    reported those two as leaks and taught the next reader to loosen it.
    """
    import ast
    import os

    root = pathlib.Path(__file__).resolve().parents[2] / "aughor"
    found: dict[str, str] = {}
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:                      # not ours to police here
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "resolve_db_path":
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found[first.value] = str(path.relative_to(root))

    assert found, "found no resolve_db_path call sites — this guard has gone blind"
    repo_data = (root.parent / "data").resolve()

    def _leaks(env: str) -> bool:
        resolved = pathlib.Path(os.environ.get(env, "") or "").resolve()
        return not os.environ.get(env) or repo_data in resolved.parents or resolved == repo_data

    unisolated = {env: where for env, where in sorted(found.items()) if _leaks(env)}
    assert unisolated == {}, (
        "these stores resolve to a path outside the suite's temp dir, so the tests write "
        f"the developer's live data/: {unisolated}. Add each to the list in tests/conftest.py")


# ── 2026-09-11: the two stores the guard above could not see. `resolve_db_path` is one
# way to resolve a store path; reading `os.environ` yourself is another, and these took
# it — upload storage (`control_plane/vending.STORAGE_ROOT`, bound at IMPORT) and the
# playbook (`playbook/store._default_path`, resolved per call). Neither passes through
# that seam, so the population never contained them and the guard could not have failed.
# A full suite run from a fresh worktree wrote `data/uploads/default/workspace/
# rearm_single/{orders.csv,orders.csv.import.json}` and seeded `data/playbook.json` +
# `data/playbook_versions.json` into the checkout; the live tree already held copies of
# those two upload files dated 2026-08-12, so an earlier run had put a test schema in a
# real workspace's upload store. ──────────────────────────────────────────────────────

def test_upload_root_is_isolated():
    """Asserted on the ENVIRONMENT and on a fresh resolution rather than on
    `vending.STORAGE_ROOT`: that global is bound at import, and `test_object_store.py`
    reloads the module under a patched env, which leaves the reloaded binding pointing at
    a dead per-test tmp dir for the rest of the session. So this pins the property the
    incident actually broke — upload storage never resolves inside the repo's `data/` —
    which no test ordering can satisfy by accident."""
    import os

    from aughor.control_plane import vending

    repo_data = (pathlib.Path(__file__).resolve().parents[2] / "data").resolve()
    configured = pathlib.Path(os.environ["AUGHOR_UPLOAD_DIR"]).resolve()
    assert "aughor-test-stores" in str(configured), "the suite did not point upload storage anywhere"
    assert repo_data != configured and repo_data not in configured.parents

    live = pathlib.Path(vending.vend_storage("probe").root).resolve()
    assert repo_data not in live.parents, f"upload storage vends into the repo: {live}"


def test_playbook_and_its_version_log_are_isolated():
    """The version log is a SIBLING of the playbook file, so pointing the playbook alone
    would still have left the append-only history landing in the repo."""
    from aughor.playbook import store
    assert "aughor-test-stores" in str(store._default_path())
    assert "aughor-test-stores" in str(store._versions_path())


def test_every_env_pathed_store_is_pointed_outside_the_repo_data_dir():
    """The sibling of the generic guard above, for the stores it structurally cannot see.

    That one's population is `resolve_db_path` call sites, so a store reading `os.environ`
    itself never appears in it. This takes a population from the code by two other routes:
    every `os.environ.get("AUGHOR_…")` whose own expression falls back to a path under the
    repo's `data/`, plus every entry in the serverless `WRITABLE_STORES` registry — the
    playbook needs the registry, because its fallback is a module constant rather than a
    literal in the call.

    Both sources are DERIVED, never listed here: a store added tomorrow that reads its env
    var inline, or that registers itself as writable, joins this population the moment it
    exists. A list in this file would only ever grow after somebody's data paid for it.
    """
    import ast
    import os

    from aughor.control_plane.writable_paths import WRITABLE_STORES

    root = pathlib.Path(__file__).resolve().parents[2] / "aughor"
    found: dict[str, str] = {var: "control_plane/writable_paths.py" for var in WRITABLE_STORES}

    def _falls_back_to_repo_data(segment: str) -> bool:
        return any(hint in segment for hint in ('"data"', "'data'", '"data/', "'data/"))

    for path in root.rglob("*.py"):
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:                      # not ours to police here
            continue
        # `os.environ.get(VAR) or <default>` puts the default in the enclosing BoolOp,
        # not in the call, so the fallback has to be read from around the call.
        enclosing: dict[int, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp):
                segment = ast.get_source_segment(source, node) or ""
                for child in ast.walk(node):
                    enclosing.setdefault(id(child), segment)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            reads_env = name == "getenv" or (
                name == "get" and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ")
            first = node.args[0]
            if not (reads_env and isinstance(first, ast.Constant)
                    and isinstance(first.value, str) and first.value.startswith("AUGHOR_")):
                continue
            segment = enclosing.get(id(node)) or ast.get_source_segment(source, node) or ""
            if _falls_back_to_repo_data(segment):
                found.setdefault(first.value, str(path.relative_to(root)))

    assert len(found) > len(WRITABLE_STORES), (
        "found no inline env-pathed store defaults — the AST half of this guard has gone "
        "blind and only the registry is left")
    repo_data = (root.parent / "data").resolve()

    def _leaks(env: str) -> bool:
        resolved = pathlib.Path(os.environ.get(env, "") or "").resolve()
        return not os.environ.get(env) or repo_data in resolved.parents or resolved == repo_data

    unisolated = {env: where for env, where in sorted(found.items()) if _leaks(env)}
    assert unisolated == {}, (
        "these stores read their own env var and fall back into the repo's data/, and the "
        f"suite has not pointed them anywhere else: {unisolated}. Add each to the list in "
        "tests/conftest.py (and to scripts/dump_openapi.py, its sibling)")
