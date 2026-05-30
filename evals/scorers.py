"""Custom Braintrust scorers for Aughor investigation quality.

Three metrics:
  verdict_accuracy   — did the agent identify the expected root cause?
  query_efficiency   — did it reach a verdict in ≤8 queries?
  hallucination_rate — are all key_findings backed by a real hypothesis_id?

All functions are importable without braintrust/autoevals installed.
"""
from __future__ import annotations


# ── verdict_accuracy ──────────────────────────────────────────────────────────

def verdict_accuracy(output: dict | None, expected: dict, **kwargs) -> dict:
    """Score how well the agent identified the expected root cause.

    Scoring:
      1.0 — headline/findings contain ≥2 expected keywords
      0.5 — contains exactly 1 expected keyword
      0.0 — no keyword match or no output
    """
    if not output:
        return {"name": "verdict_accuracy", "score": 0.0, "metadata": {"keyword_matches": 0}}

    keywords = [k.lower() for k in (expected.get("expected_top_hypothesis_keywords") or [])]
    if not keywords:
        # No keywords to match — give benefit of the doubt if output exists
        return {"name": "verdict_accuracy", "score": 0.5, "metadata": {"keyword_matches": 0}}

    # Search headline, verdict prose, and all finding claims
    text = " ".join([
        output.get("headline", ""),
        output.get("verdict", ""),
        " ".join(f.get("claim", "") for f in (output.get("key_findings") or [])),
        " ".join(output.get("what_is_not_the_cause") or []),
    ]).lower()

    matches = sum(1 for kw in keywords if kw in text)
    if matches >= 2:
        score = 1.0
    elif matches == 1:
        score = 0.5
    else:
        score = 0.0

    return {"name": "verdict_accuracy", "score": score, "metadata": {"keyword_matches": matches}}


# ── query_efficiency ──────────────────────────────────────────────────────────

def query_efficiency(
    output: dict | None,
    expected: dict,
    metadata: dict | None = None,
    **kwargs,
) -> dict:
    """Score how efficiently the agent reached a verdict.

    Scoring:
      1.0  — ≤8 queries (target)
      0.75 — ≤12 queries (acceptable)
      0.25 — ≤20 queries (over budget)
      0.0  — >20 queries
    """
    query_count = (metadata or {}).get("query_count", 0)

    if query_count <= 8:
        score = 1.0
    elif query_count <= 12:
        score = 0.75
    elif query_count <= 20:
        score = 0.25
    else:
        score = 0.0

    return {
        "name": "query_efficiency",
        "score": score,
        "metadata": {"query_count": query_count},
    }


# ── hallucination_rate ────────────────────────────────────────────────────────

def hallucination_rate(output: dict | None, expected: dict, **kwargs) -> dict:
    """Score citation coverage of key findings.

    Every Finding in key_findings must have a non-null hypothesis_id that
    maps to a real executed query. Score = cited / total findings.

    Score 1.0 when all findings are cited (target: 0% hallucination).
    Score 1.0 when there are no findings (nothing to hallucinate).
    """
    if not output:
        return {"name": "hallucination_rate", "score": 1.0, "metadata": {"cited": 0, "total": 0}}

    findings = output.get("key_findings") or []
    if not findings:
        return {"name": "hallucination_rate", "score": 1.0, "metadata": {"cited": 0, "total": 0}}

    cited = sum(1 for f in findings if f.get("hypothesis_id"))
    score = cited / len(findings)

    return {
        "name": "hallucination_rate",
        "score": score,
        "metadata": {"cited": cited, "total": len(findings)},
    }
