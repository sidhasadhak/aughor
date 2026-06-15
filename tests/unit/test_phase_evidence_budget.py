"""Budget-aware phase evidence for ada_synthesize — verbatim up to the budget, overflow folded.

The old behavior truncated the evidence log to 6 000 chars, silently dropping the tail. The budgeted
version keeps phases verbatim (exact numbers for grounding) up to the budget and folds overflow phases
into a number-preserving digest instead. The fold's LLM is faked here.
"""
from __future__ import annotations

from types import SimpleNamespace

import aughor.llm.provider as prov
from aughor.agent.investigate import _one_phase_evidence, _phases_evidence, _phases_evidence_budgeted


def _phase(name: str, sql: str) -> dict:
    return {
        "phase_id": name.lower(), "phase_name": name, "phase_icon": "", "status": "complete",
        "summary": "s", "skipped_reason": None,
        "findings": [{
            "finding_id": "f", "title": "t", "sql": sql, "columns": ["a"], "rows": [["1"]],
            "row_count": 1, "error": None, "interpretation": "i", "key_numbers": [],
            "chart_type": "auto", "stat_note": None, "is_significant": False,
        }],
    }


class _FakeProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls += 1
        return SimpleNamespace(text="SUMMARY")


def test_under_budget_is_verbatim_no_llm(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fake)
    phases = [_phase("Baseline", "SELECT 1"), _phase("Dimensional", "SELECT 2")]

    out = _phases_evidence_budgeted(phases, budget=10_000)

    assert out == _phases_evidence(phases)      # unchanged
    assert fake.calls == 0                       # no fold needed


def test_overflow_phases_are_folded_not_dropped(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fake)
    big = "SELECT " + "x" * 200
    phases = [_phase("Baseline", big), _phase("Dimensional", big), _phase("Behavioral", big)]
    # budget fits only the first phase verbatim
    budget = len(_one_phase_evidence(phases[0])) + 5

    out = _phases_evidence_budgeted(phases, budget=budget)

    assert "=== Baseline ===" in out                       # kept verbatim
    assert "ADDITIONAL EVIDENCE (summarized — 2 phase" in out
    assert "[Dimensional] SUMMARY" in out                  # overflow folded, not dropped
    assert "[Behavioral] SUMMARY" in out
    assert fake.calls == 2                                 # one digest per overflow phase


def test_fail_open_falls_back_to_truncation(monkeypatch):
    def boom(role=None):
        raise RuntimeError("fast model down")
    monkeypatch.setattr(prov, "get_provider", boom)
    big = "SELECT " + "y" * 300
    phases = [_phase("Baseline", big), _phase("Dimensional", big)]
    budget = 100

    out = _phases_evidence_budgeted(phases, budget=budget)

    assert len(out) == budget                              # truncated, never raised
    assert "ADDITIONAL EVIDENCE" not in out


def test_single_giant_phase_falls_back_to_truncation(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fake)
    phases = [_phase("Baseline", "SELECT " + "z" * 500)]   # one phase already over budget
    out = _phases_evidence_budgeted(phases, budget=100)
    assert len(out) == 100                                 # nothing to keep verbatim → truncate
