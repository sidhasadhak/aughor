"""Track A8 (docs/TENX_PROGRAM_2026-11-05.md): a store that fell back to its legacy file is SAID on /health.

`util/json_store._fell_back` already logged and counted the fallback; nothing a person reads showed it.
A read there is stale (the file is a one-time import) and a write is orphaned (nothing reconciles it).
"""
from __future__ import annotations

from aughor.stats import stats


def test_health_is_clean_when_every_store_reached_the_ledger(client, monkeypatch):
    stats.reset()
    body = client.get("/health").json()
    assert body["store_fallbacks"]["ok"] is True and body["store_fallbacks"]["since_boot"] == 0
    assert "reached the ledger" in body["store_fallbacks"]["detail"]


def test_a_fallback_degrades_health_and_names_the_operation(client, monkeypatch):
    stats.reset()
    from aughor.util.json_store import _fell_back
    _fell_back("/x/agent_runs.json", RuntimeError("database is locked"), "list_upsert")
    _fell_back("/x/agent_runs.json", RuntimeError("database is locked"), "list_upsert")
    _fell_back("/x/profiles.json", RuntimeError("database is locked"), "load")
    body = client.get("/health").json()
    fb = body["store_fallbacks"]
    assert fb["ok"] is False and fb["since_boot"] == 3
    assert fb["by_operation"] == {"ledger_fallback.list_upsert": 2, "ledger_fallback.load": 1}
    assert "orphaned" in fb["detail"] and body["status"] == "degraded"
    stats.reset()
