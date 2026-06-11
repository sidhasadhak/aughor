"""Shared fixtures for Aughor test suite."""
from __future__ import annotations

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

# Point at the builtin DuckDB fixture connection during tests
os.environ.setdefault("AUGHOR_API_KEY", "")  # disable auth in tests
os.environ.setdefault("AUGHOR_CORS_ORIGINS", "*")
# Hermetic kernel ledger — tests must never write to data/system.db
os.environ.setdefault(
    "AUGHOR_SYSTEM_DB",
    os.path.join(tempfile.mkdtemp(prefix="aughor-test-ledger-"), "system.db"),
)


def pytest_addoption(parser):
    parser.addoption(
        "--run-e2e", action="store_true", default=False,
        help="run @pytest.mark.e2e tests that need a live LLM (~100s each); off by default",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip @pytest.mark.e2e tests unless --run-e2e is passed.

    These POST to /investigate, driving the REAL ADA graph + live cloud LLM calls
    (~100s each). The marker was registered in pyproject but never enforced, so a
    headless `pytest tests/integration` RAN them and appeared to hang on network I/O
    (0% CPU). Making e2e opt-in keeps the default suite fast and renders these as
    SKIPPED (visible), never a silent hang.
    """
    if config.getoption("--run-e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="needs --run-e2e (live LLM, ~100s/test)")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient — starts the full app, no live server needed."""
    from aughor.api import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def builtin_conn_id() -> str:
    """The built-in DuckDB fixture connection id ('fixture' or first listed)."""
    return "fixture"
