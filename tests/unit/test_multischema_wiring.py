"""Per-schema store wiring — readers must see what per-schema writers wrote.

Multi-schema connections run the explorer per schema (store key {conn}__{schema},
episode file episodes_{conn}__{schema}.jsonl). A family of readers used the bare
connection key and silently saw nothing: the Activity episode feed, the ADA
planner's exploration annotations, the ontology's lifecycle/join merge, and the
monitor digest (which additionally imported a function that never existed)."""
from __future__ import annotations

import json

import aughor.explorer.store as store


def _seed(tmp_path, key, **state_bits):
    store._DATA_DIR = tmp_path
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
    from aughor.monitors.digest import build_digest

    sections = build_digest("c1").sections
    expl = next((s for s in sections if s.title == "Exploration Insights"), None)
    assert expl is not None, "exploration section still dead"
    assert expl.items == ["APAC SMB revenue dropped 38.8% on the outage day."]
    assert all("quarantined" not in i for i in expl.items)
