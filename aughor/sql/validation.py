"""The on-demand guard battery, callable outside the HTTP layer.

Extracted verbatim from ``POST /query/validate`` (KI-0, §3.10) so that trusted-query
verification runs the SAME battery the validate endpoint runs — a second hand-copy of
this sequence would drift, and a battery that drifts is two batteries. The endpoint
delegates here; nothing about its response shape changed.
"""
from __future__ import annotations

from typing import Optional


def validate_sql(conn_id: str, sql: str, *, dialect: str = "duckdb",
                 params: Optional[dict] = None, db=None) -> dict:
    """Re-run the deterministic guard battery against the live connection and return a
    structured verdict — fan-out / chasm (static), join value-domain and filter
    value-domain (live probes), grain fan-out (live probe), CIDR-E1 trust checks, and
    the AST read-only gate. Each guard is fail-open: one that can't run is simply
    omitted, never an error.

    ``db``: an already-open connection to reuse (the caller keeps ownership and closes
    it); when omitted, the connection is opened from ``conn_id`` and closed here.
    Raises ``KeyError`` when ``conn_id`` names no connection and none was passed.
    """
    from aughor.db.connection import open_connection_for
    from aughor.kernel.errors import tolerate
    from aughor.sql.params import ParamRenderError, find_params, render_for_guards

    own_db = db is None
    if own_db:
        db = open_connection_for(conn_id)

    # SE-4 H — the guard battery reads LITERALS out of the SQL text. Measured on the
    # live warehouse: `WHERE country = 'Portugalx'` yields a value-domain warning
    # naming the typo and suggesting 'Portugal'; `WHERE country = $country` yields
    # ZERO warnings — the identical answer a CORRECT literal gives. So a parameterised
    # query checked as-is does not report "unverified", it reports CLEAN, and the
    # editor's header says "Guards clean" about a query no guard could see.
    #
    # The fix is a second rendering, for analysis only: substitute the values as
    # literals and guard THAT. Execution still binds (`execute_with_params`), so the
    # string built here never reaches an engine — there is deliberately no path from
    # this variable to `execute()`. When a value is missing or unrenderable, the
    # verdict says so instead of claiming a check it did not run.
    guard_note = ""
    if find_params(sql):
        try:
            sql = render_for_guards(sql, params or {})
        except ParamRenderError as exc:
            guard_note = (f"Not checked — this query is parameterised and {exc}. "
                          "Fill in the parameters to run the guards.")
    dialect = getattr(db, "dialect", None) or dialect or "duckdb"
    fanout_hits: list = []
    join_warnings: list = []
    filter_warnings: list = []
    grain_warnings: list = []
    trust_findings: list = []
    try:
        # Fan-out / chasm — static analysis over the connection's schema-derived columns.
        try:
            from aughor.tools.schema import parse_schema_tables
            from aughor.agent.verifier import Verifier
            table_cols = parse_schema_tables(db.get_schema())
            fanout_hits = Verifier.scan([sql], table_cols, dialect)
        except Exception as exc:
            tolerate(exc, "validate: fan-out scan", counter="validate.fanout")
        # Join value-domain — live overlap probe of each join's keys.
        try:
            from aughor.sql.join_guard import check_join_value_domains
            join_warnings = [
                {"table_a": w.table_a, "col_a": w.col_a, "table_b": w.table_b,
                 "col_b": w.col_b, "overlap": w.overlap}
                for w in check_join_value_domains(db, sql)
            ]
        except Exception as exc:
            tolerate(exc, "validate: join value-domain", counter="validate.join")
        # Filter value-domain — a guessed enum literal that matches no row but has a near neighbour.
        try:
            from aughor.sql.join_guard import check_filter_value_domains
            filter_warnings = [
                {"table": w.table, "column": w.col, "literal": w.bad_value,
                 "op": w.op, "suggestion": w.suggestion or ""}
                for w in check_filter_value_domains(db, sql)
            ]
        except Exception as exc:
            tolerate(exc, "validate: filter value-domain", counter="validate.filter")
        # Grain / fan-out — LIVE uniqueness probe of each join key (catches over-counting that
        # depends on the actual data, not just the schema, so it complements the static scan above).
        try:
            from aughor.sql.grain_guard import detect_fanout

            def _grain_probe(s: str):
                r = db.execute("__grain_probe__", s)
                return (not r.error, r.rows, r.error or "")

            grain_warnings = [
                {"table": f.fanned_table, "join_key": f.join_key,
                 "ratio": round(f.ratio, 2), "caveat": f.caveat()}
                for f in detect_fanout(sql, _grain_probe, dialect)
            ]
        except Exception as exc:
            tolerate(exc, "validate: grain fan-out", counter="validate.grain")
        # CIDR-E1 trust checks — function-semantics footguns (timestamp/date-literal boundary,
        # lexicographic order of numeric text, text-vs-numeric compare). Pure AST; col_types best-
        # effort from information_schema, with a name heuristic fallback for the date-boundary case.
        try:
            # One source of truth for the col-types introspection (shared with the live E1
            # answer paths): uncapped scan, cached per connection, fail-open to the heuristic.
            from aughor.sql.trust_checks import connection_column_types, run_trust_checks
            col_types = connection_column_types(conn_id, db) or None
            trust_findings = [f.to_dict() for f in run_trust_checks(
                sql, col_types=col_types, dialect=dialect, phase="validate")]
        except Exception as exc:
            tolerate(exc, "validate: trust checks", counter="validate.trust")
    finally:
        if own_db:
            try:
                db.close()
            except Exception as exc:
                tolerate(exc, "validate: db close", counter="validate.close")

    # AL-01 · Trust plane (behind trust.verify_facade): the AST read-only gate the answer
    # paths never ran on generated SQL. Additive — a mutating/DDL statement or a disallowed
    # function is a hard blocker, distinct from the advisory warnings above. Pure (no conn),
    # so it runs after the connection is closed.
    mutation_blockers: list = []
    try:
        from aughor.trust import verify as trust_verify, Scope
        verdict = trust_verify(sql, Scope(dialect=dialect))
        mutation_blockers = [{"name": c.name, "reason": c.reason, **c.detail}
                             for c in verdict.blockers]
    except Exception as exc:
        tolerate(exc, "validate: trust facade", counter="validate.trust_facade")

    issues = (len(fanout_hits) + len(join_warnings) + len(filter_warnings)
              + len(grain_warnings) + len(trust_findings) + len(mutation_blockers))
    if guard_note:
        # Not an issue COUNT — nothing was found because nothing could be looked at.
        # `passed` is false so no surface can render this as a clean bill of health.
        return {
            "passed": False, "issue_count": 0, "unchecked": True, "note": guard_note,
            "fanout_hits": [], "join_warnings": [], "filter_warnings": [],
            "grain_warnings": [], "trust_findings": [], "mutation_blockers": [],
        }
    return {
        "passed": issues == 0,
        "issue_count": issues,
        "unchecked": False,
        "fanout_hits": fanout_hits,
        "join_warnings": join_warnings,
        "filter_warnings": filter_warnings,
        "grain_warnings": grain_warnings,
        "trust_findings": trust_findings,
        "mutation_blockers": mutation_blockers,
    }
