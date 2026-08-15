"""Re-score a reference suite from the Trust-Receipt ledger with the CURRENT comparator.

    AUGHOR_SYSTEM_DB=$PWD/data/system.db \\
      .venv/bin/python scripts/rescore_suite_from_receipts.py <suite_id> <connection_id>

Why: an eval run's `correct` verdicts are frozen at the comparator that was imported when
the run started. When the comparator itself is repaired (2026-08-14: cents-level rounding
and label-preserving dropped measures were false NEGATIVES — the checker, not the model,
produced the miss), every earlier verdict is stale. The ledger keeps the SQL each answer
actually ran (`chat_answer` artifacts), so a suite can be re-judged without re-spending a
single LLM request: execute the recorded SQL, compare to the reference, print the diff.

Prints one line per case that has a receipt — [OK]/[BAD] with the produced SQL for BADs —
and a summary. Cases without a receipt are listed as unanswered, not scored.
"""
from __future__ import annotations

import os
import sys

if not os.environ.get("AUGHOR_SYSTEM_DB"):
    sys.exit("set AUGHOR_SYSTEM_DB (a bare script does not load conftest's isolation)")

from aughor.custom_agents.quality import results_match  # noqa: E402
from aughor.db.connection import open_connection_for  # noqa: E402
from aughor.evals import store  # noqa: E402
from aughor.kernel.ledger import Ledger  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    suite_id, conn_id = argv[1], argv[2]
    cases = {c["question"]: c for c in store.list_cases(suite_id, limit=1000)}
    con = open_connection_for(conn_id)._conn

    # Newest receipt per question wins (a re-run supersedes an older answer).
    latest: dict[str, dict] = {}
    for a in Ledger.default().artifacts_of_kind("chat_answer", limit=2000):
        p = a.get("payload") or {}
        q = p.get("question") or ""
        if q in cases and q not in latest and (a.get("conn_id") in (None, "", conn_id)):
            latest[q] = p

    ok = bad = 0
    for q, case in cases.items():
        p = latest.get(q)
        if p is None:
            print(f"[--- ] {q}  (no receipt yet)")
            continue
        exp = case.get("expected") or {}
        refs = [s for s in [exp.get("reference_sql"), *(exp.get("accept_sql") or [])] if s]
        sql = p.get("sql") or ""
        try:
            got = [list(x) for x in con.execute(sql).fetchall()]
            err = ""
        except Exception as exc:
            got, err = [], f"{type(exc).__name__}: {str(exc)[:160]}"
        hit = False
        for r in refs:
            try:
                ref_rows = [list(x) for x in con.execute(r).fetchall()]
            except Exception:
                continue
            if results_match(ref_rows, got):
                hit = True
                break
        if hit:
            ok += 1
            print(f"[OK  ] {q}")
        else:
            bad += 1
            print(f"[BAD ] {q}")
            print("       sql:", " ".join(sql.split())[:320])
            if err:
                print("       err:", err)
            else:
                print("       got:", got[:3])
                try:
                    print("       ref:", [list(x) for x in con.execute(refs[0]).fetchall()[:3]])
                except Exception:
                    pass
    scored = ok + bad
    print(f"\nre-scored {scored}/{len(cases)} answered cases: correct={ok} wrong={bad}"
          + (f"  accuracy={ok / scored:.0%}" if scored else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
