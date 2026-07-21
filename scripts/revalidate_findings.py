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
import os

from aughor.explorer.revalidate import revalidate_file


def _col_types_for(store_path: str) -> dict:
    """Declared column types for the connection a store file belongs to, so the
    aggregate↔type check (SUM over a VARCHAR) can fire on stored findings too.

    `data/exploration_workspace__netflix.json` → connection `workspace`. Entirely
    best-effort: no connection, no registry, no live schema → {} and the pass still
    runs every type-free check offline.

    Opens via `open_connection_for` — NOT `build_connector(get_dsn(...))`. The latter
    builds a bare connector that has not ATTACHed the connection's uploaded databases,
    so `get_schema()` comes back without the user's schemas and every type-dependent
    check silently no-ops (it reported "no offenders" against a workspace whose 33
    luxexperience tables were sitting right there)."""
    try:
        from aughor.db.connection import open_connection_for
        from aughor.tools.schema import col_types_from_schema

        stem = os.path.basename(store_path).removeprefix("exploration_").removesuffix(".json")
        if stem.startswith("canvas_"):
            return {}
        conn_id = stem.split("__", 1)[0]
        return col_types_from_schema(open_connection_for(conn_id).get_schema()) or {}
    except Exception:
        return {}


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
            rep = revalidate_file(f, apply=args.apply, col_types=_col_types_for(f))
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
