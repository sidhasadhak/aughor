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
