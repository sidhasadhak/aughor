"""Strategy-diverse candidate generation + execution-signature selection (Levers 4+5).

June's negative result on consensus was SAME-PROMPT k=3 temperature voting (+0.74 at 6×
cost). The variant the repo's own study flagged as "measure-first, never run" is
CHASE-SQL/DivSkill's: candidates from DIFFERENT STRATEGIES (the diversity is engineered,
not sampled), deduped by what they RETURN (execution signature), then selected by
deterministic rules — plurality of result signatures, grain-of-intent conformance as the
tie-breaker, shortest SQL last. June's oracle measurement (~67% on the hardest slice vs
56% single-shot) proves the model produces correct answers single-shot never surfaces —
a selection problem, which this addresses without a judge LLM.

Cost: K calls/question (default 3) — hard-subset use, not blanket.
Wired via `evals/spider2.py --candidates K`; selection is pure + unit-tested offline.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

STRATEGIES: dict[str, str] = {
    "direct": "",  # the baseline prompt as-is
    "decompose": (
        "\nSTRATEGY: Before writing the SQL, decompose the question into its computation "
        "steps as SQL comments (-- step 1: …), then implement them as CTEs in ONE query — "
        "one CTE per step, simple final SELECT.\n"
    ),
    "plan_first": (
        "\nSTRATEGY: First identify (as SQL comments): the exact tables needed, the join "
        "keys (use the declared KEYS & JOIN PATHS), the grain of the answer (one row per "
        "what?), and the filter literals (copy stored values exactly). Then write ONE query "
        "consistent with that plan.\n"
    ),
    "adversarial": (
        "\nSTRATEGY: Write the query, then re-read the question and check your draft for "
        "the three classic errors before answering: (1) wrong aggregation grain (per-X vs "
        "overall), (2) a qualifier misread as a filter (\"players who scored >50 in any "
        "match\" selects WHICH players — it does not restrict WHICH rows you sum), "
        "(3) double-counting across a one-to-many join. Fix what you find; return the "
        "corrected query only.\n"
    ),
}


@dataclass
class Candidate:
    strategy: str
    sql: str
    ok: bool = False
    rows: Optional[list] = None
    signature: str = ""
    grain_ok: bool = True
    error: str = ""


def result_signature(columns: Sequence[str], rows: Optional[list], cap: int = 200) -> str:
    """Order-insensitive fingerprint of WHAT a query returned (not how it was written).
    Two queries with the same signature are the same answer for selection purposes."""
    if rows is None:
        return "ERROR"
    try:
        norm = sorted(
            tuple(str(v)[:40] for v in r) for r in list(rows)[:cap]
        )
        blob = f"{len(rows)}|" + "|".join(",".join(r) for r in norm)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]
    except Exception:
        return "UNHASHABLE"


def select_candidate(cands: list[Candidate]) -> Optional[Candidate]:
    """Deterministic selection — no judge LLM:
    1. executable candidates only;
    2. PLURALITY of execution signatures (two strategies independently reaching the same
       result is evidence);
    3. tie → grain-of-intent-conforming candidates first;
    4. tie → shortest SQL (Occam);
    5. stable order (strategy name) last, so selection is reproducible.
    """
    live = [c for c in cands if c.ok and c.signature not in ("ERROR",)]
    if not live:
        return None
    by_sig: dict[str, list[Candidate]] = {}
    for c in live:
        by_sig.setdefault(c.signature, []).append(c)
    groups = sorted(
        by_sig.values(),
        key=lambda g: (
            -len(g),                                   # plurality
            -sum(1 for c in g if c.grain_ok),          # grain conformance
            min(len(c.sql) for c in g),                # brevity
            min(c.strategy for c in g),                # stability
        ),
    )
    winner = sorted(groups[0], key=lambda c: (not c.grain_ok, len(c.sql), c.strategy))
    return winner[0]


@dataclass
class CandidateRun:
    chosen: Optional[Candidate]
    candidates: list[Candidate] = field(default_factory=list)
    agreed: bool = False   # all live candidates shared one signature
    n_signatures: int = 0


def run_candidates(
    question: str,
    schema: str,
    document_section: str,
    *,
    generate_fn: Callable[[str, str, str], str],   # (question, schema, doc+strategy) -> sql
    execute_fn: Callable[[str], tuple[bool, Optional[list], str]],
    columns_fn: Callable[[str], Sequence[str]],
    grain_check: Optional[Callable[[str, int], Optional[str]]] = None,
    strategies: Optional[Sequence[str]] = None,
) -> CandidateRun:
    """Generate one candidate per strategy, execute, sign, select. Pure orchestration —
    all effects arrive through the callables, so this is unit-testable offline."""
    names = list(strategies or STRATEGIES.keys())
    cands: list[Candidate] = []
    for name in names:
        directive = STRATEGIES.get(name, "")
        try:
            sql = generate_fn(question, schema, document_section + directive)
        except Exception as e:
            cands.append(Candidate(strategy=name, sql="", error=f"gen: {e}"))
            continue
        if not (sql or "").strip():
            cands.append(Candidate(strategy=name, sql="", error="empty"))
            continue
        ok, rows, err = execute_fn(sql)
        sig = result_signature(columns_fn(sql) if ok else [], rows if ok else None)
        grain_ok = True
        if ok and grain_check is not None and isinstance(rows, list):
            grain_ok = grain_check(question, len(rows)) is None
        cands.append(Candidate(strategy=name, sql=sql.strip(), ok=ok, rows=None,
                               signature=sig, grain_ok=grain_ok, error=err or ""))
    chosen = select_candidate(cands)
    sigs = {c.signature for c in cands if c.ok}
    return CandidateRun(chosen=chosen, candidates=cands,
                        agreed=len(sigs) == 1 and bool(sigs), n_signatures=len(sigs))
