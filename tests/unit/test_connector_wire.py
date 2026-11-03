"""A tile that shares another engine's protocol: read-only is measured, not assumed, and it answers to its own name."""
from __future__ import annotations

import types

import pymysql
import pytest

from aughor.connectors.declarations import ENGINES, declaration
from aughor.connectors.registry import build_connector
from aughor.connectors.warehouse.wire import MySQLWireConnection
from aughor.db.metadata import engine_type_of


class _Cursor:
    def __init__(self, answers):
        self._answers, self._row = answers, None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql):
        answer = next((v for k, v in self._answers.items() if k in sql), None)
        if isinstance(answer, Exception):
            raise answer
        self._row = {"read_only": answer}

    def fetchone(self):
        return self._row


def _fake_mysql(monkeypatch, *, refuses_session: bool, answers: dict):
    seen = []

    def connect(**kwargs):
        seen.append(kwargs.get("init_command"))
        if kwargs.get("init_command") and refuses_session:
            raise pymysql.err.NotSupportedError(1235, "function READ ONLY has only noop implementation in tidb now")
        return types.SimpleNamespace(cursor=lambda: _Cursor(answers), open=True, close=lambda: None)

    monkeypatch.setattr(pymysql, "connect", connect)
    return seen


def test_a_server_that_refuses_a_read_only_session_is_opened_without_one_and_says_so(monkeypatch):
    seen = _fake_mysql(monkeypatch, refuses_session=True, answers={"transaction_read_only": 0})
    conn = MySQLWireConnection("", meta={"host": "h", "port": "4000", "user": "root", "database": "d"})
    assert seen == ["SET SESSION TRANSACTION READ ONLY", None]
    assert conn.engine_read_only is False


def test_a_server_that_takes_it_and_does_nothing_says_so_too(monkeypatch):
    _fake_mysql(monkeypatch, refuses_session=False, answers={"transaction_read_only": 0})
    assert MySQLWireConnection("", meta={"host": "h", "database": "d"}).engine_read_only is False


def test_a_server_that_has_neither_variable_is_not_called_read_only(monkeypatch):
    _fake_mysql(monkeypatch, refuses_session=False, answers={"read_only": pymysql.err.OperationalError(1193, "Unknown system variable")})
    assert MySQLWireConnection("", meta={"host": "h", "database": "d"}).engine_read_only is False


def test_an_older_server_answers_to_the_older_name(monkeypatch):
    _fake_mysql(monkeypatch, refuses_session=False,
                answers={"transaction_read_only": pymysql.err.OperationalError(1193, "Unknown system variable"), "tx_read_only": 1})
    assert MySQLWireConnection("", meta={"host": "h", "database": "d"}).engine_read_only is True


def test_any_other_refusal_stays_a_refusal(monkeypatch):
    def connect(**_):
        raise pymysql.err.OperationalError(1045, "Access denied for user")

    monkeypatch.setattr(pymysql, "connect", connect)
    with pytest.raises(pymysql.err.OperationalError):
        MySQLWireConnection("", meta={"host": "h", "database": "d"})


def test_a_connection_answers_as_the_tile_that_opened_it(monkeypatch):
    _fake_mysql(monkeypatch, refuses_session=False, answers={"transaction_read_only": 1})
    assert engine_type_of(build_connector("tidb", dsn="", meta={"host": "h", "database": "d"})) == "tidb"
    assert engine_type_of(build_connector("doris", dsn="", meta={"host": "h", "database": "d"})) == "doris"


def test_a_shared_class_opened_without_a_tile_answers_as_its_first():
    """Last-wins here would make every MySQL connection answer as Doris, and every Trino one as Starburst."""
    from aughor.connectors.warehouse.mysql import MySQLConnection
    from aughor.connectors.warehouse.trino import TrinoConnection

    assert engine_type_of(MySQLConnection.__new__(MySQLConnection)) == "mysql"
    assert engine_type_of(TrinoConnection.__new__(TrinoConnection)) == "trino"


def test_a_shared_dialect_keeps_its_first_engines_rules():
    from aughor.connectors.declarations import by_dialect

    assert by_dialect()["mysql"].type == "mysql"
    assert by_dialect()["trino"].type == "trino"
    assert by_dialect()["postgres"].type == "postgres"


def test_only_what_passed_on_a_real_server_goes_without_a_badge():
    """The list `tests/integration/test_connectors_on_real_servers.py` ran. A new tile starts on Preview until it runs there."""
    proven = {"cockroachdb", "timescaledb", "mysql", "mariadb", "tidb", "clickhouse", "mssql", "oracle"}
    added_after = {e.type for e in ENGINES[ENGINES.index(declaration("cockroachdb")):]} | {"mysql"}
    for type_ in added_after:
        assert (declaration(type_).badge != "Preview") == (type_ in proven), type_


@pytest.mark.parametrize("said", [
    "(20017, b'DB-Lib error message 20017, severity 9:\\nUnexpected EOF from the server\\n')",
    "(20006, b'DB-Lib error message 20006, severity 9:\\nWrite to the server failed\\n')",
    "Not connected to any MS SQL server",
    "DPY-4011: the database or network closed the connection",
    "DPY-1001: not connected to database",
    "ORA-03113: end-of-file on communication channel",
])
def test_a_lost_server_is_the_connections_fault_not_the_statements(said):
    """Read off servers restarted under an open connection. `sql` here sends the model off to rewrite SQL that was fine."""
    from aughor.db.errors import CONNECTION, classify_error

    assert classify_error(Exception(said)) == CONNECTION
