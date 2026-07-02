"""SOMA candidate-disagreement — execution-grounded detection of STRUCTURAL ambiguity.

3b of the unified-answer-path arc (``docs/UNIFIED_ANSWER_PATH.md``), greenlit by the measurement chain:
the deterministic clarify detector (``aughor/agent/clarify.py``) is blind to *structural* ambiguity —
a question with two reasonable SQL readings that diverge, carrying no vague pronoun and no subjective
qualifier ("top products" units vs revenue; "average order value" per-order vs sum/count). The
``evals/ambiguity_eval`` + ``evals/its_structural`` runs proved the gap is real (0/6 detected) and that
asking recovers correctness on divergent cases (0/3 → 3/3).

The idea (from SOMA-SQL): generate a few **candidate interpretations**, execute them, and ask **only
when their results materially diverge** — execution is the arbiter, so we never ask about a question
whose readings happen to agree, and the candidate *labels* become grounded option chips. This is LLM
machinery, so it is deliberately gated: only on **structural-suspect** turns the cheap deterministic
detector left quiet, behind ``AUGHOR_SOMA_CLARIFY``, fail-open.

The core (``assess_structural_ambiguity``) is pure — candidates and the executor are injected — so it is
unit-testable without an LLM or a database; the live candidate generator + wiring are thin adapters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# ── Structural-suspect filter — the cheap gate before the expensive probe ─────
# A ranking / superlative, or a known measure-ambiguous metric, with NO explicit measure binding
# ("by revenue", "per order"): the question names *what* to rank/measure but not *how*.
_SUPERLATIVE = (
    "top", "best", "biggest", "largest", "smallest", "highest", "lowest", "worst",
    "most", "least", "leading", "greatest",
)
_AMBIG_METRIC = (
    "average order value", "aov", "conversion rate", "growth", "churn rate",
    "retention rate", "best month", "best day", "best week",
)
_BINDING = re.compile(r"\bby\s+\w|\bper\s+\w|>=|<=|\bas a (share|percentage|fraction)\b", re.IGNORECASE)


def is_structural_suspect(question: str) -> bool:
    """Cheap, deterministic: could this question hide a structural ambiguity worth the SOMA probe?

    True for "top products" / "biggest customer" / "average order value"; False once the measure is
    bound ("top customers by revenue") or for a plain lookup ("total revenue last month")."""
    q = (question or "").lower()
    if not q.strip() or _BINDING.search(q):
        return False
    has_superlative = any(re.search(rf"\b{re.escape(w)}\b", q) for w in _SUPERLATIVE)
    has_ambig_metric = any(m in q for m in _AMBIG_METRIC)
    return has_superlative or has_ambig_metric


@dataclass(frozen=True)
class CandidateReading:
    """One interpretation of an ambiguous question — a human label + the SQL it implies."""
    label: str
    sql: str


@dataclass(frozen=True)
class SomaVerdict:
    ambiguous: bool
    question: str = ""
    options: list = field(default_factory=list)   # distinct interpretation labels (grounded chips)
    source: str = "structural"
    n_groups: int = 0                              # how many distinct result-groups the candidates fell into

    def to_event(self) -> dict:
        return {"question": self.question, "options": list(self.options),
                "source": self.source, "terms": [], "reason": "the question has multiple readings "
                "that give different answers"}


# ── result signatures (order-insensitive, float-tolerant ~ abs_tol 1e-2) ──────

def _norm_cell(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return str(v)


def _signature(rows) -> tuple:
    """A hashable, order-insensitive fingerprint of a result set (capped so it stays bounded)."""
    norm = [tuple(_norm_cell(c) for c in (r or [])) for r in (rows or [])[:200]]
    return tuple(sorted(norm))


# execute_fn(sql) -> (ok, rows, error)
ExecuteFn = Callable[[str], tuple]


def assess_structural_ambiguity(question: str, candidates, execute_fn: ExecuteFn) -> SomaVerdict:
    """Execute the candidate readings and ask only if their results MATERIALLY diverge.

    Candidates whose SQL errors are dropped. The surviving candidates are grouped by result signature;
    when ≥2 distinct groups remain, the question is structurally ambiguous and each group's label
    becomes a grounded option chip. Pure: ``execute_fn`` is injected."""
    groups: dict = {}   # signature -> the first CandidateReading that produced it
    for c in candidates or []:
        if not getattr(c, "sql", "").strip():
            continue
        try:
            ok, rows, _ = execute_fn(c.sql)
        except Exception:
            continue
        if not ok:
            continue
        sig = _signature(rows)
        groups.setdefault(sig, c)
    distinct = list(groups.values())
    if len(distinct) < 2:
        return SomaVerdict(False, n_groups=len(distinct))
    options = [c.label for c in distinct if c.label][:4]
    return SomaVerdict(
        True,
        question="This could be read a few ways — which did you mean?",
        options=options,
        n_groups=len(distinct),
    )


# ── Live candidate generation (the LLM adapter — only reached on a suspect turn) ──

_SOMA_SYSTEM = (
    "You disambiguate analytics questions. A question can have multiple reasonable interpretations "
    "that compute DIFFERENT answers (e.g. 'top products' by units vs by revenue; 'average order "
    "value' per order line vs per order). List the genuinely-distinct interpretations only — if the "
    "question is unambiguous, return exactly ONE. Each interpretation gets a SHORT label naming how it "
    "differs (e.g. 'by units sold') and a single DuckDB SQL query. Never invent columns."
)


def generate_candidate_readings(question: str, schema: str, *, k: int = 3) -> list:
    """Ask the model for up to ``k`` distinct interpretations of a structural-suspect question.

    Returns ``list[CandidateReading]``. Fail-open: any error yields an empty list (→ no probe)."""
    try:
        from pydantic import BaseModel
        from aughor.llm.provider import get_provider

        class _Reading(BaseModel):
            label: str
            sql: str

        class _Readings(BaseModel):
            readings: list

        llm = get_provider("coder")
        user = (f"SCHEMA:\n{schema}\n\nQUESTION: {question}\n\n"
                f"List up to {k} distinct interpretations (label + DuckDB SQL). One if unambiguous.")
        out = llm.complete(system=_SOMA_SYSTEM, user=user, response_model=_Readings)
        readings = []
        for r in (out.readings or [])[:k]:
            label = (r.get("label") if isinstance(r, dict) else getattr(r, "label", "")) or ""
            sql = (r.get("sql") if isinstance(r, dict) else getattr(r, "sql", "")) or ""
            if sql.strip():
                readings.append(CandidateReading(label.strip(), sql.strip()))
        return readings
    except Exception:
        return []
