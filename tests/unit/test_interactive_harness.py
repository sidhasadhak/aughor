"""Tests for the interactive eval harness (evals/interactive.py).

Contract: a function-driven user simulator (AMB/LOC/UNA, leak-proof) + an episode runner that scores
SUBMITTED SQL against gold under a clarification budget — so the harness REWARDS good clarification
and PENALIZES blind guessing (the property static-transcript benchmarks lack), and never leaks gold.

Phase-2 additions (the unified-answer-path arc): the ask-vs-guess ``clarifying_system`` and the
``complexity_should_ask`` predicate backed by Aughor's real deterministic ambiguity signal — the seam
the Phase-3 clarification feature is measured against.
"""
from __future__ import annotations

import sqlite3

from evals.interactive import (
    Ambiguity, InteractiveTask, FunctionDrivenSimulator, run_episode, single_shot_system,
    clarifying_system, complexity_should_ask, aggregate,
    AMB, LOC, UNA,
)

GOLD = "SELECT SUM(amount) FROM orders WHERE status='priority'"
WRONG = "SELECT SUM(amount) FROM orders WHERE status='urgent'"


def _task():
    return InteractiveTask(
        instance_id="t1",
        question="total amount of urgent orders",       # 'urgent' is ambiguous
        gold_sql=GOLD,
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
        return ("submit", GOLD)

    res = run_episode(_task(), clarifier, ex)
    assert res.success and res.asked and res.n_asks == 1 and res.resolved_all


def test_guessing_system_fails_without_asking():
    ex = _sqlite_exec()

    def guesser(question, history, budget):
        return ("submit", WRONG)                 # wrong guess → 0 rows

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
    sysfn = single_shot_system(lambda ctx: WRONG)
    res = run_episode(_task(), sysfn, ex)
    assert not res.asked and not res.success


# ── the ask-vs-guess system (the Phase-3 seam) ─────────────────────────────────

def _ambiguity_aware_generate(ctx: str) -> str:
    # Only resolves correctly once the clarification ("priority") is in context — i.e. asking helps.
    return GOLD if "priority" in ctx.lower() else WRONG


def test_clarifying_system_asks_then_resolves_when_signal_fires():
    ex = _sqlite_exec()
    sysfn = clarifying_system(_ambiguity_aware_generate, should_ask_fn=lambda q, h: True, max_asks=1)
    res = run_episode(_task(), sysfn, ex)
    # asked once → simulator resolved 'urgent' → context carried → correct submit
    assert res.asked and res.n_asks == 1 and res.success and res.resolved_all


def test_clarifying_system_respects_max_asks_and_commits():
    ex = _sqlite_exec()
    # should_ask always True, but max_asks=1 forces a commit on the 2nd turn (no infinite asking)
    sysfn = clarifying_system(_ambiguity_aware_generate, should_ask_fn=lambda q, h: True, max_asks=1)
    res = run_episode(_task(), sysfn, ex)
    assert res.n_asks == 1 and res.turns == 2


def test_clarifying_system_does_not_ask_when_signal_is_quiet():
    ex = _sqlite_exec()
    # should_ask False → behaves like single-shot; with a wrong guess it fails, having never asked
    sysfn = clarifying_system(lambda ctx: WRONG, should_ask_fn=lambda q, h: False)
    res = run_episode(_task(), sysfn, ex)
    assert not res.asked and res.n_asks == 0 and not res.success


# ── the real deterministic ambiguity signal feeds the ask decision ─────────────

def test_complexity_should_ask_reflects_real_ambiguous_flag():
    # under-specified question → ask; concrete question → don't (uses assess_complexity)
    assert complexity_should_ask("How is performance lately?", []) is True
    assert complexity_should_ask("What is total revenue?", []) is False


def test_complexity_should_ask_only_asks_once():
    # once a clarification has landed, do not ask again (self-limiting to one targeted question)
    history = [("user", "by performance I mean revenue growth")]
    assert complexity_should_ask("How is performance lately?", history) is False


# ── aggregate metrics ──────────────────────────────────────────────────────────

def test_aggregate_metrics():
    ex = _sqlite_exec()
    good = clarifying_system(_ambiguity_aware_generate, should_ask_fn=lambda q, h: True, max_asks=1)
    bad = single_shot_system(lambda ctx: WRONG)
    results = [run_episode(_task(), good, ex), run_episode(_task(), bad, ex)]
    m = aggregate(results)
    assert m["n"] == 2 and m["success_rate"] == 0.5 and m["ask_rate"] == 0.5
