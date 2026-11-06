"""Track B1 (docs/TENX_PROGRAM_2026-11-05.md): where Postgres is promised, the shared-state tests RUN.

Every test that proves the shared Postgres skips itself when no server answers ("no live Postgres to
prove against"). That is right on a laptop and was wrong in CI, where all 23 skipped on every run since
they were written (and 4 pgvector tests beside them) — a green build that had never exercised the
Postgres seam. CI now starts a Postgres
service and sets ``AUGHOR_REQUIRE_PG_TESTS=1``; this test turns the service going missing (a renamed
port, a dropped block in ci.yml) into a red build instead of 23 quiet skips.
"""
from __future__ import annotations

import os

import pytest

PG_URL = os.environ.get("AUGHOR_PG_TEST_URL", "postgres://postgres:aughor@localhost:5544/aughor")


@pytest.mark.skipif(os.environ.get("AUGHOR_REQUIRE_PG_TESTS") != "1",
                    reason="Postgres is promised only where AUGHOR_REQUIRE_PG_TESTS=1 (CI)")
def test_the_promised_postgres_answers():
    import psycopg2
    try:
        psycopg2.connect(PG_URL, connect_timeout=5).close()
    except Exception as exc:  # noqa: BLE001 — any failure to connect is the finding
        pytest.fail(f"AUGHOR_REQUIRE_PG_TESTS=1 but {PG_URL} does not answer ({type(exc).__name__}: {exc}); "
                    "every shared-state test would skip — check the postgres service in .github/workflows/ci.yml")


def test_the_ci_workflow_still_promises_it():
    """The other half: the promise itself cannot be deleted from ci.yml without this test saying so."""
    from pathlib import Path
    ci = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text()
    assert "AUGHOR_REQUIRE_PG_TESTS: \"1\"" in ci and "pgvector/pgvector:pg16@sha256:" in ci
    assert "AUGHOR_PG_TEST_URL:" in ci and "AUGHOR_PGVECTOR_TEST_URL:" in ci
