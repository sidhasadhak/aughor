"""Benchmark suite — gold questions with expected SQL shapes and columns.

Closes the feedback loop: instead of discovering regressions via user reports,
you define expected outputs once and run the suite after any change.

Storage: data/benchmarks_{conn_id}.json

A BenchmarkCase has:
  - question        — the natural-language question
  - expected_cols   — column names the SQL result MUST include (order-insensitive)
  - must_contain    — SQL fragments that MUST appear in the generated query
                      (e.g. "NULLIF", "RANK()", "DATE_TRUNC")
  - must_not_contain — SQL fragments that MUST NOT appear (e.g. "AVG(", "LIMIT")
  - notes           — human description of what this case verifies

Run result: BenchmarkResult per case + aggregate pass/fail count.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BenchmarkCase:
    id:               str
    question:         str
    expected_cols:    list[str]        = field(default_factory=list)
    must_contain:     list[str]        = field(default_factory=list)
    must_not_contain: list[str]        = field(default_factory=list)
    notes:            str              = ""

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "question":         self.question,
            "expected_cols":    self.expected_cols,
            "must_contain":     self.must_contain,
            "must_not_contain": self.must_not_contain,
            "notes":            self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BenchmarkCase":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            question=d.get("question", ""),
            expected_cols=d.get("expected_cols", []),
            must_contain=d.get("must_contain", []),
            must_not_contain=d.get("must_not_contain", []),
            notes=d.get("notes", ""),
        )


@dataclass
class CaseResult:
    case_id:        str
    question:       str
    passed:         bool
    generated_sql:  str          = ""
    actual_cols:    list[str]    = field(default_factory=list)
    failures:       list[str]    = field(default_factory=list)   # what failed
    error:          str          = ""

    def to_dict(self) -> dict:
        return {
            "case_id":       self.case_id,
            "question":      self.question,
            "passed":        self.passed,
            "generated_sql": self.generated_sql,
            "actual_cols":   self.actual_cols,
            "failures":      self.failures,
            "error":         self.error,
        }


@dataclass
class BenchmarkRun:
    connection_id: str
    total:         int
    passed:        int
    failed:        int
    results:       list[CaseResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(self.passed / self.total * 100, 1) if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "total":         self.total,
            "passed":        self.passed,
            "failed":        self.failed,
            "score":         self.score,
            "results":       [r.to_dict() for r in self.results],
        }


# ── Persistence ───────────────────────────────────────────────────────────────

def _path(connection_id: str) -> Path:
    return _DATA_DIR / f"benchmarks_{connection_id}.json"


def load_cases(connection_id: str) -> list[BenchmarkCase]:
    p = _path(connection_id)
    if not p.exists():
        return []
    try:
        return [BenchmarkCase.from_dict(d) for d in json.loads(p.read_text())]
    except Exception:
        return []


def save_cases(connection_id: str, cases: list[BenchmarkCase]) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    _path(connection_id).write_text(
        json.dumps([c.to_dict() for c in cases], indent=2)
    )


def upsert_case(connection_id: str, case: BenchmarkCase) -> BenchmarkCase:
    if not case.id:
        case.id = str(uuid.uuid4())[:8]
    cases = load_cases(connection_id)
    cases = [c for c in cases if c.id != case.id]
    cases.append(case)
    save_cases(connection_id, cases)
    return case


def delete_case(connection_id: str, case_id: str) -> bool:
    cases = load_cases(connection_id)
    before = len(cases)
    cases = [c for c in cases if c.id != case_id]
    if len(cases) == before:
        return False
    save_cases(connection_id, cases)
    return True


# ── Runner ────────────────────────────────────────────────────────────────────

def _evaluate_case(
    case: BenchmarkCase,
    generated_sql: str,
    actual_cols: list[str],
    exec_error: str,
) -> CaseResult:
    failures: list[str] = []

    if exec_error:
        return CaseResult(
            case_id=case.id,
            question=case.question,
            passed=False,
            generated_sql=generated_sql,
            actual_cols=actual_cols,
            failures=[f"Execution error: {exec_error}"],
            error=exec_error,
        )

    # Column check (case-insensitive)
    actual_lower = {c.lower() for c in actual_cols}
    for col in case.expected_cols:
        if col.lower() not in actual_lower:
            failures.append(f"Missing expected column: '{col}'")

    # SQL must_contain
    for fragment in case.must_contain:
        if not re.search(re.escape(fragment), generated_sql, re.IGNORECASE):
            failures.append(f"SQL missing required fragment: '{fragment}'")

    # SQL must_not_contain
    for fragment in case.must_not_contain:
        if re.search(re.escape(fragment), generated_sql, re.IGNORECASE):
            failures.append(f"SQL contains forbidden fragment: '{fragment}'")

    return CaseResult(
        case_id=case.id,
        question=case.question,
        passed=len(failures) == 0,
        generated_sql=generated_sql,
        actual_cols=actual_cols,
        failures=failures,
    )


def run_benchmarks(connection_id: str) -> BenchmarkRun:
    """Generate SQL for each case, execute it, evaluate against expectations."""
    from aughor.db.connection import open_connection_for
    from aughor.agent.prompts import CHAT_PROMPT, CHAT_SQL_SYSTEM
    from aughor.llm.provider import get_provider
    from pydantic import BaseModel

    class _SQL(BaseModel):
        sql: str
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = []

    cases  = load_cases(connection_id)
    run    = BenchmarkRun(connection_id=connection_id, total=len(cases), passed=0, failed=0)

    if not cases:
        return run

    try:
        db = open_connection_for(connection_id)
    except Exception as e:
        run.failed = len(cases)
        run.results = [
            CaseResult(case_id=c.id, question=c.question, passed=False, error=str(e))
            for c in cases
        ]
        return run

    schema = db.get_schema()
    _schema_name = getattr(db, "_schema_name", None)
    schema_qualifier = (_schema_name or "main") if db.dialect == "duckdb" else (_schema_name or "public")

    for case in cases:
        try:
            prompt = CHAT_PROMPT.format(
                schema=schema,
                history_section="",
                question=case.question,
                schema_qualifier=schema_qualifier,
                kb_patterns_section="",
                conn_kb_section="",
                sql_examples_section="",
                metrics_section="",
                exploration_section="",
                causal_section="",
                document_section="",
            )
            answer: _SQL = get_provider("coder").complete(
                system=CHAT_SQL_SYSTEM, user=prompt, response_model=_SQL,
            )
            result = db.execute("benchmark", answer.sql)
            cr = _evaluate_case(case, answer.sql, result.columns, result.error or "")
        except Exception as e:
            cr = CaseResult(
                case_id=case.id, question=case.question,
                passed=False, error=str(e),
            )

        run.results.append(cr)
        if cr.passed:
            run.passed += 1
        else:
            run.failed += 1

    try:
        db.close()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "benchmark DB close is best-effort; results already collected",
                 counter="benchmarks.db.close")

    return run
