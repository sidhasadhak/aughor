"""DE-4 pre-check (ROADMAP §3.51; the dbx study's §3.6): how many output columns sqlglot's
`qualify` + `lineage` resolve to a table column, over real statements, and how long it takes.

The study reported 130 of 136 output columns across the golden set's 66 statements (53
reference statements and 13 accepted alternates) at about 4.7 ms a statement, against the
seeded ecommerce fixture. This re-measures that on the machine it runs on, and takes any other
set of statements — theLook's audit is BigQuery's spelling — so the number is measured before
anything is built on it.

    uv run python scripts/de4_lineage_precheck.py                      # the golden set
    uv run python scripts/de4_lineage_precheck.py --connection 8233e4fd --limit 2000
                                                                       # a connection's audit
    uv run python scripts/de4_lineage_precheck.py --sql-file q.jsonl --dialect bigquery \
        --schema-json schema.json                                      # another set

`--connection` reads the connection's newest audited statements (`AuditLogger.recent`, as
DE-1's pre-check does) and its schema, in its declared dialect — theLook's audit is BigQuery's
spelling. `--sql-file` is JSON lines with a `sql` field (or one statement per line).
`--schema-json` is `{"schema": {"table": {"column": "type"}}}`; without a schema, statements
are qualified by name alone and `SELECT *` falls back to table level, which the report says.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GOLDEN = REPO / "evals" / "golden_sql_expanded.jsonl"


def golden_statements() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in GOLDEN.open():
        if not line.strip():
            continue
        r = json.loads(line)
        out.append((r["id"], r["reference_sql"]))
        for i, alt in enumerate(r.get("accept_sql") or []):
            out.append((f"{r['id']}.alt{i + 1}", alt))
    return out


def seeded_schema() -> dict:
    """The ecommerce fixture's schema as sqlglot wants it: {schema: {table: {column: type}}}."""
    import duckdb

    from aughor.demo.setup import _seed_ecommerce

    path = Path(tempfile.mkdtemp()) / "samples.duckdb"
    con = duckdb.connect(str(path))
    try:
        _seed_ecommerce(con)
        rows = con.execute(
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2, ordinal_position"
        ).fetchall()
    finally:
        con.close()
    schema: dict = {}
    for s, t, c, ty in rows:
        schema.setdefault(s, {}).setdefault(t, {})[c] = ty
    return schema


def measure(statements: list[tuple[str, str]], schema: dict | None, dialect: str) -> dict:
    from aughor.sql.lineage import column_lineage

    totals = {"statements": 0, "failed": 0, "outputs": 0, "resolved": 0,
              "certain": 0, "likely": 0, "possible": 0, "unresolved": [],
              "filter_cols": 0, "join_cols": 0, "group_cols": 0, "ms": 0.0}
    for sid, sql in statements:
        totals["statements"] += 1
        t0 = time.perf_counter()
        try:
            lin = column_lineage(sql, dialect=dialect, schema=schema)
        except Exception as exc:  # the pre-check reports a failure, it does not hide one
            totals["failed"] += 1
            totals["unresolved"].append(f"{sid}: {type(exc).__name__}: {str(exc)[:80]}")
            continue
        totals["ms"] += (time.perf_counter() - t0) * 1000
        for out in lin.outputs:
            totals["outputs"] += 1
            if out.sources:
                totals["resolved"] += 1
                totals[out.confidence] += 1
            else:
                totals["unresolved"].append(f"{sid}: {out.name} ← {out.expression[:60]}")
        totals["filter_cols"] += len(lin.filters)
        totals["join_cols"] += len(lin.joins)
        totals["group_cols"] += len(lin.groups)
    return totals


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sql-file", help="JSON lines with a `sql` field, or one statement per line")
    ap.add_argument("--connection", help="measure the newest audited statements of this connection id")
    ap.add_argument("--limit", type=int, default=2000, help="with --connection: how many statements")
    ap.add_argument("--dialect", default=None, help="sqlglot dialect; the connection's own with --connection")
    ap.add_argument("--schema-json", help="{schema: {table: {column: type}}}; the golden set seeds its own")
    args = ap.parse_args()

    if args.connection:
        from aughor.db.connection import open_connection_for
        from aughor.db.schema_render import sqlglot_schema
        from aughor.security.audit import AuditLogger
        records = AuditLogger.recent(limit=args.limit, connection_id=args.connection)
        statements = [(str(r.get("hypothesis_id") or f"q{i + 1}"), str(r["sql"]))
                      for i, r in enumerate(records) if r.get("sql") and not r.get("error")]
        db = open_connection_for(args.connection)
        try:
            schema = sqlglot_schema(db.get_schema())
            dialect = args.dialect or getattr(db, "dialect", None)
        finally:
            db.close()
        print(f"connection {args.connection}: {len(statements)} audited statements that ran, dialect {dialect}, "
              f"{sum(len(v) for v in schema.values())} tables in the schema")
        t = measure(statements, schema or None, dialect)
        args.dialect = dialect
    elif args.sql_file:
        statements = []
        for i, line in enumerate(Path(args.sql_file).open()):
            line = line.strip()
            if not line:
                continue
            try:
                statements.append((f"q{i + 1}", json.loads(line)["sql"]))
            except (json.JSONDecodeError, KeyError):
                statements.append((f"q{i + 1}", line))
        schema = json.loads(Path(args.schema_json).read_text()) if args.schema_json else None
    else:
        statements = golden_statements()
        schema = seeded_schema()

    if not args.connection:
        t = measure(statements, schema, args.dialect or "duckdb")
    n = max(1, t["statements"] - t["failed"])
    print(f"statements: {t['statements']} ({t['failed']} failed to parse or qualify)")
    print(f"output columns: {t['resolved']} of {t['outputs']} resolved to a table column "
          f"— certain {t['certain']}, likely {t['likely']}, possible {t['possible']}")
    print(f"filter columns: {t['filter_cols']}  join columns: {t['join_cols']}  group columns: {t['group_cols']}")
    print(f"time: {t['ms'] / n:.1f} ms a statement (schema {'given' if schema else 'ABSENT — SELECT * resolves nothing'})")
    if t["unresolved"]:
        print("unresolved:")
        for u in t["unresolved"]:
            print("  " + u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
