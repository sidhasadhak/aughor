"""Reference-UX — on-demand /query/validate (re-run the guard battery) + /chat/feedback.
Endpoint-contract tests via the FastAPI client; the guards themselves are covered by
test_join_value_domain / test_fanout. Hermetic."""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app

client = TestClient(app)


def test_validate_requires_sql():
    r = client.post("/query/validate", json={"conn_id": "x", "sql": "   "})
    assert r.status_code == 400


def test_validate_unknown_connection_is_404():
    r = client.post("/query/validate", json={"conn_id": "no-such-conn", "sql": "SELECT 1"})
    assert r.status_code == 404


def test_chat_feedback_is_accepted_and_journaled():
    r = client.post("/chat/feedback", json={"conn_id": "c1", "turn_id": "t1", "verdict": "helpful", "note": "great"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    # unhelpful with no note also accepted (fail-open journaling)
    r2 = client.post("/chat/feedback", json={"conn_id": "c1", "turn_id": "t2", "verdict": "unhelpful"})
    assert r2.status_code == 200
