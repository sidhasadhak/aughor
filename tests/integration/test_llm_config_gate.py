"""REC-10a / SEC-10 — POST /llm/config is capability-gated.

Changing the inference backend / models / keys is an admin-grade action: an
ungated caller could pivot all inference to an attacker endpoint (exfil). It is
gated behind SECURITY_SUITE. Default tier is enterprise (has it), so behaviour is
unchanged today; a lower tier gets a 402. GET stays open (reports only which keys
are set, needed by the Settings UI).
"""
from __future__ import annotations


def test_post_llm_config_is_gated_for_lower_tier(monkeypatch, client):
    monkeypatch.setenv("AUGHOR_TIER", "free")
    r = client.post("/llm/config", json={"backend": "ollama"})
    assert r.status_code == 402
    detail = r.json()["detail"]
    assert detail["capability"] == "security.suite"


def test_get_llm_config_is_not_gated(monkeypatch, client):
    monkeypatch.setenv("AUGHOR_TIER", "free")
    r = client.get("/llm/config")
    assert r.status_code == 200


def test_post_llm_config_allowed_for_enterprise(monkeypatch, client):
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")
    # Don't actually mutate on-disk provider config — stub the merge.
    from aughor.routers import llm as llm_router
    monkeypatch.setattr(llm_router._provider, "set_config", lambda patch: {"ok": True, "echo": patch})
    r = client.post("/llm/config", json={"backend": "ollama"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
