"""Evidence Linker — extract EvidenceClaims from a completed investigation.

Parses the agent's output (AnalysisReport + query_history + ADA phases) and
produces a list of EvidenceClaim objects ready for the ledger.

Design rules:
  - Every key_finding in AnalysisReport becomes one claim.
  - SQL is linked by matching hypothesis_id → query_history.
  - Confidence comes directly from the Finding model (set by the scoring node).
  - data_freshness is set to the investigation's completion timestamp (proxy for
    "how fresh the data was when the claim was made").
  - metric_used is left None unless the claim_text references a known metric
    keyword (a future enrichment step can improve this).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from aughor.evidence.models import EvidenceClaim


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_sql_for_hypothesis(
    hypothesis_id: Optional[str],
    query_history: list[dict],
) -> Optional[str]:
    """Return the most recent SQL for a given hypothesis_id from query_history."""
    if not hypothesis_id or not query_history:
        return None
    for qr in reversed(query_history):
        h = qr.get("hypothesis_id") or qr.get("id") or ""
        if h == hypothesis_id and qr.get("sql"):
            return qr["sql"]
    return None


_METRIC_KEYWORDS = re.compile(
    r'\b(revenue|churn|refund|conversion|mrr|arr|ltv|nps|cac|gmv|aov|retention)\b',
    re.IGNORECASE,
)

def _guess_metric(text: str) -> Optional[str]:
    m = _METRIC_KEYWORDS.search(text)
    return m.group(0).lower() if m else None


# ── Public API ────────────────────────────────────────────────────────────────

def extract_claims_from_report(
    investigation_id: str,
    report: Any,                          # AnalysisReport pydantic model
    query_history: list[dict] | None = None,
    completed_at: Optional[str] = None,
) -> list[EvidenceClaim]:
    """Extract evidence claims from a completed investigation report.

    Args:
        investigation_id: the investigation this report belongs to.
        report:           an AnalysisReport instance (has .key_findings list).
        query_history:    list of QueryResult-like dicts with 'hypothesis_id'
                          and 'sql' fields, used to link SQL provenance.
        completed_at:     ISO timestamp used as data_freshness proxy.

    Returns:
        list of EvidenceClaim objects (not yet persisted — caller must call
        store.append_claim for each).
    """
    if report is None:
        return []

    findings = getattr(report, "key_findings", None) or []
    qh = query_history or []
    claims: list[EvidenceClaim] = []

    for finding in findings:
        # Finding can be a pydantic model or a dict
        if isinstance(finding, dict):
            claim_text   = finding.get("claim") or finding.get("claim_text") or ""
            confidence   = float(finding.get("confidence") or 0.5)
            hypothesis_id = finding.get("hypothesis_id")
        else:
            claim_text   = getattr(finding, "claim", "") or getattr(finding, "claim_text", "")
            confidence   = float(getattr(finding, "confidence", 0.5))
            hypothesis_id = getattr(finding, "hypothesis_id", None)

        if not claim_text.strip():
            continue

        claims.append(EvidenceClaim(
            investigation_id=investigation_id,
            hypothesis_id=hypothesis_id,
            claim_text=claim_text.strip(),
            sql_source=_find_sql_for_hypothesis(hypothesis_id, qh),
            metric_used=_guess_metric(claim_text),
            data_freshness=completed_at,
            confidence=min(max(confidence, 0.0), 1.0),
        ))

    return claims


def extract_claims_from_ada_phases(
    investigation_id: str,
    phases: list[dict],
    completed_at: Optional[str] = None,
) -> list[EvidenceClaim]:
    """Extract claims directly from ADA investigation_phases (richer provenance).

    Each phase finding with an interpretation becomes a claim.  The SQL is
    taken directly from the finding dict (not inferred from hypothesis_id).
    """
    claims: list[EvidenceClaim] = []
    for phase in phases:
        phase_id = phase.get("phase_id") or ""
        for finding in phase.get("findings") or []:
            interp = finding.get("interpretation") or ""
            if not interp or finding.get("error"):
                continue

            sql = finding.get("sql") or None
            confidence = 0.8 if finding.get("is_significant") else 0.5

            # Build a concise claim text from the title + first sentence of interpretation
            title = finding.get("title") or ""
            first_sentence = (interp.split(".")[0] + ".").strip()
            claim_text = f"{title}: {first_sentence}" if title else first_sentence

            claims.append(EvidenceClaim(
                investigation_id=investigation_id,
                hypothesis_id=phase_id,
                claim_text=claim_text[:500],
                sql_source=sql,
                metric_used=_guess_metric(claim_text),
                data_freshness=completed_at,
                confidence=confidence,
            ))

    return claims
