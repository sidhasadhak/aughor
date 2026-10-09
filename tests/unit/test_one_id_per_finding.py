"""One id, one finding (`explorer.store`).

The cockpit's ledger picker threw "two children with the same key, `pinned__0`" (2026-10-09). On theLook's live
state 35 ids named 62 findings: each pinned key question four times over — the read-back of an unchanged finding
appended a copy of what the list already held — and `synth__share__1` three DIFFERENT findings, numbered from zero
on each run, of which a card could only ever be made from the first. Read, the store now gives one id per finding;
written, a pinned question keeps its slot and every other finding is minted an id the list does not hold.
"""
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

import pytest

from aughor.explorer import store
from aughor.explorer.agent import SchemaExplorer


def _f(fid: str, words: str, at: str = "2026-10-08T06:00:00", domain: str = "Synthesis") -> dict:
    return {"id": fid, "domain": domain, "finding": words, "sql": f"SELECT '{words}'", "generated_at": at}


PINNED = _f("pinned__0", "Outerwear & Coats leads profit", "2026-09-27T14:47:38", "Key Questions")
LEGACY = [PINNED, copy.deepcopy(PINNED), copy.deepcopy(PINNED),
          _f("synth__share__1", "Outerwear & Coats is 3.5M of retail value", "2026-10-08T06:33"),
          _f("synth__share__1", "Accessories is 0.316 of retail value", "2026-10-08T09:27"),
          _f("synth__share__1", "Women's department share", "2026-10-08T23:15")]


def test_a_list_is_read_with_one_id_per_finding():
    read = store.one_id_each(LEGACY)
    assert [f["id"] for f in read] == ["pinned__0", "synth__share__1", "synth__share__1~2", "synth__share__1~3"]
    assert read[1]["finding"].startswith("Outerwear")                    # the earliest keeps the id cards resolved to
    assert store.one_id_each(read) == read                               # idempotent
    assert [f["id"] for f in LEGACY].count("synth__share__1") == 3       # the list itself is not changed


def test_a_renamed_finding_never_takes_an_id_already_held():
    found = [_f("x", "a"), _f("x", "b"), _f("x~2", "c")]
    assert [f["id"] for f in store.one_id_each(found)] == ["x", "x~3", "x~2"]
    assert store.fresh_finding_id({store.FINDINGS: found}, "y") == "y"
    assert store.fresh_finding_id({store.FINDINGS: found}, "x") == "x~3"


def test_a_pinned_question_keeps_its_slot():
    state = {store.FINDINGS: [_f("a", "a"), dict(PINNED)]}
    newer = {**PINNED, "finding": "Outerwear & Coats still leads profit", "generated_at": "2026-10-09"}
    store.keep_slot(state, newer)
    found = state[store.FINDINGS]
    assert [f["id"] for f in found] == ["a", "pinned__0"] and found[1]["finding"].startswith("Outerwear & Coats still")
    store.keep_slot(state, _f("pinned__1", "b"))
    assert [f["id"] for f in found] == ["a", "pinned__0", "pinned__1"]


@pytest.fixture
def explored(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    store.save("conn-ids", {**store._empty(), store.FINDINGS: copy.deepcopy(LEGACY)})   # the live shape, as written
    return "conn-ids"


def test_every_reader_reads_one_id_per_finding_and_a_pin_resolves_each(explored):
    assert [f["id"] for f in store.get_findings(explored)] == [
        "pinned__0", "synth__share__1", "synth__share__1~2", "synth__share__1~3"]
    from aughor.routers.exploration import domain_findings_for
    by_domain = domain_findings_for(explored, None)                      # what the briefing and the pin door read
    ids = [f["id"] for items in by_domain.values() for f in items]
    assert len(ids) == len(set(ids)) == 4
    second = next(i for items in by_domain.values() for i in items if i["id"] == "synth__share__1~2")
    assert second["finding"].startswith("Accessories")


def test_the_aggregate_of_two_schemas_runs_reads_one_id_per_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    store.save("multi__a", {**store._empty(), store.FINDINGS: [_f("synth__share__0", "a's share")]})
    store.save("multi__b", {**store._empty(), store.FINDINGS: [_f("synth__share__0", "b's share")]})
    agg = store.get_aggregate_domain_findings("multi")
    assert sorted(f["id"] for items in agg.values() for f in items) == ["synth__share__0", "synth__share__0~2"]
    assert sorted(f["id"] for f in store.load_aggregate("multi")[store.FINDINGS]) == ["synth__share__0",
                                                                                     "synth__share__0~2"]


def test_reading_back_an_unchanged_pinned_finding_keeps_one_copy(monkeypatch):
    # The live shape: the state already holds the pinned finding, and the run reads it back from the ledger.
    ex = SchemaExplorer.__new__(SchemaExplorer)
    ex.connection_id, ex._stopped, ex._activity_unchanged = "conn-ids", False, True
    ex._state = {store.FINDINGS: [dict(PINNED)]}
    ex._conn = SimpleNamespace(dialect="duckdb")

    async def _gate():
        return None

    ex._gate = _gate
    ex._read_prior_pinned = lambda qi: dict(PINNED) if qi == 0 else None
    ex._order_keys_projected = lambda sql: False
    ex._emit_insight = lambda *a, **k: None
    ex._save_state = lambda: None
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: None)
    profile = SimpleNamespace(key_questions=["Which category leads profit?"], key_question_sql=[])
    for _ in range(3):                                                   # three runs, the data unchanged
        asyncio.run(ex._phase8_pinned_questions(profile, SimpleNamespace(table_cols={}), ""))
    assert [f["id"] for f in ex._state[store.FINDINGS]] == ["pinned__0"]
