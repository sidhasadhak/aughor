"""DuckDB extension installs on a host with no writable home (Vercel, 2026-09-07).

The 2026-09-06 fix set `extension_directory` and a unit test asserted that setting —
a PROXY. Production kept failing, because DuckDB resolves the home directory before
it consults `extension_directory`. These tests assert the OUTCOME instead: that the
home-directory error is gone.

The discriminator is hermetic. `INSTALL '<local path>'` resolves the extension
directory before it touches the file, so with a broken home it raises "Can't find
the home directory" and with a working one it raises a plain "no access to the
file" — two different errors, no network in either.
"""
from __future__ import annotations

import os
import tempfile

import duckdb
import pytest

from aughor.db.duckdb_ext import fallback_home, prepare_extensions

_HOME_VARS = ("HOME", "USERPROFILE", "DUCKDB_HOME")
_MISSING_HOME = "home directory"


def _break_home(monkeypatch, tmp_path=None) -> None:
    """Make the process look like a serverless image: no usable home."""
    for var in _HOME_VARS:
        monkeypatch.delenv(var, raising=False)
    if tmp_path is not None:
        monkeypatch.setenv("HOME", str(tmp_path / "does-not-exist"))


def _install_error(con) -> str:
    with pytest.raises(duckdb.Error) as excinfo:
        con.execute("INSTALL '/nonexistent/nowhere.duckdb_extension'")
    return str(excinfo.value)


def test_without_the_fix_a_broken_home_is_what_breaks_install(monkeypatch):
    """The premise: prove the failure mode is real before pinning the fix."""
    _break_home(monkeypatch)
    con = duckdb.connect(":memory:")
    try:
        assert _MISSING_HOME in _install_error(con)
    finally:
        con.close()


def test_prepare_extensions_clears_the_home_error(monkeypatch):
    _break_home(monkeypatch)
    con = duckdb.connect(":memory:")
    try:
        prepare_extensions(con)
        err = _install_error(con)
        assert _MISSING_HOME not in err          # the real subject
        assert "nowhere.duckdb_extension" in err  # got far enough to read the path
    finally:
        con.close()


def test_a_home_that_exists_but_is_unwritable_also_falls_back(monkeypatch, tmp_path):
    """A read-only layer, not just an absent HOME."""
    ro = tmp_path / "ro-home"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setenv("HOME", str(ro))
    try:
        assert fallback_home() == tempfile.gettempdir()
    finally:
        ro.chmod(0o700)


def test_a_writable_home_is_left_completely_alone(monkeypatch, tmp_path):
    """A laptop and CI must keep the shared ~/.duckdb cache — no new network need."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert fallback_home() is None
    con = duckdb.connect(":memory:")
    try:
        before = con.execute("SELECT current_setting('home_directory')").fetchone()[0]
        prepare_extensions(con)
        after = con.execute("SELECT current_setting('home_directory')").fetchone()[0]
        assert before == after
    finally:
        con.close()


def test_the_fallback_directory_is_actually_writable(monkeypatch):
    _break_home(monkeypatch)
    home = fallback_home()
    assert home is not None
    assert os.access(home, os.W_OK)
