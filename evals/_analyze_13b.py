#!/usr/bin/env python3
"""Case-level comparison of two golden-eval result JSONs (#13b deep-test aid).

Surfaces what a headline number hides: per-question RAW→FULL deltas, the
stability band (noise control proof), metric-alt acceptances, and the exact
generated SQL for every regression — so conclusions are drawn from cases, not
from a single aggregate (the standing deep-test-before-conclude rule).

Usage:
    .venv/bin/python evals/_analyze_13b.py evals/results_raw_13b.json evals/results_full_13b.json
"""
from __future__ import annotations

import json
import sys


def load(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    return {r["id"]: r for r in data["results"]}, data.get("summary", {})


def band_stats(byid: dict) -> tuple[int, float]:
    bands = [r.get("overall_band", 0.0) for r in byid.values() if "overall_band" in r]
    unstable = sum(1 for r in byid.values() if r.get("unstable"))
    avg = round(sum(bands) / len(bands), 4) if bands else 0.0
    return unstable, avg


def headline(byid: dict) -> dict:
    n = len(byid)
    perfect = sum(1 for r in byid.values() if r["scores"].get("overall", 0) >= 0.99)
    passed = sum(1 for r in byid.values() if r["scores"].get("overall", 0) >= 0.80)
    errors = sum(1 for r in byid.values() if r["scores"].get("error"))
    alt = sum(1 for r in byid.values() if r["scores"].get("matched_reference", 0))
    return {"n": n, "perfect": perfect, "passed": passed, "errors": errors, "alt": alt}


def main():
    raw_path, full_path = sys.argv[1], sys.argv[2]
    raw, _ = load(raw_path)
    full, _ = load(full_path)

    hr, hf = headline(raw), headline(full)
    print(f"\n{'='*68}")
    print(f"  RAW vs FULL  (pinned `samples`, temp-0)   n={hr['n']}")
    print(f"{'='*68}")
    print(f"  {'metric':<22}{'RAW':>10}{'FULL':>10}{'Δ':>10}")
    for k, label in [("perfect", "Perfect (≥0.99)"), ("passed", "Pass (≥0.80)"),
                     ("errors", "Errors"), ("alt", "Metric-alt hits")]:
        d = hf[k] - hr[k]
        print(f"  {label:<22}{hr[k]:>10}{hf[k]:>10}{d:>+10}")

    ur, ar = band_stats(raw)
    uf, af = band_stats(full)
    print(f"\n  Stability (noise control):")
    print(f"    RAW : {ur}/{hr['n']} unstable, mean band {ar}")
    print(f"    FULL: {uf}/{hf['n']} unstable, mean band {af}")

    # Per-question deltas (FULL mean - RAW mean)
    deltas = []
    for sid in sorted(set(raw) & set(full)):
        dr = raw[sid]["scores"].get("overall", 0)
        df = full[sid]["scores"].get("overall", 0)
        deltas.append((sid, dr, df, round(df - dr, 3)))

    gains = [d for d in deltas if d[3] > 0.05]
    losses = [d for d in deltas if d[3] < -0.05]
    print(f"\n  Per-question: {len(gains)} gains, {len(losses)} regressions (|Δ|>0.05)")

    def show(rows, title):
        if not rows:
            return
        print(f"\n  --- {title} ---")
        for sid, dr, df, d in sorted(rows, key=lambda x: x[3]):
            r = full[sid]
            mr = r["scores"].get("matched_reference", 0)
            tag = f" [alt#{mr}]" if mr else ""
            print(f"    [{sid}] RAW {dr:.2f} → FULL {df:.2f}  (Δ{d:+.2f}){tag}  {r['question'][:48]}")
            err = r["scores"].get("error")
            if err:
                print(f"        FULL error: {err[:90]}")
            print(f"        FULL sql: {(r.get('generated_sql') or '')[:160]}")

    show(losses, "REGRESSIONS (dig these)")
    show(gains, "GAINS")


if __name__ == "__main__":
    main()
