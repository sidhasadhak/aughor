"""Ambiguity-detection eval — does the deterministic clarify detector miss real ambiguity?

This is the measure-before-trust gate for 3b (the SOMA execution-grounded clarification half of
the unified-answer-path arc, ``docs/UNIFIED_ANSWER_PATH.md``). Phase 3 ships a deterministic
two-source detector (``aughor/agent/clarify.py: assess_clarification``):

  * Source A — under-specification (the complexity ``ambiguous`` flag).
  * Source B — value/term ambiguity (a subjective-qualifier lexicon).

The open question: is that enough, or do we need SOMA candidate-disagreement (generate N SQL
interpretations, ask when they materially diverge)? This eval answers it by labelling a small set of
questions by ambiguity TYPE and measuring the detector's **recall per type** + its false-positive rate
on well-specified questions.

The decisive type is ``structural`` — a question that is genuinely ambiguous (two reasonable SQL
readings diverge) but carries **no vague pronoun and no subjective qualifier**, so neither
deterministic source can see it. The recall on ``structural`` is the size of the gap SOMA would fill.

Run: ``python -m evals.ambiguity_eval`` (pure — no DB, no model).
"""
from __future__ import annotations

from dataclasses import dataclass

from aughor.agent.clarify import assess_clarification

# label ∈ {"none", "underspecified", "value_term", "structural"}.
#   none          — well-specified; the detector must STAY QUIET (false positive if it asks)
#   underspecified— vague / anchor-less; Source A should catch
#   value_term    — a subjective qualifier implying an unstated filter; Source B should catch
#   structural    — genuinely ambiguous but no pronoun + no qualifier → NEITHER source can catch
#                   (the SOMA candidate-disagreement gap)


@dataclass(frozen=True)
class AmbTask:
    question: str
    label: str


TASKS: list[AmbTask] = [
    # ── none: well-specified, must not ask ─────────────────────────────────────
    AmbTask("What is total revenue last month?", "none"),
    AmbTask("Show top 10 customers by revenue", "none"),
    AmbTask("Revenue by region in Q1 2025", "none"),
    AmbTask("How many orders were placed yesterday?", "none"),
    AmbTask("Average order value by channel over the last 30 days", "none"),
    AmbTask("Count of cancelled orders this week", "none"),

    # ── underspecified: Source A (complexity ambiguous flag) should catch ──────
    AmbTask("How are we doing lately?", "underspecified"),
    AmbTask("Show me the good ones", "underspecified"),
    AmbTask("What's our performance?", "underspecified"),
    AmbTask("Is it growing?", "underspecified"),

    # ── value_term: Source B (subjective-qualifier lexicon) should catch ───────
    AmbTask("Total amount of urgent orders", "value_term"),
    AmbTask("List active customers", "value_term"),
    AmbTask("Revenue from premium accounts", "value_term"),
    AmbTask("How many at-risk customers do we have", "value_term"),

    # ── structural: ambiguous but NO pronoun + NO qualifier → neither catches ──
    AmbTask("What is the average order value?", "structural"),         # AVG(amount) vs SUM/COUNT(order)
    AmbTask("Revenue last quarter", "structural"),                     # calendar Q vs trailing 90 days
    AmbTask("Top products", "structural"),                             # by units or by revenue
    AmbTask("Customer growth", "structural"),                          # new customers vs revenue growth
    AmbTask("What is our conversion rate?", "structural"),             # which numerator / denominator
    AmbTask("Biggest accounts", "structural"),                        # by revenue, count, or size
]


def run() -> dict:
    by_type: dict[str, list[bool]] = {}
    for t in TASKS:
        asked = assess_clarification(t.question).should_ask
        by_type.setdefault(t.label, []).append(asked)

    report: dict[str, dict] = {}
    for label, results in by_type.items():
        n = len(results)
        asked = sum(results)
        # for "none", asking is a false positive; for the others, asking is the desired recall.
        rate = asked / n if n else 0.0
        report[label] = {"n": n, "asked": asked, "rate": round(rate, 2)}
    return report


def _fmt(report: dict) -> str:
    lines = ["ambiguity-detection eval — deterministic two-source detector",
             f"{'type':<16} {'n':>3} {'asked':>6} {'rate':>6}   interpretation"]
    interp = {
        "none":           "← false-positive rate (want LOW)",
        "underspecified": "← Source A recall (want HIGH)",
        "value_term":     "← Source B recall (want HIGH)",
        "structural":     "← the SOMA gap (low = deterministic can't see it)",
    }
    for label in ("none", "underspecified", "value_term", "structural"):
        r = report.get(label)
        if not r:
            continue
        lines.append(f"{label:<16} {r['n']:>3} {r['asked']:>6} {r['rate']:>6}   {interp[label]}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(_fmt(run()))
