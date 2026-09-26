#!/usr/bin/env python3
"""TJ-3's audit sheet: the labelled runs a person audits before bronze is fuel.

Reads the SERVING API only (never a store — one writer per data/), and writes a CSV beside
the census with the label, its reasons and blank columns for the auditor's verdict, the
failure class and a note. §3.47: 50–100 bronze rows, the sheet committed with its precision.

Usage: python scripts/tj3_audit_sheet.py [--api http://127.0.0.1:8000] [--days 30] [--limit 100] [--out docs/TJ3_AUDIT_<date>.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from datetime import date
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default=f"docs/TJ3_AUDIT_{date.today().isoformat()}.csv")
    args = ap.parse_args()
    url = f"{args.api}/learning/run-labels?days={args.days}&limit={args.limit}&rows=true"
    body = json.load(urllib.request.urlopen(url, timeout=600))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["trace_id", "kind", "completed_at", "connection_id", "question", "sql", "label", "reasons",
                    "evidence", "auditor_verdict", "failure_class", "note"])
        for r in body.get("rows", []):
            w.writerow([r["trace_id"], r.get("kind"), r.get("completed_at"), r.get("connection_id"), r.get("question"),
                        r.get("sql"), r["label"], " | ".join(r.get("reasons") or []),
                        json.dumps(r.get("evidence") or {}, sort_keys=True), "", "", ""])
    print(f"{out}: {len(body.get('rows', []))} rows; distribution {body['counts']}; discriminating={body['discriminating']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
