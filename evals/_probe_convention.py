#!/usr/bin/env python3
"""Probe: how much of FULL's apparent regression is the ex-cancelled REVENUE
CONVENTION rather than a capability gap? (#13b deep-test).

FULL consistently adds `WHERE status NOT IN ('cancelled', ...)` to revenue/items
aggregates (a defensible net-revenue convention from the injected rules/KB); the
golden references don't. This probe takes each FULL-generated query, strips ONLY
the status-exclusion predicate, re-scores the result against the SAME golden
reference(s), and reports how many regressions recover. Recovery ⇒ the model's
SQL was correct and the only divergence was the (valid) convention — i.e. a
metric-definition confound, not a capability loss.

No LLM calls — re-scores the already-generated SQL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import sqlglot
from sqlglot import exp

from aughor.db.connection import open_connection_for
from evals.sql_accuracy import score_single


def _has_status_col(node) -> bool:
    return any(c.name.lower() == "status" for c in node.find_all(exp.Column))


def strip_status_filter(sql: str) -> str:
    """Remove top-level AND conjuncts that reference a `status` column."""
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return sql
    changed = False
    for where in list(tree.find_all(exp.Where)):
        cond = where.this
        conjuncts = list(cond.flatten()) if isinstance(cond, exp.And) else [cond]
        keep = [c for c in conjuncts if not _has_status_col(c)]
        if len(keep) == len(conjuncts):
            continue
        changed = True
        if not keep:
            where.pop()
        else:
            new = keep[0]
            for c in keep[1:]:
                new = exp.and_(new, c)
            where.set("this", new)
    return tree.sql(dialect="duckdb") if changed else sql


def _probe_file(path: str, recs: dict, db, verbose: bool = True):
    full = {r["id"]: r for r in json.load(open(path))["results"]}

    recovered, unchanged, n_filtered = [], [], 0
    # Work on a single, CONSISTENT footing: run[0] (the stored generated_sql is
    # run[0]'s). Convention-neutral score = MAX(as-scored, status-stripped) so a
    # question passes if it matches the golden EITHER with the ex-cancelled
    # convention OR without it — this recovers pure-revenue queries WITHOUT
    # damaging genuinely status-dependent ones (sql006 "delivered only",
    # sql014 "delivered vs cancelled"), which keep their correct as-scored value.
    orig_pass = new_pass = 0
    deltas = []

    for sid, r in full.items():
        gen = (r.get("generated_sql") or "").strip()
        rec = recs.get(sid)
        runs0 = r.get("runs_overall")
        orig = runs0[0] if runs0 else r["scores"].get("overall", 0)
        if orig >= 0.80:
            orig_pass += 1
        if not gen or not rec:
            if orig >= 0.80:
                new_pass += 1
            continue
        stripped = strip_status_filter(gen)
        if stripped == gen:
            # no status filter to remove — convention-neutral == as-scored
            if orig >= 0.80:
                new_pass += 1
            continue
        n_filtered += 1
        stripped_score = score_single(db, rec, stripped).get("overall", 0)
        neutral = max(orig, stripped_score)  # benefit of the doubt: either definition
        if neutral >= 0.80:
            new_pass += 1
        deltas.append((sid, orig, neutral, rec["question"]))
        if neutral - orig > 0.05:
            recovered.append((sid, orig, neutral))
        else:
            unchanged.append((sid, orig, neutral))

    if verbose:
        print(f"\n  {Path(path).name}: status-filtered queries={n_filtered}, "
              f"recovered={len(recovered)}, pass {orig_pass}→{new_pass}/{len(full)}")
        for sid, o, n, q in sorted(deltas, key=lambda x: x[2] - x[1], reverse=True):
            mark = "RECOVER" if n - o > 0.05 else ("  same " if abs(n - o) <= 0.05 else " worse ")
            print(f"    [{sid}] {o:.2f} → {n:.2f}  {mark}  {q[:46]}")
    return {"n": len(full), "filtered": n_filtered, "recovered": len(recovered),
            "pass_with": orig_pass, "pass_neutral": new_pass}


def main():
    recs = {json.loads(l)["id"]: json.loads(l) for l in open("evals/golden_sql_expanded.jsonl") if l.strip()}
    db = open_connection_for("samples")
    print(f"\n{'='*64}")
    print("  Convention probe — strip ex-cancelled filter, re-score (run[0])")
    print(f"{'='*64}")
    raw = _probe_file("evals/results_raw_13b.json", recs, db, verbose=True)
    full = _probe_file("evals/results_full_13b.json", recs, db, verbose=True)
    db.close()
    print(f"\n  {'-'*56}")
    print(f"  CONVENTION-NEUTRAL pass@0.80 (run[0]):  RAW {raw['pass_neutral']}/{raw['n']}"
          f"   FULL {full['pass_neutral']}/{full['n']}   "
          f"Δ {full['pass_neutral'] - raw['pass_neutral']:+d}")
    print(f"  (as-scored, WITH convention divergence: RAW {raw['pass_with']}"
          f"   FULL {full['pass_with']})")


if __name__ == "__main__":
    main()
