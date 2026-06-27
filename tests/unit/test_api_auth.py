"""The optional AUGHOR_API_KEY front-door gate (AUDIT_2026-06-27.md #10).
OFF by default (no token needed); when set, every non-exempt request must carry
X-Api-Key. /health stays open for liveness probes."""
from __future__ import annotations

from fastapi.testclient import TestClient

import aughor.api as api

client = TestClient(api.app)


def test_no_key_configured_allows_all(monkeypatch):
    monkeypatch.setattr(api, "_API_KEY", "")
    assert client.get("/health").status_code == 200
    # An arbitrary real endpoint is reachable without a key.
    assert client.get("/connections").status_code == 200


def test_key_configured_blocks_without_header(monkeypatch):
    monkeypatch.setattr(api, "_API_KEY", "s3cret")
    r = client.get("/connections")
    assert r.status_code == 401


def test_key_configured_allows_with_correct_header(monkeypatch):
    monkeypatch.setattr(api, "_API_KEY", "s3cret")
    r = client.get("/connections", headers={"X-Api-Key": "s3cret"})
    assert r.status_code == 200


def test_wrong_key_is_rejected(monkeypatch):
    monkeypatch.setattr(api, "_API_KEY", "s3cret")
    r = client.get("/connections", headers={"X-Api-Key": "nope"})
    assert r.status_code == 401


def test_health_exempt_even_with_key(monkeypatch):
    monkeypatch.setattr(api, "_API_KEY", "s3cret")
    assert client.get("/health").status_code == 200
