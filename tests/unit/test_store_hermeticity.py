"""task_213affac — the glossary / metrics file stores must be test-isolated.

These were hardcoded to data/glossary.yaml and data/metrics.json with no env override, so the
autoseed / knowledge-sync WRITE path (no `path=` arg) mutated the LIVE files during the suite — a
glossary edit leaked into two commits before this was fixed. The stores now resolve
AUGHOR_GLOSSARY_PATH / AUGHOR_METRICS_PATH (conftest points them at a throwaway temp COPY of the real
file), mirroring the SQLite-store isolation. These tests pin the isolation and the read-content parity.
"""
from __future__ import annotations

import ast
import functools
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

from aughor.semantic import glossary, metrics

_REPO = pathlib.Path(__file__).resolve().parents[2]


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

    The call sites come from `_environment_reads`, which also resolves a name held in a module
    constant — `resolve_db_path(STATE_DIR_ENV, …)`. The literals-only scan this used to run
    could not see the four stores that resolve that way (the state dir, the industry choice,
    both pack roots); all four happened to be isolated already.
    """
    reads, _ = _environment_reads()
    found = {env: where["resolve_db_path"] for env, where in reads.items() if "resolve_db_path" in where}

    assert found, "found no resolve_db_path call sites — this guard has gone blind"
    repo_data = (_REPO / "data").resolve()

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
        # not in the call, so the fallback has to be read from around the call — from the
        # OUTERMOST BoolOp above it. `ast.walk` is breadth-first, so each parent is reached
        # before its children and hands them that BoolOp in the same pass.
        outermost_boolop: dict[int, ast.BoolOp] = {}
        for node in ast.walk(tree):
            around = outermost_boolop.get(id(node))
            if around is None and isinstance(node, ast.BoolOp):
                around = node
            if around is not None:
                for child in ast.iter_child_nodes(node):
                    outermost_boolop[id(child)] = around
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
            # Sliced here, for the calls that got this far, and never per BoolOp: on 3.11
            # `get_source_segment` re-splits the whole file in pure Python on every call, so
            # slicing all ~10k BoolOps up front was ~70s of this test (measured 2026-09-17).
            segment = ast.get_source_segment(source, outermost_boolop.get(id(node), node)) or ""
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


# ── 2026-09-17: the LIVE-DRIVE isolation. `scripts/dump_openapi._isolate_stores()` is not only
# the spec dump's: live drives (scratch API servers started to verify a change) and the SP-M
# recorder import it, and its comment said it was "kept equal to tests/conftest.py's allowlist BY
# MEASUREMENT". It was not. A scratch API started after it created data/org_llm.db inside a
# worktree — from the main checkout, that file is the live deployment's org model config. Measured
# the same day, with both bodies run from an empty environment: the conftest pinned 75 stores and
# the helper 54, 22 of the suite's stores were missing from the helper, and one of the helper's
# names (AUGHOR_ORGSETTINGS_DB) is read by no code at all. A comment that says "by measurement" is
# not a measurement, so these tests are. ─────────────────────────────────────────────────────────

#: Stores the suite isolates that a live drive deliberately READS from the checkout. Each entry is
#: re-checked below (still read by the code, still isolated by the suite, still left alone by the
#: helper), so an exclusion cannot quietly outlive its reason.
LIVE_DRIVE_READS_FROM_THE_CHECKOUT = {
    "AUGHOR_PACKS_DIR": (
        "the authored package tree (the tracked packs/): a drive must see the real packages. Not "
        "free of writes: promotion rewrites pack.yaml, which is why the suite isolates a COPY — a "
        "drive from the main checkout that promotes a pack changes the tree the running API reads, "
        "visibly, in git status."),
    "AUGHOR_SAMPLES_DB": (
        "the bundled samples warehouse, opened and ATTACHed read-only. Nothing outside the suite "
        "seeds it (re-measured below), so a drive can only read it; isolated, a drive would lose "
        "the samples connection with no way to get it back."),
}


@functools.lru_cache(maxsize=1)
def _parsed_aughor() -> tuple[tuple[str, ast.Module], ...]:
    parsed = []
    for path in sorted((_REPO / "aughor").rglob("*.py")):
        try:
            parsed.append((str(path.relative_to(_REPO / "aughor")), ast.parse(path.read_text())))
        except SyntaxError:                      # not ours to police here
            continue
    return tuple(parsed)


@functools.lru_cache(maxsize=1)
def _environment_reads() -> tuple[dict[str, dict[str, str]], tuple[str, ...]]:
    """Every AUGHOR_* name the code in aughor/ reads → {route: first place it is read}, and the
    `resolve_db_path` call sites whose name could not be resolved.

    Two routes: "resolve_db_path", the seam most stores pass through, and "environ" —
    `os.environ.get`, `os.getenv`, `os.environ[...]`, `.setdefault`, `.pop`, `in os.environ`. A
    name held in a module-level constant is resolved (`resolve_db_path(STATE_DIR_ENV, …)`), in its
    own module or, when the constant's name is unambiguous, imported from another. An unresolved
    `resolve_db_path` name is RETURNED rather than dropped, because a store the scan cannot name
    would otherwise leave every population below without a word.
    """
    def _is_env_name(value) -> bool:
        return isinstance(value, str) and re.fullmatch(r"AUGHOR_[A-Z0-9_]+", value) is not None

    own: dict[str, dict[str, str]] = {}
    anywhere: dict[str, set[str]] = {}
    for where, tree in _parsed_aughor():
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            else:
                continue
            if isinstance(value, ast.Constant) and _is_env_name(value.value):
                for target in targets:
                    if isinstance(target, ast.Name):
                        own.setdefault(where, {})[target.id] = value.value
                        anywhere.setdefault(target.id, set()).add(value.value)

    def _resolve(where: str, node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant):
            return node.value if _is_env_name(node.value) else None
        name = getattr(node, "id", None) or getattr(node, "attr", None)
        if name in own.get(where, {}):
            return own[where][name]
        values = anywhere.get(name, set())
        return next(iter(values)) if len(values) == 1 else None

    def _is_environ(node: ast.AST) -> bool:
        return getattr(node, "attr", None) == "environ" or getattr(node, "id", None) == "environ"

    reads: dict[str, dict[str, str]] = {}
    unresolved: list[str] = []
    for where, tree in _parsed_aughor():
        for node in ast.walk(tree):
            route, named = None, None
            if isinstance(node, ast.Call) and node.args:
                called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if called == "resolve_db_path":
                    route, named = "resolve_db_path", node.args[0]
                elif called == "getenv" or (called in ("get", "setdefault", "pop")
                                            and _is_environ(getattr(node.func, "value", None))):
                    route, named = "environ", node.args[0]
            elif isinstance(node, ast.Subscript) and _is_environ(node.value):
                route, named = "environ", node.slice
            elif isinstance(node, ast.Compare) and any(_is_environ(c) for c in node.comparators):
                route, named = "environ", node.left
            if route is None:
                continue
            env = _resolve(where, named)
            if env:
                reads.setdefault(env, {}).setdefault(route, f"{where}:{node.lineno}")
            elif route == "resolve_db_path":
                unresolved.append(f"{where}:{node.lineno}")
    return reads, tuple(unresolved)


def _pinned_by(body: str, temp_root: pathlib.Path) -> dict[str, str]:
    """Run an isolation body in a FRESH interpreter that inherits no AUGHOR_* variable, and return
    the AUGHOR_* variables it leaves pointing inside its own temp root.

    Fresh, because this process ran the conftest long ago, and because both bodies decide what to
    set from what is already set — an inherited value would pass for a pin the body never makes.
    "Inside the temp root" is what isolation means for a path, and it is also what tells a store
    from a behaviour switch (`AUGHOR_API_KEY=""`) without a list of either.
    """
    temp_root.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUGHOR_")}
    env["TMPDIR"] = str(temp_root)
    code = (body + "\nimport json, os\n"
            "print(json.dumps({k: v for k, v in os.environ.items() if k.startswith('AUGHOR_')}))")
    done = subprocess.run([sys.executable, "-c", code], cwd=_REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, f"the isolation body failed to run:\n{done.stderr}"
    values = json.loads(done.stdout.strip().splitlines()[-1])
    root = temp_root.resolve()
    return {k: v for k, v in values.items() if v and root in pathlib.Path(v).resolve().parents}


@pytest.fixture(scope="module")
def isolation_bodies(tmp_path_factory) -> dict[str, dict[str, str]]:
    """What each isolation list actually pins: the conftest's module body, and
    `_isolate_stores()` as a drive imports it (`run_name` keeps the dump itself from running)."""
    root = tmp_path_factory.mktemp("isolation-bodies")
    conftest = str(_REPO / "tests" / "conftest.py")
    helper = str(_REPO / "scripts" / "dump_openapi.py")
    return {
        "tests/conftest.py": _pinned_by(f"import runpy; runpy.run_path({conftest!r})", root / "suite"),
        "_isolate_stores()": _pinned_by(
            f"import runpy; runpy.run_path({helper!r}, run_name='live_drive_probe')['_isolate_stores']()",
            root / "drive"),
    }


def test_the_environment_scan_finds_what_it_exists_to_find():
    """The scan's premise, tested, so the populations below cannot go vacuous: one store per
    route, including the constant-resolved one a literals-only scan misses."""
    reads, unresolved = _environment_reads()
    assert unresolved == (), (
        f"resolve_db_path is called with names the scan cannot resolve: {list(unresolved)}. "
        "Teach `_environment_reads` the new shape — every store population here is built from it")
    assert len(reads) > 100, f"found only {len(reads)} AUGHOR_* reads in aughor/ — the scan has gone blind"
    assert "resolve_db_path" in reads["AUGHOR_ORG_LLM_DB"]         # a literal
    assert "resolve_db_path" in reads["AUGHOR_STATE_DIR"]          # through STATE_DIR_ENV
    assert "environ" in reads["AUGHOR_UPLOAD_DIR"]                 # os.environ.get("…")
    assert "environ" in reads["AUGHOR_QDRANT_PATH"]                # os.getenv(QDRANT_PATH_ENV)


def test_live_drive_isolation_covers_every_store_the_suite_isolates(isolation_bodies):
    """The population is not listed anywhere. The stores are the AUGHOR_* names the code reads (the
    scan above), and "isolated" is where each body — the conftest and `_isolate_stores()`, each run
    from an empty environment — actually points the variable. So a store registered in the conftest
    and not in the helper fails here, whatever route it reads its variable by, instead of being
    found the way ORG_LLM was: by a drive writing the store."""
    reads, _ = _environment_reads()
    suite, drive = isolation_bodies["tests/conftest.py"], isolation_bodies["_isolate_stores()"]
    # Only the REFERENCE is held to a floor: a blind probe of the conftest would leave nothing to
    # compare. The helper gets none on purpose — the first run of this test had one, and against
    # the 54-store helper it reported "the probe has gone blind" instead of the 20 missing stores.
    assert len(suite) > 60, (
        f"the conftest pinned only {len(suite)} stores under its temp root — the probe has gone "
        "blind (does the conftest still create its stores with tempfile under TMPDIR?)")
    missing = sorted(env for env in reads
                     if env in suite and env not in drive and env not in LIVE_DRIVE_READS_FROM_THE_CHECKOUT)
    assert missing == [], (
        "scripts/dump_openapi._isolate_stores() leaves these stores at their defaults although "
        f"tests/conftest.py isolates every one: {missing}. A live drive or the SP-M recorder WRITES "
        "them — run from the main checkout, into the running deployment's own stores. Add each to "
        "_isolate_stores(), or, for a store a drive must read from the checkout, to "
        "LIVE_DRIVE_READS_FROM_THE_CHECKOUT with the reason.")


def test_both_isolation_lists_pin_only_stores_the_code_reads(isolation_bodies):
    """The failure the old comment hid in plain sight: `AUGHOR_ORGSETTINGS_DB` sat in the helper
    from the day it was written, while the org store's real name, AUGHOR_ORGS_DB, went unpinned —
    and a stale name reads exactly like coverage. The same check keeps the test above honest: its
    population is the scan, so a store the scan could not see would silently drop out of it; here
    that store fails instead."""
    reads, _ = _environment_reads()
    for body, pinned in isolation_bodies.items():
        unread = sorted(set(pinned) - set(reads))
        assert unread == [], (
            f"{body} pins {unread}, which no code in aughor/ reads: a renamed store's old name, or a "
            "read the scan cannot see. Either way the store it was meant for is not what is pinned.")


def test_every_store_a_live_drive_reads_from_the_checkout_still_earns_it(isolation_bodies):
    reads, _ = _environment_reads()
    suite, drive = isolation_bodies["tests/conftest.py"], isolation_bodies["_isolate_stores()"]
    for env in LIVE_DRIVE_READS_FROM_THE_CHECKOUT:
        assert env in reads, f"no code reads {env} any more — drop it from LIVE_DRIVE_READS_FROM_THE_CHECKOUT"
        assert env in suite, f"the suite no longer isolates {env}, so this exclusion excuses nothing"
        assert env not in drive, f"_isolate_stores() pins {env} now — drop it from LIVE_DRIVE_READS_FROM_THE_CHECKOUT"
    # AUGHOR_SAMPLES_DB's reason is a claim about writers; re-measure it rather than trust it.
    seeders = [f"{where}:{node.lineno}" for where, tree in _parsed_aughor() for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               and (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) == "ensure_samples_db"]
    assert seeders == [], (
        f"aughor/ now seeds the samples warehouse ({seeders}), so a live drive can write it: isolate "
        "AUGHOR_SAMPLES_DB in _isolate_stores() and drop its exclusion.")
