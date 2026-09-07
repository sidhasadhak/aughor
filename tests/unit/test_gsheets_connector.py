"""Google Sheets connector — the failure modes a live report exposed (2026-09-06).

A user's shared sheet loaded perfectly through the raw gviz endpoint, and the
connector still failed on their serverless deployment with "check the spreadsheet is
shared" — because `INSTALL httpfs` cannot write `$HOME/.duckdb` on a read-only
filesystem, and both that error and every per-sheet error were swallowed by bare
`except: pass`. Three properties pinned here:

  * the extension directory is pointed at a writable temp dir, so serverless can
    install httpfs at all;
  * a sheet-load failure is KEPT, and `test()` reports the true reason instead of
    guessing at sharing;
  * a partial load still connects, and says which sheets failed.

No network: `_export_url` is monkeypatched to local files — the loader, the error
capture and the test message are the subjects, not Google's endpoint.
"""
from __future__ import annotations

import os

from aughor.connectors.api.gsheets import GoogleSheetsConnector, invalidate_sheet_cache


def _connector(monkeypatch, url_for: dict[str, str], sheets: str = "") -> GoogleSheetsConnector:
    """A connector whose per-sheet export URL resolves locally."""
    invalidate_sheet_cache()

    def fake_url(self, sheet):
        return url_for.get(sheet or "", "/nonexistent/nowhere.csv")

    monkeypatch.setattr(GoogleSheetsConnector, "_export_url", fake_url)
    return GoogleSheetsConnector("gsheet://test-sheet-id", meta={"sheets": sheets})


def test_a_host_with_no_writable_home_can_still_install_httpfs(monkeypatch, tmp_path):
    """The Vercel shape. Asserts the OUTCOME, not the setting.

    The previous version of this test asserted `extension_directory` was a temp dir
    and passed — while the deployment kept dying on `INSTALL httpfs`, because DuckDB
    resolves the home directory FIRST. Here the home is broken the way a serverless
    image breaks it, and the subject is whether the home error is gone.
    """
    for var in ("HOME", "USERPROFILE", "DUCKDB_HOME"):
        monkeypatch.delenv(var, raising=False)
    csv = tmp_path / "ok.csv"
    csv.write_text("a,b\n1,2\n")
    conn = _connector(monkeypatch, {"": str(csv)})
    try:
        assert "home directory" not in conn._load_errors.get("httpfs", "")
        home = conn._duckdb.execute("SELECT current_setting('home_directory')").fetchone()[0]
        assert home and os.access(str(home), os.W_OK)
    finally:
        conn.close()


def test_a_writable_home_keeps_the_shared_extension_cache(monkeypatch, tmp_path):
    """A laptop/CI must not be pushed onto a temp extension dir (network on every run)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    csv = tmp_path / "ok.csv"
    csv.write_text("a,b\n1,2\n")
    conn = _connector(monkeypatch, {"": str(csv)})
    try:
        ext = conn._duckdb.execute("SELECT current_setting('extension_directory')").fetchone()[0]
        assert str(ext) == ""  # untouched default -> ~/.duckdb
    finally:
        conn.close()


def test_a_load_failure_reaches_test_with_the_true_reason(monkeypatch):
    conn = _connector(monkeypatch, {})  # every sheet resolves to a nonexistent path
    ok, msg = conn.test()
    assert ok is False
    # The captured error, not the sharing guess: the message names the failed table
    # and carries the underlying reader error.
    assert "sheet1:" in msg
    assert "shared" not in msg.split("—")[0]  # the guess no longer leads
    conn.close()


def test_a_partial_load_connects_and_names_the_failed_sheet(monkeypatch, tmp_path):
    csv = tmp_path / "good.csv"
    csv.write_text("x,y\n1,2\n3,4\n")
    conn = _connector(monkeypatch, {"good": str(csv)}, sheets="good,bad")
    ok, msg = conn.test()
    assert ok is True
    assert "good" in msg
    assert "1 sheet(s) failed: bad" in msg
    conn.close()


def test_the_sharing_hint_survives_when_nothing_was_captured(monkeypatch, tmp_path):
    """A genuinely empty result with no recorded error still gets the actionable
    hint — the guess is wrong as a diagnosis, right as a last resort."""
    csv = tmp_path / "empty_dir_placeholder.csv"  # never used
    conn = _connector(monkeypatch, {"": str(csv)})
    conn._load_errors.clear()
    conn._duckdb.execute('DROP TABLE IF EXISTS "sheet1"')
    ok, msg = conn.test()
    assert ok is False and "shared" in msg
    conn.close()
