"""WP-10 — the unified public Trust Receipt (`GET /receipt/{id}`).

Pins: the ledger resolves an EXACT artifact version by id; the public projection surfaces
executed SQL / tables / fired guards / caveats / governed-metric enforcement / model; the HMAC
signature verifies and a tampered field fails it; the route round-trips and 404s on an unknown
id AND (fail-closed, no existence leak) on a receipt outside the caller's org.
"""
from __future__ import annotations

from aughor.kernel.ledger import Ledger
from aughor.trust.receipt import build_public_receipt, verify


def _write(led: Ledger, natural_key: str, *, conn_id: str = "c1", **payload) -> str:
    base = {"question": "how many customers?", "headline": "800 customers",
            "sql": "SELECT COUNT(*) FROM customers", "tables": ["customers"],
            "model": {"role": "coder", "id": "glm-5.2:cloud"}}
    base.update(payload)
    return led.artifact_write(
        "chat_answer", natural_key, base, conn_id=conn_id,
        lineage=[("source_sql", "sql", "SELECT COUNT(*) FROM customers"),
                 ("input", "table:customers", None),
                 ("flagged", "guard:measure_grain", "measure summed at the wrong grain"),
                 ("validated_by", "guard:fan_out_defan", "rewrote SQL to prevent over-counting"),
                 ("metric_used", "metric:customer_count", "matched governed metric")])


def test_artifact_by_id_resolves_the_exact_version():
    led = Ledger.default()
    v1 = _write(led, "chat:c1:versioned", headline="v1")
    v2 = _write(led, "chat:c1:versioned", headline="v2")
    assert v1 != v2
    # by-id resolves the EXACT version handed out (an immutable link), not the latest.
    assert led.artifact_by_id(v1)["payload"]["headline"] == "v1"
    assert led.artifact_by_id(v2)["payload"]["headline"] == "v2"
    assert led.artifact_latest("chat:c1:versioned")["payload"]["headline"] == "v2"


def test_public_receipt_projection_surfaces_the_trust_signals():
    led = Ledger.default()
    rid = _write(led, "chat:c1:proj")
    pub = build_public_receipt(led.receipt_by_id(rid),
                               connection={"id": "c1", "name": "Test", "dialect": "duckdb"})
    assert pub["mode"] == "quick"
    assert pub["question"] == "how many customers?"
    assert [s["sql"] for s in pub["executed_sql"]] == ["SELECT COUNT(*) FROM customers"]
    assert pub["input_tables"] == ["customers"]
    names = {g["name"]: g["action"] for g in pub["guards"]}
    assert names == {"measure_grain": "flagged", "fan_out_defan": "validated_by"}
    assert "measure summed at the wrong grain" in pub["caveats"]   # a flagged guard → caveat
    assert pub["metrics"]["used"] == ["customer_count"]
    assert pub["model"] == {"role": "coder", "id": "glm-5.2:cloud"}
    assert pub["connection"]["dialect"] == "duckdb"


def test_signature_verifies_and_tamper_fails():
    led = Ledger.default()
    pub = build_public_receipt(led.receipt_by_id(_write(led, "chat:c1:sig")))
    assert pub["signature"] and verify(pub)
    tampered = {**pub, "headline": "1,000,000 customers"}   # change a number
    assert not verify(tampered)                             # signature no longer matches
    # An unsigned build is not accepted as verified.
    unsigned = build_public_receipt(led.receipt_by_id(_write(led, "chat:c1:sig2")), signed=False)
    assert "signature" not in unsigned and not verify(unsigned)


def test_receipt_route_roundtrips(client):
    led = Ledger.default()
    rid = _write(led, "chat:c1:route")
    r = client.get(f"/receipt/{rid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == rid and body["mode"] == "quick"
    assert body["executed_sql"][0]["sql"] == "SELECT COUNT(*) FROM customers"
    assert verify(body)                       # the served receipt is self-verifying


def test_receipt_route_404_on_unknown_id(client):
    assert client.get("/receipt/does-not-exist-000").status_code == 404


def test_receipt_route_404_on_foreign_org(client, monkeypatch):
    """A receipt whose connection is not org-visible returns 404 (fail-closed, no leak)."""
    led = Ledger.default()
    rid = _write(led, "chat:secretconn:x", conn_id="secretconn")
    # Simulate identity-on with a visible set that excludes this receipt's connection.
    monkeypatch.setattr("aughor.security.authz.org_visible_conn_ids", lambda: {"other_conn"})
    assert client.get(f"/receipt/{rid}").status_code == 404
    # Same call with the connection visible → 200 (proves it's the org gate, not a bad id).
    monkeypatch.setattr("aughor.security.authz.org_visible_conn_ids", lambda: {"secretconn"})
    assert client.get(f"/receipt/{rid}").status_code == 200


# ── WP-10 extend: Query Builder run carries a signed receipt ──────────────────

def test_query_run_returns_a_resolvable_builder_receipt(client):
    """POST /query/run on a successful query returns a receipt_id that resolves to a signed
    `builder` receipt (Why-this-number on the Query Builder surface)."""
    r = client.post("/query/run", json={
        "conn_id": "fixture", "sql": "SELECT COUNT(*) AS n FROM customers", "limit": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("error") is None, body
    rid = body.get("receipt_id")
    assert rid, "a successful query run should carry a receipt id"

    rec = client.get(f"/receipt/{rid}")
    assert rec.status_code == 200, rec.text
    pub = rec.json()
    assert pub["mode"] == "builder"
    assert pub["executed_sql"][0]["sql"] == "SELECT COUNT(*) AS n FROM customers"
    assert "customers" in pub["input_tables"]
    assert verify(pub)                       # server-signed


def test_query_run_blocked_sql_has_no_receipt(client):
    """A blocked (mutating) query returns no receipt id."""
    r = client.post("/query/run", json={"conn_id": "fixture", "sql": "DELETE FROM customers"})
    assert r.status_code == 200
    assert r.json().get("receipt_id") is None
