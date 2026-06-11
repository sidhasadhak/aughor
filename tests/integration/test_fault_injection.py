"""Hot-path fault injection — an internal dependency failure must DEGRADE GRACEFULLY.

The robustness suite has three axes; this is the third:
  * test_failure_paths.py   — bad INPUTS (4xx / surfaced error, never 500)
  * scripts/chaos_drill.py  — CRASH faults (kill -9 → orphan recovery)
  * THIS FILE               — internal DEPENDENCY faults (the LLM provider throws
                              mid-request on a hot path)

The contract: when the LLM backend dies mid-request, the platform surfaces an
error to the user and stays alive — it never crashes the process, never hangs,
and never returns a silent-wrong success.

Behavior was PROBED against the real app before these were written (chat → one
`error` SSE in ~2s, server alive after; investigate → error+done via salvage,
server alive; SqlWriter.fix → FixResult(ok=False), never raises). Each assertion
below reflects observed behavior, so a regression that turns graceful degradation
into a crash/hang/silent-success trips CI.

All in-process via TestClient + monkeypatch — no live LLM, no live server.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient


class _RaisingProvider:
    """Stands in for every LLM provider role; every call fails like a dead backend."""

    def complete(self, *args, **kwargs):
        raise RuntimeError("INJECTED: LLM backend unavailable")


@pytest.fixture
def llm_down(monkeypatch):
    """Make every get_provider(...).complete(...) raise. The hot paths import
    get_provider at call time from aughor.llm.provider, so patching the attribute
    there reaches them; replacing the factory also bypasses the per-role cache and
    the Anthropic fallback (no real network)."""
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role="coder": _RaisingProvider())


def _stream_events(client: TestClient, path: str, body: dict, timeout_s: float = 60.0) -> list[dict]:
    """POST an SSE endpoint and collect parsed `data:` events, with a wall-clock
    guard so a hang fails loudly instead of stalling the suite."""
    events: list[dict] = []
    t0 = time.monotonic()
    with client.stream("POST", path, json=body) as r:
        assert r.status_code == 200, f"{path} did not open a stream: {r.status_code}"
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except Exception:
                    pass
            if time.monotonic() - t0 > timeout_s:
                pytest.fail(f"{path} did not terminate within {timeout_s}s under injected LLM failure (hang)")
    return events


# ── Chat hot path — LLM failure → error SSE, never silent success, server survives ──

def test_chat_surfaces_error_and_server_survives(client: TestClient, builtin_conn_id: str, llm_down) -> None:
    events = _stream_events(client, "/chat", {
        "connection_id": builtin_conn_id, "question": "what is total revenue?", "mode": "ask",
    })
    types = [e.get("type") for e in events]

    # The user MUST be told it failed — a populated error event, not a silent empty stream.
    err = [e for e in events if e.get("type") == "error"]
    assert err, f"chat swallowed an LLM failure (no error event): {types}"
    assert (err[-1].get("message") or "").strip(), "error event carried no message"

    # And it must NOT have emitted a successful answer alongside the failure.
    assert "answer" not in types, f"chat emitted an answer despite the LLM being down: {types}"

    # The process is not poisoned by the fault — the next request still works.
    assert client.get("/health").status_code == 200


# ── SqlWriter repair loop — the contract Phase-8 relies on: fix() fails SOFT ────

def test_sqlwriter_fix_fails_soft_under_llm_failure() -> None:
    """Phase-8's exploration loop calls sql_writer.fix() and treats `not fix.ok` as
    'drop this angle, continue'. So fix() must NEVER propagate the LLM exception —
    it must return FixResult(ok=False). If this regresses, one dead LLM call would
    crash the whole exploration instead of losing a single angle."""
    from aughor.sql.writer import SqlWriter, FixResult

    class _FakeDB:
        dialect = "duckdb"
        def get_schema(self):
            return 'TABLE t(a INT, b INT)'
        def dry_run(self, sql):
            return (True, "")

    w = SqlWriter(_FakeDB(), schema_str='TABLE t(a INT, b INT)')
    w._llm = _RaisingProvider()  # every fix attempt's LLM call raises

    result = w.fix("SELECT bad FROM t", "Binder Error: bad does not exist", max_retries=2)
    assert isinstance(result, FixResult)
    assert result.ok is False, "fix() must fail soft, not succeed, when the LLM is down"
    assert result.sql == "SELECT bad FROM t", "failed fix should hand back the original SQL"
    assert result.attempts == 2


# ── Investigate salvage — the terminal-synthesis contract: never raises ────────

def test_try_salvage_returns_none_without_evidence() -> None:
    """_try_salvage underpins /investigate's graceful end. With no gathered evidence
    it returns None (caller then emits the error SSE) — and it must never raise."""
    from aughor.routers.investigations import _try_salvage
    assert _try_salvage({}, "inv_none", "why did revenue change?", "fixture") is None


def test_try_salvage_never_raises_on_malformed_state() -> None:
    """Even if the partial state is malformed (a non-model object where a model is
    expected), salvage swallows it and returns None — never raises into the stream."""
    from aughor.routers.investigations import _try_salvage
    bad = {"subq_answers": ["not-a-model"], "sub_questions": ["nope"]}
    assert _try_salvage(bad, "inv_bad", "q", "fixture") is None
