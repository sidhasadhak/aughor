"""Learning / Memory-layer read API (Wave 1 · E4) — the closed loop's accumulation, made visible.

Additive, read-only endpoints over existing stores. Hermetic: the ambiguity ledger and trusted-programs
stores are redirected to temp dirs by conftest; trusted-QUERIES (a hardcoded data/ JSON with no env
override — a separate hermeticity gap) is deliberately not seeded here, so the suite never writes live data/.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.org.context import DEFAULT_ORG_ID
from aughor.semantic.ambiguity_ledger import crystallize_user_choice, purge_connections
from aughor.semantic.trusted_programs import TrustedProgram, save_trusted_program

client = TestClient(app)
# A TestClient request carries no identity, so the endpoint scopes to DEFAULT_ORG_ID — seed the same org.


def test_learning_summary_reflects_ledger_burndown():
    conn = "learn_sum_1"
    purge_connections([conn])
    crystallize_user_choice(conn, "top products", "by revenue", org_id=DEFAULT_ORG_ID)  # source=user
    r = client.get("/learning/summary", params={"connection_id": conn})
    assert r.status_code == 200
    body = r.json()
    assert body["connection_id"] == conn
    assert body["ledger"]["resolutions"] >= 1
    assert body["ledger"]["by_source"].get("user", 0) >= 1          # the burn-down attributes by source
    assert isinstance(body["ledger"]["served_total"], int)
    assert "verdicts" in body                                        # acceptance economy present
    assert isinstance(body["trusted"]["queries"], int)
    assert isinstance(body["trusted"]["programs"], int)


def test_learning_summary_is_connection_scoped():
    a, b = "learn_scope_a", "learn_scope_b"
    purge_connections([a, b])
    crystallize_user_choice(a, "revenue definition", "net of refunds", org_id=DEFAULT_ORG_ID)
    rb = client.get("/learning/summary", params={"connection_id": b}).json()
    assert rb["ledger"]["resolutions"] == 0                          # a's resolutions don't leak into b


def test_learning_trusted_lists_programs_without_body():
    conn = "learn_trusted_1"
    tp = save_trusted_program(TrustedProgram(
        connection_id=conn, org_id=DEFAULT_ORG_ID, question="monthly revenue by region",
        program={"steps": [{"op": "aggregate"}]}, plan_source="user"))
    body = client.get("/learning/trusted", params={"connection_id": conn}).json()
    assert isinstance(body["queries"], list)                         # not seeded (live-file store) → shape only
    progs = body["programs"]
    assert any(p.get("id") == tp.id or p.get("question") == "monthly revenue by region" for p in progs)
    assert all("program" not in p for p in progs)                    # heavy program body excluded from the list
