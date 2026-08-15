"""Per-case diff of an A/B grid — the reading `flag_ab_grid.py` tells you to do and
nothing produced.

    AUGHOR_SYSTEM_DB=$PWD/data/system.db \\
      .venv/bin/python scripts/grid_case_diff.py <suite_id> [<off_run_id> <on_run_id>]

With only a suite id it takes the two most recent runs whose config differs on exactly
one flag override (the shape `flag_ab_grid.py` writes) and diffs them. Prints, per
case: the verdict in each cell (correct / wrong / no-reference / error), the flip
direction when they disagree, and — for runs recorded since the `trace.observation`
score exists (2026-08-14) — the SQL each cell produced, so a flip can be attributed to
what the prompt change did to the query rather than to a coin toss.

Why per-case: at temperature 0 the replicate band measures determinism, not sampling,
so a band of ~0.000 makes any single-case flip look "attributable" (module docstring
of flag_ab_grid.py). The evidence is which cases moved and what their SQL became.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap

if not os.environ.get("AUGHOR_SYSTEM_DB"):
    sys.exit("set AUGHOR_SYSTEM_DB (a bare script does not load conftest's isolation)")

from aughor.evals import store  # noqa: E402


def _verdict(res: dict | None) -> str:
    if res is None:
        return "missing"
    if res.get("error"):
        return "error"
    c = res.get("correct")
    if c is None:
        return "no-ref"
    return "correct" if c else "wrong"


def _trace(res: dict | None) -> dict:
    for s in (res or {}).get("scores") or []:
        if s.get("evaluator") == "trace.observation":
            return s.get("detail") or {}
    return {}


def _pick_runs(suite_id: str) -> tuple[dict, dict]:
    runs = [r for r in store.list_runs(suite_id, limit=50)
            if (r.get("config") or {}).get("flag_overrides")]
    for i, a in enumerate(runs):
        for b in runs[i + 1:]:
            fa = (a.get("config") or {}).get("flag_overrides") or {}
            fb = (b.get("config") or {}).get("flag_overrides") or {}
            if set(fa) == set(fb) and len(fa) == 1:
                (flag,) = fa
                if fa[flag] != fb[flag]:
                    off, on = (a, b) if not fa[flag] else (b, a)
                    return off, on
    sys.exit(f"no off/on run pair found for suite {suite_id}; pass the two run ids explicitly")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    suite_id = argv[1]
    if len(argv) >= 4:
        off, on = store.get_run(argv[2]), store.get_run(argv[3])
        if not off or not on:
            sys.exit("run id not found")
    else:
        off, on = _pick_runs(suite_id)

    flag = next(iter(((off.get("config") or {}).get("flag_overrides") or {"?": None})))
    cases = {c["id"]: c for c in store.list_cases(suite_id, limit=1000)}
    r_off = {x["case_id"]: x for x in store.run_results(off["id"], limit=5000)}
    r_on = {x["case_id"]: x for x in store.run_results(on["id"], limit=5000)}

    print(f"suite {suite_id} · flag {flag}\n  off run {off['id']} ({off.get('status')}, "
          f"{len(r_off)} results)\n  on  run {on['id']} ({on.get('status')}, {len(r_on)} results)\n")

    tally = {"same": 0, "off→on gained": 0, "off→on lost": 0, "other": 0, "unrun": 0}
    for cid, case in cases.items():
        a, b = r_off.get(cid), r_on.get(cid)
        va, vb = _verdict(a), _verdict(b)
        if va == "missing" or vb == "missing":
            # A cell that never reached this case is NOT a flip — a killed or still-
            # running grid must never read as "the flag lost 10 cases".
            tally["unrun"] += 1
            continue
        if va == vb:
            tally["same"] += 1
            continue
        if va != "correct" and vb == "correct":
            kind = "off→on gained"
        elif va == "correct" and vb != "correct":
            kind = "off→on lost"
        else:
            kind = "other"
        tally[kind] += 1
        print(f"[{kind:14}] {case.get('question', '?')}")
        print(f"    off={va:8}  on={vb}")
        for label, res in (("off", a), ("on", b)):
            tr = _trace(res)
            sql = " ".join((tr.get("sql") or "").split())
            if sql:
                print(f"    {label} sql: " + textwrap.shorten(sql, 260, placeholder=" …"))
            elif res is not None and res.get("error"):
                print(f"    {label} err: " + textwrap.shorten(res['error'], 200, placeholder=" …"))
        print()

    known_off = sum(1 for x in r_off.values() if x.get("correct") is not None)
    known_on = sum(1 for x in r_on.values() if x.get("correct") is not None)
    acc_off = sum(1 for x in r_off.values() if x.get("correct"))
    acc_on = sum(1 for x in r_on.values() if x.get("correct"))
    both = [cid for cid in cases if cid in r_off and cid in r_on]
    acc_off_b = sum(1 for cid in both if r_off[cid].get("correct"))
    acc_on_b = sum(1 for cid in both if r_on[cid].get("correct"))
    print(f"accuracy  off={acc_off}/{known_off}  on={acc_on}/{known_on}"
          f"   on the {len(both)} cases BOTH cells ran: off={acc_off_b} on={acc_on_b}")
    print("flips     " + json.dumps(tally, ensure_ascii=False))
    if tally["unrun"]:
        print(f"          ({tally['unrun']} cases unrun in one cell — read the paired subset, "
              f"not the totals)")
    if not any(_trace(x) for x in list(r_off.values())[:3] + list(r_on.values())[:3]):
        print("\n(no trace.observation on these runs — recorded before 2026-08-14; the SQL "
              "each cell produced is not available, only the verdicts)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
