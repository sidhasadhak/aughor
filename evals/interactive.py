"""Interactive eval harness — measure an NL2SQL system's *interaction* skill, not just single-turn EX.

Motivated by BIRD-INTERACT (Huo et al., ICLR 2026 Oral, arXiv 2510.05318): real database work is a
multi-turn dialogue — ambiguous first request, clarification, error recovery, evolving follow-ups —
and frontier models are terrible at it (GPT-5 ~8.67%/17%). Crucially, prior multi-turn benchmarks
replay *static* transcripts, so they cannot reward a system that interacts *well* or penalize one that
guesses. This harness fixes that with a **function-driven user simulator** that responds to whatever
the system actually asks, and an **episode runner** that scores the system's *submitted* SQL against
executable gold — so good clarification is rewarded and blind guessing is penalized.

It is the measurement substrate for Aughor's interactive axis — Phase 2 of the unified-answer-path arc
(``docs/UNIFIED_ANSWER_PATH.md``), built **before** the ask-vs-guess clarification feature (Phase 3)
per the discipline proven across the Spider2 work (*let evidence pick the lever*): the harness exists
first so the clarification feature is measurable from day one, and the never-asks baseline tells us how
much ambiguity is actually costing today.

Design (following BIRD-INTERACT's function-driven simulator):
  * The simulator maps each system request to one of three symbolic actions — AMB (answer a
    pre-annotated ambiguity), LOC (a non-revealing schema-level locating hint), UNA (**reject** an
    attempt to elicit the answer) — then responds. This keeps it controllable and, critically,
    prevents ground-truth leakage (the UNA guard + a scrub that never echoes the gold SQL).
  * Clarification is BUDGET-constrained (τ = m_amb + patience); a system that won't commit fails.

Connecting to Aughor's *real* pipeline — the leverage seam Phase 3 plugs into:
  * ``single_shot_system(generate_fn)`` baselines the current never-asks behaviour.
  * ``clarifying_system(generate_fn, should_ask_fn)`` is the ask-vs-guess system; ``should_ask_fn``
    is the decision Phase 3 owns. ``complexity_should_ask`` backs it with Aughor's own deterministic
    ``assess_complexity(...).ambiguous`` signal, so the harness exercises the real router decision.

Pure except for injected callables (``system_fn``, ``execute_fn``), so the core is fully unit-testable
offline; ``generate_fn``/``execute_fn`` bind to the real LLM + DB for a live baseline run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import sqlglot
from sqlglot import exp

# system_fn(question, history, budget_remaining) -> ("ask", text) | ("submit", sql)
SystemFn = Callable[[str, list, int], tuple]
ExecuteFn = Callable[[str], tuple]          # (sql) -> (ok, rows, error)
ParseFn = Callable[[str], str]              # (request) -> "AMB" | "LOC" | "UNA"
ShouldAskFn = Callable[[str, list], bool]   # (question, history) -> ask?

AMB, LOC, UNA = "AMB", "LOC", "UNA"

_ELICIT_PATTERNS = (
    "the answer", "gold", "correct sql", "correct query", "the right query", "expected result",
    "what is the sql", "give me the query", "give me the sql", "tell me the result",
    "what should the output", "what's the output", "what is the output", "ground truth",
)


@dataclass
class Ambiguity:
    """A pre-annotated ambiguity in the user's request and the clarification to give when asked."""
    key: str                 # the ambiguous term/phrase, e.g. "urgent care"
    clarification: str       # what the user means, e.g. "urgent = status='priority'"


@dataclass
class InteractiveTask:
    instance_id: str
    question: str            # the ambiguous user request (what the system sees)
    gold_sql: str            # ground truth — used by simulator + scorer, NEVER exposed to the system
    ambiguities: list = field(default_factory=list)   # list[Ambiguity]
    clarification_budget: int = 2                       # τ = m_amb + patience


@dataclass
class SimResponse:
    action: str              # AMB | LOC | UNA
    text: str
    leak_blocked: bool = False


@dataclass
class EpisodeResult:
    instance_id: str
    success: bool
    asked: bool
    turns: int
    n_asks: int
    resolved_all: bool
    leak_blocked: int
    budget_used: int


# ── result scoring (order-insensitive, float-tolerant ~ abs_tol 1e-2) ─────────────

def _norm_cell(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return str(v)


def _results_match(a, b) -> bool:
    sa = sorted(tuple(_norm_cell(c) for c in row) for row in (a or []))
    sb = sorted(tuple(_norm_cell(c) for c in row) for row in (b or []))
    return sa == sb


def _tables_of(sql: str) -> set:
    try:
        tree = sqlglot.parse_one(sql)
    except Exception:
        return set()
    return {t.name for t in tree.find_all(exp.Table)} if tree is not None else set()


def _scrub(text: str, gold_sql: str) -> str:
    """Never let a simulator response echo the gold SQL (anti-leak backstop)."""
    g = " ".join(gold_sql.split()).lower()
    if g and g in " ".join(text.split()).lower():
        return "[redacted to avoid leaking the answer]"
    return text


class FunctionDrivenSimulator:
    """Responds to whatever the system asks, mapping each request to AMB / LOC / UNA then answering.
    Controllable and leak-proof: only pre-annotated ambiguities are explained, answer-elicitation is
    rejected, and every response is scrubbed of the gold SQL."""

    def __init__(self, task: InteractiveTask, parse_fn: Optional[ParseFn] = None):
        self.task = task
        self.parse_fn = parse_fn
        self._gold_tables = _tables_of(task.gold_sql)
        self._resolved: set = set()

    def all_resolved(self) -> bool:
        return all(a.key in self._resolved for a in self.task.ambiguities) if self.task.ambiguities else True

    def _classify(self, request: str) -> str:
        if self.parse_fn:
            a = (self.parse_fn(request) or "").upper()
            if a in (AMB, LOC, UNA):
                return a
        r = request.lower()
        if any(p in r for p in _ELICIT_PATTERNS):
            return UNA
        for amb in self.task.ambiguities:
            if amb.key.lower() in r and amb.key not in self._resolved:
                return AMB
        return LOC

    def respond(self, request: str) -> SimResponse:
        action = self._classify(request)
        if action == UNA:
            return SimResponse(UNA, "I can't reveal the expected answer or query — ask about your "
                                    "own intent or the data instead.", leak_blocked=True)
        if action == AMB:
            for amb in self.task.ambiguities:
                if amb.key.lower() in request.lower() and amb.key not in self._resolved:
                    self._resolved.add(amb.key)
                    return SimResponse(AMB, _scrub(amb.clarification, self.task.gold_sql))
        # LOC: a non-revealing, schema-level locating hint (tables the system could see anyway).
        hint = ("Relevant tables: " + ", ".join(sorted(self._gold_tables))) if self._gold_tables \
            else "Please specify which columns or filters you mean."
        return SimResponse(LOC, _scrub(hint, self.task.gold_sql))


def run_episode(task: InteractiveTask, system_fn: SystemFn, execute_fn: ExecuteFn,
                *, parse_fn: Optional[ParseFn] = None, hard_turn_cap: int = 12) -> EpisodeResult:
    """Drive one system through ask/submit under the clarification budget, scoring the submitted SQL
    against gold. A system that asks past budget or never commits fails (the hard cap protects us)."""
    sim = FunctionDrivenSimulator(task, parse_fn)
    history: list = []
    budget = task.clarification_budget
    asked = n_asks = leak_blocked = turns = 0

    while turns < hard_turn_cap:
        turns += 1
        kind, payload = system_fn(task.question, list(history), budget)
        if kind == "ask":
            if budget <= 0:
                history.append(("system", "[ask ignored: clarification budget exhausted]"))
                continue
            resp = sim.respond(payload)
            n_asks += 1
            asked = 1
            budget -= 1
            if resp.leak_blocked:
                leak_blocked += 1
            history.append(("user", resp.text))
        elif kind == "submit":
            ok_c, rows_c, _ = execute_fn(payload)
            ok_g, rows_g, _ = execute_fn(task.gold_sql)
            success = bool(ok_c and ok_g and _results_match(rows_c, rows_g))
            return EpisodeResult(task.instance_id, success, bool(asked), turns, n_asks,
                                 sim.all_resolved(), leak_blocked, task.clarification_budget - budget)
        else:
            break
    return EpisodeResult(task.instance_id, False, bool(asked), turns, n_asks,
                         sim.all_resolved(), leak_blocked, task.clarification_budget - budget)


# ── systems-under-test ────────────────────────────────────────────────────────

def _ctx_with_clarifications(question: str, history: list) -> str:
    ctx = question
    for role, text in history:
        if role == "user":
            ctx += f"\n[clarification] {text}"
    return ctx


def single_shot_system(generate_fn: Callable[[str], str]) -> SystemFn:
    """Wrap a single-shot NL→SQL generator (e.g. Aughor's current pipeline) as a never-asks system,
    to baseline how much ambiguity costs when the system never clarifies. Received clarifications (if
    any) are appended as context, but a single-shot system characteristically does not seek them."""
    def system_fn(question: str, history: list, budget: int) -> tuple:
        return ("submit", generate_fn(_ctx_with_clarifications(question, history)))
    return system_fn


def clarifying_system(generate_fn: Callable[[str], str], should_ask_fn: ShouldAskFn,
                      *, max_asks: int = 1) -> SystemFn:
    """The ask-vs-guess system: when ``should_ask_fn`` says the request is materially ambiguous (and a
    clarification budget remains, up to ``max_asks``), ask one targeted question instead of guessing;
    otherwise submit, folding any clarifications already received into the generation context.

    ``should_ask_fn`` is the decision **Phase 3 owns** — this harness is how that decision is measured.
    The clarification request includes the question text so the function-driven simulator can match a
    pre-annotated ambiguity (and so a real LLM clarifier reads as on-topic)."""
    def system_fn(question: str, history: list, budget: int) -> tuple:
        n_user = sum(1 for role, _ in history if role == "user")
        if n_user < max_asks and budget > 0 and should_ask_fn(question, history):
            return ("ask", f"Could you clarify your request so I answer precisely: {question}")
        return ("submit", generate_fn(_ctx_with_clarifications(question, history)))
    return system_fn


def complexity_should_ask(question: str, history: list) -> bool:
    """A ``should_ask_fn`` backed by Aughor's own deterministic ambiguity signal — ask once when the
    question is under-specified and no clarification has landed yet. This is the real seam Phase 3
    refines (e.g. gating on SOMA candidate-disagreement materiality on top of the ``ambiguous`` flag)."""
    from aughor.agent.complexity import assess_complexity
    if any(role == "user" for role, _ in history):
        return False
    return assess_complexity(question).ambiguous


def aggregate(results: list) -> dict:
    """Interaction metrics over a set of episodes."""
    n = len(results)
    if not n:
        return {}
    return {
        "n": n,
        "success_rate": sum(r.success for r in results) / n,
        "ask_rate": sum(r.asked for r in results) / n,
        "avg_turns": sum(r.turns for r in results) / n,
        "clarification_resolution_rate": sum(r.resolved_all for r in results) / n,
        "avg_budget_used": sum(r.budget_used for r in results) / n,
        "leak_attempts_blocked": sum(r.leak_blocked for r in results),
    }
