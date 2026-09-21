"""JD-5's live arm (ran 2026-09-21; re-running is a fresh spend of TypeSafe tokens) — Jev alone on the frozen rows, per-row probabilities recorded.

The LLM arms are already on file (evals/semops_band_results.json, the A/B runs inside
evals/semops_band_decision.json); no funded LLM backend exists on this machine tonight, so the
live spend is Jev only and every comparison is offline composition against those records, on
the SAME rows and gold. One bundle per 25 rows through the harness's own JevBackend (the
slimmed seam shape), latency and reported usage per bundle."""
import json
import sys
import time
from pathlib import Path

WT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WT))
sys.path.insert(0, str(WT / "evals"))

import semops_band_eval as h  # noqa: E402

h._isolate()
h._load_env_file("/Users/amitkamlapure/dev/aughor/.env")

import os  # noqa: E402

from aughor.judgment.seam import Noul  # noqa: E402
from aughor.semops import operators as ops  # noqa: E402

KEY = os.environ["TYPESAFE_API_KEY"]
BATCH = 25

#: The 800-row corpus is judged in the four 200-row slices the A/B runs used, and each filter
#: is labelled with the slice name those runs recorded ("scratch/thelook_sN.json") so the
#: offline analysis joins on it. The slices are derived HERE, deterministically, from the
#: committed corpus — nothing under scratch/ is read.
def runs():
    import json as _json
    corpus = _json.loads((WT / "evals/semops_band_rows_thelook_800.json").read_text())["rows"]
    corpus = [r if isinstance(r, str) else (r.get("name") if isinstance(r, dict) else r[-1])
              for r in corpus]
    gold = h.load_gold(WT / "evals/semops_band_gold_thelook_800.json")
    out = [("evals/semops_band_rows_thelook_products.json",
            h.load_rows(WT / "evals/semops_band_rows_thelook_products.json"),
            h.load_gold(WT / "evals/semops_band_gold_thelook_products.json"))]
    for s in range(4):
        lo, hi = 200 * s, 200 * (s + 1)
        sliced = {pred: {i - lo: v for i, v in g.items() if lo <= i < hi}
                  for pred, g in gold.items()}
        out.append((f"scratch/thelook_s{s}.json", corpus[lo:hi], sliced))
    return out


def one_filter(rows, predicate, backend):
    probs, bundles = {}, []
    for start in range(0, len(rows), BATCH):
        chunk = list(range(start, min(start + BATCH, len(rows))))
        listing = "\n".join(f"[{gi}] {str(rows[gi])[:ops._MAX_CELL]}" for gi in chunk)
        state = f"Predicate: {predicate}\n\nRows (index: text):\n{listing}"
        qs = [Noul(f"r{gi}", f"Row [{gi}] satisfies the predicate.") for gi in chunk]
        before = dict(backend.arm.tokens)
        t0 = time.monotonic()
        answers = backend.judge(state, qs)
        dt = time.monotonic() - t0
        for gi in chunk:
            a = answers.get(f"r{gi}")
            p = a.distribution.get("true") if (a is not None and a.available) else None
            probs[gi] = round(p, 6) if p is not None else None
        bundles.append({
            "rows": len(chunk), "elapsed_s": round(dt, 3),
            "input_tokens": backend.arm.tokens.get("jev_input_tokens", 0) - before.get("jev_input_tokens", 0),
            "output_tokens": backend.arm.tokens.get("jev_output_tokens", 0) - before.get("jev_output_tokens", 0),
        })
    return probs, bundles


def main():
    out = {"run_at": "2026-09-21", "model": None, "batch": BATCH, "filters": []}
    for rows_file, rows, gold in runs():
        for predicate in gold:
            arm = h.ArmResult("jev-solo", True)
            backend = h.JevBackend(KEY, arm)
            probs, bundles = one_filter(rows, predicate, backend)
            bands = {}
            for p in probs.values():
                bands[ops._band(p)] = bands.get(ops._band(p), 0) + 1
            g = gold[predicate]
            scored = [gi for gi in g if probs.get(gi) is not None]
            acc = (sum(1 for gi in scored if (probs[gi] >= 0.5) == bool(g[gi])) / len(scored)
                   if scored else None)
            rec = {"rows_file": rows_file,
                   "gold_file": ("evals/semops_band_gold_thelook_products.json"
                                 if rows_file.startswith("evals/") else
                                 "evals/semops_band_gold_thelook_800.json"), "predicate": predicate,
                   "rows": len(rows), "probs": {str(k): v for k, v in sorted(probs.items())},
                   "bundles": bundles, "bands": bands,
                   "unanswered": sum(1 for p in probs.values() if p is None),
                   "accuracy_at_0.5": round(acc, 4) if acc is not None else None}
            out["filters"].append(rec)
            print(f"{rows_file.split('/')[-1]} · {predicate[:44]:<44} "
                  f"acc@0.5={rec['accuracy_at_0.5']} bands={bands} "
                  f"in_tok={sum(b['input_tokens'] for b in bundles)} "
                  f"t={sum(b['elapsed_s'] for b in bundles):.1f}s", flush=True)
            (WT / "evals" / "jev_live_results_2026-09-21.partial.json").write_text(json.dumps(out, indent=1))
    (WT / "evals" / "jev_live_results_2026-09-21.json").write_text(json.dumps(out, indent=1))
    tot_in = sum(b["input_tokens"] for f in out["filters"] for b in f["bundles"])
    tot_t = sum(b["elapsed_s"] for f in out["filters"] for b in f["bundles"])
    n_b = sum(len(f["bundles"]) for f in out["filters"])
    print(f"\nDONE: {len(out['filters'])} filters, {n_b} bundles, {tot_in} input tokens, "
          f"{tot_t:.0f}s total, median bundle latency "
          f"{sorted(b['elapsed_s'] for f in out['filters'] for b in f['bundles'])[n_b // 2]:.2f}s")


if __name__ == "__main__":
    main()
