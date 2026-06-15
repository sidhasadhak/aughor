#!/usr/bin/env python3
"""Replicated dev-set benchmark — separate signal from consensus noise.

Single small-n runs of a stochastic pipeline can't tell a real win from variance
(seen repeatedly: v4 vs v5, the gpt-oss gate, the composite-key run where
untouched cases flip-flopped). This runs a config N times on the fixed 19-instance
dev set and reports, per instance, how often it passes — so STABLE wins (pass
every rep) are distinguished from FLAKY (varies) and STABLE losses (never pass).

Usage:
  python evals/dev_bench.py --reps 3 --label fullstack -- \
      --spider-root /path/to/spider2-lite --dev --explore --consensus 3 --select \
      --coder-model gpt-oss:120b-cloud --workers 6

Everything after `--` is passed verbatim to spider2_lite.py (minus --out/--score,
which this script manages per rep).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent


def _correct_ids(run_dir: Path) -> set[str]:
    ids_csv = Path(str(run_dir) + "-ids.csv")
    if not ids_csv.exists():
        return set()
    return {l.strip().replace("sf_", "") for i, l in enumerate(ids_csv.read_text().splitlines()) if i > 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--label", required=True)
    ap.add_argument("passthrough", nargs=argparse.REMAINDER,
                    help="args after -- forwarded to spider2_lite.py")
    args = ap.parse_args()

    fwd = args.passthrough
    if fwd and fwd[0] == "--":
        fwd = fwd[1:]

    dev = json.loads((_REPO / "evals" / "spider2_dev_set.json").read_text())
    tiers = {d["id"]: tier for tier, ds in dev.items() for d in ds}
    ids = list(tiers.keys())

    pass_count = {i: 0 for i in ids}
    rep_totals = []
    for r in range(1, args.reps + 1):
        out = _REPO / "evals" / "spider2_out" / f"dev_{args.label}_r{r}"
        cmd = [sys.executable, str(_REPO / "evals" / "spider2_lite.py"),
               "--out", str(out), "--score"] + fwd
        print(f"\n=== REP {r}/{args.reps} → {out.name} ===", flush=True)
        subprocess.run(cmd, cwd=str(_REPO), check=False)
        correct = _correct_ids(out)
        for i in ids:
            if i in correct:
                pass_count[i] += 1
        rep_totals.append(sum(1 for i in ids if i in correct))
        print(f"rep {r}: {rep_totals[-1]}/{len(ids)}", flush=True)

    # ── aggregate report ──
    n = args.reps
    print("\n" + "=" * 60)
    print(f"REPLICATED DEV REPORT — {args.label}  ({n} reps)")
    print("=" * 60)
    for tier in ("easy", "medium", "hard"):
        t_ids = [i for i in ids if tiers[i] == tier]
        print(f"\n{tier.upper()}:")
        for i in t_ids:
            c = pass_count[i]
            mark = "✓✓✓" if c == n else ("···" if c == 0 else f"{c}/{n}")
            tag = "STABLE-WIN" if c == n else ("stable-loss" if c == 0 else "FLAKY")
            print(f"  {i:12} {mark:6} {tag}")

    stable_wins = sum(1 for i in ids if pass_count[i] == n)
    flaky = sum(1 for i in ids if 0 < pass_count[i] < n)
    mean = sum(rep_totals) / n
    var = sum((x - mean) ** 2 for x in rep_totals) / n
    print(f"\nper-rep totals: {rep_totals}")
    print(f"mean {mean:.1f}/{len(ids)} ({100*mean/len(ids):.1f}%)  std {var**0.5:.2f}")
    print(f"STABLE wins: {stable_wins}/{len(ids)}   FLAKY: {flaky}   "
          f"expected-value floor (stable only): {stable_wins}")


if __name__ == "__main__":
    main()
