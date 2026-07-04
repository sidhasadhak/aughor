"""The Trust & Governance plane (AL-01) — one `verify(artifact, scope) -> Verdict` façade.

Every capability that produces an artifact (SQL today; code / metadata next) asks the Trust
plane one question — "is this safe, and what's wrong with it?" — instead of hand-assembling a
subset of the ~9 guard modules. The façade *delegates* to the existing modules (composition,
not a rewrite): each guard is wrapped into a `Check`, and the collection is a `Verdict`.

Guard composition for `kind="sql"`:

  * readonly (BLOCK)      — AST mutation / destruction / disallowed-function detection.
                            Decisive and NOT swallowed (the one safety-critical verdict; this
                            is the guard the answer paths were missing — closes SEC-02's
                            "read-only isn't enforced on the generation path" at the plane).
  * trust_checks (WARN)   — CIDR-E1 function-semantics footguns. Pure AST + optional col_types.
  * preflight (repair)    — conn-gated: the shared identifier-repair / filter-bind / dry-run /
                            SqlWriter.fix chain. Folds its receipt into checks and returns the
                            repaired SQL as `Verdict.artifact`.
  * join_domain (WARN)    — conn-gated: live value-domain overlap probe of each join's keys.
  * grain (WARN)          — conn-gated: live uniqueness probe of each join key (fan-out).

Deferred to later AL-01 slices (documented, not silently dropped): the `code` / `metadata`
kinds; the semantic-alignment (`tools/semantic_validator`), parallel-consistency
(`tools/sql_consistency`), numeric-claim (`agent/verify`), structural-ambiguity (`agent/soma`)
and consensus (`agent/sql_consensus`) guards; and migrating the answer paths off their inline
guard calls onto this façade. This slice builds the plane + its conformance test and wires the
first consumer (the `/query/validate` surface) behind the `trust.verify_facade` flag.
"""
from __future__ import annotations

from aughor.trust.verdict import BLOCK, INFO, WARN, Check, Scope, Verdict

__all__ = ["verify", "Verdict", "Check", "Scope", "BLOCK", "WARN", "INFO"]


def _tolerate(exc: Exception, where: str, counter: str = "") -> None:
    """Advisory guards fail-open (their absence degrades to 'no warning', never a crash). The
    readonly BLOCK verdict is the one exception — it is called directly, never routed here.
    `tolerate` is the kernel's swallow-logger and never raises, so no wrapper guard is needed."""
    from aughor.kernel.errors import tolerate
    tolerate(exc, where, counter=counter or "trust.verify")


def verify(artifact: str, scope: Scope | None = None, *, kind: str = "sql") -> Verdict:
    """Verify one artifact against `scope`; return a `Verdict`. Never raises.

    `kind` dispatches the guard set. Only `"sql"` composes guards today; `"code"` / `"metadata"`
    return a trivially-ok Verdict (a documented follow-up) so callers can already route every
    artifact kind through the one façade."""
    scope = scope or Scope()
    if kind == "sql":
        return _verify_sql(artifact or "", scope)
    return Verdict(kind=kind, artifact=artifact or "")


def _verify_sql(sql: str, scope: Scope) -> Verdict:
    checks: list[Check] = []
    dialect = scope.dialect or "duckdb"

    # 1 — Read-only / mutation: the decisive BLOCK. `readonly.*` never raises (positive-only,
    #     False on parse failure), so it is called directly — a mutation verdict must never be
    #     swallowed by a tolerate().
    from aughor.sql import readonly
    if readonly.is_mutating(sql, dialect):
        checks.append(Check(
            "readonly", ok=False, severity=BLOCK,
            reason="statement mutates data / schema / state",
            detail={"destructive": readonly.is_destructive(sql, dialect)},
        ))
    bad_fns = readonly.disallowed_functions(sql, dialect)
    if bad_fns:
        checks.append(Check(
            "disallowed_functions", ok=False, severity=BLOCK,
            reason="uses disallowed function(s): " + ", ".join(sorted(bad_fns)),
            detail={"functions": sorted(bad_fns)},
        ))

    # 2 — CIDR-E1 function-semantics footguns: advisory WARN. Pure AST + optional col_types.
    try:
        from aughor.sql.trust_checks import run_trust_checks
        for f in run_trust_checks(sql, col_types=scope.col_types, dialect=dialect):
            d = f.to_dict()
            checks.append(Check("trust_checks", ok=False, severity=WARN,
                                reason=d.get("message", ""), detail=d))
    except Exception as exc:
        _tolerate(exc, "trust.verify: E1 trust_checks")

    out, repaired = sql, False

    # 3–5 — Probe / repair guards need a live connection; skip cleanly without one.
    if scope.conn is not None:
        # Preflight repair — the existing shared chain; fold its receipt in and adopt the fix.
        try:
            from aughor.sql.safety import preflight_repair
            fixed_sql, receipt = preflight_repair(scope.conn, sql, scope.schema)
            if fixed_sql and fixed_sql.strip() != sql.strip():
                out, repaired = fixed_sql, True
            bound = receipt.get("dry_run_ok")
            if bound is False and not receipt.get("fixed"):
                checks.append(Check("preflight", ok=False, severity=WARN,
                                    reason="SQL did not bind (dry-run failed)", detail=receipt))
            elif any(receipt.get(k) for k in ("identifiers_repaired", "filter_bound", "fixed")):
                checks.append(Check("preflight", ok=True, severity=INFO,
                                    reason="SQL repaired before execute", detail=receipt))
        except Exception as exc:
            _tolerate(exc, "trust.verify: preflight_repair")

        # Join value-domain — live overlap probe of each join's keys.
        try:
            from aughor.sql.join_guard import check_join_value_domains
            for w in check_join_value_domains(scope.conn, out):
                reason = w.to_prompt_text() if hasattr(w, "to_prompt_text") else "join value-domain mismatch"
                checks.append(Check("join_domain", ok=False, severity=WARN, reason=reason,
                                    detail={k: getattr(w, k) for k in ("table_a", "col_a", "table_b", "col_b", "overlap")
                                            if hasattr(w, k)}))
        except Exception as exc:
            _tolerate(exc, "trust.verify: join value-domain")

        # Grain / fan-out — live uniqueness probe of each join key.
        try:
            from aughor.sql.grain_guard import detect_fanout

            def _probe(s: str):
                r = scope.conn.execute("__trust_grain__", s)
                return (not r.error, r.rows, r.error or "")

            for f in detect_fanout(out, _probe, dialect):
                checks.append(Check("grain", ok=False, severity=WARN, reason=f.caveat(),
                                    detail={"table": f.fanned_table, "join_key": f.join_key,
                                            "ratio": round(f.ratio, 2)}))
        except Exception as exc:
            _tolerate(exc, "trust.verify: grain fan-out")

    return Verdict(kind="sql", artifact=out, checks=tuple(checks),
                   repaired=repaired, original=sql if repaired else "")
