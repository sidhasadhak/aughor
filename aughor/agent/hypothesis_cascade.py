"""Cascade-aware hypothesis scoring — run the cheap proxy first, escalate only the
ambiguous verdicts to the full ``coder`` model.

``EvidenceScore.confidence`` is *"0 = fully refuted, 1 = fully confirmed"*, so a clear-cut
verdict (near 0 or 1) is a safe accept and the inconclusive middle escalates. The cheap
model's self-reported confidence is the cascade proxy score — no token logprobs needed.

Opt-in via ``AUGHOR_CASCADE_HYPOTHESIS=1`` until thresholds are calibrated on a real corpus;
default-off keeps ``score_evidence`` on the oracle, behaving exactly as before. Any proxy
failure falls back to the oracle, so the cascade is never worse than today.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from aughor.agent.state import EvidenceScore
from aughor.llm.cascade import CascadeThresholds, default_thresholds, route
from aughor.llm.provider import get_provider, get_proxy_provider

logger = logging.getLogger(__name__)

_THRESHOLDS_PATH = Path(__file__).parent.parent.parent / "data" / "hypothesis_cascade.json"


def cascade_enabled() -> bool:
    return os.getenv("AUGHOR_CASCADE_HYPOTHESIS", "").strip().lower() in ("1", "true", "yes", "on")


def load_thresholds() -> CascadeThresholds:
    """Learned thresholds from ``data/hypothesis_cascade.json`` if a calibration has been run,
    else a conservative uncalibrated default."""
    try:
        if _THRESHOLDS_PATH.exists():
            d = json.loads(_THRESHOLDS_PATH.read_text())
            return CascadeThresholds(
                tau_pos=float(d["tau_pos"]),
                tau_neg=float(d["tau_neg"]),
                n_calibration=int(d.get("n_calibration", 0)),
                sample_recall=float(d.get("sample_recall", float("nan"))),
                sample_precision=float(d.get("sample_precision", float("nan"))),
                escalation_rate=float(d.get("escalation_rate", float("nan"))),
            )
    except Exception:
        logger.warning("hypothesis_cascade: unreadable thresholds file, using default", exc_info=True)
    return default_thresholds()


def score_evidence_cascade(system: str, user: str) -> tuple[EvidenceScore, str]:
    """Return ``(EvidenceScore, resolved_by)`` with ``resolved_by ∈ {"proxy","oracle"}``.

    Disabled → exactly the original oracle call. Enabled → the cheap proxy scores first and
    only an ambiguous verdict escalates to the oracle. A proxy failure falls back to the
    oracle (fail-safe)."""
    def oracle() -> EvidenceScore:
        return get_provider("coder").complete(system=system, user=user, response_model=EvidenceScore)

    if not cascade_enabled():
        return oracle(), "oracle"

    try:
        cheap = get_proxy_provider().complete(system=system, user=user, response_model=EvidenceScore)
    except Exception:
        logger.warning("hypothesis_cascade: proxy failed, falling back to oracle", exc_info=True)
        return oracle(), "oracle"

    if route(cheap.confidence, load_thresholds()) == "escalate":
        return oracle(), "oracle"
    return cheap, "proxy"
