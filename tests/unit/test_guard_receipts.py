"""A4 — guard receipts: a silent rewrite must announce itself.

The claim under test is the WIRING, layer by layer: the kernel seam is free when
nothing is registered (a bare platform stays agent-free), the agent's forwarder
carries a receipt to the progress sink, and the shared pre-execute hardening
actually reports the de-fan it adopts. The SSE frame shape is pinned so the
frontend dispatcher and the Chain-of-Thought surface have a stable contract.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.kernel.registries import execution_hooks as hooks


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = list(hooks._GUARD_RECEIPT)
    hooks._GUARD_RECEIPT.clear()
    yield
    hooks._GUARD_RECEIPT[:] = saved


def test_bare_platform_emit_is_a_free_noop():
    """No hook registered ⇒ emitting must neither raise nor require the agent layer."""
    hooks.emit_guard_receipt("fanout_defan", "rewrote_sql", detail="x", before="a", after="b")


def test_a_crashing_hook_never_breaks_the_guard():
    """The receipt is telemetry riding on a correctness guard — a broken reporter
    must not take down the rewrite it reports on."""
    hooks.register_guard_receipt_hook("boom", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    seen: list = []
    hooks.register_guard_receipt_hook("ok", lambda g, a, d, b, af: seen.append(g))
    hooks.emit_guard_receipt("preflight_repair", "repaired_sql")
    assert seen == ["preflight_repair"], "the healthy hook still ran after the crashing one"


def test_forwarder_carries_the_receipt_to_the_progress_sink():
    """End-to-end through the real registration: bootstrap's forwarder → the
    ContextVar sink → the self-tagged queue payload the SSE stream translates
    into a `guard_receipt` frame."""
    from aughor.agent.bootstrap import _register_guard_receipt_forwarder
    from aughor.agent.progress import clear_progress_sink, set_progress_sink

    _register_guard_receipt_forwarder()
    loop = asyncio.new_event_loop()
    try:
        q: asyncio.Queue = asyncio.Queue()
        token = set_progress_sink(loop, q)
        try:
            hooks.emit_guard_receipt(
                "fanout_defan", "rewrote_sql",
                detail="join fans out orders across order_items",
                before="SELECT SUM(x) ...", after="WITH pre AS (...) ...")
            loop.run_until_complete(asyncio.sleep(0))   # drain call_soon_threadsafe
            payload = q.get_nowait()
        finally:
            clear_progress_sink(token)
    finally:
        loop.close()

    assert "__guard_receipt__" in payload
    r = payload["__guard_receipt__"]
    assert r["guard"] == "fanout_defan" and r["action"] == "rewrote_sql"
    assert r["before"].startswith("SELECT") and r["after"].startswith("WITH")


def test_preflight_harden_reports_the_defan_it_adopts(monkeypatch):
    """The shared hardening (every answer path) emits through the seam when its
    de-fan rewrite is adopted — the receipt carries the before/after SQL."""
    received: list = []
    hooks.register_guard_receipt_hook("capture",
                                      lambda g, a, d, b, af: received.append((g, a, b, af)))

    class _FF:
        hub_root, satellites = "orders", ["order_items"]

    monkeypatch.setattr("aughor.sql.fanout.detect_fanout", lambda *a, **k: _FF())
    monkeypatch.setattr("aughor.sql.fanout.defan", lambda sql, ff, dialect: "SELECT 2 -- rewritten")
    monkeypatch.setattr("aughor.db.schema_render.parse_schema_tables",
                        lambda s: {"orders": ["id"]})
    monkeypatch.setattr("aughor.sql.safety.preflight_repair", lambda c, s, sc: (s, {}))

    class _Conn:
        dialect = "duckdb"
        def dry_run(self, sql):
            return True, ""

    from aughor.sql.executor import preflight_harden
    out = preflight_harden(_Conn(), "SELECT 1", "TABLE: orders\n  id  BIGINT")
    assert out == "SELECT 2 -- rewritten"
    assert received and received[0][0] == "fanout_defan"
    assert received[0][2] == "SELECT 1" and received[0][3] == "SELECT 2 -- rewritten"
