#!/usr/bin/env python3
"""Reference-free NL2SQL eval on a REAL database — the plug-and-play test.

TPC-H/DS ship validated answers; a real warehouse doesn't. So we score without
reference SQL, the way you'd have to on any customer database:

  1. AUTO-GENERATE questions — a strong model reads the live schema and proposes
     realistic business questions across a difficulty ladder.
  2. GENERATE SQL through Aughor's full pipeline (twice, for self-consistency).
  3. SCORE three ways, no ground truth needed:
       • execution sanity — runs clean? plausible non-empty result?
       • self-consistency — do two independent generations agree on the answer?
         (the strongest reference-free signal — could become a live confidence score)
       • LLM-as-judge — a DIFFERENT model judges (question, SQL, result, schema).

Generator = coder provider (AUGHOR_CODER_MODEL); judge/author = narrator provider
(a different model) to avoid self-grading bias. Works on ANY connection id.

Usage:
    AUGHOR_LLM_BACKEND=ollama AUGHOR_CODER_MODEL=qwen3-coder-next:cloud \
      .venv/bin/python evals/run_realdb.py --connection c1c664b0 --n 12 --output out.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
from pathlib import Path

_QUESTION_TIMEOUT = 240  # seconds; legit hard questions ran ≤176s, true hangs are minutes+

_REPO = Path(__file__).parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pydantic import BaseModel, Field

from evals.run_tpch import _equiv  # measure-based result comparator (self-consistency)


class _GenQ(BaseModel):
    question: str
    difficulty: str = "medium"
    rationale: str = ""


class _GenQs(BaseModel):
    questions: list[_GenQ] = Field(default_factory=list)


class _Judgment(BaseModel):
    verdict: str = "WRONG"   # CORRECT | PARTIAL | WRONG
    reason: str = ""


def generate_questions(schema: str, n: int):
    """Ask the narrator model to propose realistic business questions for THIS schema."""
    from aughor.llm.provider import get_provider
    system = (
        "You are a senior data analyst exploring a company's analytics warehouse. "
        "Given the schema, propose realistic business questions a stakeholder would ask. "
        "Rules: every question MUST be answerable with a single read-only SQL query over "
        "these tables; span the difficulty ladder (easy aggregates → filtered joins → "
        "multi-join → time-series/window); be specific and unambiguous (name the metric and "
        "any filter/time window); do NOT ask anything needing ML, external data, or columns "
        "not present. Return difficulty as one of easy/medium/hard."
    )
    user = f"SCHEMA:\n{schema[:9000]}\n\nPropose exactly {n} questions."
    res: _GenQs = get_provider("narrator").complete(system=system, user=user, response_model=_GenQs)
    return res.questions[:n]


def judge(question: str, sql: str, columns, rows, schema: str) -> _Judgment:
    """Cross-model judge: is this SQL a correct, complete answer to the question?"""
    from aughor.llm.provider import get_provider
    sample = "\n".join(", ".join(str(v) for v in r) for r in rows[:8]) or "(no rows)"
    system = (
        "You are a meticulous SQL reviewer. Given a business question, the database schema, "
        "the SQL that was generated, and a sample of its result, judge whether the SQL "
        "correctly and completely answers the question. Check: correct tables/columns, correct "
        "joins, correct filters and aggregation, and a sensible result. "
        "Verdict CORRECT (right answer), PARTIAL (mostly right, a minor issue), or WRONG "
        "(wrong table/column/join/filter, or misreads the question). One-sentence reason."
    )
    user = (
        f"SCHEMA (excerpt):\n{schema[:5000]}\n\n"
        f"QUESTION: {question}\n\nGENERATED SQL:\n{sql}\n\n"
        f"RESULT COLUMNS: {', '.join(columns)}\nRESULT SAMPLE:\n{sample}"
    )
    try:
        return get_provider("narrator").complete(system=system, user=user, response_model=_Judgment)
    except Exception as e:
        return _Judgment(verdict="WRONG", reason=f"judge error: {e}")


def _run_sql(db, sql: str):
    """Execute via the connection's own cursor; return (columns, rows, error)."""
    raw = getattr(db, "_conn", None)
    try:
        if raw is not None:
            cur = raw.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, cur.fetchall(), None
        r = db.execute("__realdb_eval__", sql)
        return list(r.columns), list(r.rows), (r.error or None)
    except Exception as e:
        return [], [], str(e)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connection", required=True)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    from aughor.db.connection import open_connection_for
    from evals.run_golden import generate_sql_full_pipeline

    cid = args.connection
    db = open_connection_for(cid)
    schema = db.get_schema()

    print(f"[setup] generating {args.n} questions from the live schema…")
    questions = generate_questions(schema, args.n)
    print(f"[setup] got {len(questions)} questions\n")

    def _process(q):
        sql1 = generate_sql_full_pipeline(q, cid, db)
        sql2 = generate_sql_full_pipeline(q, cid, db)
        c1, r1, e1 = _run_sql(db, sql1)
        c2, r2, e2 = _run_sql(db, sql2)
        executes = e1 is None and bool(sql1)
        consistent = (e1 is None and e2 is None and _equiv(r1, r2) and _equiv(r2, r1)) or \
                     (e1 is not None and e2 is not None)
        jm = judge(q, sql1, c1, r1, schema) if executes else _Judgment(verdict="WRONG", reason=e1 or "no SQL")
        return dict(generated_sql=sql1, executes=executes, exec_error=e1,
                    row_count=len(r1), self_consistent=bool(consistent),
                    judge_verdict=jm.verdict.upper().strip(), judge_reason=jm.reason)

    def _flush():
        if not args.output:
            return
        ex = sum(1 for r in results if r.get("executes"))
        json.dump({"results": results, "summary": {
            "total": len(results), "executes": ex,
            "self_consistent": sum(1 for r in results if r.get("self_consistent")),
            "judge_correct": sum(1 for r in results if r.get("judge_verdict") == "CORRECT"),
            "judge_partial": sum(1 for r in results if r.get("judge_verdict") == "PARTIAL")}},
            open(args.output, "w"), indent=2, default=str)

    results = []
    pool = cf.ThreadPoolExecutor(max_workers=1)
    for i, gq in enumerate(questions, 1):
        rec = {"n": i, "question": gq.question, "difficulty": gq.difficulty}
        t0 = time.time()
        fut = pool.submit(_process, gq.question)
        try:
            # Hard per-question timeout: a runaway generated query (e.g. a
            # cartesian join on a 10M-row table) or a hung model call must not
            # stall the whole run. On timeout, interrupt the DuckDB connection to
            # cancel any in-flight query, then reconnect for the next question.
            rec.update(fut.result(timeout=_QUESTION_TIMEOUT))
        except cf.TimeoutError:
            try:
                raw = getattr(db, "_conn", None)
                if raw is not None:
                    raw.interrupt()
            except Exception:
                pass
            try:
                db = open_connection_for(cid)  # fresh connection — old one may be wedged
            except Exception:
                pass
            rec.update(executes=False, exec_error=f"timeout >{_QUESTION_TIMEOUT}s",
                       judge_verdict="TIMEOUT", judge_reason="exceeded per-question timeout",
                       self_consistent=False)
        except Exception as e:
            rec.update(executes=False, exec_error=str(e)[:200],
                       judge_verdict="WRONG", judge_reason="pipeline error", self_consistent=False)
        rec["latency_s"] = round(time.time() - t0, 1)
        results.append(rec)
        _flush()  # incremental — partial results survive a later hang
        v = rec.get("judge_verdict", "?")
        flags = ("ok" if rec.get("executes") else "ERR") + ("/consistent" if rec.get("self_consistent") else "/varies")
        print(f"  [{i:2}] {v:8} {flags:16} ({rec['latency_s']}s) {gq.difficulty:6} {gq.question[:54]}…")
        if not rec.get("executes"):
            print(f"        {rec.get('exec_error')}")
    pool.shutdown(wait=False)

    n = len(results)
    ex = sum(1 for r in results if r.get("executes"))
    cons = sum(1 for r in results if r.get("self_consistent"))
    cor = sum(1 for r in results if r.get("judge_verdict") == "CORRECT")
    par = sum(1 for r in results if r.get("judge_verdict") == "PARTIAL")
    print("\n" + "=" * 64)
    print(f" REAL DB ({cid})  generator: {os.getenv('AUGHOR_CODER_MODEL','default')}  judge: narrator")
    print(f" Executes cleanly  : {ex}/{n}")
    print(f" Self-consistent   : {cons}/{n}  (2 independent generations agree)")
    print(f" Judge CORRECT     : {cor}/{n}   PARTIAL: {par}/{n}")
    print("=" * 64)

    if args.output:
        json.dump({"results": results, "summary": {
            "total": n, "executes": ex, "self_consistent": cons,
            "judge_correct": cor, "judge_partial": par}},
            open(args.output, "w"), indent=2, default=str)
        print(f"written to {args.output}")


if __name__ == "__main__":
    main()
