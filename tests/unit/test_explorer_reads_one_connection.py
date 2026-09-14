"""The explorer does not look beyond the connection it explores — the user's rule (2026-09-14), and two of the calls
that came with it: a federated connection, which attaches other connections by construction, is not explored, and
whoever starts an exploration on one is told why; and the playbook entries the explorer reads are ranked by relevance
alone, never by a success rate learned from outcomes on every connection."""
from __future__ import annotations

import asyncio

import pytest

from aughor.db import registry
from aughor.playbook import retriever as PB
from aughor.playbook.models import PlaybookEntry


@pytest.fixture
def federated(tmp_path):
    member = registry.add_connection("one-member", "duckdb", str(tmp_path / "member.duckdb"))
    fed = registry.add_connection("two-in-one", "federated", "federated://", meta={"connection_ids": [member]})
    return fed, member


def test_a_federated_connection_is_not_explored_and_says_why(federated):
    from aughor.routers._shared import explorer_refusal, kickoff_exploration, spawn_explorer
    fed, member = federated
    why = explorer_refusal(fed)
    assert "federated" in why and explorer_refusal(member) == ""
    assert asyncio.run(spawn_explorer(fed)) == {"ok": False, "reason": why, "job_id": None}
    assert kickoff_exploration(fed) is False            # an explicit start, which Scout's governance never skips


def test_the_start_and_restart_doors_refuse_a_federated_connection_before_anything_is_wiped(client, federated,
                                                                                            monkeypatch):
    import aughor.routers.exploration as EX
    fed, _ = federated
    wiped = []
    monkeypatch.setattr(EX, "_purge_exploration_state", lambda conn_id: wiped.append(conn_id) or [])
    started = client.post(f"/exploration/{fed}/start")
    assert started.status_code == 200, started.text
    assert started.json()["ok"] is False and "federated" in started.json()["reason"]
    restarted = client.post(f"/exploration/{fed}/restart")
    assert restarted.status_code == 200, restarted.text
    assert restarted.json() == started.json() and wiped == []     # refused as start refuses, before anything is wiped


def test_a_canvas_on_a_federated_connection_is_refused_before_its_state_is_wiped(client, federated, monkeypatch):
    import aughor.routers.exploration as EX
    from aughor.canvas.models import CanvasScope
    from aughor.canvas.store import create_canvas
    fed, _ = federated
    canvas = create_canvas("two in one", [CanvasScope(connection_id=fed)])
    episodes = EX.episodes_dir() / f"episodes_canvas_{canvas.id}.jsonl"
    episodes.parent.mkdir(parents=True, exist_ok=True)
    episodes.write_text('{"phase": "profile"}\n')
    emptied = []
    monkeypatch.setattr("aughor.explorer.store.save_canvas", lambda canvas_id, state: emptied.append(canvas_id))
    for door in ("restart", "resume"):
        answer = client.post(f"/exploration/canvas/{canvas.id}/{door}")
        assert answer.status_code == 200, (door, answer.text)
        assert answer.json()["ok"] is False and "federated" in answer.json()["reason"], door
    assert episodes.exists() and emptied == []


def _entry(entry_id: str, metric: str, *, tags: tuple = (), recommendation: str = "", rate: float = 0.0):
    return PlaybookEntry(id=entry_id, trigger_metric=metric, trigger_condition=f"{metric} moved",
                         recommendation=recommendation, tags=list(tags), historical_success_rate=rate)


def test_the_explorer_ranks_playbook_entries_by_relevance_alone(monkeypatch):
    relevant = _entry("relevant", "refund", recommendation="check the refund rate by channel")
    proven = _entry("proven", "churn", tags=("refund", "rate"), rate=1.0)
    monkeypatch.setattr(PB, "list_active_entries", lambda: [relevant, proven])
    assert [e.id for e in PB.retrieve_for_metric_and_phases(["refund rate"], limit=2)] == ["proven", "relevant"]
    assert [e.id for e in PB.retrieve_for_metric_and_phases(["refund rate"], limit=2, learned_rates=False)] == [
        "relevant", "proven"]
