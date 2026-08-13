"""The workbench capabilities, asserted against every connector the product opens.

**Why this file exists.** Twice in one wave a capability was added to
``DuckDBConnection`` and silently missing from ``LocalUploadConnection`` — the class
behind the demo *Workspace*, which is DuckDB-backed but is a sibling, not a subclass.
Both times every other test passed, because the tests used a `duckdb`-typed connection
and the product opens the other one by default:

* SE-3 F — ``interrupt()``: Cancel was a no-op, found only by driving the browser.
* SE-4 H — ``execute_with_params()``: caught here, by looking for the same mistake.

So the assertion is not "DuckDBConnection has X". It is "**every class we actually
open** has X", which is the thing that was false both times. A new connector that
forgets one of these fails here rather than in someone's browser.
"""
from __future__ import annotations

import inspect

import pytest

from aughor.connectors.file.local_upload import LocalUploadConnection
from aughor.db.connection import DatabaseConnection, DuckDBConnection, PostgresConnection

#: The connector classes a user can reach from the SQL workbench. Postgres is included
#: even though the demo has none — it is a first-class target and its overrides are the
#: ones most likely to drift, being spelled differently at every level (`cancel()` vs
#: `interrupt()`, `%(name)s` vs `$name`).
WORKBENCH_CONNECTORS = [DuckDBConnection, LocalUploadConnection, PostgresConnection]


@pytest.mark.parametrize("cls", WORKBENCH_CONNECTORS, ids=lambda c: c.__name__)
def test_connector_can_run_parameterised_queries(cls):
    """It must NOT inherit the base's refusal — the base exists to say "no safely",
    not to be the answer for a connector users actually query."""
    assert cls.execute_with_params is not DatabaseConnection.execute_with_params, (
        f"{cls.__name__} inherits the base refusal, so parameters silently fail on it")


@pytest.mark.parametrize("cls", WORKBENCH_CONNECTORS, ids=lambda c: c.__name__)
def test_connector_can_be_interrupted(cls):
    """Either it overrides `interrupt()`, or it keeps its driver handle where the base
    implementation looks for it (`self._conn`). Anything else means Cancel does
    nothing while reporting success."""
    if cls.interrupt is not DatabaseConnection.interrupt:
        return                                  # its own implementation; SE-3 F tests it
    source = inspect.getsource(cls)
    assert "self._conn" in source, (
        f"{cls.__name__} uses the base interrupt(), which reaches `self._conn` — but "
        f"this class never assigns it, so interrupting is a silent no-op")


def test_the_base_refuses_rather_than_interpolating():
    """The one thing a connector without binding must never do is build the statement
    by concatenation. The base returns a visible error instead."""
    class _NoBinding(DatabaseConnection):
        dialect = "madeup"
        def execute(self, hypothesis_id, sql): ...
        def get_schema(self): ...
        def test(self): ...
        def close(self): ...

    result = _NoBinding().execute_with_params("query_workbench", "SELECT :v", {"v": "x"})
    assert result.error and "cannot run parameterised" in result.error
    assert result.rows == []
    # The value must not appear anywhere in what came back — no interpolation happened.
    assert "'x'" not in (result.sql or "")


def test_capability_names_cannot_be_confused_with_the_row_cap():
    """`execute_bounded` is a ROW cap and predates this wave; `execute_with_params` is
    binding. An earlier draft called the new one `execute_bound` — one letter apart,
    opposite meanings, on the same class."""
    assert hasattr(DuckDBConnection, "execute_bounded")
    assert not hasattr(DuckDBConnection, "execute_bound")
