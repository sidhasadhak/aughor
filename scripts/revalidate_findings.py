#!/usr/bin/env python
"""Re-validate stored explorer findings against the current guards.

Dry-run by default — prints what WOULD be quarantined/repaired and changes nothing.
Pass --apply to flag/repair in place (non-destructive: quarantine sets invalid=True,
which only HIDES the finding from intel; it stays in the store and is reversible).

  python scripts/revalidate_findings.py             # dry-run, all stores
  python scripts/revalidate_findings.py --apply      # quarantine + repair in place
  python scripts/revalidate_findings.py --glob 'data/exploration_workspace.json'
"""
import argparse
import glob

from aughor.explorer.revalidate import revalidate_file


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="flag/repair in place (default: dry-run)")
    ap.add_argument("--glob", default="data/exploration_*.json", help="store files to scan")
    args = ap.parse_args()

    files = [f for f in glob.glob(args.glob)
             if "_reset_backup" not in f and "_finding_purge_backup" not in f]
    tot_q = tot_r = 0
    for f in sorted(files):
        try:
            rep = revalidate_file(f, apply=args.apply)
        except Exception as e:
            print(f"  (skip {f}: {e})")
            continue
        if rep["quarantined"] or rep["repaired"]:
            print(f"\n■ {rep['file']}")
            for r in rep["quarantined"]:
                verb = "QUARANTINED" if args.apply else "would quarantine"
                print(f"   {verb}  {r['id']}  — {r['reason']}")
                print(f"      {r['finding']}")
            for r in rep["repaired"]:
                verb = "REPAIRED" if args.apply else "would repair"
                print(f"   {verb}  {r['id']}  — {r['fix']}")
            tot_q += len(rep["quarantined"])
            tot_r += len(rep["repaired"])

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n{mode}: {tot_q} to quarantine, {tot_r} to repair across {len(files)} store(s).")
    if not args.apply and (tot_q or tot_r):
        print("Re-run with --apply to flag/repair (reversible; quarantine only hides from intel, "
              "keeps the finding in the store).")


if __name__ == "__main__":
    main()
