"""Shared fixtures for Aughor test suite."""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

# Point at the builtin DuckDB fixture connection during tests
os.environ.setdefault("AUGHOR_API_KEY", "")  # disable auth in tests
os.environ.setdefault("AUGHOR_CORS_ORIGINS", "*")


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
