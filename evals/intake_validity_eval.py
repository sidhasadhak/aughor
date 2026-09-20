"""JD-2 — how often does the free-text intake name a table or column that does not exist?

Three of intake's ~25 fields are picks from a set the schema already holds, asked as free
text: `metric_table` (a table), `date_column` and `dimensions` (columns). This measures what
those picks were worth on REAL historical traffic, by decoding the intake spec every deep run
persisted and checking each name against the warehouse it was supposedly about.

**No model call, no warehouse write.** The corpus is `data/checkpoints.db` and the ground
truth is `information_schema` read out of the DuckDB files themselves, so the whole thing is
free and repeatable — which is the point: the same decode is the AFTER measurement once a
closed option list lands, so the experiment needs no new instrument.

Three rules that keep the number honest, each of which moves it DOWN:

* **Unverifiable is not invalid.** A pick naming a schema this harness cannot read (BigQuery,
  or a `missimi` schema present in no local warehouse) is counted in neither the numerator nor
  the denominator. A failed probe and a true negative look identical, so they are kept apart.
* **One spec per investigation.** A run writes its spec into every checkpoint it takes; count
  the checkpoints and a single bad pick becomes five. Specs are collapsed per `thread_id`.
* **Case-insensitive.** SQL identifiers are, so a name is not marked invalid over casing.

The companion fact, reported alongside because it decides what the number MEANS: whether a
thread's spec ever changes across its checkpoints. If it never does, the spec-repair retry did
not fix these — the invalid name is what the investigation ran on, not a proposal it caught.

Usage:

    uv run python evals/intake_validity_eval.py --output evals/intake_validity_results.json
    uv run python evals/intake_validity_eval.py --checkpoints /path/to/checkpoints.db
"""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: The state key the spec lives under. Leading underscore: it is internal to the run, and the
#: un-underscored `ada_intake` is a different (absent) thing — looking for that one finds
#: nothing and reads as "no investigation ever recorded a spec".
SPEC_KEY = "_ada_intake"

#: Locked by another process in normal operation, and not a source of declared schema anyway.
SKIP_WAREHOUSES = ("mat_cache",)

NULLISH = {"", "NONE", "NULL", "N/A"}


def warehouse_reference(data_dir: Path) -> dict:
    """Every real "schema.table" and "schema.table.column", read from the warehouses.

    Deliberately not from the ontology, a profile cache or a rendered schema block: those are
    all downstream of the same builder the intake reads, so agreeing with one of them would
    prove only that two copies match. `information_schema` is the thing itself.
    """
    import duckdb

    tables: set[str] = set()
    columns: set[str] = set()
    read: list[str] = []
    for path in sorted(glob.glob(str(data_dir / "*.duckdb"))):
        if any(skip in path for skip in SKIP_WAREHOUSES):
            continue
        try:
            con = duckdb.connect(path, read_only=True)
        except Exception:  # noqa: BLE001 — a warehouse we cannot open is one we cannot judge with
            continue
        try:
            for schema, table, column in con.execute(
                "SELECT table_schema, table_name, column_name FROM information_schema.columns"
            ).fetchall():
                tables.add(f"{schema}.{table}".lower())
                columns.add(f"{schema}.{table}.{column}".lower())
            read.append(Path(path).name)
        finally:
            con.close()
    return {"tables": tables, "columns": columns,
            "schemas": {t.split(".")[0] for t in tables}, "warehouses": read}


def specs_by_investigation(checkpoints_db: Path) -> tuple[dict, dict]:
    """One spec per investigation, plus how many DISTINCT specs each one wrote.

    The second value is the load-bearing one. A run writes its spec into every checkpoint it
    takes, so a thread with several distinct specs is a thread whose repair rewrote it; a
    thread with exactly one ran start to finish on what it first decided.
    """
    import ormsgpack

    conn = sqlite3.connect(f"file:{checkpoints_db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT thread_id, checkpoint FROM checkpoints WHERE instr(checkpoint, ?) > 0",
            ("metric_table",)).fetchall()
    finally:
        conn.close()

    seen: dict = {}
    variants: dict = defaultdict(set)
    for thread, blob in rows:
        try:
            # Some blobs carry LangGraph ext types; without a hook ormsgpack raises and the
            # run silently drops out of the corpus, which would bias it toward simple runs.
            state = ormsgpack.unpackb(bytes(blob), ext_hook=lambda code, data: None) or {}
        except Exception:  # noqa: BLE001
            continue
        values = state.get("channel_values") or {}
        spec = values.get(SPEC_KEY)
        if not isinstance(spec, dict):
            continue
        dims = tuple(spec.get("dimensions") or [])
        variants[thread].add((spec.get("metric_table"), spec.get("date_column"), dims))
        seen[thread] = {
            "conn": values.get("connection_id") or "",
            "investigation_id": values.get("investigation_id") or "",
            "question": str(values.get("question") or "")[:110],
            "metric_table": spec.get("metric_table"),
            "date_column": spec.get("date_column"),
            "dimensions": list(dims),
        }
    return seen, {t: len(v) for t, v in variants.items()}


def classify(value, pool: set, schemas: set) -> str:
    """valid | invalid | unverifiable | none — for one picked name."""
    if value is None or str(value).strip().upper() in NULLISH:
        return "none"
    name = str(value).strip().lower()
    if name.split(".")[0] not in schemas:
        return "unverifiable"
    return "valid" if name in pool else "invalid"


def how_wrong(value, ref: dict) -> str:
    """Why a name is invalid — the part that separates a real defect from schema drift.

    A table that exists in NO schema was invented. A real table or column attached to the
    wrong schema cannot be drift: the name was right and the place was not.
    """
    parts = str(value).strip().lower().split(".")
    by_table = defaultdict(set)
    for t in ref["tables"]:
        by_table[t.split(".")[1]].add(t.split(".")[0])
    if len(parts) >= 3:
        tail = ".".join(parts[1:])
        if any(f"{s}.{tail}" in ref["columns"] for s in ref["schemas"]):
            return "right table and column, wrong schema"
        if ".".join(parts[:2]) in ref["tables"]:
            return "real table, column does not exist"
    if len(parts) >= 2 and parts[1] in by_table:
        return "right table, wrong schema"
    return "table does not exist in any warehouse"


def measure(specs: dict, variants: dict, ref: dict) -> dict:
    fields = {"metric_table": Counter(), "date_column": Counter(), "dimensions": Counter()}
    kinds: Counter = Counter()
    offenders: list = []
    runs_with_any = 0

    for spec in specs.values():
        dirty = False
        picks = [("metric_table", spec["metric_table"], ref["tables"]),
                 ("date_column", spec["date_column"], ref["columns"])]
        picks += [("dimensions", d, ref["columns"]) for d in spec["dimensions"]]
        for field, value, pool in picks:
            verdict = classify(value, pool, ref["schemas"])
            fields[field][verdict] += 1
            if verdict == "invalid":
                dirty = True
                kinds[how_wrong(value, ref)] += 1
                offenders.append({"field": field, "name": str(value),
                                  "why": how_wrong(value, ref), "question": spec["question"]})
        runs_with_any += dirty

    out: dict = {"investigations_with_a_spec": len(specs), "by_field": {},
                 "runs_with_at_least_one_invalid": runs_with_any,
                 "failure_kinds": dict(kinds.most_common()),
                 "warehouses_read": ref["warehouses"], "schemas_read": sorted(ref["schemas"]),
                 "threads_whose_spec_changed_mid_run": sum(1 for n in variants.values() if n > 1),
                 "offenders": offenders[:40]}
    for field, counts in fields.items():
        verifiable = counts["valid"] + counts["invalid"]
        out["by_field"][field] = {
            "valid": counts["valid"], "invalid": counts["invalid"],
            "unverifiable": counts["unverifiable"], "none": counts["none"],
            "verifiable": verifiable,
            "invalid_rate": round(counts["invalid"] / verifiable, 4) if verifiable else None,
        }
    # JD-2's claim is not "fewer mistakes on average" — it is that a closed option list cannot
    # NAME something that is not on it. So the falsifier is an empty invalid column, and it
    # fires the moment the free-text picks turn out to be valid already.
    total_invalid = sum(f["invalid"] for f in out["by_field"].values())
    out["falsifier"] = {
        "nothing_to_fix": total_invalid == 0,
        "note": ("fires when the free-text picks name nothing that does not exist — a closed "
                 "option list would then remove a failure that was not happening"),
    }
    out["inconclusive"] = len(specs) == 0
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoints", default=str(REPO / "data" / "checkpoints.db"))
    ap.add_argument("--data-dir", default=str(REPO / "data"),
                    help="where the *.duckdb warehouses live (the ground truth)")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    ckpt = Path(args.checkpoints)
    if not ckpt.exists():
        raise SystemExit(f"no checkpoint store at {ckpt}")

    ref = warehouse_reference(Path(args.data_dir))
    specs, variants = specs_by_investigation(ckpt)
    summary = measure(specs, variants, ref)

    print(f"investigations with a persisted intake spec: {summary['investigations_with_a_spec']}")
    print(f"ground truth: {len(ref['schemas'])} schemas, {len(ref['tables'])} tables, "
          f"{len(ref['columns'])} columns from {', '.join(ref['warehouses'])}\n")
    print(f"  {'field':<14}{'valid':>7}{'invalid':>9}{'unverif':>9}{'none':>6}   invalid rate")
    for field, f in summary["by_field"].items():
        rate = f"{f['invalid']}/{f['verifiable']} = {f['invalid_rate']:.1%}" if f["verifiable"] else "n/a"
        print(f"  {field:<14}{f['valid']:>7}{f['invalid']:>9}{f['unverifiable']:>9}{f['none']:>6}   {rate}")

    n = summary["investigations_with_a_spec"]
    bad = summary["runs_with_at_least_one_invalid"]
    print(f"\ninvestigations that ran on at least one name that does not exist: "
          f"{bad} of {n}" + (f" ({bad / n:.1%})" if n else ""))
    print(f"threads whose spec changed mid-run (a repair rewrote it): "
          f"{summary['threads_whose_spec_changed_mid_run']} of {n}")
    if summary["failure_kinds"]:
        print("\nhow the bad names are wrong:")
        for kind, count in summary["failure_kinds"].items():
            print(f"  {count:>5}  {kind}")
    if summary["inconclusive"]:
        print("\nINCONCLUSIVE: no spec decoded — this settles nothing in either direction.")
    else:
        print(f"\nfalsifier: {'FIRES' if summary['falsifier']['nothing_to_fix'] else 'HOLDS'}"
              f" — {summary['falsifier']['note']}")

    if args.output:
        Path(args.output).write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
