"""Per-run Learning Receipt (Wave 1 · E4) — the closed loop's per-answer work, made visible.

Covers the run accumulator (LearningSignals on RunMetrics), the pure builder, and the crystallize
touchpoint. Flag-gated (learning.receipt): off → None → byte-identical (no receipt section, no SSE).
"""
from __future__ import annotations

import pytest

from aughor.agent.learning_receipt import build_learning_receipt
from aughor.kernel import metering


@pytest.fixture
def run():
    """An active metered run — mirrors the answer path's _metered_stream wrapper."""
    token = metering.start()
    try:
        yield
    finally:
        metering.reset(token)


def _ra(*sources):
    """A resolved-ambiguity list shaped like the Trust-Receipt writer's _resolved_ambig."""
    return [{"subject": f"s{i}", "reading": "r", "source": s} for i, s in enumerate(sources)]


# ── the run accumulator ───────────────────────────────────────────────────────

def test_record_learning_is_noop_without_a_run():
    assert metering.learning_snapshot() is None
    metering.record_learning(resolutions_crystallized=1)     # background/seed call must not crash
    assert metering.learning_snapshot() is None


def test_record_learning_accumulates_within_a_run(run):
    metering.record_learning(resolutions_crystallized=1)
    metering.record_learning(resolutions_crystallized=1, trusted_program_replayed=1)
    assert metering.learning_snapshot() == {"resolutions_crystallized": 2, "trusted_program_replayed": 1}


def test_record_learning_ignores_unknown_fields(run):
    metering.record_learning(bogus_field=5, resolutions_crystallized=1)
    snap = metering.learning_snapshot()
    assert snap["resolutions_crystallized"] == 1 and "bogus_field" not in snap


def test_cost_snapshot_stays_byte_identical(run):
    # Learning rides the same accumulator but is a SEPARATE surface — the cost blob stamped on the
    # Trust Receipt must not gain a `learning` key.
    metering.record_learning(resolutions_crystallized=3)
    assert "learning" not in metering.snapshot()


# ── the pure builder ──────────────────────────────────────────────────────────

def test_receipt_is_none_when_flag_off(monkeypatch, run):
    monkeypatch.delenv("AUGHOR_LEARNING_RECEIPT", raising=False)
    metering.record_learning(resolutions_crystallized=1)
    assert build_learning_receipt(_ra("user")) is None       # off → nothing, byte-identical


def test_receipt_is_none_when_nothing_happened(monkeypatch, run):
    monkeypatch.setenv("AUGHOR_LEARNING_RECEIPT", "1")
    assert build_learning_receipt([]) is None                # all-zero receipt is noise → suppressed


def test_receipt_counts_readings_and_corrections(monkeypatch, run):
    monkeypatch.setenv("AUGHOR_LEARNING_RECEIPT", "1")
    r = build_learning_receipt(_ra("probe", "user", "verdict"))
    assert r["readings_reused"] == 3
    assert r["corrections_applied"] == 2                     # user + verdict count as corrections, probe doesn't
    assert r["by_source"] == {"probe": 1, "user": 1, "verdict": 1}
    assert r["resolutions_crystallized"] == 0 and r["trusted_program_replayed"] == 0


def test_receipt_merges_runtime_events(monkeypatch, run):
    monkeypatch.setenv("AUGHOR_LEARNING_RECEIPT", "1")
    metering.record_learning(resolutions_crystallized=1, trusted_program_replayed=1)
    r = build_learning_receipt([])                           # no readings, but runtime events → still surfaced
    assert r is not None and r["readings_reused"] == 0
    assert r["resolutions_crystallized"] == 1 and r["trusted_program_replayed"] == 1


# ── the touchpoint (end to end) ───────────────────────────────────────────────

def test_crystallize_records_a_signal_within_a_run(run):
    from aughor.semantic.ambiguity_ledger import crystallize_user_choice, purge_connections
    purge_connections(["lr_cryst"])
    crystallize_user_choice("lr_cryst", "top products", "by revenue")
    assert metering.learning_snapshot()["resolutions_crystallized"] == 1


# ── the Trust-Receipt integration (no LLM) ────────────────────────────────────

def _capture_artifacts(monkeypatch):
    """Patch artifact_write/emit on the real Ledger singleton; return the captured-payload list."""
    from aughor.kernel.ledger import Ledger
    payloads: list[dict] = []
    real = Ledger.default()
    monkeypatch.setattr(real, "artifact_write", lambda kind, nk, payload, **kw: payloads.append(payload))
    monkeypatch.setattr(real, "emit", lambda *a, **k: None)
    return payloads


def test_write_answer_receipt_attaches_and_returns_learning(monkeypatch, run):
    monkeypatch.setenv("AUGHOR_LEARNING_RECEIPT", "1")
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")            # retrieve_resolutions is closed_loop-gated
    from aughor.semantic.ambiguity_ledger import crystallize_user_choice, purge_connections
    purge_connections(["lr_wr"])
    crystallize_user_choice("lr_wr", "top products", "by revenue")   # matched below + records crystallized=1
    payloads = _capture_artifacts(monkeypatch)

    from aughor.routers.investigations import _write_answer_receipt
    out = _write_answer_receipt(
        kind="chat_answer", natural_key="chat:lr_wr:t1", question="what are the top products?",
        sqls=["SELECT 1"], headline="Top products", schema="", connection_id="lr_wr")

    assert out is not None and out["readings_reused"] >= 1 and out["resolutions_crystallized"] == 1
    assert payloads and payloads[0].get("learning") == out   # the SAME receipt is persisted + returned


def test_write_answer_receipt_byte_identical_when_flag_off(monkeypatch, run):
    monkeypatch.delenv("AUGHOR_LEARNING_RECEIPT", raising=False)
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    from aughor.semantic.ambiguity_ledger import crystallize_user_choice, purge_connections
    purge_connections(["lr_off"])
    crystallize_user_choice("lr_off", "top products", "by revenue")
    payloads = _capture_artifacts(monkeypatch)

    from aughor.routers.investigations import _write_answer_receipt
    out = _write_answer_receipt(
        kind="chat_answer", natural_key="chat:lr_off:t1", question="what are the top products?",
        sqls=["SELECT 1"], headline="Top products", schema="", connection_id="lr_off")

    assert out is None                                       # flag off → no receipt returned…
    assert payloads and "learning" not in payloads[0]        # …and no payload key
