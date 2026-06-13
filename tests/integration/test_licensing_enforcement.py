"""Licensing enforcement — the capability model + that gated routes actually 402.

The `aughor/licensing/` scaffold existed but no route called `require_capability`.
These pin (a) the tier→capability matrix and (b) that wired routes return HTTP 402
when the resolved tier lacks the capability, while staying open at the default
`enterprise` tier (so the gate lands dark).
"""
from fastapi.testclient import TestClient

from aughor.licensing import Capability, Tier, has_capability, capabilities_for


# ── capability model (pure) ──────────────────────────────────────────────────

class TestCapabilityModel:
    def test_tiers_are_additive(self):
        free = capabilities_for(Tier.FREE)
        pro = capabilities_for(Tier.PRO)
        ent = capabilities_for(Tier.ENTERPRISE)
        assert free <= pro <= ent

    def test_free_lacks_pro_features(self):
        for cap in (Capability.MONITORS, Capability.METRICS_DEFINE,
                    Capability.ACTION_HUB, Capability.SCHEDULED_BRIEFS,
                    Capability.PLAYBOOK, Capability.FEDERATION):
            assert cap not in capabilities_for(Tier.FREE)
            assert cap in capabilities_for(Tier.PRO)

    def test_free_keeps_core(self):
        for cap in (Capability.CONNECT, Capability.CATALOG, Capability.NL2SQL_CHAT,
                    Capability.QUERY_BUILDER):
            assert cap in capabilities_for(Tier.FREE)

    def test_has_capability_uses_env_default(self, monkeypatch):
        monkeypatch.setenv("AUGHOR_TIER", "free")
        assert has_capability(Capability.MONITORS) is False
        monkeypatch.setenv("AUGHOR_TIER", "enterprise")
        assert has_capability(Capability.MONITORS) is True

    def test_unknown_tier_falls_back_to_enterprise(self, monkeypatch):
        monkeypatch.setenv("AUGHOR_TIER", "nonsense")
        assert has_capability(Capability.SECURITY_SUITE) is True   # everything on


# ── route gating (real path via TestClient) ──────────────────────────────────

class TestRouteGating:
    def test_free_tier_402s_a_gated_write(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("AUGHOR_TIER", "free")
        r = client.post("/metrics", json={"name": "gate_probe", "label": "X", "sql": "SUM(x)"})
        assert r.status_code == 402
        body = r.json()["detail"]
        assert body["capability"] == "metrics.define"
        assert body["current_tier"] == "free" and body["error"] == "capability_locked"
        # gate fired before the handler → nothing was persisted
        assert all(m["name"] != "gate_probe" for m in client.get("/metrics").json())

    def test_free_tier_402s_monitors_with_upgrade_hint(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("AUGHOR_TIER", "free")
        r = client.post("/monitors", json={
            "name": "x", "connection_id": "y", "metric": "revenue",
            "monitor_type": "threshold", "threshold": 1.0,
        })
        assert r.status_code == 402
        assert r.json()["detail"]["capability"] == "monitors"
        assert "upgrade_hint" in r.json()["detail"]

    def test_enterprise_tier_does_not_gate(self, client: TestClient, monkeypatch):
        # default/enterprise tier → the gate is open: an invalid body reaches validation
        # (422), never 402. Proves wiring the dependency is a no-op at enterprise.
        monkeypatch.setenv("AUGHOR_TIER", "enterprise")
        r = client.post("/metrics", json={"label": "missing name + sql"})
        assert r.status_code != 402

    def test_reads_are_not_gated(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("AUGHOR_TIER", "free")
        assert client.get("/metrics").status_code == 200   # listing is free
