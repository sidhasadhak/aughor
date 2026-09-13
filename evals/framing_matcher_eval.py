#!/usr/bin/env python3
"""ON-10 — the question frame's MATCHER, measured with no model and no warehouse.

`evals/framing_matcher_set.jsonl` holds questions over the two hosts that declare business definitions — Olist and
LuxExperience, each graph frozen beside its falsifier set — each with a GOLD frame: the declared definition it means,
the rules that apply, the type the reading starts from, the breakdown it names, and terms that must not appear. Every
item is tagged with the gap it probes and split dev/test before any measurement: a matcher change is developed against
dev and measured on test once. `paraphrase` items name a definition in words nobody declared — a deterministic matcher
cannot reach them (a person's synonym can), so they are reported apart from the in-scope score.

Usage:
    .venv/bin/python evals/framing_matcher_eval.py [--split dev|test|all] [--output results.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DATASET = REPO / "evals" / "framing_matcher_set.jsonl"
GRAPHS = {"olist": "evals/ablation_olist_business_ontology.json",
          "lux": "evals/ablation_luxexperience_business_ontology.json"}
OUT_OF_SCOPE = {"paraphrase"}


def load_graphs() -> dict:
    from aughor.ontology.models import OntologyGraph
    return {host: OntologyGraph.model_validate(json.loads((REPO / path).read_text())) for host, path in GRAPHS.items()}


def score(frame: dict, expect: dict) -> dict:
    """Each gold field the item states, checked against the frame; an item is correct when every stated check holds."""
    chosen = frame.get("chosen")
    outcome = frame["outcomes"][chosen]["name"] if chosen is not None else None
    rules = sorted(r["id"] for r in frame.get("rules", []) if r.get("usable"))
    start = (frame.get("start") or {}).get("entity")
    named = sorted(d["path"] for d in frame.get("drivers", []) if d.get("named"))
    checks: dict[str, bool] = {}
    if "definition" in expect:
        checks["definition"] = outcome == expect["definition"]
    if "rules" in expect:
        checks["rules"] = rules == sorted(expect["rules"])
    if expect.get("start"):
        checks["start"] = start == expect["start"]
    if expect.get("named"):
        checks["named"] = bool(set(named) & set(expect["named"]))
    for text in expect.get("absent_terms") or []:
        checks[f"absent {text!r}"] = not any(t.get("text") == text for t in frame.get("terms", []))
    return {"ok": all(checks.values()), "checks": checks,
            "frame": {"outcome": outcome, "ambiguous": frame.get("ambiguous"), "rules": rules, "start": start,
                      "named": named, "terms": [(t.get("text"), t.get("kind"), t.get("target")) for t in frame.get("terms", [])]}}


def run(split: str = "all") -> dict:
    from aughor.ontology.framing import frame_question
    graphs = load_graphs()
    records = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    if split != "all":
        records = [r for r in records if r["split"] == split]
    rows = []
    for rec in records:
        frame = frame_question(rec["question"], graphs[rec["host"]], dialect="duckdb").model_dump(mode="json")
        rows.append({"id": rec["id"], "host": rec["host"], "gap": rec["gap"], "split": rec["split"],
                     "question": rec["question"], "expect": rec["expect"], **score(frame, rec["expect"])})
    return {"results": rows, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    out: dict = {}
    for split in ("dev", "test"):
        subset = [r for r in rows if r["split"] == split]
        if not subset:
            continue
        in_scope = [r for r in subset if r["gap"] not in OUT_OF_SCOPE]
        by_gap: dict = defaultdict(lambda: [0, 0])
        for r in subset:
            by_gap[r["gap"]][0] += r["ok"]
            by_gap[r["gap"]][1] += 1
        out[split] = {"in_scope": [sum(r["ok"] for r in in_scope), len(in_scope)],
                      "by_gap": {g: v for g, v in sorted(by_gap.items())}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("dev", "test", "all"), default="all")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    result = run(args.split)
    for r in result["results"]:
        failed = [k for k, v in r["checks"].items() if not v]
        print(f"{'ok  ' if r['ok'] else 'MISS'} {r['id']:26} {r['split']:4} "
              + (f"failed {failed} · frame {r['frame']['outcome']} rules={r['frame']['rules']} "
                 f"start={r['frame']['start']} named={r['frame']['named']}" if failed else ""))
    for split, s in result["summary"].items():
        gaps = " · ".join(f"{g} {ok}/{n}" for g, (ok, n) in s["by_gap"].items())
        print(f"\n{split}: in scope {s['in_scope'][0]}/{s['in_scope'][1]}   ({gaps})")
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"\nResults → {args.output}")


if __name__ == "__main__":
    main()
