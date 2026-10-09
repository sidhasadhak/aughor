#!/usr/bin/env python3
"""ON-10 — the question frame's MATCHER, measured with no model and no warehouse.

`evals/framing_matcher_set.jsonl` holds questions over the hosts that declare business definitions — Olist and
LuxExperience, each graph frozen beside its falsifier set, and (Arc OC-3) theLook with its approved metrics keyed to the
entities they measure — each with a GOLD frame: the declared definition it means,
the rules that apply, the type the reading starts from, the breakdown it names, and terms that must not appear. Every
item is tagged with the gap it probes and split dev/test before any measurement: a matcher change is developed against
dev and measured on test once. `paraphrase` items name a definition in words nobody declared — a deterministic matcher
cannot reach them (a person's synonym can), so they are reported apart from the in-scope score.

`--keyed` hands the frame theLook's keyed metrics (`evals/framing_keyed_metrics_thelook.json`, names and entities only)
— the OC-3 falsifier reads the same items with and without it. `--readings` hands them with their approved statements
(`evals/framing_keyed_statements_thelook.json`) and reports, per keyed item, whether the frame carries the metric in the
shape a deep analysis takes as declared — its measure, its rows and the objects the rules chose — or why not.

Usage:
    .venv/bin/python evals/framing_matcher_eval.py [--split dev|test|all] [--keyed | --readings] [--output results.json]
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
          "lux": "evals/ablation_luxexperience_business_ontology.json",
          "thelook": "evals/ablation_thelook_business_ontology.json"}
KEYED = {"thelook": "evals/framing_keyed_metrics_thelook.json"}
STATEMENTS = {"thelook": "evals/framing_keyed_statements_thelook.json"}
#: The engine each host's statements are written for — a statement is read in its own dialect (`--readings`).
DIALECTS = {"thelook": "bigquery"}
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
    if "ambiguous" in expect:
        checks["ambiguous"] = bool(frame.get("ambiguous")) == bool(expect["ambiguous"])
    for text in expect.get("absent_terms") or []:
        checks[f"absent {text!r}"] = not any(t.get("text") == text for t in frame.get("terms", []))
    return {"ok": all(checks.values()), "checks": checks,
            "frame": {"outcome": outcome, "ambiguous": frame.get("ambiguous"), "rules": rules, "start": start,
                      "named": named, "terms": [(t.get("text"), t.get("kind"), t.get("target")) for t in frame.get("terms", [])]}}


def load_keyed(statements: bool = False) -> dict:
    """Each host's keyed metrics, as the frame is handed them (an object with a name, a label and an entity) — with
    ``statements``, each with its approved statement and filters."""
    from types import SimpleNamespace
    out = {}
    for host, path in KEYED.items():
        rows = json.loads((REPO / path).read_text())["metrics"]
        said = json.loads((REPO / STATEMENTS[host]).read_text())["statements"] if statements else {}
        out[host] = [SimpleNamespace(approved_by="", entity_confirmed_by="eval",
                                     **{"sql": "", "filters": [], **said.get(r["name"], {}), **r}) for r in rows]
    return out


def reading_of(frame: dict) -> dict:
    """What a deep analysis takes from the frame's chosen keyed metric (`framing._keyed_reading`), or why not."""
    chosen = frame.get("chosen")
    o = frame["outcomes"][chosen] if chosen is not None else None
    if o is None or o.get("kind") != "metric":
        return {"taken": False, "why": "no keyed metric chosen"}
    entry = frame.get("compiled", {}).get(o["metric"]) or {}
    r = entry.get("reading") or {}
    if not r.get("formula"):
        return {"taken": False, "why": r.get("why_not") or entry.get("refused") or "not compiled"}
    return {"taken": True, "formula": r["formula"], "table": r["table"], "filters": r["filters"],
            "objects": bool(r.get("objects"))}


def run(split: str = "all", keyed: bool = False, readings: bool = False) -> dict:
    from aughor.ontology.framing import frame_question
    graphs = load_graphs()
    metrics = load_keyed(statements=readings) if keyed or readings else {}
    records = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    if split != "all":
        records = [r for r in records if r["split"] == split]
    rows = []
    for rec in records:
        dialect = DIALECTS.get(rec["host"], "duckdb") if readings else "duckdb"
        frame = frame_question(rec["question"], graphs[rec["host"]], dialect=dialect,
                               metrics=metrics.get(rec["host"], ())).model_dump(mode="json")
        rows.append({"id": rec["id"], "host": rec["host"], "gap": rec["gap"], "split": rec["split"],
                     "question": rec["question"], "expect": rec["expect"], **score(frame, rec["expect"]),
                     **({"reading": reading_of(frame)} if readings and rec["gap"].startswith("keyed_metric") else {})})
    out = {"results": rows, "summary": summarize(rows)}
    if readings:
        keyed_rows = [r for r in rows if "reading" in r]
        out["readings"] = {"taken": sum(r["reading"]["taken"] for r in keyed_rows), "of": len(keyed_rows),
                           "with_rule_objects": sum(r["reading"].get("objects", False) for r in keyed_rows)}
    return out


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
    ap.add_argument("--keyed", action="store_true", help="hand the frame each host's keyed metrics (Arc OC-3)")
    ap.add_argument("--readings", action="store_true",
                    help="hand them with their statements and report what a deep analysis takes (Arc OC-3)")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    result = run(args.split, keyed=args.keyed, readings=args.readings)
    for r in result["results"]:
        failed = [k for k, v in r["checks"].items() if not v]
        print(f"{'ok  ' if r['ok'] else 'MISS'} {r['id']:26} {r['split']:4} "
              + (f"failed {failed} · frame {r['frame']['outcome']} rules={r['frame']['rules']} "
                 f"start={r['frame']['start']} named={r['frame']['named']}" if failed else ""))
    for split, s in result["summary"].items():
        gaps = " · ".join(f"{g} {ok}/{n}" for g, (ok, n) in s["by_gap"].items())
        print(f"\n{split}: in scope {s['in_scope'][0]}/{s['in_scope'][1]}   ({gaps})")
    for r in result["results"]:
        if "reading" in r:
            rd = r["reading"]
            print(f"  {'taken    ' if rd['taken'] else 'not taken'} {r['id']:28} "
                  + (f"{rd['formula']} on {rd['table']} · rows {rd['filters'] or 'all'}"
                     + (" · the rules' objects" if rd["objects"] else "") if rd["taken"] else rd["why"]))
    if "readings" in result:
        rs = result["readings"]
        print(f"\nkeyed items a deep analysis takes as declared: {rs['taken']}/{rs['of']} "
              f"({rs['with_rule_objects']} over the objects a rule chose)")
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"\nResults → {args.output}")


if __name__ == "__main__":
    main()
