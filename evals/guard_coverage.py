#!/usr/bin/env python3
"""Guard-coverage report — fire the deterministic guard battery over a prediction set on the REAL DBs.

Turns this session's deterministic capabilities from "tested" into "leveraged on the real path": for
each predicted SQL in a run directory, run the guards against the actual SQLite database and report
how often each catches a likely defect, with examples. Fully offline (no model) — uses existing
predictions + the local Spider2-Lite DBs.

Guards exercised:
  * CIDR-E1 trust checks   (aughor/sql/trust_checks)  — function-semantics footguns (pure AST + types),
  * grain / fan-out        (aughor/sql/grain_guard)   — live COUNT vs COUNT(DISTINCT) probe,
  * filter value-domain    (aughor/sql/join_guard)    — guessed enum/literal vs the live domain.

This is evidence for the CIDR-2026 claim that fan-out / missing-DISTINCT (E2) is the dominant real
error — measured on Aughor's own generated SQL, not a benchmark's gold.

Usage:
  python evals/guard_coverage.py --spider-root <spider2-lite> --pred <dir of local*.sql> [--examples 5]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
import spider2_lite as H                                   # loader + _sqlite_exec

from aughor.sql.trust_checks import run_trust_checks
from aughor.sql.grain_guard import detect_fanout


def _col_types(db_path: Path) -> dict:
    ct: dict = {}
    try:
        conn = sqlite3.connect(str(db_path))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            for _cid, name, typ, *_ in conn.execute(f'PRAGMA table_info("{t}")'):
                if name and typ:
                    ct[f"{t.lower()}.{name.lower()}"] = typ
                    ct.setdefault(name.lower(), typ)
        conn.close()
    except Exception:
        pass
    return ct


def _probe_factory(db_path: Path):
    def probe(sql: str):
        r = H._sqlite_exec(db_path, sql)
        return (r.ok, r.rows or [], r.error or "")
    return probe


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic guard coverage over a prediction set")
    ap.add_argument("--spider-root", required=True, type=Path)
    ap.add_argument("--pred", required=True, type=Path, help="dir of local*.sql predictions")
    ap.add_argument("--examples", type=int, default=5)
    args = ap.parse_args()

    instances = {r["instance_id"]: r for r in H.load_local_instances(args.spider_root)}
    pred_files = sorted(args.pred.glob("local*.sql"))

    n = 0
    fired = Counter()      # guard -> #predictions with >=1 finding
    total = Counter()      # guard -> total findings
    patt = Counter()       # trust pattern -> count
    material_grain = 0     # predictions with a grain finding whose ratio >= 1.5 (a real over-count)
    max_ratio = 0.0
    examples: dict = {"trust": [], "grain": [], "filter": []}

    for pf in pred_files:
        iid = pf.stem
        inst = instances.get(iid)
        if not inst:
            continue
        db_path = args.spider_root / "resource" / "databases" / f"{inst['db']}.sqlite"
        if not db_path.exists():
            continue
        sql = pf.read_text().strip()
        if not sql:
            continue
        n += 1
        col_types = _col_types(db_path)

        tf = run_trust_checks(sql, col_types=col_types, dialect="sqlite")
        if tf:
            fired["trust"] += 1
            total["trust"] += len(tf)
            for f in tf:
                patt[f.pattern] += 1
            if len(examples["trust"]) < args.examples:
                examples["trust"].append((iid, tf[0].pattern, tf[0].subject))

        try:
            gf = detect_fanout(sql, _probe_factory(db_path), dialect="sqlite")
        except Exception:
            gf = []
        if gf:
            fired["grain"] += 1
            total["grain"] += len(gf)
            top = max(f.ratio for f in gf)
            max_ratio = max(max_ratio, top)
            if top >= 1.5:
                material_grain += 1
            if len(examples["grain"]) < args.examples:
                examples["grain"].append((iid, gf[0].fanned_table, round(top, 2)))

        try:
            from aughor.connectors.file.sqlite import SQLiteConnection
            from aughor.sql.join_guard import check_filter_value_domains
            conn = SQLiteConnection(dsn=str(db_path), connection_id=f"cov_{iid}")
            ff = check_filter_value_domains(conn, sql)
            conn.close()
        except Exception:
            ff = []
        if ff:
            fired["filter"] += 1
            total["filter"] += len(ff)
            if len(examples["filter"]) < args.examples:
                examples["filter"].append((iid, ff[0].col, ff[0].bad_value, ff[0].suggestion))

    print(f"\nGuard coverage over {n} predictions in '{args.pred.name}'")
    print("=" * 64)
    for g in ("trust", "grain", "filter"):
        pct = (100.0 * fired[g] / n) if n else 0.0
        print(f"  {g:8s}: fired on {fired[g]:3d}/{n} ({pct:4.1f}%)   {total[g]} findings")
    print(f"  grain: {material_grain} with ratio>=1.5 (material over-count), max ratio {max_ratio:.2f}")
    print(f"  trust patterns: {dict(patt)}")
    print("\nExamples:")
    for g, exs in examples.items():
        for e in exs:
            print(f"  [{g:6s}] {e}")


if __name__ == "__main__":
    main()
