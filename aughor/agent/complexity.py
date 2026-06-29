"""Deterministic question-complexity assessment → cost-tiered model routing.

The 2025/2026 text-to-SQL literature converges on **test-time scaling**: allocate
compute by difficulty — a cheap/fast model + single shot for easy questions, the
frontier model (+ the heavier candidate/verify depth) for hard ones (EllieSQL,
SquRL, Agentar-Scale, ReForce's confidence-tiered probing; see
``docs/NL2SQL_WINNING_FORMULA_2026.md``).

Aughor's prior conclusion is that **deterministic guards beat added LLM machinery on a
strong model**, so the assessor here is **deterministic** — explainable keyword / shape
signals over the question (and, when available, the schema-link breadth), not another
model call. It is a pure function, so it is cheap (~µs), reproducible, and unit-testable.

It pays in **cost/latency**, not accuracy past the model ceiling: it never downgrades a
hard question, it only *upgrades the cheap path* for genuinely easy ones, and it leaves
every trust guard untouched. The verdict also carries an ``ambiguous`` flag — the seam a
later clarification step (the BIRD-INTERACT interactive direction) will gate on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from aughor.llm.provider import Role

Tier = Literal["simple", "moderate", "complex"]

# ── Signal lexicons (lowercased, word-boundary matched) ───────────────────────
# Causal / explanatory — the hardest: multi-hypothesis decomposition.
_CAUSAL = (
    "why", "cause", "caused", "causing", "driver", "drivers", "drove", "reason",
    "explain", "root cause", "because", "attribut", "contribut", "impact", "blame",
)
# Comparison / relationship — moderate–hard: cross-sections, correlations.
_COMPARE = (
    "compare", "comparison", "versus", " vs ", " vs.", "difference between",
    "correlat", "relationship", "relate", "associat", "outperform", "underperform",
)
# Aggregation / grouping / ranking — moderate: GROUP BY / windowing.
_AGGREGATE = (
    "by ", "per ", "each ", "breakdown", "break down", "group", "distribution",
    "average", "median", "total", "sum of", "count of", "rank", "top ", "bottom ",
    "highest", "lowest", "most", "least", "share of", "percentage", "ratio", "rate of",
)
# Temporal / trend — moderate: time windows, period-over-period.
_TEMPORAL = (
    "trend", "over time", "month over month", "year over year", "mom", "yoy",
    "growth", "decline", "drop", "increase", "decrease", "change", "since", "last ",
    "previous", "prior", "week", "month", "quarter", "year", "daily", "weekly",
)
# Multi-step / nested — hard: subqueries, sequencing.
_MULTISTEP = (
    "and then", "for each", "of the", "among", "within each", "across all",
    "then ", "first ", "after ", "before ", "as a percentage of", "relative to",
)
# Ambiguity / under-specification markers — gate a clarification (interaction lever).
_VAGUE = (
    "it ", "they ", "them ", "that one", "this one", "those", "these", "recently",
    "lately", "good", "bad", "best", "worst", "better", "soon", "a lot", "performance",
)


def _hits(text: str, lexicon) -> list[str]:
    return [w for w in lexicon if w in text]


@dataclass(frozen=True)
class ComplexityVerdict:
    """The deterministic assessment of a question's difficulty."""
    tier: Tier
    score: float                      # 0.0 (trivial) … 1.0 (hard)
    ambiguous: bool                   # under-specified → a clarification may help
    signals: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"tier": self.tier, "score": round(self.score, 3),
                "ambiguous": self.ambiguous, "signals": self.signals,
                "reasons": self.reasons}


def assess_complexity(question: str, schema_context: str = "") -> ComplexityVerdict:
    """Score a natural-language question's difficulty deterministically.

    ``schema_context`` (optional) lets the breadth of plausibly-relevant tables raise
    the score for wide-schema questions — the schema-linking-at-scale signal — without
    an LLM. Returns a :class:`ComplexityVerdict`."""
    q = (question or "").strip().lower()
    if not q:
        return ComplexityVerdict("simple", 0.0, False, {}, ["empty question"])

    words = re.findall(r"[a-z0-9_]+", q)
    n_words = len(words)

    causal = _hits(q, _CAUSAL)
    compare = _hits(q, _COMPARE)
    aggregate = _hits(q, _AGGREGATE)
    temporal = _hits(q, _TEMPORAL)
    multistep = _hits(q, _MULTISTEP)
    vague = _hits(q, _VAGUE)
    # Conjunctions hint at compound conditions (multiple filters / clauses).
    conjunctions = len(re.findall(r"\b(and|or|but|while|whereas)\b", q))
    # Question marks / clauses.
    clauses = q.count(",") + q.count(";")

    signals = {
        "words": n_words, "causal": len(causal), "compare": len(compare),
        "aggregate": len(aggregate), "temporal": len(temporal),
        "multistep": len(multistep), "conjunctions": conjunctions, "clauses": clauses,
    }

    # ── Weighted score (capped contributions so no single signal dominates) ────
    score = 0.0
    reasons: list[str] = []
    if causal:
        score += 0.45
        reasons.append(f"causal({','.join(causal[:2])})")
    if compare:
        score += 0.20
        reasons.append(f"comparison({len(compare)})")
    if multistep:
        score += 0.20
        reasons.append(f"multi-step({len(multistep)})")
    if aggregate:
        score += min(0.18, 0.06 * len(aggregate))
        reasons.append(f"aggregation({len(aggregate)})")
    if temporal:
        score += min(0.12, 0.04 * len(temporal))
        reasons.append(f"temporal({len(temporal)})")
    score += min(0.10, 0.03 * conjunctions)
    score += min(0.08, 0.04 * clauses)
    if n_words > 25:
        score += 0.10
        reasons.append("long question")
    elif n_words > 15:
        score += 0.05

    # Schema breadth: many plausibly-relevant tables → harder linking. Cheap heuristic
    # over the rendered schema (count tables whose name token appears in the question).
    if schema_context:
        tables = re.findall(r"^TABLE:\s+([\w.]+)", schema_context, re.MULTILINE)
        bare = {t.split(".")[-1].lower() for t in tables}
        hit_tables = sum(1 for t in bare if t and (t in q or t.rstrip("s") in q))
        signals["schema_tables"] = len(bare)
        signals["question_tables"] = hit_tables
        if hit_tables >= 3:
            score += 0.12
            reasons.append(f"{hit_tables} tables referenced")
        elif hit_tables >= 2:
            score += 0.06

    score = max(0.0, min(1.0, score))
    tier: Tier = "simple" if score < 0.30 else ("moderate" if score < 0.65 else "complex")

    # Ambiguity: vague references / under-specification, especially without a concrete
    # anchor (a metric/aggregation or a time window). This is advisory — a later
    # clarification step gates on it; it does not change the cost tier here.
    ambiguous = bool(vague) and not (aggregate or temporal) and n_words < 12
    if ambiguous:
        reasons.append(f"vague({','.join(v.strip() for v in vague[:2])})")

    return ComplexityVerdict(tier, score, ambiguous, signals, reasons)


# ── Routing policy: tier → inference role ─────────────────────────────────────
# The platform's inference plane binds each ROLE to a model (per Org/Workspace/Agent).
# We route by role, not by model name, so the *operator* decides how cheap "fast" is —
# routing simple questions to "fast" is the test-time-scaling lever; nothing downgrades
# a hard question (moderate/complex stay on the frontier "coder" role).
def model_role_for(verdict: "ComplexityVerdict") -> "Role":
    """The inference role a question of this difficulty should generate SQL with."""
    return "fast" if verdict.tier == "simple" else "coder"
