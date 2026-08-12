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
    ("AUGHOR_ORG_LLM_DB", "org_llm.db"),
    ("AUGHOR_SAVEDQUERY_DB", "saved_queries.db"),
    ("AUGHOR_VOLUMES_DB", "volumes.db"),
    ("AUGHOR_VERDICTS_DB", "verdicts.db"),
    ("AUGHOR_AMBIGUITY_LEDGER_DB", "ambiguity_ledger.db"),
    ("AUGHOR_OVERLAY_LEDGER_DB", "overlay_ledger.db"),
    ("AUGHOR_PACK_DELTAS_DB", "pack_deltas.db"),
    ("AUGHOR_PACK_BINDINGS_DB", "pack_bindings.db"),
    ("AUGHOR_GOVERN_TAGS_DB", "govern_tags.db"),
    ("AUGHOR_GOVERN_CAPS_DB", "govern_caps.db"),
    ("AUGHOR_QUALITY_DB", "quality.db"),
    ("AUGHOR_CHECKPOINTS_DB", "checkpoints.db"),
    ("AUGHOR_IDEMPOTENCY_DB", "idempotency.db"),
    ("AUGHOR_RBAC_DB", "rbac.db"),
    ("AUGHOR_AGENTS_DB", "agents.db"),
    ("AUGHOR_OVERVIEW_DRILLS_DB", "overview_drills.db"),
    # WP-4 — matcache had NO env override and was hardcoded to data/mat_cache.duckdb, so
    # any test touching the result cache wrote the developer's live file (a non-hermetic
    # hole; the same class that once emptied the live registry).
    ("AUGHOR_MATCACHE_DB", "mat_cache.duckdb"),
    # DuckDB demo stores — without these the suite CREATED data/aughor.duckdb and
    # opened data/samples.duckdb read-write in the developer's live data/ (lock
    # contention with a running app; same class as the registry incident).
    ("AUGHOR_FIXTURE_DB", "aughor.duckdb"),
    ("AUGHOR_SAMPLES_DB", "samples.duckdb"),
    # R14 — the query-popularity counter store (born hermetic like the R11 tree).
    ("AUGHOR_POPULARITY_DB", "popularity.db"),
    # Briefing-cockpit — user-authored dashboard cards (born hermetic).
    ("AUGHOR_DASHBOARD_DB", "dashboard_cards.db"),
    # Wave A1 — automations + their run history (born hermetic).
    ("AUGHOR_AUTOMATIONS_DB", "automations.db"),
    # Wave A4 — the resolve-once proposal inbox + target-bound standing grants (born hermetic).
    ("AUGHOR_KINETIC_INBOX_DB", "kinetic_inbox.db"),
    # R8 — the compiled ontology doc tree (a FILE store, not SQLite). Hardcoded to
    # data/ontology_docs/ until flag strategy batch C flipped `ontology.autodoc`
    # default-ON and the suite started writing real doc trees for the fixture
    # connection — the matcache hole, rediscovered. Same fix: point it at the tmp dir.
    ("AUGHOR_ONTOLOGY_DOCS_DIR", "ontology_docs"),
    ("AUGHOR_KINETIC_GRANTS_DB", "kinetic_grants.db"),
    # Wave E/L — the eval plane's own store: suites, cases, RUN HISTORY and graduation
    # receipts. It honoured AUGHOR_EVALS_DB from the start but was never listed here, so any
    # test that created a suite wrote data/evals.db. Found when L4's first unit test to call
    # `ensure_suite()` left a real suite in the live store. This one is worse than a nuisance:
    # `/evals/flags/{flag}/graduate` derives a flag's BASELINE and its noise floor from this
    # store's run history, so test-written rows are not just clutter — they are potential
    # evidence in a graduation decision.
    ("AUGHOR_EVALS_DB", "evals.db"),
):
    os.environ.setdefault(_env, os.path.join(_test_stores_dir, _file))

# WP-4 — three stores write into a DIRECTORY (JSONL / JSON files), not a single file, and
# had no env override: episode collectors (data/episodes_*.jsonl), agent procedural memory
# (data/agent_runs.json, data/learned_actions.json), and the Action Hub (data/action_*.json).
# Point each dir at the throwaway temp dir so the suite never writes/deletes the live files.
#
# AUGHOR_STATE_DIR (2026-07-21) closes the family WP-4 missed — the per-connection GENERATED
# state: exploration_*.json, business_profile_*.json, briefing_cache.json, patterns_cache.json,
# explore_watermark.json, AND aughor/db/purge.py, which resolved its own Path("data") and so
# UNLINKED from the live dir even when the store it was purging had been redirected. A suite
# run destroyed a real exploration_workspace.json (89 findings; data/*.json is gitignored, so
# it was unrecoverable). One env for the whole family → a new store in it is isolated by
# construction. Authored files (glossary/kb/rules) keep their own vars and stay repo-readable.
for _dir_env in ("AUGHOR_EPISODES_DIR", "AUGHOR_MEMORY_DIR", "AUGHOR_ACTIONS_DIR",
                 "AUGHOR_STATE_DIR"):
    os.environ.setdefault(_dir_env, _test_stores_dir)

# R11 — the per-column config store is a YAML file tree (data/ontology_column_config/)
# written by the intelligence build when `ontology.column_config` is on; isolate it so
# the suite never mutates the live tree (born hermetic, unlike the older data/ stores).
os.environ.setdefault(
    "AUGHOR_COLUMN_CONFIG_ROOT", os.path.join(_test_stores_dir, "ontology_column_config")
)
# R8a — the documents registry (data/documents.json) is written by every index/delete;
# isolate it so suite-driven indexing can never mutate the live registry.
os.environ.setdefault(
    "AUGHOR_DOCUMENTS_REGISTRY", os.path.join(_test_stores_dir, "documents.json")
)

# Layer 0.2 — the runtime LLM config (data/llm_config.json) was the LAST store tests
# inherited from the developer's machine: it holds the operator's chosen backend AND
# secretvault-encrypted API keys, and aughor/api.py's import-time load_dotenv() brings
# in the AUGHOR_SECRET_KEY that decrypts them — so a test could resolve a real paid
# binding without a single key in its own env. Isolated like every other store; the
# file simply doesn't exist, so tests see the pure env→default precedence.
os.environ.setdefault(
    "AUGHOR_LLM_CONFIG_PATH", os.path.join(_test_stores_dir, "llm_config.json")
)

# The suite must not spend real LLM requests. `semantic.autoseed` defaults ON and `get_schema()`
# fires it, so ANY test that loads a schema would call a live model against the free 1,000/day
# budget. Measured before this line existed: `tests/integration/test_evals_experiments.py`
# (8 tests) logged 12 failed seed attempts, and a SUCCESSFUL seed logs nothing, so 12 was a floor.
# Default it OFF for the whole suite; a test that genuinely exercises the seeder opts back in with
# `monkeypatch.setattr("aughor.semantic.autoseed._ENABLED", True)`.
#
# ⚠️ `_ENABLED` is read at MODULE IMPORT, so `monkeypatch.setenv("AUGHOR_AUTOSEED", ...)` inside a
# test is a NO-OP — patch the attribute, not the env var. This `setdefault` must stay above any
# app import for the same reason.
#
# History worth keeping: flipping this default first EXPOSED two phase-8 explorer tests
# (test_explorer_grain_runtime.py, test_narration_inversion_runtime.py) that were never hermetic —
# their fake LLM fell through to the real provider, and their 120s `asyncio.wait_for` then raced
# network latency, failing intermittently under full-suite load. Autoseed's glossary enrichment
# had been masking it by helping the loop converge faster. Both were made hermetic (the fake now
# raises on any unmodelled call; profile inference is pinned to None) before this default flipped.
os.environ.setdefault("AUGHOR_AUTOSEED", "false")

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
    from aughor.demo.setup import ensure_fixture_db, ensure_samples_db
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


# ── exemplar flags for the flag machinery's own tests ────────────────────────────
# `kernel/flags.py`'s contract — default-on resolution, env precedence, override
# drift — has to be asserted against SOME registered flag. Borrowing a product flag
# makes those assertions a moving target: the flag endgame deletes every flag it
# touches, so each wave strands whichever exemplar it happens to hardwire.
# `test_feature_flags.py` has already re-pointed its default-OFF exemplar twice
# (ai_sql -> obs.prompt_capture -> semops.champion_validate), and Wave 2d removes
# `ask.clarify`, the default-ON exemplar. These fixtures register a flag that exists
# only for the duration of the requesting test, so the machinery's contract stops
# depending on any product flag's disposition.
#
# Registration is a monkeypatched dict insert because that is exactly how the real
# registry is read: `flag_enabled`, `list_flags` and `override_drift` all consult
# FLAG_ENV / FLAG_DEFAULT at call time. `UnknownFlagError` is deliberately loud, so
# an unregistered name would not silently no-op — it has to be registered for real.

SYNTHETIC_DEFAULT_ON = "_synthetic.default_on"
SYNTHETIC_DEFAULT_ON_VAR = "AUGHOR_SYNTHETIC_DEFAULT_ON"
SYNTHETIC_DEFAULT_OFF = "_synthetic.default_off"
SYNTHETIC_DEFAULT_OFF_VAR = "AUGHOR_SYNTHETIC_DEFAULT_OFF"


def _register_synthetic(monkeypatch, name: str, var: str, default: bool) -> str:
    from aughor.kernel import flags as _flags

    monkeypatch.setitem(_flags.FLAG_ENV, name, var)
    monkeypatch.setitem(_flags.FLAG_META, name,
                        {"label": f"Synthetic {'default-on' if default else 'default-off'} flag",
                         "description": "Test-only flag registered by a fixture."})
    if default:
        monkeypatch.setitem(_flags.FLAG_DEFAULT, name, True)
    monkeypatch.delenv(var, raising=False)
    return name


@pytest.fixture
def synthetic_default_on(monkeypatch):
    """A registered DEFAULT-ON flag that exists only inside the requesting test.

    Its disposition resolves to `default_on` for free — `flag_disposition` derives
    that from FLAG_DEFAULT membership rather than a separate table.
    """
    from aughor.kernel import flags as _flags

    name = _register_synthetic(monkeypatch, SYNTHETIC_DEFAULT_ON,
                               SYNTHETIC_DEFAULT_ON_VAR, default=True)
    yield name
    # Safe against the real store: conftest points AUGHOR_SYSTEM_DB at a tempdir.
    _flags.clear_flag(name)


@pytest.fixture
def synthetic_default_off(monkeypatch):
    """A registered DEFAULT-OFF flag that exists only inside the requesting test."""
    from aughor.kernel import flags as _flags

    name = _register_synthetic(monkeypatch, SYNTHETIC_DEFAULT_OFF,
                               SYNTHETIC_DEFAULT_OFF_VAR, default=False)
    yield name
    _flags.clear_flag(name)


@pytest.fixture(autouse=True)
def _reset_provider_process_caches():
    """Clear the LLM provider's process-global caches between tests.

    Both exist to survive a whole server lifetime on purpose — the health-check verdict
    cache (so a connection test stops re-probing every bound model, 19% of one day's
    request budget) and the quota cooldown (so an exhausted backend is skipped rather
    than re-probed per call). Process-global is right in production and poison in a test
    session: one file's cached verdict was served to another file's assertion, which
    passed alone and failed in the suite. Cleared here rather than per-file because the
    leak crosses file boundaries.

    The RUNTIME-CONFIG cache (`_runtime`) is reset the same way, for the same reason:
    it is filled lazily by whichever `_cfg()` call happens first, so a test that
    patches `_read_config`/`_CONFIG_PATH` (test_free_by_default_binding's in-memory
    store, the config gate) can leave `backend: openrouter` cached for the REST of
    the suite. Before the config-path isolation that leak was invisible locally —
    every binding test silently resolved the developer's real openrouter config and
    key — and visible only as ordering luck on CI. Resetting per test makes every
    test start from the isolated (empty) config unless it builds its own.
    """
    from aughor.llm import coordination as _c
    from aughor.llm import provider as _p
    _cfg_path = os.environ.get("AUGHOR_LLM_CONFIG_PATH")

    def _reset():
        _p._ping_cache.clear()
        if _cfg_path and os.path.exists(_cfg_path):
            os.unlink(_cfg_path)   # a write_config-persisting test must not leak forward
        _p._runtime = None         # re-read (isolated ⇒ empty) on next _cfg()
        _p._config_version += 1    # drop providers built against another test's config
        # The cooldown now lives in the coordinator (aughor/llm/coordination.py); dropping
        # the instance re-resolves a clean one from env, which clears pacing and
        # concurrency too.
        _c.set_default(None)

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _no_provider_credentials(request):
    """Layer 0.2 — the mechanical no-key guarantee: a test structurally cannot reach a
    paid backend.

    Two moves, both enforcement rather than discipline:

    * every provider credential env var is DELETED, driven off ``provider._KEY_ENV``
      itself so a newly registered backend is scrubbed by construction (the list can
      never lag the registry). This matters because ``aughor/api.py`` loads the
      developer's real ``.env`` at import time — the suite process otherwise holds
      real keys (the "together had a key" incident: a free primary's fallback chain
      quietly reached a PAID backend that only looked configured because of .env).
    * the fallback chain is pinned EMPTY via ``AUGHOR_FALLBACK_BACKENDS=none`` (the
      explicit empty-chain spelling; ``""`` has always meant "default order"). The
      chain tests in test_provider_resilience set this variable themselves, and their
      own monkeypatch simply replaces the pin — no special-casing needed.

    Skipped for @e2e / @eval tests, which spend live requests on purpose. There is
    deliberately no per-test assertion here: real keys can only arrive via env or the
    (now isolated) runtime config, both closed above — tests/unit/test_no_key_guarantee.py
    carries the proof.

    A PRIVATE MonkeyPatch instance, not the shared ``monkeypatch`` fixture: an autouse
    conftest fixture that requests the shared instance drags its instantiation ahead
    of every module-local autouse fixture, which INVERTS teardown order — a module
    fixture's teardown then runs while the test's own patches are still applied
    (test_parallel_safety's hostile-contextvar teardown caught exactly that).
    """
    from aughor.llm import provider as _p
    mp = pytest.MonkeyPatch()
    try:
        if request.node.get_closest_marker("e2e") or request.node.get_closest_marker("eval"):
            # Live-spending tests keep the operator's REAL binding: undo the suite-wide
            # runtime-config isolation (AUGHOR_LLM_CONFIG_PATH above) for this test only,
            # or `pytest -m eval` / --run-e2e would resolve the ollama default instead of
            # the configured backend and meter zero tokens (test_ratchet_live_smoke
            # caught exactly that when the isolation first landed).
            from pathlib import Path as _Path
            _real = _Path(_p.__file__).resolve().parent.parent.parent / "data" / "llm_config.json"
            mp.setattr(_p, "_CONFIG_PATH", _real)
            mp.setattr(_p, "_runtime", None)   # lazy-reload from the real path
            mp.setattr(_p, "_config_version", _p._config_version + 1)
        else:
            for _var in _p._KEY_ENV.values():
                mp.delenv(_var, raising=False)
            # The BINDING env vars go too, not just credentials: aughor.api's
            # import-time load_dotenv() plants the developer's .env (AUGHOR_BACKEND=
            # openrouter + model pins) into the process env the moment any test
            # touches the app — after which every later test resolves a keyless
            # openrouter binding and dies in the client constructor. Scrubbed per
            # test, so every test starts from the ollama default unless it pins a
            # backend itself (the faux_llm fixture does).
            for _var in ("AUGHOR_BACKEND", "AUGHOR_MODEL", "AUGHOR_CODER_MODEL",
                         "AUGHOR_NARRATOR_MODEL", "AUGHOR_FAST_NARRATOR_MODEL"):
                mp.delenv(_var, raising=False)
            mp.setenv("AUGHOR_FALLBACK_BACKENDS", "none")
        yield
    finally:
        mp.undo()


@pytest.fixture
def faux_llm(monkeypatch):
    """Route every LLM completion in this test through the scripted faux backend.

    Returns the ``aughor.llm.faux`` module: ``set_responses([...])`` to script,
    ``calls()`` to see the exact prompts the code built, ``pending()`` to prove the
    script was fully consumed. An unscripted call raises ``FauxResponsesExhausted``
    loudly and never falls through to a real provider (``never_failover``).

    Isolation is inherited, not re-built: `_reset_provider_process_caches` nulls the
    runtime-config cache and bumps `_config_version` around EVERY test (so the
    provider cache can't serve a faux-bound provider to a later test), and
    `_no_provider_credentials` scrubs the developer's .env binding vars — this
    fixture only pins the backend and manages the script. `_config_version` is
    deliberately never monkeypatched: a restore moves the version BACKWARDS, and a
    later real `load_config()` bump can then collide with the stale `_cache_version`
    and revive a dead provider cache.
    """
    from aughor.llm import faux as _faux
    from aughor.llm import provider as _p
    monkeypatch.setenv("AUGHOR_BACKEND", _p.FAUX_BACKEND)
    _faux.reset()
    yield _faux
    _faux.reset()
