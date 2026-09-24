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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["dev", "test", "all"])
    ap.add_argument("--output", default="")
    args = ap.parse_args()
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
