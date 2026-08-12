"""DATA-06 for the security-read surface: the audit log is tenant-scoped.

`GET /security/audit` returns `sql_full` — the complete text of every statement an
org has run. Before this, it returned every org's rows to any authenticated caller:
the largest single disclosure left on the read path, and the exact route SE-1's
editor history rail is built on.

Conventions follow tests/integration/test_data06_depth.py: identity ON, unique org
ids per test, cross-org asserts only on the outcome (never on which layer produced
it), and localhost mode (identity off) stays unfiltered — pinned explicitly here
because "scoped" must not mean "broken for the single-user install".
"""
from __future__ import annotations

import pytest

from aughor.org.context import using_org
from aughor.security.audit import AuditLogger


@pytest.fixture()
def two_org_rows():
    """One audited statement per org, written with each org's own tenant context."""
    with using_org("auditscope_a"):
        AuditLogger.log(connection_id="conn-a", hypothesis_id="query_workbench",
                        sql="SELECT secret_a FROM orders_a", verdict="safe")
    with using_org("auditscope_b"):
        AuditLogger.log(connection_id="conn-b", hypothesis_id="query_workbench",
                        sql="SELECT secret_b FROM orders_b", verdict="safe")
    yield


def _sqls(payload) -> str:
    return " ".join(r.get("sql_full", "") for r in payload["records"])


def test_audit_read_is_org_scoped(client, monkeypatch, two_org_rows):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    a = client.get("/security/audit", params={"limit": 500},
                   headers={"X-Aughor-Org": "auditscope_a"})
    assert a.status_code == 200
    text_a = _sqls(a.json())
    assert "secret_a" in text_a, "an org must still see its OWN statements"
    assert "secret_b" not in text_a, "another org's SQL text must never appear"

    b = client.get("/security/audit", params={"limit": 500},
                   headers={"X-Aughor-Org": "auditscope_b"})
    assert "secret_b" in _sqls(b.json()) and "secret_a" not in _sqls(b.json())


def test_audit_stats_are_org_scoped(client, monkeypatch, two_org_rows):
    """The aggregate leaks too: how much SQL another tenant runs, and how much of it
    is blocked."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    a = client.get("/security/audit/stats", headers={"X-Aughor-Org": "auditscope_a"}).json()
    b = client.get("/security/audit/stats", headers={"X-Aughor-Org": "auditscope_b"}).json()
    unfiltered = AuditLogger.stats()
    assert a["total"] >= 1 and b["total"] >= 1
    assert a["total"] < unfiltered["total"], "a tenant's total is not the whole log's"


def test_cross_org_connection_filter_is_403_not_empty(client, monkeypatch):
    """An explicit foreign connection_id must be refused, not answered with an empty
    list — "no rows" and "not yours" are different answers, and only one of them
    stops a probe."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    with using_org("auditflt_a"):
        cid = registry.add_connection("audit-flt-conn", "duckdb", "data/aughor.duckdb")
    try:
        r = client.get("/security/audit", params={"connection_id": cid},
                       headers={"X-Aughor-Org": "auditflt_b"})
        assert r.status_code == 403
        assert client.get("/security/audit", params={"connection_id": cid},
                          headers={"X-Aughor-Org": "auditflt_a"}).status_code == 200
    finally:
        registry.delete_connection(cid)


def test_localhost_mode_is_unfiltered(client, two_org_rows):
    """Identity OFF (the default local posture) must stay byte-identical: one operator
    owns every row, and filtering would hide their own history."""
    body = client.get("/security/audit", params={"limit": 500}).json()
    text = _sqls(body)
    assert "secret_a" in text and "secret_b" in text


def test_budget_routes_are_org_scoped(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.security.sandbox import QueryBudget, set_budget
    with using_org("auditbud_a"):
        cid = registry.add_connection("audit-bud-conn", "duckdb", "data/aughor.duckdb")
    set_budget(cid, QueryBudget(max_rows=7))
    try:
        wrong = {"X-Aughor-Org": "auditbud_b"}
        assert client.get(f"/security/budget/{cid}", headers=wrong).status_code == 403
        assert client.put(f"/security/budget/{cid}", json={"max_rows": 1},
                          headers=wrong).status_code == 403
        listed = client.get("/security/budget", headers=wrong).json()["budgets"]
        assert cid not in listed, "another org's budget must not be listed"
        mine = client.get("/security/budget", headers={"X-Aughor-Org": "auditbud_a"}).json()
        assert cid in mine["budgets"], "the owner still sees it"
    finally:
        registry.delete_connection(cid)


def test_governance_feed_audit_sink_is_scoped(client, monkeypatch, two_org_rows):
    """`/audit/feed` reads the SAME audit rows (detail = the whole row, sql_full
    included). A guard whose sibling route is unguarded is not a guard."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get("/audit/feed", params={"category": "data_access", "limit": 500},
                   headers={"X-Aughor-Org": "auditscope_a"})
    if r.status_code == 403:
        pytest.skip("RBAC denied the admin-gated feed for this principal")
    blob = str(r.json())
    assert "secret_b" not in blob, "the feed must not carry another org's SQL"


# ── the ledger sink: scoped by COLUMN, not by payload ────────────────────────────

def test_ledger_events_are_tenant_stamped_and_filterable():
    """The column exists, `emit` stamps it from the ambient tenant, and the reader
    filters on it. Asserted on `govern.tag` specifically: it is the kind whose PAYLOAD
    carried org_id on 0 of 4 live rows, so it is exactly what a payload filter would
    have silently emptied."""
    from aughor.kernel.ledger import Ledger
    ledger = Ledger.default()
    with using_org("ledgerscope_a"):
        ledger.emit("govern.tag", {"tag": "certified"}, conn_id="ledger-conn-a")
    with using_org("ledgerscope_b"):
        ledger.emit("govern.tag", {"tag": "certified"}, conn_id="ledger-conn-b")

    a = ledger.events(kind="govern.tag", org_id="ledgerscope_a", limit=50)
    b = ledger.events(kind="govern.tag", org_id="ledgerscope_b", limit=50)
    assert [e["conn_id"] for e in a] == ["ledger-conn-a"]
    assert [e["conn_id"] for e in b] == ["ledger-conn-b"]

    unfiltered = {e["conn_id"] for e in ledger.events(kind="govern.tag", limit=50)}
    assert {"ledger-conn-a", "ledger-conn-b"} <= unfiltered, \
        "no org filter (localhost) still sees every tenant's rows"


def test_governance_feed_ledger_sink_is_scoped(client, monkeypatch):
    """The feed's third sink — the one this branch first left open — now scopes too."""
    from aughor.kernel.ledger import Ledger
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    with using_org("ledgerfeed_b"):
        Ledger.default().emit("govern.tag", {"tag": "b-only-secret-tag"},
                              conn_id="ledgerfeed-conn-b")
    r = client.get("/audit/feed", params={"category": "governance_change", "limit": 500},
                   headers={"X-Aughor-Org": "ledgerfeed_a"})
    if r.status_code == 403:
        pytest.skip("RBAC denied the admin-gated feed for this principal")
    assert "b-only-secret-tag" not in str(r.json())
