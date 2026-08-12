"""CI-0 scorecard — re-measure the mechanical-feel markers after each Arc CI wave.

Reads the local investigations store the way the 2026-08-12 baseline did
(docs/CI0_TRANSCRIPT_READING_2026-08-12.md) so successive readings are
comparable. Run:  uv run python scripts/ci0_scorecard.py [path-to-history.db]

Success for Arc CI is these numbers trending toward zero (except the last one,
which should climb) — judged alongside a fresh close-read of recent prose, not
instead of it.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/history.db")


def main() -> None:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT question, headline, report_json, started_at FROM investigations "
        "WHERE report_json IS NOT NULL"
    ).fetchall()

    quick_n = deep_n = q_no_prose = leak = 0
    d_fallback = d_empty_recs = d_low = 0
    dup_q: Counter[str] = Counter()

    for r in rows:
        try:
            rep = json.loads(r["report_json"])
        except Exception:
            continue
        dup_q[(r["question"] or "").strip().lower()] += 1
        h = str(rep.get("headline") or "")
        if "RELEVANT SQL" in h or "\n" in h or "──" in h or h.startswith(("⚠", "This finding's scan touched")):
            leak += 1
        if rep.get("_report_type") or rep.get("executive_summary"):
            deep_n += 1
            if "Narrative synthesis was unavailable" in str(rep.get("confidence_justification") or ""):
                d_fallback += 1
            if not rep.get("recommendations"):
                d_empty_recs += 1
            if str(rep.get("confidence") or "").upper() == "LOW":
                d_low += 1
        else:
            quick_n += 1
            ins = rep.get("insight")
            narrative = (ins or {}).get("narrative") if isinstance(ins, dict) else (ins or "")
            if not str(narrative or "").strip():
                q_no_prose += 1

    repeats = sum(1 for q, n in dup_q.items() if q and n >= 3)

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.0f}%" if d else "n/a"

    print(f"corpus: {quick_n} quick turns, {deep_n} deep reports ({DB})")
    print(f"quick turns with zero prose:          {q_no_prose:5}  {pct(q_no_prose, quick_n)}")
    print(f"internal text leaked into headlines:  {leak:5}")
    print(f"questions asked 3+ times:             {repeats:5}")
    print(f"deep: deterministic fallback:         {d_fallback:5}  {pct(d_fallback, deep_n)}")
    print(f"deep: zero recommendations:           {d_empty_recs:5}  {pct(d_empty_recs, deep_n)}")
    print(f"deep: confidence LOW:                 {d_low:5}  {pct(d_low, deep_n)}")
    try:
        from aughor.obs import session_log
        rm = session_log.route_mix()
        print(f"converse-served turns (lifetime):     {rm.get('converse_turns', 0):5}")
    except Exception:
        print("converse-served turns:                  n/a (route receipt unavailable)")


if __name__ == "__main__":
    main()
