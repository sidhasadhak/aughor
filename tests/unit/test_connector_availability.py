"""`/connectors/types` reports whether each tile's driver is actually installed.

The registry defers every driver import to `connect()`, so a type being registered
says nothing about whether it can run. Before this, the picker offered fifteen tiles
on a deployment carrying two drivers, and the user learned which ones worked by
filling in a form and getting an ImportError back.

The install these tests care about is the DEPLOYED one: Vercel installs a project's
base dependencies and no extras, so `warehouse` and `crm` are absent there while a
development machine has them. That is why the base-install case is simulated rather
than asserted against whatever happens to be installed on the machine running this.
"""
from __future__ import annotations

import importlib.util

from fastapi.testclient import TestClient

from aughor.connectors.registry import DRIVERS, missing_drivers

# What `pyproject.toml` lists under [project.dependencies]. Everything else a
# connector imports lives in an extra — declared there, and asserted to be, by
# `tests/unit/test_connector_dependencies.py`.
BASE_INSTALL = {"duckdb", "psycopg2"}


def _simulate_install(monkeypatch, present: set[str]) -> None:
    """Make `find_spec` answer as if only `present` (and stdlib) were installed."""
    real = importlib.util.find_spec

    def fake(name: str, package=None):
        root = name.split(".")[0]
        if root in {"duckdb", "psycopg2", "google", "snowflake", "pymysql",
                    "pyexasol", "ibis", "requests"}:
            return real(name, package) if name.split(".")[0] in present else None
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake)


def test_every_registered_type_declares_its_drivers() -> None:
    """A type with no DRIVERS entry reports no gap, so a missing entry reads as
    'available' forever — the exact failure this module exists to prevent."""
    from aughor.connectors.registry import REGISTRY

    advertised = {"duckdb", "postgres", *REGISTRY.supported_types()}
    undeclared = advertised - set(DRIVERS)
    assert not undeclared, (
        f"connector types advertised by /connectors/types with no DRIVERS entry: "
        f"{sorted(undeclared)} — add one, or the picker will call them available "
        f"whether or not they are"
    )


def test_base_install_serves_duckdb_backed_types(monkeypatch) -> None:
    """The deployed install can serve more than duckdb+postgres: five more types
    are duckdb-backed and need nothing extra."""
    _simulate_install(monkeypatch, BASE_INSTALL)
    for conn_type in ("duckdb", "postgres", "motherduck", "local_upload",
                      "s3", "federated", "gsheets"):
        assert missing_drivers(conn_type) == [], (
            f"{conn_type} should be available on a base install"
        )


def test_base_install_reports_warehouse_and_crm_types_missing(monkeypatch) -> None:
    """The types whose drivers live in an extra must report the gap, not silence."""
    _simulate_install(monkeypatch, BASE_INSTALL)
    expected = {
        "bigquery":   ["google.cloud.bigquery"],
        "snowflake":  ["snowflake.connector"],
        "mysql":      ["pymysql"],
        "exasol":     ["pyexasol"],
        "sqlite":     ["ibis"],
        "stripe":     ["requests"],
        "hubspot":    ["requests"],
        "salesforce": ["requests"],
    }
    for conn_type, missing in expected.items():
        assert missing_drivers(conn_type) == missing, (
            f"{conn_type} should report {missing} missing on a base install"
        )


def test_unknown_type_claims_no_driver_gap() -> None:
    """An unregistered type is a different error; inventing a driver gap for it
    would be a second wrong answer on top of the first."""
    assert missing_drivers("no-such-connector") == []


def test_endpoint_carries_available_and_missing(client: TestClient) -> None:
    r = client.get("/connectors/types")
    assert r.status_code == 200, r.text
    types = r.json()["types"]
    assert types, "no connector types returned"
    for t in types:
        assert "available" in t and isinstance(t["available"], bool), t
        assert "missing" in t and isinstance(t["missing"], list), t
        assert t["available"] is (not t["missing"]), (
            f"{t['type']}: available and missing disagree — {t}"
        )


def test_endpoint_marks_a_driverless_type_unavailable(monkeypatch, client: TestClient) -> None:
    """End-to-end, on a SIMULATED install rather than this machine's.

    This used to name exasol and lean on `pyexasol` being declared in no extra, so it was
    "unavailable in EVERY install" — true, and a defect, until `[warehouse]` started
    pinning it. A test whose premise is a bug passes for the wrong reason the moment the
    bug is fixed; simulating the absent driver asserts the endpoint's contract instead.
    """
    _simulate_install(monkeypatch, BASE_INSTALL)
    types = {t["type"]: t for t in client.get("/connectors/types").json()["types"]}
    assert types["exasol"]["available"] is False
    assert types["exasol"]["missing"] == ["pyexasol"]
    assert types["duckdb"]["available"] is True, (
        "the simulation must not make everything unavailable — then the assertion above "
        "would hold for a reason that has nothing to do with drivers")
