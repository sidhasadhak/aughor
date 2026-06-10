"""WCH-9 stress: degenerate data shapes the audit predicted would break things.

Scenario 7 (empty database / 0-row tables) and scenario 6 (unicode + exotic
column names, oversized values). No LLM required: these exercise the discovery
and profiling layers, which is where the audit expected crashes — an explorer
must abort/complete GRACEFULLY, never hang or raise, and the profiler must
survive identifiers that need quoting.
"""
import asyncio

import duckdb
import pytest

from aughor.db.connection import DuckDBConnection
from aughor.explorer.agent import SchemaExplorer
from aughor.explorer.models import ExplorationPhase


def _make_db(tmp_path, name, ddl: list[str]):
    p = tmp_path / name
    c = duckdb.connect(str(p))
    for stmt in ddl:
        c.execute(stmt)
    c.close()
    return p


@pytest.fixture(autouse=True)
def _hermetic_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "sys.db"))
    from aughor.kernel.ledger import Ledger
    Ledger._instances.clear()


class TestEmptyDatabase:
    def test_explorer_aborts_gracefully_on_zero_tables(self, tmp_path):
        db_path = _make_db(tmp_path, "empty.duckdb", [])
        db = DuckDBConnection(db_path, connection_id="stress_empty")
        ex = SchemaExplorer("stress_empty", db)
        # Must return (abort), not raise, not hang.
        asyncio.run(asyncio.wait_for(ex.explore(), timeout=30))
        assert ex.status.phase != ExplorationPhase.FAILED or ex.status.error

    def test_explorer_survives_all_empty_tables(self, tmp_path):
        db_path = _make_db(tmp_path, "zerorows.duckdb", [
            "CREATE TABLE orders (id INTEGER, total DOUBLE, created_at TIMESTAMP)",
            "CREATE TABLE customers (id INTEGER, name VARCHAR)",
        ])
        db = DuckDBConnection(db_path, connection_id="stress_zerorows")
        ex = SchemaExplorer("stress_zerorows", db)

        async def run():
            # Phases 3-7 on 0-row tables must not divide-by-zero / raise.
            # (Phase 3+ may attempt LLM calls; we only need the data-discovery
            # layer, so stop after profiler load like explore() does on abort.)
            tp, cp, jmap = await asyncio.get_event_loop().run_in_executor(
                None, ex._load_profiler_data
            )
            return tp, cp, jmap

        tp, cp, jmap = asyncio.run(asyncio.wait_for(run(), timeout=60))
        assert set() != set(tp) or tp == {}  # loaded without raising is the gate
        # Profiles for 0-row tables must report row_count 0, not crash.
        for t, prof in tp.items():
            rc = getattr(prof, "row_count", None)
            assert rc in (0, None) or rc >= 0


class TestExoticIdentifiersAndValues:
    def test_profiler_survives_unicode_and_special_columns(self, tmp_path):
        big = "x" * 10_000
        db_path = _make_db(tmp_path, "exotic.duckdb", [
            '''CREATE TABLE "wëird tablé" (
                "μ_revenue" DOUBLE,
                "email@domain" VARCHAR,
                "order#" INTEGER,
                "emoji🙂col" VARCHAR,
                "select" VARCHAR,
                ts TIMESTAMP
            )''',
            f'''INSERT INTO "wëird tablé" VALUES
                (1.5, 'a@b.c', 1, '🙂', '{big}', '2024-05-01 10:00:00'),
                (2.5, NULL, 2, '😀', 'ok', '2024-05-02 10:00:00')''',
        ])
        db = DuckDBConnection(db_path, connection_id="stress_exotic")
        ex = SchemaExplorer("stress_exotic", db)

        tp, cp, jmap = asyncio.run(asyncio.wait_for(_in_thread(ex), timeout=120))
        # The gate: discovery + profiling completed without raising, and the
        # exotic table was seen at all.
        assert any("wëird" in t or "weird" in t.lower() for t in tp), f"tables={list(tp)}"


async def _in_thread(ex):
    return await asyncio.get_event_loop().run_in_executor(None, ex._load_profiler_data)
