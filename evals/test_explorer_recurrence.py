#!/usr/bin/env python3
"""Does the explorer still generate degenerate 'all X = exactly Y' insights?

A stale pre-fix insight (Commerce__basket_composition__7, 2026-06-09) claimed "All orders
contained exactly 3 items" — FALSE (data is uniform 1-5 items). Its SQL used COUNT()/COUNT()
INTEGER division (→ avg=1.0) with no date filter, and the LLM narrated a single aggregate row
into a universal claim. This runs a FRESH domain-intel exploration on workspace and checks
whether NEW insights (generated after the snapshot) reproduce that class — universal-claim
language and/or the integer-division-of-counts SQL signature.
"""
from __future__ import annotations
import sys, os, re, asyncio
from pathlib import Path
_R = Path(__file__).parent.parent
sys.path.insert(0, str(_R))
try:
    from dotenv import load_dotenv; load_dotenv(_R / ".env")
except ImportError:
    pass
os.environ.setdefault("AUGHOR_FALLBACK_DISABLED", "1")

CONN = "samples"  # clean slate (0 prior insights) on the SAME ecommerce data → forces fresh generation
SNAPSHOT = ""      # samples starts empty, so every generated insight is new

_UNIVERSAL = re.compile(r"\b(all|every|each)\b[^.]*\bexactly\b", re.I)
_INT_DIV_COUNTS = re.compile(r"count\s*\([^)]*\)\s*/\s*count\s*\(", re.I)

# The PRECISE signal (not the language heuristic, which over-flags true-uniform synthetic
# data): does any stored insight's SQL still carry the grain-bug signature the fix skips?
_TC = {
    "products": ["product_id", "category", "unit_price", "weight_kg"],
    "order_items": ["item_id", "order_id", "product_id", "quantity", "unit_price"],
    "orders": ["order_id", "customer_id", "total_amount"],
    "customers": ["customer_id", "signup_date"], "reviews": ["review_id", "customer_id", "rating"],
    "ecommerce.products": ["product_id", "category", "weight_kg"],
    "ecommerce.order_items": ["item_id", "order_id", "product_id"],
    "ecommerce.orders": ["order_id", "customer_id"], "ecommerce.customers": ["customer_id"],
    "ecommerce.reviews": ["review_id", "customer_id", "rating"],
}


async def main():
    from aughor.db.connection import open_connection_for
    from aughor.explorer.agent import SchemaExplorer
    from aughor.explorer.store import get_insights

    before = get_insights(CONN)
    print(f"before: {len(before)} insights (latest {max((i.get('generated_at','') for i in before), default='?')})")
    print(f"running full explore() on {CONN} … (a few min — builds ontology + domain insights)\n")

    db = open_connection_for(CONN)
    ex = SchemaExplorer(CONN, db)
    await ex.explore(domain_intel_only=False)

    after = get_insights(CONN)
    new = [i for i in after if i.get("generated_at", "") > SNAPSHOT]
    print(f"after: {len(after)} insights; NEW this run: {len(new)}\n")

    from aughor.sql.fanout import integer_division_risk, count_star_entity_fanout
    grain_bug = []   # PRECISE: insight SQL still carries the grain-bug signature the fix skips
    for i in new:
        sql = str(i.get("sql") or "")
        reason = integer_division_risk(sql) or count_star_entity_fanout(sql, _TC)
        if reason:
            grain_bug.append((i.get("id"), reason, str(i.get("finding"))[:80]))

    print(f"NEW insights this run: {len(new)}")
    print(f"  — language 'all/each … exactly' (over-flags true-uniform synthetic data): "
          f"{sum(bool(_UNIVERSAL.search(str(i.get('finding') or ''))) for i in new)}")
    print(f"  — PRECISE grain-bug SQL signature (int-div / COUNT(*) parent fan-out): {len(grain_bug)}")
    for iid, reason, f in grain_bug:
        print(f"    ⚠ {iid}: {reason[:70]}\n        {f}")
    print("\n" + "=" * 70)
    if not new:
        print("VERDICT: INCONCLUSIVE — no new insights (already-covered angles skipped).")
    elif grain_bug:
        print(f"VERDICT: FIX FAILED — {len(grain_bug)} new insight(s) still carry the grain-bug SQL.")
    else:
        print(f"VERDICT: FIX HOLDS — {len(new)} new insights, 0 carry the grain-bug SQL signature "
              f"(int-div / COUNT(*) parent fan-out skipped before storage).")


if __name__ == "__main__":
    asyncio.run(main())
