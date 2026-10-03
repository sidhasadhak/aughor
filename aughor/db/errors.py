"""DE-3d (ROADMAP §3.51) — what kind of error the engine gave: ``connection``, ``timeout``, ``cancelled`` or ``sql``.

Every connector caught its driver's exception and handed back ``QueryResult(error=str(e))``: a dropped socket, a
statement timeout, the person's Cancel and a typo in a column name all read the same way, so nothing above the door
could tell a statement that must not be retried (the person's, failed on its own SQL) from a pooled connection that
is dead and must not be handed out again. dbx's sidecar types each error and says whether the operation may have
reached the database; this is the read-only half of that.

Classified by the driver exception's class name and message, never by importing the driver: the connectors'
drivers are optional installs, and a classifier that imports psycopg2 to recognise a psycopg2 error would fail to
import on the machine that has only pymysql. The lists below are each driver's own names — psycopg2, pymysql,
snowflake-connector, google-api-core, pyexasol, duckdb, sqlite3 and the standard library — and the message patterns
are the texts those drivers put in them. Unknown is ``sql``: the kind that is never retried and never evicts.
"""
from __future__ import annotations

import re

CONNECTION = "connection"
TIMEOUT = "timeout"
CANCELLED = "cancelled"
SQL = "sql"
KINDS = (CONNECTION, TIMEOUT, CANCELLED, SQL)

# DE-3b: a DRIVER's exception names live on its engine's declaration (`connectors/declarations.py`:
# `connection_errors` / `timeout_errors` / `cancelled_errors`) and are derived here; only the names
# no engine owns — the standard library's and the HTTP stacks' — are written in this module.
from aughor.connectors.declarations import derive_error_names  # noqa: E402

_DRIVER_NAMES = derive_error_names()

#: Exception class names that are a lost or unreachable connection on their own.
_CONNECTION_NAMES = frozenset({
    "ConnectionError", "ConnectionResetError", "ConnectionRefusedError", "ConnectionAbortedError",         # stdlib
    "BrokenPipeError", "RemoteDisconnected", "ConnectError", "ReadError", "WriteError",                   # http
}) | _DRIVER_NAMES["connection"]
#: Exception class names that are a timeout on their own.
_TIMEOUT_NAMES = frozenset({"TimeoutError", "ReadTimeout", "ConnectTimeout", "Timeout", "ReadTimeoutError",
                            "WriteTimeout", "PoolTimeout"}) | _DRIVER_NAMES["timeout"]
#: Exception class names that are a cancelled statement on their own.
_CANCELLED_NAMES = frozenset({"CancelledError", "Cancelled", "KeyboardInterrupt"}) | _DRIVER_NAMES["cancelled"]
#: pymysql's `OperationalError` carries a SQL refusal (1792, a read-only transaction) as readily as a lost server;
#: the errno decides. 2002/2003: cannot connect; 2006: server has gone away; 2013: lost connection during query;
#: 2055: lost connection to the server at the socket; 4031: the server closed an idle connection.
_MYSQL_CONNECTION_CODES = frozenset({2002, 2003, 2006, 2013, 2055, 4031})

_TIMEOUT_TEXT = re.compile(r"statement timeout|timed out|time out|timeout|deadline exceeded|exceeded the (?:configured )?time limit", re.I)
_CANCELLED_TEXT = re.compile(r"cancel(?:l)?ed|canceling statement due to user request|interrupt|aborted by user|query aborted", re.I)
_CONNECTION_TEXT = re.compile(
    r"server has gone away|lost connection|connection (?:was |is |has been )?(?:closed|reset|refused|lost|aborted|broken)|"
    r"could not connect|not connected|no connection to the server|broken pipe|ssl syscall|terminating connection|"
    r"connection already closed|failed to get the response|connection timed out|network (?:error|is unreachable)|"
    r"name or service not known|temporary failure in name resolution|server closed the connection|socket (?:closed|error)",
    re.I)


def classify_error(exc: BaseException) -> str:
    """The kind of ``exc``, one of :data:`KINDS`. Timeout is read before cancelled, because Postgres reports a
    statement timeout as a cancelled query ("canceling statement due to statement timeout")."""
    name = type(exc).__name__
    text = str(exc)
    if name in _TIMEOUT_NAMES or _TIMEOUT_TEXT.search(text):
        return TIMEOUT
    if name in _CANCELLED_NAMES or _CANCELLED_TEXT.search(text):
        return CANCELLED
    if name in _CONNECTION_NAMES or _CONNECTION_TEXT.search(text):
        return CONNECTION
    if name == "OperationalError":
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        if code in _MYSQL_CONNECTION_CODES:
            return CONNECTION
        # psycopg2's OperationalError is the connection's (could not connect, server closed), pymysql's is any
        # server error; a psycopg2 one that said nothing above is still the connection's.
        if (type(exc).__module__ or "").startswith("psycopg2"):
            return CONNECTION
    return SQL
