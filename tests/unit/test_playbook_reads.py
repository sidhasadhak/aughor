"""What the agents get from the playbook.

Measured 2026-09-14 before these fixes: the seeder turned none of the KB's 486 inflation and deflation causes into
plays, questions drew plays from other industries (21 of 96 across 24 questions), definitional answers never
carried a play, and the synthesis block called every play proven while none had an outcome.
"""
from __future__ import annotations

import pytest

import aughor.business_profile.metric_kb as metric_kb
import aughor.playbook.store as store
from aughor.business_profile.metric_kb import kb_entry_industry, load_industry_kbs
from aughor.playbook import builder, retriever
from aughor.playbook.models import DATA_QUALITY_TAG, PlaybookEntry


def _kb_with_causes() -> list[dict]:
    return [e for e in builder._load_all_kb() if builder._has_causal_data(e)]


# ── the seed ─────────────────────────────────────────────────────────────────────────────────────────

def test_every_inflation_and_deflation_cause_becomes_a_play():
    entry = {"id": "t_metric", "title": "T",
             "inflation_causes": [{"cause": "test orders"}, "duplicate rows"],
             "deflation_causes": [{"cause": "late refunds", "fix": "count at refund date"}]}
    plays = builder._build_entries_for_kb(entry)
    assert sorted(p.recommendation for p in plays) == [
        "Check if duplicate rows is artificially inflating T.",
        "Check if late refunds is suppressing T.",
        "Check if test orders is artificially inflating T.",
    ]
    assert all(DATA_QUALITY_TAG in p.tags for p in plays)


def test_the_seed_holds_every_relationship_and_cause_in_the_kb():
    kb = _kb_with_causes()
    held = sum(len(e.get("causal_relationships") or []) + len(e.get("inflation_causes") or [])
               + len(e.get("deflation_causes") or []) for e in kb)
    assert len([p for e in kb for p in builder._build_entries_for_kb(e)]) == held


def test_seeding_writes_the_whole_seed_once(monkeypatch):
    batches: list[int] = []
    monkeypatch.setattr(builder, "count_entries", lambda: 0)
    monkeypatch.setattr(builder, "save_entries", lambda plays: batches.append(len(plays)))
    seeded = builder.seed_from_kb()
    assert batches == [seeded]


def test_save_entries_versions_plays_like_save_entry(tmp_path):
    path = tmp_path / "playbook.json"

    def play(pid: str, recommendation: str) -> PlaybookEntry:
        return PlaybookEntry(id=pid, trigger_metric="m", trigger_condition="c", recommendation=recommendation)

    store.save_entries([play(f"p{i}", f"r{i}") for i in range(3)], path)
    assert [e.version for e in store.list_entries(path)] == [1, 1, 1]
    store.save_entries([play("p1", "r1")], path)          # the same content: no new version
    assert len(store.list_versions("p1", path)) == 1
    store.save_entries([play("p1", "changed")], path)
    assert [v["version"] for v in store.list_versions("p1", path)] == [1, 2]
    assert [e.id for e in store.list_entries(path)] == ["p0", "p1", "p2"]


# ── scoped reads ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def kb_plays(monkeypatch):
    """The KB's whole seed, active, served to the retriever without a store."""
    plays = [p.model_copy(update={"status": "active"})
             for e in _kb_with_causes() for p in builder._build_entries_for_kb(e)]
    monkeypatch.setattr(retriever, "list_active_entries", lambda: plays)
    return plays


def test_a_scoped_read_never_returns_another_industrys_play(kb_plays):
    """Each industry is queried with its own metric names and one from every other industry. The queries
    come from the KB, not from a list written beside the expectation."""
    kbs = load_industry_kbs()
    others = [kb["metrics"][0]["name"] for kb in kbs if kb.get("metrics")]
    for kb in kbs:
        for label in [m["name"] for m in kb.get("metrics", [])] + others:
            for play in retriever.retrieve_for_metric_and_phases([label], industry=kb["id"]):
                assert kb_entry_industry(play.source_kb_id) in ("", kb["id"]), (kb["id"], label, play.id)


def test_an_unscoped_read_still_crosses_industries(kb_plays):
    """The witness that the scoped assertion can fail: without a scope, SaaS churn draws another industry's plays."""
    plays = retriever.retrieve_for_metric_and_phases(["why is churn up this quarter"], limit=4)
    assert any(kb_entry_industry(p.source_kb_id) not in ("", "saas") for p in plays)


def test_an_uncurated_industry_reads_only_the_shared_plays(kb_plays):
    plays = retriever.retrieve_for_metric_and_phases(["revenue retention churn conversion"], limit=20, industry="")
    assert plays and all(kb_entry_industry(p.source_kb_id) == "" for p in plays)


def test_data_quality_plays_stay_out_of_recommendations_unless_asked(kb_plays):
    question = ["gross merchandise value inflated by cancelled orders"]
    assert not any(map(retriever.is_data_quality, retriever.retrieve_for_metric_and_phases(question, limit=10)))
    assert any(map(retriever.is_data_quality,
                   retriever.retrieve_for_metric_and_phases(question, limit=10, include_data_quality=True)))


# ── what the prompt and the answer say ───────────────────────────────────────────────────────────────

def _play(rate: float = 0.0) -> PlaybookEntry:
    return PlaybookEntry(id="x", trigger_metric="m", trigger_condition="c",
                         recommendation="Do the thing.", historical_success_rate=rate)


def test_the_block_says_proven_only_when_a_play_has_an_outcome(monkeypatch):
    monkeypatch.setattr(store, "emit_playbook_use", lambda *a, **k: None)
    unproven = retriever.build_playbook_prompt_section([_play()])
    assert "proven interventions" not in unproven and "none has a logged outcome yet" in unproven
    assert "proven interventions" in retriever.build_playbook_prompt_section([_play(0.6), _play()])


def test_a_definitional_answer_carries_the_industrys_play(monkeypatch):
    import aughor.semantic.connection_kb as connection_kb
    import aughor.semantic.kb_retriever as kb_retriever
    from aughor.agent.nodes import answer_text_only

    monkeypatch.setattr(kb_retriever, "retrieve_for_planning", lambda q, top_k=3: "")
    monkeypatch.setattr(connection_kb, "retrieve_for_question", lambda q, conn: "")
    monkeypatch.setattr(metric_kb, "industry_scope", lambda conn, schema=None, **k: "airline")
    asked: dict = {}

    def _retrieve(labels, limit=6, **kwargs):
        asked.update(kwargs)
        return [PlaybookEntry(id="p", trigger_metric="air_load_factor", trigger_condition="c",
                              recommendation="Check capacity before blaming demand.")]

    monkeypatch.setattr(retriever, "retrieve_for_metric_and_phases", _retrieve)
    out = answer_text_only({"question": "what is load factor", "connection_id": "c1"})
    assert "Check capacity before blaming demand." in out["final_text_answer"]
    assert asked["industry"] == "airline"
