#!/usr/bin/env python3
"""Reliability-banded validation of B6 (execution-grounded probe-and-repair).

Applies probe_and_repair to a FIXED baseline run's predictions (so the only variation is B6's own
repair), N times, scores each rep with Spider's evaluate.py, then uses evals/reliability.py to report
the TRUE effect: net *reliable* fail→pass vs pass→fail flips (unstable churn excluded) with a McNemar
p-value, on a stratified slice (failing + passing controls).

Pre-registered decision gate: net-positive & significant ⇒ B6 is a real win and a rebuttal of the
"machinery doesn't help strong models" claim → wire it into the product. Net-neutral ⇒ the claim is
confirmed for the dominant bucket → leave B6 unwired. Either outcome is informative.

Usage:
  python evals/validate_probe_repair.py --spider-root <lite> --baseline <ss_shape dir> \
      --out <b6 dir> --reps 3 --slice-failing 15 --slice-passing 15 --coder-model glm-5.2:cloud
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

import spider2_lite as H          # reuse _coder, _sqlite_exec, build_schema, load_local_instances, score
from reliability import reliability_bands, compare_runs
from aughor.sql.probe_repair import probe_and_repair

from pydantic import BaseModel


_REPAIR_SYS = (
    "You are a conservative SQL reviewer. Given a baseline SQLite query and EVIDENCE probed from the "
    "live database, identify a CONCRETE defect ONLY if the evidence clearly shows one. defect_type "
    "must be one of: grain (wrong aggregation level / fan-out), filter (wrong/missing filter or "
    "literal), value (wrong value encoding/format), frame (wrong window frame), join, or none. If the "
    "baseline is consistent with the evidence, or you are unsure, return defect_type='none' and NO "
    "corrected_sql. Otherwise return the minimal corrected SQLite query that fixes ONLY that defect."
)


class _Fix(BaseModel):
    defect_type: str = "none"
    corrected_sql: Optional[str] = None


def _make_repair_fn(question: str, schema: str, model: Optional[str]):
    def repair(baseline_sql: str, evidence: str):
        user = (f"QUESTION: {question}\n\nSCHEMA:\n{schema}\n\nBASELINE SQL:\n{baseline_sql}\n\n"
                f"LIVE DATA EVIDENCE (probed read-only):\n{evidence}\n\n"
                "Name the concrete defect (or none) and give corrected_sql only if defect_type != none.")
        try:
            ans: _Fix = H._coder(model).complete(system=_REPAIR_SYS, user=user,
                                                 response_model=_Fix, temperature=0.0)
            return (ans.corrected_sql, ans.defect_type)
        except Exception:
            return (None, "none")
    return repair


def _passing(ids_csv: Path) -> set[str]:
    if not ids_csv.exists():
        return set()
    return {l.strip().removeprefix("sf_") for l in ids_csv.read_text().splitlines()[1:] if l.strip()}


def _apply_b6_rep(spider_root: Path, baseline_dir: Path, out_dir: Path, ids: list[str],
                  model: Optional[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    instances = {r["instance_id"]: r for r in H.load_local_instances(spider_root)}
    for iid in ids:
        base_file = baseline_dir / f"{iid}.sql"
        if not base_file.exists() or iid not in instances:
            continue
        base_sql = base_file.read_text().strip()
        inst = instances[iid]
        db_path = spider_root / "resource" / "databases" / f"{inst['db']}.sqlite"
        schema = H.build_schema(spider_root, inst["db"])

        def _ex(s: str):
            r = H._sqlite_exec(db_path, s)
            return (r.ok, r.rows, r.error or "")

        res = probe_and_repair(base_sql, _ex, _make_repair_fn(inst["question"], schema, model),
                               dialect="sqlite")
        (out_dir / f"{iid}.sql").write_text(res.sql + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Reliability-banded validation of B6 probe-and-repair")
    ap.add_argument("--spider-root", required=True, type=Path)
    ap.add_argument("--baseline", required=True, type=Path, help="A scored baseline run dir (has *.sql + -ids.csv)")
    ap.add_argument("--out", required=True, type=Path, help="Output root for B6 rep dirs")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--ids", type=str, default=None, help="Explicit comma-separated slice")
    ap.add_argument("--slice-failing", type=int, default=15)
    ap.add_argument("--slice-passing", type=int, default=15)
    ap.add_argument("--coder-model", type=str, default=None)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    if args.coder_model:
        H._CODER_MODEL = args.coder_model
        print(f"Coder model: {args.coder_model}")

    base_pass = _passing(Path(str(args.baseline.resolve()) + "-ids.csv"))
    all_ids = sorted(p.stem for p in args.baseline.glob("local*.sql"))
    if args.ids:
        slice_ids = [i.strip() for i in args.ids.split(",")]
    else:
        failing = [i for i in all_ids if i not in base_pass][:args.slice_failing]
        passing = [i for i in all_ids if i in base_pass][:args.slice_passing]
        slice_ids = failing + passing
    print(f"Slice: {len(slice_ids)} instances ({sum(1 for i in slice_ids if i not in base_pass)} failing / "
          f"{sum(1 for i in slice_ids if i in base_pass)} passing). Reps: {args.reps}")

    # baseline outcomes on the slice are FIXED (the predictions don't change): 1 stable value per id.
    before = {i: [i in base_pass] * args.reps for i in slice_ids}

    after: dict[str, list[bool]] = {i: [] for i in slice_ids}
    for rep in range(1, args.reps + 1):
        rep_dir = args.out / f"rep_{rep}"
        print(f"\n[rep {rep}/{args.reps}] applying B6 to {len(slice_ids)} baseline predictions → {rep_dir}")
        _apply_b6_rep(args.spider_root, args.baseline, rep_dir, slice_ids, args.coder_model)
        H.score(args.spider_root, rep_dir, args.workers)
        rep_pass = _passing(Path(str(rep_dir.resolve()) + "-ids.csv"))
        for i in slice_ids:
            after[i].append(i in rep_pass)

    bands = reliability_bands(after)
    rep = compare_runs(before, after)
    print("\n" + "=" * 64)
    print("B6 RELIABILITY-BANDED VERDICT (vs fixed baseline)")
    print("=" * 64)
    print(f"  reliable gains (fail→pass): {rep.reliable_gain}  {rep.detail['gained']}")
    print(f"  reliable losses (pass→fail): {rep.reliable_loss}  {rep.detail['lost']}")
    print(f"  NET reliable effect:        {rep.net:+d}   (McNemar p={rep.p_value:.4f})")
    print(f"  unstable-band churn (noise, excluded): {rep.unstable_churn}")
    unstable = [i for i, b in bands.items() if b.band == 'unstable']
    print(f"  B6 unstable instances: {len(unstable)} {unstable}")
    print("\nDECISION GATE: net>0 AND p<0.05 ⇒ real win, wire B6 into the product; "
          "else ⇒ meta-pattern confirmed for this bucket, leave B6 unwired.")


if __name__ == "__main__":
    main()
