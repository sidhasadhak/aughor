"""KI-1 (§3.10) — the intake lane.

The receipts this file IS: a bundle round-trips (upload → plan → accept N / dismiss M);
accepted objects land in their EXISTING stores through each store's own governance
(a metric arrives `proposed`, a trusted query goes through KI-0's verified seed and is
NOT prompt-authoritative until that store's own approve); a provenance query walks an
accepted object → bundle hash → source; and an identical re-import plans ZERO pending
decisions — the idempotence that makes the door safe to point a sync at.

Hermetic: every target store rides a per-test env override or monkeypatched path; the
connection is a real read-only DuckDB file behind a patched `open_connection_for`.
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app

client = TestClient(app)

CONN = "ki1conn"


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    """Point every store the lane fans out to at this test's own files."""
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
    dbfile = tmp_path / "ki1.duckdb"
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


def _bundle(**extra):
    b = {
        "version": 1,
        "connection_id": CONN,
        "sections": {
            "metrics": [{"name": "net_revenue", "label": "Net Revenue",
                         "sql": "SUM(amount)", "tables": ["orders"]}],
            "synonyms": [{"subject_kind": "column", "subject_id": "orders.amount",
                          "synonym": "sales value", "source": "human"}],
            "glossary": [{"table": "orders", "description": "One row per order line.",
                          "grain": "order line",
                          "columns": {"amount": {"description": "Line total, EUR."}}}],
            "rules": [{"title": "Fiscal year", "body": "FY starts in February.",
                       "tags": ["finance"]}],
            "joins": [{"title": "orders to regions",
                       "body": "Join orders.region to regions.name; N:1."}],
            "trusted_queries": [{"question": "revenue by region",
                                 "sql": "SELECT region, SUM(amount) AS revenue "
                                        "FROM orders GROUP BY region",
                                 "note": "pre-aggregate, then join"}],
        },
    }
    b.update(extra)
    return b


def _upload(bundle, source="acme-dictionary"):
    return client.post("/intake/bundles", json={
        "actor": "ana@example.com", "source": source, "bundle": bundle})


# ── refusals at the door ─────────────────────────────────────────────────────────────


def test_forward_version_and_unknown_sections_are_refused(stores):
    r = _upload({"version": 99, "connection_id": CONN, "sections": {"metrics": []}})
    assert r.status_code == 400 and "newer than this build" in r.json()["detail"]
    r2 = _upload({"version": 1, "connection_id": CONN,
                  "sections": {"prophecies": []}})
    assert r2.status_code == 400 and "unknown section" in r2.json()["detail"]


def test_malformed_rows_are_refused_not_staged(stores, demo_conn):
    b = _bundle()
    b["sections"]["metrics"].append({"label": "No name, no sql"})
    r = _upload(b)
    assert r.status_code == 201
    body = r.json()
    assert any("name and sql are required" in x for x in body["refused"])
    assert all(c["kind"] != "metric" or c["payload"].get("name") == "net_revenue"
               for c in body["candidates"])


# ── plan verdicts ────────────────────────────────────────────────────────────────────


def test_plan_verdicts_against_live_stores(stores, demo_conn):
    # Pre-seed the stores so the plan has something to diff against.
    from aughor.semantic.metrics import MetricDefinition, save_metric
    from aughor.semantic.trusted_queries import TrustedQuery, save_trusted
    from aughor.evals.promote_trusted import trusted_id

    save_metric(MetricDefinition(name="net_revenue", label="Net Revenue",
                                 sql="SUM(net)", connection="*",
                                 status="approved", version=2,
                                 approved_by="Finance"))
    save_trusted(TrustedQuery(
        id=trusted_id(CONN, "revenue by region"), connection_id=CONN,
        question="revenue by region", sql="SELECT 1", status="approved",
        version=1, verified_by="lead@example.com"))

    r = _upload(_bundle())
    assert r.status_code == 201, r.text
    by_kind = {}
    for c in r.json()["candidates"]:
        by_kind.setdefault(c["kind"], []).append(c)

    # The approved metric differs → conflict, naming what differs.
    assert by_kind["metric"][0]["verdict"] == "conflict"
    assert "sql" in by_kind["metric"][0]["detail"]
    # The approved trusted answer differs → conflict, naming the verifier.
    assert by_kind["trusted_query"][0]["verdict"] == "conflict"
    assert "APPROVED" in by_kind["trusted_query"][0]["detail"]
    # Nothing else exists yet → new.
    for kind in ("synonym", "glossary", "rule", "join"):
        assert by_kind[kind][0]["verdict"] == "new", kind


# ── the human verdicts, and where accepted objects land ──────────────────────────────


def test_accept_fans_out_through_each_stores_governance(stores, demo_conn):
    r = _upload(_bundle())
    assert r.status_code == 201, r.text
    bundle_id = r.json()["bundle"]["id"]
    cands = {c["kind"]: c for c in r.json()["candidates"]}
    accept = [cands[k]["id"] for k in
              ("metric", "synonym", "glossary", "rule", "trusted_query")]
    dismiss = [cands["join"]["id"]]

    res = client.post(f"/intake/bundles/{bundle_id}/resolve",
                      json={"actor": "ana@example.com",
                            "accept": accept, "dismiss": dismiss})
    assert res.status_code == 200, res.text
    assert res.json()["accepted"] == 5 and res.json()["dismissed"] == 1
    assert res.json()["errors"] == 0

    # Metric: in the metrics WORKFLOW, proposed — never approved by an import.
    from aughor.semantic.metrics import get_metric
    m = get_metric("net_revenue", connection_id=CONN)
    assert m is not None and m.status == "proposed"
    assert m.proposed_by == "ana@example.com"

    # Trusted query: through KI-0's door — verified, proposed, NOT in the prompt.
    from aughor.semantic.trusted_queries import get_trusted, retrieve_trusted
    from aughor.evals.promote_trusted import trusted_id
    row = get_trusted(trusted_id(CONN, "revenue by region"))
    assert row is not None and row.status == "proposed"
    assert row.verification.get("passed") is True
    assert row.source.startswith("intake:")
    assert retrieve_trusted("revenue by region", CONN) == []

    # Synonym: the vocabulary writer finally has a consumer.
    from aughor.ontology.vocabulary import synonyms_for
    assert any(s.synonym == "sales value" for s in synonyms_for(CONN))

    # Glossary: table + column descriptions landed.
    from aughor.semantic.glossary import load_glossary
    entry = (load_glossary() or {})["tables"]["orders"]
    assert entry["description"].startswith("One row per order")
    assert entry["columns"]["amount"]["description"] == "Line total, EUR."

    # Rule: a connection-KB entry; the dismissed join wrote NOTHING.
    from aughor.semantic.connection_kb import load_entries
    kinds = {e.kind for e in load_entries(CONN)}
    assert "rule" in kinds and "join" not in kinds


def test_identical_reimport_plans_zero_pending(stores, demo_conn):
    first = _upload(_bundle())
    bundle_id = first.json()["bundle"]["id"]
    ids = [c["id"] for c in first.json()["candidates"]]
    client.post(f"/intake/bundles/{bundle_id}/resolve",
                json={"actor": "ana@example.com", "accept": ids})

    # Byte-identical re-upload: content-hash dedupe returns the SAME bundle.
    again = _upload(_bundle())
    assert again.json()["duplicate"] is True
    assert again.json()["bundle"]["id"] == bundle_id

    # Semantically identical (different hash): everything plans `identical`,
    # staged as noop — ZERO pending decisions. The receipt.
    third = _upload(_bundle(exported_note="same content, new file"))
    assert third.status_code == 201 and third.json()["duplicate"] is False
    cands = third.json()["candidates"]
    pending = [c for c in cands if c["status"] == "pending"]
    assert pending == [], [(c["kind"], c["verdict"], c["detail"]) for c in pending]
    assert {c["verdict"] for c in cands} == {"identical"}


def test_failed_apply_keeps_the_candidate_pending(stores, demo_conn):
    b = _bundle()
    # Passes planning (question+sql present) but the connection cannot run it —
    # KI-0's seed still stores it as a DRAFT, which counts as landed, so use a
    # metric whose apply genuinely raises instead: sql blanked via an EDIT.
    r = _upload(b)
    bundle_id = r.json()["bundle"]["id"]
    metric_cand = next(c for c in r.json()["candidates"] if c["kind"] == "metric")
    res = client.post(f"/intake/bundles/{bundle_id}/resolve",
                      json={"actor": "ana@example.com",
                            "accept": [metric_cand["id"]],
                            "edits": {metric_cand["id"]: {"name": "net_revenue",
                                                          "sql": "   "}}})
    assert res.status_code == 200
    assert res.json()["errors"] == 1
    from aughor.intake import store
    cand = store.get_candidate(metric_cand["id"], org_id="default")
    assert cand["status"] == "pending"   # not lost — editable and retryable


# ── provenance and the round trip ────────────────────────────────────────────────────


def test_provenance_walks_object_to_bundle_hash_and_source(stores, demo_conn):
    r = _upload(_bundle(), source="acme-q3-dictionary")
    bundle_id = r.json()["bundle"]["id"]
    tq_cand = next(c for c in r.json()["candidates"] if c["kind"] == "trusted_query")
    client.post(f"/intake/bundles/{bundle_id}/resolve",
                json={"actor": "ana@example.com", "accept": [tq_cand["id"]]})

    from aughor.intake import store
    applied = store.get_candidate(tq_cand["id"], org_id="default")
    assert applied["target_ref"].startswith("trusted_query:tq_")

    p = client.get("/intake/provenance", params={"ref": applied["target_ref"]}).json()
    assert p["found"] is True
    trail = p["trail"][0]
    assert trail["bundle_source"] == "acme-q3-dictionary"
    assert trail["uploaded_by"] == "ana@example.com"
    assert trail["content_hash"] == r.json()["bundle"]["content_hash"]


def test_export_reimports_as_all_identical(stores, demo_conn):
    # Land everything, approve the trusted query so the export carries it.
    r = _upload(_bundle())
    bundle_id = r.json()["bundle"]["id"]
    client.post(f"/intake/bundles/{bundle_id}/resolve",
                json={"actor": "ana@example.com",
                      "accept": [c["id"] for c in r.json()["candidates"]]})
    from aughor.evals.promote_trusted import trusted_id
    tq_id = trusted_id(CONN, "revenue by region")
    t = client.post(f"/learning/trusted/{tq_id}/transition",
                    json={"action": "approve", "actor": "lead@example.com"})
    assert t.status_code == 200, t.text

    exported = client.get(f"/intake/export/{CONN}").json()
    assert "yaml_text" in exported and exported["bundle"]["sections"]["trusted_queries"]

    back = _upload(exported["bundle"], source="round-trip")
    assert back.status_code == 201, back.text
    cands = back.json()["candidates"]
    not_identical = [(c["kind"], c["verdict"], c["detail"])
                     for c in cands if c["verdict"] != "identical"]
    assert not_identical == []


# ── the governance feed knows the new kind ───────────────────────────────────────────


def test_intake_governance_kind_is_categorized_and_sunk():
    from aughor.govern.audit_categories import category_for, feed
    from aughor.kernel.ledger import Ledger

    assert category_for("intake.governance") == "governance_change"
    Ledger.default().emit("intake.governance", {
        "action": "resolve", "bundle": "ib_feedcheck", "actor": "t",
        "accepted": 3, "dismissed": 1, "errors": 0, "at": "2026-09-05T00:00:00"})
    got = [e for e in feed(category="governance_change", limit=200)
           if e.kind == "intake.governance"
           and (e.detail or {}).get("bundle") == "ib_feedcheck"]
    assert got and "3 accepted" in got[0].summary
