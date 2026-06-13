"""Flush cached distributions that were computed for identifier columns.

Before the camelCase-key fix (profiler.py `_KEY_PATTERN_CAMEL`), id columns like
`franchiseID`/`supplierID` were mis-typed as "measure" and distribution-profiled,
leaving bogus numeric percentiles in the explorer's cached state. This removes those
stale entries using the SAME (now-fixed) key patterns the classifier uses, so only
identifier columns are dropped — real measures (revenue, lifetime_spend, …) are kept.

Usage:  python scripts/flush_id_distributions.py [--apply]   (dry-run without --apply)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from aughor.tools.profiler import _KEY_PATTERN, _KEY_PATTERN_CAMEL

DATA = Path(__file__).resolve().parent.parent / "data"
APPLY = "--apply" in sys.argv


def is_id_column(col: str) -> bool:
    return bool(_KEY_PATTERN.search(col.lower()) or _KEY_PATTERN_CAMEL.search(col))


def flush_file(path: Path) -> list[str]:
    try:
        state = json.loads(path.read_text())
    except Exception:
        return []
    dists = state.get("distributions")
    if not isinstance(dists, dict):
        return []
    removed = []
    for key in list(dists.keys()):
        # key is "<table>:<column>" — table may be schema-qualified, column has no colon.
        table, _, col = key.rpartition(":")
        if col and is_id_column(col):
            removed.append(key)
            if APPLY:
                del dists[key]
    if removed and APPLY:
        # keep the profiled counter honest
        if isinstance(state.get("distributions_profiled"), int):
            state["distributions_profiled"] = len(dists)
        path.write_text(json.dumps(state, indent=2))
    return removed


def main() -> None:
    total = 0
    for path in sorted(DATA.glob("exploration*.json")):
        removed = flush_file(path)
        if removed:
            total += len(removed)
            print(f"{path.name}: {len(removed)} id-distribution(s) "
                  f"{'removed' if APPLY else 'WOULD remove (dry-run)'}")
            for k in removed:
                print(f"    - {k}")
    print(f"\n{'Removed' if APPLY else 'Would remove'} {total} stale id distribution(s) "
          f"across {DATA}{'' if APPLY else '  (re-run with --apply)'}")


if __name__ == "__main__":
    main()
