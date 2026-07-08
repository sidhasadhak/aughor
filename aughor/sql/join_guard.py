"""
Value-domain join guard.

Every other join safety gate (detect_invalid_joins, check_entity_column_alignment,
Phase-8 binder) reasons about column names / types / ontology.  A wrong join can
still slip through when two columns share a name-shape but hold values from
entirely different entities — e.g. orders.customer_id = 'C-000123' while
forms.c_id = 'CF-98122'.  The value domain cannot be fooled the way names can.

This module probes value overlap by sampling both sides of each explicit JOIN
condition and checking containment.  A real FK has high overlap; a bogus join
has ~0%.  The check is entirely fail-open: any exception (unparseable SQL, CTE
alias, empty table, connection unavailable) returns no warnings and lets the
query proceed normally.

Hook: call check_join_value_domains(conn, sql) alongside detect_invalid_joins
in execute_planned_queries.  The returned JoinDomainWarning objects satisfy the
same .to_prompt_text() interface as JoinWarning / AmbiguityWarning.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

# Overlap below this fraction → warn.  Chosen conservatively so a lightly
# populated child table (e.g. a fresh orders table for today only) doesn't
# fire a false positive.  The warn-not-block design lets the query run.
_THRESHOLD = 0.15

# Rows sampled from each side.  Large enough to detect systematic mismatches;
# small enough that DuckDB resolves the probe in < 100 ms even on cold data.
_SAMPLE_A = 100   # from the join's LHS (the "many" / FK side)
_SAMPLE_B = 1000  # from the join's RHS (the referenced / PK side)

# Limit the number of join pairs probed per query — each probe is one extra
# query execution, so cap at 4 to keep the pre-flight fast.
_MAX_PROBES = 4


def _quote_table(name: str) -> str:
    """Return a safely quoted table reference for DuckDB.

    Handles both plain names ('orders') and schema-qualified names
    ('beauty.orders').  Does not attempt to quote names that already contain
    quotes, to avoid double-quoting caller mistakes.
    """
    if '"' in name:
        return name
    parts = name.split(".")
    return ".".join(f'"{p}"' for p in parts)


def _extract_join_conditions(sql: str) -> list[tuple[str, str, str, str]]:
    """Return (table_a, col_a, table_b, col_b) for each explicit JOIN … ON eq."""
    try:
        import sqlglot
        import sqlglot.expressions as exp

        tree = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)

        # Build alias → real-table-name map.
        alias_map: dict[str, str] = {}
        for tbl in tree.find_all(exp.Table):
            real = tbl.name or ""
            if tbl.db:
                real = f"{tbl.db}.{tbl.name}"
            alias = tbl.alias or real
            if alias:
                alias_map[alias.lower()] = real

        conditions: list[tuple[str, str, str, str]] = []
        for join in tree.find_all(exp.Join):
            on = join.args.get("on")
            if not on:
                continue
            for eq in on.find_all(exp.EQ):
                left, right = eq.left, eq.right
                if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                    continue
                raw_ta = (left.table or "").lower()
                raw_tb = (right.table or "").lower()
                if not raw_ta or not raw_tb:
                    continue
                t_a = alias_map.get(raw_ta, raw_ta)
                t_b = alias_map.get(raw_tb, raw_tb)
                c_a = left.name or ""
                c_b = right.name or ""
                if t_a and c_a and t_b and c_b and t_a != t_b:
                    conditions.append((t_a, c_a, t_b, c_b))
        return conditions
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: SQL parse failed — no conditions extracted",
                 counter="join_guard.parse_error")
        return []


def _probe_overlap(
    conn: "DatabaseConnection",
    table_a: str,
    col_a: str,
    table_b: str,
    col_b: str,
) -> float | None:
    """Fraction of sampled values from table_a.col_a found in table_b.col_b.

    Returns None on any failure (fail-open).
    """
    try:
        ta = _quote_table(table_a)
        tb = _quote_table(table_b)
        qa = f'"{col_a}"'
        qb = f'"{col_b}"'

        # Containment, not sample-vs-sample: take a small DISTINCT sample of the LHS
        # (FK side) and check each value against the FULL RHS column. Sampling BOTH
        # sides was the original bug — for a high-cardinality key (millions of distinct
        # order_id), two independent samples almost never intersect, so a perfectly
        # valid FK reported ~0% overlap and got flagged as fabricated. Checking the
        # sampled LHS values against the entire RHS gives the true containment fraction
        # (real FK → ~1.0; a bogus join like touchpoint_type=channel → 0.0).
        probe_sql = f"""
WITH s_a AS (
    SELECT DISTINCT CAST({qa} AS VARCHAR) AS v
    FROM {ta}
    USING SAMPLE {_SAMPLE_A} ROWS
)
SELECT
    (SELECT COUNT(*) FROM s_a) AS total,
    (SELECT COUNT(*) FROM s_a WHERE v IN (SELECT CAST({qb} AS VARCHAR) FROM {tb})) AS matched
""".strip()

        result = conn.execute("__domain_probe__", probe_sql)
        if result and result.rows:
            # The connection stringifies all result values (no dtype passthrough),
            # so coerce to int before any numeric comparison.
            total = int(result.rows[0][0])
            matched = int(result.rows[0][1])
            if total > 0:
                return matched / total
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: value-domain probe failed — join allowed to proceed",
                 counter="join_guard.probe_error")
    return None


# Above this many rows on either side, the exact probe's full RHS scan (a hashed IN-set of
# every distinct value) gets expensive — estimate containment with a HyperLogLog instead.
_HLL_MIN_ROWS = max(1, int(os.getenv("AUGHOR_JOIN_HLL_MIN_ROWS", "1000000")))


def hll_min_rows() -> int:
    """The per-table row-count threshold above which join overlap is HLL-estimated rather
    than exactly probed (env ``AUGHOR_JOIN_HLL_MIN_ROWS``). Public so the explorer's phase-4
    precompute shares one source of truth."""
    return _HLL_MIN_ROWS


def _probe_overlap_hll(
    conn: "DatabaseConnection",
    table_a: str,
    col_a: str,
    table_b: str,
    col_b: str,
) -> float | None:
    """Containment of ``table_a.col_a`` in ``table_b.col_b`` estimated via HLL
    inclusion–exclusion (``approx_count_distinct``) — one aggregate pass per side, no
    anti-join and no materialised IN-set, so it stays cheap on huge tables. Returns the
    containment fraction in [0, 1] (real FK → ~1.0; disjoint → ~0.0), or None (fail-open)."""
    try:
        from aughor.sql.sketches import overlap_from_hll
        ta, tb = _quote_table(table_a), _quote_table(table_b)
        qa, qb = f'"{col_a}"', f'"{col_b}"'
        sql = f"""
SELECT
  (SELECT approx_count_distinct(CAST({qa} AS VARCHAR)) FROM {ta} WHERE {qa} IS NOT NULL) AS a_d,
  (SELECT approx_count_distinct(CAST({qb} AS VARCHAR)) FROM {tb} WHERE {qb} IS NOT NULL) AS b_d,
  (SELECT approx_count_distinct(v) FROM (
       SELECT CAST({qa} AS VARCHAR) AS v FROM {ta} WHERE {qa} IS NOT NULL
       UNION ALL
       SELECT CAST({qb} AS VARCHAR)      FROM {tb} WHERE {qb} IS NOT NULL
   ) AS _u) AS union_d
""".strip()
        result = conn.execute("__hll_overlap_probe__", sql)
        if result and result.rows:
            a_d, b_d, u_d = (int(result.rows[0][0]), int(result.rows[0][1]), int(result.rows[0][2]))
            _, cont_a, _ = overlap_from_hll(a_d, b_d, u_d)
            return cont_a
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: HLL overlap probe failed — fall back / allow",
                 counter="join_guard.hll_error")
    return None


def _probe_pair(conn, t1, c1, t2, c2, table_rows, hll_min_rows) -> float | None:
    """Max bidirectional containment for one edge, choosing the HLL estimator when either
    side is large (``table_rows`` known) and the exact sampled probe otherwise."""
    big = bool(table_rows) and (
        int((table_rows or {}).get(t1, 0) or 0) >= hll_min_rows
        or int((table_rows or {}).get(t2, 0) or 0) >= hll_min_rows
    )
    probe = _probe_overlap_hll if big else _probe_overlap
    overlaps = [o for o in (probe(conn, t1, c1, t2, c2), probe(conn, t2, c2, t1, c1)) if o is not None]
    return max(overlaps) if overlaps else None


# ── Ill-formatted join-key reconciliation (DataAgentBench GAP-3) ─────────────────────
# When two join keys have LOW raw value overlap they may still refer to the SAME entity
# under a formatting skew — a differing prefix (bid_123 vs bref_123), whitespace, case, or
# leading zeros — the #3 hard axis in DataAgentBench (26/54 queries). This tries a small,
# fixed set of DETERMINISTIC normalizations on both keys, re-probes overlap under each, and
# — if one lifts overlap over a "reconciled" bar — surfaces the exact normalization to join
# on. It distinguishes "same entity, different format" (a transform reconciles → actionable
# repair) from "genuinely different entities" (nothing reconciles → the mismatch stands).
# Deterministic, monotonic (only ever ADDS a suggestion), fail-open, gated on
# `join.key_reconciliation`. DuckDB expression syntax — matches the existing probe (which is
# DuckDB-centric; both fail open on dialects that reject the sample/regexp syntax), which is
# exactly the cross-source federation surface (a FederatedConnection is DuckDB).

# name → (human label, DuckDB expression template over {col})
_KEY_TRANSFORMS: list[tuple[str, str, str]] = [
    ("trim_lower",   "trimmed + lowercased",                  "lower(trim(CAST({col} AS VARCHAR)))"),
    ("digits",       "digits only",                           "regexp_replace(CAST({col} AS VARCHAR), '[^0-9]', '', 'g')"),
    ("strip_prefix", "leading letters/underscores stripped",  "regexp_replace(CAST({col} AS VARCHAR), '^[A-Za-z_]+', '')"),
    ("strip_zeros",  "leading zeros stripped",                "regexp_replace(trim(CAST({col} AS VARCHAR)), '^0+', '')"),
    ("alnum_lower",  "alphanumerics only, lowercased",        "lower(regexp_replace(CAST({col} AS VARCHAR), '[^A-Za-z0-9]', '', 'g'))"),
]

# A transform must lift overlap to at least this, AND by at least _RECONCILE_MIN_GAIN over the
# raw overlap, to count — so a marginal coincidence never masquerades as a reconciliation.
_RECONCILE_MIN_OVERLAP = 0.60
_RECONCILE_MIN_GAIN    = 0.30


@dataclass
class KeyReconciliation:
    transform: str
    label: str
    expr_a: str     # DuckDB expression to normalize side A's key
    expr_b: str     # ... and side B's key
    overlap: float  # reconciled overlap under the transform


def _probe_overlap_expr(conn, table_a: str, expr_a: str, table_b: str, expr_b: str) -> float | None:
    """Containment of transformed A-values in transformed B-values (empty/NULL results ignored).

    Returns None on any failure (fail-open)."""
    try:
        ta, tb = _quote_table(table_a), _quote_table(table_b)
        probe_sql = f"""
WITH s_a AS (
    SELECT DISTINCT {expr_a} AS v FROM {ta} USING SAMPLE {_SAMPLE_A} ROWS
)
SELECT
    (SELECT COUNT(*) FROM s_a WHERE v IS NOT NULL AND v <> '') AS total,
    (SELECT COUNT(*) FROM s_a
        WHERE v IS NOT NULL AND v <> '' AND v IN (SELECT {expr_b} FROM {tb})) AS matched
""".strip()
        result = conn.execute("__reconcile_probe__", probe_sql)
        if result and result.rows:
            total = int(result.rows[0][0])
            matched = int(result.rows[0][1])
            if total > 0:
                return matched / total
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: reconcile probe failed — no suggestion",
                 counter="join_guard.reconcile_error")
    return None


def reconcile_join_keys(
    conn, table_a: str, col_a: str, table_b: str, col_b: str, raw_overlap: float,
) -> KeyReconciliation | None:
    """Try deterministic normalizations to reconcile two low-overlap join keys.

    Returns the first transform that materially lifts overlap (direction-aware, like the raw
    probe), or None if the keys are genuinely disjoint. Fail-open throughout."""
    for name, label, tmpl in _KEY_TRANSFORMS:
        ea = tmpl.format(col=f'"{col_a}"')
        eb = tmpl.format(col=f'"{col_b}"')
        ov_ab = _probe_overlap_expr(conn, table_a, ea, table_b, eb)
        ov_ba = _probe_overlap_expr(conn, table_b, eb, table_a, ea)
        ovs = [o for o in (ov_ab, ov_ba) if o is not None]
        if not ovs:
            continue
        ov = max(ovs)
        if ov >= _RECONCILE_MIN_OVERLAP and ov - raw_overlap >= _RECONCILE_MIN_GAIN:
            return KeyReconciliation(name, label, ea, eb, ov)
    return None


@dataclass
class JoinDomainWarning:
    table_a: str
    col_a: str
    table_b: str
    col_b: str
    overlap: float
    reconciliation: KeyReconciliation | None = None

    def to_prompt_text(self) -> str:
        pct = f"{self.overlap:.0%}"
        base = (
            f"JOIN VALUE-DOMAIN MISMATCH: {self.table_a}.{self.col_a} ↔ "
            f"{self.table_b}.{self.col_b} — only {pct} of sampled values match. "
        )
        if self.reconciliation:
            r = self.reconciliation
            return (
                base
                + f"BUT they reconcile to {r.overlap:.0%} overlap after normalizing both keys "
                f"({r.label}) — the keys refer to the same entity in different formats. Join on "
                f"the normalized expressions instead: ON {r.expr_a} = {r.expr_b}."
            )
        return (
            base
            + "These columns likely belong to different entities. "
            "Verify you are joining on the correct column pair."
        )


def check_join_value_domains(
    conn: "DatabaseConnection",
    sql: str,
    threshold: float = _THRESHOLD,
) -> list[JoinDomainWarning]:
    """Check each explicit JOIN condition for value-domain overlap.

    Returns a (possibly empty) list of warnings.  Never raises — entirely
    fail-open so the calling query path is never blocked by the guard.
    """
    warnings: list[JoinDomainWarning] = []
    try:
        conditions = _extract_join_conditions(sql)
        for t_a, c_a, t_b, c_b in conditions[:_MAX_PROBES]:
            # Direction-aware containment: a real FK is contained in ONE direction
            # (child ⊆ parent), even when the parent has many keys the child lacks. The
            # single-direction check false-flagged a legitimate parent⋈child subset join
            # (orders ⋈ refunds: only ~10% of orders are refunded, so orders→refunds reads
            # 10%, but refunds→orders is ~100%). Probe BOTH ways and take the MAX — a truly
            # fabricated join (different entities, e.g. touchpoint_type = channel) is low
            # BOTH ways and still flags; a subset FK is high one way and passes.
            ov_ab = _probe_overlap(conn, t_a, c_a, t_b, c_b)
            ov_ba = _probe_overlap(conn, t_b, c_b, t_a, c_a)
            overlaps = [o for o in (ov_ab, ov_ba) if o is not None]
            if overlaps and max(overlaps) < threshold:
                raw = max(overlaps)
                recon = None
                try:
                    from aughor.kernel.flags import flag_enabled
                    if flag_enabled("join.key_reconciliation"):
                        recon = reconcile_join_keys(conn, t_a, c_a, t_b, c_b, raw)
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "join_guard: reconciliation skipped — mismatch still surfaced",
                             counter="join_guard.reconcile_gate_error")
                warnings.append(JoinDomainWarning(t_a, c_a, t_b, c_b, raw, reconciliation=recon))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: domain check failed — no warnings emitted",
                 counter="join_guard.check_error")
    if warnings:
        from aughor.stats import bump
        bump("guard.join_domain.fired", len(warnings))
        reconciled = sum(1 for w in warnings if w.reconciliation is not None)
        if reconciled:
            bump("guard.join_domain.reconciled", reconciled)
    return warnings


# ── Build-time joinability: PREVENT a value-disjoint join, not just catch it ─────────
# The query-time guard above catches a value-disjoint join when the model writes one. This
# precomputes the SAME value-overlap signal at BUILD time over the NAME-inferred join
# candidates, so a join whose two keys share a name-shape but hold disjoint values is
# demoted to "do not join" BEFORE generation — the model never sees it as a valid FK, so it
# can't draw it in the first place (prevention, not recovery). Bounded (only the small set
# of name-matched candidates is probed), cached per connection, fail-open (an unverifiable
# edge is KEPT — we never reject on inability to check).
_JOINABLE_MAX_PROBES = 32
_VERIFIED_JOIN_CACHE: dict = {}


@dataclass
class VerifiedJoin:
    t1: str
    c1: str
    t2: str
    c2: str
    overlap: float        # max containment fraction across both directions; -1.0 = unverifiable
    match: str = "exact"  # the name-inference confidence carried through


def verify_join_edges(
    conn: "DatabaseConnection",
    joins: list,
    *,
    threshold: float = _THRESHOLD,
    max_probes: int = _JOINABLE_MAX_PROBES,
    table_rows: "dict | None" = None,
    hll_min_rows: int = _HLL_MIN_ROWS,
) -> tuple:
    """Probe each name-inferred join edge for value overlap. Returns ``(verified, rejected)``
    lists of :class:`VerifiedJoin`. An edge is VERIFIED when its keys actually share values
    (a real FK → ~1.0) or can't be probed (fail-open), REJECTED when value-disjoint (a
    name-shape coincidence → ~0.0). When ``table_rows`` is supplied, edges touching a table
    above ``hll_min_rows`` are estimated with a HyperLogLog (cheap on huge tables) instead of
    the exact sampled probe."""
    verified: list = []
    rejected: list = []
    for j in (joins or [])[:max_probes]:
        t1, c1, t2, c2 = j.get("t1"), j.get("c1"), j.get("t2"), j.get("c2")
        if not all((t1, c1, t2, c2)):
            continue
        ov = _probe_pair(conn, t1, c1, t2, c2, table_rows, hll_min_rows)
        vj = VerifiedJoin(t1, c1, t2, c2, overlap=(ov if ov is not None else -1.0),
                          match=j.get("match", "exact"))
        (rejected if (ov is not None and ov < threshold) else verified).append(vj)
    return verified, rejected


def verified_join_edges(conn: "DatabaseConnection", joins: list, *, cache_key: str = "",
                        table_rows: "dict | None" = None) -> tuple:
    """Cached :func:`verify_join_edges` — computed once per (cache_key, edge-signature) so the
    overlap probes run at build time, not per question. An empty ``cache_key`` disables caching.
    ``table_rows`` (table → row count) routes huge tables through the HLL estimator."""
    sig = tuple(sorted((j.get("t1"), j.get("c1"), j.get("t2"), j.get("c2")) for j in (joins or [])))
    key = (cache_key, sig)
    if cache_key and key in _VERIFIED_JOIN_CACHE:
        return _VERIFIED_JOIN_CACHE[key]
    result = verify_join_edges(conn, joins, table_rows=table_rows)
    if cache_key:
        _VERIFIED_JOIN_CACHE[key] = result
    return result


def seed_verified_cache(cache_key: str, joins: list, verifications: list) -> tuple:
    """Precompute path: turn the explorer's phase-4 FK checks into the build-time joinability
    cache, so the data catalog reuses that work instead of re-probing. ``verifications`` are the
    explorer's ``join_verifications`` records ({from_table, from_col, to_table, to_col, verified,
    orphan_count, fk_distinct, ...}); a non-verified (orphaned) edge becomes a REJECTED (do-not-
    join) entry. Keyed by the SAME (cache_key, edge-signature) :func:`verified_join_edges` reads,
    so a later catalog build hits the cache. Returns ``(verified, rejected)``. Fail-open."""
    verified: list = []
    rejected: list = []
    try:
        by_pair = {(v.get("from_table"), v.get("from_col"), v.get("to_table"), v.get("to_col")): v
                   for v in (verifications or [])}
        for j in (joins or []):
            t1, c1, t2, c2 = j.get("t1"), j.get("c1"), j.get("t2"), j.get("c2")
            rec = by_pair.get((t1, c1, t2, c2)) or by_pair.get((t2, c2, t1, c1))
            if rec is None:
                continue
            fk_d = int(rec.get("fk_distinct") or 0)
            orphans = int(rec.get("orphan_count") or 0)
            # containment of the FK side ≈ (distinct − orphaned) / distinct
            ov = (max(0, fk_d - orphans) / fk_d) if fk_d > 0 else (1.0 if rec.get("verified") else 0.0)
            vj = VerifiedJoin(t1, c1, t2, c2, overlap=ov, match=j.get("match", "exact"))
            (verified if rec.get("verified") or ov >= _THRESHOLD else rejected).append(vj)
        sig = tuple(sorted((j.get("t1"), j.get("c1"), j.get("t2"), j.get("c2")) for j in (joins or [])))
        if cache_key:
            _VERIFIED_JOIN_CACHE[(cache_key, sig)] = (verified, rejected)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: seed_verified_cache best-effort", counter="join_guard.seed_error")
    return verified, rejected


def render_verified_joins(verified: list, rejected: list) -> str:
    """The data-catalog block: the value-verified FK joins to USE, plus an explicit
    DO-NOT-JOIN list for the name-shape coincidences that hold disjoint values."""
    lines: list = []
    if verified:
        lines.append("FOREIGN KEY JOINS (value-verified — use these exact keys to join the tables above):")
        for v in verified:
            lines.append(f"  {'✓' if v.overlap >= 0 else '·'} {v.t1}.{v.c1} = {v.t2}.{v.c2}")
    if rejected:
        lines.append("")
        lines.append("DO NOT JOIN (these column pairs share a name but hold DISJOINT values — "
                     "joining them fabricates rows):")
        for r in rejected:
            lines.append(f"  ✗ {r.t1}.{r.c1} ≠ {r.t2}.{r.c2}  ({r.overlap:.0%} value overlap)")
    return "\n".join(lines)


# ── WHERE/HAVING literal value-domain guard ─────────────────────────────────
# The join guard protects join KEYS; this protects FILTER LITERALS. A model that
# guesses an enum value — `order_status = 'cancelled'` when the data holds
# 'canceled' — produces a query that runs clean but silently matches ZERO rows, so
# every cancellation rate reads 0%. The fix probes the column's actual domain and,
# only when the column is enumerable (few distinct values) AND the guessed literal
# is absent BUT a close real value exists, flags it with the correct value. The
# close-match requirement keeps it high-precision: a genuinely-valid-but-empty
# filter (e.g. status='refunded' with no refunds yet) has no near neighbour and is
# left alone.
_FILTER_MAX_PROBES = 6
_ENUMERABLE_MAX_DISTINCT = 50
_HIGHCARD_SAMPLE = 10000   # CHESS used N=10000 sampled distinct values for its value index
_HIGHCARD_CUTOFF = 0.82    # stricter than the ≤50-distinct 0.6 — high-cardinality binding is riskier


@dataclass
class FilterDomainWarning:
    table: str
    col: str
    bad_value: str
    valid_values: list[str]
    suggestion: str | None
    op: str = "="

    def to_prompt_text(self) -> str:
        vals = ", ".join(repr(v) for v in self.valid_values[:12])
        sugg = f" Did you mean '{self.suggestion}'?" if self.suggestion else ""
        if self.op in ("!=", "NOT IN"):
            # A negated predicate on a missing value is a SILENT NO-OP: `status != 'cancelled'`
            # keeps every row when no row equals 'cancelled', so a filter meant to DROP those
            # rows drops none (the Q29 "zero cancellations despite 15,737" scar).
            effect = (f"{self.table}.{self.col} {self.op} '{self.bad_value}' excludes NO rows — that "
                      f"exact value is not in the column, so this filter is a silent no-op and the "
                      f"rows you meant to remove are all kept.")
        else:
            effect = (f"{self.table}.{self.col} {self.op} '{self.bad_value}' matches NO rows — that "
                      f"exact value is not in the column.")
        return (
            f"FILTER VALUE MISMATCH: {effect}{sugg} The column's actual values are: {vals}. "
            f"Rewrite the predicate using an EXACT value from that list."
        )


def _extract_filter_literals(sql: str) -> list[tuple[str, str, str, str]]:
    """(table, col, literal, op) for `col = 'lit'` / `col != 'lit'` / `col [NOT] IN (…)`
    predicates that are NOT inside a JOIN … ON (those are the join guard's job). `op` is one
    of '=', '!=', 'IN', 'NOT IN'. Unqualified columns resolve only when the query has exactly
    one base table — otherwise the column is ambiguous and skipped (fail-safe).

    Negated predicates (`!=` / `NOT IN`) matter as much as positive ones: a misspelled
    EXCLUDED literal is a silent no-op (`status != 'cancelled'` keeps every row when the data
    holds 'canceled'), the Q29 'zero cancellations despite 15,737' scar."""
    out: list[tuple[str, str, str, str]] = []
    try:
        import sqlglot
        import sqlglot.expressions as exp
        tree = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception:
        return out
    alias_map: dict[str, str] = {}
    base_tables: list[str] = []
    for tbl in tree.find_all(exp.Table):
        real = f"{tbl.db}.{tbl.name}" if tbl.db else (tbl.name or "")
        alias = tbl.alias or real
        if alias:
            alias_map[alias.lower()] = real
        if real:
            base_tables.append(real)
    distinct_bases = set(base_tables)
    on_node_ids: set[int] = set()
    for j in tree.find_all(exp.Join):
        on = j.args.get("on")
        if on is not None:
            for node in on.walk():
                on_node_ids.add(id(node))

    def _resolve(colnode) -> str | None:
        raw_t = (colnode.table or "").lower()
        if raw_t:
            return alias_map.get(raw_t, raw_t)
        return next(iter(distinct_bases)) if len(distinct_bases) == 1 else None

    def _emit_binary(node, op: str) -> None:
        # `col <op> 'lit'` (or the reversed `'lit' <op> col`) → record it.
        col = lit = None
        if isinstance(node.left, exp.Column) and isinstance(node.right, exp.Literal) and node.right.is_string:
            col, lit = node.left, node.right
        elif isinstance(node.right, exp.Column) and isinstance(node.left, exp.Literal) and node.left.is_string:
            col, lit = node.right, node.left
        if col is not None:
            t = _resolve(col)
            if t and col.name:
                out.append((t, col.name, lit.this, op))

    for eq in tree.find_all(exp.EQ):
        if id(eq) not in on_node_ids:
            _emit_binary(eq, "=")
    # `!=` and `<>` both parse to exp.NEQ — a negated equality.
    for neq in tree.find_all(exp.NEQ):
        if id(neq) not in on_node_ids:
            _emit_binary(neq, "!=")
    for inn in tree.find_all(exp.In):
        if id(inn) in on_node_ids:
            continue
        col = inn.this
        if isinstance(col, exp.Column):
            t = _resolve(col)
            if t and col.name:
                # `col NOT IN (…)` parses as Not(In(…)) — the negated form.
                op = "NOT IN" if isinstance(inn.parent, exp.Not) else "IN"
                for e in inn.expressions:
                    if isinstance(e, exp.Literal) and e.is_string:
                        out.append((t, col.name, e.this, op))
    return out


def _highcard_bind_warnings(conn: "DatabaseConnection", t: str, c: str,
                            litops: "set[tuple[str, str]]") -> list[FilterDomainWarning]:
    """Bind a guessed literal on a HIGH-cardinality text column (names/SKUs/cities) to its nearest
    real value — but ONLY when the literal is execution-confirmed absent and a close neighbour exists
    in a bounded sample of the live domain. Positive predicates only (=, IN): never weaken a negation
    by rewriting it. CHESS-style: trigram-blocked value index over a distinct sample."""
    from aughor.sql.value_index import ValueIndex
    out: list[FilterDomainWarning] = []
    positives = [(lit, op) for lit, op in litops if op in ("=", "IN")]
    if not positives:
        return out
    qt, qc = _quote_table(t), f'"{c}"'
    index: "ValueIndex | None" = None
    for lit, op in positives:
        safe = lit.replace("'", "''")
        exists = conn.execute(
            "__filter_highcard_exists__",
            f"SELECT 1 FROM {qt} WHERE LOWER(CAST({qc} AS VARCHAR)) = LOWER('{safe}') LIMIT 1",
        )
        if exists and exists.rows:
            continue  # the literal is a real value — do not second-guess it
        if index is None:  # build the index once per column, lazily (only when a literal is absent)
            res = conn.execute(
                "__filter_highcard_sample__",
                f"SELECT DISTINCT CAST({qc} AS VARCHAR) AS v FROM {qt} "
                f"WHERE {qc} IS NOT NULL LIMIT {_HIGHCARD_SAMPLE}",
            )
            sample = [r[0] for r in res.rows if r and r[0] is not None] if res and res.rows else []
            index = ValueIndex(sample)
        best = index.best_match(lit, cutoff=_HIGHCARD_CUTOFF)
        if best and best.lower() != lit.lower():
            out.append(FilterDomainWarning(t, c, lit, [best], best, op))
    return out


def check_filter_value_domains(conn: "DatabaseConnection", sql: str) -> list[FilterDomainWarning]:
    """Flag WHERE/HAVING equality/IN literals that don't exist in an enumerable column's
    actual value domain (a guessed enum value). Fail-open; never raises."""
    import difflib
    from collections import defaultdict
    warnings: list[FilterDomainWarning] = []
    try:
        by_col: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        for t, c, lit, op in _extract_filter_literals(sql):
            by_col[(t, c)].add((lit, op))
        for (t, c), litops in list(by_col.items())[:_FILTER_MAX_PROBES]:
            try:
                qt, qc = _quote_table(t), f'"{c}"'
                res = conn.execute(
                    "__filter_domain_probe__",
                    f"SELECT DISTINCT CAST({qc} AS VARCHAR) AS v FROM {qt} "
                    f"WHERE {qc} IS NOT NULL LIMIT {_ENUMERABLE_MAX_DISTINCT + 1}",
                )
                if not res or not res.rows:
                    continue
                vals = [r[0] for r in res.rows if r and r[0] is not None]
                if not vals:
                    continue
                if len(vals) > _ENUMERABLE_MAX_DISTINCT:
                    # High-cardinality column: the ≤50 enumeration can't see the domain. Use a
                    # CHESS-style value index over a bounded sample, but only bind a literal that is
                    # execution-confirmed absent (so we never second-guess a real value).
                    warnings.extend(_highcard_bind_warnings(conn, t, c, litops))
                    continue
                exact = set(vals)
                by_lower = {v.lower(): v for v in vals}   # lower -> stored casing
                for lit, op in litops:
                    if lit in exact:
                        continue                            # exact stored value — fine
                    if lit.lower() in by_lower:
                        # Case-only difference: SQL '=' is case-sensitive, so this matches no row
                        # (the 'Womenswear' vs stored 'womenswear' bug). Bind to the stored casing.
                        warnings.append(FilterDomainWarning(t, c, lit, vals, by_lower[lit.lower()], op))
                        continue
                    close = difflib.get_close_matches(lit, vals, n=1, cutoff=0.6)
                    if close:  # only flag an obvious typo/variant, never a novel value
                        warnings.append(FilterDomainWarning(t, c, lit, vals, close[0], op))
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "filter_guard: value-domain probe failed — query allowed to proceed",
                         counter="filter_guard.probe_error")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "filter_guard: check failed — no warnings emitted",
                 counter="filter_guard.check_error")
    return warnings


def repair_filter_literals(sql: str, warnings: list["FilterDomainWarning"],
                           dialect: str = "duckdb") -> "str | None":
    """Deterministically rewrite each guessed filter literal to its confirmed stored value.

    Given probe-confirmed warnings (a literal that matches no row but has a close neighbour in the
    column's actual domain), replace ONLY the literal in the comparison on that exact (table, column)
    — never other identical strings elsewhere. Returns the rewritten SQL, or None if nothing changed.
    Pure AST surgery; the caller dry-runs the result before adopting, so a bad rewrite is never used."""
    import sqlglot
    import sqlglot.expressions as exp

    fixes = {(w.table.lower(), w.col.lower(), w.bad_value): w.suggestion
             for w in warnings if w.suggestion}
    if not fixes:
        return None
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    a2t: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        a2t[t.name.lower()] = t.name
        if t.alias:
            a2t[t.alias.lower()] = t.name
    all_tables = {t.name for t in tree.find_all(exp.Table)}

    def _resolve(colnode) -> "str | None":
        if colnode.table:
            return a2t.get(colnode.table.lower())
        return next(iter(all_tables)) if len(all_tables) == 1 else None

    changed = False
    for lit in tree.find_all(exp.Literal):
        if not lit.is_string:
            continue
        parent = lit.parent
        col = None
        if isinstance(parent, (exp.EQ, exp.NEQ)):
            other = parent.left if parent.right is lit else parent.right
            if isinstance(other, exp.Column):
                col = other
        elif isinstance(parent, exp.In) and isinstance(parent.this, exp.Column):
            col = parent.this
        if col is None or not col.name:
            continue
        t = _resolve(col)
        if not t:
            continue
        sugg = fixes.get((t.lower(), col.name.lower(), lit.this))
        if sugg is not None:
            lit.set("this", sugg)
            changed = True
    return tree.sql(dialect=dialect) if changed else None


def bind_filter_literals(conn: "DatabaseConnection", sql: str,
                         dialect: str = "duckdb") -> "tuple[str, list]":
    """Detect guessed filter literals against the live column domain and actively bind them to the
    stored values. Returns (possibly-rewritten sql, applied warnings). Fail-open: on any issue or no
    confident fix, returns the original sql and an empty list."""
    try:
        warnings = check_filter_value_domains(conn, sql)
        if not warnings:
            return sql, []
        fixed = repair_filter_literals(sql, warnings, dialect)
        if fixed and fixed.strip() != sql.strip():
            return fixed, warnings
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "filter_guard: active binding skipped", counter="filter_guard.bind_error")
    return sql, []
