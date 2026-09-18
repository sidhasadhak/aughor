"""`recent()` means newest first, including inside one second.

`audit.py` writes `ts` at SECOND resolution (`time.strftime("%Y-%m-%dT%H:%M:%SZ")`), so
every statement run in the same second carries an identical sort key. With `ORDER BY ts
DESC` alone the order of those rows was the query plan's business, and the plan scans
`idx_audit_ts` ascending by rowid — so "newest first" served the current second exactly
BACKWARDS, and `recent(...)[0]` was that second's OLDEST row.

This is what made `test_duckdb_julianday_heal::test_the_audit_log_records_the_statement_that_ran`
look flaky across three recorded CI failures on commits that could not have caused it. It
reads `recent(50, connection_id=...)[0]` after running one statement, and passed only when
its own row happened to open a new second. When a sibling test's statement landed in the
same second first, `[0]` was the sibling's — a stable inversion that only LOOKS random,
because where the second boundary falls moves with machine speed and load.

It was never only a test problem: this is the read behind the SQL editor's history rail.
"""
from __future__ import annotations

from aughor.security.audit import AuditLogger, GuardVerdicts


def test_one_second_of_statements_comes_back_newest_first():
    """The regression. Six rows written far faster than the 1s `ts` tick, so they share a
    key and only the tiebreaker can order them."""
    for i in range(6):
        AuditLogger.log(connection_id="order-fix", sql=f"SELECT {i}", hypothesis_id="h")

    rows = AuditLogger.recent(50, connection_id="order-fix")
    assert [r["sql_full"] for r in rows] == [f"SELECT {i}" for i in range(5, -1, -1)]


def test_the_fixture_actually_ties_so_the_test_is_not_passing_on_the_timestamp():
    """Guards the guard. If those six writes straddled a second boundary the assertion above
    would pass on `ts` alone and prove nothing about the tiebreaker — the shape where a test
    goes green for a reason that is not the one it was written for."""
    for i in range(6):
        AuditLogger.log(connection_id="order-tie", sql=f"SELECT {i}", hypothesis_id="h")

    stamps = {r["ts"] for r in AuditLogger.recent(50, connection_id="order-tie")}
    assert len(stamps) == 1, (
        f"the six writes spanned {len(stamps)} seconds ({sorted(stamps)}), so ts alone could "
        "order them and this file is no longer testing the tiebreaker")


def test_the_newest_statement_is_the_one_you_just_ran():
    """The property every caller actually depends on, stated directly: write last, read
    first. This is the assertion `test_the_audit_log_records_the_statement_that_ran` was
    making implicitly."""
    AuditLogger.log(connection_id="order-last", sql="SELECT 'first'", hypothesis_id="h")
    AuditLogger.log(connection_id="order-last", sql="SELECT 'mine'", hypothesis_id="h")

    assert AuditLogger.recent(50, connection_id="order-last")[0]["sql_full"] == "SELECT 'mine'"


def test_guard_verdicts_are_ordered_the_same_way():
    """`guard_verdicts` shares the second-resolution `ts` and the newest-first contract, so
    it carried the identical inversion."""
    for i in range(6):
        GuardVerdicts.record(trace_id="order-gv", pattern=f"p{i}", detail="")

    rows = GuardVerdicts.recent(50, trace_id="order-gv")
    assert [r["pattern"] for r in rows] == [f"p{i}" for i in range(5, -1, -1)]
