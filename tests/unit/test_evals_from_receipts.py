"""Wave L2's precondition: eval cases seeded from answer receipts.

Hermetic — the Ledger read goes through `load_investigation_findings`, which these
tests fake. The selection rules are the point: what must NOT become a case matters
more than what does, because a bad case adds noise to the very delta L2 exists to
measure.
"""
from __future__ import annotations

import pytest

from aughor.evals import from_receipts as FR


def _rec(rid, question, sql, headline, tables=()):
    return {"id": rid, "question": question, "sql": sql, "text": headline,
            "tables": list(tables), "source": "evidence_ledger"}


@pytest.fixture()
def _receipts(monkeypatch):
    def _install(records):
        monkeypatch.setattr(FR, "load_investigation_findings", lambda *a, **k: records,
                            raising=False)
        monkeypatch.setattr(
            "aughor.ontology.context_graph_build.load_investigation_findings",
            lambda *a, **k: records)
    return _install


def test_a_receipt_becomes_a_case_carrying_its_executed_sql(_receipts):
    _receipts([_rec("r1", "How many returns were there?",
                    "SELECT COUNT(*) FROM returns", "Returns: 30,949", ["returns"])])
    cases = FR.candidate_cases("c1")
    assert len(cases) == 1
    case = cases[0]
    assert case["question"] == "How many returns were there?"
    assert case["artifact"] == "SELECT COUNT(*) FROM returns"
    assert case["expected"]["headline"] == "Returns: 30,949"
    assert set(FR.CASE_TAGS) <= set(case["tags"])


def test_abstentions_are_not_cases(_receipts):
    """An honest 'I looked and there is nothing there' is worth holding on the graph
    (L1 does) but asserts absence — it would pass for reasons unrelated to the
    configuration under test."""
    _receipts([_rec("r1", "How many returns are there?", "SELECT 1",
                    "Returns table not found in schema; cannot count returns")])
    assert FR.candidate_cases("c1") == []


def test_context_dependent_questions_are_not_cases(_receipts):
    """A replayed case has no conversation around it."""
    _receipts([_rec("r1", "Investigate this finding",
                    "SELECT o.channel, SUM(o.gmv_eur) FROM orders o", "GMV fell in EU")])
    assert FR.candidate_cases("c1") == []


def test_the_same_question_recurring_with_different_sql_is_dropped(_receipts):
    """Recurring text with different SQL carried its meaning in context the case
    cannot replay — keeping both would weight an unreproducible question twice."""
    _receipts([
        _rec("r1", "Show me the orders", "SELECT * FROM orders WHERE region='EU'", "EU"),
        _rec("r2", "Show me the orders", "SELECT * FROM orders WHERE region='US'", "US"),
    ])
    assert len(FR.candidate_cases("c1")) == 1


def test_sql_duplicates_collapse_ignoring_formatting(_receipts):
    _receipts([
        _rec("r1", "Count the orders", "SELECT COUNT(*) FROM orders", "1"),
        _rec("r2", "Total orders please", "select  count(*)\n from ORDERS", "1"),
    ])
    assert len(FR.candidate_cases("c1")) == 1


def test_seed_suite_refuses_to_create_an_empty_suite(_receipts):
    """An empty suite reports a perfect pass rate over zero cases — the most
    misleading number available."""
    _receipts([])
    out = FR.seed_suite("c1")
    assert out == {"suite_id": "", "added": 0, "candidates": 0}


def test_the_suite_says_it_measures_consistency_not_correctness(_receipts, monkeypatch):
    """A receipt records what Aughor PRODUCED, not what was true. If that caveat is
    not attached to the suite, someone will report its pass rate as accuracy."""
    _receipts([_rec("r1", "How many returns were there?",
                    "SELECT COUNT(*) FROM returns", "Returns: 30,949")])
    created: dict = {}
    monkeypatch.setattr("aughor.evals.store.create_suite",
                        lambda name, **kw: created.update({"name": name, **kw})
                        or {"id": "s1"})
    monkeypatch.setattr("aughor.evals.store.add_cases", lambda sid, cases: len(cases))

    out = FR.seed_suite("c1")
    assert out["suite_id"] == "s1" and out["added"] == 1
    desc = created["description"].lower()
    assert "consistency" in desc and "not correctness" in desc
