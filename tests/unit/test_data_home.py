"""IN-4 — the data home resolves, and nothing moves until a person migrates.

The property these tests exist for is the one that could lose a deployment. The install this
wave was measured on holds 1.4 GB under `data/` — a 266 MB `system.db`, 437 MB of uploads, a
208 MB checkpoint store. A default that relocated because a home DIRECTORY existed would not
delete any of it; it would make the connections, the history and the receipts invisible, which
reads identically to a person and is harder to diagnose. So the home is the live answer only
once `aughor migrate-state` has verified a copy and written its marker.
"""
from __future__ import annotations

import sys

import pytest

from aughor.db import home, paths
from aughor.db.sqlite_util import resolve_db_path


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.STATE_DIR_ENV, raising=False)
    monkeypatch.setenv(home.HOME_ENV, str(tmp_path))
    return tmp_path


class TestPrecedence:
    def test_a_home_that_merely_exists_does_not_move_anything(self, clean_env):
        """The safety property, stated as a test. The directory is there; no marker is."""
        assert home.in_use() is False
        assert paths.state_dir() == paths.Path("data")

    def test_the_marker_is_what_moves_the_default(self, clean_env):
        (clean_env / home.MARKER).write_text("migrated")
        assert home.in_use() is True
        assert paths.state_dir() == clean_env / home.STATE_SUBDIR

    def test_an_explicit_state_dir_beats_a_migrated_home(self, clean_env, monkeypatch):
        """An operator who has pointed state at durable storage keeps it, and the suite — which
        sets this var for every test — is never relocated by a developer's own migration."""
        (clean_env / home.MARKER).write_text("migrated")
        monkeypatch.setenv(paths.STATE_DIR_ENV, "/tmp/explicit-wins")
        assert paths.state_dir() == paths.Path("/tmp/explicit-wins")

    def test_removing_the_marker_returns_to_the_checkout(self, clean_env):
        (clean_env / home.MARKER).write_text("migrated")
        assert paths.state_dir() != paths.Path("data")
        (clean_env / home.MARKER).unlink()
        assert paths.state_dir() == paths.Path("data")

    def test_the_answer_is_resolved_on_call_not_cached(self, clean_env):
        before = paths.state_dir()
        (clean_env / home.MARKER).write_text("migrated")
        assert paths.state_dir() != before, "state_dir cached its answer across a migration"


class TestTheHomeItself:
    def test_the_override_is_honoured_and_expanded(self, monkeypatch):
        monkeypatch.setenv(home.HOME_ENV, "~/somewhere-else")
        assert home.home() == paths.Path.home() / "somewhere-else"

    def test_state_lives_in_a_subdirectory_of_the_home(self, clean_env):
        """So the home can hold the marker and a log without either landing inside the
        directory the stores enumerate."""
        assert home.state_home().parent == home.home()
        assert home.marker_path().parent == home.home()
        assert home.marker_path() not in list(home.state_home().parents)

    def test_a_marker_that_cannot_be_read_fails_closed(self, clean_env, monkeypatch):
        """An unreadable home must leave the checkout's `data/` live rather than point a
        running deployment at a directory it cannot stat."""
        def boom(_self):
            raise OSError("permission denied")
        monkeypatch.setattr(paths.Path, "is_file", boom)
        assert home.in_use() is False


class TestPlatformDefaults:
    def test_posix_uses_a_dotfile_in_the_home_directory(self, monkeypatch):
        monkeypatch.delenv(home.HOME_ENV, raising=False)
        monkeypatch.setattr(sys, "platform", "darwin")
        assert home.default_home() == paths.Path.home() / ".aughor"

    def test_windows_uses_localappdata(self, monkeypatch):
        monkeypatch.delenv(home.HOME_ENV, raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        # Asserted as a relationship, not a rendering: this suite runs on POSIX too, where a
        # backslash is an ordinary character and `as_posix()` would not split the path.
        local = "/c/Users/x/AppData/Local"
        monkeypatch.setenv("LOCALAPPDATA", local)
        assert home.default_home() == paths.Path(local) / "aughor"

    def test_windows_without_localappdata_falls_back_rather_than_raising(self, monkeypatch):
        """A bare service account can have it unset; that must not crash the resolver."""
        monkeypatch.delenv(home.HOME_ENV, raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert home.default_home() == paths.Path.home() / ".aughor"

    def test_the_home_is_not_the_checkout(self, monkeypatch):
        """`~/.aughor` is the data home, `~/aughor` is the checkout (`AUGHOR_DIR`), and
        `<checkout>/.aughor/` is the installer's runtime dir. Three names one letter apart."""
        monkeypatch.delenv(home.HOME_ENV, raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        assert home.default_home() != paths.Path.home() / "aughor"


class TestTheFourConventionsAreReconciled:
    """Store paths were computed four ways — `state_dir()`, CWD-relative `Path("data")`,
    checkout-anchored `Path(__file__).parents[2]/"data"`, and some with no override — and the
    CWD-relative and checkout-anchored halves DISAGREE about which `data/` a process reads.
    `rehome` reconciles them at one seam, and only once a migration has happened."""

    CHECKOUT = paths.Path("/somewhere/aughor")

    def test_nothing_moves_before_the_marker(self, clean_env):
        """The whole fleet's behaviour today: each convention keeps its own answer."""
        assert resolve_db_path("X_STATE", paths.Path("data")) == paths.Path("data")
        assert resolve_db_path("X_CWD", paths.Path("data/monitors.db")) == paths.Path("data/monitors.db")
        anchored = self.CHECKOUT / "data" / "system.db"
        assert resolve_db_path("X_ANCHORED", anchored) == anchored

    def test_all_three_conventions_land_in_one_place_after(self, clean_env):
        (clean_env / home.MARKER).write_text("migrated")
        state = clean_env / home.STATE_SUBDIR
        assert resolve_db_path("X_STATE", paths.Path("data")) == state
        assert resolve_db_path("X_CWD", paths.Path("data/monitors.db")) == state / "monitors.db"
        assert resolve_db_path("X_ANCHORED", self.CHECKOUT / "data" / "system.db") == state / "system.db"

    def test_a_nested_generated_path_keeps_its_shape(self, clean_env):
        (clean_env / home.MARKER).write_text("migrated")
        got = resolve_db_path("X_NESTED", self.CHECKOUT / "data" / "uploads" / "default" / "f.csv")
        assert got == clean_env / home.STATE_SUBDIR / "uploads" / "default" / "f.csv"

    def test_an_env_override_still_beats_a_migrated_home(self, clean_env, monkeypatch):
        (clean_env / home.MARKER).write_text("migrated")
        monkeypatch.setenv("X_EXPLICIT", "/mnt/durable/system.db")
        assert resolve_db_path("X_EXPLICIT", paths.Path("data/system.db")) == paths.Path("/mnt/durable/system.db")

    def test_a_path_outside_data_is_never_rehomed(self, clean_env):
        (clean_env / home.MARKER).write_text("migrated")
        assert resolve_db_path("X_OUT", paths.Path("/var/lib/thing.db")) == paths.Path("/var/lib/thing.db")


class TestAuthoredContentStaysInTheCheckout:
    """`data/` is MIXED — most of its files are git-tracked, and `.gitignore` is a per-file
    denylist whose own comments keep `ontology_overrides/` tracked because it is a reviewable
    governed artifact. Versioned content does not follow the state. `context_graph/` left the
    authored list with the 2027 study's close-out (C3): a projection of the ledger, rebuilt on
    demand, it is generated state and moves like the metrics instance."""

    CHECKOUT = paths.Path("/somewhere/aughor")

    @pytest.mark.parametrize("entry", ["glossary.yaml", "global_rules.md", "events.yaml", "seed.py"])
    def test_an_authored_file_does_not_move(self, clean_env, entry):
        (clean_env / home.MARKER).write_text("migrated")
        default = self.CHECKOUT / "data" / entry
        assert resolve_db_path(f"X_{entry}", default) == default

    @pytest.mark.parametrize("entry", ["ontology_column_config",
                                       "ontology_overrides", "shipped", "demo_packs"])
    def test_an_authored_directory_does_not_move(self, clean_env, entry):
        (clean_env / home.MARKER).write_text("migrated")
        default = self.CHECKOUT / "data" / entry / "inner.json"
        assert resolve_db_path(f"X_{entry}", default) == default

    def test_the_context_graph_is_generated_state_and_moves(self, clean_env):
        """The close-out (C3): the graph is a projection of the ledger, rebuilt on demand — a home
        that never received a copy rebuilds it, so it moves with the state and is not tracked."""
        (clean_env / home.MARKER).write_text("migrated")
        default = self.CHECKOUT / "data" / "context_graph" / "default" / "c1" / "main.json"
        assert resolve_db_path("X_context_graph", default) == clean_env / home.STATE_SUBDIR / "context_graph" / "default" / "c1" / "main.json"

    @pytest.mark.parametrize("entry", ["metrics.instance.json", "metrics.instance.converted.json",
                                       "glossary.instance.yaml", "glossary.instance.converted.yaml"])
    def test_the_metrics_instance_moves_although_the_file_beside_it_is_authored(self, clean_env, entry):
        """The overlay's instance and its conversion marker are generated state; the frozen
        `metrics.json` beside them stays."""
        (clean_env / home.MARKER).write_text("migrated")
        default = self.CHECKOUT / "data" / entry
        assert resolve_db_path(f"X_{entry}", default) == clean_env / home.STATE_SUBDIR / entry

    def test_the_authored_list_matches_what_git_actually_tracks(self):
        """The population is measured, not hand-listed beside its expectation. If somebody adds
        a tracked file under `data/`, this fails rather than silently rehoming it."""
        import subprocess
        repo = paths.Path(__file__).resolve().parents[2]
        out = subprocess.run(["git", "ls-files", "data/"], cwd=repo,
                             capture_output=True, text=True, check=True).stdout.split()
        tracked = {paths.Path(line).parts[1] for line in out if len(paths.Path(line).parts) > 1}
        assert tracked, "probe failed: git ls-files data/ returned nothing"
        assert tracked == set(home.AUTHORED_ENTRIES), {
            "tracked but would be rehomed": sorted(tracked - set(home.AUTHORED_ENTRIES)),
            "listed but no longer tracked": sorted(set(home.AUTHORED_ENTRIES) - tracked)}

    def test_an_install_migrated_before_the_overlay_still_reads_its_overrides(self, clean_env):
        """The review's finding, pinned: `ontology_overrides/` was authored when `migrate-state`
        first shipped, so a home migrated then never received it. If it ever rehomed, every
        declaration on such an install would resolve into an empty tree, and `migrate-state`
        cannot repair it — it answers "already" once the marker exists."""
        (clean_env / home.MARKER).write_text("migrated")
        default = self.CHECKOUT / "data" / "ontology_overrides"
        assert resolve_db_path("X_OVR", default) == default


# ── every store follows the home: the population is the SOURCE, not a list ───────────────────────
#
# IN-4 wired the home into `resolve_db_path` and every store that went through it — and left about
# twenty that did not: the platform's main store (`Ledger.default()` read `AUGHOR_SYSTEM_DB` and the
# checkout default itself), the model configuration, uploads, documents, the playbook, the demo
# warehouses. A migration would have copied them and gone on reading the checkout, and the day the
# code caught up, read a copy weeks stale. Found 2026-10-06 by reading, before the first real run.

import ast as _ast
import pathlib as _pathlib

_ROUTERS = {"resolve_db_path", "rehome", "_rehome", "state_dir", "follow_checkout_file"}

#: The `data/` paths that do NOT follow the home, each for a reason. Asserted both ways: a new
#: unrouted path fails, and an entry here that no longer exists fails too, so the list cannot rot.
_STAYS = {
    ("aughor/cli.py", "src"): "migrate-state's SOURCE — the checkout's data/ it copies from",
    ("aughor/connectors/declarations.py", "'data/sales/'"): "a connect form's placeholder, not a path",
    ("aughor/db/home.py", "checkout_data"): "follow_checkout_file's anchor — the data/ it maps FROM",
    ("aughor/db/keyfile.py", "LEGACY_KEY_FILE"): "the fallback for a key not yet moved; the home's copy wins",
    ("aughor/installer.py", "path"): "a stdlib mirror of the rule, held equal to the app in test_installer",
    ("aughor/ontology/column_config.py", "_DEFAULT_ROOT"): "authored, tracked — stays in the checkout",
    ("aughor/rules.py", "_RULES_FILE"): "authored, tracked",
    ("aughor/semantic/glossary.py", "_DATA"): "the seed and frozen files are authored; the instance resolves",
    ("aughor/semantic/metrics.py", "_DATA"): "the seed and frozen files are authored; the instance resolves",
    ("aughor/tools/events.py", "_EVENTS_YAML"): "authored, tracked",
}


def _call_name(n):
    return getattr(n.func, "id", None) or getattr(n.func, "attr", None)


def _is_data_literal(node, parent) -> bool:
    if not (isinstance(node, _ast.Constant) and isinstance(node.value, str)):
        return False
    v = node.value
    if v.startswith("data/") and len(v) > 5 and " " not in v:
        return True
    return v == "data" and (
        (isinstance(parent, _ast.Call) and _call_name(parent) == "Path")
        or (isinstance(parent, _ast.BinOp) and isinstance(parent.op, _ast.Div)))


def _unrouted_data_paths(root: _pathlib.Path) -> set[tuple[str, str]]:
    """Every `data/` path literal in the package that no resolver reaches — directly, or through
    the module constant it is assigned to (every READ of which must sit inside a resolver)."""
    found: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        parents = {c: n for n in _ast.walk(tree) for c in _ast.iter_child_nodes(n)}

        def routed(n) -> bool:
            while n in parents:
                n = parents[n]
                if isinstance(n, _ast.Call) and _call_name(n) in _ROUTERS:
                    return True
            return False

        def assigned(n):
            while n in parents:
                par = parents[n]
                if (isinstance(par, _ast.Assign) and len(par.targets) == 1
                        and isinstance(par.targets[0], _ast.Name)):
                    return par.targets[0].id
                if isinstance(par, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef, _ast.Module)):
                    return None
                n = par
            return None

        rel = path.relative_to(root.parent).as_posix()
        for n in _ast.walk(tree):
            if not _is_data_literal(n, parents.get(n)) or routed(n):
                continue
            name = assigned(n)
            if name is None:
                found.add((rel, repr(n.value)))
                continue
            reads = [u for u in _ast.walk(tree)
                     if isinstance(u, _ast.Name) and u.id == name and isinstance(u.ctx, _ast.Load)]
            if not reads or any(not routed(u) for u in reads):
                found.add((rel, name))
    return found


_PACKAGE = _pathlib.Path(__file__).resolve().parents[2] / "aughor"


class TestEveryStoreFollowsTheHome:
    def test_no_data_path_escapes_the_home_unless_it_says_why(self):
        found = _unrouted_data_paths(_PACKAGE)
        new = found - set(_STAYS)
        assert not new, ("a data/ path no resolver reaches — it would stay in the checkout after "
                         f"`migrate-state`. Route it through resolve_db_path/rehome: {sorted(new)}")
        gone = set(_STAYS) - found
        assert not gone, f"_STAYS names paths that are no longer there — drop them: {sorted(gone)}"

    def test_the_guard_sees_a_store_that_reads_its_default_directly(self, tmp_path):
        """Mutation-tested on the defect it was written for: `Ledger.default()` as it was."""
        pkg = tmp_path / "aughor"
        pkg.mkdir()
        (pkg / "ledger.py").write_text(
            'import os\nfrom pathlib import Path\n'
            '_DEFAULT_DB = Path(__file__).parent / "data" / "system.db"\n'
            'def default():\n    return Path(os.environ.get("AUGHOR_SYSTEM_DB", _DEFAULT_DB))\n')
        (pkg / "fixed.py").write_text(
            'from pathlib import Path\nfrom x import resolve_db_path\n'
            '_D = Path(__file__).parent / "data" / "a.db"\n'
            'def default():\n    return resolve_db_path("AUGHOR_A_DB", _D)\n')
        assert _unrouted_data_paths(pkg) == {("aughor/ledger.py", "_DEFAULT_DB")}

    def test_the_ledger_follows_a_migrated_home(self, clean_env, monkeypatch):
        from aughor.kernel import ledger as L
        monkeypatch.delenv("AUGHOR_SYSTEM_DB", raising=False)
        (clean_env / home.MARKER).write_text("migrated")
        seen = []
        monkeypatch.setattr(L.Ledger, "__init__", lambda self, path: seen.append(path) or None)
        monkeypatch.setattr(L.Ledger, "_instances", {})
        L.Ledger.default()
        assert seen == [str(clean_env / home.STATE_SUBDIR / "system.db")]


class TestAConnectionsFileFollows:
    def _checkout_data(self):
        return _pathlib.Path(home.__file__).resolve().parents[2] / "data"

    def test_nothing_moves_before_the_marker(self, clean_env):
        p = self._checkout_data() / "x.duckdb"
        assert home.follow_checkout_file(p) == p

    def test_a_file_in_the_checkouts_data_follows_to_its_copy(self, clean_env):
        (clean_env / home.MARKER).write_text("migrated")
        copy = clean_env / home.STATE_SUBDIR / "uploads" / "x.duckdb"
        copy.parent.mkdir(parents=True)
        copy.write_bytes(b"")
        assert home.follow_checkout_file(self._checkout_data() / "uploads" / "x.duckdb") == copy
        assert home.follow_checkout_file("data/uploads/x.duckdb") == copy

    def test_a_missing_copy_keeps_the_working_path(self, clean_env):
        (clean_env / home.MARKER).write_text("migrated")
        p = self._checkout_data() / "gone.duckdb"
        assert home.follow_checkout_file(p) == p

    def test_a_folder_called_data_elsewhere_is_never_redirected(self, clean_env, tmp_path):
        (clean_env / home.MARKER).write_text("migrated")
        (clean_env / home.STATE_SUBDIR).mkdir()
        (clean_env / home.STATE_SUBDIR / "w.duckdb").write_bytes(b"")
        theirs = tmp_path / "someone" / "data" / "w.duckdb"
        assert home.follow_checkout_file(theirs) == theirs
