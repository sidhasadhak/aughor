"""The offline composition (reads committed inputs only; no model call, safe to re-run) — every comparison on the SAME rows and gold, no model call.

Inputs: scratch/jev_live_results.json (live), scratch/jev_shuffled_control.json (live control),
evals/semops_band_results.json (products: reference+sampled+banded, flash-lite), the A/B runs
embedded in evals/semops_band_decision.json (s0/s1: sampled+banded). Output:
evals/jd5_jev_receipt.json and a printed summary."""
import json
import random
import sys
from pathlib import Path

WT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WT))
sys.path.insert(0, str(WT / "evals"))

import semops_band_eval as h  # noqa: E402

# ── pricing card (input side; sources in the receipt doc) ─────────────────────────────────────
PRICE = {"jev": 0.042, "gemini-3.1-flash-lite": 0.25}   # $ per 1M input tokens

BAND_LO, BAND_HI = 0.30, 0.70

jev = json.loads((WT / "evals/jev_live_results_2026-09-21.json").read_text())
shuf = json.loads((WT / "evals/jev_shuffled_control_2026-09-21.json").read_text())
products = json.loads((WT / "evals/semops_band_results.json").read_text())
decision = json.loads((WT / "evals/semops_band_decision.json").read_text())

jev_by = {(f["rows_file"], f["predicate"]): f for f in jev["filters"]}


_CORPUS_GOLD = h.load_gold(WT / "evals/semops_band_gold_thelook_800.json")


def gold_for(path):
    """Gold by the label a run recorded. The sN labels resolve to slices of the committed
    800-row corpus (local indices), so nothing under scratch/ is ever read."""
    import re
    path = str(path)
    m = re.search(r"(?:jd3_gold_s|thelook_s)(\d+)\.json$", path)
    if m:
        n = int(m.group(1))
        lo, hi = 200 * n, 200 * (n + 1)
        return {pred: {i - lo: v for i, v in g.items() if lo <= i < hi}
                for pred, g in _CORPUS_GOLD.items()}
    return h.load_gold(WT / path)


# ── paired filters: jev vs the recorded arms ─────────────────────────────────────────────────

def paired(recorded_predicates, rows_file, gold, source):
    """decide()-shaped records: jev as the challenger against each recorded arm."""
    out = []
    for p in recorded_predicates:
        key = (rows_file, p["predicate"])
        jf = jev_by.get(key)
        g = gold.get(p["predicate"])
        arms = p.get("arms") or {}
        if not jf or not g or "sampled" not in arms:
            continue
        ex = set(p.get("excluded_rows") or [])
        ex |= {int(k) for k, v in jf["probs"].items() if v is None}
        rows_ = [i for i in g if i not in ex]
        if not rows_:
            continue
        s = set(arms["sampled"]["kept_rows"])
        b = set(arms["banded"]["kept_rows"]) if "banded" in arms else None
        jr = {i: (jf["probs"][str(i)] >= 0.5) for i in rows_}
        rec = {"predicate": p["predicate"], "rows": len(rows_), "source": source,
               "rows_file": rows_file,
               "sampled_right": [(i in s) == bool(g[i]) for i in rows_],
               "jev_right": [jr[i] == bool(g[i]) for i in rows_],
               "banded_right": ([(i in b) == bool(g[i]) for i in rows_] if b is not None else None),
               "sampled_champion": int(arms["sampled"]["calls"].get("champion", 0)),
               "sampled_tokens": sum((arms["sampled"].get("approx_prompt_tokens") or {}).values()),
               "banded_tokens": (sum((arms["banded"].get("approx_prompt_tokens") or {}).values())
                                 if b is not None else None),
               "jev_tokens": sum(bd["input_tokens"] for bd in jf["bundles"])}
        out.append(rec)
    return out


pairs = paired(products.get("predicates") or [],
               "evals/semops_band_rows_thelook_products.json",
               gold_for("evals/semops_band_gold_thelook_products.json"), "products(flash-lite ref run)")
for run_name in ("A_s0", "A_s1", "B_s0", "B_s1"):
    run = decision["runs"].get(run_name) or {}
    sample = run_name.split("_")[1]
    pairs += paired(run.get("predicates") or [], f"scratch/thelook_{sample}.json",
                    gold_for(f"jd3_gold_{sample}.json"), run_name)

# The products file IS s0 (200/200 identical rows — both fetched in FARM_FINGERPRINT order):
# its three filters never pool with the primary pairing, or the same rows would count twice.
# They serve the composed-cascade analysis (only that run recorded a reference arm) and a
# repeatability read. A is the primary pairing; B is a sensitivity read on the same rows,
# reported beside it and never pooled with it.
primary = [p for p in pairs if p["source"].startswith("A_")]
sensitivity = [p for p in pairs if p["source"].startswith("B_")]


def boot_diff(filters, a_key, b_key):
    """(mean(a) - mean(b)) pooled over rows, CI by resampling whole filters — decide()'s rule."""
    fs = [f for f in filters if f.get(a_key) is not None and f.get(b_key) is not None]
    if not fs:
        return None

    def diff(sel):
        n = sum(f["rows"] for f in sel)
        return (sum(sum(f[a_key]) for f in sel) - sum(sum(f[b_key]) for f in sel)) / n

    point = diff(fs)
    rng = random.Random(h.BOOTSTRAP_SEED)
    boots = sorted(diff([fs[rng.randrange(len(fs))] for _ in fs])
                   for _ in range(h.BOOTSTRAP_RESAMPLES))
    lo = boots[int(0.025 * h.BOOTSTRAP_RESAMPLES)]
    hi = boots[int(0.975 * h.BOOTSTRAP_RESAMPLES) - 1]
    n = sum(f["rows"] for f in fs)
    return {"filters": len(fs), "rows": n,
            a_key.replace("_right", "_accuracy"): round(sum(sum(f[a_key]) for f in fs) / n, 4),
            b_key.replace("_right", "_accuracy"): round(sum(sum(f[b_key]) for f in fs) / n, 4),
            "difference": round(point, 4), "ci95": [round(lo, 4), round(hi, 4)]}


# ── the composed cascade on products (true per-row champion verdicts) ────────────────────────

def composed_on_products():
    out = []
    gold = gold_for("evals/semops_band_gold_thelook_products.json")
    for p in products.get("predicates") or []:
        arms = p.get("arms") or {}
        if "reference" not in arms:
            continue
        jf = jev_by.get(("evals/semops_band_rows_thelook_products.json", p["predicate"]))
        g = gold[p["predicate"]]
        ref = set(arms["reference"]["kept_rows"])
        ex = set(p.get("excluded_rows") or [])
        rows_ = [i for i in g if i not in ex and jf["probs"].get(str(i)) is not None]
        kept, escalated = set(), []
        for i in rows_:
            pr = jf["probs"][str(i)]
            if pr >= BAND_HI:
                kept.add(i)
            elif pr <= BAND_LO:
                pass
            else:
                escalated.append(i)
                if i in ref:
                    kept.add(i)
        acc = sum(1 for i in rows_ if (i in kept) == bool(g[i])) / len(rows_)
        champ_calls = -(-len(escalated) // 25) if escalated else 0
        out.append({"predicate": p["predicate"], "rows": len(rows_),
                    "accuracy": round(acc, 4), "escalated": len(escalated),
                    "champion_calls": champ_calls,
                    "sampled_accuracy": round(sum(1 for i in rows_ if (i in set(arms["sampled"]["kept_rows"])) == bool(g[i])) / len(rows_), 4),
                    "sampled_champion_calls": int(arms["sampled"]["calls"].get("champion", 0)),
                    "reference_accuracy": round(sum(1 for i in rows_ if (i in ref) == bool(g[i])) / len(rows_), 4)})
    return out


# ── calibration: ECE over ten bins, jev probs vs gold, pooled ────────────────────────────────

def ece(filters):
    pairs_ = []
    for f in filters:
        g = gold_for(f["gold_file"]).get(f["predicate"]) or {}
        for i, label in g.items():
            p = f["probs"].get(str(i))
            if p is not None:
                pairs_.append((p, bool(label)))
    bins = [[] for _ in range(10)]
    for p, y in pairs_:
        bins[min(9, int(p * 10))].append((p, y))
    tot = len(pairs_)
    e = 0.0
    table = []
    for k, b in enumerate(bins):
        if not b:
            table.append({"bin": f"{k/10:.1f}-{(k+1)/10:.1f}", "n": 0})
            continue
        conf = sum(p for p, _ in b) / len(b)
        freq = sum(1 for _, y in b if y) / len(b)
        e += abs(conf - freq) * len(b) / tot
        table.append({"bin": f"{k/10:.1f}-{(k+1)/10:.1f}", "n": len(b),
                      "mean_p": round(conf, 3), "frac_true": round(freq, 3)})
    return round(e, 4), table, tot


# ── the shuffled control, read beside the real arm ───────────────────────────────────────────

control = []
for cf in shuf["filters"]:
    real = jev_by.get(("evals/semops_band_rows_thelook_products.json", cf["predicate"]))
    control.append({"predicate": cf["predicate"], "real_accuracy": real["accuracy_at_0.5"],
                    "shuffled_accuracy": cf["accuracy_at_0.5"],
                    "majority_class_floor": cf["majority_class_floor"]})

# ── the framework re-decision: recorded banded totals re-costed under the slimmed seam ───────
# Measured request shapes (25 rows, same builder code, measure_slim.py 2026-09-21):
CHARS = {"today25": 2340, "slim25": 5228, "preslim25": 9021}
slim_ratio = CHARS["slim25"] / CHARS["preslim25"]
framework = {}
for label, dec in (("A", decision["decisions"]["A"]), ("B", decision["decisions"]["B"])):
    framework[label] = {
        "sampled_prompt_tokens": dec["sampled_prompt_tokens"],
        "banded_prompt_tokens_preslim": dec["banded_prompt_tokens"],
        "banded_prompt_tokens_slimmed_est": round(dec["banded_prompt_tokens"] * slim_ratio),
        "slim_ratio_measured": round(slim_ratio, 3),
        "banded_vs_sampled_after_slim": round(dec["banded_prompt_tokens"] * slim_ratio
                                              / dec["sampled_prompt_tokens"], 2),
        "accuracy_difference": dec["accuracy_difference"], "ci95": dec["ci95"],
        "champion_calls": [dec["banded_champion_calls"], dec["sampled_champion_calls"]],
    }

# ── cost & latency card ──────────────────────────────────────────────────────────────────────
all_bundles = [b for f in jev["filters"] for b in f["bundles"]]
lat = sorted(b["elapsed_s"] for b in all_bundles)
jev_tok = sum(b["input_tokens"] for b in all_bundles)
jev_out = sum(b["output_tokens"] for b in all_bundles)
n_rows = sum(f["rows"] for f in jev["filters"])
sampled_tok_200 = [f["sampled_tokens"] for f in primary if f["rows"] >= 150]
cost = {
    "jev_input_tokens_total": jev_tok, "jev_output_tokens_total": jev_out,
    "jev_rows_judged": n_rows, "jev_tokens_per_row": round(jev_tok / n_rows, 1),
    "jev_usd_per_1k_rows": round(jev_tok / n_rows * 1000 * PRICE["jev"] / 1e6, 5),
    "sampled_flashlite_usd_per_1k_rows_mean": round(
        (sum(sampled_tok_200) / len(sampled_tok_200)) / 200 * 1000
        * PRICE["gemini-3.1-flash-lite"] / 1e6, 5) if sampled_tok_200 else None,
    "bundle_latency_s": {"median": lat[len(lat) // 2], "p90": lat[int(len(lat) * 0.9)],
                         "n": len(lat)},
    "prices_usd_per_M_input": PRICE,
}

bands_pool = {}
for f in jev["filters"]:
    for k, v in f["bands"].items():
        bands_pool[k] = bands_pool.get(k, 0) + v

receipt = {
    "run_at": "2026-09-21",
    "rule": "evals/semops_band_eval.py DECISION_MARGIN docstring; challenger=jev-solo@0.5, "
            "paired on the recorded runs' rows and gold; CI bootstraps whole filters "
            f"(seed {h.BOOTSTRAP_SEED})",
    "model_seen_live": jev.get("model") or "jev-1.13.0 (probe)",
    "jev_vs_sampled_primary": boot_diff(primary, "jev_right", "sampled_right"),
    "jev_vs_banded_primary": boot_diff(primary, "jev_right", "banded_right"),
    "jev_vs_sampled_sensitivity_B": boot_diff(sensitivity, "jev_right", "sampled_right"),
    "gold_only_accuracy_unique_filters": {
        "filters": len([f for f in jev["filters"] if f["rows_file"].startswith("scratch/")]),
        "accuracy": round(sum(f["accuracy_at_0.5"] * f["rows"] for f in jev["filters"]
                              if f["rows_file"].startswith("scratch/"))
                          / sum(f["rows"] for f in jev["filters"]
                                if f["rows_file"].startswith("scratch/")), 4),
        "note": "s0-s3 x 6 predicates; the products file duplicates s0 and is excluded"},
    "repeatability_products_vs_s0": [
        (lambda a, b: {"predicate": pred[:44],
                       "verdict_flips": sum(1 for k in a if a[k] is not None
                                            and b.get(k) is not None
                                            and (a[k] >= 0.5) != (b[k] >= 0.5)),
                       "rows": 200,
                       "mean_abs_dp": round(sum(abs(a[k] - b[k]) for k in a
                                                if a[k] is not None and b.get(k) is not None)
                                            / max(1, sum(1 for k in a if a[k] is not None
                                                         and b.get(k) is not None)), 4)})(
            jev_by[("evals/semops_band_rows_thelook_products.json", pred)]["probs"],
            jev_by[("scratch/thelook_s0.json", pred)]["probs"])
        for pred in [f["predicate"] for f in jev["filters"]
                     if f["rows_file"] == "evals/semops_band_rows_thelook_products.json"]],
    "composed_banded_jev_products": composed_on_products(),
    "shuffled_context_control": control,
    "calibration": dict(zip(("ece", "reliability", "n"), ece(jev["filters"]))),
    "bands_pooled": bands_pool,
    "framework_token_redecision": framework,
    "cost_and_latency": cost,
}
(WT / "evals/jd5_jev_receipt.json").write_text(json.dumps(receipt, indent=1))
print(json.dumps({k: v for k, v in receipt.items() if k not in
                  ("composed_banded_jev_products", "shuffled_context_control", "calibration")},
                 indent=1))
print("\ncomposed:", json.dumps(receipt["composed_banded_jev_products"], indent=1))
print("\ncontrol:", json.dumps(receipt["shuffled_context_control"], indent=1))
print("\nECE:", receipt["calibration"]["ece"], "n =", receipt["calibration"]["n"])
for row in receipt["calibration"]["reliability"]:
    print("  ", row)
print("\nwrote evals/jd5_jev_receipt.json")
