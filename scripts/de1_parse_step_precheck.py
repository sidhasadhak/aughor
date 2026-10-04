"""DE-1's pre-check (ROADMAP §3.51; `docs/DBX_STUDY_2026-10-01.md` §6): what the parse step would refuse, measured
on real statements before it runs at every door.

The parse step — one read-only statement, parsed in the engine's dialect (`aughor.db.connection._validate`) — ran in
the built-in DuckDB and Postgres connections only. DE-1 runs it at every connector's door. The falsifier: on an
engine where sqlglot refuses more than a handful of REAL statements, the parser is the wrong tool for that dialect.
This script counts them. Two sources:

  * the audit log's newest statements for a connection, in that connection's dialect (the live measurement — run it
    where the audit store is, e.g. theLook's BigQuery on the machine that serves it):

        uv run python scripts/de1_parse_step_precheck.py --connection 8233e4fd --limit 2000

  * the golden set, `evals/golden_sql_expanded.jsonl`, in a dialect (the repo's own measurement, 0 of 53 refused in
    every dialect on 2026-10-03):

        uv run python scripts/de1_parse_step_precheck.py --golden --dialect bigquery

A statement that already failed on the engine is counted apart: the question is the VALID statements the step
would refuse. Nothing is written; the audit log is read through `AuditLogger.recent`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: A connection type's sqlglot dialect, as the connectors declare it (`dialect` on each class).
_DIALECT_OF_TYPE = {
    "bigquery": "bigquery", "snowflake": "snowflake", "mysql": "mysql", "mariadb": "mysql",
    "exasol": "postgres", "postgres": "postgres", "postgresql": "postgres", "sqlite": "sqlite",
}


def _dialect_for(connection_id: str, override: str | None) -> str:
    if override:
        return override
    try:
        from aughor.db.registry import get_dsn
        conn_type, _dsn = get_dsn(connection_id)
    except Exception as exc:  # noqa: BLE001 — the registry may not hold it; say so and ask for --dialect
        sys.exit(f"could not resolve the dialect of {connection_id!r} ({exc}); pass --dialect")
    return _DIALECT_OF_TYPE.get(str(conn_type or "").lower(), "duckdb")


def _report(title: str, rows: list[tuple[str, str, bool, str]], dialect: str) -> int:
    """``rows``: (label, sql, ran_clean, error). Prints the counts and every refusal; returns the refused count."""
    from aughor.db.connection import _METADATA_LABELS, _validate

    refused: list[tuple[str, str, str, bool]] = []
    clean = 0
    for label, sql, ran_clean, _error in rows:
        if ran_clean:
            clean += 1
        ok, reason = _validate(sql, dialect, allow_metadata=label in _METADATA_LABELS)
        if not ok:
            refused.append((label, reason, sql, ran_clean))
    refused_clean = [r for r in refused if r[3]]
    print(f"\n{title}\n{'=' * len(title)}")
    print(f"statements: {len(rows)}   ran without an engine error: {clean}   dialect: {dialect}")
    print(f"the parse step would refuse: {len(refused)}   of which valid (ran clean): {len(refused_clean)}")
    by_reason = Counter(r[1].split(":")[0] for r in refused_clean)
    for reason, n in by_reason.most_common():
        print(f"  {n:5}  {reason}")
    for label, reason, sql, _ in refused_clean[:50]:
        print(f"\n  [{label}] {reason[:120]}\n      {' '.join(sql.split())[:300]}")
    if len(refused_clean) > 50:
        print(f"\n  … and {len(refused_clean) - 50} more")
    return len(refused_clean)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--connection", help="audit the newest statements of this connection id")
    ap.add_argument("--limit", type=int, default=2000, help="how many audit rows to read (newest first)")
    ap.add_argument("--dialect", help="parse in this sqlglot dialect (resolved from the registry when omitted)")
    ap.add_argument("--golden", action="store_true", help="run evals/golden_sql_expanded.jsonl instead of the audit")
    args = ap.parse_args()

    if args.golden:
        rows = [json.loads(line) for line in (REPO / "evals" / "golden_sql_expanded.jsonl").read_text().splitlines()
                if line.strip()]
        total = 0
        for dialect in ([args.dialect] if args.dialect else ["bigquery", "duckdb", "postgres", "snowflake", "mysql"]):
            total += _report(f"golden set ({len(rows)} statements)",
                             [(r.get("id", ""), r["reference_sql"], True, "") for r in rows], dialect)
        return 1 if total else 0

    if not args.connection:
        ap.error("--connection ID (or --golden)")
    from aughor.security.audit import AuditLogger
    records = AuditLogger.recent(limit=args.limit, connection_id=args.connection)
    # The audit store's column is `sql_full` (`sql_digest` beside it). This read `sql`, which no row carries, so
    # on the first machine with an audit log it counted 0 of 22,267 statements and reported 0 refused (2026-10-03).
    rows = [(str(r.get("hypothesis_id") or ""), str(r.get("sql_full") or ""), not r.get("error"), str(r.get("error") or ""))
            for r in records if r.get("sql_full")]
    if records and not rows:
        sys.exit(f"{len(records)} audit rows read for {args.connection!r} and none carried a statement — "
                 "the reader is wrong, not the log; nothing was measured")
    dialect = _dialect_for(args.connection, args.dialect)
    refused = _report(f"audit log, connection {args.connection}, newest {len(rows)}", rows, dialect)
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
