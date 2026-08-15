"""The ledger names a damaged file at startup, loudly, and the app still boots.

`data/system.db` was corrupted THREE times in three days (SIGBUS "FS pagein error: 22" —
a mapped SQLite file replaced under a live mapping) and every time it was found by
accident, hours later, because every writer on the store is `tolerate()`-wrapped: the
damage presented as receipts that never appeared and eval verdicts that read as findings.
The 2026-08-14 post-mortem named the missing guard — a startup `PRAGMA quick_check`,
logged once — and this is it, plus its surface on `/health` so a poll (or a human) sees
`degraded` instead of `ok`.

Never fatal on purpose: a damaged ledger must still let the process come up, so the
operator can read the message and recover; a boot crash would hide it behind CORS-less
500s (see the 2026-08-11 outage).
"""
from __future__ import annotations

import logging
import sqlite3

from aughor.kernel.ledger import Ledger


def _corrupt(path) -> None:
    """Make a real SQLite file that opens but fails quick_check: write a valid db, then
    smash a b-tree PAGE HEADER (page 2). Cell payload damage is NOT what quick_check
    verifies — a first version of this fixture wrote garbage into cell content and
    quick_check said `ok`; a broken page header raises `database disk image is
    malformed`, which is exactly the production signature (2026-08-14/15)."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 500,) for _ in range(200)])
    con.commit()
    con.close()
    with open(path, "r+b") as fh:
        fh.seek(4096)                # page 2's b-tree header
        fh.write(b"\xff" * 16)


def test_healthy_file_reports_no_error(tmp_path):
    led = Ledger(tmp_path / "system.db")
    assert led.integrity_error is None


def test_damaged_file_is_named_loudly_and_still_boots(tmp_path, caplog):
    path = tmp_path / "system.db"
    _corrupt(path)
    with caplog.at_level(logging.CRITICAL, logger="aughor.kernel.ledger"):
        led = Ledger(path)          # must NOT raise
    assert led.integrity_error, "quick_check passed on a file we deliberately damaged"
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert any("LEDGER INTEGRITY FAILURE" in m and "sqlite3 .recover" in m for m in msgs), msgs


def test_health_reports_degraded_when_the_ledger_is_damaged(client, monkeypatch, tmp_path):
    path = tmp_path / "system.db"
    _corrupt(path)
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(path))
    Ledger._instances.pop(str(path), None)      # a fresh instance for this path
    body = client.get("/health").json()
    assert body["status"] == "degraded", body
    assert body["ledger"]["ok"] is False and body["ledger"]["error"]


def test_health_reports_ok_ledger_normally(client):
    body = client.get("/health").json()
    assert body["ledger"]["ok"] is True
    assert body["ledger"]["error"] is None
    assert body["status"] == "ok"
