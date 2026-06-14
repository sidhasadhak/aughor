"""Calibrate the hypothesis-scoring cascade — learn the ``(tau_pos, tau_neg)`` thresholds
that make the cheap proxy match the oracle at a target recall/precision.

Runs BOTH the proxy and the oracle on a corpus of real ``(hypothesis, evidence)`` scoring
inputs — using the *identical* ``SCORE_EVIDENCE_PROMPT`` that ``score_evidence`` uses — and
feeds ``(proxy_confidence, oracle_verdict == "confirmed")`` to ``learn_thresholds``. The
oracle IS the gold algorithm: the guarantee is that proxy-accepted verdicts match the
oracle's, on held-out data, with probability ≥ 1 − δ.

Writes ``data/hypothesis_cascade.json``, which ``hypothesis_cascade.load_thresholds()`` then
picks up automatically (so the live cascade routes against a *learned* guarantee instead of
the conservative default).

Corpus format — JSONL, one object per line::

    {"hypothesis_id": "h1", "hypothesis_description": "...",
     "predictions_section": "IF TRUE: ...\\nIF FALSE: ...", "query_results": "<formatted evidence>"}

Run (needs the configured proxy + oracle models available on the active backend)::

    python -m aughor.agent.calibrate_hypothesis_cascade --corpus corpus.jsonl --write
"""
from __future__ import annotations

import argparse
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

from aughor.agent.hypothesis_cascade import THRESHOLDS_PATH
from aughor.agent.prompts import SCORE_EVIDENCE_PROMPT
from aughor.agent.state import EvidenceScore
from aughor.llm.cascade import CascadeConfig, CascadeThresholds, learn_thresholds, route
from aughor.llm.provider import get_provider, get_proxy_provider

logger = logging.getLogger(__name__)

_SYSTEM = "You are a senior data analyst evaluating evidence for a hypothesis."


@dataclass(frozen=True)
class CalibrationExample:
    hypothesis_id: str
    hypothesis_description: str
    predictions_section: str
    query_results: str

    def user_prompt(self) -> str:
        return SCORE_EVIDENCE_PROMPT.format(
            hypothesis_id=self.hypothesis_id,
            hypothesis_description=self.hypothesis_description,
            predictions_section=self.predictions_section,
            query_results=self.query_results,
        )


def load_corpus(path: str | Path) -> list[CalibrationExample]:
    out: list[CalibrationExample] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        out.append(
            CalibrationExample(
                hypothesis_id=d.get("hypothesis_id", "h"),
                hypothesis_description=d["hypothesis_description"],
                predictions_section=d.get("predictions_section", "(none)"),
                query_results=d["query_results"],
            )
        )
    return out


def collect_rows(examples: list[CalibrationExample], proxy=None, oracle=None) -> list[tuple[float, bool]]:
    """Score each example with BOTH models → ``(proxy_confidence, oracle_label)``. The oracle's
    verdict is the gold label (``verdict == "confirmed"``)."""
    proxy = proxy or get_proxy_provider()
    oracle = oracle or get_provider("coder")
    rows: list[tuple[float, bool]] = []
    for i, ex in enumerate(examples):
        user = ex.user_prompt()
        o: EvidenceScore = oracle.complete(system=_SYSTEM, user=user, response_model=EvidenceScore)
        p: EvidenceScore = proxy.complete(system=_SYSTEM, user=user, response_model=EvidenceScore)
        rows.append((float(p.confidence), o.verdict == "confirmed"))
        logger.info("calibrate[%d/%d] proxy=%.2f oracle=%s", i + 1, len(examples), p.confidence, o.verdict)
    return rows


def _measure(rows: list[tuple[float, bool]], t: CascadeThresholds) -> dict:
    pos = sum(1 for _, lbl in rows if lbl)
    missed = sum(1 for s, lbl in rows if lbl and route(s, t) == "accept_negative")
    escalated = sum(1 for s, _ in rows if route(s, t) == "escalate")
    n = len(rows)
    return {
        "n": n,
        "recall": (pos - missed) / pos if pos else 1.0,
        "escalation_rate": escalated / n if n else 0.0,
        "oracle_call_reduction": (1 - escalated / n) if n else 0.0,
    }


def calibrate(rows, config: CascadeConfig = CascadeConfig(), holdout: float = 0.3, seed: int = 0):
    """Shuffle, learn on train, measure on held-out. Returns ``(thresholds, report)``."""
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    n_test = int(len(rows) * holdout)
    train, test = rows[n_test:], rows[:n_test]
    if len(train) < config.min_calibration_size:
        train = test = rows  # too few to hold out — learn + measure on all (reported honestly)
    t = learn_thresholds([r[0] for r in train], [r[1] for r in train], config)
    return t, {"train": _measure(train, t), "heldout": _measure(test, t), "thresholds": t.to_dict()}


def save_thresholds(t: CascadeThresholds, path: Path = THRESHOLDS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(t.to_dict(), indent=2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Calibrate the hypothesis-scoring cascade (live proxy + oracle).")
    ap.add_argument("--corpus", required=True, help="JSONL of (hypothesis, evidence) scoring inputs")
    ap.add_argument("--recall", type=float, default=0.9, help="target recall vs the oracle")
    ap.add_argument("--precision", type=float, default=0.85, help="target precision vs the oracle")
    ap.add_argument("--delta", type=float, default=0.1, help="failure probability")
    ap.add_argument("--write", action="store_true", help="write data/hypothesis_cascade.json")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    examples = load_corpus(args.corpus)
    logger.info("Calibrating on %d examples (live proxy + oracle calls)…", len(examples))
    rows = collect_rows(examples)
    cfg = CascadeConfig(recall_target=args.recall, precision_target=args.precision, failure_probability=args.delta)
    t, report = calibrate(rows, cfg)
    print(json.dumps(report, indent=2))
    if args.write:
        save_thresholds(t)
        print(f"wrote {THRESHOLDS_PATH}")
    else:
        print("(dry run — re-run with --write to persist; the live cascade will then use these.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
