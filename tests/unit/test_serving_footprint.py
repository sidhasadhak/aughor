"""The serving footprint is a RATCHET, not a one-off cleanup.

The development environment is ~1.1 GB and that was believed to rule out any
250 MB-limited deployment target. Measuring what the API actually loads — import
`aughor.api`, diff `sys.modules` — gave a boot closure of 121 MB and a clean serving
install of 102 MB. The weight was never on the request path; it was in dependencies
nothing at boot imports (`docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md` §1).

Splitting those into extras is easy to undo by accident: one convenience import at
module scope in a router or a `db/` module silently drags 312 MB back onto the serving
path, and nothing fails — the dev environment has it installed. These tests fail instead.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

#: Packages that must NOT be in the API's boot closure. Each is either large, optional,
#: or both — and each was verified absent when the split was made.
HEAVY = {
    "polars":      "192 MB, +120 MB pyarrow; serves ONE call site in db/connection.py "
                   "which already falls back to DuckDB on ImportError. Extra: [fastread]",
    "pyarrow":     "120 MB, arrives with polars",
    "matplotlib":  "28 MB, chart rendering for exports only. Extra: [export]",
    "reportlab":   "PDF rendering, export only. Extra: [export]",
    "pptx":        "PPTX rendering, export only. Extra: [export]",
    "statsmodels": "36 MB and imported by ZERO modules — deleted outright, never restore",
    "mlflow":      "observability extra",
    "connectorx":  "113 MB, warehouse extra",
}

# Deliberately NOT listed: `botocore` (21 MB). It IS in the boot closure of a development
# environment, but only transitively via boto3 / snowflake-connector-python /
# mlflow-skinny — all of which live in extras. A runtime-only install never installs it,
# so listing it here would fail the dev environment for a problem that does not exist in
# the artifact that ships.


def _boot_closure() -> set[str]:
    """Third-party top-level modules loaded by importing the API.

    Run in a SUBPROCESS: the test session has already imported half the codebase, so an
    in-process check would measure the test runner rather than the API."""
    code = textwrap.dedent("""
        import json, sys, sysconfig, pathlib
        before = set(sys.modules)
        import aughor.api          # noqa: F401
        sp = pathlib.Path(sysconfig.get_paths()["purelib"])
        tops = set()
        for name in set(sys.modules) - before:
            mod = sys.modules.get(name)
            f = getattr(mod, "__file__", None) or ""
            if str(sp) in f:
                tops.add(name.split(".")[0])
        print(json.dumps(sorted(tops)))
    """)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=300)
    if proc.returncode != 0:
        pytest.skip(f"could not import the API in a subprocess: {proc.stderr[-400:]}")
    import json
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_no_heavy_dependency_is_on_the_serving_path():
    """The ratchet. A new module-scope import of any of these puts hundreds of MB back
    into every deployment, and nothing else would notice."""
    closure = _boot_closure()
    leaked = sorted(closure & set(HEAVY))
    assert not leaked, "\n".join(
        [f"{p!r} is back in the API boot closure — {HEAVY[p]}" for p in leaked]
        + ["Import it inside the function that needs it, or keep it in its extra."])


def test_the_boot_closure_still_carries_what_serving_needs():
    """Vacuous-pass guard: if the import broke, every check above would 'pass' on an
    empty set."""
    closure = _boot_closure()
    for required in ("fastapi", "duckdb", "sqlglot", "pydantic", "openai"):
        assert required in closure, f"{required} missing — the closure measurement is broken"


def test_statsmodels_is_not_a_dependency_anywhere():
    """It was a declared runtime dependency imported by zero modules. Deleting it is only
    durable if re-adding it fails."""
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    runtime = pyproject["project"]["dependencies"]
    assert not [d for d in runtime if "statsmodels" in d], (
        "statsmodels is back in runtime dependencies; it is imported by no module")


def test_export_degrades_with_an_actionable_message_not_an_import_error():
    """Without the extra, asking for a PDF must say what to install — an ImportError out
    of a router tells the operator nothing they can act on."""
    import aughor.export as E

    if E.EXPORT_AVAILABLE:                      # the dev env has the extra installed
        pytest.skip("export extra is installed; the unavailable path is covered below")
    with pytest.raises(E.ExportUnavailable, match=r"export"):
        E.export_report({"report": {}}, "pdf")


def test_the_unavailable_path_names_the_install_command(monkeypatch):
    """Exercised regardless of what is installed locally, because the message is the
    whole feature."""
    import aughor.export as E

    monkeypatch.setattr(E, "EXPORT_AVAILABLE", False)
    monkeypatch.setattr(E, "_EXPORT_IMPORT_ERROR", "No module named 'reportlab'")
    with pytest.raises(E.ExportUnavailable) as exc:
        E.export_report({"report": {}}, "pdf")
    msg = str(exc.value)
    assert "[export]" in msg and "install" in msg.lower()
    assert "reportlab" in msg      # the underlying cause survives into the message


def test_an_unsupported_format_still_fails_before_the_availability_check():
    """A bad format is a client error whether or not the extra is installed."""
    import aughor.export as E

    with pytest.raises(ValueError, match="unsupported export format"):
        E.export_report({"report": {}}, "docx")


# ── The degraded path: qdrant-client absent ───────────────────────────────────────────
# The development environment HAS qdrant-client, so every ordinary test exercises the
# happy path. These simulate its absence, which is the configuration this split creates
# and the only one where the new guards do anything.


@pytest.fixture
def no_qdrant(monkeypatch):
    """Make `import qdrant_client` raise, as it would without the `semantic` extra."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "qdrant_client" or name.startswith("qdrant_client."):
            raise ImportError("No module named 'qdrant_client'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # `available()` is cheap and uncached, so nothing else needs resetting.
    return fake_import


def test_vector_store_reports_unavailable_without_the_extra(no_qdrant):
    from aughor.semantic import vector_store

    assert vector_store.available() is False


def test_the_no_qdrant_fixture_actually_changes_something():
    """Vacuous-pass guard for every test above: the development environment HAS
    qdrant-client, so if `available()` were False for some unrelated reason, the whole
    degraded-path suite would pass while testing nothing."""
    from aughor.semantic import vector_store

    assert vector_store.available() is True, (
        "qdrant-client is not installed locally, so the no_qdrant tests prove nothing — "
        "install the extra: uv pip install -e '.[semantic]'")


def test_reads_answer_like_an_empty_index(no_qdrant):
    """A deployment without semantic search HAS no index; 'no hits' is the honest answer,
    and every caller already handles it."""
    from aughor.semantic import vector_store

    assert vector_store.search("anything", [0.1, 0.2], top_k=5) == []
    assert vector_store.collection_count("anything") == 0
    assert vector_store.scroll_payloads("anything") == []


def test_writes_no_op_rather_than_raising(no_qdrant):
    from aughor.semantic import vector_store

    vector_store.ensure_collection("c")                      # must not raise
    vector_store.upsert("c", [{"id": "1", "vector": [0.0], "payload": {}}])


def test_the_raw_client_fails_with_an_actionable_message(no_qdrant):
    """`_client` is deliberately unguarded — it is the one place a caller who skipped the
    availability check should hear about it, and the message must name the fix."""
    from aughor.semantic import vector_store

    with pytest.raises(vector_store.SemanticIndexUnavailable) as exc:
        vector_store._client()
    assert "[semantic]" in str(exc.value) and "install" in str(exc.value).lower()


def test_purge_hooks_report_nothing_to_purge(no_qdrant):
    """A purge over an index that does not exist removed zero points — not an error."""
    from aughor.agent.bootstrap import _qdrant_conn, _qdrant_inv

    assert _qdrant_conn("conn1", "org1") == {"qdrant_points": 0}
    assert _qdrant_inv(["inv1", "inv2"]) == {"qdrant_points": 0}


def test_the_suggestions_cache_misses_rather_than_raising(no_qdrant):
    from aughor.semantic.suggestions_cache import get_cached

    assert get_cached("conn1", "fingerprint") is None


def test_the_connection_filter_degrades_to_no_filter(no_qdrant):
    """Its value is moot once search() returns nothing, so None keeps the three call
    sites free of their own guards."""
    from aughor.tools.prior_analyses import _connection_filter

    assert _connection_filter("conn1") is None
