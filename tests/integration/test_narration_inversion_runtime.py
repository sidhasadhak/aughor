"""Runtime LEVERAGE proofs for the narration-inversion guard — proof that the guard
actually FIRES on each real code path, not just that the detector works in isolation.

Unit tests (test_narration_inversion.py) prove the detector. These prove the WIRING:
the guard is reached with real values and takes its effect on the real path. The
triggering condition is LLM-nondeterministic, so each test FORCES it (monkeypatch the
interpreter/coder/narrator to emit the inverting output) and then drives the actual
endpoint / node / loop and asserts the drop or caveat lands.

Why this file exists: the guard was first shipped "wired" with only unit tests + a
"same pattern as the sibling guards" argument. That is exactly the gap the
BUILT→WIRED→TESTED→LEVERAGED principle exists to catch — so each surface is now proven
at runtime here.
"""
from __future__ import annotations

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

# rows where the value 3 is ONE OF several differing values → a universal "3" is wrong
VARYING = [[1, 3], [2, 5], [3, 2]]


# ── Chat: an inverted headline gets the inline caveat on the real /chat path ───

# Live-LLM: only the coder role is faked; the /chat headline path still calls a real
# provider (the narrator), so this needs a live LLM and is excluded from CI (-m "not e2e").
@pytest.mark.e2e
def test_chat_caveat_fires_on_real_endpoint(client: TestClient, builtin_conn_id: str, monkeypatch) -> None:
    import aughor.llm.provider as prov
    from aughor.routers.investigations import _ChatAnswer

    monkeypatch.setenv("AUGHOR_COMPILER", "0")  # run the injected SQL verbatim, not the compiler
    real = prov.get_provider

    class FakeCoder:
        def complete(self, *a, **k):
            return _ChatAnswer(
                sql="SELECT * FROM (VALUES (1,3),(2,5),(3,2)) AS t(items, order_count)",
                headline="All orders have 3 items.",
            )

    monkeypatch.setattr(prov, "get_provider",
                        lambda role="coder": FakeCoder() if role == "coder" else real(role))

    headline = None
    t0 = time.monotonic()
    with client.stream("POST", "/chat", json={
        "connection_id": builtin_conn_id, "question": "how many items per order?", "mode": "ask",
    }) as r:
        assert r.status_code == 200, r.text
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                try:
                    e = json.loads(line[5:].strip())
                except Exception:
                    continue
                if e.get("type") == "headline":
                    headline = e.get("headline")
                    break
            if time.monotonic() - t0 > 60:
                pytest.fail("/chat did not emit a headline in time")
    assert headline, "no headline event"
    assert "varies across the data" in headline, f"caveat did not fire on the real path: {headline!r}"


# ── ADA: an inverted report gets a DataQualityNote on the real synthesize_report ─

def test_ada_caveat_note_lands_on_real_node(monkeypatch) -> None:
    import aughor.agent.nodes as nodes
    from aughor.agent.state import AnalysisReport, Finding, QueryResult

    class FakeNarrator:
        def complete(self, *a, **k):
            return AnalysisReport(
                headline="All orders have 3 items.",
                verdict="Basket size looks uniform.",
                key_findings=[Finding(claim="All orders have 3 items, so basket size is constant.",
                                      evidence="", confidence=0.9)],
                what_is_not_the_cause=[], data_quality_notes=[], risks=[], recommended_actions=[],
            )

    real = nodes.get_provider
    monkeypatch.setattr(nodes, "get_provider",
                        lambda role="coder": FakeNarrator() if role == "narrator" else real(role))

    state = {
        "query_history": [QueryResult(hypothesis_id="h", sql="SELECT items, order_count FROM t",
                                      columns=["items", "order_count"], rows=VARYING, row_count=3)],
        "question": "how many items per order?", "hypotheses": [], "pitfalls": [],
        "query_mode": "explore", "connection_id": "fixture",
    }
    report = nodes.synthesize_report(state)["report"]
    issues = " ".join(n.issue for n in report.data_quality_notes)
    assert "varies" in issues or "over-generalises" in issues, (
        f"inversion DataQualityNote did not land on the real node: {issues!r}"
    )


# ── Explorer: an inverted Phase-8 finding is DROPPED by the real guard chain ────

def test_explorer_phase8_drops_inversion_on_real_loop(monkeypatch) -> None:
    import asyncio
    import logging
    from types import SimpleNamespace

    import aughor.llm.provider as prov
    import aughor.ontology.store as ostore
    import aughor.sql.writer as wmod
    from aughor.db.connection import open_connection_for
    from aughor.explorer.agent import SchemaExplorer

    # SqlWriter reporting a schema where the forced SQL's columns are REAL, so the
    # schema-grounding pre-flight (invented-identifiers guard) doesn't drop the
    # query before it reaches the narration-inversion guard under test. The fixture
    # warehouse needn't actually contain these columns — only the static
    # table_cols + a green dry_run are needed (and the warehouse is read-only).
    class FakeSqlWriter:
        def __init__(self, conn, *a, **k):
            self.table_cols = {"customers": ["customer_id", "items", "order_count"]}

        def fix(self, *a, **k):
            return SimpleNamespace(ok=False, sql="", final_error="")

    monkeypatch.setattr(wmod, "SqlWriter", FakeSqlWriter)

    # Inject a minimal ontology so Phase 8 runs hermetically (no pre-built ontology
    # in the isolated test system DB). The loop only reads id/display_name/
    # source_tables/description/domain + relationships, so a tiny stand-in suffices.
    ent = SimpleNamespace(id="customers", display_name="Customers",
                          source_tables=["customers"], description="customer records",
                          domain="Commerce")
    fake_ont = SimpleNamespace(entities={"customers": ent}, relationships={})
    monkeypatch.setattr(ostore, "load_latest_ontology", lambda cid, schema_name=None: fake_ont)

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
        ex._state = {}                                        # fresh budget so the loop body runs
        monkeypatch.setattr(ex, "_save_state", lambda: None)  # never persist
        monkeypatch.setattr(ex._conn, "dry_run", lambda _sql: (True, ""))  # bind check green (no live tables)

        async def fake_run(sql, think=""):
            return VARYING                                    # every query → a varying distribution

        monkeypatch.setattr(ex, "_run", fake_run)
        real = prov.get_provider

        class FakeLLM:
            def complete(self, *a, response_model=None, **k):
                f = getattr(response_model, "model_fields", {})
                if "sql" in f:        # _NextQuestion → one controlled question
                    return response_model(question="q", sql="SELECT items, order_count FROM customers",
                                          angle="volume", why="t")
                if "finding" in f:    # _Interpretation → the INVERTING claim
                    return response_model(finding="All orders have 3 items.", novelty=4, angle_covered="volume")
                return real("coder").complete(*a, response_model=response_model, **k)

        monkeypatch.setattr(prov, "get_provider", lambda role="coder": FakeLLM())
        asyncio.run(asyncio.wait_for(ex._phase8_domain_intelligence(), timeout=120))
    finally:
        lg.removeHandler(handler)

    fired = [m for m in records if "skipping narration inversion" in m]
    assert fired, "the Phase-8 inversion guard never fired on the real loop"
