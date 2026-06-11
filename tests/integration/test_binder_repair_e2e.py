"""Runtime LEVERAGE proof for the Phase-8 Binder-error repair (commit 57f5760).

The unit tests (test_sql_repair_learnings.py) prove the diagnosis TEXT is correct for
the GROUP-BY-completeness and EXTRACT(EPOCH ...) classes. This proves the leverage: a
real fix() — real DuckDB + real coder LLM — actually REPAIRS those errors to executable
SQL, so the explorer's retry loop stops DROPPING the angle.

Opt-in (@e2e) because it calls the live coder model (~seconds). Run with:
    pytest tests/integration/test_binder_repair_e2e.py --run-e2e
"""
from __future__ import annotations

import pytest

# Standalone scripts/tests that hit the coder must load .env or fall back to an
# uninstalled model and the LLM call silently fails (known gotcha).
from dotenv import load_dotenv
load_dotenv()


@pytest.mark.e2e
@pytest.mark.parametrize("name,sql", [
    ("group_by_completeness",
     "SELECT region, segment, COUNT(*) AS n FROM customers GROUP BY region"),
    ("extract_epoch_on_date_diff",
     "SELECT event_id, EXTRACT(EPOCH FROM (end_date - start_date)) AS dur FROM events"),
])
def test_fix_repairs_binder_error_to_executable_sql(name: str, sql: str) -> None:
    from aughor.db.connection import open_connection_for
    from aughor.sql.writer import SqlWriter

    db = open_connection_for("fixture")
    try:
        w = SqlWriter(db)
        ok, err = db.dry_run(sql)
        assert not ok and err, f"[{name}] expected the original SQL to error on the fixture; it didn't"

        res = w.fix(sql, err, max_retries=2)
        assert res.ok, f"[{name}] fix() failed to repair the Binder error: {res.final_error}"

        # The repair must actually EXECUTE — a 'fix' that still errors is no fix.
        rr = db.execute("verify", res.sql)
        assert not rr.error, f"[{name}] repaired SQL still errors: {rr.error}\nSQL: {res.sql}"
    finally:
        db.close()
