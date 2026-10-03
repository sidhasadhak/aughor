"""
Value-domain join guard.

Every other join safety gate (detect_invalid_joins, check_entity_column_alignment,
Phase-8 binder) reasons about column names / types / ontology.  A wrong join can
still slip through when two columns share a name-shape but hold values from
entirely different entities — e.g. orders.customer_id = 'C-000123' while
forms.c_id = 'CF-98122'.  The value domain cannot be fooled the way names can.

This module probes value overlap by sampling both sides of each explicit JOIN
condition and checking containment.  A real FK has high overlap; a bogus join
has ~0%.  The check is fail-open — the query always proceeds — but not silent:
what it could not check (unparseable SQL, a refused probe, a side it cannot
attribute) is returned as `unchecked` by `join_domain_check` (GM-4).

Hook: call check_join_value_domains(conn, sql) alongside detect_invalid_joins
in execute_planned_queries.  The returned JoinDomainWarning objects satisfy the
same .to_prompt_text() interface as JoinWarning / AmbiguityWarning.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection
    from aughor.sql.guard_run import GuardRun

# Overlap below this fraction → warn.  Chosen conservatively so a lightly
# populated child table (e.g. a fresh orders table for today only) doesn't
# fire a false positive.  The warn-not-block design lets the query run.
_THRESHOLD = 0.15

# Rows sampled from each side.  Large enough to detect systematic mismatches;
# small enough that DuckDB resolves the probe in < 100 ms even on cold data.
_SAMPLE_A = 100   # from the join's LHS (the "many" / FK side)
_SAMPLE_B = 1000  # from the join's RHS (the referenced / PK side)

# Every join a statement makes is probed, two statements per join (the user's call, 2026-09-29: of ~2,050
# joined statements on theLook, 2 had five or more joins, and a cap of 4 left their fifth unchecked and unsaid).


def _sample_from(conn: "DatabaseConnection", table: str, cols: str, n: int) -> str:
    """The FROM of an ``n``-row sample of ``table``, reading ``cols``.

    DuckDB draws it at random (`USING SAMPLE … ROWS`). No other engine takes that spelling: sqlglot renders it
    as a RESERVOIR table sample, which Postgres, BigQuery, Snowflake and Exasol refuse, and MySQL has no table
    sample at all. So everywhere else the sample is the first ``n`` rows of the columns the probe reads — a
    biased sample still answers "are these values in that column", where the refused probe answered nothing and
    the join was allowed to proceed (GM-1). Only the columns read, never ``*``: BigQuery bills every column a
    statement names, whatever its LIMIT."""
    if getattr(conn, "dialect", "duckdb") == "duckdb":
        return f"{table} USING SAMPLE {n} ROWS"
    return f"(SELECT {cols} FROM {table} LIMIT {n}) AS _sample"


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


def _readable(dialect: str | None) -> str | None:
    """``dialect`` when sqlglot can read and write it, else None — the neutral reading."""
    if not dialect:
        return None
    try:
        from sqlglot.dialects.dialect import Dialect
        Dialect.get_or_raise(dialect)
        return dialect
    except Exception:
        return None


def _parse(sql: str, dialect: str | None = None):
    """``sql`` parsed the way its engine reads it, else in sqlglot's neutral reading; None when neither can.

    The guards read every statement neutrally, and the neutral reading refuses the spelling BigQuery's
    model and cards write — `` `bigquery-public-data.thelook_ecommerce.orders` `` — so on theLook the join
    and filter guards ran nothing and, until GM-4, reported clean. The engine's own dialect reads it."""
    import sqlglot
    for read in dict.fromkeys((dialect or None, None)):
        try:
            tree = sqlglot.parse_one(sql, read=read, error_level=sqlglot.ErrorLevel.RAISE)
        except Exception:
            continue
        if tree is not None:
            return tree
    return None


def _table_name(tbl) -> str:
    """Every part of a table's name the statement gives — project, dataset, table. The probe reads this
    table, and a name cut to its last two parts resolves against the connection's own project: on theLook,
    `thelook_ecommerce.orders` without `bigquery-public-data` is a 404, and the join went unchecked."""
    return ".".join(part for part in (tbl.catalog, tbl.db, tbl.name) if part)


@dataclass(frozen=True)
class _Side:
    """One side of a join's equality: what the statement writes, and where its values are read from.

    ``source`` is the node the side's qualifier names — a stored table, a CTE the statement defines, or a
    subquery — and ``stored`` is that table's full name when it is one the warehouse has (a CTE's is not)."""
    alias: str        # the qualifier the side's columns carry, lowercased
    expr: Any         # the side as written: a column, or an expression over one qualifier's columns
    source: Any
    stored: str
    dialect: str      # the statement's own

    @property
    def plain(self) -> bool:
        """A stored table's column as written — what the platform's own probe (`_probe_overlap`) reads."""
        import sqlglot.expressions as exp
        return bool(self.stored) and isinstance(self.expr, exp.Column)

    @property
    def table(self) -> str:
        """The side's table as a reader names it: the stored table, the CTE, or the subquery's alias."""
        import sqlglot.expressions as exp
        if self.stored:
            return self.stored
        return self.source.name if isinstance(self.source, exp.Table) else self.alias

    @property
    def column(self) -> str:
        """The side's column, or the expression as the statement writes it."""
        import sqlglot.expressions as exp
        return self.expr.name if isinstance(self.expr, exp.Column) else self.expr.sql(dialect=self.dialect)


def _same_source(a: _Side, b: _Side) -> bool:
    """Both sides read one stored table, or one CTE — a self-join."""
    import sqlglot.expressions as exp
    if a.stored or b.stored:
        return a.stored == b.stored
    return (isinstance(a.source, exp.Table) and isinstance(b.source, exp.Table)
            and a.source.name.lower() == b.source.name.lower())


def _scope_sources(select) -> dict:
    """The row sources ``select`` itself reads — its FROM and JOINs, not deeper — by the names its
    columns may qualify them with."""
    import sqlglot.expressions as exp
    nodes = []
    from_ = select.args.get("from_") or select.args.get("from")
    if from_ is not None:
        nodes.append(from_.this)
    nodes += [j.this for j in select.args.get("joins") or []]
    out: dict = {}
    for n in nodes:
        if isinstance(n, (exp.Table, exp.Subquery)):
            out.setdefault((n.alias_or_name or "").lower(), n)
            if isinstance(n, exp.Table) and n.name:
                out.setdefault(n.name.lower(), n)
    return out


def _stored_origin(tree, source, column: str, depth: int = 0) -> "tuple[str, str] | None":
    """The stored ``(table, column)`` that ``column`` of ``source`` reads, followed through the
    statement's CTEs and subqueries — None when the column is computed, or the trail is lost
    (a UNION, a qualifier it cannot place, a source it cannot see)."""
    import sqlglot.expressions as exp
    if source is None or depth > 8:
        return None
    if isinstance(source, exp.Table):
        cte = None
        if not source.db and not source.catalog:
            name = (source.name or "").lower()
            cte = next((c for c in tree.find_all(exp.CTE) if c.alias_or_name.lower() == name), None)
        if cte is None:
            return _table_name(source).lower(), column.lower()
        select = cte.this
    elif isinstance(source, exp.Subquery):
        select = source.this
    else:
        return None
    if not isinstance(select, exp.Select):
        return None
    proj = next((e for e in select.expressions
                 if isinstance(e, exp.Star) or (e.alias_or_name or "").lower() == column.lower()), None)
    inner = proj.this if isinstance(proj, exp.Alias) else proj
    sources = _scope_sources(select)
    if isinstance(inner, exp.Star):
        return (_stored_origin(tree, next(iter(sources.values())), column, depth + 1)
                if len(sources) == 1 else None)
    if not isinstance(inner, exp.Column):
        return None
    qual = (inner.table or "").lower()
    src = sources.get(qual) if qual else (next(iter(sources.values())) if len(sources) == 1 else None)
    return _stored_origin(tree, src, inner.name, depth + 1)


def _one_domain(tree, a: "_Side", b: "_Side") -> bool:
    """Both keys are views of ONE stored column — `monthly_cohorts.user_id` and
    `repeat_orders.user_id`, each read from `orders.user_id` through the statement's CTEs.
    Their values come from one domain by construction, so a low overlap is what the
    statement's filters select, never a mismatch: on theLook's repeat-rate query (2026-10-01)
    the 2025 cohorts and the repeaters shared 13% of values — the repeat rate itself — and the
    guard called the join unreliable."""
    import sqlglot.expressions as exp
    if not (isinstance(a.expr, exp.Column) and isinstance(b.expr, exp.Column)):
        return False
    origin_a = _stored_origin(tree, a.source, a.expr.name)
    return origin_a is not None and origin_a == _stored_origin(tree, b.source, b.expr.name)


def _join_sides(tree, dialect: str | None) -> "tuple[list[tuple[_Side, _Side]], list[str]]":
    """Each equality a JOIN … ON makes between two row sources, as a pair of sides, each pair once — and, for
    each equality the guard cannot attribute to one source per side, why (an unqualified column, a side mixing
    two sources, a qualifier naming no table, CTE or subquery the statement defines, e.g. an UNNEST).

    A comparison with a literal is a filter written in ON, not a key, and is skipped; so is an equality between
    two columns of one row source, and a self-join — both sides reading one stored table or one CTE, whatever the
    expressions. A self-join compares a key with itself: one domain on both sides, and a lagged one (`prev.period
    = DATE_SUB(curr.period, INTERVAL 12 MONTH)`, the year-over-year shape) overlaps only partly BY DESIGN — probed,
    theLook's own YoY statement read as a 14% "different entities" mismatch."""
    import sqlglot.expressions as exp
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    by_alias: dict = {}
    by_name: dict = {}
    for tbl in tree.find_all(exp.Table):
        full = _table_name(tbl)
        is_cte = not tbl.db and not tbl.catalog and (tbl.name or "").lower() in ctes
        entry = (tbl, "" if is_cte else full)
        if tbl.alias:
            by_alias.setdefault(tbl.alias.lower(), entry)
        for key in (tbl.name, full):
            if key:
                by_name.setdefault(key.lower(), entry)
    for sq in tree.find_all(exp.Subquery):
        if sq.alias:
            by_alias.setdefault(sq.alias.lower(), (sq, ""))

    def side(node) -> "tuple[_Side | None, str]":
        cols = list(node.find_all(exp.Column))
        if not cols:
            return None, ""
        written = node.sql(dialect=dialect)
        quals = {(c.table or "").lower() for c in cols}
        if "" in quals:
            return None, f"{written} names a column without its table"
        if len(quals) > 1:
            return None, f"{written} mixes the columns of {len(quals)} tables"
        alias = quals.pop()
        found = by_alias.get(alias) or by_name.get(alias)
        if found is None:
            return None, f"{written}: '{alias}' is not a table, CTE or subquery the guard can read"
        return _Side(alias, node, found[0], found[1], dialect or ""), ""

    pairs: dict = {}
    unreadable: list[str] = []
    for join in tree.find_all(exp.Join):
        on = join.args.get("on")
        if on is None:
            continue
        for eq in on.find_all(exp.EQ):
            a, why_a = side(eq.left)
            b, why_b = side(eq.right)
            if a is None or b is None:
                if why_a or why_b:
                    unreadable.append(why_a or why_b)
                continue
            if a.alias == b.alias or _same_source(a, b):
                continue
            pairs.setdefault((a.alias, a.expr.sql(), b.alias, b.expr.sql()), (a, b))
    return list(pairs.values()), list(dict.fromkeys(unreadable))


def _extract_join_conditions(sql: str, dialect: str | None = None) -> list[tuple[str, str, str, str]]:
    """Return (table_a, col_a, table_b, col_b) for each explicit JOIN … ON equality between two columns, each
    pair once — a CTE's or a subquery's column named by the CTE or the alias. ``dialect`` is the statement's:
    it is read the way its engine reads it (`_parse`). Empty when it cannot be read."""
    try:
        tree = _parse(sql, dialect)
        if tree is None:
            raise ValueError("the statement parses in neither its engine's dialect nor the neutral reading")
        import sqlglot.expressions as exp
        pairs, _ = _join_sides(tree, dialect)
        return [(a.table, a.column, b.table, b.column) for a, b in pairs
                if isinstance(a.expr, exp.Column) and isinstance(b.expr, exp.Column)]
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
    why: list[str] | None = None,
) -> float | None:
    """Fraction of sampled values from table_a.col_a found in table_b.col_b.

    Returns None on any failure (fail-open), and then appends the reason to ``why`` when one is passed: an error
    is a probe that could not run, where an empty sample is one that had nothing to compare (GM-4).
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
    FROM {_sample_from(conn, ta, qa, _SAMPLE_A)}
)
SELECT
    (SELECT COUNT(*) FROM s_a) AS total,
    (SELECT COUNT(*) FROM s_a WHERE v IN (SELECT CAST({qb} AS VARCHAR) FROM {tb})) AS matched
""".strip()

        result = conn.execute("__domain_probe__", probe_sql, sql_dialect="duckdb", internal=True)
        if result is not None and getattr(result, "error", None) and why is not None:
            from aughor.sql.guard_run import why as _why
            why.append(f"the probe of {table_a}.{col_a} failed: {_why(result.error)}")
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
        if why is not None:
            from aughor.sql.guard_run import why as _why
            why.append(f"the probe of {table_a}.{col_a} failed: {_why(exc)}")
    return None


#: The name the derived probe gives its sample of side A — chosen so no statement's own CTE shares it.
_SIDE_CTE = "_aughor_side_a"


def _derived_probe_sql(tree, a: _Side, b: _Side) -> str:
    """The containment probe for a side the statement itself defines — a CTE, a subquery, an expression — in
    the statement's own dialect: a sample of side A's values (the first `_SAMPLE_A` rows of the columns it
    reads), each checked against every value of side B, with the statement's CTEs carried in so either side
    can name one. Each side keeps the statement's qualifier, so its expression reads exactly as written."""
    import sqlglot.expressions as exp
    text = exp.DataType.build("text")

    def from_(side: _Side):
        src = side.source.copy()
        if not isinstance(src, exp.Subquery):
            src.set("alias", exp.TableAlias(this=exp.to_identifier(side.alias)))
        return src

    read_a = list({c.name: exp.column(c.name, table=a.alias) for c in a.expr.find_all(exp.Column)}.values())
    sample_a = exp.select(*read_a).from_(from_(a)).limit(_SAMPLE_A)
    side_a = (exp.select(exp.alias_(exp.cast(a.expr.copy(), text), "v")).distinct()
              .from_(sample_a.subquery(a.alias)))
    values_b = exp.select(exp.cast(b.expr.copy(), text)).from_(from_(b))
    total = exp.select(exp.Count(this=exp.Star())).from_(_SIDE_CTE).where(exp.column("v").is_(exp.null()).not_())
    matched = (exp.select(exp.Count(this=exp.Star())).from_(_SIDE_CTE)
               .where(exp.and_(exp.column("v").is_(exp.null()).not_(), exp.column("v").isin(query=values_b))))
    probe = exp.select(exp.alias_(total.subquery(), "total"), exp.alias_(matched.subquery(), "matched"))
    carried = {}
    for cte in tree.find_all(exp.CTE):
        carried.setdefault(cte.alias_or_name.lower(), cte)
    for cte in carried.values():
        probe = probe.with_(cte.alias_or_name, as_=cte.this.copy())
    probe = probe.with_(_SIDE_CTE, as_=side_a)
    # sqlglot keeps a statement's WITH under "with_" (30.x); "with" was the key before it.
    with_ = tree.args.get("with_") or tree.args.get("with")
    if with_ is not None and with_.args.get("recursive"):
        (probe.args.get("with_") or probe.args.get("with")).set("recursive", True)
    return probe.sql(dialect=a.dialect or None)


def _probe_overlap_derived(conn: "DatabaseConnection", tree, a: _Side, b: _Side,
                           why: list[str]) -> float | None:
    """Containment of side ``a``'s sampled values in side ``b``'s, when either side is one the statement defines.

    Its fragments are the author's own SQL, so the probe is written in the statement's dialect and declares
    nothing: declaring DuckDB would translate a native fragment and corrupt it (GM-1 measured `DATE_TRUNC(x,
    MONTH)` with its arguments swapped). A CTE is recomputed by each probe — two per join, the cost the user chose
    over leaving these joins unchecked (2026-09-29). None on failure, with the reason appended to ``why``."""
    from aughor.sql.guard_run import why as _why
    try:
        result = conn.execute("__domain_probe__", _derived_probe_sql(tree, a, b), internal=True)
    except Exception as exc:
        why.append(f"the probe of {a.table}.{a.column} failed: {_why(exc)}")
        return None
    if result is not None and getattr(result, "error", None):
        why.append(f"the probe of {a.table}.{a.column} failed: {_why(result.error)}")
        return None
    try:
        total, matched = int(result.rows[0][0]), int(result.rows[0][1])
    except Exception:
        return None
    return matched / total if total > 0 else None


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
        result = conn.execute("__hll_overlap_probe__", sql, sql_dialect="duckdb", internal=True)
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
    expr_a: str     # expression to normalize side A's key, in the engine's spelling
    expr_b: str     # ... and side B's key
    overlap: float  # reconciled overlap under the transform


def _probe_overlap_expr(conn, table_a: str, expr_a: str, table_b: str, expr_b: str, *,
                        col_a: str) -> float | None:
    """Containment of transformed A-values in transformed B-values (empty/NULL results ignored).
    ``col_a`` is the column ``expr_a`` transforms, the one the A-side sample reads.

    Returns None on any failure (fail-open)."""
    try:
        ta, tb = _quote_table(table_a), _quote_table(table_b)
        probe_sql = f"""
WITH s_a AS (
    SELECT DISTINCT {expr_a} AS v FROM {_sample_from(conn, ta, f'"{col_a}"', _SAMPLE_A)}
)
SELECT
    (SELECT COUNT(*) FROM s_a WHERE v IS NOT NULL AND v <> '') AS total,
    (SELECT COUNT(*) FROM s_a
        WHERE v IS NOT NULL AND v <> '' AND v IN (SELECT {expr_b} FROM {tb})) AS matched
""".strip()
        result = conn.execute("__reconcile_probe__", probe_sql, sql_dialect="duckdb", internal=True)
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


def _in_engine_spelling(expr: str, dialect: str | None) -> str:
    """A DuckDB expression as the engine spells it. A reconciliation is probed in DuckDB's spelling, which
    the door translates, but its expressions are handed to a model writing for the engine and to a reader:
    `CAST(x AS VARCHAR)` and `regexp_replace(…, 'g')` are refused by BigQuery, so they are said as BigQuery
    writes them. Falls back to the DuckDB spelling when the expression cannot be rendered."""
    if not dialect or dialect == "duckdb":
        return expr
    try:
        import sqlglot
        return sqlglot.transpile(expr, read="duckdb", write=dialect)[0]
    except Exception:
        return expr


def reconcile_join_keys(
    conn, table_a: str, col_a: str, table_b: str, col_b: str, raw_overlap: float, *,
    dialect: str | None = None,
) -> KeyReconciliation | None:
    """Try deterministic normalizations to reconcile two low-overlap join keys.

    Returns the first transform that materially lifts overlap (direction-aware, like the raw
    probe), or None if the keys are genuinely disjoint. Fail-open throughout. The returned
    expressions are in ``dialect``'s spelling (the engine's), DuckDB's when none is given."""
    for name, label, tmpl in _KEY_TRANSFORMS:
        ea = tmpl.format(col=f'"{col_a}"')
        eb = tmpl.format(col=f'"{col_b}"')
        ov_ab = _probe_overlap_expr(conn, table_a, ea, table_b, eb, col_a=col_a)
        ov_ba = _probe_overlap_expr(conn, table_b, eb, table_a, ea, col_a=col_b)
        ovs = [o for o in (ov_ab, ov_ba) if o is not None]
        if not ovs:
            continue
        ov = max(ovs)
        if ov >= _RECONCILE_MIN_OVERLAP and ov - raw_overlap >= _RECONCILE_MIN_GAIN:
            return KeyReconciliation(name, label, _in_engine_spelling(ea, dialect),
                                     _in_engine_spelling(eb, dialect), ov)
    return None


_IDENTIFIER = re.compile(r"^\w+$")


def _side_label(table: str, col: str) -> str:
    """`table.column` for a column; an expression is named as written (it carries its own qualifier)."""
    return f"{table}.{col}" if table and _IDENTIFIER.match(col or "") else col


@dataclass
class JoinDomainWarning:
    table_a: str
    col_a: str
    table_b: str
    col_b: str
    overlap: float
    reconciliation: KeyReconciliation | None = None

    @property
    def label_a(self) -> str:
        """Side A as a reader names it: `table.column`, or the join expression as the statement writes it."""
        return _side_label(self.table_a, self.col_a)

    @property
    def label_b(self) -> str:
        return _side_label(self.table_b, self.col_b)

    def to_prompt_text(self) -> str:
        pct = f"{self.overlap:.0%}"
        base = (
            f"JOIN VALUE-DOMAIN MISMATCH: {self.label_a} ↔ "
            f"{self.label_b} — only {pct} of sampled values match. "
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


_JOIN_WORD = re.compile(r"\bJOIN\b", re.IGNORECASE)
_FILTER_WORD = re.compile(r"\b(WHERE|HAVING)\b", re.IGNORECASE)


def check_join_value_domains(
    conn: "DatabaseConnection",
    sql: str,
    threshold: float = _THRESHOLD,
) -> list[JoinDomainWarning]:
    """Check each explicit JOIN condition for value-domain overlap.

    Returns a (possibly empty) list of warnings.  Never raises — entirely
    fail-open so the calling query path is never blocked by the guard. An
    empty list does not say every join was checked; :func:`join_domain_check`
    does (GM-4).
    """
    return join_domain_check(conn, sql, threshold).findings


def join_domain_check(
    conn: "DatabaseConnection",
    sql: str,
    threshold: float = _THRESHOLD,
) -> "GuardRun":
    """The join value-domain guard's run over ``sql``: its warnings, and each join it could not check (GM-4) —
    a statement it could not parse, a join side it cannot attribute to one row source, or a join whose probes
    the warehouse refused both ways. Never raises.

    Every join is probed (the user's call, 2026-09-29): a join between two stored tables' columns by the
    platform's probe, and a join to a CTE or a subquery, or on an expression, by a probe that carries the
    statement's own CTEs (`_probe_overlap_derived`) — 9% and 4% of theLook's joined statements, which the
    guard used to probe against a table that does not exist, or skip."""
    from aughor.db.dialects import authored_dialect
    from aughor.sql.guard_run import GuardRun, why as _why
    run = GuardRun("join-domain")
    warnings: list[JoinDomainWarning] = run.findings
    dialect = _readable(authored_dialect(conn))
    try:
        tree = _parse(sql, dialect)
        if tree is None:
            if _JOIN_WORD.search(sql or ""):
                run.unchecked.append("the statement could not be parsed to find its join keys")
            return run
        pairs, unreadable = _join_sides(tree, dialect)
        run.unchecked.extend(unreadable)
        for a, b in pairs:
            if not (a.plain and b.plain):
                if _one_domain(tree, a, b):
                    from aughor.stats import bump
                    bump("guard.join_domain.one_domain")
                    continue
                failed: list[str] = []
                overlaps = [o for o in (_probe_overlap_derived(conn, tree, a, b, failed),
                                        _probe_overlap_derived(conn, tree, b, a, failed)) if o is not None]
                if not overlaps and failed:
                    run.unchecked.append(f"{_side_label(a.table, a.column)} ↔ {_side_label(b.table, b.column)}: "
                                         f"{failed[0]}")
                elif overlaps and max(overlaps) < threshold:
                    warnings.append(JoinDomainWarning(a.table, a.column, b.table, b.column, max(overlaps)))
                continue
            t_a, c_a, t_b, c_b = a.stored, a.column, b.stored, b.column
            # Direction-aware containment: a real FK is contained in ONE direction
            # (child ⊆ parent), even when the parent has many keys the child lacks. The
            # single-direction check false-flagged a legitimate parent⋈child subset join
            # (orders ⋈ refunds: only ~10% of orders are refunded, so orders→refunds reads
            # 10%, but refunds→orders is ~100%). Probe BOTH ways and take the MAX — a truly
            # fabricated join (different entities, e.g. touchpoint_type = channel) is low
            # BOTH ways and still flags; a subset FK is high one way and passes.
            failed: list[str] = []
            ov_ab = _probe_overlap(conn, t_a, c_a, t_b, c_b, failed)
            ov_ba = _probe_overlap(conn, t_b, c_b, t_a, c_a, failed)
            overlaps = [o for o in (ov_ab, ov_ba) if o is not None]
            if not overlaps and failed:
                run.unchecked.append(f"{t_a}.{c_a} ↔ {t_b}.{c_b}: {failed[0]}")
                continue
            if overlaps and max(overlaps) < threshold:
                raw = max(overlaps)
                recon = None
                try:
                    recon = reconcile_join_keys(conn, t_a, c_a, t_b, c_b, raw, dialect=dialect)
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "join_guard: reconciliation skipped — mismatch still surfaced",
                             counter="join_guard.reconcile_gate_error")
                warnings.append(JoinDomainWarning(t_a, c_a, t_b, c_b, raw, reconciliation=recon))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: domain check failed — no warnings emitted",
                 counter="join_guard.check_error")
        run.unchecked.append(f"the check failed: {_why(exc)}")
    if run.unchecked:
        from aughor.stats import bump
        bump("guard.join_domain.unchecked", len(run.unchecked))
    if warnings:
        from aughor.stats import bump
        bump("guard.join_domain.fired", len(warnings))
        reconciled = sum(1 for w in warnings if w.reconciliation is not None)
        if reconciled:
            bump("guard.join_domain.reconciled", reconciled)
    return run


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
    # The edge was verified upstream (an explorer FK check) even though no containment
    # fraction reached us. Kept SEPARATE from `overlap` because the two answer different
    # questions — "was this checked?" and "by how much do the values overlap?" — and
    # folding the first into the second is what produced a fabricated 1.0 (see
    # seed_verified_cache) and then, over-correcting, a lost verification.
    verified_upstream: bool = False


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
            if fk_d > 0:
                ov = max(0, fk_d - orphans) / fk_d
            elif rec.get("verified"):
                # Verified upstream but WITHOUT the counts that would make it a
                # measurement. `1.0` here read downstream as "100% of key values
                # overlap" — a probe result the record does not contain. `-1.0` is the
                # established "couldn't probe" sentinel; the verification itself travels
                # on `verified_upstream` so the ontology can still stamp the edge
                # `verified` without anyone inventing a number for it.
                ov = -1.0
            else:
                ov = 0.0
            vj = VerifiedJoin(t1, c1, t2, c2, overlap=ov, match=j.get("match", "exact"),
                              verified_upstream=bool(rec.get("verified")))
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
    DO-NOT-JOIN list for the name-shape coincidences that hold disjoint values.

    Accepted joins carry their MEASURED overlap (Wave P2). They used to render as a bare
    ``✓`` while only rejections showed a number — so the prompt stated its evidence
    exactly when refusing and withheld it when asserting, which is the asymmetry
    backwards: a join asserted at 62% overlap and one asserted at 100% are different
    claims, and the model could not tell them apart. An unprobed edge says ``not probed``
    rather than borrowing the confidence of the ones that were.
    """
    lines: list = []
    if verified:
        lines.append("FOREIGN KEY JOINS (value-verified — use these exact keys to join the tables above):")
        for v in verified:
            warrant = f"{v.overlap:.0%} value overlap" if v.overlap >= 0 else "not probed"
            # DE-3c: a key the engine itself declares says so beside its measurement.
            declared = "; declared foreign key" if v.match == "declared" else ""
            lines.append(f"  {'✓' if v.overlap >= 0 else '·'} {v.t1}.{v.c1} = {v.t2}.{v.c2}  ({warrant}{declared})")
    if rejected:
        lines.append("")
        lines.append("DO NOT JOIN (these column pairs share a name but hold DISJOINT values — "
                     "joining them fabricates rows):")
        for r in rejected:
            if r.match == "declared":
                # DE-3c: the schema declares the key and the data does not bear it out. Said as
                # both — a reader who sees only "do not join" would never learn the declaration
                # exists, and one who sees only the declaration would join into missing rows.
                lines.append(f"  ⚠ {r.t1}.{r.c1} = {r.t2}.{r.c2}  (DECLARED foreign key, but only "
                             f"{r.overlap:.0%} value overlap — the declaration and the data disagree)")
                continue
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
    #: CA-2 — the literal is a real stored value, but of ANOTHER column of the same table
    #: (`CHANNEL_LVL_0 = 'Direkteingabe'` when 'Direkteingabe' lives only in CHANNEL_LVL_1).
    #: The repair moves the predicate to that column; the literal itself is kept.
    column_suggestion: str | None = None
    #: CA-2 — the literal is in NO text column of the table at all: the predicate can only ever
    #: match zero rows, and the honest report says the segment is absent, never invents one.
    novel: bool = False

    def caveat(self) -> str:
        """What a reader is told when the statement that ran still carries this finding. The novel wording's
        tail ("the segment is absent, not zero") is what the battery keys on to keep that caveat after a repair."""
        if self.column_suggestion:
            return (f"filter guard: '{self.bad_value}' is not a value of {self.table}.{self.col} but is a "
                    f"value of {self.table}.{self.column_suggestion} — the predicate as written matches no row")
        if self.novel:
            return (f"filter guard: '{self.bad_value}' is not a stored value of {self.table}.{self.col} or of "
                    f"any other text column in {self.table} — the predicate matches no row; the segment is "
                    f"absent, not zero")
        sugg = f" (did you mean '{self.suggestion}'?)" if self.suggestion else ""
        return (f"filter guard: '{self.bad_value}' is not a stored value of {self.table}.{self.col}{sugg} — "
                f"the predicate is a silent no-op")

    def to_prompt_text(self) -> str:
        vals = ", ".join(repr(v) for v in self.valid_values[:12])
        sugg = f" Did you mean '{self.suggestion}'?" if self.suggestion else ""
        if self.column_suggestion:
            return (
                f"FILTER COLUMN MISMATCH: {self.table}.{self.col} {self.op} '{self.bad_value}' "
                f"matches NO rows — '{self.bad_value}' is not a value of {self.col} (its values "
                f"are: {vals}) but IS a stored value of {self.table}.{self.column_suggestion}. "
                f"Filter {self.column_suggestion} instead; keep the literal exactly as written."
            )
        if self.novel:
            return (
                f"FILTER VALUE ABSENT: {self.table}.{self.col} {self.op} '{self.bad_value}' "
                f"matches NO rows — '{self.bad_value}' is not a stored value of {self.col} "
                f"(values: {vals}) nor of any other text column in {self.table}. Do not invent "
                f"a substitute: if no exact value fits the question, keep the query honest and "
                f"let the result say the segment is absent."
            )
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


def _extract_filter_literals(sql: str, *, dialects: tuple = (None,),
                             numbers: bool = False) -> list[tuple[str, str, str, str]]:
    """(table, col, literal, op) for `col = 'lit'` / `col != 'lit'` / `col [NOT] IN (…)`
    predicates that are NOT inside a JOIN … ON (those are the join guard's job). `op` is one
    of '=', '!=', 'IN', 'NOT IN'. Unqualified columns resolve only when the query has exactly
    one base table — otherwise the column is ambiguous and skipped (fail-safe).

    Negated predicates (`!=` / `NOT IN`) matter as much as positive ones: a misspelled
    EXCLUDED literal is a silent no-op (`status != 'cancelled'` keeps every row when the data
    holds 'canceled'), the Q29 'zero cancellations despite 15,737' scar.

    ``dialects`` are tried in order until one parses (the default, the neutral reading, is what
    the guards have always used); ``numbers`` admits numeric literals too — an integer KEY
    (`user_id = 12345`), which a guard about text values never needs and an object page must
    read (PENDING item 25: on theLook, BigQuery with integer ids, no finding ever cited one
    object)."""
    out: list[tuple[str, str, str, str]] = []
    import sqlglot
    import sqlglot.expressions as exp
    tree = None
    for dialect in dialects:
        try:
            tree = sqlglot.parse_one(sql, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
            break
        except Exception:
            continue
    if tree is None:
        return out

    def _value(node) -> bool:
        return isinstance(node, exp.Literal) and (node.is_string or (numbers and node.is_number))
    alias_map: dict[str, str] = {}
    base_tables: list[str] = []
    for tbl in tree.find_all(exp.Table):
        real = _table_name(tbl)
        alias = tbl.alias or real
        if alias:
            alias_map[alias.lower()] = real
        if not tbl.alias and tbl.name:
            alias_map.setdefault(tbl.name.lower(), real)
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
        if isinstance(node.left, exp.Column) and _value(node.right):
            col, lit = node.left, node.right
        elif isinstance(node.right, exp.Column) and _value(node.left):
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
                    if _value(e):
                        out.append((t, col.name, e.this, op))
    return out


#: The placeholder a filter probe's body reads, replaced by the source the probe runs against.
_SRC_TOKEN = "{src}"
_SRC_NAME = "_aughor_src"


@dataclass(frozen=True)
class _Source:
    """Where a filtered column's values are read: a stored table (``node`` None), or a CTE or a subquery the
    statement defines (``node`` is it; ``tree`` is the statement, whose CTEs every probe of it carries)."""
    name: str
    node: Any = None
    tree: Any = None
    dialect: str = ""


def _source(src: "_Source | str") -> _Source:
    return src if isinstance(src, _Source) else _Source(str(src))


def _defined_sources(tree, dialect: str) -> dict:
    """The CTEs and subqueries ``tree`` defines, by lowercased name or alias."""
    import sqlglot.expressions as exp
    out: dict = {}
    for cte in tree.find_all(exp.CTE):
        out.setdefault(cte.alias_or_name.lower(), _Source(cte.alias_or_name, cte, tree, dialect))
    for sq in tree.find_all(exp.Subquery):
        if sq.alias:
            out.setdefault(sq.alias.lower(), _Source(sq.alias, sq, tree, dialect))
    return out


def _probe(conn: "DatabaseConnection", label: str, src: "_Source | str", body: str):
    """Run ``body`` — platform SQL in DuckDB's spelling that reads the table ``{src}`` — against ``src``.

    A stored table is quoted into the body, which is declared DuckDB and translated by the door. A CTE or a
    subquery the statement defines is the author's own SQL, so the body is parsed as DuckDB, ``{src}`` is replaced
    by that source, the statement's CTEs are carried in, and the whole is rendered in the statement's dialect and
    declared nothing: declaring DuckDB would translate the native fragment and corrupt it (GM-1). On theLook 51 of
    the 251 statements that filter on a text value filter a CTE's or a subquery's column, and each probe read a
    table that does not exist (GM-4)."""
    src = _source(src)
    if src.node is None:
        return conn.execute(label, body.replace(_SRC_TOKEN, _quote_table(src.name)), sql_dialect="duckdb", internal=True)
    import sqlglot
    import sqlglot.expressions as exp
    probe = sqlglot.parse_one(body.replace(_SRC_TOKEN, _SRC_NAME), read="duckdb")
    for placeholder in list(probe.find_all(exp.Table)):
        if placeholder.name == _SRC_NAME:
            placeholder.replace(src.node.copy() if isinstance(src.node, exp.Subquery)
                                else exp.Table(this=exp.to_identifier(src.name)))
    carried: dict = {}
    for cte in src.tree.find_all(exp.CTE):
        carried.setdefault(cte.alias_or_name.lower(), cte)
    for cte in carried.values():
        probe = probe.with_(cte.alias_or_name, as_=cte.this.copy())
    return conn.execute(label, probe.sql(dialect=src.dialect or None), internal=True)


def _persisted_value_sample(conn: "DatabaseConnection", t: str, c: str) -> "list[str]":
    """The R5 persisted entity-value sample for (table, column), [] when absent.
    Read through the kernel registry seam (the agent registers the profiler's
    loader at bootstrap — no Platform→Agent import); keyed by the bare table
    name like the profiler. Read-only; never builds."""
    try:
        cid = getattr(conn, "_connection_id", "") or ""
        if not cid:
            return []
        from aughor.kernel.registries.value_samples import load_value_samples_for
        return load_value_samples_for(cid).get((t.split(".")[-1], c)) or []
    except Exception:
        return []


# Public alias (stable cross-module interface — keeps the "no cross-module private
# imports" ratchet satisfied; the R7 grounded-literal contract reads it).
def extract_filter_literals(sql: str, *, dialects: tuple = (None,),
                            numbers: bool = False) -> "list[tuple[str, str, str, str]]":
    """Public: (table, column, literal, op) for every WHERE/HAVING string-literal
    equality/IN predicate in ``sql`` (alias-resolved, ON-clause nodes excluded) — numeric ones
    too with ``numbers``, parsed in the first of ``dialects`` that reads it."""
    return _extract_filter_literals(sql, dialects=dialects, numbers=numbers)


def _highcard_bind_warnings(conn: "DatabaseConnection", t: "_Source | str", c: str,
                            litops: "set[tuple[str, str]]",
                            unchecked: "list[str] | None" = None) -> list[FilterDomainWarning]:
    """Bind a guessed literal on a HIGH-cardinality text column (names/SKUs/cities) to its nearest
    real value — but ONLY when the literal is execution-confirmed absent and a close neighbour exists
    in the column's value domain. Positive predicates only (=, IN): never weaken a negation
    by rewriting it. CHESS-style: trigram-blocked value index over a distinct sample.

    Sample source (R5 deferred, closed): the PERSISTED entity-value sample from the
    profiler is consulted first — an offline bind costs zero warehouse scans. Only
    when it is absent or yields no neighbour does the live bounded SELECT DISTINCT
    run (staleness-safe: a value newer than the last profile still binds).

    A probe the warehouse refused is not a value's absence (GM-4): an existence probe that errored read as
    "absent" and bound a literal that may be right to its nearest neighbour. The reason goes to ``unchecked``
    and that literal is left as written."""
    from aughor.sql.guard_run import why as _why
    from aughor.sql.value_index import ValueIndex
    out: list[FilterDomainWarning] = []
    positives = [(lit, op) for lit, op in litops if op in ("=", "IN")]
    if not positives:
        return out
    src = _source(t)
    t = src.name
    qc = f'"{c}"'
    offline: "ValueIndex | None" = None
    offline_loaded = False
    index: "ValueIndex | None" = None
    for lit, op in positives:
        safe = lit.replace("'", "''")
        exists = _probe(conn, "__filter_highcard_exists__", src,
                        f"SELECT 1 FROM {{src}} WHERE LOWER(CAST({qc} AS VARCHAR)) = LOWER('{safe}') LIMIT 1")
        if exists is not None and getattr(exists, "error", None):
            if unchecked is not None:
                unchecked.append(f"whether '{lit}' is a value of {t}.{c} could not be read: {_why(exists.error)}")
            continue
        if exists and exists.rows:
            continue  # the literal is a real value — do not second-guess it
        if not offline_loaded:  # warmed profiler sample, loaded once per column
            offline_loaded = True
            sample = _persisted_value_sample(conn, t, c)
            offline = ValueIndex(sample) if sample else None
        best = offline.best_match(lit, cutoff=_HIGHCARD_CUTOFF) if offline else None
        if best is not None:
            # The sample may predate the last data refresh — a 1-row probe confirms the
            # suggestion still exists before it can drive a rewrite (never bind to a ghost).
            _bsafe = best.replace("'", "''")
            _bexists = _probe(conn, "__filter_highcard_exists__", src,
                              f"SELECT 1 FROM {{src}} WHERE LOWER(CAST({qc} AS VARCHAR)) = LOWER('{_bsafe}') LIMIT 1")
            if not (_bexists and _bexists.rows):
                best = None
        if best is None:
            if index is None:  # live fallback, built once per column, only when needed
                res = _probe(conn, "__filter_highcard_sample__", src,
                             f"SELECT DISTINCT CAST({qc} AS VARCHAR) AS v FROM {{src}} "
                             f"WHERE {qc} IS NOT NULL LIMIT {_HIGHCARD_SAMPLE}")
                sample = [r[0] for r in res.rows if r and r[0] is not None] if res and res.rows else []
                index = ValueIndex(sample)
            best = index.best_match(lit, cutoff=_HIGHCARD_CUTOFF)
        if best and best.lower() != lit.lower():
            out.append(FilterDomainWarning(t, c, lit, [best], best, op))
    return out


_SIBLING_MAX_LITERALS = 2      # novel literals per query that get a sibling-column search
_SIBLING_MAX_COLUMNS = 16      # text columns of the table probed per literal (LIMIT 1 each)
_SIBLING_TEXT_TYPES = ("varchar", "text", "string", "char", "nvarchar", "bpchar", "enum")


def _table_text_columns(conn: "DatabaseConnection", table: "_Source | str") -> "list[str] | None":
    """The text-typed columns of `table`, spelled as the schema declares them. Names come
    from a zero-row projection (declared case survives; the cached type map lowercases);
    types from the connection's cached introspection narrow to text columns when available,
    and every column is a candidate when they are not (a CAST-to-VARCHAR equality on a
    numeric column simply never matches). None when even the projection fails."""
    src = _source(table)
    table = src.name
    try:
        res = _probe(conn, "__filter_sibling_cols__", src, "SELECT * FROM {src} LIMIT 0")
    except Exception:
        return None
    if res is None or res.error or not res.columns:
        return None
    declared = list(res.columns)
    try:
        from aughor.sql.trust_checks import connection_column_types
        types = connection_column_types(getattr(conn, "_connection_id", ""), conn) or {}
    except Exception:
        types = {}
    if not types:
        return declared
    bare = table.split(".")[-1].lower()
    text_lower = {
        key.rsplit(".", 1)[1] for key, dt in types.items()
        if "." in key and key.rsplit(".", 1)[0].split(".")[-1] == bare
        and any(tt in str(dt).lower() for tt in _SIBLING_TEXT_TYPES)
    }
    narrowed = [c for c in declared if c.lower() in text_lower]
    return narrowed or declared


def _sibling_columns_holding(conn: "DatabaseConnection", table: "_Source | str", col: str,
                             lit: str) -> "tuple[list[str], bool] | None":
    """Which OTHER text columns of `table` hold `lit` as an exact stored value. Bounded
    (LIMIT 1 per column, ≤ _SIBLING_MAX_COLUMNS columns). Returns the column names as the
    schema spells them and whether every other text column was searched — an empty list after
    a search the bound cut short is not "no other column holds it" (GM-4) — or None when the
    probe could not run."""
    src = _source(table)
    cols = _table_text_columns(conn, src)
    if cols is None:
        return None
    holders: list[str] = []
    safe_lit = lit.replace("'", "''")
    others = [c for c in cols if c.lower() != col.lower()]
    for c in others[:_SIBLING_MAX_COLUMNS]:
        try:
            res = _probe(conn, "__filter_sibling_probe__", src,
                         f'SELECT 1 FROM {{src}} WHERE CAST("{c}" AS VARCHAR) = \'{safe_lit}\' LIMIT 1')
        except Exception:
            return None
        if res is None or res.error:
            return None
        if res.rows:
            holders.append(c)
    return holders, len(others) <= _SIBLING_MAX_COLUMNS


def check_filter_value_domains(conn: "DatabaseConnection", sql: str) -> list[FilterDomainWarning]:
    """Flag WHERE/HAVING equality/IN literals that don't exist in an enumerable column's
    actual value domain (a guessed enum value). Fail-open; never raises. An empty list
    does not say every filter was checked; :func:`filter_domain_check` does (GM-4)."""
    return filter_domain_check(conn, sql).findings


def filter_domain_check(conn: "DatabaseConnection", sql: str) -> "GuardRun":
    """The filter value-domain guard's run over ``sql``: its warnings, and each filter it could not check (GM-4)
    — a statement it could not parse, a column whose values the warehouse would not list, a literal whose search
    of the table's other columns failed or was cut short. Never raises.

    The statement is read in its own dialect, every filtered column is probed, and a CTE's or a subquery's
    column is read through the statement's own CTEs (`_probe`) — the choices the user made for the join guard,
    2026-09-29, which the filter guard shares."""
    import difflib
    from collections import defaultdict
    from aughor.db.dialects import authored_dialect
    from aughor.sql.guard_run import GuardRun, why as _why
    run = GuardRun("filter-domain")
    warnings: list[FilterDomainWarning] = run.findings
    sibling_budget = [_SIBLING_MAX_LITERALS]   # per-query cap on sibling-column probes
    dialect = _readable(authored_dialect(conn))
    try:
        by_col: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        tree = _parse(sql, dialect)
        literals = _extract_filter_literals(sql, dialects=tuple(dict.fromkeys((dialect, None))))
        if not literals and _FILTER_WORD.search(sql or "") and tree is None:
            run.unchecked.append("the statement could not be parsed to find its filter values")
        defined = _defined_sources(tree, dialect) if tree is not None else {}
        for t, c, lit, op in literals:
            by_col[(t, c)].add((lit, op))
        for (t, c), litops in by_col.items():
            try:
                src = defined.get(t.lower()) or _Source(t)
                qc = f'"{c}"'
                res = _probe(conn, "__filter_domain_probe__", src,
                             f"SELECT DISTINCT CAST({qc} AS VARCHAR) AS v FROM {{src}} "
                             f"WHERE {qc} IS NOT NULL LIMIT {_ENUMERABLE_MAX_DISTINCT + 1}")
                if res is not None and getattr(res, "error", None):
                    run.unchecked.append(f"the values of {t}.{c} could not be read: {_why(res.error)}")
                    continue
                if not res or not res.rows:
                    continue
                vals = [r[0] for r in res.rows if r and r[0] is not None]
                if not vals:
                    continue
                if len(vals) > _ENUMERABLE_MAX_DISTINCT:
                    # High-cardinality column: the ≤50 enumeration can't see the domain. Use a
                    # CHESS-style value index over a bounded sample, but only bind a literal that is
                    # execution-confirmed absent (so we never second-guess a real value).
                    warnings.extend(_highcard_bind_warnings(conn, src, c, litops, run.unchecked))
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
                    if close:  # an obvious typo/variant of a stored value — bind to it
                        warnings.append(FilterDomainWarning(t, c, lit, vals, close[0], op))
                        continue
                    # CA-2 — a value with NO close neighbour used to be let through as "novel"
                    # (a value this guard must not second-guess). For an ENUMERABLE column the
                    # domain above is complete, so absence is certain: the predicate matches no
                    # row. Two honest outcomes: the value lives in a sibling column of the same
                    # table (the deep path's `CHANNEL_LVL_0 = 'Direkteingabe'` when it is a
                    # CHANNEL_LVL_1 value — every query returned [] and the report invented a
                    # segment), or it lives nowhere — and then nothing may be invented.
                    # The domain above is complete, so the predicate matches no row; when which other column holds
                    # the value could not be looked up, or not everywhere, that is said, not repaired (GM-4).
                    if sibling_budget[0] <= 0:
                        run.unchecked.append(f"'{lit}' is not a stored value of {t}.{c}; the table's other columns "
                                             f"were not searched for it (the guard searches for at most "
                                             f"{_SIBLING_MAX_LITERALS} such values per statement)")
                        continue
                    sibling_budget[0] -= 1
                    searched = _sibling_columns_holding(conn, src, c, lit)
                    if searched is None:
                        run.unchecked.append(f"'{lit}' is not a stored value of {t}.{c}, and the table's other "
                                             "columns could not be searched for it")
                        continue
                    holders, everywhere = searched
                    if len(holders) == 1:
                        warnings.append(FilterDomainWarning(t, c, lit, vals, None, op,
                                                            column_suggestion=holders[0]))
                    elif not holders and everywhere:
                        warnings.append(FilterDomainWarning(t, c, lit, vals, None, op, novel=True))
                    elif not holders:
                        run.unchecked.append(f"'{lit}' is not a stored value of {t}.{c}; only "
                                             f"{_SIBLING_MAX_COLUMNS} of the table's other text columns were "
                                             "searched for it")
                    # 2+ holders: ambiguous — no repair, no warning (fail-open)
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "filter_guard: value-domain probe failed — query allowed to proceed",
                         counter="filter_guard.probe_error")
                run.unchecked.append(f"the values of {t}.{c} could not be read: {_why(exc)}")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "filter_guard: check failed — no warnings emitted",
                 counter="filter_guard.check_error")
        run.unchecked.append(f"the check failed: {_why(exc)}")
    if run.unchecked:
        from aughor.stats import bump
        bump("guard.filter_domain.unchecked", len(run.unchecked))
    return run


def filter_repair_holds(before: "GuardRun", after: "GuardRun") -> bool:
    """Whether the filter guard's run over a REPAIRED statement (``after``) confirms the repair, against its run
    over the statement that ran (``before``): no finding a repair should have removed, and nothing unchecked that was
    checked before (`GuardRun.cleared`).

    A novel literal — a value in no text column of its table — is an honest absence, never a repair target (a
    model "fix" that drops the predicate answers a different question), so a repair may keep one that was there
    before; one it introduces is a new silent zero and refuses it. Every other finding refuses it: the quick path
    adopted a model's repair that re-wrote `country = 'Brasil'` back to 'Brazil' and shipped 0 where the answer is
    4,458 (theLook, 2026-09-29)."""
    from aughor.sql.guard_run import GuardRun
    kept = {(w.table, w.col, w.bad_value) for w in before.findings if getattr(w, "novel", False)}
    remaining = [w for w in after.findings
                 if not (getattr(w, "novel", False) and (w.table, w.col, w.bad_value) in kept)]
    return GuardRun(after.guard, remaining, list(after.unchecked)).cleared(before)


def repair_filter_literals(sql: str, warnings: list["FilterDomainWarning"],
                           dialect: str = "duckdb") -> "str | None":
    """Deterministically rewrite each guessed filter literal to its confirmed stored value.

    Given probe-confirmed warnings (a literal that matches no row but has a close neighbour in the
    column's actual domain), replace ONLY the literal in the comparison on that exact (table, column)
    — never other identical strings elsewhere. Returns the rewritten SQL, or None if nothing changed.
    Pure AST surgery; the caller dry-runs the result before adopting, so a bad rewrite is never used."""
    import sqlglot
    import sqlglot.expressions as exp

    # Keyed by BARE table name: the warnings carry the qualified name (`traffic.t`) while
    # `_resolve` below reads sqlglot's `Table.name`, which is bare — the schema lives in
    # `.db`. Keying both sides on the bare name is what grounded_literals.py already relies
    # on ("repair_filter_literals resolves BARE table names"); a value fix for a qualified
    # table silently never matched (CA-2 receipt: the CHANNEL_LVL_0 swap detected and not
    # rewritten until this normalization).
    def _bare_tbl(name: str) -> str:
        return (name or "").split(".")[-1].lower()

    fixes = {(_bare_tbl(w.table), w.col.lower(), w.bad_value): w.suggestion
             for w in warnings if w.suggestion}
    # CA-2 — column swaps: the literal stays, the predicate moves to the column that holds it.
    col_fixes = {(_bare_tbl(w.table), w.col.lower(), w.bad_value): w.column_suggestion
                 for w in warnings if w.column_suggestion and not w.suggestion}
    if not fixes and not col_fixes:
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
        sugg = fixes.get((_bare_tbl(t), col.name.lower(), lit.this))
        if sugg is not None:
            lit.set("this", sugg)
            changed = True
            continue
        new_col = col_fixes.get((_bare_tbl(t), col.name.lower(), lit.this))
        if new_col:
            col.set("this", exp.to_identifier(new_col, quoted=True))
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


# ── Join-coverage (sum-preservation) guard ─────────────────────────────────────
# The guard battery above detects over-count (fan-out) and disjoint keys — never
# UNDER-count. An INNER JOIN that drops base rows without a match silently deflates
# every total (live incident: a franchise×supplier query captured half the network's
# revenue because franchises without supplier rows vanished), and the finding shipped
# at High confidence. This probe compares the joined SUM against the same SUM over
# the base fact table alone and returns a caveat when coverage is materially short.

import re

_COVERAGE_SUM_RE = re.compile(
    r"SUM\s*\(\s*(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)\s*\)", re.IGNORECASE)
_COVERAGE_FROM_RE = re.compile(
    r"\bFROM\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
_COVERAGE_WHERE_OK_RE = re.compile(
    r"\bWHERE\s+(?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*\s+IS\s+NOT\s+NULL\s*(?:GROUP|ORDER|LIMIT|$)",
    re.IGNORECASE)

COVERAGE_THRESHOLD = 0.90  # joined total below 90% of base → material row loss


def check_join_coverage(conn, sql: str) -> "str | None":
    """Caveat string when an INNER-JOINed SUM covers materially less than the base table.

    Deliberately conservative (fail-open, two cheap probes, no LLM): fires only for a
    query with a JOIN and a plain SUM(column), whose WHERE clause (if any) is a bare
    IS NOT NULL — a genuine filter legitimately shrinks the total and must not be
    mistaken for join loss."""
    try:
        if not sql or not re.search(r"\bJOIN\b", sql, re.IGNORECASE):
            return None
        if re.search(r"\b(LEFT|RIGHT|FULL|OUTER)\s+JOIN\b", sql, re.IGNORECASE):
            return None  # outer joins preserve the base side by construction
        if " WHERE " in sql.upper() and not _COVERAGE_WHERE_OK_RE.search(sql):
            return None
        m_sum = _COVERAGE_SUM_RE.search(sql)
        m_from = _COVERAGE_FROM_RE.search(sql)
        if not m_sum or not m_from:
            return None
        col, base = m_sum.group(1), m_from.group(1)
        base_res = conn.execute("__coverage_probe__", f"SELECT SUM({col}) FROM {base}", internal=True)
        if getattr(base_res, "error", None) or not base_res.rows or base_res.rows[0][0] is None:
            return None
        base_total = float(base_res.rows[0][0])
        if base_total == 0:
            return None
        # Probe the join frame directly: the query's FROM..JOIN..(WHERE) clause
        # with the same SUM, so the comparison shares every join condition.
        frame = sql[m_from.start():]
        for stop in (r"\bGROUP\s+BY\b", r"\bORDER\s+BY\b", r"\bLIMIT\b", r"\bHAVING\b"):
            s = re.search(stop, frame, re.IGNORECASE)
            if s:
                frame = frame[: s.start()]
        joined_res = conn.execute("__coverage_probe__", f"SELECT SUM({col}) {frame}", internal=True)
        if getattr(joined_res, "error", None) or not joined_res.rows or joined_res.rows[0][0] is None:
            return None
        joined_total = float(joined_res.rows[0][0])
        ratio = joined_total / base_total
        if ratio >= COVERAGE_THRESHOLD:
            return None
        return (
            f"Join coverage: the INNER JOIN in this query captures only {ratio:.0%} of "
            f"{col} in {base} — rows without a match in the joined table(s) are excluded, "
            f"so these totals understate the true figure. Re-run with LEFT JOINs (or treat "
            f"this as the matched subset only) before acting on absolute values."
        )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join-coverage probe is best-effort", counter="join_guard.coverage")
        return None
