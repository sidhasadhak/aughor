#!/usr/bin/env python3
"""Lever D proof — does a SMALLER per-phase schema actually cut LLM latency?

Lever A (faster model) was falsified by measuring on real prompts. Same discipline
here BEFORE writing the trim: prove that shrinking the grounded schema the coder
sees actually reduces generation latency on the incumbent model + a real plan-prompt
shape. If latency is decode-bound (not prefill-bound), trimming input would barely
move it and Lever D's schema-cap would be a smaller win than hoped — better to learn
that from 6 calls than from an implementation.

Holds the model (incumbent) and the prompt SHAPE constant; varies only schema size.
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

os.environ["AUGHOR_FALLBACK_DISABLED"] = "1"  # no silent model swap

from aughor.db.connection import open_connection_for
from aughor.agent.investigate import _build_grounded_schema, _filter_schema
from aughor.agent.prompts_investigate import DIMENSIONAL_PLAN_PROMPT, PhasePlan
from aughor.llm.provider import get_provider
import re

CONN = "f809a5c6"  # the 75k-char warehouse where the bloat bites
RUNS = 2


def _cap_at_table_boundary(schema: str, budget: int) -> str:
    """Crude budget cap that respects TABLE: block boundaries (so the schema stays
    syntactically whole). Good enough to measure latency-vs-size."""
    if len(schema) <= budget:
        return schema
    blocks, cur = [], []
    for line in schema.splitlines():
        if line.startswith("TABLE:") or line.startswith("##"):
            if cur:
                blocks.append("\n".join(cur)); cur = []
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    out, total = [], 0
    for b in blocks:
        if total + len(b) > budget:
            break
        out.append(b); total += len(b) + 1
    return "\n".join(out) or schema[:budget]


def _plan_prompt(schema: str) -> str:
    return DIMENSIONAL_PLAN_PROMPT.format(
        question="why did revenue fall last month?",
        baseline_summary="Revenue fell 18% MoM, 2.4σ — significant.",
        decomposition_summary="Order count drove most of the drop; AOV roughly flat.",
        metric_label="revenue", metric_sql="SUM(cs_sales_price)",
        observation_period="last month", obs_start="2024-05-01", obs_end="2024-05-31",
        comp_start="2024-04-01", comp_end="2024-04-30",
        date_column="date_dim.d_date", metric_table="catalog_sales",
        schema=schema, dimensions_list="  - customer.c_customer_sk\n  - item.i_category",
    )


def main():
    db = open_connection_for(CONN)
    full = db.get_schema()
    grounded = _build_grounded_schema(full, "catalog_sales",
                                      ["customer.c_customer_sk", "item.i_category"],
                                      "date_dim.d_date", "why did revenue fall last month?")
    print(f"connection {CONN}: full={len(full)} grounded={len(grounded)} chars")
    coder = get_provider("coder")
    print(f"model: {coder._model}\n")

    variants = [
        ("grounded (today)", grounded),
        ("cap 20k", _cap_at_table_boundary(grounded, 20_000)),
        ("cap 12k", _cap_at_table_boundary(grounded, 12_000)),
        ("cap 8k", _cap_at_table_boundary(grounded, 8_000)),
    ]
    print(f"{'variant':20} {'schema':>8} {'med lat':>10} {'queries':>8}  ok")
    print("-" * 60)
    base_lat = None
    for label, sch in variants:
        lats, nq, ok = [], [], 0
        prompt = _plan_prompt(sch)
        for _ in range(RUNS):
            t0 = time.monotonic()
            try:
                r = coder.complete(
                    system="Write contribution-analysis SQL for each dimension.",
                    user=prompt, response_model=PhasePlan)
                lats.append((time.monotonic() - t0) * 1000)
                n = len(getattr(r, "queries", []) or [])
                nq.append(n)
                if n:
                    ok += 1
            except Exception as e:
                print(f"{label:20} {len(sch):>8} ERROR {str(e)[:50]}")
                lats = []
                break
        if not lats:
            continue
        med = statistics.median(lats)
        if base_lat is None:
            base_lat = med
        delta = f"  ({(med-base_lat)/base_lat*100:+.0f}%)" if base_lat and label != variants[0][0] else ""
        print(f"{label:20} {len(sch):>8} {med:>8.0f}ms {str(nq):>8}  {ok}/{RUNS}{delta}")


if __name__ == "__main__":
    main()
