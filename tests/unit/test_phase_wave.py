"""WS1 · ada.parallel_phases — the deep path's middle-phase wave (phase_waves.py).

Contract under test: baseline ∥ decompose ∥ dimensional run concurrently on reader
clones, and the SERIAL tier-routers' early-stop decisions are applied post-hoc so the
report contains exactly what the serial chain would have produced (dropped phases are
the price of the wall-clock win, never extra report content). Off-flag the graph wires
the classic serial chain — no wave node.
"""
from __future__ import annotations

import threading
import time

import pytest

from aughor.agent.phase_waves import ada_phase_wave, route_after_wave


class _StubConn:
    dialect = "duckdb"
    _connection_id = "stub"

    def make_reader(self):
        return self


def _phase_update(pid: str, extra: dict | None = None) -> dict:
    upd = {"investigation_phases": [{"phase_id": pid, "findings": []}]}
    upd.update(extra or {})
    return upd


@pytest.fixture
def stub_phases(monkeypatch):
    """Patch the three real phase nodes with recording stubs."""
    import aughor.agent.investigate as inv

    calls: dict[str, dict] = {}

    def _mk(pid: str, extra: dict | None = None, delay: float = 0.0, boom: bool = False):
        def node(state, conn=None):
            if boom:
                raise RuntimeError(f"{pid} exploded")
            time.sleep(delay)
            calls[pid] = {"thread": threading.get_ident(),
                          "t": time.time(),
                          "phases_seen": len(state.get("investigation_phases", []))}
            base = list(state.get("investigation_phases", []))
            upd = _phase_update(pid, extra)
            upd["investigation_phases"] = base + upd["investigation_phases"]
            return upd
        return node

    def apply(baseline_extra=None, *, delay=0.0, decompose_boom=False):
        monkeypatch.setattr(inv, "ada_baseline",
                            _mk("baseline", baseline_extra, delay=delay))
        monkeypatch.setattr(inv, "ada_decompose",
                            _mk("decomposition", {"_decomp_summary": "clear split",
                                                  "_decomp_passes": "x"},
                                delay=delay, boom=decompose_boom))
        monkeypatch.setattr(inv, "ada_dimensional",
                            _mk("dimensional", {"_dimensional_summary": "mobile drives it",
                                                "_dimensional_passes": "mobile 68%"},
                                delay=delay))
        return calls

    return apply


SIGNIFICANT = {"_baseline_summary": "big drop", "_baseline_passes": "drop",
               "_baseline_significant": True, "_baseline_sigma": 4.2}
NOT_SIGNIFICANT = {"_baseline_summary": "flat", "_baseline_passes": "flat",
                   "_baseline_significant": False, "_baseline_sigma": 0.4}


def test_wave_runs_concurrently(stub_phases):
    calls = stub_phases(SIGNIFICANT, delay=0.25)
    t0 = time.time()
    out = ada_phase_wave({"question": "why did revenue drop by channel?",
                          "investigation_phases": []}, _StubConn())
    elapsed = time.time() - t0
    assert set(calls) == {"baseline", "decomposition", "dimensional"}
    assert elapsed < 0.6, f"wave took {elapsed:.2f}s — phases ran serially"
    # all kept (dimension question + huge sigma), serial report order preserved
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    assert ids == ["baseline", "decomposition", "dimensional"]


def test_early_stop_drops_sibling_results(stub_phases):
    stub_phases(NOT_SIGNIFICANT)
    out = ada_phase_wave({"question": "why did revenue change?",
                          "investigation_phases": []}, _StubConn())
    # serial router: not significant + no dimension ask → straight to synthesize
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    assert ids == ["baseline"], f"early-stop must drop siblings, got {ids}"
    assert out["_wave_next"] == "ada_synthesize"
    assert "_dimensional_passes" not in out


def test_behavioral_gate_matches_serial_router(stub_phases):
    stub_phases(SIGNIFICANT)
    out = ada_phase_wave({"question": "why did the refund rate spike by channel?",
                          "investigation_phases": []}, _StubConn())
    assert out["_wave_next"] == "ada_behavioral"  # behavioral keyword → serial would proceed
    out2 = ada_phase_wave({"question": "why did revenue drop by channel?",
                           "investigation_phases": []}, _StubConn())
    assert out2["_wave_next"] == "ada_synthesize"  # no behavioral keyword → skip


def test_member_failure_is_isolated(stub_phases):
    stub_phases(SIGNIFICANT, decompose_boom=True)
    out = ada_phase_wave({"question": "why did revenue drop by channel?",
                          "investigation_phases": []}, _StubConn())
    ids = [p["phase_id"] for p in out["investigation_phases"]]
    assert "baseline" in ids and "dimensional" in ids and "decomposition" not in ids


def test_route_after_wave_defaults_to_synthesize():
    assert route_after_wave({}) == "ada_synthesize"
    assert route_after_wave({"_wave_next": "ada_behavioral"}) == "ada_behavioral"


def test_graph_wires_wave_only_when_flag_on(monkeypatch):
    import aughor.agent.graph as g

    class _Db(_StubConn):
        pass

    monkeypatch.setattr(g, "_ada_parallel_phases_enabled", lambda: False)
    compiled_off = g.build_graph_generic(_Db())
    assert "ada_phase_wave" not in compiled_off.get_graph().nodes

    monkeypatch.setattr(g, "_ada_parallel_phases_enabled", lambda: True)
    compiled_on = g.build_graph_generic(_Db())
    assert "ada_phase_wave" in compiled_on.get_graph().nodes
