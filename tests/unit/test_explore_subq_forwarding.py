"""Explore path: per-sub-question evidence forwarding + progress payload (T3-3, 2026-07-09).

Deep-Analysis audit finding (inv2, explore mode): the `explore_report` event forwarded SQL+rows for
only the LAST sub-question — the streaming router's manual dict-merge clobbers the `operator.add`
`subq_answers` channel — so Q1..Q5 were uninspectable AND had no chart (the frontend renders a chart
per step from each answer's columns/rows). `_explore_subq_event` carries each step's evidence for a
progress event; `_reduced_subq_answers` re-reads the authoritative reduced state. See
aughor/routers/investigations.py.
"""
import asyncio

from aughor.agent.state import SubQuestionAnswer
from aughor.routers.investigations import _explore_subq_event, _reduced_subq_answers


def _answer(i, nrows):
    return SubQuestionAnswer(
        subq_id=f"Q{i}", question=f"q{i}", purpose="relationship",
        sql=f"SELECT {i}", columns=["seg", "rate"],
        rows=[[f"s{j}", float(j)] for j in range(nrows)], row_count=nrows,
        error=None, answer=f"a{i}", insight=f"ins{i}", refinement=None)


def test_event_carries_columns_rows_for_charting():
    """Each progress event carries the step's own columns+rows — the datum the frontend charts."""
    ev = _explore_subq_event(_answer(1, 5))
    assert ev["subq_id"] == "Q1"
    assert ev["columns"] == ["seg", "rate"]
    assert len(ev["rows"]) == 5
    assert ev["sql"] == "SELECT 1"


def test_event_caps_rows_at_30():
    ev = _explore_subq_event(_answer(2, 100))
    assert len(ev["rows"]) == 30


def test_reduced_answers_prefers_graph_state():
    """When the checkpoint holds the full accumulated list, it wins over the clobbered fallback."""
    full = [_answer(i, 3) for i in range(1, 7)]        # all 6 sub-questions

    class _Agent:
        def get_state(self, config):
            return type("S", (), {"values": {"subq_answers": full}})()

    got = asyncio.run(_reduced_subq_answers(_Agent(), "inv1", fallback=[_answer(6, 3)]))
    assert len(got) == 6                                # not just the last one


def test_reduced_answers_falls_back_on_read_error():
    """A checkpoint read failure degrades to the clobbered list, never crashes the stream."""
    class _Agent:
        def get_state(self, config):
            raise RuntimeError("no checkpoint")

    fallback = [_answer(6, 3)]
    got = asyncio.run(_reduced_subq_answers(_Agent(), "inv1", fallback=fallback))
    assert got is fallback
