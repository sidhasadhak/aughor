"""KI-4 (§3.10) — the suggestions loop.

Receipts driven here: usage yields proposals in the SAME lane; a mined trusted
query's provenance names the run it came from (in its note, its payload and its
lineage); acceptance-then-approval visibly moves the learning-plane counts
(`export_sft`/`export_golden` now include human-approved trusted queries, with
`trusted_query` lineage); a re-mine of an unchanged corpus proposes nothing.

Refusals proven too: a question with two distinct validated SQLs is divergence, not a
candidate; a subject-less guard cluster is unmineable; eval-promoted trusted entries
never enter the corpus (consistency is not a human warrant).
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.intake import suggestions

client = TestClient(app)

CONN = "ki4conn"


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_INTAKE_DB", str(tmp_path / "intake.db"))
    monkeypatch.setenv("AUGHOR_TRUSTED_QUERIES_PATH", str(tmp_path / "tq.json"))
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    monkeypatch.setenv("AUGHOR_GLOSSARY_PATH", str(tmp_path / "glossary.yaml"))
    monkeypatch.setenv("AUGHOR_VOCABULARY_ROOT", str(tmp_path / "vocab"))
    import aughor.semantic.connection_kb as kb
    monkeypatch.setattr(kb, "_DATA_DIR", tmp_path / "kb")
    monkeypatch.setattr(kb, "_index_entry", lambda e: None)
    monkeypatch.setattr(kb, "_delete_from_index", lambda c, i: None)
    monkeypatch.setattr(kb, "_invalidate_linker_hints", lambda c: None)
    return tmp_path


@pytest.fixture()
def demo_conn(tmp_path, monkeypatch):
    dbfile = tmp_path / "ki4.duckdb"
    c = duckdb.connect(str(dbfile))
    c.execute("CREATE TABLE orders AS SELECT * FROM (VALUES "
              "('north', 10), ('south', 20)) AS t(region, amount)")
    c.close()
    from aughor.db import connection as conn_mod

    def _open(conn_id, *args, **kwargs):
        if conn_id != CONN:
            raise KeyError(conn_id)
        return conn_mod.DuckDBConnection(dbfile, connection_id=conn_id)

    monkeypatch.setattr(conn_mod, "open_connection_for", _open)
    return CONN


GOOD_SQL = "SELECT region, SUM(amount) AS revenue FROM orders GROUP BY region"


def _wire_sources(monkeypatch, *, examples=None, guard_rows=None, invs=None):
    from aughor.db import history
    from aughor.security.audit import GuardVerdicts
    from aughor.semantic import vector_store

    monkeypatch.setattr(vector_store, "scroll_payloads",
                        lambda collection, limit=10_000: list(examples or []))
    monkeypatch.setattr(GuardVerdicts, "recent",
                        classmethod(lambda cls, limit=2000, **kw: list(guard_rows or [])))
    monkeypatch.setattr(history, "list_investigations",
                        lambda limit=1000: list(invs or []))


def _example(question, sql, inv_id, conn=CONN):
    return {"question": question, "sql": sql, "inv_id": inv_id,
            "connection_id": conn}


# ── the miners ───────────────────────────────────────────────────────────────────────


def test_single_sql_questions_propose_and_divergence_refuses(monkeypatch):
    _wire_sources(monkeypatch, examples=[
        _example("revenue by region", GOOD_SQL, "inv_1"),
        _example("Revenue by region", GOOD_SQL, "inv_2"),      # same, case-folded
        _example("churn by month", "SELECT 1", "inv_3"),       # sql too short — noise
        _example("profit by region", "SELECT a FROM t1 GROUP BY a", "inv_4"),
        _example("profit by region", "SELECT b FROM t2 GROUP BY b", "inv_5"),  # diverges
        _example("other conn", "SELECT x FROM y GROUP BY x", "inv_6", conn="elsewhere"),
    ])
    proposals, pop = suggestions.mine_trusted_from_examples(CONN)
    by_q = {p["question"].lower(): p for p in proposals}
    assert "revenue by region" in by_q and "profit by region" not in by_q
    mined = by_q["revenue by region"]
    # THE receipt: the proposal names the runs it came from.
    assert mined["source_runs"] == ["inv_1", "inv_2"]
    assert "inv_1" in mined["note"] and "inv_2" in mined["note"]
    assert pop["divergent_questions"] == ["profit by region"]
    assert pop["sql_examples"] == 4      # other-conn and short-sql rows never counted...


def test_guard_clusters_need_a_subject_and_a_threshold(monkeypatch):
    fire = lambda pattern, subject, phase="execute": {
        "pattern": pattern, "subject": subject, "phase": phase}
    _wire_sources(monkeypatch, guard_rows=(
        [fire("E1-date-boundary", "orders.created_at")] * 4
        + [fire("preflight_repair", "")] * 24                 # subject-less: unmineable
        + [fire("E1-quoted-identifier", "orders.row_id")] * 2  # below threshold
        + [fire("E1-date-boundary", "orders.created_at", phase="eval")] * 9))
    proposals, pop = suggestions.mine_rules_from_guard_fires(CONN, min_fires=3)
    assert len(proposals) == 1
    assert "orders.created_at" in proposals[0]["title"]
    assert "fired 4 times" in proposals[0]["body"]            # eval fires not counted
    assert pop["clusters_meeting_threshold"] == 1


def test_unresolved_questions_group_and_rank(monkeypatch):
    inv = lambda q, status, cid=CONN: {"question": q, "status": status,
                                       "connection_id": cid, "id": "i1"}
    _wire_sources(monkeypatch, invs=[
        inv("why did margin drop", "failed"),
        inv("Why did margin drop", "timed_out"),
        inv("count of llamas", "failed"),
        inv("fine question", "complete"),
        inv("other conn q", "failed", cid="elsewhere"),
    ])
    out = suggestions.unresolved_questions(CONN)
    assert out[0]["question"].lower() == "why did margin drop"
    assert out[0]["count"] == 2 and out[0]["statuses"] == ["failed", "timed_out"]
    assert len(out) == 2


# ── the lane, the approval, and the learning plane ───────────────────────────────────


def test_suggest_stages_accepts_approves_and_moves_the_corpus(
        stores, demo_conn, monkeypatch):
    _wire_sources(monkeypatch,
                  examples=[_example("revenue by region", GOOD_SQL, "inv_777")],
                  guard_rows=[{"pattern": "E1-date-boundary",
                               "subject": "orders.order_date",
                               "phase": "execute"}] * 3)
    r = client.post("/intake/suggest", json={
        "connection_id": CONN, "actor": "ana@example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["staged"] is True
    assert body["populations"]["trusted"]["proposed"] == 1
    kinds = sorted(c["kind"] for c in body["candidates"])
    assert kinds == ["rule", "trusted_query"]

    # Accept both; the trusted proposal rides KI-0's verified seed → proposed.
    res = client.post(f"/intake/bundles/{body['bundle']['id']}/resolve",
                      json={"actor": "ana@example.com",
                            "accept": [c["id"] for c in body["candidates"]]})
    assert res.status_code == 200 and res.json()["errors"] == 0
    tq_ref = next(x["target_ref"] for x in res.json()["results"]
                  if x["target_ref"].startswith("trusted_query:"))
    tq_id = tq_ref.split(":", 1)[1]
    from aughor.semantic.trusted_queries import get_trusted
    row = get_trusted(tq_id)
    assert row.status == "proposed" and "inv_777" in row.note

    # The second act: approval — and the corpus MOVES, with the tq in the lineage.
    t = client.post(f"/learning/trusted/{tq_id}/transition",
                    json={"action": "approve", "actor": "lead@example.com"})
    assert t.status_code == 200, t.text

    import uuid

    from aughor.learning import exporters, store
    name = f"ki4-receipt-{uuid.uuid4().hex[:8]}"
    sft = exporters.export_sft(name=f"{name}-sft")
    golden = exporters.export_golden(name=f"{name}-golden")
    lineage = (store.lineage_of(sft["id"]) if sft.get("id") else []) + \
              (store.lineage_of(golden["id"]) if golden.get("id") else [])
    assert any(kind == "trusted_query" and src == tq_id
               for kind, src in [(entry["source_kind"], entry["source_id"])
                                 for entry in lineage])
    assert sft["row_count"] + golden["row_count"] >= 1
    # …and the corpus splits it exactly once: SFT xor golden, never both.
    in_sft = any(e["source_id"] == tq_id and e["source_kind"] == "trusted_query"
                 for e in (store.lineage_of(sft["id"]) if sft.get("id") else []))
    in_golden = any(e["source_id"] == tq_id and e["source_kind"] == "trusted_query"
                    for e in (store.lineage_of(golden["id"]) if golden.get("id") else []))
    assert in_sft != in_golden

    # Re-mining the unchanged corpus proposes nothing: same bundle, dedupe.
    again = client.post("/intake/suggest", json={
        "connection_id": CONN, "actor": "ana@example.com"}).json()
    assert again["staged"] is False and again["duplicate"] is True


def test_eval_promoted_and_unverified_rows_never_enter_the_corpus(stores):
    from aughor.learning.exporters import _trusted_export_rows
    from aughor.semantic.trusted_queries import TrustedQuery, save_trusted

    save_trusted(TrustedQuery(id="tq_eval", connection_id=CONN, question="q1",
                              sql="SELECT 1 FROM t", status="approved",
                              source="eval_promotion",
                              verified_by="eval-suite:s1", verified_at="2026-09-05"))
    save_trusted(TrustedQuery(id="tq_legacy", connection_id=CONN, question="q2",
                              sql="SELECT 2 FROM t", status="approved"))  # no verifier
    save_trusted(TrustedQuery(id="tq_draft", connection_id=CONN, question="q3",
                              sql="SELECT 3 FROM t", status="draft",
                              verified_by="x", verified_at="y"))
    save_trusted(TrustedQuery(id="tq_human", connection_id=CONN, question="q4",
                              sql="SELECT 4 FROM t", status="approved",
                              source="api", verified_by="lead@example.com",
                              verified_at="2026-09-05"))
    assert [t.id for t in _trusted_export_rows()] == ["tq_human"]


def test_nothing_minable_reports_populations_and_stages_nothing(
        stores, demo_conn, monkeypatch):
    _wire_sources(monkeypatch)   # every source empty
    r = client.post("/intake/suggest", json={
        "connection_id": CONN, "actor": "ana@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["staged"] is False and "bundle" not in body
    assert body["populations"]["trusted"]["sql_examples"] == 0
    assert "nothing minable" in body["note"]
