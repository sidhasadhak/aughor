"""Program AT Track 2 — show what the profiler decided about a schema, and why.

Run it against any connection/schema and it prints the four things Track 2 added, in the
order a sceptic would want them:

  1. CONFIDENT concepts, each with the layers that agreed and the numbers they agreed on;
  2. HINTS — one witness only, deliberately invisible to every prompt and consumer;
  3. DERIVED QUANTITIES — the arithmetic a table implies but does not store;
  4. the rendered annotation lines the agent actually reads.

    python scripts/show_concepts.py                       # workspace/data_co
    python scripts/show_concepts.py --conn 8d36d4c2       # a demo canvas
    python scripts/show_concepts.py --conn workspace --schema scm

Run it FROM THE REPO ROOT. The upload connector resolves its storage path relatively, so
running it elsewhere silently profiles nothing and prints clean, wrong zeros.

Profiles are cached by schema fingerprint. `--rebuild` forces a fresh scan when you have
changed profiler code and want to see the effect rather than the cache.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aughor.db.connection import open_connection_for_with_schema  # noqa: E402
from aughor.ontology.operations import caveat_for  # noqa: E402
from aughor.tools.concept import CONFIDENT, concept_of  # noqa: E402
from aughor.tools.profile_cache import get_or_build_profiles, invalidate  # noqa: E402
from aughor.tools.profiler import render_profile_annotations  # noqa: E402
from aughor.tools.schema import compute_join_map, parse_schema_tables  # noqa: E402
from aughor.tools.table_names import bare  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--conn", default="workspace")
    ap.add_argument("--schema", default="data_co")
    ap.add_argument("--rebuild", action="store_true", help="drop cached profiles first")
    args = ap.parse_args()

    db = open_connection_for_with_schema(args.conn, args.schema)
    print(f"connector : {type(db).__name__}  ({args.conn}/{args.schema})")

    base = db.get_schema()
    table_cols = parse_schema_tables(base)
    tables = [bare(t) for t in table_cols]
    if not tables:
        print("!! no tables — are you running from the repo root?")
        return 1
    fk_hints: dict = {t: set() for t in tables}
    for j in compute_join_map(table_cols).get("joins", []):
        fk_hints.setdefault(j["t1"], set()).add(j["c1"])

    if args.rebuild:
        invalidate(args.conn)
    t0 = time.time()
    tps, cps = get_or_build_profiles(db, args.conn, tables, fk_hints)
    print(f"profiled  : {len(cps)} columns in {len(tps)} tables, {time.time() - t0:.1f}s\n")

    confident = [c for c in cps.values() if concept_of(c.concept, c.concept_confidence)]
    hints = [c for c in cps.values() if c.concept and c.concept_confidence < CONFIDENT]

    print("=" * 78)
    print(f"1 · CONFIDENT CONCEPTS — {len(confident)} of {len(cps)} columns")
    print("    (two or more witness layers agreed; only these are acted on)")
    print("=" * 78)
    for cp in sorted(confident, key=lambda c: (c.table, c.column)):
        print(f"\n  {cp.table}.{cp.column}")
        print(f"     IS {cp.concept}  ({cp.concept_confidence:.2f})   —   {caveat_for(cp.concept)}")
        print(f"     semantic_type={cp.semantic_type}  unit={cp.unit or '-'}")
        for e in cp.concept_evidence:
            print(f"       · {e[:150]}")

    print("\n" + "=" * 78)
    print(f"2 · HINTS — {len(hints)} columns, ONE witness each")
    print("    (kept as information, invisible to prompts, and they drive nothing)")
    print("=" * 78)
    for cp in sorted(hints, key=lambda c: (c.table, c.column)):
        print(f"  {cp.column:<34} {cp.concept:<22} {cp.concept_confidence:.2f}")

    print("\n" + "=" * 78)
    print("3 · DERIVED QUANTITIES — arithmetic the table implies but does not store")
    print("=" * 78)
    any_derived = False
    for name, tp in sorted(tps.items()):
        for note in getattr(tp, "derived_quantities", None) or []:
            any_derived = True
            print(f"  [{name}] {note}")
    if not any_derived:
        print("  (none — no pair rule held on this schema)")

    print("\n" + "=" * 78)
    print("4 · WHAT THE AGENT READS — the concept lines in the profile annotation")
    print("=" * 78)
    for line in render_profile_annotations(tps, cps).splitlines():
        if "| IS " in line or "DERIVED QUANTITIES" in line or line.strip().startswith("·"):
            print("  " + line.strip()[:180])

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
