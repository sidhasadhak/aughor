"""The 2027 study's close-out, C7 (phase 6, "it arrives ready") — what a pack proposes the day a
connection is made (`aughor/packs/connect.py`).

What these hold: a pack's terms land in the connection's vocabulary at source `pack` — below a
person's and this install's mined words, above a model's guess — widen retrieval at once and reach no
prompt until a person confirms one; a decline is a tombstone the next bind cannot resurrect; the
objects' terms wait for the build that matches the map to tables, and say so. A measured prior's band
becomes one `monitor_bundle` proposal per bounded side — the shape the inbox already arms — carrying
the prior's provenance and a backtest of that band on this connection; an unmeasured prior and a metric
the connection has not registered stage nothing and say why; a re-run stages nothing twice. The bind
door proposes both halves; the terms doors confirm and decline; the day-one screen counts them.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.ontology import vocabulary as V
from aughor.ontology.models import OntologyEntity, OntologyGraph
from aughor.packs import connect as X
from aughor.packs.loader import load_pack
from aughor.packs.models import ExpectedObject, Pack, PackManifest, PackMetric, PackOntology
from aughor.packs.roots import pack_dir

D0 = date(2026, 6, 1)


def _conn() -> str:
    return "conn-" + uuid.uuid4().hex[:6]


def _pack(**kw) -> Pack:
    base = dict(manifest=PackManifest(id="bank-test", name="t"),
                metrics=[PackMetric(name="net_interest_margin", title="Net interest margin",
                                    aliases=["NIM", "margin on earning assets", "net interest margin"])],
                ontology=PackOntology(objects=[ExpectedObject(name="Loan", aliases=["credit facility"])]))
    base.update(kw)
    return Pack(**base)


def _graph(conn: str) -> OntologyGraph:
    g = OntologyGraph(connection_id=conn, schema_name="bank", schema_fingerprint="fp-1")
    g.entities["Loan"] = OntologyEntity(id="Loan", display_name="Loan", source_tables=["bank.loans"], identity_key="loan_id",
                                        grain_verified=True)
    return g


# ── terms ──────────────────────────────────────────────────────────────────────────────────

def test_a_packs_terms_are_proposed_at_source_pack_widen_retrieval_and_reach_no_prompt_until_confirmed():
    conn = _conn()
    pack = _pack()
    out = X.propose_terms(pack, conn, graph=_graph(conn))
    # the metric's two aliases (its title and the alias that are the metric's own words are not terms),
    # and the object's name and alias on the table the map matched it to
    assert out["declared"] == 4 and out["proposed"] == 4 and out["already"] == 0
    rows = {(s.subject_kind, s.subject_id, s.synonym): s for s in V.synonyms_for(conn)}
    assert set(rows) == {("metric", "net_interest_margin", "nim"), ("metric", "net_interest_margin", "margin on earning assets"),
                         ("table", "loans", "loan"), ("table", "loans", "credit facility")}
    assert all(s.source == "pack" and s.note.startswith("pack:bank-test") for s in rows.values())
    # retrieval widens at once; the prompt block is byte-identical until a person confirms
    assert V.synonym_expansion(conn)["nim"] == {"net_interest_margin"}
    assert V.build_synonyms_block(conn) == ""
    X.confirm_term(conn, "metric", "net_interest_margin", "NIM", by="user:ana")
    assert '"nim" means metric net_interest_margin' in V.build_synonyms_block(conn)
    assert rows and V.synonyms_for(conn)[0].source == "human" and "confirmed by user:ana" in V.synonyms_for(conn)[0].note
    # a decline is a tombstone: the row goes, and the next bind does not bring it back
    stone = X.decline_term(conn, "table", "loans", "credit facility", by="user:ana", note="we say loan")
    assert stone["status"] == "declined" and stone["source"] == "pack"
    assert ("table", "loans", "credit facility") not in {(s.subject_kind, s.subject_id, s.synonym) for s in V.synonyms_for(conn)}
    again = X.propose_terms(pack, conn, graph=_graph(conn))
    assert again["proposed"] == 0 and again["already"] == 2 and again["confirmed"] == 1 and again["declined"] == 1
    assert ("table", "loans", "credit facility") not in {(s.subject_kind, s.subject_id, s.synonym) for s in V.synonyms_for(conn)}
    status = X.terms_status(pack, conn, graph=_graph(conn))
    assert (status["declared"], status["confirmed"], status["pending"], status["declined"], status["not_proposed"]) == (4, 1, 2, 1, 0)
    assert {r["status"] for r in status["terms"]} == {"confirmed", "proposed", "declined"}


def test_the_objects_terms_wait_for_the_build_and_a_stronger_source_is_left_alone():
    conn = _conn()
    pack = _pack(metrics=[PackMetric(name="net_interest_margin", title="Net interest margin",
                                     aliases=["NIM", "margin on earning assets", "interest margin"])])
    # a person already said "margin on earning assets" and a scan mined "nim": neither is touched
    V.add_synonym(conn, "metric", "net_interest_margin", "margin on earning assets", source="human")
    V.add_synonym(conn, "metric", "net_interest_margin", "nim", source="mined")
    out = X.propose_terms(pack, conn)                      # no graph at bind time
    assert out["note"] == X.OBJECTS_WAIT
    assert out["declared"] == 3 and out["proposed"] == 1 and out["already"] == 1 and out["confirmed"] == 1
    by = {s.synonym: s.source for s in V.synonyms_for(conn)}
    assert by == {"margin on earning assets": "human", "nim": "mined", "interest margin": "pack"}
    # the build matches the map to tables: the objects' terms arrive then, nothing proposed twice
    from aughor.packs.ontology_map import propose_terms_on_build
    import aughor.packs.ontology_map as OM
    graph = _graph(conn)
    OM_bound = OM.bound_pack_ids
    OM.bound_pack_ids = lambda c, s: ["bank-test"]
    OM_load = OM.load_pack_by_id
    OM.load_pack_by_id = lambda pid: pack if pid == "bank-test" else OM_load(pid)
    try:
        built = propose_terms_on_build(graph, conn, "bank")
    finally:
        OM.bound_pack_ids, OM.load_pack_by_id = OM_bound, OM_load
    assert built["bank-test"]["proposed"] == 2 and built["bank-test"]["already"] == 2 and built["bank-test"]["confirmed"] == 1
    assert {(s.subject_kind, s.synonym) for s in V.synonyms_for(conn) if s.subject_kind == "table"} == {("table", "loan"), ("table", "credit facility")}


# ── alerts ─────────────────────────────────────────────────────────────────────────────────

def _metric(name: str):
    return SimpleNamespace(name=name, label=name, status="approved", sql="SUM(net_interest_income) / SUM(earning_assets)",
                           tables=["bank.quarterly"], filters=[], unit="ratio")


def _nim_series(days: int = 420, dips: tuple[int, ...] = (100, 200, 300)):
    rows = []
    for i in range(days):
        v = 0.0326 + (i % 5) * 0.0004
        if i in dips:
            v = 0.015                                     # below the prior's low of 0.02205
        rows.append(((D0 + timedelta(days=i)).isoformat(), v))
    return rows


def _patch_registry(monkeypatch, registered: set[str]):
    monkeypatch.setattr("aughor.semantic.metrics.get_metric",
                        lambda name, path=None, connection_id=None: _metric(name) if name in registered else None)
    monkeypatch.setattr("aughor.settling.sampler.time_tables", lambda cid: [("bank.quarterly", "as_of", 400)])
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: None)


def test_a_measured_priors_band_is_staged_per_side_with_its_provenance_and_backtest_and_the_rest_say_why(monkeypatch):
    from aughor.actions.inbox import get_proposal
    from aughor.monitors.models import Monitor
    _patch_registry(monkeypatch, {"net_interest_margin"})
    conn = _conn()
    banking = load_pack(pack_dir("banking"))
    today = D0 + timedelta(days=420)
    run_sql = lambda sql: (["day", "value"], _nim_series(), None)  # noqa: E731
    out = X.alert_proposals_for(banking, conn, run_sql=run_sql, today=today)
    assert [(s["metric"], s["side"], s["bound"]) for s in out["staged"]] == [
        ("net_interest_margin", "below", 0.02205), ("net_interest_margin", "above", 0.09415)]
    assert out["skipped"]["approval_rate"] == X.UNMEASURED
    assert out["skipped"]["noncurrent_loan_rate"].startswith("metric 'noncurrent_loan_rate' is not registered on this connection")
    below, above = out["staged"]
    assert below["backtest"].startswith("would have fired 3 times in the last 365 days")
    assert above["backtest"].startswith("would never have fired in the last 365 days")
    assert below["measured_on"] == ["fdic-financials-2025-q2"]
    p = get_proposal(below["proposal_id"])
    assert p is not None and p.kind == "monitor_bundle" and p.proposer == "watcher" and p.source == "pack:banking"
    assert p.run_id == f"pack:banking:alerts:{conn}" and p.call_id == "prior:net_interest_margin:below"
    monitor = Monitor(**p.params["monitor"])             # what the accept builds, validated now
    assert (monitor.metric_name, monitor.alert_on, monitor.warning_threshold, monitor.threshold_direction) == (
        "net_interest_margin", "threshold_cross", 0.02205, "below")
    assert monitor.name == "Net interest margin below its prior range"
    assert p.params["automation"]["effects"][1]["config"]["channel"] == ""   # the destination is the approver's
    assert p.detail["to_fill"] and p.detail["prior"]["measured_on"] == ["fdic-financials-2025-q2"]
    assert p.detail["prior"]["sources"] == ["fdic-qbp-2025-q2", "fdic-qbp-2026-q2"]
    assert p.detail["backtest"]["ok"] is True and p.detail["backtest"]["count"] == 3 and p.detail["backtest"]["rule"] == "threshold"
    assert "measured on fdic-financials-2025-q2" in p.reasoning and "falls below 0.02205" in p.reasoning
    assert "would have fired 3 times" in p.reasoning and "Proposed, not armed" in p.reasoning
    # a re-run stages nothing twice; the day-one screen reads both by status
    again = X.alert_proposals_for(banking, conn, run_sql=run_sql, today=today)
    assert again["staged"] == [] and len(again["already_staged"]) == 2
    status = X.alerts_status(banking, conn)
    assert status["by_status"] == {"pending": 2} and {r["side"] for r in status["proposals"]} == {"below", "above"}
    assert status["proposals"][0]["backtest"]


def test_a_band_with_no_series_to_replay_is_still_proposed_and_says_it_has_no_backtest(monkeypatch):
    from aughor.actions.inbox import get_proposal
    _patch_registry(monkeypatch, {"net_interest_margin"})
    conn = _conn()
    banking = load_pack(pack_dir("banking"))
    out = X.alert_proposals_for(banking, conn, run_sql=lambda sql: (["v"], [], None), today=D0 + timedelta(days=420))
    assert len(out["staged"]) == 2
    assert out["staged"][0]["backtest"].startswith("no backtest: nothing to replay")
    p = get_proposal(out["staged"][0]["proposal_id"])
    assert p.detail["backtest"]["ok"] is False and "No backtest on this connection" in p.reasoning


# ── the bind door, the terms doors and the day-one screen ──────────────────────────────────

def _client() -> TestClient:
    from aughor.routers.packs import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_doors_propose_on_connect_then_confirm_and_decline_terms(monkeypatch):
    _patch_registry(monkeypatch, set())
    conn = _conn()
    client = _client()
    r = client.post("/packs/banking/propose", json={"connection_id": conn})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["terms"]["proposed"] > 10 and body["terms"]["note"] == X.OBJECTS_WAIT
    assert body["alerts"]["staged"] == [] and set(body["alerts"]["skipped"]) == {"approval_rate", "net_interest_margin", "noncurrent_loan_rate"}
    terms = client.get(f"/packs/banking/terms?connection_id={conn}").json()
    assert terms["pending"] == body["terms"]["proposed"] and terms["confirmed"] == 0
    nim = next(t for t in terms["terms"] if t["synonym"] == "nim")
    ok = client.post("/packs/banking/terms/confirm", json={"connection_id": conn, "terms": [nim]})
    assert ok.status_code == 200 and ok.json()["confirmed"][0]["status"] == "confirmed" and ok.json()["status"]["confirmed"] == 1
    ldr = next(t for t in terms["terms"] if t["synonym"] == "ldr")
    no = client.post("/packs/banking/terms/confirm", json={"connection_id": conn, "terms": [ldr], "decline": True, "note": "not our word"})
    assert no.status_code == 200 and no.json()["declined"][0]["status"] == "declined" and no.json()["status"]["declined"] == 1
    assert client.post("/packs/banking/terms/confirm", json={"connection_id": conn, "terms": [{"subject_kind": "planet"}]}).status_code == 422
    assert client.post("/packs/nope/propose", json={"connection_id": conn}).status_code == 404
    # the day-one screen carries both halves
    from aughor.packs.onboarding import onboarding
    day_one = onboarding(conn, None, pack_id="banking", graph=None)
    assert day_one["arrival"]["terms"][0]["confirmed"] == 1 and day_one["arrival"]["terms"][0]["declined"] == 1
    assert day_one["arrival"]["alerts"][0]["by_status"] == {}


def test_binding_a_pack_proposes_its_terms_and_alerts_and_the_binding_stands_when_it_cannot(monkeypatch):
    _patch_registry(monkeypatch, set())
    monkeypatch.setattr("aughor.routers.connections.open_connection_for", lambda cid: (_ for _ in ()).throw(RuntimeError("unreachable")))
    conn = _conn()
    client = _client()
    r = client.post("/packs/banking/bind", json={"connection_id": conn, "bindings": {}, "verified": False})
    assert r.status_code == 200, r.text
    arrival = r.json()["arrival"]
    assert arrival["pack"] == "banking" and arrival["terms"]["proposed"] > 10 and arrival["alerts"]["staged"] == []
    assert any(s.source == "pack" for s in V.synonyms_for(conn))
