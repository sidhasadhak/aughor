"""The arc's close-out, C2 — the organisation first, the connection second (the 2027 study §E item 2).

What these hold: a metric scoped `org:<id>` is read by every connection of that organisation between
its own definitions and the install's global ones, and by no other organisation's; the glossary's
`organisations` section sits between the global entries and a connection's overlay, is written by
`organisation=`, and never leaks across organisations; the unscoped reads a person makes (`GET
/metrics`, `GET /glossary`) show one organisation what is its own when identity is on and are
byte-identical when it is off; another organisation's `org:` scope cannot be written; a Briefing's
history is read by its organisation; and the organisation's Briefing is the fold of every visible
connection's latest kept Briefing, a connection with none kept said so.
"""
from __future__ import annotations

import uuid

import pytest
import yaml
from fastapi import HTTPException

from aughor.semantic import glossary as G
from aughor.semantic import metrics as M
from aughor.semantic.metrics import GLOBAL_CONNECTION, MetricDefinition


def _metric(name, sql, connection=GLOBAL_CONNECTION):
    return MetricDefinition(name=name, label=name, sql=sql, connection=connection)


@pytest.fixture
def metrics_path(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text("[]")
    return p


@pytest.fixture
def orgs(monkeypatch):
    """conn_a and conn_c belong to acme, conn_b to other; the registry is not consulted."""
    table = {"conn_a": "acme", "conn_c": "acme", "conn_b": "other"}
    monkeypatch.setattr(M, "organisation_of", lambda cid: table.get(cid, "default"))
    monkeypatch.setattr(G, "organisation_of", lambda cid: table.get(cid, "default"))
    return table


def _identity_on(monkeypatch, org: str, visible: set[str]):
    from aughor.security import authz
    monkeypatch.setattr(authz, "tenant_scope", lambda: org)
    monkeypatch.setattr(authz, "org_visible_conn_ids", lambda: set(visible))


# ── metrics ────────────────────────────────────────────────────────────────────────────────

def test_an_organisations_metric_is_read_between_a_connections_own_and_the_globals(metrics_path, orgs):
    M.save_metric(_metric("revenue", "SELECT SUM(total) FROM orders"), metrics_path)
    M.save_metric(_metric("revenue", "SELECT SUM(net) FROM orders", "org:acme"), metrics_path)
    M.save_metric(_metric("churn", "SELECT 1", "org:acme"), metrics_path)
    M.save_metric(_metric("revenue", "SELECT SUM(gross) FROM sales", "conn_a"), metrics_path)
    assert M.org_scope("acme") == "org:acme" and M.is_org_scope("org:acme") and not M.is_org_scope("conn_a") and not M.is_org_scope(None)
    a = {m.name: m for m in M.list_metrics(metrics_path, connection_id="conn_a")}
    assert a["revenue"].connection == "conn_a" and a["churn"].connection == "org:acme"        # own, then the organisation's
    c = {m.name: m for m in M.list_metrics(metrics_path, connection_id="conn_c")}
    assert c["revenue"].connection == "org:acme" and c["churn"].connection == "org:acme"     # the organisation's, over the global
    b = {m.name: m for m in M.list_metrics(metrics_path, connection_id="conn_b")}
    assert b["revenue"].connection == GLOBAL_CONNECTION and "churn" not in b                # another organisation reads neither
    assert M.get_metric("churn", metrics_path, connection_id="conn_a").connection == "org:acme"
    assert M.get_metric("churn", metrics_path, connection_id="conn_b") is None
    assert [m.name for m in M.list_metrics(metrics_path, connection_id="org:acme")] == ["revenue", "churn"]
    # callers passing no connection read every row, as they always did
    assert len(M.list_metrics(metrics_path)) == 4
    # deleting the organisation's definition leaves the global and the connection's alone
    assert M.delete_metric("revenue", path=metrics_path, connection_id="org:acme") is True
    assert {m.connection for m in M.list_metrics(metrics_path) if m.name == "revenue"} == {GLOBAL_CONNECTION, "conn_a"}


def test_the_unscoped_list_is_one_organisations_when_identity_is_on_and_unchanged_when_off(monkeypatch):
    rows = [_metric("g", "SELECT 1"), _metric("mine", "SELECT 1", "org:acme"), _metric("theirs", "SELECT 1", "org:other"),
            _metric("a", "SELECT 1", "conn_a"), _metric("b", "SELECT 1", "conn_b")]
    assert M.organisation_visible(rows) == rows                                   # identity off: byte-identical
    _identity_on(monkeypatch, "acme", {"conn_a"})
    assert [m.name for m in M.organisation_visible(rows)] == ["g", "mine", "a"]
    from aughor.routers import metrics as R
    monkeypatch.setattr(R, "list_metrics", lambda connection_id=None: rows)
    assert [m["name"] for m in R.get_metrics()] == ["g", "mine", "a"]
    assert len(R.get_metrics(connection_id="conn_a")) == 5                        # a scoped read is the store's own resolution
    with pytest.raises(HTTPException) as e:
        R._require_own_organisation("org:other")
    assert e.value.status_code == 403 and e.value.detail["code"] == "ORGANISATION_SCOPE_DENIED"
    R._require_own_organisation("org:acme")
    R._require_own_organisation("conn_b")                                         # a connection scope is the owner guard's business


# ── glossary ───────────────────────────────────────────────────────────────────────────────

def _glossary(tmp_path) -> "object":
    p = tmp_path / "glossary.yaml"
    p.write_text(yaml.safe_dump({
        "tables": {"orders": {"description": "the install's word", "grain": "one row per order"},
                   "customers": {"description": "everyone's customers"}},
        G.ORGANISATIONS_KEY: {"acme": {"tables": {"orders": {"description": "acme's word", "owner": "Finance"},
                                                  "invoices": {"description": "acme's invoices"}}},
                              "other": {"tables": {"orders": {"description": "the other organisation's word"}}}},
        G.CONNECTIONS_KEY: {"conn_a": {"tables": {"orders": {"grain": "one row per order line"}}},
                            "conn_b": {"tables": {"orders": {"description": "conn_b's own word"}}}},
    }))
    return p


def test_the_organisations_words_sit_between_the_installs_and_the_connections_own(tmp_path, orgs):
    p = _glossary(tmp_path)
    a = G.load_glossary(p, connection_id="conn_a")
    assert a["tables"]["orders"] == {"description": "acme's word", "owner": "Finance", "grain": "one row per order line"}
    assert a["tables"]["invoices"]["description"] == "acme's invoices" and a["tables"]["customers"]["description"] == "everyone's customers"
    assert G.CONNECTIONS_KEY not in a and G.ORGANISATIONS_KEY not in a
    c = G.load_glossary(p, connection_id="conn_c")                              # acme's words with no overlay of its own
    assert c["tables"]["orders"]["description"] == "acme's word" and "invoices" in c["tables"]
    b = G.load_glossary(p, connection_id="conn_b")
    assert b["tables"]["orders"]["description"] == "conn_b's own word" and "invoices" not in b["tables"]
    assert b["tables"]["orders"].get("owner") is None                            # acme's owner never reaches other's connection
    assert G.load_glossary(p)[G.ORGANISATIONS_KEY]["acme"]["tables"]["invoices"]   # the unscoped read is unchanged
    merged = G.load_merged_glossary(p, connection_id="conn_a")
    assert merged["tables"]["orders"]["description"] == "acme's word" and merged["tables"]["invoices"]["description"] == "acme's invoices"
    # a write for the organisation lands in its section, not the global entry
    G.update_table("payments", description="acme's payments", path=p, organisation="acme")
    G.update_column("payments", "amount", description="net of fees", path=p, organisation="acme")
    raw = yaml.safe_load(p.read_text())
    assert raw[G.ORGANISATIONS_KEY]["acme"]["tables"]["payments"] == {"description": "acme's payments", "columns": {"amount": {"description": "net of fees"}}}
    assert "payments" not in raw["tables"]
    assert G.load_glossary(p, connection_id="conn_a")["tables"]["payments"]["description"] == "acme's payments"
    assert "payments" not in G.load_glossary(p, connection_id="conn_b")["tables"]


def test_the_whole_glossary_shows_one_organisation_its_own_when_identity_is_on(tmp_path, monkeypatch):
    data = yaml.safe_load(_glossary(tmp_path).read_text())
    assert G.organisation_visible(data) == data                                  # identity off: byte-identical
    _identity_on(monkeypatch, "acme", {"conn_a"})
    seen = G.organisation_visible(data)
    assert list(seen[G.ORGANISATIONS_KEY]) == ["acme"] and list(seen[G.CONNECTIONS_KEY]) == ["conn_a"]
    assert seen["tables"] == data["tables"]
    from aughor.routers import knowledge as K
    monkeypatch.setattr(K, "load_glossary", lambda: data)
    assert list(K.get_glossary()[G.ORGANISATIONS_KEY]) == ["acme"]
    assert K._organisation_for_write(False) is None and K._organisation_for_write(True) == "default"


# ── the Briefing ───────────────────────────────────────────────────────────────────────────

def test_the_organisations_briefing_folds_every_visible_connections_latest_kept_one_and_says_which_has_none(monkeypatch):
    from aughor.briefing import organisation as O
    from aughor.briefing import versions as V
    cid, empty = "conn-" + uuid.uuid4().hex[:6], "conn-" + uuid.uuid4().hex[:6]
    key = dict(scope_key=cid, range_key="2026-09-01..2026-09-30", recipe="month")
    V.record(cid, {"narrative": "Returns rose.\n\nThe detail follows.", "headline_theme": "Returns rising",
                   "measured": [{"name": "return_rate", "current": 4.1, "unit": "%"}]}, **key)
    V.record(cid, {"narrative": "Returns rose further.\n\nMore.", "headline_theme": "Returns rising",
                   "measured": [{"name": "return_rate", "current": 5.2, "unit": "%"}]}, **key)
    monkeypatch.setattr(O, "_visible_connections", lambda: [{"id": cid, "name": "Shop"}, {"id": empty, "name": "Warehouse"}])
    out = O.organisation_briefing()
    assert out["organisation"] == "default" and out["connections"] == 2 and out["with_briefing"] == 1
    kept = next(r for r in out["briefings"] if r["connection_id"] == cid)
    assert kept["version"] == 2 and kept["headline_theme"] == "Returns rising" and kept["lede"] == "Returns rose further."
    assert kept["figures"] == {"return_rate": 5.2} and kept["as_of"] and kept["connection_name"] == "Shop"
    none = next(r for r in out["briefings"] if r["connection_id"] == empty)
    assert none["briefing"] is None and "no Briefing kept" in none["note"]
    from aughor.routers import briefs as B
    assert B.get_organisation_briefing()["connections"] == 2
    # a Briefing's history is its organisation's: another organisation reading the same key sees nothing
    assert len(V.history(cid, **key)) == 2
    _identity_on(monkeypatch, "acme", set())
    assert V.history(cid, **key) == []
