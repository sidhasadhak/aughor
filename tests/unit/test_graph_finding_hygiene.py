"""A question is not a finding, and a graph search routes — it does not report.

Measured on the user's own OpenRouter log (2026-09-15): one `search_graph` result
carried TEN near-identical `finding` nodes, each ~2KB, and every one was the scheduled
run's PROMPT — the code-written context block plus the question — not a discovery.
Two writers had stored ``headline or question``, so an answer that concluded nothing
projected its own input as knowledge, and the serving path shipped it whole, twice
(label + summary), re-paid on every later loop turn.

Locked here, at all three seams: the live writer refuses a headline that is the
question; the rebuild collector skips the poisoned historical receipts (so the next
scheduled refresh drops the junk already committed); and the model-facing search clips
summaries and collapses near-identical rows with the cut declared.
"""
from __future__ import annotations


# ── the rebuild collector ───────────────────────────────────────────────────────────

def test_rebuild_skips_receipts_whose_headline_is_the_question(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_LEDGER_DIR", str(tmp_path))
    from aughor.kernel.ledger import Ledger
    from aughor.ontology.context_graph_build import load_investigation_findings

    led = Ledger.default()
    question = ("[Scheduled-run context — written by code, not inferred]\n"
                "This is a scheduled daily run.\n\nWhat changed in theLook?")
    led.artifact_write("chat_answer", "chat:conn-h:inv1",
                       {"question": question, "headline": question, "sql": "SELECT 1",
                        "tables": ["orders"]}, conn_id="conn-h")
    led.artifact_write("chat_answer", "chat:conn-h:inv2",
                       {"question": "how many orders?",
                        "headline": "266 orders on Sep 2, up 19.8% over Sep 1.",
                        "sql": "SELECT 2", "tables": ["orders"]}, conn_id="conn-h")

    findings = load_investigation_findings("conn-h")
    assert [f["text"] for f in findings] == ["266 orders on Sep 2, up 19.8% over Sep 1."]


# ── the live writer's gate ──────────────────────────────────────────────────────────

def test_live_writer_never_projects_the_question(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_LEDGER_DIR", str(tmp_path))
    import aughor.routers.investigations as inv

    noted: list[dict] = []
    monkeypatch.setattr(inv, "_note_finding_on_graph",
                        lambda **kw: noted.append(kw))

    q = "[Scheduled-run context — written by code, not inferred]\nWhat changed?"
    # The caller's own fallback shape: headline arrives AS the question when the run
    # concluded nothing (routers pass `_grounded_headline or question`).
    inv._write_answer_receipt(kind="chat_answer", natural_key="chat:conn-h:a",
                              question=q, sqls=["SELECT 1"], headline=q,
                              schema="", connection_id="conn-h")
    inv._write_answer_receipt(kind="chat_answer", natural_key="chat:conn-h:b",
                              question=q, sqls=["SELECT 1"],
                              headline="Orders fell 7.3% on Sep 5.",
                              schema="", connection_id="conn-h")

    assert [n["headline"] for n in noted] == ["", "Orders fell 7.3% on Sep 5."]
    # And the receipt PAGE still shows something for the inconclusive answer.
    from aughor.kernel.ledger import Ledger
    arts = Ledger.default().artifacts_of_kind(["chat_answer"], conn_id="conn-h", limit=5)
    assert all((a.get("payload") or {}).get("headline") for a in arts)


# ── the model-facing search ─────────────────────────────────────────────────────────

def test_search_result_is_clipped_and_deduped(monkeypatch):
    import aughor.agent.platform_tools as pt

    long_echo = "[Scheduled-run context — written by code, not inferred]\n" + ("x" * 2000)
    def _fake_search(connection_id, query, limit=10):
        return {"available": True, "count": 4, "notice": "", "nodes": [
            {"id": "finding:1", "kind": "finding", "label": long_echo[:80], "summary": long_echo},
            {"id": "finding:2", "kind": "finding", "label": long_echo[:80], "summary": long_echo},
            {"id": "finding:3", "kind": "finding", "label": long_echo[:80], "summary": long_echo},
            {"id": "metric:aov", "kind": "metric", "label": "AOV", "summary": "average order value"},
        ]}
    monkeypatch.setattr("aughor.mcp.knowledge_tools.search_graph", _fake_search)
    monkeypatch.setattr(pt, "_graph_staleness", lambda c: "fresh")

    out = pt.search_graph("conn-h", {"query": "orders"})
    assert out["count"] == 2                                   # 3 echoes → 1 row
    assert out["nodes"][0]["similar"] == 3
    assert len(out["nodes"][0]["summary"]) <= 281              # clipped, not shipped whole
    assert "collapsed" in out["notice"]
    # The whole result is small enough to re-pay per turn without wincing.
    import json
    assert len(json.dumps(out)) < 1200
