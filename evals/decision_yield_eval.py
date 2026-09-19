"""A1 — what the decision corpus is worth, arm A against arm B.

Every other eval in this directory scores ANSWERS. This one scores the RECORD: given the
closed-set choices the platform made while answering, how many of them could a selection
model ever be trained on? That is a different question, and until A1 it had an
embarrassing answer.

**Arm A** is the corpus as the code wrote it before A1: three `record_decision` sites, none
passing `conn_id`, `trace_id` or `inv_id`; `framing.definition` recording no probability;
and `outcome` written inline by `tool_loop` as "the tool did not raise". **Arm B** is the
corpus the instrumented code writes: provenance on every row, and an outcome that a human
verdict can drive negative through `mark_outcomes_for_run`.

**This harness makes no model call and opens no warehouse.** It reads a decisions store and
counts. That is deliberate: arm A's yield is exact BY CONSTRUCTION — the old code could not
write a `conn_id`, so arm A's attributable count is zero for any traffic whatsoever, and no
amount of spending would discover otherwise. Paying a model to re-derive a structural zero
is the mistake `evals/README.md`'s live protocol exists to prevent. So arm A is computed,
arm B is measured, and the run is free.

Usage:

    uv run python evals/decision_yield_eval.py \\
        --db data/decisions.db --output evals/decision_yield_results.json

    # or against a store a scripted run produced
    uv run python evals/decision_yield_eval.py --db /tmp/run/decisions.db

The falsifier is stated in `summarize`: if arm B's rows are no more attributable, no better
supplied with probabilities and no more discriminating than arm A's, A1 bought nothing and
should be reverted rather than defended.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: The three registered decision sites, in the order they run on a deep turn. Named here so
#: a site that stops recording shows up as a zero row rather than vanishing from the table.
SITES = ("ask.route", "framing.definition", "converse.tool")


def load_yield(db_path: Path) -> dict:
    """The per-site yield of one decisions store, read through the store's own reader.

    Pointed at the store by env rather than by argument because `resolve_db_path` is the
    single seam that decides where a store lives — a second path resolution here would be a
    second definition of "the decisions store", and those drift.
    """
    os.environ["AUGHOR_DECISIONS_DB"] = str(db_path)
    from aughor.learning import decisions
    return decisions.corpus_yield()


#: What the PRE-A1 code could write, PER SITE. Site-specific on purpose: a blanket "arm A
#: recorded nothing" is not true and would overstate A1. `ask.route` always passed the
#: model's confidence (`nodes.py`, `confidence=float(decision.confidence)`), so the
#: probability column is NOT what A1 bought there — attribution and the outcome are.
#: `converse.tool` passed an outcome, but only ever the literal "did the tool raise", so it
#: is one value forever. `framing.definition` passed neither: its response model had a single
#: `definition` field, and nothing downstream ever closed it.
_ARM_A_CAPABILITY = {
    #                      probability?  outcome the old code wrote
    "ask.route":          (True,         None),
    "converse.tool":      (False,        "ok"),
    "framing.definition": (False,        None),
}


def arm_a(measured: dict) -> dict:
    """Arm A's yield for the same rows, derived — not re-run.

    Derivable because each cell is a property of the pre-A1 SOURCE, not of the traffic: no
    site had a `conn_id` parameter, so `attributable` is zero at every volume; and each
    site's probability and outcome capability is fixed by `_ARM_A_CAPABILITY` above. `total`
    and `trainable` are unchanged — A1 records more about a decision, it does not make more
    decisions.

    An unknown site is treated as arm-A-capable on both columns. That is the conservative
    direction: it makes A1 look like it bought LESS, so a new site cannot flatter the result
    by being absent from the table above.
    """
    out = {}
    for site, s in measured.items():
        has_prob, outcome = _ARM_A_CAPABILITY.get(site, (True, None))
        outcomes = {outcome: s["total"]} if (outcome and s["total"]) else {}
        out[site] = {
            "total": s["total"],
            "attributable": 0,
            "with_probability": s["with_probability"] if has_prob else 0,
            "trainable": s["trainable"],
            "outcomes": outcomes,
            "discriminating": len(outcomes) > 1,
        }
    return out


def summarize(a: dict, b: dict) -> dict:
    """The A/B table, and the falsifier that would send A1 back."""
    sites = sorted(set(a) | set(b) | set(SITES))
    rows = []
    for site in sites:
        sa = a.get(site) or {"total": 0, "attributable": 0, "with_probability": 0,
                             "trainable": 0, "outcomes": {}, "discriminating": False}
        sb = b.get(site) or dict(sa)
        rows.append({
            "site": site,
            "total": sb["total"],
            "attributable": {"a": sa["attributable"], "b": sb["attributable"]},
            "with_probability": {"a": sa["with_probability"], "b": sb["with_probability"]},
            "discriminating": {"a": sa["discriminating"], "b": sb["discriminating"]},
            "outcomes_b": sb["outcomes"],
            "trainable": sb["trainable"],
        })
    total = sum(r["total"] for r in rows)
    attr_b = sum(r["attributable"]["b"] for r in rows)
    prob_b = sum(r["with_probability"]["b"] for r in rows)
    attr_a = sum(r["attributable"]["a"] for r in rows)
    prob_a = sum(r["with_probability"]["a"] for r in rows)
    disc_b = [r["site"] for r in rows if r["discriminating"]["b"]]
    out = {
        "n_rows": total,
        "sites_recording": [r["site"] for r in rows if r["total"]],
        "sites_silent": [r["site"] for r in rows if not r["total"]],
        "attributable": {"a": attr_a, "b": attr_b},
        "with_probability": {"a": prob_a, "b": prob_b},
        "discriminating_sites": {"a": [], "b": disc_b},
        "by_site": rows,
    }
    # A1's claim is that the corpus becomes usable, not that it becomes bigger. So the
    # falsifier is about the three columns that were empty or constant, and it FIRES on a
    # tie — "no worse" is not a reason to keep instrumentation nobody reads.
    out["falsifier"] = {
        "a1_bought_nothing": total > 0 and attr_b <= attr_a and prob_b <= prob_a and not disc_b,
        "note": ("fires when the instrumented corpus is no more attributable, no better "
                 "supplied with probabilities and no more discriminating than the old one"),
    }
    # An empty store cannot settle anything either way, and reading a zero as a pass is how
    # a guard passes for the wrong reason. Say so on the record instead.
    out["inconclusive"] = total == 0
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO / "data" / "decisions.db"),
                    help="the decisions store to read (default: the repo's own)")
    ap.add_argument("--output", default="", help="write the result JSON here")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"no decisions store at {db}")

    measured = load_yield(db)
    result = {"db": str(db), "summary": summarize(arm_a(measured), measured)}
    s = result["summary"]

    print(f"decision corpus: {s['n_rows']} rows from {db}")
    if s["sites_silent"]:
        print(f"  silent sites (no traffic in this store): {', '.join(s['sites_silent'])}")
    print(f"  {'site':<22} {'rows':>6} {'attributable':>16} {'with prob':>14}  discriminating")
    for r in s["by_site"]:
        print(f"  {r['site']:<22} {r['total']:>6} "
              f"{r['attributable']['a']:>7} -> {r['attributable']['b']:<6} "
              f"{r['with_probability']['a']:>5} -> {r['with_probability']['b']:<6} "
              f" {r['discriminating']['a']} -> {r['discriminating']['b']}"
              + (f"   outcomes={r['outcomes_b']}" if r["outcomes_b"] else ""))
    if s["inconclusive"]:
        print("\nINCONCLUSIVE: the store is empty — this settles nothing in either direction.")
    else:
        print(f"\nfalsifier: {'FIRES' if s['falsifier']['a1_bought_nothing'] else 'HOLDS'}"
              f" — {s['falsifier']['note']}")

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
