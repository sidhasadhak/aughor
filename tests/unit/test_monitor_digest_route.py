"""The alert summary's door answers (found 2026-10-28, taking Arc ED-5's receipt).

`GET /monitors/digest` was declared after `GET /monitors/{monitor_id}`, and FastAPI matches routes in order, so every
call read "digest" as a monitor's id and answered 404 "Monitor not found" — the door had never served. This pins that it
answers its own summary, and refuses a period it does not know with its own words.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


def test_the_digest_door_answers_its_summary_not_a_missing_monitor(client):
    r = client.get("/monitors/digest", params={"conn_id": "digest-door-test", "period": "week"})
    assert r.status_code == 200, r.text
    assert "Monitor not found" not in r.text and "sections" in r.json()


def test_the_digest_door_refuses_a_period_it_does_not_know(client):
    r = client.get("/monitors/digest", params={"conn_id": "digest-door-test", "period": "fortnight"})
    assert r.status_code == 422 and "period must be" in r.text
