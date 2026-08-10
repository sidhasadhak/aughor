"""/health reports whether uploads are durable.

Uploads are the one path whose durability was invisible from everywhere else. A
vended capability's files live under /tmp on a serverless instance and mirror to
Blob only when `BLOB_READ_WRITE_TOKEN` is configured; without it `mirror_up` and
`mirror_down` are no-ops and every upload lasts exactly as long as the instance.
Nothing reported that — not /health, not /capabilities — so the failure presented
as files that uploaded fine and were gone later.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.control_plane.object_store import TOKEN_ENV


def test_health_has_object_store_block(client: TestClient) -> None:
    body = client.get("/health").json()
    assert "object_store" in body, f"/health body missing 'object_store': {body}"
    os_block = body["object_store"]
    assert set(os_block) >= {"configured", "env", "detail"}, os_block
    assert isinstance(os_block["configured"], bool)
    assert os_block["env"] == TOKEN_ENV


def test_configured_follows_the_token(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV, "vercel_blob_rw_test_token")
    on = client.get("/health").json()["object_store"]
    assert on["configured"] is True
    assert "durable" in on["detail"]

    monkeypatch.delenv(TOKEN_ENV, raising=False)
    off = client.get("/health").json()["object_store"]
    assert off["configured"] is False
    assert "ephemeral" in off["detail"]


def test_detail_names_the_variable_to_set(client: TestClient, monkeypatch) -> None:
    """The whole point is that an operator reading this knows what to do next."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    detail = client.get("/health").json()["object_store"]["detail"]
    assert TOKEN_ENV in detail, detail
