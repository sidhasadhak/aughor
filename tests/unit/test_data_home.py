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
    """`data/` is MIXED — 102 of its files are git-tracked, and `.gitignore` is a per-file
    denylist whose own comments keep `ontology_overrides/` and `context_graph/` tracked because
    they are the reviewable governed artifacts. Versioned content does not follow the state."""

    CHECKOUT = paths.Path("/somewhere/aughor")

    @pytest.mark.parametrize("entry", ["glossary.yaml", "global_rules.md", "events.yaml", "seed.py"])
    def test_an_authored_file_does_not_move(self, clean_env, entry):
        (clean_env / home.MARKER).write_text("migrated")
        default = self.CHECKOUT / "data" / entry
        assert resolve_db_path(f"X_{entry}", default) == default

    @pytest.mark.parametrize("entry", ["context_graph", "ontology_column_config",
                                       "ontology_overrides", "shipped", "demo_packs"])
    def test_an_authored_directory_does_not_move(self, clean_env, entry):
        (clean_env / home.MARKER).write_text("migrated")
        default = self.CHECKOUT / "data" / entry / "inner.json"
        assert resolve_db_path(f"X_{entry}", default) == default

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
