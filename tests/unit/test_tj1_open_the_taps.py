"""TJ-1 (§3.47) — open the taps that exist: the census's dead joins and blind spots.

Each test pins one defect the trajectory census found (docs/TRAJECTORY_CENSUS_2026-09-25.md
§10) at the seam that caused it: the receipt read a `.model` the provider never had (1); the
fallback model shipped a slashless literal the ratchet could not see (4); a registry row
whose bytes were gone read as an empty dataset (9); the catalogue prices had no caller so
every call priced at nothing (the unpriced 83 of 83).
"""
from __future__ import annotations

import pytest


def test_the_provider_exposes_the_model_the_receipt_stamps(monkeypatch):
    """Defect 1: `getattr(get_provider("coder"), "model", None)` was None on 1,276 of 1,277
    receipts because `LLMProvider` kept `_model` and no property."""
    from aughor.llm import provider as P
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "none")
    monkeypatch.setattr(P, "_active_model", lambda backend, role: "vendor/pinned-coder")
    monkeypatch.setattr(P, "key_is_undecryptable", lambda backend: False)
    monkeypatch.setattr(P, "_active_key", lambda backend: "k")
    p = P.LLMProvider("openrouter", "coder")
    assert p.model == "vendor/pinned-coder"
    with pytest.raises(AttributeError):
        p.model = "somebody-else/model"            # the binding is the operator's


def test_the_fallback_model_has_no_default(monkeypatch):
    """Defect 4: a literal Anthropic id was the default; now "" — skipped like any
    unconfigured backend — unless the operator names one."""
    from aughor.llm import provider as P
    monkeypatch.delenv("AUGHOR_FALLBACK_MODEL", raising=False)
    assert P._fallback_model() == ""
    monkeypatch.setenv("AUGHOR_FALLBACK_MODEL", "  vendor/named  ")
    assert P._fallback_model() == "vendor/named"


def test_a_registry_row_whose_bytes_are_gone_says_missing_not_empty(tmp_path, monkeypatch):
    """Defect 9: `data/datasets/` was absent, so the 5 golden rows read as 0. The store
    now says which empty a reader is looking at, and the door repeats it."""
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.learning import store

    monkeypatch.setenv("AUGHOR_LEARNING_DB", str(tmp_path / "learning.db"))
    monkeypatch.setenv("AUGHOR_DATASETS_DIR", str(tmp_path / "datasets"))
    rows = [{"question": "q1", "sql": "select 1"}]
    node = store.register("tj1-golden", "golden", rows, task="nl2sql")
    assert store.bytes_state(node) == "present" and store.rows_of(node) == rows

    # The bytes vanish under the registry (a full-suite run has done this to data/).
    for f in (tmp_path / "datasets").glob("*.jsonl"):
        f.unlink()
    assert store.bytes_state(node) == "missing" and store.rows_of(node) == []
    body = TestClient(app).get("/learning/datasets/tj1-golden").json()
    assert body["bytes"] == "missing" and "re-run the export" in body["note"]

    # Re-exporting an unchanged corpus writes the same path — the missing file comes back.
    again = store.register("tj1-golden", "golden", rows, task="nl2sql")
    assert again["data_id"] == node["data_id"] and store.bytes_state(again) == "present"

    store.purge_bytes(node["data_id"])
    assert store.bytes_state(node) == "purged"
    assert TestClient(app).get("/learning/datasets/tj1-golden").json()["bytes"] == "purged"


def test_the_usage_summary_consults_the_catalogue_at_most_hourly(monkeypatch):
    """The unpriced 83 of 83: `refresh_catalogue_prices` had no caller. The summary now
    asks once, then not again within the hour — a page load is not a provider request."""
    from aughor.obs import usage
    calls = []
    monkeypatch.setattr(usage, "refresh_catalogue_prices", lambda: calls.append(1) or 7)
    monkeypatch.setattr(usage, "_CATALOGUE_REFRESHED_AT", 0.0)
    assert usage.ensure_catalogue_prices() == 7
    assert usage.ensure_catalogue_prices() == 0
    assert usage.ensure_catalogue_prices(max_age_s=0.0) == 7
    assert calls == [1, 1]


def test_the_summary_route_says_whose_gap_an_unpriced_call_is(monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.obs import usage
    monkeypatch.setattr(usage, "refresh_catalogue_prices", lambda: 0)
    monkeypatch.setattr(usage, "_CATALOGUE_REFRESHED_AT", 0.0)
    body = TestClient(app).get("/obs/usage-summary?range=24h").json()
    assert body["pricing"]["catalogue_consulted"] is True
    assert "provider's model catalogue" in body["pricing"]["unpriced_means"]


def test_a_converse_turns_decision_records_carry_the_runs_own_trace(monkeypatch):
    """Defect 2: the decision trace was a fresh uuid per turn and joined nothing (188 of
    188). It is now the run's ambient trace — the id the session log and the history row
    already carry — so one query walks turn → decisions → steps."""
    import asyncio

    from aughor import telemetry as tel
    from aughor.routers import investigations as inv

    seen: dict = {}

    def _converse(connection_id, question, **kw):
        seen["trace_id"] = kw.get("trace_id")
        return type("R", (), {"answer": "There were 1,744 orders.", "steps": [],
                              "stop_reason": "done"})()

    monkeypatch.setattr("aughor.agent.converse_tools.converse", _converse)
    monkeypatch.setattr("aughor.agent.converse_tools.ground_answer_numbers",
                        lambda answer, rows, question="": (answer, None))
    monkeypatch.setattr(inv, "build_history_section", lambda h: "")
    monkeypatch.setattr(inv, "build_prior_answers_section", lambda a: "")
    monkeypatch.setattr(inv, "resolve_prior_answers", lambda *a, **k: [])

    async def _drain():
        return [c async for c in inv._stream_converse("how many orders?", "fixture", [], session_id="s1")]

    with tel.bind_trace("run-tj1-abc"):
        asyncio.run(_drain())
    assert seen["trace_id"] == "run-tj1-abc"

    # Outside any bound trace the rows still get an id a verdict can close.
    seen.clear()
    asyncio.run(_drain())
    assert seen["trace_id"] and seen["trace_id"] != "run-tj1-abc"


def test_the_learning_summary_counts_the_few_shot_memory(monkeypatch):
    """The receipt door for the memory's collections — counted in the serving process, and a
    count that could not be taken reads None, never 0."""
    from fastapi.testclient import TestClient

    from aughor.api import app
    monkeypatch.setenv("AUGHOR_EMBED_BACKEND", "ollama")
    monkeypatch.setattr("aughor.semantic.vector_store.collection_count",
                        lambda name: {"aughor_sql_examples": 3, "aughor_investigations": 1}[name])
    body = TestClient(app).get("/learning/summary").json()["few_shot"]
    assert body == {"backend": "ollama", "model": "nomic-embed-text", "sql_examples": 3, "investigations": 1}

    def _down(name):
        raise RuntimeError("locked")
    monkeypatch.setattr("aughor.semantic.vector_store.collection_count", _down)
    body = TestClient(app).get("/learning/summary").json()["few_shot"]
    assert body["sql_examples"] is None and "could not be counted" in body["note"]
