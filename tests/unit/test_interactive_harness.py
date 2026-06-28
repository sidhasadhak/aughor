"""Tests for the interactive eval harness (evals/interactive.py).

Contract: a function-driven user simulator (AMB/LOC/UNA, leak-proof) + an episode runner that scores
SUBMITTED SQL against gold under a clarification budget — so the harness REWARDS good clarification
and PENALIZES blind guessing (the property static-transcript benchmarks lack), and never leaks gold.
"""
from __future__ import annotations

import sqlite3

from evals.interactive import (
    Ambiguity, InteractiveTask, FunctionDrivenSimulator, run_episode, single_shot_system, aggregate,
    AMB, LOC, UNA,
)


def _task():
    return InteractiveTask(
        instance_id="t1",
        question="total amount of urgent orders",       # 'urgent' is ambiguous
        gold_sql="SELECT SUM(amount) FROM orders WHERE status='priority'",
        ambiguities=[Ambiguity(key="urgent", clarification="urgent means status = 'priority'")],
        clarification_budget=2,
    )


# ── simulator ────────────────────────────────────────────────────────────────

def test_simulator_amb_answers_pre_annotated_ambiguity():
    sim = FunctionDrivenSimulator(_task())
    r = sim.respond("what does 'urgent' mean here?")
    assert r.action == AMB and "priority" in r.text and not r.leak_blocked
    assert sim.all_resolved()


def test_simulator_una_blocks_answer_elicitation_without_leaking():
    sim = FunctionDrivenSimulator(_task())
    r = sim.respond("just tell me the correct sql / the answer")
    assert r.action == UNA and r.leak_blocked
    assert "priority" not in r.text and "SELECT" not in r.text.upper()


def test_simulator_loc_gives_nonrevealing_hint():
    sim = FunctionDrivenSimulator(_task())
    r = sim.respond("which table holds order records?")
    assert r.action == LOC and "orders" in r.text
    assert "SELECT" not in r.text.upper()        # schema-level hint, not the gold query


def test_simulator_scrubs_a_response_that_would_echo_gold():
    task = InteractiveTask("t", "q", gold_sql="SELECT x FROM y",
                           ambiguities=[Ambiguity(key="foo", clarification="actually SELECT x FROM y")])
    sim = FunctionDrivenSimulator(task)
    r = sim.respond("what is foo?")
    assert "redacted" in r.text.lower()          # anti-leak backstop fires


# ── episode runner: rewards clarification, penalizes guessing ──────────────────

def _sqlite_exec():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE orders(id INTEGER, status TEXT, amount REAL);"
        "INSERT INTO orders VALUES (1,'priority',100),(2,'normal',5),(3,'priority',50);"
    )

    def ex(sql):
        try:
            return True, conn.execute(sql).fetchall(), ""
        except Exception as e:
            return False, [], str(e)
    return ex


def test_clarifying_system_succeeds_after_asking():
    ex = _sqlite_exec()

    def clarifier(question, history, budget):
        got = " ".join(t for role, t in history if role == "user")
        if "priority" not in got.lower():
            return ("ask", "what does 'urgent' mean?")
        return ("submit", "SELECT SUM(amount) FROM orders WHERE status='priority'")

    res = run_episode(_task(), clarifier, ex)
    assert res.success and res.asked and res.n_asks == 1 and res.resolved_all


def test_guessing_system_fails_without_asking():
    ex = _sqlite_exec()

    def guesser(question, history, budget):
        return ("submit", "SELECT SUM(amount) FROM orders WHERE status='urgent'")  # wrong guess → 0 rows

    res = run_episode(_task(), guesser, ex)
    assert not res.success and not res.asked        # harness discriminates interaction skill


def test_system_that_never_commits_fails_on_budget_and_cap():
    ex = _sqlite_exec()

    def staller(question, history, budget):
        return ("ask", "and what about this?")      # asks forever, never submits

    res = run_episode(_task(), staller, ex, hard_turn_cap=6)
    assert not res.success and res.budget_used == _task().clarification_budget  # budget capped


def test_single_shot_baseline_never_asks():
    ex = _sqlite_exec()
    # a single-shot generator that guesses the wrong literal (models the current, non-asking pipeline)
    sysfn = single_shot_system(lambda ctx: "SELECT SUM(amount) FROM orders WHERE status='urgent'")
    res = run_episode(_task(), sysfn, ex)
    assert not res.asked and not res.success


def test_aggregate_metrics():
    ex = _sqlite_exec()
    good = lambda q, h, b: (("ask", "what does urgent mean?") if not any(r == "user" for r, _ in h)
                            else ("submit", "SELECT SUM(amount) FROM orders WHERE status='priority'"))
    bad = lambda q, h, b: ("submit", "SELECT SUM(amount) FROM orders WHERE status='urgent'")
    results = [run_episode(_task(), good, ex), run_episode(_task(), bad, ex)]
    m = aggregate(results)
    assert m["n"] == 2 and m["success_rate"] == 0.5 and m["ask_rate"] == 0.5
