"""Per-schema store wiring — readers must see what per-schema writers wrote.

Multi-schema connections run the explorer per schema (store key {conn}__{schema},
episode file episodes_{conn}__{schema}.jsonl). A family of readers used the bare
connection key and silently saw nothing: the Activity episode feed, the ADA
planner's exploration annotations, the ontology's lifecycle/join merge, and the
monitor digest (which additionally imported a function that never existed)."""
from __future__ import annotations

import json

import pytest

import aughor.explorer.store as store


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    """Redirect the explorer store per test.

    Was a bare `store._DATA_DIR = tmp_path` inside `_seed` — a module-global assignment with
    NO teardown, so it leaked one test's tmp_path into every later test in the session.
    monkeypatch restores it; the assignment never did."""
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)


def _seed(tmp_path, key, **state_bits):
    state = store._empty()
    state.update(state_bits)
    store.save(key, state)


# ── load_aggregate merges bare CONTENT without letting it poison the phase ────

def test_aggregate_includes_bare_content_but_not_bare_phase(tmp_path):
    _seed(tmp_path, "c1", insights=[{"id": "fix1", "finding": "a fix-saved finding"}])
    _seed(tmp_path, "c1__sales", phase="complete",
          insights=[{"id": "s1", "finding": "per-schema finding"}])

    agg = store.load_aggregate("c1")
    assert {i["id"] for i in agg["insights"]} == {"fix1", "s1"}
    # an empty/pending bare state must not report the exploration as pending
    assert agg["phase"] == "complete"


# ── exploration annotations aggregate across per-schema runs ─────────────────

def test_annotations_come_from_per_schema_runs(tmp_path):
    _seed(tmp_path, "c1")  # bare state: empty, phase pending
    _seed(tmp_path, "c1__sales", phase="complete", null_meanings={
        "orders:cancelled_at": {"meaning": "still_active", "null_rate": 0.8},
    })
    block = store.render_exploration_annotations("c1")
    assert "NULL SEMANTICS" in block, (
        "annotations empty — the ADA planner and ontology overlay lose all "
        "explorer intelligence on multi-schema connections"
    )


# ── the episodes endpoint merges bare + per-schema files ──────────────────────

def test_episodes_endpoint_merges_per_schema_files(tmp_path, monkeypatch):
    import aughor.routers.exploration as expl_router

    (tmp_path / "data").mkdir()
    # WP-4 — the endpoint now reads episodes_dir() (honours AUGHOR_EPISODES_DIR), not a
    # CWD-relative Path("data"). Point the resolved dir at this test's fixture files.
    monkeypatch.setattr("aughor.explorer.episodes._DATA_DIR", tmp_path / "data")
    (tmp_path / "data" / "episodes_c1.jsonl").write_text(
        json.dumps({"connection_id": "c1", "phase": "exploration", "ts": 1, "sql": "q1"}) + "\n")
    (tmp_path / "data" / "episodes_c1__sales.jsonl").write_text(
        json.dumps({"connection_id": "c1__sales", "phase": "exploration", "ts": 2, "sql": "q2"}) + "\n")
    (tmp_path / "data" / "episodes_other.jsonl").write_text(
        json.dumps({"connection_id": "other", "phase": "exploration", "ts": 3, "sql": "leak"}) + "\n")

    out = expl_router.get_exploration_episodes("c1")
    assert [e["sql"] for e in out] == ["q1", "q2"]  # merged, ts-ordered, no leak


# ── the digest's exploration section reads the real store ─────────────────────

def test_digest_exploration_section_reads_real_insights(tmp_path):
    _seed(tmp_path, "c1__sales", phase="complete", insights=[
        {"id": "s1", "finding": "APAC SMB revenue dropped 38.8% on the outage day. More prose."},
        {"id": "s2", "finding": "quarantined", "invalid": True},
    ])
    from aughor.monitors.alert_summary import build_alert_summary

    sections = build_alert_summary("c1").sections
    expl = next((s for s in sections if s.title == "Exploration Insights"), None)
    assert expl is not None, "exploration section still dead"
    assert expl.items == ["APAC SMB revenue dropped 38.8% on the outage day."]
    assert all("quarantined" not in i for i in expl.items)


# ── a failure must not be reportable as health ────────────────────────────────
#
# `_agg_phase` treated FAILED as terminal and collapsed every terminal phase to
# COMPLETE — answering "has it stopped running?" when the caller asked "did it
# work?". Combined with a hardcoded `error: None` in the status route, a
# connection whose schemas had all failed reported: phase complete, error null,
# and the failures visible only in `per_schema`, which nothing surfaced.

def test_all_schemas_failed_is_not_reported_as_complete(tmp_path):
    _seed(tmp_path, "c1__sales", phase="failed")
    _seed(tmp_path, "c1__ops", phase="failed")

    agg = store.load_aggregate("c1")

    assert agg["phase"] == "failed", (
        f"every schema failed and the connection reported {agg['phase']!r}")


def test_a_run_where_some_schemas_succeeded_still_completes(tmp_path):
    """Not everything terminal is a failure — those schemas really did finish, and
    their findings are real. Turning a partial success into FAILED would trade one
    lie for another."""
    _seed(tmp_path, "c1__sales", phase="complete")
    _seed(tmp_path, "c1__ops", phase="failed")

    assert store.load_aggregate("c1")["phase"] == "complete"


def test_a_still_running_schema_keeps_reporting_its_live_phase(tmp_path):
    _seed(tmp_path, "c1__sales", phase="complete")
    _seed(tmp_path, "c1__ops", phase="distribution")

    assert store.load_aggregate("c1")["phase"] == "distribution"


def test_the_status_route_names_the_schemas_that_failed(tmp_path):
    """A phase is one word and cannot say WHICH schemas fell over, so a partly
    failed run needs the error field to say it — the field that was hardcoded None."""
    from aughor.routers.exploration import get_exploration_status

    _seed(tmp_path, "c1__sales", phase="complete")
    _seed(tmp_path, "c1__ops", phase="failed")
    _seed(tmp_path, "c1__hr", phase="failed")

    status = get_exploration_status("c1")

    assert status["phase"] == "complete"
    assert status["error"], "a run with two failed schemas reported no error"
    assert "2 of 3" in status["error"]
    assert "ops" in status["error"] and "hr" in status["error"]


def test_a_clean_run_still_reports_no_error(tmp_path):
    """The guard must not invent failures — a healthy run stays healthy."""
    from aughor.routers.exploration import get_exploration_status

    _seed(tmp_path, "c1__sales", phase="complete")
    _seed(tmp_path, "c1__ops", phase="complete")

    status = get_exploration_status("c1")

    assert status["phase"] == "complete"
    assert status["error"] is None
