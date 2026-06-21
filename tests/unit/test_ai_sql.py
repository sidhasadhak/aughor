"""R8 — AI as a governed SQL operator (prompt() over a column). Hermetic: the LLM provider
is faked, so we test the GOVERNANCE (pinning, row-cap refusal, fail-open, provenance, UDF
cost-gate), not the model."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

import aughor.semops.ai_sql as ai_sql


class _FakeProvider:
    _model = "fake-model"

    def __init__(self, fn):
        self._fn, self.calls = fn, []

    def complete(self, *, system, user, response_model, temperature=None):
        self.calls.append({"temperature": temperature, "user": user})
        return self._fn(user)


def _echo(user: str):
    """Return value 'v{i}' for every '[i]' index present in the prompt listing."""
    idxs = [int(m) for m in re.findall(r"\[(\d+)\]", user)]
    return SimpleNamespace(rows=[SimpleNamespace(index=i, value=f"v{i}") for i in idxs])


def _patch(monkeypatch, fn):
    prov = _FakeProvider(fn)
    monkeypatch.setattr(ai_sql, "get_provider", lambda role: prov)
    return prov


def test_ai_prompt_aligns_values_and_records_provenance(monkeypatch):
    prov = _patch(monkeypatch, _echo)
    out, rec = ai_sql.ai_prompt(["good", "bad", "ok"], "classify sentiment")
    assert out == ["v0", "v1", "v2"]
    assert rec.operator == "prompt" and rec.model == "fake-model"
    assert rec.n_input == 3 and rec.n_applied == 3 and not rec.truncated
    assert all(c["temperature"] == 0.0 for c in prov.calls)   # pinned deterministic


def test_ai_prompt_refuses_over_the_cap(monkeypatch):
    _patch(monkeypatch, _echo)
    out, rec = ai_sql.ai_prompt(["x"] * 10, "label", max_rows=5)
    assert rec.truncated and out == [None] * 10            # refused, not silently truncated
    assert any("exceed" in n for n in rec.notes)


def test_ai_prompt_is_fail_open_per_batch(monkeypatch):
    def _boom(_user):
        raise RuntimeError("llm down")
    _patch(monkeypatch, _boom)
    out, rec = ai_sql.ai_prompt(["a", "b"], "label")
    assert out == [None, None]                              # never raises into the query path
    assert rec.n_applied == 0 and any("failed" in n for n in rec.notes)


def test_ai_prompt_empty_input():
    out, rec = ai_sql.ai_prompt([], "label")
    assert out == [] and rec.n_input == 0


def test_ai_prompt_override_cap_processes(monkeypatch):
    _patch(monkeypatch, _echo)
    out, rec = ai_sql.ai_prompt(["x"] * 8, "label", max_rows=5, override_cap=True, batch=4)
    assert not rec.truncated and rec.n_applied == 8


class _FakeDuck:
    def __init__(self):
        self.fn = None

    def create_function(self, name, fn, args, ret):
        self.name, self.fn = name, fn


def test_prompt_udf_is_cost_gated(monkeypatch):
    _patch(monkeypatch, _echo)
    duck = _FakeDuck()
    ai_sql.register_prompt_udf(duck, max_calls=2, name="prompt")
    assert duck.name == "prompt" and duck.fn is not None
    assert duck.fn("label", "txt") == "v0"      # call 1
    duck.fn("label", "txt")                     # call 2
    with pytest.raises(RuntimeError, match="governance cap"):
        duck.fn("label", "txt")                 # call 3 → over the cap, raises loudly


def test_emit_ai_receipt_fail_open():
    rec = ai_sql.AIColumnReceipt(operator="prompt", template="t", role="fast", model="m", n_input=1)
    ai_sql.emit_ai_receipt(rec, conn_id="c1")   # must not raise (hermetic ledger)
    assert rec.to_dict()["operator"] == "prompt"
