"""Linker recall — does the quick path hand the SQL writer the tables a correct answer reads?

PENDING item 19 (the SQL writer sees the data). Model-free and deterministic: for each question
in a gold set, the tables its reference SQL reads are the target; the tables the quick path would
put in front of the writer are computed exactly as `_answer_core` computes them —
`link_schema_for_prompt`, the linked tables it parses, the pinned date table,
`rank_tables_for_context` at the baseline cap, `fk_neighbor_expand`. Recall is the share of the
target present; "complete" is a question whose every target table is present — the writer cannot
join a table it was never shown.

Two renderings of the SAME warehouse: the house form (DuckDB, Postgres, SQLite — indented column
lines) and the inline form five warehouse connectors write (``TABLE: t [a INT, b TEXT]``), so a
fix that only one form sees shows up as a gap between the two.

    uv run python evals/linker_recall_eval.py [--gold evals/golden_sql_expanded.jsonl] [--out PATH]

Runs against the built-in samples warehouse (seeded into a temp file; nothing under data/ is
touched) with every store pointed at a temp directory, as the unit suite does.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _gold_tables(sql: str) -> set[str]:
    import sqlglot
    from sqlglot import exp
    tree = sqlglot.parse_one(sql, read="duckdb")
    ctes = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    return {t.name.lower() for t in tree.find_all(exp.Table)
            if t.name and t.name.lower() not in ctes}


def _inline(schema: str) -> str:
    """The house form rewritten the way BigQuery/Snowflake render it: every table's columns
    inline on its header, no indented column lines, no value annotations."""
    from aughor.db.schema_render import parse_inline_columns  # noqa: F401 — the form it parses
    out, current, cols = [], None, []

    def _flush():
        if current is not None:
            out.append(f"{current} [{', '.join(cols)}]")

    for line in schema.splitlines():
        if line.startswith("TABLE:"):
            _flush()
            current, cols = line.rstrip(), []
            continue
        m = re.match(r"^\s{2}(\w+)\s{2,}(\S+)", line)
        if current is not None and m and not line.strip().startswith("--"):
            cols.append(f"{m.group(1)} {m.group(2)}")
            continue
        if current is not None and line and not line[0].isspace():
            _flush()
            current = None
            out.append(line)
        elif current is None:
            out.append(line)
    _flush()
    return "\n".join(out)


def linked_tables(question: str, full_schema: str, connection_id: str) -> list[str]:
    """The tables the quick path's catalog would carry, computed as `_answer_core` computes them."""
    from aughor.agent.grounding import schema_slice
    from aughor.llm.profile import profile_for
    from aughor.tools.schema import fk_neighbor_expand, parse_schema_tables, temporal_dimension_tables
    from aughor.tools.schema_linker import rank_tables_for_context
    sliced = schema_slice(question, connection_id, schema=full_schema)
    linked = list(parse_schema_tables(sliced).keys())
    if not linked:
        return []
    pinned = [t for t in temporal_dimension_tables(full_schema, linked, question) if t not in linked]
    ranked = rank_tables_for_context(question, full_schema, linked + pinned,
                                     cap=profile_for("coder").context_table_cap,
                                     connection_id=connection_id, pinned=pinned)
    return fk_neighbor_expand(full_schema, ranked, cap=10)


def measure(gold_path: Path) -> dict:
    import tests.conftest  # noqa: F401 — every store at a temp path, as the suite runs
    import duckdb
    from aughor.db.connection import open_connection
    from aughor.demo.setup import _seed_ecommerce

    path = Path(tempfile.mkdtemp()) / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    connection_id = "linker-recall-eval"
    db = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=connection_id)
    house = db.get_schema()
    forms = {"house": house, "inline": _inline(house)}

    rows = [json.loads(line) for line in gold_path.read_text().splitlines() if line.strip()]
    report: dict = {"gold": gold_path.name, "questions": len(rows), "forms": {}}
    for form, schema in forms.items():
        per = []
        for row in rows:
            target = _gold_tables(row["reference_sql"])
            got = {t.rsplit(".", 1)[-1].lower() for t in linked_tables(row["question"], schema,
                                                                        connection_id)}
            hit = target & got
            per.append({"id": row.get("id"), "target": sorted(target), "sent": sorted(got),
                        "missing": sorted(target - got),
                        "recall": round(len(hit) / len(target), 3) if target else 1.0})
        n = len(per) or 1
        report["forms"][form] = {
            "mean_recall": round(sum(p["recall"] for p in per) / n, 3),
            "complete": sum(1 for p in per if not p["missing"]),
            "mean_tables_sent": round(sum(len(p["sent"]) for p in per) / n, 2),
            "misses": [p for p in per if p["missing"]],
        }
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=str(REPO / "evals" / "golden_sql_expanded.jsonl"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    report = measure(Path(args.gold))
    for form, r in report["forms"].items():
        print(f"{form:7s} mean recall {r['mean_recall']:.3f} · complete {r['complete']}/"
              f"{report['questions']} · tables sent {r['mean_tables_sent']:.2f}")
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
