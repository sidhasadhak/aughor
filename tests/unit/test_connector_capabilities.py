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

#: Every connector class the product can OPEN, resolved from the registry rather than
#: listed by hand.
#:
#: The hand-written list this replaces named three classes and called them "the connectors
#: a user can reach from the SQL workbench" — and `/query` restricts nothing by type, so
#: the premise was false: a Snowflake or BigQuery connection reaches the same route. The
#: guard was therefore green while `execute_with_params` was missing from every warehouse
#: connector — exactly the failure it was written to catch, one level up. A list derived
#: from the registry cannot go stale the next time a connector is added.
def _openable_connectors():
    from aughor.connectors.registry import REGISTRY

    out, unloadable = [DuckDBConnection, PostgresConnection], []
    for conn_type in sorted(REGISTRY.supported_types()):
        try:
            cls = REGISTRY.get_class(conn_type)
        except Exception as exc:
            unloadable.append(f"{conn_type}: {exc}")
            continue
        if cls is not None and cls not in out:
            out.append(cls)
    # A connector whose module will not import is skipped, and a skipped connector is an
    # UNGUARDED one — silence is the failure mode this whole file exists to prevent. Every
    # connector defers its driver import to `connect()`, so a missing optional driver is
    # NOT a reason for this to fail; an import error here is a real breakage.
    assert not unloadable, f"registered connectors this guard could not load: {unloadable}"
    assert LocalUploadConnection in out, (
        "the Workspace's class fell out of the registry walk — it is the class the product "
        "opens BY DEFAULT, and every capability this file guards went missing from it once")
    return out


WORKBENCH_CONNECTORS = _openable_connectors()

#: Connectors deliberately left unable to bind, with the reason. An entry here is a
#: DECISION; an omission is a bug.
NO_BINDING = {
    "ExasolConnection":
        "pyexasol takes query_params by formatting them into the statement text rather "
        "than sending bind values, and the package is installed nowhere here, so the claim "
        "cannot be checked against the driver. See warehouse/exasol.py.",
}

#: Connectors with no driver-handle abort, with the reason. Same contract as NO_BINDING:
#: an entry is a DECISION, an omission is a bug.
#: Empty, and kept anyway. `BigQueryConnection` was the one entry — "cancelling means
#: cancelling a JOB, and this connector does not retain one" — which was true right up
#: until it retained one. The mechanism stays so the next exemption has a home and the
#: rot-guard below keeps watching it.
NO_INTERRUPT: dict[str, str] = {}


@pytest.mark.parametrize("cls", WORKBENCH_CONNECTORS, ids=lambda c: c.__name__)
def test_connector_can_run_parameterised_queries(cls):
    """It must NOT inherit the base's refusal — the base exists to say "no safely",
    not to be the answer for a connector users actually query."""
    if cls.__name__ in NO_BINDING:
        pytest.skip(NO_BINDING[cls.__name__])
    assert cls.execute_with_params is not DatabaseConnection.execute_with_params, (
        f"{cls.__name__} inherits the base refusal, so parameters silently fail on it")


@pytest.mark.parametrize("cls", WORKBENCH_CONNECTORS, ids=lambda c: c.__name__)
def test_a_binding_connector_declares_both_halves(cls):
    """`param_style` without `_bind_execute` renders a statement nothing runs;
    `_bind_execute` without `param_style` is dead code the envelope never reaches. Neither
    half fails loudly on its own."""
    from aughor.connectors.base import Connector

    if cls.__name__ in NO_BINDING or not issubclass(cls, Connector):
        return                               # DuckDB/Postgres bind through their own `_run`
    if cls.execute_with_params is not Connector.execute_with_params:
        return                               # its own implementation, e.g. LocalUpload's `_run`
    assert cls.param_style, f"{cls.__name__} declares no param_style"
    assert cls._bind_execute is not Connector._bind_execute, (
        f"{cls.__name__} declares param_style {cls.param_style!r} but never implements "
        f"_bind_execute, so every bound query raises NotImplementedError")


def test_the_exemption_list_names_only_real_connectors():
    """A rot-guard on the guard: a renamed or deleted connector leaves an entry here that
    exempts nothing, and the next connector to miss binding goes uncaught."""
    names = {c.__name__ for c in WORKBENCH_CONNECTORS}
    for label, exempt in (("NO_BINDING", NO_BINDING), ("NO_INTERRUPT", NO_INTERRUPT)):
        assert set(exempt) <= names, f"{label} names non-connectors: {set(exempt) - names}"


@pytest.mark.parametrize("cls", WORKBENCH_CONNECTORS, ids=lambda c: c.__name__)
def test_connector_can_be_interrupted(cls):
    """Either it overrides `interrupt()`, or it keeps its driver handle where the base
    implementation looks for it (`self._conn`). Anything else means Cancel does
    nothing while reporting success."""
    if cls.__name__ in NO_INTERRUPT:
        pytest.skip(NO_INTERRUPT[cls.__name__])
    if cls.interrupt is not DatabaseConnection.interrupt:
        return                                  # its own implementation; SE-3 F tests it
    # Assert the RESOLVED handle, not the presence of a substring in the source. The
    # substring form (`"self._conn" in source`) passed for S3, Federated, Google Sheets and
    # the three REST mirrors — every one of which keeps its handle on `self._duckdb` and
    # merely happens to contain `self._connection_id`. Six connectors whose Cancel was a
    # silent no-op sat behind a green assertion that matched a field name.
    stub = cls.__new__(cls)                     # no __init__: this asks about the CLASS
    stub._conn = object()
    assert stub._driver_handle() is stub._conn, (
        f"{cls.__name__} uses the base interrupt(), which reaches whatever "
        f"`_driver_handle()` returns — and this class does not resolve to its driver, so "
        f"interrupting is a silent no-op that reports success")
    # The MRO, not the class body: the three REST mirrors assign their handle in
    # `RestApiSync.__init__`, so reading only the subclass source says they assign nothing.
    source = "\n".join(inspect.getsource(k) for k in cls.__mro__
                       if k.__module__.startswith("aughor"))
    assert "self._conn =" in source or "self._duckdb =" in source, (
        f"{cls.__name__} never assigns a driver handle this class knows how to find")


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
