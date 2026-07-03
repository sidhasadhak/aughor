"""REC-02 / SEC-02 / INV-2 — Postgres connections must open READ-ONLY.

Aughor is a read-only analyst; the connection layer must reject writes rather
than relying solely on the (defence-in-depth) SQL safety gate. We assert the
session is opened with ``default_transaction_read_only=on`` via libpq
``options``, which applies before any statement even under autocommit. No live
Postgres is required — we capture the connect kwargs.
"""
from __future__ import annotations

import psycopg2


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return None


class _FakeConn:
    def __init__(self):
        self.autocommit = False

    def cursor(self):
        return _FakeCursor()


def test_postgres_opens_read_only(monkeypatch):
    captured = {}

    def _fake_connect(dsn, **kwargs):
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return _FakeConn()

    monkeypatch.setattr(psycopg2, "connect", _fake_connect)

    from aughor.db.connection import PostgresConnection
    PostgresConnection("postgresql://u:p@localhost/db", schema_name="public")

    assert "options" in captured["kwargs"], "psycopg2.connect must receive libpq options"
    assert "default_transaction_read_only=on" in captured["kwargs"]["options"], (
        f"connection is not read-only: options={captured['kwargs'].get('options')!r}"
    )


def test_read_only_applies_to_parallel_readers(monkeypatch):
    """make_reader() opens a fresh connection via the same _connect path, so it
    must also be read-only — a parallel worker must not become a write hole."""
    calls = []

    def _fake_connect(dsn, **kwargs):
        calls.append(kwargs.get("options"))
        return _FakeConn()

    monkeypatch.setattr(psycopg2, "connect", _fake_connect)

    from aughor.db.connection import PostgresConnection
    conn = PostgresConnection("postgresql://u:p@localhost/db")
    conn.make_reader()

    assert len(calls) == 2, "expected one connect for the base conn and one for the reader"
    assert all(opt and "default_transaction_read_only=on" in opt for opt in calls)
