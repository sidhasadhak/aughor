"""JD-2's premise, tested — and REFUTED on this corpus.

Three of intake's ~25 fields are picks from a set the schema already holds, asked as free
text: `metric_table` (a table), `date_column` and `dimensions` (columns). JD-2 proposed
replacing them with a closed option list, on the argument that a closed list cannot name
something that does not exist. This harness tests the premise that argument rests on — that
the free-text field names things that do not exist — and finds it false.

**The ground truth is the schema block PERSISTED WITH EACH RUN** (`filtered_schema` on the
spec), not the warehouse as it stands today. That choice is the whole lesson here. A first
version of this harness compared three months of specs against today's `data/*.duckdb` and
reported ~20% of picks invalid; every headline example turned out to be a real table the
harness had not looked at — the `workspace` connection is a `local_upload` store under
`data/uploads/`, `baef6c3e` points at a 4 GB DuckDB outside `data/`, schemas have been
removed (`data/uploads/default/workspace/_removed_seeds.json`) and some connections the
corpus used no longer exist. The warehouse moved under the corpus, so "does this name exist
NOW" cannot answer "did the model make this up THEN". The schema the run was handed can.

**No model call, no warehouse write.** The corpus is `data/checkpoints.db` and the ground
truth is `information_schema` read out of the DuckDB files themselves, so the whole thing is
free and repeatable — which is the point: the same decode is the AFTER measurement once a
closed option list lands, so the experiment needs no new instrument.

Three rules that keep the number honest, each of which moves it DOWN:

* **One spec per thread.** A run writes its spec into every checkpoint it takes; count the
  checkpoints and a single bad pick becomes five. Specs are collapsed per `thread_id`. Note
  `thread_id`, not investigation: two probe threads share one `investigation_id`, so the
  thread count (202) is one higher than the investigation count (201).
* **Case-insensitive, and token-based.** SQL identifiers are case-insensitive, and a real
  column can contain spaces and brackets (`shipping date (dateorders)`), so a name counts as
  shown when every identifier token in it appears in the block.
* **A run that persisted no schema is excluded**, never scored as a miss.

The companion fact, reported alongside: whether a thread's spec ever changes across its
checkpoints. It never does (0 of 202), so whatever the model picked is what the run used.

Usage:

    uv run python evals/intake_validity_eval.py --output evals/intake_validity_results.json
    uv run python evals/intake_validity_eval.py --checkpoints /path/to/checkpoints.db
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: The state key the spec lives under. Leading underscore: it is internal to the run, and the
#: same name WITHOUT that underscore is a different (absent) thing — looking for that one finds
#: nothing and reads as "no investigation ever recorded a spec".
SPEC_KEY = "_ada_intake"

#: Locked by another process in normal operation, and not a source of declared schema anyway.
SKIP_WAREHOUSES = ("mat_cache",)

NULLISH = {"", "NONE", "NULL", "N/A"}


_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def shown_tokens(schema_block: str) -> set:
    """Every identifier token in the schema block a run was handed.

    Token membership rather than substring: a substring test would count `order` as shown
    because `order_date` is, which biases toward "the model picked something real" — the
    direction that flatters the refutation. Tokens do not."""
    return {t.lower() for t in _TOKEN.findall(schema_block or "")}


def was_shown(name, tokens: set) -> str:
    """shown | column_not_shown | not_shown | none — for one picked name."""
    if name is None or str(name).strip().upper() in NULLISH:
        return "none"
    parts = [p for p in str(name).strip().lower().split(".") if p]
    if not parts:
        return "none"
    table = parts[1] if len(parts) >= 2 else parts[0]
    column = ".".join(parts[2:]) if len(parts) >= 3 else ""
    table_ok = all(t in tokens for t in _TOKEN.findall(table))
    if not table_ok:
        return "not_shown"
    if not column:
        return "shown"
    return "shown" if all(t in tokens for t in _TOKEN.findall(column)) else "column_not_shown"


def specs_by_thread(checkpoints_db: Path) -> tuple[dict, dict]:
    """One spec per thread, plus how many DISTINCT specs each thread wrote.

    The second value is load-bearing: a thread with several distinct specs is one whose repair
    rewrote it; a thread with exactly one ran start to finish on what it first decided.
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
            # run silently drops out of the corpus, biasing it toward simple runs.
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
            "schema_shown": str(spec.get("filtered_schema") or values.get("schema_context") or ""),
        }
    return seen, {t: len(v) for t, v in variants.items()}


def measure(specs: dict, variants: dict) -> dict:
    fields = {"metric_table": Counter(), "date_column": Counter(), "dimensions": Counter()}
    misses: list = []
    runs_with_any = 0
    no_schema = 0

    for spec in specs.values():
        tokens = shown_tokens(spec.get("schema_shown", ""))
        if not tokens:
            no_schema += 1
            continue
        dirty = False
        picks = [("metric_table", spec["metric_table"]), ("date_column", spec["date_column"])]
        picks += [("dimensions", d) for d in spec["dimensions"]]
        for field, value in picks:
            verdict = was_shown(value, tokens)
            fields[field][verdict] += 1
            if verdict in ("not_shown", "column_not_shown"):
                dirty = True
                misses.append({"field": field, "name": str(value), "verdict": verdict,
                               "question": spec["question"]})
        runs_with_any += dirty

    out: dict = {"threads_with_a_spec": len(specs),
                 "threads_with_no_schema_persisted": no_schema,
                 "investigations_with_a_spec": len({s["investigation_id"] for s in specs.values()
                                                    if s["investigation_id"]}),
                 "by_field": {}, "runs_naming_something_not_shown": runs_with_any,
                 "threads_whose_spec_changed_mid_run": sum(1 for n in variants.values() if n > 1),
                 "misses": misses[:40]}
    total = Counter()
    for field, counts in fields.items():
        scored = counts["shown"] + counts["column_not_shown"] + counts["not_shown"]
        out["by_field"][field] = {
            "shown": counts["shown"], "column_not_shown": counts["column_not_shown"],
            "not_shown": counts["not_shown"], "none": counts["none"], "scored": scored,
            "shown_rate": round(counts["shown"] / scored, 4) if scored else None,
        }
        total.update(counts)
    scored = total["shown"] + total["column_not_shown"] + total["not_shown"]
    out["overall"] = {"picks_scored": scored, "shown": total["shown"],
                      "shown_rate": round(total["shown"] / scored, 4) if scored else None}
    # JD-2's claim is that a closed option list removes picks that name what does not exist.
    # The falsifier fires when the free-text picks are ALREADY drawn from what the model was
    # shown — a closed list would then remove a failure that is not happening.
    out["falsifier"] = {
        "nothing_to_fix": bool(scored) and (total["shown"] / scored) >= 0.99,
        "note": ("fires when >=99% of picks name a table and column present in the schema the "
                 "run was handed — the free-text field is already choosing from the list"),
    }
    out["inconclusive"] = scored == 0
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoints", default=str(REPO / "data" / "checkpoints.db"))
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    ckpt = Path(args.checkpoints)
    if not ckpt.exists():
        raise SystemExit(f"no checkpoint store at {ckpt}")

    specs, variants = specs_by_thread(ckpt)
    s = measure(specs, variants)

    print(f"threads with a persisted intake spec: {s['threads_with_a_spec']} "
          f"({s['investigations_with_a_spec']} distinct investigations)")
    print("ground truth: the schema block persisted WITH EACH RUN\n")
    print(f"  {'field':<14}{'shown':>8}{'col not':>9}{'not shown':>11}{'none':>6}   picked from what it was shown")
    for field, f in s["by_field"].items():
        rate = f"{f['shown']}/{f['scored']} = {f['shown_rate']:.1%}" if f["scored"] else "n/a"
        print(f"  {field:<14}{f['shown']:>8}{f['column_not_shown']:>9}{f['not_shown']:>11}{f['none']:>6}   {rate}")
    o = s["overall"]
    print(f"\n  {'ALL PICKS':<14}{o['shown']:>8}{'':>9}{'':>11}{'':>6}   "
          + (f"{o['shown']}/{o['picks_scored']} = {o['shown_rate']:.1%}" if o["picks_scored"] else "n/a"))
    print(f"\nruns naming anything not in the schema they were shown: "
          f"{s['runs_naming_something_not_shown']} of {s['threads_with_a_spec']}")
    print(f"threads whose spec changed mid-run: {s['threads_whose_spec_changed_mid_run']}")
    if s["threads_with_no_schema_persisted"]:
        print(f"excluded (no schema persisted): {s['threads_with_no_schema_persisted']}")
    if s["inconclusive"]:
        print("\nINCONCLUSIVE: nothing scored — this settles nothing in either direction.")
    else:
        print(f"\nfalsifier: {'FIRES' if s['falsifier']['nothing_to_fix'] else 'HOLDS'}"
              f" — {s['falsifier']['note']}")
        if s["falsifier"]["nothing_to_fix"]:
            print("  => JD-2 is NOT supported by this corpus: the free-text field is already\n"
                  "     picking from the list it is shown, so a closed list removes nothing.")

    if args.output:
        Path(args.output).write_text(json.dumps(s, indent=2, default=str) + "\n")
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
