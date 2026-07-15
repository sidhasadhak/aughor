"""Wide-question routing eval — does the deterministic detector send BROAD landscape
questions to the explore wave without poaching real investigations or lookups?

R9 of the Databricks-HAR program unlocks the already-built explore subgraph from the
``/ask`` door: a genuinely broad question — "characterize / profile / map how X varies
across the business" — is answered best by the multi-cut explore wave, not a single ADA
investigation. The routing decision stays **deterministic** (no model in the routing path —
the R4 ablation lesson); ``aughor/agent/ask_router.py: is_wide_question`` is the detector,
gated behind the ``explore.route_wide`` flag.

This is the measure-before-trust gate: label a small set of questions by intent and measure
the router's explore-rate per label. The contract we want:

  * ``wide``        → HIGH explore-rate (the detector fires — that IS the win)
  * ``investigate`` → ZERO explore-rate (a causal 'why' is an investigation, never poached)
  * ``lookup``      → ZERO explore-rate (a direct lookup stays quick)

and, with the flag OFF, ZERO explore-rate everywhere (byte-identical to before R9).

The router is exercised with the flag forced ON (``route_wide=True``) and a benign injected
classifier, so this is pure — no DB, no model. Run: ``python -m evals.route_wide_eval``.
"""
from __future__ import annotations

from dataclasses import dataclass

from aughor.agent.ask_router import decide_ask_route


# A benign classifier for the borderline tiebreak — a non-wide, non-causal moderate question
# should NOT become explore via the classifier here; returning "investigate" keeps the eval
# measuring ONLY the deterministic wide gate, not the (injected) LLM's mood.
def _benign_classifier(question: str):
    class _D:
        confidence = 1.0
        reasoning = "eval stub"
    return "investigate", _D()


# label ∈ {"wide", "investigate", "lookup"}.
#   wide        — broad landscape/characterization/optimization → explore is the answer
#   investigate — causal / driver "why" → a single ADA investigation, must NOT go explore
#   lookup      — a direct, well-specified figure → quick, must NOT go explore
@dataclass(frozen=True)
class RouteTask:
    question: str
    label: str


TASKS: list[RouteTask] = [
    # ── wide: the explore wave should own these ────────────────────────────────
    RouteTask("Give me an overview of the sales landscape", "wide"),
    RouteTask("What are the characteristics of high-value customers?", "wide"),
    RouteTask("Profile our product catalog", "wide"),
    RouteTask("Explore the different customer segments", "wide"),
    RouteTask("What patterns exist across our order data?", "wide"),
    RouteTask("How does conversion vary across channels and regions?", "wide"),
    RouteTask("What factors relate to repeat purchasing?", "wide"),
    RouteTask("What is the optimal discount depth for margin?", "wide"),

    # ── investigate: causal 'why' — must stay an investigation, never explore ───
    RouteTask("Why did revenue drop last week?", "investigate"),
    RouteTask("What is driving the increase in churn?", "investigate"),
    RouteTask("What caused the spike in refunds in March?", "investigate"),
    RouteTask("Explain the decline in average order value", "investigate"),

    # ── lookup: a direct figure — must stay quick, never explore ───────────────
    RouteTask("What is total revenue last month?", "lookup"),
    RouteTask("Show top 10 customers by revenue", "lookup"),
    RouteTask("How many orders were placed yesterday?", "lookup"),
    RouteTask("Count of cancelled orders this week", "lookup"),
]


def _explore_rate(route_wide: bool) -> dict:
    by_type: dict[str, list[bool]] = {}
    for t in TASKS:
        r = decide_ask_route(t.question, classifier=_benign_classifier, route_wide=route_wide)
        is_explore = r.mode == "explore"
        by_type.setdefault(t.label, []).append(is_explore)

    report: dict[str, dict] = {}
    for label, results in by_type.items():
        n = len(results)
        explored = sum(results)
        report[label] = {"n": n, "explored": explored,
                         "rate": round(explored / n if n else 0.0, 2)}
    return report


def run() -> dict:
    """Explore-rate per label with the flag ON and OFF. ``on`` is the live behavior; ``off``
    proves R9 is byte-identical when the flag is disabled."""
    return {"on": _explore_rate(True), "off": _explore_rate(False)}


def _fmt(report: dict) -> str:
    lines = ["wide-question routing eval — deterministic explore gate (R9)"]
    interp = {
        "wide":        "← the win (want HIGH)",
        "investigate": "← must NOT poach investigations (want 0)",
        "lookup":      "← must NOT poach lookups (want 0)",
    }
    for state in ("on", "off"):
        lines.append(f"\nflag {state.upper():<3}   {'label':<12} {'n':>3} {'explored':>9} {'rate':>6}")
        for label in ("wide", "investigate", "lookup"):
            r = report[state].get(label)
            if not r:
                continue
            tail = interp[label] if state == "on" else "← want 0 (byte-identical)"
            lines.append(f"          {label:<12} {r['n']:>3} {r['explored']:>9} {r['rate']:>6}   {tail}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(_fmt(run()))
