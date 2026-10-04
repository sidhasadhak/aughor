#!/usr/bin/env python3
"""PENDING item 12 — would near-matches find what a missed question meant? Measured with no model.

For every item of `framing_matcher_set.jsonl` whose EXACT frame defines nothing, the near-match
candidates (`aughor/ontology/near_match.py`) are computed and scored:
  * a paraphrase item is RECOVERABLE when its gold definition is among the candidates — the most
    the chooser could then pick right;
  * an item whose gold is "no definition" (the controls) is a FALSE CANDIDATE when any candidate
    appears — a question the chooser would be asked to frame that should frame nothing.
Tuned on dev; test measured once. Nothing here answers a question.

Usage: .venv/bin/python evals/framing_near_match_eval.py [--split dev|test|all] [--output out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.framing_matcher_eval import DATASET, load_graphs  # noqa: E402


HELDOUT = REPO / "evals" / "framing_near_match_heldout.jsonl"
#: The four captured graphs the held-out set is asked of.
HELDOUT_GRAPHS = {"lux": "evals/ablation_luxexperience_business_ontology.json",
                  "olist": "evals/ablation_olist_business_ontology.json",
                  "thelook": "evals/ablation_thelook_business_ontology.json",
                  "samples": "evals/ablation_samples_business_ontology.json"}
#: The rule fitted on the DEV split alone (2026-10-04): offer a candidate from this score, and
#: frame without the chooser only when the best leads the next by this much (or stands alone).
RULE_THRESHOLD, RULE_MARGIN = 1.0, 1.0


def heldout(output: str = "") -> int:
    """The held-out set (written and committed before any run on it), measured under the rule
    the dev split fitted: what the finder would frame by itself, what it would hand the chooser,
    and what stays quiet — for reworded questions and for controls that mean nothing declared.
    Each question is read as `agent.framing.resolve_frame` reads it: the ask alone."""
    from aughor.automations.temporal import ask_of
    from aughor.ontology.framing import frame_question
    from aughor.ontology.models import OntologyGraph
    from aughor.ontology.near_match import near_candidates
    graphs = {h: OntologyGraph.model_validate(json.loads((REPO / path).read_text()))
              for h, path in HELDOUT_GRAPHS.items()}
    tally: dict[str, int] = {}
    rows = []
    for it in (json.loads(line) for line in HELDOUT.read_text().splitlines() if line.strip()):
        g, q, gold = graphs[it["host"]], ask_of(it["question"]), it["expect"]["definition"]
        if frame_question(q, g).defines:
            verdict, cands = "exact_matcher_framed", []
        else:
            cands = near_candidates(q, g, threshold=RULE_THRESHOLD)
            clear = bool(cands) and (len(cands) == 1 or cands[0]["score"] - cands[1]["score"] >= RULE_MARGIN)
            names = [c["name"] for c in cands]
            if gold:
                verdict = ("stays_missed" if not cands else
                           ("framed_right" if names[0] == gold else "framed_WRONG") if clear else
                           ("chooser_has_it" if gold in names else "chooser_lacks_it"))
            else:
                verdict = "control_quiet" if not cands else ("control_framed_WRONG" if clear else "control_to_chooser")
        tally[verdict] = tally.get(verdict, 0) + 1
        rows.append({"id": it["id"], "gold": gold, "verdict": verdict,
                     "candidates": [{"name": c["name"], "score": c["score"]} for c in cands]})
        print(f"{verdict:22s} {it['id']:20s} gold={gold!s:22s} {[(c['name'], c['score']) for c in cands]}")
    print()
    print(json.dumps(tally, indent=1, sort_keys=True))
    if output:
        Path(output).write_text(json.dumps({"rule": {"threshold": RULE_THRESHOLD, "margin": RULE_MARGIN,
                                                     "fitted_on": "the dev split of framing_matcher_set.jsonl"},
                                            "tally": tally, "items": rows}, indent=1) + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["dev", "test", "all"])
    ap.add_argument("--output", default="")
    ap.add_argument("--heldout", action="store_true",
                    help="measure evals/framing_near_match_heldout.jsonl under the dev-fitted rule")
    args = ap.parse_args()
    if args.heldout:
        return heldout(args.output)
    from aughor.ontology.framing import frame_question
    from aughor.ontology.near_match import near_candidates
    graphs = load_graphs()
    items = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    rows, tally = [], {}
    for it in items:
        if args.split != "all" and it["split"] != args.split:
            continue
        g = graphs[it["host"]]
        frame = frame_question(it["question"], g)
        if frame.defines:
            continue                                    # the exact matcher framed it; near-match never runs
        gold = it["expect"].get("definition")
        cands = near_candidates(it["question"], g)
        names = [c["name"] for c in cands]
        if gold:
            verdict = "recoverable" if gold in names else "not_found"
        else:
            verdict = "false_candidate" if cands else "quiet"
        t = tally.setdefault(it["split"], {"recoverable": 0, "not_found": 0, "false_candidate": 0, "quiet": 0})
        t[verdict] += 1
        rows.append({"id": it["id"], "split": it["split"], "gap": it["gap"], "gold": gold, "verdict": verdict,
                     "candidates": cands})
        print(f"{verdict:16s} {it['id']:24s} {it['split']:4s} gold={gold!s:22s} → {names}")
    print()
    for split, t in sorted(tally.items()):
        missed = t["recoverable"] + t["not_found"]
        print(f"{split}: recoverable {t['recoverable']}/{missed} of the missed questions with a definition · "
              f"false candidates on {t['false_candidate']}/{t['false_candidate'] + t['quiet']} that should frame nothing")
    if args.output:
        Path(args.output).write_text(json.dumps({"tally": tally, "items": rows}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
