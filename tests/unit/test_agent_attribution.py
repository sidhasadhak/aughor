"""Wave H2 — attributing spend and answers to the user-defined persona that produced them.

Two claims, and the pre-check reshaped both:

* **The usage axis is a REPORTING change, not a plumbing one.** ``agent_id`` was already
  written onto every session event from the ambient persona contextvar; G3 measured it at
  0% only because nobody had ever asked *as* an agent. What was missing was the ability to
  group by it. The test that carries this is
  :func:`test_the_agent_axis_reads_the_column_the_write_path_already_fills`.
* **The persona rides one stamp point.** ``_write_answer_receipt`` is the single place every
  user-facing answer (chat / ADA / monitor) is receipted, so an interactive ask and H1's
  scheduled agent run attribute identically — and an unbound answer carries ``agent: null``
  rather than a nameless agent object.

Also pinned: the fleet charter id (scout/analyst/watcher, resolved per job kind in
``kernel/jobs.py``) is NOT this axis. They are different questions — what kind of platform
work ran, versus whose persona asked — and conflating them would misattribute every number.
"""
from __future__ import annotations

from aughor.obs.usage import AXES, rollup
from aughor.trust.receipt import build_public_receipt


def _call(*, agent_id="", provider="openrouter", model="m:free") -> dict:
    return {"provider": provider, "model": model, "ok": True, "duration_ms": 10.0,
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
            "user_id": "", "org_id": "default", "conn_id": "", "agent_id": agent_id,
            "payload": {"role": "coder"}}


# ── the usage axis ──────────────────────────────────────────────────────────────────

def test_the_agent_axis_reads_the_column_the_write_path_already_fills():
    """`agent_id` is a real column on every session event, stamped from the persona
    contextvar. Before H2 the report could not group by it — the data was there and
    unreachable."""
    assert "agent_id" in AXES
    r = rollup([_call(agent_id="ua_1"), _call(agent_id="ua_1"), _call(agent_id="ua_2")],
               axes=("agent_id",))
    assert [(row.key["agent_id"], row.calls) for row in r.rows] == [("ua_1", 2), ("ua_2", 1)]


def test_unbound_calls_are_counted_not_folded_into_a_nameless_agent():
    """Most traffic is anonymous. A blank grouped as an agent reads as a real persona
    outspending every named one — the exact failure G3's `unattributed` exists to prevent."""
    r = rollup([_call(), _call(), _call(agent_id="ua_1")], axes=("agent_id",))
    assert r.unattributed["agent_id"] == 2
    assert r.to_dict()["coverage"]["agent_id"] == 0.333   # reported rounded, as every axis is
    assert "(unattributed)" in {row.key["agent_id"] for row in r.rows}


def test_the_agent_axis_composes_with_cost_axes():
    """The question H2 exists to answer: what did this persona spend, by model."""
    r = rollup([_call(agent_id="ua_1", model="a:free"),
                _call(agent_id="ua_1", model="b:free"),
                _call(agent_id="ua_2", model="a:free")], axes=("agent_id", "model"))
    keys = {(row.key["agent_id"], row.key["model"]): row.calls for row in r.rows}
    assert keys == {("ua_1", "a:free"): 1, ("ua_1", "b:free"): 1, ("ua_2", "a:free"): 1}


# ── the receipt ─────────────────────────────────────────────────────────────────────

def _raw(payload: dict) -> dict:
    return {"artifact": {"id": "art_1", "kind": "chat_answer", "created_at": "2026-07-29T00:00:00Z",
                         "conn_id": "conn-1", "payload": payload},
            "lineage": [], "cost": None}


def test_a_receipt_carries_the_persona_that_produced_the_answer():
    r = build_public_receipt(_raw({"question": "q", "headline": "h",
                                   "agent": {"id": "ua_1", "name": "Customer Analyst"}}),
                             signed=False)
    assert r["agent"] == {"id": "ua_1", "name": "Customer Analyst"}


def test_an_unbound_answer_says_null_rather_than_an_empty_agent():
    """`{}` or `{"id": "", "name": ""}` would render as a nameless agent on every receipt
    ever issued; null is the honest shape for "nobody asked as an agent"."""
    r = build_public_receipt(_raw({"question": "q", "headline": "h"}), signed=False)
    assert r["agent"] is None


def test_the_persona_is_inside_the_signature():
    """Attribution that can be edited without breaking the signature is not attribution."""
    raw = _raw({"question": "q", "headline": "h", "agent": {"id": "ua_1", "name": "A"}})
    signed = build_public_receipt(raw, signed=True)
    from aughor.trust.receipt import verify

    assert verify(signed) is True
    tampered = {**signed, "agent": {"id": "ua_2", "name": "B"}}
    assert verify(tampered) is False
