"""ON-2's falsifier, measured on the two question sets that carry reference answers.

§3.15 ON-2: "compilable share of the last 30 days of real questions (session_events) below 30% ⇒
the IR is too narrow; widen before exposing the tool." The ledger that sentence names turned out to
hold mostly questions no SQL answers (the receipt in §3.15 counts them), so the IR's WIDTH is
measured here instead, on questions built to be hard: for every record a person wrote the object
query the question asks for; it is compiled against the dataset's committed MEASURED ontology — no
model anywhere — executed read-only, and scored against the dataset's own reference with the
ablation harness's scorer. A refusal is recorded with its reason and classed by what would fix it:

    graph   the ontology lacks the link, measured it N:N, or never measured it — an ontology edit
    law     a construction law refused a query that would have been wrong (an authoring slip)
    name    a name the graph does not carry
    ir      the algebra cannot say it — the falsifier's own class

What this is NOT: the share a model reaches when it fills the IR from the question. This is the
upper bound; only a model run measures the real number.

    uv run python evals/object_query_coverage.py --output evals/object_query_coverage_results.json

Beside a serving API, redirect every AUGHOR_*_DB first (the list is tests/conftest.py's): executing
a query records guard verdicts and popularity, and those stores are served.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RECORDS = "evals/object_query_coverage.jsonl"
#: Each question set → the measured ontology its object queries compile against, committed beside it.
GRAPHS = {
    "evals/ablation_samples_ecommerce.jsonl": "evals/ablation_samples_ecommerce_ontology_measured.json",
    "evals/ablation_luxexperience_hard.jsonl": "evals/ablation_luxexperience_ontology_measured.json",
}
FALSIFIER_THRESHOLD = 0.30

_KINDS = (
    ("graph", ("no link", "N:N", "never been measured", "query backing", "links reach", "is not verified")),
    ("law", ("the fan-out", "does not add up", "not a quantity", "would repeat")),
    ("name", ("has no property", "no object type", "has no segment", "no metric")),
)


def refusal_kind(reason: str) -> str:
    """What would make a refused question compilable."""
    for kind, markers in _KINDS:
        if any(marker in reason for marker in markers):
            return kind
    return "ir"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _open_warehouse(source: list[dict], samples_db: str | None):
    """Read-only: the set's own DuckDB file, or the bundled samples SQL seeded into a scratch file."""
    from aughor.db.connection import open_connection
    first = source[0]
    if first.get("duckdb_path"):
        path = Path(first["duckdb_path"])
        path = path if path.is_absolute() else ROOT / path
        if not path.exists():
            return None, f"{first['duckdb_path']} is not on this machine"
        return open_connection("duckdb", str(path), schema_name=first.get("schema"),
                               connection_id=first.get("connection_id", "")), ""
    if first.get("connection_id") == "samples":
        path = Path(samples_db) if samples_db else Path(tempfile.mkdtemp(prefix="oq-samples-")) / "samples.duckdb"
        if not path.exists():
            import duckdb

            from aughor.demo.setup import _seed_ecommerce
            con = duckdb.connect(str(path))
            _seed_ecommerce(con)
            con.close()
        return open_connection("duckdb", str(path), schema_name=first.get("schema") or "ecommerce",
                               connection_id="samples"), ""
    return None, f"no warehouse for connection {first.get('connection_id')!r} — name a duckdb_path"


def measure(records: str = RECORDS, *, datasets: list[str] | None = None, samples_db: str | None = None,
            compile_only: bool = False) -> dict:
    from aughor.ontology.models import OntologyGraph
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
    from evals.ablation_eval import _classify_plain
    from evals.sql_accuracy import score_single

    wanted = _jsonl(ROOT / records)
    if datasets:
        wanted = [r for r in wanted if r["dataset"] in datasets]
    sets = list(dict.fromkeys(r["dataset"] for r in wanted))
    rows: list[dict] = []
    notes: dict[str, str] = {}
    for dataset in sets:
        source = {r["id"]: r for r in _jsonl(ROOT / dataset)}
        graph = OntologyGraph.model_validate(json.loads((ROOT / GRAPHS[dataset]).read_text()))
        db, why = (None, "compile only") if compile_only else _open_warehouse(list(source.values()), samples_db)
        if db is None:
            notes[dataset] = f"not executed: {why}"
        try:
            for rec in (r for r in wanted if r["dataset"] == dataset):
                src = source[rec["id"]]
                row = {"id": rec["id"], "dataset": dataset, "trap": src.get("trap"), "question": src["question"]}
                if rec.get("note"):
                    row["note"] = rec["note"]
                try:
                    compiled = compile_object_query(rec["object_query"], graph, fiscal_start_month=1,
                                                    dialect=getattr(db, "dialect", "") or "duckdb")
                except ObjectQueryRefused as exc:
                    row.update({"path": "refused", "refused": exc.reason, "refusal_kind": refusal_kind(exc.reason)})
                    rows.append(row)
                    continue
                row.update({"path": "compiled", "sql": compiled.sql, "plan": compiled.plan,
                            "links": compiled.links, "caveats": compiled.caveats})
                if db is not None:
                    score = score_single(db, src, compiled.sql)
                    row["class"] = _classify_plain(score, compiled.sql)
                    row["match"] = round(score.get("result_set_match", 0.0), 3)
                    if score.get("error"):
                        row["error"] = str(score["error"])[:300]
                rows.append(row)
        finally:
            if db is not None:
                db.close()
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "compiler": "aughor.semantic.object_query", "graphs": {d: GRAPHS[d] for d in sets},
            "notes": notes, "summary": summarize(rows), "rows": rows}


def summarize(rows: list[dict]) -> dict:
    def block(subset: list[dict]) -> dict:
        n = len(subset)
        compiled = [r for r in subset if r["path"] == "compiled"]
        scored = [r for r in compiled if "class" in r]
        return {"questions": n, "compiled": len(compiled),
                "compiled_share": round(len(compiled) / n, 3) if n else 0.0,
                "scored": len(scored), "correct": sum(1 for r in scored if r["class"] == "correct"),
                "wrong": sorted(r["id"] for r in scored if r["class"] != "correct"),
                "refused": dict(Counter(r["refusal_kind"] for r in subset if r["path"] == "refused"))}

    out = block(rows)
    out["falsifier"] = {"threshold": FALSIFIER_THRESHOLD, "compiled_share": out["compiled_share"],
                        "ir_refusals": sum(1 for r in rows if r.get("refusal_kind") == "ir"),
                        "fires": out["compiled_share"] < FALSIFIER_THRESHOLD}
    out["by_dataset"] = {d: block([r for r in rows if r["dataset"] == d])
                         for d in dict.fromkeys(r["dataset"] for r in rows)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="ON-2's falsifier: the object-query IR's width on reference sets")
    ap.add_argument("--records", default=RECORDS)
    ap.add_argument("--dataset", action="append", help="limit to one question set (repeatable)")
    ap.add_argument("--samples-db", help="an already-seeded samples DuckDB file (default: seed a scratch copy)")
    ap.add_argument("--compile-only", action="store_true", help="compile against the graphs; execute nothing")
    ap.add_argument("--output")
    args = ap.parse_args()
    result = measure(args.records, datasets=args.dataset, samples_db=args.samples_db,
                     compile_only=args.compile_only)
    for r in result["rows"]:
        verdict = r.get("class", "compiled") if r["path"] == "compiled" else f"refused/{r['refusal_kind']}"
        print(f"  {r['id']:34} {verdict:16} {(r.get('refused') or r.get('error') or '')[:120]}")
    s = result["summary"]
    print(f"\n  compiled {s['compiled']}/{s['questions']} ({s['compiled_share']:.0%}) · correct "
          f"{s['correct']}/{s['scored']} scored · refused {s['refused']} · falsifier fires: {s['falsifier']['fires']}")
    for dataset, note in result["notes"].items():
        print(f"  ⚠ {dataset}: {note}")
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(f"  receipt → {args.output}")


if __name__ == "__main__":
    main()
