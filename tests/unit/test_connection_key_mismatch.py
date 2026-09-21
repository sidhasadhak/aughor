"""A connection whose credentials cannot be decrypted says so, instead of "internal_error".

Measured 2026-09-21: `.env` lost `AUGHOR_SECRET_KEY`, all 7 connections became undecryptable, and
every request that opened one returned `500 {"error": "internal_error", "request_id": …}`. It
failed — correctly — but hid the one cause the operator could fix behind a request id.
"""
import duckdb
from cryptography.fernet import Fernet


def _connection_under_a_new_key(client, tmp_path, monkeypatch):
    from aughor.db import pool, registry
    from aughor.semantic.metrics import MetricDefinition, save_metric
    db = tmp_path / "w.duckdb"
    w = duckdb.connect(str(db))
    w.execute("CREATE TABLE t AS SELECT 5 AS a")
    w.close()
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "m.json"))
    (tmp_path / "m.json").write_text("[]")
    monkeypatch.setenv("AUGHOR_SECRET_KEY", Fernet.generate_key().decode())   # saved under A
    conn_id = registry.add_connection("theLook", "duckdb", str(db))
    save_metric(MetricDefinition(name="m", label="M", sql="SUM(a)", tables=["t"],
                                 connection=conn_id, status="approved"))
    assert client.get(f"/metrics/m/value?conn_id={conn_id}").json()["value"] == 5.0
    monkeypatch.setenv("AUGHOR_SECRET_KEY", Fernet.generate_key().decode())   # read under B
    try:
        pool.evict_conn(conn_id)
    except Exception:
        pass
    return conn_id, str(db)


def test_a_key_mismatch_names_its_cause_and_the_connection(client, tmp_path, monkeypatch):
    conn_id, _ = _connection_under_a_new_key(client, tmp_path, monkeypatch)
    r = client.get(f"/metrics/m/value?conn_id={conn_id}")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error"] == "connection_key_mismatch", "it read as an internal error"
    assert body["connection_id"] == conn_id
    assert "cannot be decrypted" in body["detail"] and "'theLook'" in body["detail"]


def test_it_is_not_reported_as_a_missing_connection(client, tmp_path, monkeypatch):
    """Routes turn KeyError into "404 Connection not found". A key mismatch is not that — the
    connection is right there — so the error must not be a KeyError."""
    from aughor.db.registry import ConnectionKeyMismatch
    assert not issubclass(ConnectionKeyMismatch, KeyError)
    conn_id, _ = _connection_under_a_new_key(client, tmp_path, monkeypatch)
    assert client.get(f"/metrics/m/value?conn_id={conn_id}").status_code != 404


def test_the_error_carries_no_secret(client, tmp_path, monkeypatch):
    """Not the key, and not the DSN — the credential that could not be read stays unread."""
    import os
    conn_id, dsn = _connection_under_a_new_key(client, tmp_path, monkeypatch)
    text = client.get(f"/metrics/m/value?conn_id={conn_id}").text
    assert os.environ["AUGHOR_SECRET_KEY"] not in text
    assert dsn not in text
