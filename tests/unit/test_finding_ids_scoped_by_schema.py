"""A finding's id is unique across its connection (`explorer.store.scoped_finding_id`).

Measured on LuxExperience, 2026-10-11: the Postgres connection explores three schemas, each with its own Key Questions,
and every schema's first one was ``pinned__0``. The ledger keeps a finding's receipt under the connection and the id,
so the three were one receipt — and the pinned pass, reading its last answer back from that receipt, put
gold_finance's answers (etl_load_log, fact_reconciliation_test) into luxexperience's Briefing. A run over one schema of
several now puts the schema in front of every id it mints; findings kept from before take it once, each with a receipt
that is its own; and a removed schema takes its findings' receipts.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aughor.explorer import dossier, store
from aughor.explorer.dossier import receipt_key as K
from aughor.explorer.agent import SchemaExplorer
from aughor.kernel.ledger import Ledger


def _f(fid: str, words: str, sql: str) -> dict:
    return {"id": fid, "domain": "Key Questions", "finding": words, "sql": sql, "generated_at": "2026-10-11T09:00:00"}


def _explorer(schema: str | None, *, canvas: str | None = None, state: dict | None = None) -> SchemaExplorer:
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.connection_id, ex.schema_name, ex.canvas_id = "lux", schema, canvas
    ex._store_key = f"lux__{schema}" if schema else "lux"
    ex._state = state if state is not None else {store.FINDINGS: []}
    ex._stopped, ex._conn = False, SimpleNamespace(dialect="postgres")
    return ex


def test_an_id_takes_its_schema_once_and_a_whole_connection_keeps_its_ids():
    assert store.scoped_finding_id("gold_finance", "pinned__0") == "gold_finance:pinned__0"
    assert store.scoped_finding_id("gold_finance", "gold_finance:pinned__0") == "gold_finance:pinned__0"
    assert store.scoped_finding_id(None, "pinned__0") == "pinned__0"
    assert store.scoped_finding_id("", "pinned__0") == "pinned__0"
    assert _explorer("gold_finance")._finding_id("synth__share__1") == "gold_finance:synth__share__1"
    assert _explorer(None)._finding_id("synth__share__1") == "synth__share__1"            # theLook: unchanged
    assert _explorer("gold_finance", canvas="cv1")._finding_id("pinned__0") == "pinned__0"  # a canvas keeps its own


def test_each_schema_reads_back_its_own_pinned_answer():
    led = Ledger.default()
    led.artifact_write("finding", K("lux", "gold_finance:pinned__0"),
                       _f("gold_finance:pinned__0", "12 loads failed", "SELECT 12 FROM gold_finance.etl_load_log"),
                       conn_id="lux")
    led.artifact_write("finding", K("lux", "luxexperience:pinned__0"),
                       _f("luxexperience:pinned__0", "Conversion is 31%", "SELECT 0.31"), conn_id="lux")
    assert _explorer("luxexperience")._read_prior_pinned(0)["finding"] == "Conversion is 31%"
    assert _explorer("gold_finance")._read_prior_pinned(0)["finding"] == "12 loads failed"
    assert _explorer("gold_governance")._read_prior_pinned(0) is None                    # never another schema's


def test_kept_findings_take_their_schema_with_a_receipt_of_their_own():
    led = Ledger.default()
    mine = _f("pinned__1", "Conversion is 31%", "SELECT 0.31")
    led.artifact_write("finding", K("lux2", "pinned__1"), {**mine, "dossier": {"question": "conversion?"}},
                       conn_id="lux2")
    theirs = _f("pinned__2", "Bookings fell 4%", "SELECT -0.04")
    led.artifact_write("finding", K("lux2", "pinned__2"),                   # gold_finance's run wrote over it
                       _f("pinned__2", "12 loads failed", "SELECT 12 FROM gold_finance.etl_load_log"), conn_id="lux2")
    alike = _f("pinned__4", "Orders rose 3%", "SELECT COUNT(*) FROM orders")    # the same query in two schemas
    led.artifact_write("finding", K("lux2", "pinned__4"), {**alike, "finding": "Orders fell 9%", "dossier": {"q": 1}},
                       conn_id="lux2")
    state = {store.FINDINGS: [dict(mine), dict(theirs), _f("luxexperience:pinned__3", "x", "SELECT 1"), dict(alike)]}

    assert dossier.rescope("lux2", "luxexperience", state) == 3
    assert [f["id"] for f in state[store.FINDINGS]] == [
        "luxexperience:pinned__1", "luxexperience:pinned__2", "luxexperience:pinned__3", "luxexperience:pinned__4"]
    same_query = led.receipt(K("lux2", "luxexperience:pinned__4"))["artifact"]["payload"]
    assert (same_query["finding"], same_query.get("dossier")) == ("Orders rose 3%", None)    # its words, not theirs
    own = led.receipt(K("lux2", "luxexperience:pinned__1"))
    assert own["artifact"]["payload"]["dossier"] == {"question": "conversion?"}            # its derivation carried over
    assert own["artifact"]["payload"]["id"] == "luxexperience:pinned__1"
    other = led.receipt(K("lux2", "luxexperience:pinned__2"))["artifact"]["payload"]
    assert (other["finding"], other["sql"], other.get("dossier")) == ("Bookings fell 4%", "SELECT -0.04", None)
    assert dossier.rescope("lux2", "luxexperience", state) == 0                              # once
    assert dossier.rescope("lux2", "", state) == 0


def test_a_finding_reading_another_schema_is_set_aside_not_renamed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    leaked = _f("pinned__0", "12 loads failed", "SELECT 12 FROM gold_finance.etl_load_log")
    ex = _explorer("luxexperience", state={store.FINDINGS: [leaked, _f("pinned__1", "Conversion is 31%", "SELECT 0.31")]})
    ex._rescope_findings()
    held = store.load("lux__luxexperience")[store.FINDINGS]                                   # saved at once
    assert [(f["id"], bool(f.get("invalid"))) for f in held] == [
        ("luxexperience:pinned__0", True), ("luxexperience:pinned__1", False)]
    assert "another schema" in held[0]["invalid_reason"]

    # Ids already scoped, one finding leaking: setting it aside alone is saved.
    ex = _explorer("luxexperience", state={store.FINDINGS: [_f("luxexperience:pinned__5", "12 loads failed",
                                                                 "SELECT 12 FROM gold_finance.etl_load_log")]})
    ex._rescope_findings()
    assert [(f["id"], f.get("invalid")) for f in store.load("lux__luxexperience")[store.FINDINGS]] == [
        ("luxexperience:pinned__5", True)]


def test_a_pinned_answer_reading_another_schema_is_not_reproduced(monkeypatch):
    ex = _explorer("luxexperience")
    ex._activity_unchanged = True

    async def _gate():
        return None

    emitted: list = []
    ex._gate = _gate
    ex._read_prior_pinned = lambda qi: _f("luxexperience:pinned__0", "12 loads failed",
                                          "SELECT 12 FROM gold_finance.etl_load_log")
    ex._order_keys_projected = lambda sql: False
    ex._emit_insight = lambda *a, **k: emitted.append(a)
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: None)
    profile = SimpleNamespace(key_questions=["How many loads failed?"], key_question_sql=[])
    wrote: list = []

    def _write(*a, **k):                    # past the read-back, the question is asked afresh
        wrote.append(1)
        raise RuntimeError("no model here")

    asyncio.run(ex._pass_pinned_questions(profile, SimpleNamespace(table_cols={}, schema="", write=_write), ""))
    assert wrote == [1] and emitted == [] and ex._state[store.FINDINGS] == []


def test_removing_a_schema_takes_its_findings_receipts_and_leaves_its_siblings():
    from aughor.db import purge
    led = Ledger.default()
    led.artifact_write("finding", K("lux3", "gold_finance:pinned__0"), {"f": 1}, conn_id="lux3")
    led.artifact_write("finding", K("lux3", "gold_finance:synth__share__1"), {"f": 2}, conn_id="lux3")
    led.artifact_write("finding", K("lux3", "goldXfinance:pinned__0"), {"f": 3}, conn_id="lux3")  # `_` is no wildcard
    led.artifact_write("finding", K("lux3", "gold_finance_2:pinned__0"), {"f": 4}, conn_id="lux3")
    led.artifact_write("finding", K("lux3", "pinned__0"), {"f": 5}, conn_id="lux3")
    counts = purge.purge_schema_artifacts("lux3", "gold_finance")
    assert counts["finding_receipts"] == 2
    assert led.artifact_latest(K("lux3", "gold_finance:pinned__0")) is None
    for kept in ("goldXfinance:pinned__0", "gold_finance_2:pinned__0", "pinned__0"):
        assert led.artifact_latest(K("lux3", f"{kept}")) is not None


def test_every_id_the_explorer_mints_goes_through_the_schema():
    import inspect
    import re
    from aughor.explorer import agent
    src = inspect.getsource(agent)
    minted = re.findall(r"fresh_finding_id\(self\._state,\s*([^\n]+)", src)
    assert len(minted) >= 2 and all(m.startswith("self._finding_id(") for m in minted), minted
    assert not re.search(r'"id":\s*f"', src)                    # no id written as a bare literal
    assert re.search(r"_id = self\._finding_id\(f\"\{t_dim\}", src)  # the cross-table pass
