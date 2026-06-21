#!/usr/bin/env python3
"""R4 — Semantic-layer ablation eval.

Measures the SAFETY value of Aughor's governed layer, not just its accuracy, on a real
warehouse. The MotherDuck thesis, made measurable: *a governed-layer failure is an error
message; a text-to-SQL failure is a plausible wrong answer.* So we don't just ask "is it
right?" — we ask "when it's wrong, is it SILENTLY wrong (a plausible un-flagged number) or
CAUGHT (flagged/repaired)?"

Three arms run on the SAME question against the SAME warehouse:

  * **raw**       — schema-only NL→SQL (`generate_sql_chat`): an LLM + the schema, no guards.
                    This is what a thin text-to-SQL agent produces.
  * **guarded**   — the raw SQL run through Aughor's DETERMINISTIC guard battery (the
                    Verifier): fan-out de-fan (a rewrite) + id-arithmetic, ratio-of-sums,
                    and value-domain detectors (which flag → the product repairs/caveats).
                    This isolates the durable moat — pure, reproducible, no LLM drift.
  * **injected**  — the full intelligence-injected pipeline (`generate_sql_full_pipeline`:
                    exploration annotations + KB + metrics + de-fan + retry). Included to
                    surface, honestly, that LLM-DERIVED context is a SEPARATE axis that can
                    drift (the documented #13 confound the eval infra's frozen-state guard
                    gates against) — which is exactly why the *deterministic* layer is the moat.

Outcome classes:
  * raw / injected : correct | silent-wrong | error
  * guarded        : correct | caught (a guard fired → flagged, never silently wrong)
                     | silent-wrong (slipped past every guard) | error

Usage:
    uv run python evals/ablation_eval.py --output evals/ablation_missimi_results.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from evals.run_golden import generate_sql_chat, generate_sql_full_pipeline
from evals.sql_accuracy import score_single
from aughor.db.connection import open_connection_for, open_connection_for_with_schema

_MATCH = 0.99  # result-set match threshold for "correct"


def _quiet(fn, default):
    """Run fn(); on any failure return default. A return (not pass), so it never becomes a
    silent-swallow — and one guard hiccup never aborts the eval."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — eval harness: degrade, don't crash
        return default


def apply_guards(raw_sql: str, db, tcols: dict) -> tuple[str, list[str]]:
    """Aughor's DETERMINISTIC guard battery (the Verifier) over an arbitrary SQL — the
    same guards `_stream_chat` runs. Fan-out is a deterministic de-fan REWRITE; the others
    are detectors whose firing means the product flags/repairs the query (never a silent
    wrong answer). Returns (sql_after_rewrites, fired_guards)."""
    from aughor.sql.fanout import detect_fanout, defan, measure_times_key_arithmetic, avg_of_row_ratios
    from aughor.sql.join_guard import check_filter_value_domains

    fired: list[str] = []
    sql = raw_sql

    # Fan-out: detect → deterministic de-fan rewrite (adopt only if it binds).
    ff = _quiet(lambda: detect_fanout(sql, tcols, db.dialect), None)
    if ff:
        fired.append("fanout")
        rw = _quiet(lambda: defan(sql, ff, db.dialect), None)
        if rw and rw.strip() != sql.strip() and _quiet(lambda: db.dry_run(rw)[0], False):
            sql = rw

    # id-arithmetic + ratio-of-sums: detectors return a hint string (→ the product
    # regenerates with it). Firing = the trap is flagged.
    for fn, name in ((measure_times_key_arithmetic, "id_arithmetic"), (avg_of_row_ratios, "ratio_of_sums")):
        if _quiet(lambda fn=fn: fn(sql, tcols, db.dialect), None):
            fired.append(name)

    # Value-domain: a filter literal absent from the column's domain (the silent-zero).
    if _quiet(lambda: check_filter_value_domains(db, sql), []):
        fired.append("value_domain")

    return sql.strip(), fired


def _classify_plain(score: dict, sql: str | None) -> str:
    if not sql:
        return "error"
    if (score.get("error") or "").startswith("Generation") or not score.get("execution_success", 0.0):
        return "error"
    if score.get("result_set_match", 0.0) >= _MATCH and score.get("row_count_match", 0.0) >= _MATCH:
        return "correct"
    return "silent-wrong"


def _classify_guarded(score: dict, sql: str | None, fired: list[str]) -> str:
    if not sql:
        return "error"
    if (score.get("error") or "").startswith("Generation") or not score.get("execution_success", 0.0):
        return "caught" if fired else "error"      # a guard fired but the rewrite didn't bind → still flagged
    if score.get("result_set_match", 0.0) >= _MATCH and score.get("row_count_match", 0.0) >= _MATCH:
        return "correct"
    return "caught" if fired else "silent-wrong"    # flagged (safe) vs slipped past every guard (dangerous)


def run(dataset: str, limit: int | None, output: str | None) -> dict:
    records = [json.loads(line) for line in open(dataset) if line.strip()]
    if limit:
        records = records[:limit]

    conn_id = records[0].get("connection_id", "samples")
    schema_name = records[0].get("schema")
    db = (open_connection_for_with_schema(conn_id, schema_name) if schema_name
          else open_connection_for(conn_id))
    schema_text = _quiet(db.get_schema, "")
    from aughor.tools.schema import _parse_schema_tables
    tcols = _quiet(lambda: _parse_schema_tables(schema_text), {})

    print(f"\n{'='*72}\n R4 · Semantic-layer ablation  |  {conn_id}"
          f"{('/' + schema_name) if schema_name else ''}  ({len(records)} questions)\n{'='*72}", flush=True)

    rows = []
    for i, rec in enumerate(records, 1):
        q = rec["question"]
        print(f"  [{i}/{len(records)}] {rec['id']} ({rec.get('trap')}) ...", file=sys.stderr, flush=True)
        t0 = time.time()

        raw_sql = _quiet(lambda: generate_sql_chat(q, conn_id, schema_text), None)
        raw_score = score_single(db, rec, raw_sql) if raw_sql else {"error": "Generation failed", "execution_success": 0.0}
        raw_cls = _classify_plain(raw_score, raw_sql)

        guarded_sql, fired = apply_guards(raw_sql, db, tcols) if raw_sql else (None, [])
        g_score = score_single(db, rec, guarded_sql) if guarded_sql else {"error": "Generation failed", "execution_success": 0.0}
        g_cls = _classify_guarded(g_score, guarded_sql, fired)

        inj_sql = _quiet(lambda: generate_sql_full_pipeline(q, conn_id, db), None)
        inj_score = score_single(db, rec, inj_sql) if inj_sql else {"error": "Generation failed", "execution_success": 0.0}
        inj_cls = _classify_plain(inj_score, inj_sql)

        rows.append({
            "id": rec["id"], "trap": rec.get("trap"), "question": q,
            "raw": {"sql": raw_sql, "class": raw_cls, "match": round(raw_score.get("result_set_match", 0.0), 3)},
            "guarded": {"sql": guarded_sql, "class": g_cls, "guards_fired": fired,
                        "match": round(g_score.get("result_set_match", 0.0), 3)},
            "injected": {"sql": inj_sql, "class": inj_cls, "match": round(inj_score.get("result_set_match", 0.0), 3)},
            "latency_s": round(time.time() - t0, 1),
        })
    db.close()

    summary = _summarize(rows)
    _print_report(rows, summary)
    if output:
        Path(output).write_text(json.dumps({"results": rows, "summary": summary}, indent=2, default=str))
        print(f"\nResults → {output}")
    return {"results": rows, "summary": summary}


def _summarize(rows: list[dict]) -> dict:
    raw_c = Counter(r["raw"]["class"] for r in rows)
    g_c = Counter(r["guarded"]["class"] for r in rows)
    inj_c = Counter(r["injected"]["class"] for r in rows)
    n = len(rows) or 1
    # the moat: raw silent-wrongs that the guard battery converts to correct or caught
    saves = [r["id"] for r in rows if r["raw"]["class"] == "silent-wrong" and r["guarded"]["class"] in ("correct", "caught")]
    regressions = [r["id"] for r in rows if r["raw"]["class"] == "correct" and r["guarded"]["class"] not in ("correct", "caught")]
    return {
        "n": len(rows),
        "raw": dict(raw_c), "guarded": dict(g_c), "injected": dict(inj_c),
        "raw_accuracy": round(raw_c["correct"] / n, 3),
        "guarded_safe_rate": round((g_c["correct"] + g_c["caught"]) / n, 3),   # correct OR flagged = never silently wrong
        "injected_accuracy": round(inj_c["correct"] / n, 3),
        "raw_silent_wrong": raw_c["silent-wrong"],
        "guarded_silent_wrong": g_c["silent-wrong"],
        "injected_silent_wrong": inj_c["silent-wrong"],
        "saves": saves, "regressions": regressions,
    }


def _print_report(rows: list[dict], s: dict) -> None:
    print(f"\n{'id':24}{'trap':13}{'raw':>13}{'guarded':>13}{'injected':>13}")
    print("-" * 76)
    for r in rows:
        g = r["guarded"]
        tail = f"  ⟵ {','.join(g['guards_fired'])}" if g["guards_fired"] else ""
        print(f"{r['id']:24}{str(r['trap']):13}{r['raw']['class']:>13}{g['class']:>13}{r['injected']['class']:>13}{tail}")
    print("-" * 76)
    print(f"\n  Raw            : {s['raw_accuracy']:.0%} correct   {s['raw']}")
    print(f"  Guarded        : {s['guarded_safe_rate']:.0%} SAFE (correct+caught)   {s['guarded']}")
    print(f"  Injected       : {s['injected_accuracy']:.0%} correct   {s['injected']}")
    print(f"\n  SILENT-WRONG   : raw {s['raw_silent_wrong']}  →  guarded {s['guarded_silent_wrong']}"
          f"   (a silent-wrong is a plausible, un-flagged wrong answer)")
    print(f"  Saves (raw silent-wrong → guarded correct/caught): {len(s['saves'])}  {s['saves']}")
    print(f"  Regressions (raw correct → guarded not-safe)     : {len(s['regressions'])}  {s['regressions']}")
    print(f"  Injection confound (injected silent-wrong)       : {s['injected_silent_wrong']}  "
          f"(LLM-derived context drift — why FULL runs are frozen-state gated)")
    print("=" * 76)


# ── Deterministic guard-efficacy demo ────────────────────────────────────────────
# The headline evidence: the EXACT plausible-wrong SQL a naive text-to-SQL agent writes,
# executed unguarded (→ a clean, plausible, WRONG number), then through the guard battery
# (→ corrected or flagged). No LLM — fully reproducible. These are the answers that "look
# right and are wrong" — the class a governed layer exists to make impossible to ship silently.
_CANONICAL_TRAPS = [
    {
        "trap": "fan-out (chasm)",
        "naive": "SELECT ROUND(SUM(o.order_value),2) AS revenue FROM missimi.orders o "
                 "JOIN missimi.order_items oi ON o.order_id = oi.order_id",
        "true": "SELECT ROUND(SUM(order_value),2) FROM missimi.orders",
        "why": "order_value is order-grain; the join to order_items repeats it per line",
    },
    {
        "trap": "value-domain (silent zero)",
        "naive": "SELECT COUNT(*) AS n FROM missimi.orders WHERE order_status = 'cancelled'",
        "true": "SELECT COUNT(*) FROM missimi.orders WHERE order_status = 'canceled'",
        "why": "the stored literal is 'canceled' (one L); the typo'd filter matches no rows",
    },
    {
        "trap": "id-arithmetic (fabrication)",
        "naive": "SELECT ROUND(SUM(unit_price * order_item_id),2) AS revenue FROM missimi.order_items",
        "true": "SELECT ROUND(SUM(unit_price),2) FROM missimi.order_items",
        "why": "order_item_id is a key, not a quantity; multiplying by it fabricates a magnitude",
    },
]


def demo_traps(conn_id: str = "workspace", schema: str = "missimi") -> list[dict]:
    """Run each canonical trap unguarded vs guarded and report the numbers."""
    db = open_connection_for_with_schema(conn_id, schema)
    tcols = _quiet(lambda: __import__("aughor.tools.schema", fromlist=["_parse_schema_tables"])._parse_schema_tables(db.get_schema()), {})

    def _scalar(sql):
        r = db.execute("__trap__", sql)
        if r.error or not r.rows:
            return f"<error: {r.error}>" if r.error else "<no rows>"
        return r.rows[0][0]

    out = []
    print(f"\n{'='*72}\n Deterministic guard-efficacy on the canonical traps  ({conn_id}/{schema})\n{'='*72}")
    print(f"{'trap':28}{'naive (unguarded)':>20}{'guarded':>20}\n{'-'*72}")
    for t in _CANONICAL_TRAPS:
        naive_val = _scalar(t["naive"])
        guarded_sql, fired = apply_guards(t["naive"], db, tcols)
        # the value-domain/id-arith guards flag (don't rewrite) → the guarded answer is the
        # FLAGGED state; we show the corrected (true) value the repair produces.
        rewrote = guarded_sql.strip() != t["naive"].strip()
        guarded_val = _scalar(guarded_sql) if rewrote else (f"⚑ flagged ({','.join(fired)})")
        true_val = _scalar(t["true"])
        out.append({"trap": t["trap"], "naive": naive_val, "guarded": guarded_val,
                    "true": true_val, "fired": fired, "rewrote": rewrote, "why": t["why"]})
        print(f"{t['trap']:28}{str(naive_val):>20}{str(guarded_val):>20}   true={true_val}")
    print("-" * 72)
    print("  Every 'naive' value executes cleanly and looks plausible — and is wrong.")
    print("=" * 72)
    db.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="evals/ablation_missimi.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--traps", action="store_true", help="Run only the deterministic guard-efficacy demo (no LLM)")
    args = ap.parse_args()
    if args.traps:
        demo_traps()
        return
    run(args.dataset, args.limit, args.output)


if __name__ == "__main__":
    main()
