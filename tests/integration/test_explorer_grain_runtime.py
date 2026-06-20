"""Runtime LEVERAGE proof for the COUNT(*)-chasm grain guard (FAN-b slice).

Unit tests (test_explorer_grain_lint.py::TestCountStarChasm) prove the detector.
This proves the WIRING: a COUNT(*)-over-a-chasm query actually reaches the explorer's
Phase-8 _skip_result block and gets DROPPED on the real loop. Hermetic — a minimal
injected ontology + a SqlWriter exposing a chasm schema + a fake interpreter, no live
LLM. (Per the BUILT→WIRED→TESTED→LEVERAGED rule: the guard is observed firing on the
real path, not inferred from the sibling grain-lints it sits beside.)
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

# A chasm schema: clicks and impressions are each on the many-side of `campaign`.
CHASM_TC = {
    "campaigns":   ["campaign_id", "name", "budget"],
    "clicks":      ["click_id", "campaign_id", "ts", "amount"],
    "impressions": ["impression_id", "campaign_id", "ts"],
}
CHASM_SQL =("SELECT c.name, COUNT(*) FROM campaigns c "
             "JOIN clicks k ON c.campaign_id=k.campaign_id "
             "JOIN impressions i ON c.campaign_id=i.campaign_id GROUP BY c.name")
# AVG over the SAME chasm — the mean is biased by the cross-product (each click
# row repeated per impression), which SUM/COUNT-targeted guards don't catch.
AVG_CHASM_SQL = ("SELECT c.name, AVG(k.ts) FROM campaigns c "
                 "JOIN clicks k ON c.campaign_id=k.campaign_id "
                 "JOIN impressions i ON c.campaign_id=i.campaign_id GROUP BY c.name")
# SUM over the SAME chasm — a single satellite's measure summed across the join to
# a SECOND independent satellite over-counts (the ROAS $48T fan-out trap). detect_fanout
# only de-FANS this (and silently proceeds if it can't rewrite); sum_over_chasm_fanout
# is the DROP backstop.
SUM_CHASM_SQL = ("SELECT c.name, SUM(k.amount) FROM campaigns c "
                 "JOIN clicks k ON c.campaign_id=k.campaign_id "
                 "JOIN impressions i ON c.campaign_id=i.campaign_id GROUP BY c.name")


def _run_phase8_with_forced_sql(monkeypatch, forced_sql: str) -> list[str]:
    """Drive the REAL `_phase8_domain_intelligence` loop with the coder forced to
    emit `forced_sql` (and a fake interpreter, reached only if the guard fails to
    drop). Returns the captured `aughor.explorer.agent` log messages. Only the LLM
    is forced — the question→execute→lint→drop path is the real one."""
    import aughor.llm.provider as prov
    import aughor.ontology.store as ostore
    import aughor.sql.writer as wmod
    from aughor.db.connection import open_connection_for
    from aughor.explorer.agent import SchemaExplorer

    # SqlWriter that reports the chasm schema (the guard reads sql_writer.table_cols);
    # fix() is unused because the fake query "succeeds".
    class FakeSqlWriter:
        def __init__(self, conn, *a, **k):
            self.table_cols = CHASM_TC

        def fix(self, *a, **k):
            return SimpleNamespace(ok=False, sql="", final_error="")

    monkeypatch.setattr(wmod, "SqlWriter", FakeSqlWriter)

    ent = SimpleNamespace(id="campaigns", display_name="Campaigns", source_tables=["campaigns"],
                          description="ad campaigns", domain="Marketing")
    monkeypatch.setattr(ostore, "load_latest_ontology",
                        lambda cid, schema_name=None: SimpleNamespace(entities={"campaigns": ent}, relationships={}))

    records: list[str] = []

    class _Cap(logging.Handler):
        def emit(self, r):
            try:
                records.append(r.getMessage())
            except Exception:
                pass

    handler = _Cap()
    lg = logging.getLogger("aughor.explorer.agent")
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    try:
        ex = SchemaExplorer("fixture", open_connection_for("fixture"))
        # The forced chasm SQL references campaigns/clicks/impressions, which need
        # not exist in the fixture warehouse — the grain guard reads the static
        # CHASM_TC from FakeSqlWriter, so only the pre-flight bind check needs to
        # pass. Stub dry_run green to exercise the guard hermetically (no live DDL,
        # and the fixture DB is attached read-only anyway).
        monkeypatch.setattr(ex._conn, "dry_run", lambda _sql: (True, ""))
        ex._state = {}
        monkeypatch.setattr(ex, "_save_state", lambda: None)

        async def fake_run(sql, think=""):
            return [["A", 10], ["B", 20]]

        monkeypatch.setattr(ex, "_run", fake_run)
        real = prov.get_provider

        class FakeLLM:
            def complete(self, *a, response_model=None, **k):
                f = getattr(response_model, "model_fields", {})
                if "sql" in f:        # _NextQuestion → the forced query
                    return response_model(question="q", sql=forced_sql, angle="volume", why="t")
                if "finding" in f:    # _Interpretation (only reached if the guard fails to drop)
                    return response_model(finding="Campaigns vary in volume.", novelty=4, angle_covered="volume")
                return real("coder").complete(*a, response_model=response_model, **k)

        monkeypatch.setattr(prov, "get_provider", lambda role="coder": FakeLLM())
        asyncio.run(asyncio.wait_for(ex._phase8_domain_intelligence(), timeout=120))
    finally:
        lg.removeHandler(handler)
    return records


def test_explorer_phase8_drops_count_star_chasm(monkeypatch) -> None:
    records = _run_phase8_with_forced_sql(monkeypatch, CHASM_SQL)
    fired = [m for m in records if "grain bug" in m and "chasm" in m.lower()]
    assert fired, "the COUNT(*)-chasm grain guard never fired on the real Phase-8 loop"


def test_explorer_phase8_drops_avg_chasm(monkeypatch) -> None:
    records = _run_phase8_with_forced_sql(monkeypatch, AVG_CHASM_SQL)
    fired = [m for m in records if "grain bug" in m and "AVG" in m and "chasm" in m.lower()]
    assert fired, "the AVG-over-chasm grain guard never fired on the real Phase-8 loop"


def test_explorer_phase8_drops_sum_chasm(monkeypatch) -> None:
    records = _run_phase8_with_forced_sql(monkeypatch, SUM_CHASM_SQL)
    fired = [m for m in records if "grain bug" in m and "SUM" in m and "chasm" in m.lower()]
    assert fired, "the SUM-over-chasm grain guard never fired on the real Phase-8 loop"


def test_explorer_phase7_emits_cross_table_insight(monkeypatch) -> None:
    """Runtime LEVERAGE proof for the Phase-7 emit fix (T2): a cross-table insight
    must fire a LIVE `exploration.insight` event tagged phase=cross_table. Before
    the fix Phase-7 only bumped counters (no event, no artifact), so the earliest
    findings never surfaced live. Drives the REAL `_phase7_patterns` method — only
    the DB query (`_run`) and rate-gate are stubbed; the insight creation + the
    `_emit_insight` call site are the real ones."""
    import aughor.kernel.ledger as ledger_mod
    from aughor.db.connection import open_connection_for
    from aughor.explorer.agent import SchemaExplorer

    monkeypatch.setattr(ledger_mod.Ledger, "default",
                        classmethod(lambda cls: SimpleNamespace(artifact_write=lambda *a, **k: None)))

    ex = SchemaExplorer("fixture", open_connection_for("fixture"))
    ex._state = {}
    monkeypatch.setattr(ex, "_save_state", lambda: None)

    journal: list[tuple] = []
    monkeypatch.setattr(ex, "_journal", lambda kind, payload=None: journal.append((kind, payload or {})))

    async def _no_gate():
        return None
    monkeypatch.setattr(ex, "_gate", _no_gate)

    # avg measure varies ~2.5x across the dimension → ratio 2.5 > 1.15 → an insight
    async def fake_run(sql, think=""):
        return [["North", 100.0, 60], ["South", 40.0, 50]]
    monkeypatch.setattr(ex, "_run", fake_run)

    cp = {
        "customers": {"region": SimpleNamespace(
            semantic_type="dimension", is_low_cardinality=True, distinct_count=3, dtype="VARCHAR")},
        "orders": {"amount": SimpleNamespace(
            semantic_type="measure", is_low_cardinality=False, distinct_count=900, dtype="DOUBLE")},
    }
    jmap = {"joins": [{"t1": "orders", "t2": "customers", "c1": "customer_id", "c2": "id"}]}

    asyncio.run(asyncio.wait_for(ex._phase7_patterns(cp, jmap, {}), timeout=30))

    xt = [p for k, p in journal if k == "exploration.insight" and p.get("phase") == "cross_table"]
    assert xt, "Phase-7 cross-table insight did not emit a live exploration.insight event"
    assert "region" in xt[0]["finding"] or "avg" in xt[0]["finding"].lower()
