"""Earned autonomy ladder (memory/trust.py) + activated auto-crystallize. A connection climbs
L0→L3 from the run signals `record_run` persists (clean = grounded AND read-only); at L2+ a clean
run auto-crystallizes into an EXPLAIN-gated learned skill. Conservative: L0 is the floor and the
thresholds need a real sample, so auto-execution is never earned by accident."""
from __future__ import annotations

import pytest

from aughor.memory import trust as T
from aughor.memory import skills as S


def _runs(n_clean, n_dirty=0, conf=0.9):
    clean = [{"connection_id": "c", "grounded": True, "read_only": True, "confidence": conf} for _ in range(n_clean)]
    dirty = [{"connection_id": "c", "grounded": False, "read_only": True, "confidence": 0.4} for _ in range(n_dirty)]
    return clean + dirty


# ── connection autonomy ladder ────────────────────────────────────────────────────

def test_no_runs_is_l0_manual():
    a = T.autonomy_level("never-seen")
    assert a["level"] == 0 and a["label"] == "manual"


@pytest.mark.parametrize("clean,dirty,expect", [
    (0, 0, 0),        # nothing → L0
    (4, 0, 0),        # too few clean → L0
    (6, 0, 1),        # ≥5 clean, 100% → L1
    (10, 5, 0),       # 10 clean but 67% rate → below L1's 80% → L0
    (20, 0, 2),       # ≥20 clean, 100% → L2
    (50, 0, 3),       # ≥50 clean, 100%, conf 0.9 → L3
])
def test_ladder_thresholds(monkeypatch, clean, dirty, expect):
    monkeypatch.setattr(T, "_runs_for", lambda c: _runs(clean, dirty))
    assert T.autonomy_level("c")["level"] == expect


def test_l3_requires_mean_confidence(monkeypatch):
    # 50 clean @ 100% but low confidence → can't reach L3, settles at L2.
    monkeypatch.setattr(T, "_runs_for", lambda c: _runs(50, 0, conf=0.5))
    assert T.autonomy_level("c")["level"] == 2


# ── per-skill autonomy is capped by the connection's level ─────────────────────────

def test_skill_autonomy_capped_by_connection(monkeypatch):
    monkeypatch.setattr(T, "_runs_for", lambda c: _runs(6))      # connection earns L1
    assert T.skill_autonomy(100, "c")["level"] == 1              # heavy reuse, but capped at L1
    assert T.skill_autonomy(0, "c")["level"] == 0


def test_skill_autonomy_usage_rungs(monkeypatch):
    monkeypatch.setattr(T, "_runs_for", lambda c: _runs(60))     # connection L3 (uncaps usage)
    assert T.skill_autonomy(0, "c")["level"] == 0
    assert T.skill_autonomy(1, "c")["level"] == 1
    assert T.skill_autonomy(5, "c")["level"] == 2
    assert T.skill_autonomy(20, "c")["level"] == 3


# ── auto-crystallize activates only at earned L2+, double-gated ────────────────────

class _FakeRes:
    error = None

class _FakeConn:
    def execute(self, *_a, **_k):
        return _FakeRes()
    def close(self):
        pass


@pytest.fixture
def _store(tmp_path, monkeypatch):
    from aughor.util.json_store import KeyedJsonStore
    monkeypatch.setattr(S, "_STORE", KeyedJsonStore(str(tmp_path / "skills.json")))


def _wire_l2(monkeypatch, level=2, run_signals=None):
    monkeypatch.setattr(S, "_autonomy_level", lambda c: level)
    monkeypatch.setattr(S, "_run_signals", lambda inv: run_signals if run_signals is not None else {"grounded": True, "read_only": True})
    monkeypatch.setattr(S, "resolve_active_schema", lambda c: "missimi")
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda c: _FakeConn())
    monkeypatch.setattr("aughor.db.history.get_investigation", lambda _id: {
        "question": "top channels by AOV",
        "report": {"sql": "SELECT marketing_channel, SUM(order_value) AS rev FROM missimi.orders GROUP BY marketing_channel"}})


def test_auto_crystallize_saves_at_l2(_store, monkeypatch):
    _wire_l2(monkeypatch)
    S.auto_crystallize("inv-1", "c")
    assert S.load_learned_actions("c", "missimi"), "a clean L2 run should auto-crystallize a skill"


def test_auto_crystallize_noop_below_l2(_store, monkeypatch):
    _wire_l2(monkeypatch, level=1)
    S.auto_crystallize("inv-1", "c")
    assert S.load_learned_actions("c", "missimi") == {}


def test_auto_crystallize_skips_a_dirty_run_even_at_l2(_store, monkeypatch):
    _wire_l2(monkeypatch, run_signals={"grounded": False, "read_only": True})
    S.auto_crystallize("inv-1", "c")
    assert S.load_learned_actions("c", "missimi") == {}
