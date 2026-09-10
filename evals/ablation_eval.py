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
  * **ontology**  — raw schema + ONLY the verified ontology blocks (ENTITY MODEL, ENTITY
                    RELATIONSHIPS, VERIFIED SEMANTIC LAYER — `ontology_context` below), no
                    exploration findings, no KB, no metrics catalog. Arc ON's own arm (ROADMAP
                    §3.15 ON-0): the 2026-06-21 run could only say "injected context regressed",
                    never whether the ONTOLOGY was the part that did. This arm can.
  * **ontology_guarded** — the ontology arm's SQL through the same guard battery. If the
                    blocks teach cardinality upstream, the guards should fire LESS here than
                    on `guarded` — by-construction beating by-guard, measured.
  * **injected**  — the full intelligence-injected pipeline (`generate_sql_full_pipeline`:
                    exploration annotations + KB + metrics + de-fan + retry). Included to
                    surface, honestly, that LLM-DERIVED context is a SEPARATE axis that can
                    drift (the documented #13 confound the eval infra's frozen-state guard
                    gates against) — which is exactly why the *deterministic* layer is the moat.

Before any model is called, every record's reference SQL (and each `accept_sql`) is EXECUTED;
a record whose reference fails is skipped and listed, never scored — a dataset-authoring
error must not read as a model failure, and must not spend tokens.

Outcome classes:
  * raw / injected : correct | silent-wrong | error
  * guarded        : correct | caught (a guard fired → flagged, never silently wrong)
                     | silent-wrong (slipped past every guard) | error

Usage:
    uv run python evals/ablation_eval.py --output evals/ablation_missimi_results.json
    uv run python evals/ablation_eval.py --dataset evals/ablation_missimi.jsonl \
        --dataset evals/ablation_missimi_hard.jsonl --arms raw,guarded,ontology,ontology_guarded
    uv run python evals/ablation_eval.py --check-references --dataset evals/ablation_samples_ecommerce.jsonl
    # Beside a SERVING API: redirect the stores (one writer per data/) and hand the arm the
    # graph the API serves — the store is system.db, and a redirected store holds no ontology.
    AUGHOR_SYSTEM_DB=/tmp/scratch/system.db uv run python evals/ablation_eval.py \
        --dataset evals/ablation_samples_ecommerce.jsonl \
        --graph-json samples/ecommerce=/tmp/samples_ecommerce.json   # GET /ontology?connection_id=samples&schema_name=ecommerce
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Skipped when the caller has declared it wants a clean environment. This runs at
# IMPORT, so a test that imports anything from this module gets the developer's `.env`
# in its process — which is how a suite that is green in CI fails on a laptop.
if not os.environ.get("AUGHOR_SKIP_DOTENV"):
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


ARMS: tuple[str, ...] = ("raw", "guarded", "ontology", "ontology_guarded", "injected")
_NO_SQL = {"error": "Generation failed", "execution_success": 0.0}


def ontology_context(graph, schema_text: str, tcols: dict) -> str:
    """The verified ontology blocks, exactly as the product renders them, and nothing else.

    ENTITY MODEL (schema-wide, the heavy-phase annotator), ENTITY RELATIONSHIPS
    (existence-bound to this schema's tables) and the VERIFIED SEMANTIC LAYER (scoped here
    to every table the schema carries, since the arm has no linker). '' when the connection
    has no built ontology — and the caller SAYS so rather than quietly running raw twice.
    """
    if graph is None:
        return ""
    from aughor.ontology.builder import render_ontology_annotations
    from aughor.ontology.semantic_block import render_relationship_block, render_semantic_layer
    blocks = [
        _quiet(lambda: render_ontology_annotations(graph), ""),
        _quiet(lambda: render_relationship_block(graph, tcols), ""),
        _quiet(lambda: render_semantic_layer(graph, list(tcols)), ""),
    ]
    return "\n\n".join(b for b in blocks if b)


def check_references(db, records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Execute every reference (and accept_sql) BEFORE any model call.

    Returns (scorable, failed). A failed record carries the error so the author can fix
    the dataset; it is never scored, so it can never masquerade as a model failure.
    """
    from evals.sql_accuracy import _safe_exec
    ok_rows, bad_rows = [], []
    for rec in records:
        ref_ok, _c, ref_rows, err = _safe_exec(db, rec.get("reference_sql", ""))
        if not ref_ok:
            bad_rows.append({"id": rec["id"], "error": str(err)[:300], "which": "reference_sql"})
            continue
        broken_alts = []
        for i, alt in enumerate(rec.get("accept_sql") or [], start=1):
            alt_ok, _c2, _r2, alt_err = _safe_exec(db, alt)
            if not alt_ok:
                broken_alts.append({"accept_sql": i, "error": str(alt_err)[:200]})
        rec = dict(rec)
        rec["_reference_rows"] = len(ref_rows)
        if broken_alts:
            rec["_broken_accept_sql"] = broken_alts
        ok_rows.append(rec)
    return ok_rows, bad_rows


def _load_graph(conn_id: str, schema_name: str | None,
                graph_json: dict[str, str] | None = None) -> tuple[object | None, str]:
    """The ontology graph for this dataset, and where it came from.

    `--graph-json` maps a dataset label (`conn` or `conn/schema`) to a file holding the
    JSON of `GET /ontology?connection_id=…&schema_name=…` — the graph WITH the human
    overrides overlaid, exactly what the product's chat path reads. That door exists
    because the ontology store IS `system.db`: a bare run beside the serving API has to
    redirect `AUGHOR_SYSTEM_DB` (one writer per data/), and a redirected store holds no
    ontology, so the arm would quietly equal raw. Without a mapping, the store is read.
    """
    label = f"{conn_id}/{schema_name}" if schema_name else conn_id
    path = (graph_json or {}).get(label) or (graph_json or {}).get(conn_id)
    if path:
        from aughor.ontology.models import OntologyGraph
        graph = OntologyGraph.model_validate(json.loads(Path(path).read_text()))
        return graph, f"file:{path}"
    from aughor.ontology.store import load_latest_ontology
    return _quiet(lambda: load_latest_ontology(conn_id, schema_name), None), "store"


def _arms_after_ontology_check(arms: tuple[str, ...], onto_ctx: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Drop the ontology arms when there is nothing to inject.

    An `ontology` arm with an empty block is the raw arm under another name: running it
    spends a model call per question to measure a difference that cannot exist, and the
    table then shows two equal columns that LOOK like a finding. Returns (arms, dropped).
    """
    if "ontology" not in arms or onto_ctx:
        return arms, ()
    dropped = tuple(a for a in ("ontology", "ontology_guarded") if a in arms)
    return tuple(a for a in arms if a not in dropped), dropped


def _llm_identity() -> dict:
    """Which model answers — written into every summary.

    A dated table that does not name its model is a catalogue without a timestamp: the
    2026-06-21 run's `raw 92%` cannot be compared with anything because nobody wrote down
    what produced it. Resolved from config with no network call, through the same seam
    `/health` reads. `fallback_chain` is what a throttled primary would fall over to —
    empty means a throttled call becomes an `error` row, never another model's answer
    counted as this arm's (pin it with AUGHOR_FALLBACK_BACKENDS=none for a clean run).
    """
    try:
        from aughor.llm import provider
        backend, model, _base_url = provider.resolve_binding("coder")
        return {"backend": backend, "model": model, "role": "coder",
                "fallback_chain": list(provider._fallback_backends())}
    except Exception as exc:  # noqa: BLE001 — identity is a receipt, never a reason to abort
        return {"backend": None, "model": None, "role": "coder", "fallback_chain": None,
                "error": f"{type(exc).__name__}: {exc}"[:200]}


def run(dataset: str, limit: int | None, output: str | None,
        arms: tuple[str, ...] = ARMS, check_only: bool = False,
        graph_json: dict[str, str] | None = None) -> dict:
    records = [json.loads(line) for line in open(dataset) if line.strip()]
    if limit:
        records = records[:limit]
    arms = tuple(a for a in ARMS if a in arms)          # canonical order, unknown names dropped
    if "guarded" in arms and "raw" not in arms:
        arms = ("raw",) + arms
    if "ontology_guarded" in arms and "ontology" not in arms:
        arms = tuple(a for a in ARMS if a in arms or a == "ontology")

    conn_id = records[0].get("connection_id", "samples")
    schema_name = records[0].get("schema")
    db = (open_connection_for_with_schema(conn_id, schema_name) if schema_name
          else open_connection_for(conn_id))
    schema_text = _quiet(db.get_schema, "")
    from aughor.db.schema_render import parse_schema_tables
    tcols = _quiet(lambda: parse_schema_tables(schema_text), {})

    label = f"{conn_id}{('/' + schema_name) if schema_name else ''}"
    llm = _llm_identity()
    print(f"\n{'='*76}\n R4/ON-0 · Semantic-layer ablation  |  {label}  ({len(records)} questions)"
          f"\n arms: {', '.join(arms)}"
          f"\n model: {llm.get('backend')} · {llm.get('model')} · fallback chain: "
          f"{llm.get('fallback_chain') or 'none'}\n{'='*76}", flush=True)

    scorable, failed = check_references(db, records)
    if failed:
        print(f"  ⚠ {len(failed)} record(s) whose reference SQL does not execute — SKIPPED, not scored:")
        for f in failed:
            print(f"      {f['id']}: {f['error']}")
    if check_only:
        print(f"  references OK: {len(scorable)}  failed: {len(failed)}")
        for r in scorable:
            note = f"   ⚠ broken accept_sql: {r['_broken_accept_sql']}" if r.get("_broken_accept_sql") else ""
            print(f"      {r['id']:28} {r['_reference_rows']:>6} row(s){note}")
        db.close()
        return {"dataset": dataset, "connection": label, "reference_failed": failed,
                "reference_ok": [r["id"] for r in scorable]}

    wanted_ontology = "ontology" in arms
    graph, graph_source = _load_graph(conn_id, schema_name, graph_json) if wanted_ontology else (None, None)
    onto_ctx = ontology_context(graph, schema_text, tcols) if wanted_ontology else ""
    arms, dropped = _arms_after_ontology_check(arms, onto_ctx)
    if dropped:
        print(f"  ⚠ no built ontology for {label} (source: {graph_source}) — the `ontology` arm would "
              f"equal raw, so {list(dropped)} are DROPPED, not spent on. Build intelligence first "
              f"(POST /ontology/rebuild), or pass --graph-json {label}=<the JSON of GET /ontology>.")
    onto_schema = (schema_text + "\n\n" + onto_ctx) if onto_ctx else schema_text

    rows = []
    for i, rec in enumerate(scorable, 1):
        q = rec["question"]
        print(f"  [{i}/{len(scorable)}] {rec['id']} ({rec.get('trap')}) ...", file=sys.stderr, flush=True)
        t0 = time.time()
        row: dict = {"id": rec["id"], "trap": rec.get("trap"), "question": q}

        if "raw" in arms:
            raw_sql = _quiet(lambda: generate_sql_chat(q, conn_id, schema_text), None)
            raw_score = score_single(db, rec, raw_sql) if raw_sql else dict(_NO_SQL)
            row["raw"] = {"sql": raw_sql, "class": _classify_plain(raw_score, raw_sql),
                          "match": round(raw_score.get("result_set_match", 0.0), 3)}
            if "guarded" in arms:
                g_sql, fired = apply_guards(raw_sql, db, tcols) if raw_sql else (None, [])
                g_score = score_single(db, rec, g_sql) if g_sql else dict(_NO_SQL)
                row["guarded"] = {"sql": g_sql, "class": _classify_guarded(g_score, g_sql, fired),
                                  "guards_fired": fired,
                                  "match": round(g_score.get("result_set_match", 0.0), 3)}

        if "ontology" in arms:
            o_sql = _quiet(lambda: generate_sql_chat(q, conn_id, onto_schema), None)
            o_score = score_single(db, rec, o_sql) if o_sql else dict(_NO_SQL)
            row["ontology"] = {"sql": o_sql, "class": _classify_plain(o_score, o_sql),
                               "match": round(o_score.get("result_set_match", 0.0), 3)}
            if "ontology_guarded" in arms:
                og_sql, o_fired = apply_guards(o_sql, db, tcols) if o_sql else (None, [])
                og_score = score_single(db, rec, og_sql) if og_sql else dict(_NO_SQL)
                row["ontology_guarded"] = {"sql": og_sql,
                                           "class": _classify_guarded(og_score, og_sql, o_fired),
                                           "guards_fired": o_fired,
                                           "match": round(og_score.get("result_set_match", 0.0), 3)}

        if "injected" in arms:
            inj_sql = _quiet(lambda: generate_sql_full_pipeline(q, conn_id, db), None)
            inj_score = score_single(db, rec, inj_sql) if inj_sql else dict(_NO_SQL)
            row["injected"] = {"sql": inj_sql, "class": _classify_plain(inj_score, inj_sql),
                               "match": round(inj_score.get("result_set_match", 0.0), 3)}

        row["latency_s"] = round(time.time() - t0, 1)
        rows.append(row)
    db.close()

    summary = _summarize(rows, arms)
    summary["dataset"] = dataset
    summary["connection"] = label
    summary["reference_failed"] = failed
    summary["llm"] = llm
    summary["ontology_available"] = bool(onto_ctx) if wanted_ontology else None
    summary["ontology_source"] = graph_source
    summary["ontology_context_chars"] = len(onto_ctx)
    summary["arms_dropped"] = list(dropped)
    _print_report(rows, summary, arms)
    result = {"results": rows, "summary": summary}
    if output:
        Path(output).write_text(json.dumps(result, indent=2, default=str))
        print(f"\nResults → {output}")
    return result


def _summarize(rows: list[dict], arms: tuple[str, ...] = ARMS) -> dict:
    n = len(rows) or 1
    counts = {a: Counter(r[a]["class"] for r in rows if a in r) for a in arms}
    out: dict = {"n": len(rows), "arms": list(arms)}
    out.update({a: dict(c) for a, c in counts.items()})
    if "raw" in arms:
        out["raw_accuracy"] = round(counts["raw"]["correct"] / n, 3)
        out["raw_silent_wrong"] = counts["raw"]["silent-wrong"]
    if "guarded" in arms:
        gc = counts["guarded"]
        out["guarded_safe_rate"] = round((gc["correct"] + gc["caught"]) / n, 3)
        out["guarded_silent_wrong"] = gc["silent-wrong"]
        # the moat: raw silent-wrongs the guard battery converts to correct or caught
        out["saves"] = [r["id"] for r in rows if r["raw"]["class"] == "silent-wrong"
                        and r["guarded"]["class"] in ("correct", "caught")]
        out["regressions"] = [r["id"] for r in rows if r["raw"]["class"] == "correct"
                              and r["guarded"]["class"] not in ("correct", "caught")]
    if "ontology" in arms:
        oc = counts["ontology"]
        out["ontology_accuracy"] = round(oc["correct"] / n, 3)
        out["ontology_silent_wrong"] = oc["silent-wrong"]
        if "raw" in arms:
            # the arc's question, per question: did the blocks help, hurt, or do nothing
            out["ontology_gains"] = [r["id"] for r in rows if r["raw"]["class"] != "correct"
                                     and r["ontology"]["class"] == "correct"]
            out["ontology_losses"] = [r["id"] for r in rows if r["raw"]["class"] == "correct"
                                      and r["ontology"]["class"] != "correct"]
    if "ontology_guarded" in arms:
        ogc = counts["ontology_guarded"]
        out["ontology_guarded_safe_rate"] = round((ogc["correct"] + ogc["caught"]) / n, 3)
        out["ontology_guarded_silent_wrong"] = ogc["silent-wrong"]
        fired_raw = sum(len(r["guarded"]["guards_fired"]) for r in rows if "guarded" in r)
        fired_onto = sum(len(r["ontology_guarded"]["guards_fired"]) for r in rows)
        out["guards_fired"] = {"on_raw": fired_raw if "guarded" in arms else None, "on_ontology": fired_onto}
    if "injected" in arms:
        ic = counts["injected"]
        out["injected_accuracy"] = round(ic["correct"] / n, 3)
        out["injected_silent_wrong"] = ic["silent-wrong"]
    return out


def _print_report(rows: list[dict], s: dict, arms: tuple[str, ...] = ARMS) -> None:
    head = f"{'id':26}{'trap':13}" + "".join(f"{a:>17}" for a in arms)
    print("\n" + head)
    print("-" * len(head))
    for r in rows:
        cells = "".join(f"{(r[a]['class'] if a in r else '·'):>17}" for a in arms)
        fired = []
        for a in ("guarded", "ontology_guarded"):
            if a in r and r[a]["guards_fired"]:
                fired.append(f"{a[:1]}:{','.join(r[a]['guards_fired'])}")
        tail = f"  ⟵ {' '.join(fired)}" if fired else ""
        print(f"{r['id']:26}{str(r['trap']):13}{cells}{tail}")
    print("-" * len(head))
    if "raw" in arms:
        print(f"\n  Raw              : {s['raw_accuracy']:.0%} correct   {s['raw']}")
    if "guarded" in arms:
        print(f"  Guarded          : {s['guarded_safe_rate']:.0%} SAFE (correct+caught)   {s['guarded']}")
    if "ontology" in arms:
        avail = "" if s.get("ontology_available") else "   ⚠ NO ONTOLOGY — equals raw"
        print(f"  Ontology         : {s['ontology_accuracy']:.0%} correct   {s['ontology']}{avail}")
        if "raw" in arms:
            print(f"    vs raw         : gains {s['ontology_gains']}  losses {s['ontology_losses']}")
    if "ontology_guarded" in arms:
        print(f"  Ontology+guards  : {s['ontology_guarded_safe_rate']:.0%} SAFE   {s['ontology_guarded']}"
              f"   guards fired: {s['guards_fired']}")
    if "injected" in arms:
        print(f"  Injected         : {s['injected_accuracy']:.0%} correct   {s['injected']}")
    sw = {a: s.get(f"{a}_silent_wrong") for a in arms if f"{a}_silent_wrong" in s}
    print(f"\n  SILENT-WRONG per arm: {sw}   (a plausible, un-flagged wrong answer)")
    if "guarded" in arms:
        print(f"  Saves (raw silent-wrong → guarded correct/caught): {len(s['saves'])}  {s['saves']}")
        print(f"  Regressions (raw correct → guarded not-safe)     : {len(s['regressions'])}  {s['regressions']}")
    if s.get("reference_failed"):
        print(f"  Skipped (reference SQL failed): {[f['id'] for f in s['reference_failed']]}")
    if s.get("arms_dropped"):
        print(f"  Dropped arms (no ontology to inject — not spent on): {s['arms_dropped']}")
    llm = s.get("llm") or {}
    print(f"  Model: {llm.get('backend')} · {llm.get('model')}   fallback chain: "
          f"{llm.get('fallback_chain') or 'none'}   ontology source: {s.get('ontology_source')}")
    print("=" * len(head))


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
    tcols = _quiet(lambda: __import__("aughor.db.schema_render", fromlist=["parse_schema_tables"]).parse_schema_tables(db.get_schema()), {})

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
    ap.add_argument("--dataset", action="append", default=None,
                    help="JSONL of questions; repeatable — one connection per file")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--arms", default=",".join(ARMS),
                    help=f"comma-separated subset of {','.join(ARMS)} (LLM cost scales with arms)")
    ap.add_argument("--check-references", action="store_true",
                    help="Execute every reference/accept SQL and stop — no model, no scoring")
    ap.add_argument("--graph-json", action="append", default=None, metavar="LABEL=PATH",
                    help="Ontology graph for a dataset's connection: LABEL is `conn` or `conn/schema`, "
                         "PATH holds the JSON of GET /ontology?connection_id=…&schema_name=…; repeatable. "
                         "Use it when the store is redirected (AUGHOR_SYSTEM_DB) beside a serving API.")
    ap.add_argument("--traps", action="store_true", help="Run only the deterministic guard-efficacy demo (no LLM)")
    args = ap.parse_args()
    graph_json: dict[str, str] = {}
    for item in args.graph_json or []:
        label, sep, path = item.partition("=")
        if not sep or not label or not Path(path).is_file():
            ap.error(f"--graph-json expects LABEL=PATH with an existing file, got {item!r}")
        graph_json[label] = path
    if args.traps:
        demo_traps()
        return
    datasets = args.dataset or ["evals/ablation_missimi.jsonl"]
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    results = [run(d, args.limit, None, arms=arms, check_only=args.check_references,
                   graph_json=graph_json) for d in datasets]
    if args.output and not args.check_references:
        payload = results[0] if len(results) == 1 else {"datasets": results}
        Path(args.output).write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nResults → {args.output}")


if __name__ == "__main__":
    main()
