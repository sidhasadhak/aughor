"""Diagnose WHY key_question_sql came back mostly empty: dropped indices vs audit failures.
Replays the generator's own batched LLM call + audit, printing raw SQL + per-question reason.
"""
from dotenv import load_dotenv
load_dotenv(".env")

import json
from pydantic import BaseModel, Field

from aughor.db.connection import open_connection_for
from aughor.profile import store as pstore
from aughor.profile.validate import audit_finding_sql
from aughor.tools.schema import _parse_schema_tables
from aughor.llm.provider import get_provider

CID = "8090c60f"
conn = open_connection_for(CID)
schema = conn.get_schema()
table_cols = _parse_schema_tables(schema)
profile = pstore.load(CID)
recipes = pstore.load_recipes(CID)
questions = [q for q in (profile.key_questions or []) if q.strip()]

_rlines = ""
for r in (recipes or [])[:8]:
    _aps = "; ".join((r.get("anti_patterns") or [])[:2])
    _rlines += f"  • {r.get('metric')}: formula={r.get('formula')}; grain={r.get('grain')}; AVOID={_aps}\n"

system = (
    "You are a precise analytics engineer. For each numbered business question, write ONE "
    "runnable DuckDB SELECT that ANSWERS it using only real tables/columns from the schema. "
    "Rules: for a COMPOSITE question compute EACH metric in its OWN CTE keyed by the entity, then JOIN "
    "the CTEs on the entity key and filter in the outer query — NEVER aggregate across a "
    "multi-table join directly (fan-out). Every rate = SUM(numerator)/NULLIF(SUM(denominator),0) "
    "at the correct grain (0..1, never >1). Follow the computation recipes. If a question truly "
    "cannot be answered from the schema, return an empty string for its sql."
)

class _QSql(BaseModel):
    index: int = Field(description="The question number, exactly as given")
    sql: str = Field(description="A runnable SELECT that answers it, or empty if impossible")

class _Out(BaseModel):
    items: list[_QSql]

spec = "\n".join(f"  [{i}] {q}" for i, q in enumerate(questions))
user = f"SCHEMA:\n{schema}\n\nCOMPUTATION RECIPES:\n{_rlines}\n\nQUESTIONS:\n{spec}"
llm = get_provider("coder")
out: _Out = llm.complete(system=system, user=user, response_model=_Out, temperature=0.0)
got = {it.index: (it.sql or "").strip() for it in out.items}

print(f"asked for {len(questions)} questions; model returned {len(out.items)} items "
      f"for indices {sorted(got)}\n")
for i, q in enumerate(questions):
    cand = got.get(i, "")
    if not cand:
        print(f"[{i}] DROPPED (no item / empty) — {q[:70]}")
        continue
    ok, reason = audit_finding_sql(cand, table_cols, conn)
    print(f"[{i}] {'PASS' if ok else 'FAIL: ' + reason[:70]} — {q[:60]}")
    if not ok:
        print(f"      SQL: {cand[:160]}")
