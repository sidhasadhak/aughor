"""R3 — the data-understanding grounding block is built ONCE per investigation
(in ada_intake) and reused by every ADA phase, instead of each of baseline /
decompose / dimensional / behavioral re-running measure-grain probing +
trusted-query retrieval for a byte-identical result.

The reuse logic lives in `_phase_grounding`; `run_analysis_phase` calls it and
must not rebuild when a caller threads the shared block in.
"""
from __future__ import annotations

import aughor.semantic.data_understanding as du
import aughor.agent.investigate as inv


class _DU:
    def __init__(self, block):
        self._block = block

    def grounding_block(self):
        return self._block


def _explode(*a, **k):
    raise AssertionError("build_data_understanding must NOT be called here")


def test_reuses_provided_nonempty_block(monkeypatch):
    monkeypatch.setattr(du, "build_data_understanding", _explode)
    out = inv._phase_grounding(
        "GRAINS: revenue is per-order", conn=object(),
        connection_id="c", schema="TABLE: orders(id int)", question="why down?")
    assert out == "GRAINS: revenue is per-order"


def test_reuses_provided_empty_block_without_rebuilding(monkeypatch):
    """Intake stores '' when it found nothing to ground — that is a real answer,
    NOT a signal to rebuild. The None-vs-'' distinction is the whole contract."""
    monkeypatch.setattr(du, "build_data_understanding", _explode)
    assert inv._phase_grounding(
        "", conn=object(), connection_id="c",
        schema="TABLE: orders(id int)", question="q") == ""


def test_builds_when_block_is_none(monkeypatch):
    calls = []
    monkeypatch.setattr(du, "build_data_understanding",
                        lambda *a, **k: calls.append((a, k)) or _DU("BUILT"))
    out = inv._phase_grounding(
        None, conn=object(), connection_id="c",
        schema="TABLE: orders(id int)", question="q")
    assert out == "BUILT"
    assert len(calls) == 1


def test_none_block_without_schema_does_not_build(monkeypatch):
    monkeypatch.setattr(du, "build_data_understanding", _explode)
    assert inv._phase_grounding(
        None, conn=object(), connection_id="c", schema="", question="q") == ""


def test_build_failure_is_fail_open(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("grain probe blew up")
    monkeypatch.setattr(du, "build_data_understanding", _boom)
    assert inv._phase_grounding(
        None, conn=object(), connection_id="c",
        schema="TABLE: orders(id int)", question="q") == ""


def test_run_analysis_phase_does_not_rebuild_when_block_threaded(monkeypatch):
    """End-to-end at the real function: a phase that receives the shared block
    reaches the planner WITHOUT re-running build_data_understanding."""
    monkeypatch.setattr(du, "build_data_understanding", _explode)

    class _StopAtPlanner:
        def complete(self, **k):
            raise RuntimeError("stop after grounding")

    monkeypatch.setattr(inv, "_provider", lambda role: _StopAtPlanner())
    run = inv.run_analysis_phase(
        conn=object(), phase_id="baseline", title="t", emoji="📊",
        plan_system="Write SQL.", plan_user="the question",
        interpret_system="Interpret.", interpret_user_fn=lambda r: "i",
        schema="TABLE: orders(id int)", question="q", connection_id="c",
        grounding_block="REUSED BLOCK",
    )
    # Planner stopped the run, but grounding ran off the reused block (no rebuild,
    # else the _explode stub would have raised AssertionError).
    assert run.ok is False
