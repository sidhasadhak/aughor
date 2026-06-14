"""Hypothesis-cascade calibration harness — the collect → learn → measure → persist loop,
proven deterministically with mocked proxy/oracle (no LLM).
"""
import json
import random

import aughor.agent.calibrate_hypothesis_cascade as cal
import aughor.agent.hypothesis_cascade as hc
from aughor.agent.state import EvidenceScore
from aughor.llm.cascade import CascadeConfig


def _ev(conf: float, verdict: str) -> EvidenceScore:
    return EvidenceScore(hypothesis_id="h", confidence=conf, verdict=verdict, key_finding="k", should_continue=False)


class _Scripted:
    """Returns the next scripted EvidenceScore on each .complete() call."""

    def __init__(self, scores):
        self._scores = list(scores)
        self.i = 0

    def complete(self, system, user, response_model):
        s = self._scores[self.i]
        self.i += 1
        return s


def _synthetic(n: int, seed: int):
    """A calibrated proxy: P(oracle confirms | proxy_conf) = proxy_conf. Returns the examples
    plus the scripted oracle/proxy outputs collect_rows will replay (oracle first, then proxy)."""
    rng = random.Random(seed)
    examples, oracle_out, proxy_out, truth = [], [], [], []
    for i in range(n):
        pc = rng.random()
        confirmed = rng.random() < pc
        examples.append(
            cal.CalibrationExample(
                hypothesis_id=f"h{i}",
                hypothesis_description=f"hypothesis {i}",
                predictions_section="(none)",
                query_results=f"rows for {i}",
            )
        )
        oracle_out.append(_ev(0.9 if confirmed else 0.1, "confirmed" if confirmed else "refuted"))
        proxy_out.append(_ev(pc, "confirmed" if pc >= 0.5 else "refuted"))
        truth.append(confirmed)
    return examples, oracle_out, proxy_out, truth


def test_collect_rows_pairs_proxy_score_with_oracle_label():
    examples, oracle_out, proxy_out, truth = _synthetic(40, seed=1)
    rows = cal.collect_rows(examples, proxy=_Scripted(proxy_out), oracle=_Scripted(oracle_out))
    assert len(rows) == 40
    # each row = (proxy.confidence, oracle.verdict == "confirmed")
    for (score, label), p, t in zip(rows, proxy_out, truth):
        assert score == p.confidence and label == t


def test_calibrate_learns_thresholds_meeting_recall():
    examples, oracle_out, proxy_out, _ = _synthetic(600, seed=2)
    rows = cal.collect_rows(examples, proxy=_Scripted(proxy_out), oracle=_Scripted(oracle_out))
    cfg = CascadeConfig(recall_target=0.9, precision_target=0.85, failure_probability=0.1)
    t, report = cal.calibrate(rows, cfg)
    assert report["heldout"]["recall"] >= cfg.recall_target - 0.05
    assert 0.0 <= report["heldout"]["escalation_rate"] <= 1.0
    assert t.tau_neg <= t.tau_pos


def test_save_load_roundtrip(tmp_path, monkeypatch):
    examples, oracle_out, proxy_out, _ = _synthetic(400, seed=3)
    rows = cal.collect_rows(examples, proxy=_Scripted(proxy_out), oracle=_Scripted(oracle_out))
    t, _ = cal.calibrate(rows)

    p = tmp_path / "hypothesis_cascade.json"
    cal.save_thresholds(t, p)
    # the live loader picks the file up and routes against the learned thresholds
    monkeypatch.setattr(hc, "THRESHOLDS_PATH", p)
    loaded = hc.load_thresholds()
    assert loaded.tau_pos == t.tau_pos and loaded.tau_neg == t.tau_neg
    assert loaded.n_calibration == t.n_calibration


def test_load_corpus_parses_jsonl(tmp_path):
    f = tmp_path / "corpus.jsonl"
    f.write_text(
        "\n".join(
            json.dumps(d)
            for d in [
                {"hypothesis_id": "h1", "hypothesis_description": "a", "query_results": "r1"},
                {"hypothesis_description": "b", "predictions_section": "p", "query_results": "r2"},
            ]
        )
        + "\n\n"  # trailing blank line tolerated
    )
    examples = cal.load_corpus(f)
    assert len(examples) == 2
    assert examples[0].hypothesis_id == "h1" and examples[1].predictions_section == "p"
