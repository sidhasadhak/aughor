"""JD-4's shuffled-context control, run against Jev live — the falsifier before belief.

Each bundle's STATE lists the rows under the WRONG indices (a fixed derangement of the chunk),
while the questions still reference the original indices. A model that reads the state must now
score the wrong text per question; if its accuracy against gold survives the shuffle, it was
never reading the rows — and every number in the live receipt is void. Three products filters,
one call per 25-row bundle, same shape as the live arm."""
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

rows = h.load_rows(WT / "evals/semops_band_rows_thelook_products.json")
gold = h.load_gold(WT / "evals/semops_band_gold_thelook_products.json")

out = {"run_at": "2026-09-21", "control": "shuffled-context (derangement per bundle)",
       "filters": []}
for predicate, g in gold.items():
    arm = h.ArmResult("jev-shuffled", True)
    backend = h.JevBackend(KEY, arm)
    probs = {}
    t_all = 0.0
    for start in range(0, len(rows), BATCH):
        chunk = list(range(start, min(start + BATCH, len(rows))))
        # Rotate the TEXTS one position against the indices: every index shows another row's
        # text (a derangement), so a question about [gi] is answered against the wrong row.
        shifted = {gi: rows[chunk[(k + 1) % len(chunk)]] for k, gi in enumerate(chunk)}
        listing = "\n".join(f"[{gi}] {str(shifted[gi])[:ops._MAX_CELL]}" for gi in chunk)
        state = f"Predicate: {predicate}\n\nRows (index: text):\n{listing}"
        qs = [Noul(f"r{gi}", f"Row [{gi}] satisfies the predicate.") for gi in chunk]
        t0 = time.monotonic()
        answers = backend.judge(state, qs)
        t_all += time.monotonic() - t0
        for gi in chunk:
            a = answers.get(f"r{gi}")
            p = a.distribution.get("true") if (a is not None and a.available) else None
            probs[gi] = round(p, 6) if p is not None else None
    scored = [gi for gi in g if probs.get(gi) is not None]
    acc = sum(1 for gi in scored if (probs[gi] >= 0.5) == bool(g[gi])) / len(scored)
    # The floor the control should sit NEAR: agreeing with the majority class blind.
    base = max(sum(1 for v in g.values() if v), sum(1 for v in g.values() if not v)) / len(g)
    rec = {"predicate": predicate, "accuracy_at_0.5": round(acc, 4),
           "majority_class_floor": round(base, 4),
           "probs": {str(k): v for k, v in sorted(probs.items())},
           "input_tokens": arm.tokens.get("jev_input_tokens", 0), "elapsed_s": round(t_all, 1)}
    out["filters"].append(rec)
    print(f"SHUFFLED {predicate[:44]:<44} acc={acc:.4f} (majority floor {base:.4f})", flush=True)

(WT / "evals" / "jev_shuffled_control_2026-09-21.json").write_text(json.dumps(out, indent=1))
print("wrote evals/jev_shuffled_control_2026-09-21.json")
