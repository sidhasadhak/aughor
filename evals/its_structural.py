"""ITS-outcome run — does ASKING recover correctness on structurally-ambiguous questions?

The final measure-before-trust gate for 3b's SOMA half (``docs/UNIFIED_ANSWER_PATH.md``). The
ambiguity-detection eval (``evals/ambiguity_eval.py``) proved the deterministic detector is BLIND to
*structural* ambiguity (0/6). This run asks the next question: when a structural question's INTENDED
reading diverges from the model's DEFAULT reading, does a clarifying question actually fix the answer?

Method — a real run against Aughor's actual SQL model (no toy generator):
  * Seed a small DuckDB where each structural question's two readings give DIFFERENT answers
    (top product by units vs by revenue; biggest customer by order-count vs by spend; …).
  * For each task, ask the real model to write SQL for (a) the bare question [default] and
    (b) the question + a one-line clarification [asked]; execute both; score whether the INTENDED
    entity appears in the result.
  * Report the default vs asked success rate. A large gap = asking recovers correctness on the
    divergent cases SOMA candidate-disagreement is designed to catch.

Caveat (honest): the tasks are deliberately chosen so intent ≠ the common default — i.e. this measures
the UPSIDE of asking on genuinely-divergent cases (SOMA only asks when candidates diverge). It does not
price the "wasted ask" when the default would already have been right; that cost is one extra turn, not
a wrong answer. Needs LLM creds; run: ``python -m evals.its_structural``.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
from pydantic import BaseModel

_SCHEMA = (
    "TABLE: orders\n"
    "  order_id INT, customer VARCHAR, product VARCHAR, channel VARCHAR,\n"
    "  status VARCHAR, quantity INT, amount DOUBLE, order_date DATE\n"
)

# Seed so each question's two readings diverge:
#   product : gadget = 80 units / $80   ·  jewelry = 2 units / $1000   (units vs revenue)
#   customer: alice  = 8 orders / $80   ·  bob     = 2 orders / $1000  (count vs spend)
#   channel : web    = 8 orders / $80   ·  store   = 2 orders / $1000  (count vs revenue)
def _seed() -> "duckdb.DuckDBPyConnection":
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE orders(order_id INT, customer VARCHAR, product VARCHAR, channel VARCHAR, "
        "status VARCHAR, quantity INT, amount DOUBLE, order_date DATE)"
    )
    rows = []
    for i in range(8):  # gadget / alice / web — many cheap orders
        rows.append((i + 1, "alice", "gadget", "web", "complete", 10, 10.0, "2025-01-10"))
    for i in range(2):  # jewelry / bob / store — few expensive orders
        rows.append((i + 9, "bob", "jewelry", "store", "complete", 1, 500.0, "2025-01-12"))
    con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", rows)
    return con


@dataclass(frozen=True)
class ITSTask:
    question: str
    intended_entity: str   # the answer under the INTENDED reading (diverges from the default)
    clarification: str     # the one-line disambiguation the user would give


TASKS: list[ITSTask] = [
    ITSTask("What is our top product?",      "gadget", "rank products by units sold, not revenue"),
    ITSTask("Who is our biggest customer?",  "alice",  "by the number of orders placed, not total spend"),
    ITSTask("What is our top channel?",      "web",    "by the number of orders, not revenue"),
]


class _Gen(BaseModel):
    sql: str


def _real_generate(ctx: str) -> str:
    """Aughor's real SQL model (the `coder` role + the chat system prompt) over the schema."""
    from aughor.llm.provider import get_provider
    from aughor.agent.prompts import CHAT_SQL_SYSTEM
    llm = get_provider("coder")
    prompt = (f"SCHEMA:\n{_SCHEMA}\n\nQUESTION: {ctx}\n\n"
              "Write ONE DuckDB SQL query that answers the question. Return only the column(s) the "
              "question asks for.")
    return llm.complete(system=CHAT_SQL_SYSTEM, user=prompt, response_model=_Gen).sql


def _hits(con, sql: str, entity: str) -> bool:
    try:
        rows = con.execute(sql).fetchall()
    except Exception:
        return False
    return any(entity.lower() == str(c).lower() for r in rows for c in r)


def run(generate=_real_generate) -> dict:
    con = _seed()
    default_ok = asked_ok = 0
    detail = []
    for t in TASKS:
        d = _hits(con, generate(t.question), t.intended_entity)
        a = _hits(con, generate(f"{t.question} ({t.clarification})"), t.intended_entity)
        default_ok += d
        asked_ok += a
        detail.append((t.question, d, a))
    n = len(TASKS)
    return {"n": n, "default_rate": round(default_ok / n, 2),
            "asked_rate": round(asked_ok / n, 2), "detail": detail}


if __name__ == "__main__":
    r = run()
    print(f"ITS-outcome — structural ambiguity (n={r['n']})")
    print(f"  default (no ask): {int(r['default_rate']*r['n'])}/{r['n']}  ({r['default_rate']:.0%})")
    print(f"  asked (clarified): {int(r['asked_rate']*r['n'])}/{r['n']}  ({r['asked_rate']:.0%})")
    for q, d, a in r["detail"]:
        print(f"    [{'✓' if d else '·'} default | {'✓' if a else '·'} asked]  {q}")
