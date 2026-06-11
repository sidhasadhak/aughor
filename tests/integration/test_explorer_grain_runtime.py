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
    "clicks":      ["click_id", "campaign_id", "ts"],
    "impressions": ["impression_id", "campaign_id", "ts"],
}
CHASM_SQL = ("SELECT c.name, COUNT(*) FROM campaigns c "
             "JOIN clicks k ON c.campaign_id=k.campaign_id "
             "JOIN impressions i ON c.campaign_id=i.campaign_id GROUP BY c.name")


def test_explorer_phase8_drops_count_star_chasm(monkeypatch) -> None:
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
                        lambda cid: SimpleNamespace(entities={"campaigns": ent}, relationships={}))

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
        ex._state = {}
        monkeypatch.setattr(ex, "_save_state", lambda: None)

        async def fake_run(sql, think=""):
            return [["A", 10], ["B", 20]]

        monkeypatch.setattr(ex, "_run", fake_run)
        real = prov.get_provider

        class FakeLLM:
            def complete(self, *a, response_model=None, **k):
                f = getattr(response_model, "model_fields", {})
                if "sql" in f:        # _NextQuestion → the chasm COUNT(*) query
                    return response_model(question="q", sql=CHASM_SQL, angle="volume", why="t")
                if "finding" in f:    # _Interpretation (only reached if the guard fails to drop)
                    return response_model(finding="Campaigns vary in volume.", novelty=4, angle_covered="volume")
                return real("coder").complete(*a, response_model=response_model, **k)

        monkeypatch.setattr(prov, "get_provider", lambda role="coder": FakeLLM())
        asyncio.run(asyncio.wait_for(ex._phase8_domain_intelligence(), timeout=120))
    finally:
        lg.removeHandler(handler)

    fired = [m for m in records if "grain bug" in m and "chasm" in m.lower()]
    assert fired, "the COUNT(*)-chasm grain guard never fired on the real Phase-8 loop"
