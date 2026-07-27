"""Seed eval cases from a connection's answer receipts — Wave L2's precondition.

L2 has to A/B `graph.readback`, and an A/B needs cases. The suites in this tree held
one and two of them; a pass-rate delta over one case is not a measurement, it is a coin
landing, and J3's rule is that E4 refuses to attribute what it cannot floor-verify. So
before the grid can run honestly, the suite has to exist.

The material is already here: every answer writes a receipt carrying the question, the
executed SQL and the tables it read. This module turns those into cases the same way
E6's "add this run as a test case" does one at a time, in bulk and deterministically —
no LLM, no network.

**What these cases measure, and what they do not.** A receipt records what Aughor
*produced*, not what was *true*. A suite built from receipts therefore measures
CONSISTENCY — does a configuration still reach the answer this connection reached
before — and never correctness. That distinction is load-bearing for L2: it is a valid
axis for "did read-back change the answers", and it would be a lie as an accuracy
number. Cases are tagged ``consistency`` and ``from_receipt`` so a reader cannot
mistake one for verified ground truth, and the suite description says so too.

Selection is deliberately narrow (see :func:`candidate_cases`): a receipt is only
usable as a case if it has a question, executed SQL, and a headline — an abstention or
an error is a real answer but not a reproducible target.
"""
from __future__ import annotations

import re
from typing import Optional

#: Cases carry these so nobody reads a consistency suite as an accuracy suite.
CASE_TAGS = ("consistency", "from_receipt")

_ABSTAIN_MARKERS = (
    "not found in schema", "cannot ", "unable to", "no data", "does not exist",
    "i don't have", "insufficient",
)


def _is_abstention(headline: str) -> bool:
    """An honest 'I looked and there is nothing there' is valuable knowledge (it is a
    finding on the graph) but a poor eval case: it asserts absence, so it passes for
    reasons that have nothing to do with the configuration under test."""
    low = headline.lower()
    return any(m in low for m in _ABSTAIN_MARKERS)


_SQL_KEYWORDS = {
    "select", "from", "where", "group", "order", "by", "join", "left", "right", "inner",
    "outer", "on", "as", "and", "or", "not", "null", "count", "sum", "avg", "min", "max",
    "case", "when", "then", "else", "end", "with", "over", "partition", "limit", "desc",
    "asc", "distinct", "having", "union", "all", "cast", "coalesce", "round", "date",
}


def _tokens(text: str) -> set[str]:
    """Word-ish tokens of 4+ characters, singularized crudely so `returns`/`return`
    match. Four is long enough to skip `the`/`by`/`is` without a stopword list."""
    out = set()
    for w in re.findall(r"[A-Za-z_]{4,}", (text or "").lower()):
        w = w.strip("_")
        out.add(w)
        if w.endswith("s"):
            out.add(w[:-1])
    return out


def _is_self_contained(question: str, sql: str) -> bool:
    """True iff the question names something its own SQL also names.

    A replayed case has no conversation around it, so a question that carried its
    meaning in the previous turn ("Break that down by type", "Investigate this
    finding") is unreproducible — replaying it measures the harness, not the
    configuration under test. Sharing a real identifier with the SQL is a cheap,
    deterministic proxy for "this question stands on its own".

    It is a proxy, not a decision procedure: "Break that down by type" passes when the
    SQL happens to select a `type` column. That is why :func:`seed_suite` yields a
    suite for REVIEW rather than one trusted on sight — the same posture every other
    generated artifact in this program takes.
    """
    return bool(_tokens(question) & (_tokens(sql) - _SQL_KEYWORDS))


def _normalize(sql: str) -> str:
    """Whitespace/case-insensitive key for de-duplication — two receipts whose SQL
    differs only in formatting are the same case, and duplicates would silently weight
    one question more heavily in the pass rate."""
    return re.sub(r"\s+", " ", sql or "").strip().lower()


def candidate_cases(connection_id: str, *, limit: int = 60,
                    org_id: Optional[str] = None) -> list[dict]:
    """Receipts → candidate eval cases, newest first, de-duplicated by SQL.

    Returns dicts shaped for :func:`aughor.evals.store.add_cases`: ``question``, the
    executed SQL as ``artifact``, and ``expected`` carrying the headline and tables so
    a reviewer can see what the case was captured from.
    """
    from aughor.ontology.context_graph_build import load_investigation_findings

    seen: set[str] = set()
    seen_questions: set[str] = set()
    out: list[dict] = []
    # Reuse L1's normalizer rather than re-reading the Ledger with a second shape:
    # one definition of "what a receipt means" for both the graph and the eval plane.
    #
    # But NOT its limit. That cap is the committed graph's size budget; the eval corpus
    # wants every receipt it can get, and inheriting the graph's window silently capped
    # a 628-receipt connection at 100 — newest-first, so eval runs writing their own
    # receipts evicted the older, more varied questions. Read wide here and let the
    # selection rules below do the narrowing, since they narrow for reasons that are
    # about eval quality rather than about JSON file size.
    for rec in load_investigation_findings(connection_id, org_id,
                                           limit=max(limit * 20, 1000)):
        question = str(rec.get("question") or "").strip()
        sql = str(rec.get("sql") or "").strip()
        headline = str(rec.get("text") or "").strip()
        if not question or not sql or not headline:
            continue
        if _is_abstention(headline) or not _is_self_contained(question, sql):
            continue
        key = _normalize(sql)
        if key in seen:
            continue
        # A question whose text recurs with DIFFERENT SQL carried its meaning in
        # context the case cannot replay ("Investigate this finding" — which finding?).
        # Replaying it measures nothing about the configuration under test, so it is
        # dropped rather than left to add noise to the pass rate.
        qkey = question.lower()
        if qkey in seen_questions:
            continue
        seen_questions.add(qkey)
        seen.add(key)
        out.append({
            "question": question,
            "artifact": sql,
            "expected": {"headline": headline, "tables": rec.get("tables") or [],
                         "receipt_id": rec.get("id", "")},
            "tags": list(CASE_TAGS),
        })
        if len(out) >= limit:
            break
    return out


def seed_suite(connection_id: str, *, name: str = "", limit: int = 60,
               org_id: Optional[str] = None) -> dict:
    """Create a consistency suite for a connection from its receipts.

    Returns ``{"suite_id", "added", "candidates"}``. Adds nothing and creates no suite
    when there are no usable receipts — an empty suite would report a perfect pass rate
    over zero cases, which is the most misleading number available.
    """
    from aughor.evals.store import add_cases, create_suite

    cases = candidate_cases(connection_id, limit=limit, org_id=org_id)
    if not cases:
        return {"suite_id": "", "added": 0, "candidates": 0}

    suite = create_suite(
        name or f"{connection_id} — answer consistency (from receipts)",
        description=(
            "Cases captured from this connection's answer receipts. These measure "
            "CONSISTENCY (does a configuration still reach the answer reached before), "
            "NOT correctness: a receipt records what Aughor produced, not what is true. "
            "Do not report a pass rate from this suite as an accuracy number."
        ),
        connection_id=connection_id,
    )
    added = add_cases(suite["id"], cases)
    return {"suite_id": suite["id"], "added": added, "candidates": len(cases)}
