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
# Hermetic connection registry — tests must NEVER mutate data/connections.db (a full
# suite run once emptied the live registry because these paths were hardcoded).
_test_registry_dir = tempfile.mkdtemp(prefix="aughor-test-registry-")
os.environ.setdefault("AUGHOR_REGISTRY_DB", os.path.join(_test_registry_dir, "connections.db"))
os.environ.setdefault("AUGHOR_CONNECTION_SETTINGS", os.path.join(_test_registry_dir, "connection_settings.json"))

# Hermetic remaining stores — history/metastore/workspaces/audit/canvas/... all defaulted to
# the live data/ dir and were mutated in-place by the suite (OPS-02 / DATA-01, the same class
# of bug that once emptied the live registry). Each store now honours an AUGHOR_*_DB override
# (aughor/db/sqlite_util.resolve_db_path); point every one at a throwaway temp dir. MUST run
# before any app module is imported so the module-level _DB_PATH captures the override.
_test_stores_dir = tempfile.mkdtemp(prefix="aughor-test-stores-")
for _env, _file in (
    ("AUGHOR_HISTORY_DB", "history.db"),
    ("AUGHOR_METASTORE_DB", "metastore.db"),
    ("AUGHOR_WORKSPACES_DB", "workspaces.db"),
    ("AUGHOR_AUDIT_DB", "audit.db"),
    ("AUGHOR_CANVAS_DB", "canvases.db"),
    ("AUGHOR_ARTIFACTS_DB", "artifacts.db"),
    ("AUGHOR_EVIDENCE_DB", "evidence_ledger.db"),
    ("AUGHOR_MONITORS_DB", "monitors.db"),
    ("AUGHOR_BRIEFS_FILE", "brief_subscriptions.json"),
    ("AUGHOR_ORGS_DB", "orgs.db"),
    ("AUGHOR_SAVEDQUERY_DB", "saved_queries.db"),
    ("AUGHOR_VOLUMES_DB", "volumes.db"),
    ("AUGHOR_VERDICTS_DB", "verdicts.db"),
    ("AUGHOR_AMBIGUITY_LEDGER_DB", "ambiguity_ledger.db"),
    ("AUGHOR_TRUSTED_PROGRAMS_DB", "trusted_programs.db"),
    ("AUGHOR_PACK_DELTAS_DB", "pack_deltas.db"),
    ("AUGHOR_PACK_BINDINGS_DB", "pack_bindings.db"),
    ("AUGHOR_CHECKPOINTS_DB", "checkpoints.db"),
    ("AUGHOR_IDEMPOTENCY_DB", "idempotency.db"),
    ("AUGHOR_RBAC_DB", "rbac.db"),
    ("AUGHOR_AGENTS_DB", "agents.db"),
    # DuckDB demo stores — without these the suite CREATED data/aughor.duckdb and
    # opened data/samples.duckdb read-write in the developer's live data/ (lock
    # contention with a running app; same class as the registry incident).
    ("AUGHOR_FIXTURE_DB", "aughor.duckdb"),
    ("AUGHOR_SAMPLES_DB", "samples.duckdb"),
):
    os.environ.setdefault(_env, os.path.join(_test_stores_dir, _file))

# The glossary + metrics catalog are file stores (YAML/JSON, not SQLite) with real content — and the
# autoseed / knowledge-sync path WRITES them with no path, so the suite mutated the live
# data/glossary.yaml (task_213affac: it leaked into two commits). Point each at a throwaway temp
# COPY of the real file: tests read identical content, but every write lands in the temp dir and can
# never touch data/. MUST run before any app import so the module-level resolvers see the override.
import shutil as _shutil  # noqa: E402

_repo_data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
for _env, _file in (("AUGHOR_GLOSSARY_PATH", "glossary.yaml"), ("AUGHOR_METRICS_PATH", "metrics.json")):
    _dst = os.path.join(_test_stores_dir, _file)
    _src = os.path.join(_repo_data, _file)
    if os.path.exists(_src) and not os.path.exists(_dst):
        _shutil.copyfile(_src, _dst)
    os.environ.setdefault(_env, _dst)


@pytest.fixture(scope="session", autouse=True)
def _seed_builtin_dbs():
    """Guarantee the builtin demo connections have openable DuckDB files before any
    test. Both are gitignored dev artifacts absent on a clean checkout / CI, and the
    'fixture' connection (used by builtin_conn_id) breaks if its file is missing.
    Runs independently of the app lifespan (whose seeding is fault-isolated)."""
    from aughor.samples.setup import ensure_fixture_db, ensure_samples_db
    ensure_fixture_db()
    ensure_samples_db()
    yield


@pytest.fixture(scope="session", autouse=True)
def _register_agent_plugins():
    """Plug the Agent into the Platform's registries for the whole test session —
    exactly as the live app does at startup (``api.py`` lifespan / the CLI). Without
    this the purge cascade and schema annotators run platform-only, and tests that
    assert the agent's contribution (e.g. ``test_connection_purge``) would fail."""
    from aughor.agent.bootstrap import register_agent_plugins
    register_agent_plugins()
    yield


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
