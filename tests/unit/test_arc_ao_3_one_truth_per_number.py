"""Arc AO-3 — one truth per number.

Measured 2026-10-03 (docs/AGENT_OPS_STUDY_2026-10-03.md §2 D1–D6): the same agent showed
76.7K tokens on the roster row (24h) and 3.5M on its page (all time, the route ignored any
range); `$0.00` on every tile because the model in use had no declared price; five
surfaces rendered "nothing here" on a failed fetch. These pin the window onto every
number, the price onto the model, and the unpriced count onto the spend row.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.custom_agents import create_agent, delete_agent, list_agents


@pytest.fixture(autouse=True)
def _clean_agents():
    yield
    for a in list_agents():
        delete_agent(a.id)


@pytest.fixture()
def client(monkeypatch):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled", lambda name: name == "agents.user_defined")
    from aughor.api import app
    return TestClient(app)


# ── the operator declares a price the provider does not publish ─────────────────────
#
# The product ships no model id (`test_llm_model_catalog` holds that), so the rate for a
# provider with no price endpoint comes from the operator, dated, in one env var. The
# ids below are a test's: a test may name one, `aughor/` may not.

def test_the_operator_can_declare_a_dated_price_for_a_model(monkeypatch):
    import aughor.obs.usage as usage
    monkeypatch.setitem(usage.PRICES, ("gemini", "gemini-3.1-flash-lite"),
                        usage.Price(0.25, 1.50, "2026-09-15"))
    usage.price_for.cache_clear()
    try:
        p = usage.price_for("gemini", "gemini-3.1-flash-lite")
        assert p is not None and p.input_per_1m == 0.25 and p.as_of == "2026-09-15"
        # The preview spelling rides the same prefix; an unrelated model stays unpriced.
        assert usage.price_for("gemini", "gemini-3.1-flash-lite-preview") == p
        assert usage.price_for("gemini", "gemini-9-ultra") is None
    finally:
        usage.price_for.cache_clear()


def test_the_declaration_is_parsed_strictly_and_a_bad_entry_is_dropped_not_guessed(caplog):
    from aughor.obs.usage import Price, declared_prices_from_env
    got = declared_prices_from_env(
        "gemini:gemini-3.1-flash-lite=0.25/1.50@2026-09-15; OpenAI:gpt-x=2/8@2026-09-01;"
        "broken-entry; acme:m=notanumber/1@2026-01-01")
    assert got[("gemini", "gemini-3.1-flash-lite")] == Price(0.25, 1.50, "2026-09-15")
    assert got[("openai", "gpt-x")] == Price(2.0, 8.0, "2026-09-01")
    assert len(got) == 2, "the two bad entries are dropped"
    assert "ignored" in caplog.text
    assert declared_prices_from_env("") == {}
    # An undated rate is still a rate, and says it is undated rather than inventing a day.
    assert declared_prices_from_env("p:m=1/2")[("p", "m")].as_of == "undated"


# ── the observability route reads ONE window and says which ─────────────────────────

def _llm_call(agent_id: str, at: str, *, model: str, prompt: int = 1000, completion: int = 100):
    return {"kind": "llm_call", "agent_id": agent_id, "at": at, "ok": True,
            "provider": "gemini", "model": model, "prompt_tokens": prompt,
            "completion_tokens": completion, "total_tokens": prompt + completion,
            "payload": {"role": "coder"}}


def test_observability_is_windowed_and_the_window_rides_on_the_response(client, monkeypatch):
    import aughor.obs.usage as usage
    from aughor.kernel.ledger import Ledger
    from aughor.db import history

    # One priced model (declared, as an operator would) and one nobody prices.
    monkeypatch.setitem(usage.PRICES, ("gemini", "gemini-3.1-flash-lite"),
                        usage.Price(0.25, 1.50, "2026-09-15"))
    usage.price_for.cache_clear()
    a = create_agent("Windowed", instructions="x")
    captured: dict = {}

    def _events(self, **kw):
        captured.update(kw)
        return [_llm_call(a.id, kw["since"], model="gemini-3.1-flash-lite"),
                _llm_call(a.id, kw["since"], model="mystery-model")]

    monkeypatch.setattr(Ledger, "session_events", _events)
    monkeypatch.setattr(history, "list_investigations_for_agent", lambda aid, limit=50: [
        {"id": "inv-old", "agent_id": aid, "started_at": "2020-01-01T00:00:00+00:00",
         "status": "complete", "kind": "investigation"},
        {"id": "inv-new", "agent_id": aid, "started_at": "2999-01-01T00:00:00+00:00",
         "status": "complete", "kind": "investigation"},
    ])

    r = client.get(f"/agents/custom/{a.id}/observability?range=7d")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window"]["range"] == "7d"
    assert body["window"]["since"] < body["window"]["until"]
    # The spend scan was bounded by that same window and keyed to this agent.
    assert captured["agent_id"] == a.id
    assert captured["since"] == body["window"]["since"]
    assert captured["until"] == body["window"]["until"]
    # Runs outside the window are not this page's runs; the scan size is said.
    assert [x["id"] for x in body["runs"]] == [], "a 2020 run and a 2999 run are both outside 7d"
    assert body["run_count"] == 0 and body["runs_scanned"] == 2
    # One priced call, one unpriced: the row carries the count behind `cost_is_complete`.
    spend = body["spend"]
    assert spend["calls"] == 2
    assert spend["unpriced_calls"] == 1
    assert spend["cost_is_complete"] is False
    assert spend["cost_usd"] > 0, "the priced call must contribute; it is a floor, not zero"


def test_an_unknown_range_falls_back_to_the_default_and_says_so(client, monkeypatch):
    from aughor.kernel.ledger import Ledger
    monkeypatch.setattr(Ledger, "session_events", lambda self, **kw: [])
    a = create_agent("Default", instructions="x")
    body = client.get(f"/agents/custom/{a.id}/observability?range=nonsense").json()
    assert body["window"]["range"] == "24h"
    assert body["spend"]["unpriced_calls"] == 0 and body["spend"]["calls"] == 0


# ── the roster's built-in spend is windowed too ─────────────────────────────────────

def test_the_roster_reads_built_in_spend_over_the_shared_window(client, monkeypatch):
    from aughor.kernel.ledger import Ledger
    captured: dict = {}

    def _jobs(self, **kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(Ledger, "jobs_where", _jobs)
    r = client.get("/agents?range=6h")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows, "the built-in roster is never empty"
    assert captured["since"] and captured["until"]
    assert all(row["window"]["range"] == "6h" for row in rows)
    assert all(row["window"]["since"] == captured["since"] for row in rows)


def test_jobs_take_a_window(client, monkeypatch):
    from aughor.kernel.ledger import Ledger
    captured: dict = {}

    def _jobs(self, **kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(Ledger, "jobs_where", _jobs)
    assert client.get("/jobs?since=2026-10-01T00:00:00Z&until=2026-10-02T00:00:00Z").status_code == 200
    # Normalised by the shared window resolver (one spelling of a bound, everywhere).
    assert captured["since"].startswith("2026-10-01T00:00:00")
    assert captured["until"].startswith("2026-10-02T00:00:00")
    captured.clear()
    assert client.get("/jobs").status_code == 200
    assert captured["since"] is None and captured["until"] is None, "no window means no bound"


# The fleet's custom-agent rows (rolled up from the windowed scan, never the all-time usage
# report) are pinned in `test_agent_ops_endpoints.py`, the file that may name that route.
