"""POST /overview/drill records a per-connection prior end-to-end (route + wiring).

The store itself is unit-tested in tests/unit/test_overview_drills.py; this pins the
HTTP seam: the route is registered, the request model binds, and a drill lands in the
prior the next overview reads back.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.overview.drills import load_priors


def test_overview_drill_endpoint_records_prior(client: TestClient):
    r = client.post("/overview/drill", json={
        "connection_id": "ep_conn", "lens": "concentration", "table": "s.orders"})
    assert r.status_code == 204
    p = load_priors("ep_conn")
    assert p["lens"].get("concentration") == 1
    assert p["table"].get("s.orders") == 1


def test_overview_drill_endpoint_is_fire_and_forget_on_empty_body(client: TestClient):
    # Empty body → field defaults → a no-op record, but still 204: the client's
    # best-effort capture call must never surface an error.
    assert client.post("/overview/drill", json={}).status_code == 204
