"""Ground-first resolution on the REAL /chat runtime (flag ask.resolve_first).

Hermetic: the coder provider is stubbed (and asserted *not* called on the abstain
path), so no LLM. Drives the actual `_stream_chat` endpoint via the TestClient.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient


def _stream_headline(client, conn_id, question, *, want_type="headline", timeout=60):
    got = {"headline": None, "types": []}
    with client.stream("POST", "/chat", json={
        "connection_id": conn_id, "question": question, "mode": "ask",
    }) as r:
        assert r.status_code == 200, r.text
        t0 = time.monotonic()
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                try:
                    e = json.loads(line[5:].strip())
                except Exception:
                    continue
                got["types"].append(e.get("type"))
                if e.get("type") == "headline":
                    got["headline"] = e.get("headline")
                if e.get("type") in ("done", "error"):
                    break
            if time.monotonic() - t0 > timeout:
                pytest.fail("/chat did not finish in time")
    return got


def _stub_coder(monkeypatch, called):
    # Records every user prompt the coder sees. The abstain assertion must be
    # QUESTION-scoped: the session TestClient app keeps background work alive
    # (investigation jobs / explorer threads from earlier tests), and any of it
    # calling the process-global get_provider during this test's monkeypatch
    # window would trip a bare "was the coder called at all" flag — a proven
    # full-suite-order flake, not a product regression.
    import aughor.llm.provider as prov
    from aughor.routers.investigations import _ChatAnswer
    real = prov.get_provider

    class FakeCoder:
        def complete(self, *a, **k):
            called["coder"] = True
            called.setdefault("users", []).append(str(k.get("user", "")))
            return _ChatAnswer(sql="SELECT 1 AS x", headline="stub answer")

        def complete_streaming(self, *a, **k):
            return self.complete(*a, **k)

    monkeypatch.setattr(prov, "get_provider",
                        lambda role="coder", **kw: FakeCoder() if role == "coder" else real(role))


def test_abstains_before_generation_on_absent_entity(client: TestClient, builtin_conn_id: str, monkeypatch):
    # "Mytheresa" is not a value anywhere in the ecommerce fixture → the bounded
    # existence probe confirms absence → honest abstain BEFORE the coder runs.
    monkeypatch.setenv("AUGHOR_ASK_RESOLVE_FIRST", "1")
    called = {"coder": False}
    _stub_coder(monkeypatch, called)

    got = _stream_headline(client, builtin_conn_id, "show me sales for mytheresa")
    assert got["headline"] and "not present in this data" in got["headline"], got
    mytheresa_prompts = [u for u in called.get("users", []) if "mytheresa" in u.lower()]
    assert not mytheresa_prompts, "abstain must short-circuit before SQL generation for THIS question"


def test_flag_off_is_unchanged(client: TestClient, builtin_conn_id: str, monkeypatch):
    # Flag off → resolution never runs → the coder generates as usual (byte-identical path).
    monkeypatch.setenv("AUGHOR_ASK_RESOLVE_FIRST", "0")
    called = {"coder": False}
    _stub_coder(monkeypatch, called)

    _stream_headline(client, builtin_conn_id, "show me sales for mytheresa")
    assert called["coder"] is True, "flag-off must reach normal generation"
