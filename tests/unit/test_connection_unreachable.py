"""A database that is not running says so, instead of "internal_error".

Measured 2026-11-03: LuxExperience's Docker container was down after a reboot, and drafting its Briefing guide, its
suggestions and its schema each answered `500 {"error": "internal_error"}`, which a page can only print as "failed (500)".
"""
import pytest
from fastapi.testclient import TestClient

from aughor.db.connection import open_connection
from aughor.db.errors import CONNECTION, ConnectionUnreachable, classify_error, is_unreachable

# Port 1 on this machine: nothing listens there, so the driver's refusal below is a real one.
CLOSED = "postgresql://someone:hunter2@localhost:1/nothing"


def test_a_refused_connection_says_where_it_looked_and_keeps_the_password_out():
    pytest.importorskip("psycopg2")
    with pytest.raises(ConnectionUnreachable) as refused:
        open_connection("postgres", CLOSED, connection_id="c1")
    assert refused.value.where == "localhost:1" and refused.value.conn_id == "c1"
    assert "localhost:1" in str(refused.value) and "hunter2" not in str(refused.value)
    assert classify_error(refused.value) == CONNECTION          # what retries and the pool read: unchanged


def test_a_refused_login_is_not_called_a_database_to_start():
    assert not is_unreachable(Exception('connection to server at "h", port 5, failed: FATAL: password authentication failed'))


def test_the_door_answers_what_to_do_instead_of_internal_error(monkeypatch):
    pytest.importorskip("psycopg2")
    from aughor.api import app
    monkeypatch.setattr("aughor.briefing.guide.draft_guide", lambda *a, **k: open_connection("postgres", CLOSED, connection_id="c1"))
    r = TestClient(app, raise_server_exceptions=False).post("/exploration/c1/briefing/guide/draft")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error"] == "connection_unreachable"
    assert body["detail"] == "This connection's database is not answering at localhost:1. Start it, then try again."
