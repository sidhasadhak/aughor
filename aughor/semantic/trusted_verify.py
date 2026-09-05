"""KI-0 (§3.10) — verification for trusted-query seeds.

Imported SQL is fuel, never ground truth: a seed becomes prompt-authoritative only
after it has actually RUN against its connection and walked the same guard battery
`/query/validate` runs. This module produces that verdict.

Blocking (a failing seed stays a draft, never in the prompt):
  * a mutation/DDL blocker from the AST read-only gate — checked FIRST, so a seeded
    ``DROP TABLE`` is refused before anything reaches an engine;
  * an execution error;
  * an unrenderable parameterised statement (the battery could not look at it).

Advisory (recorded in the report, shown to the approver, non-blocking): E1 trust
findings and the fan-out / join / filter / grain warnings. A trusted query exists
precisely to encode judgement a heuristic can't make, so a warning is the approver's
to weigh — but an error or a mutation is nobody's to waive.
"""
from __future__ import annotations

from datetime import datetime, timezone

#: Verification needs proof of life, not the result set.
_SAMPLE_ROWS = 50


def verify(connection_id: str, sql: str) -> dict:
    """Execute ``sql`` (bounded) and run the shared guard battery. Returns a report:

    ``{passed, checked_at, blockers, execution: {ok, row_count, truncated, error},
    battery: <the /query/validate dict>}``

    Raises ``KeyError`` when ``connection_id`` names no connection.
    """
    from aughor.db.connection import open_connection_for
    from aughor.kernel.errors import tolerate
    from aughor.sql.validation import validate_sql

    checked_at = datetime.now(timezone.utc).isoformat()

    # Opening executes nothing of the caller's, so it is safe to do first — and the
    # AST gate needs the connection's real dialect to parse against.
    db = open_connection_for(connection_id)
    try:
        dialect = getattr(db, "dialect", None) or "duckdb"

        # The pure AST gate runs BEFORE any execution: a mutating statement must never
        # run, not even once, not even bounded. `readonly.is_mutating` is decisive and
        # never raises; the facade wrapping it is tolerated only for its advisory part.
        blockers: list[dict] = []
        try:
            from aughor.trust import Scope, verify as trust_verify
            verdict = trust_verify(sql, Scope(dialect=dialect))
            blockers = [{"name": c.name, "reason": c.reason, **c.detail}
                        for c in verdict.blockers]
        except Exception as exc:
            tolerate(exc, "trusted verify: AST gate unavailable; the battery re-runs "
                          "the facade", counter="trusted_verify.ast")
        if blockers:
            return {"passed": False, "checked_at": checked_at, "blockers": blockers,
                    "execution": {"ok": False, "row_count": 0, "truncated": False,
                                  "error": "not executed: mutation/DDL blocker"},
                    "battery": None}

        result = db.execute_bounded("__trusted_verify__", sql, max_rows=_SAMPLE_ROWS)
        execution = {
            "ok": not result.error,
            "row_count": int(result.row_count or len(result.rows or [])),
            "truncated": len(result.rows or []) >= _SAMPLE_ROWS,
            "error": result.error or "",
        }
        battery = validate_sql(connection_id, sql, db=db)
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "trusted verify: db close", counter="trusted_verify.close")

    passed = execution["ok"] and not battery.get("unchecked") \
        and not battery.get("mutation_blockers")
    return {"passed": bool(passed), "checked_at": checked_at, "blockers": blockers,
            "execution": execution, "battery": battery}
