"""Build-time audit of each north-star metric's ``value_sql``.

The BusinessProfile carries an LLM-written ``value_sql`` per metric — a scalar
query the Briefing runs live to show the metric's current value. The LLM gets the
grain right MOST of the time, but the wrong ones are confidently wrong and become
a headline KPI: a ROAS that joins three satellites of one order key (spend
over-counted 2.3M×), or a "Cart-to-Order Conversion" that filters the DENOMINATOR
to already-converted carts (``WHERE abandoned = 0``) so it reads 100% instead of
18%. A grounded-but-wrong KPI is worse than no KPI.

So before the profile is saved we route every ``value_sql`` through the SAME
authorities the explorer uses on its own SQL:
  1. dry-run (must parse + bind against the real schema);
  2. the static grain/fan-out guards (chasm SUM/COUNT/AVG, integer division,
     count-*-as-parent) — the structural over-count bugs;
  3. the join value-domain guard (fabricated joins like touchpoint_type = channel);
  4. a live range/boundary check — a bounded rate (0..1 / 0..100%) that comes out
     ABOVE its bound, or rounds to either boundary (0 or the max) at display
     precision, is a grain artifact, not a real value. (The classic >1 conversion
     bug and the abandoned=0 → 100% bug both land here.) So is a value outside any
     other band the unit/range states ('0..24' block hours, '≥ 1' order per active
     user); a band it only calls typical is never a bound.

A metric that fails is BLANKED (``value_sql = ""``); the Briefing's KPI strip
already drops metrics with no value_sql, so the result is "show nothing" rather
than "show a wrong number". The caller may then try a recipe-grounded
regeneration for blanked metrics that have a curated recipe (see infer.py) — the
audit is what tells it which ones need it.

Entirely best-effort and fail-OPEN per metric: any unexpected error leaves that
metric's value_sql untouched (no worse than before the audit existed).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# A number as range text writes it: "0", "-1", "0.95", "1,000,000".
_NUM = r"[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
# "0..1", "0.8–1.4", "~5–60", "$25–$75", "0% to 100%", "0 to +∞", "0 to 10,000,000+". A bound never starts glued
# to what precedes it: not the 2 of "B2B", the -1 of "month-1" or the second 0 of "0.0 to total revenue".
_TWO_SIDED_RE = re.compile(
    r"(?<![\w.])(?P<lo_approx>[~≈]\s*)?[$€£¥₹]?(?P<lo>" + _NUM + r")\s*%?\s*(?:\.\.|[–—‐‑‒−-]|\bto\b)\s*"
    r"(?:(?P<hi_inf>\+?\s*(?:∞|inf(?:inity)?\b))|(?P<hi_approx>[~≈]\s*)?[$€£¥₹]?(?P<hi>" + _NUM + r")(?P<hi_plus>\+)?)"
)
_BRACKET_RE = re.compile(r"\[\s*(?P<lo>" + _NUM + r")\s*,\s*(?P<hi>" + _NUM + r")\s*\]")
# "≥ 1", "<= 5", "0+" — a bound on one side, read only where the text declares its range (see stated_range).
_ONE_SIDED_RE = re.compile(
    r"(?P<op>≥|>=|≤|<=|>|<)\s*(?P<approx>[~≈]\s*)?[$€£¥₹]?(?P<num>" + _NUM + r")"
    r"|(?<![\w.])(?P<plus>" + _NUM + r")\+"
)
# Clauses: a band, and the words that hedge it, never cross ';', a parenthesis or a sentence's end.
_CLAUSE_SPLIT_RE = re.compile(r"[;()]|(?<!e\.g)(?<!i\.e)\.\s+(?=[A-Z])")
# Words that make a band what is usual rather than what is possible. "human scale" is the guess F4
# (infer._calibrate_ranges) names — 'USD (human scale: 20-150)' would flag a correct $537 AOV.
_HEDGE_RE = re.compile(
    r"\b(?:typical(?:ly)?|often|commonly|usually|e\.g\.|for example|expect(?:ed)?|roughly|approx(?:imately)?"
    r"|target(?:s|ed)?|healthy|human scale)",
    re.I,
)


def _number(text: str) -> float:
    return float(text.replace(",", "").replace("−", "-"))


def _first_stated_band(text: str) -> tuple[float | None, float | None, bool] | None:
    """(lo, hi, hedged) of the first band `text` states — None for an end the text leaves open — or None."""
    for i, clause in enumerate(_CLAUSE_SPLIT_RE.split(text)):
        forms = (_TWO_SIDED_RE, _BRACKET_RE, _ONE_SIDED_RE) if i == 0 else (_TWO_SIDED_RE, _BRACKET_RE)
        found = [m for m in (form.search(clause) for form in forms) if m]
        if not found:
            continue
        m = min(found, key=lambda match: match.start())
        groups = m.groupdict()
        if m.re is _ONE_SIDED_RE:
            if groups["plus"] is not None:
                lo, hi = _number(groups["plus"]), None
            else:
                bound = _number(groups["num"])
                lo, hi = (bound, None) if groups["op"] in ("≥", ">=", ">") else (None, bound)
            approx = bool(groups["approx"])
        else:
            lo = _number(groups["lo"])
            hi = None if groups.get("hi_inf") or groups.get("hi_plus") else _number(groups["hi"])
            approx = bool(groups.get("lo_approx") or groups.get("hi_approx"))
        return (lo, hi, approx or bool(_HEDGE_RE.search(clause[:m.start()])))
    return None


def stated_range(unit_or_range: str) -> tuple[str, float | None, float | None]:
    """Read the range a metric's unit/range text states, as the (kind, lo, hi) the live checks hold it to.

    kinds: 'ratio01' (a stated 0..1), 'pct100' (a stated 0..100), 'band' (any other stated band, open at an end
    where the text says so — '0..24', '≥ 1'), 'typical' (a band the text hedges — 'typically 0.8..1.4', 'often
    80–200', '~5–60' — which real values also fall outside, so it is never a bound), 'open' (no band, or one open
    above from zero — 'USD', 'ratio 0..∞', '≥ 0').

    The FIRST band the text states is its range; what follows glosses or comments on it, so 'ratio 0..1
    (0..100%); industry-typical 0.75–0.90' is a ratio. A one-sided bound counts only
    in the opening clause, where it declares the range ('ratio ≥ 1'); later ones are commentary thresholds
    ('healthy SaaS payback is <12 months'). A unit word alone states no band: 'ratio', 'percent' and '%' read
    'open' — a guessed bound fails real values (an inventory turnover of 5 read as a 0..1 ratio)."""
    band = _first_stated_band(unit_or_range or "")
    if band is None:
        return ("open", None, None)
    lo, hi, hedged = band
    if lo is not None and hi is not None and lo > hi:
        return ("open", None, None)
    if hi is None and lo == 0.0:
        return ("open", None, None)
    if hedged:
        return ("typical", lo, hi)
    if (lo, hi) == (0.0, 1.0):
        return ("ratio01", lo, hi)
    if (lo, hi) == (0.0, 100.0):
        return ("pct100", lo, hi)
    return ("band", lo, hi)


# Generic words in a metric name that don't identify WHICH metric it is — excluded
# so the distinctive tokens are the entity nouns (conversion, roas, margin, …).
_METRIC_GENERIC = frozenset(
    "rate ratio percent pct total average avg per the of and a an level overall "
    "current value score index amount number count share".split()
)


def profile_metric_ranges(profile) -> list[tuple]:
    """Build [(distinctive_tokens, kind, max_bound)] from a profile's north-star
    metrics so a FINDING can be checked against the metric's DECLARED sane range —
    the authoritative answer to "is a conversion of 1.41 a bug?" (yes, it's 'ratio
    0-1') vs "is a ROAS of 2.3 a bug?" (no, it's 'ratio 0-∞'). The text/keyword guess
    can't tell those apart; the profile can.

    max_bound is a bounded RATE's ceiling (1 or 100) and None for every other kind: a band bounds the
    metric's own scalar (audit_value_sql), not each column a finding returns beside it — the 31 aircraft
    next to a fleet's 11.2 block hours a day are not an impossible utilization."""
    import re as _re
    out: list[tuple] = []
    for m in (getattr(profile, "north_star_metrics", None) or []):
        name = getattr(m, "name", "") or ""
        toks = frozenset(
            t for t in _re.findall(r"[a-z][a-z0-9]{2,}", name.lower())
            if t not in _METRIC_GENERIC
        )
        if not toks:
            continue
        kind, _lo, hi = stated_range(getattr(m, "unit_or_range", "") or "")
        out.append((toks, kind, hi if kind in ("ratio01", "pct100") else None))
    return out


def match_metric_range(text: str, ranges: list[tuple]) -> tuple | None:
    """Return (kind, max_bound) of the profile metric whose distinctive tokens best
    match `text` (a finding/SQL), or None. A metric matches only if a MAJORITY of its
    distinctive tokens appear — so "cart-to-order conversion … 1.41" matches the
    Conversion metric (bounded 0-1) but a finding that merely mentions 'channel' won't
    spuriously bind to 'Channel-Level ROAS'."""
    if not text or not ranges:
        return None
    low = text.lower()
    best, best_hits = None, 0
    for toks, kind, mx in ranges:
        hits = sum(1 for t in toks if t in low)
        if hits and hits >= (len(toks) + 1) // 2 and hits > best_hits:
            best, best_hits = (kind, mx), hits
    return best


def make_uniqueness_oracle(conn, table_cols: dict):
    """Build an `is_unique_on(table_bare, key_col) -> bool | None` for the fan-out
    chasm guards, backed by a live `COUNT(*) = COUNT(DISTINCT key)` probe (cached on
    the conn). Lets the guards tell a 1:1 DIMENSION (e.g. invoices, one-per-order)
    from a real fan-out SATELLITE (e.g. attribution, many-per-order) so they stop
    blanking correct `SUM(measure × weight)` / `COUNT(*)` queries over a fact⋈dimension
    join. Returns None if no conn (guards then stay conservative)."""
    if conn is None:
        return None
    qualified: dict[str, str] = {}
    for t in (table_cols or {}):
        qualified.setdefault(str(t).split(".")[-1].lower(), str(t))
    # Cache probes on the conn when it has a normal __dict__ (so repeated audits in a
    # build share results); fall back to a local cache for slotted conns — no silent
    # swallow either way.
    cache = getattr(conn, "_fanout_uniq_cache", None)
    if cache is None:
        cache = {}
        if hasattr(conn, "__dict__"):
            conn._fanout_uniq_cache = cache

    def is_unique_on(bare: str, col: str):
        key = (bare.lower(), col.lower())
        if key in cache:
            return cache[key]
        tbl = qualified.get(bare.lower(), bare)
        val = None
        try:
            res = conn.execute("fanout-uniq-probe",
                               f'SELECT COUNT(*) = COUNT(DISTINCT "{col}") FROM {tbl}')
            if not getattr(res, "error", None):
                rows = getattr(res, "rows", None) or []
                if rows and rows[0] and rows[0][0] is not None:
                    cell = rows[0][0]
                    # results come back stringified ('True'/'False') — bool('False') is
                    # truthy, so parse the value rather than coercing the string.
                    val = cell if isinstance(cell, bool) else \
                        str(cell).strip().lower() in ("true", "t", "1")
        except Exception:
            val = None
        cache[key] = val
        return val

    return is_unique_on


def make_cardinality_oracle(conn, table_cols: dict):
    """Build a `distinct_count(table_bare, col) -> int | None` backed by a live
    `COUNT(DISTINCT col)` probe (cached on the conn). Lets a guard tell a CONTINUOUS
    measure (revenue: hundreds/thousands of distinct values) from a DISCRETE dimension
    (a 1–5 rating, a fiscal year) when a column's name/type alone can't — the signal the
    group-by-continuous-measure guard needs. Returns None if no conn (guard stays conservative)."""
    if conn is None:
        return None
    qualified: dict[str, str] = {}
    for t in (table_cols or {}):
        qualified.setdefault(str(t).split(".")[-1].lower(), str(t))
    cache = getattr(conn, "_fanout_cardinality_cache", None)
    if cache is None:
        cache = {}
        if hasattr(conn, "__dict__"):
            conn._fanout_cardinality_cache = cache

    def distinct_count(bare: str, col: str):
        key = (bare.lower(), col.lower())
        if key in cache:
            return cache[key]
        tbl = qualified.get(bare.lower(), bare)
        val = None
        try:
            res = conn.execute("cardinality-probe",
                               f'SELECT COUNT(DISTINCT "{col}") FROM {tbl}')
            if not getattr(res, "error", None):
                rows = getattr(res, "rows", None) or []
                if rows and rows[0] and rows[0][0] is not None:
                    val = int(float(str(rows[0][0])))     # results come back stringified
        except Exception:
            val = None
        cache[key] = val
        return val

    return distinct_count


def _first_numeric(rows: list[list]) -> float | None:
    """The single scalar a value_sql is supposed to return — first numeric cell of
    the first row. None if absent/NULL/non-numeric (a value_sql that can't produce
    a scalar is itself a failure)."""
    if not rows:
        return None
    for cell in rows[0]:
        if cell is None or cell == "" or cell == "NULL":
            continue
        try:
            return float(cell)
        except (TypeError, ValueError):
            continue
    return None


def audit_value_sql(value_sql: str, table_cols: dict, conn, unit_or_range: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means the value_sql is untrustworthy and
    should be dropped. Fail-open: on any internal error returns (True, "") so a
    flaky audit never discards a metric."""
    sql = (value_sql or "").strip()
    if not sql:
        return (False, "empty")
    try:
        dialect = getattr(conn, "dialect", "duckdb")

        # 1. dry-run: must parse + bind against the real schema.
        try:
            ok, why = conn.dry_run(sql)
            if not ok:
                return (False, f"does not bind: {why}")
        except Exception:
            pass  # dry_run unavailable → fall through to execution, which also binds

        # 2. static grain/fan-out guards — the same DROP signals the explorer uses.
        # A cardinality oracle lets the chasm guards skip 1:1 dimensions (e.g. invoices)
        # so a correct fact⋈dimension SUM(measure × weight) isn't blanked as a chasm.
        from aughor.sql.fanout import (
            integer_division_risk, count_star_entity_fanout, count_star_chasm_fanout,
            avg_over_chasm_fanout, sum_over_chasm_fanout, cte_grain_mismatch_fanout,
            measure_times_key_arithmetic, avg_of_row_ratios,
        )
        uniq = make_uniqueness_oracle(conn, table_cols)
        grain = (integer_division_risk(sql)
                 or count_star_entity_fanout(sql, table_cols)
                 or count_star_chasm_fanout(sql, table_cols, dialect=dialect, is_unique_on=uniq)
                 or avg_over_chasm_fanout(sql, table_cols, dialect=dialect, is_unique_on=uniq)
                 or sum_over_chasm_fanout(sql, table_cols, dialect=dialect, is_unique_on=uniq)
                 or cte_grain_mismatch_fanout(sql, table_cols, dialect=dialect)
                 or measure_times_key_arithmetic(sql, table_cols, dialect=dialect)
                 or avg_of_row_ratios(sql, table_cols, dialect=dialect))
        if grain:
            return (False, f"grain bug: {grain}")

        # 3. join value-domain guard — fabricated joins (vocabularies don't overlap).
        try:
            from aughor.sql.join_guard import check_join_value_domains
            warns = check_join_value_domains(conn, sql)
            if warns:
                return (False, f"fabricated join: {warns[0].to_prompt_text()}")
        except Exception:
            pass

        # 4. live range/boundary check.
        try:
            res = conn.execute("profile-value-sql", sql)
            if getattr(res, "error", None):
                return (False, f"errors: {res.error}")
            val = _first_numeric(getattr(res, "rows", []) or [])
            if val is None:
                return (False, "no scalar (NULL/empty result)")
            kind, lo, hi = stated_range(unit_or_range)
            if kind in ("ratio01", "pct100", "band"):
                # Outside a stated bound → a grain artifact (the >1 conversion bug, a
                # 26-hour aircraft day). Slack is 5% of the band's width — a rate's 1.05,
                # a percent's 105 — or of its one bound when an end is open.
                scale = (hi - lo) if lo is not None and hi is not None else abs(hi if lo is None else lo)
                slack = 0.05 * scale
                if hi is not None and val > hi + slack:
                    return (False, f"out of range: {val:g} > {hi:g} for '{unit_or_range}'")
                if lo is not None and val < lo - slack:
                    return (False, f"out of range: {val:g} < {lo:g} for '{unit_or_range}'")
            if kind in ("ratio01", "pct100"):
                # Rounds to a boundary at display precision → degenerate. A real
                # bounded rate is almost never exactly 0% or 100%; both boundaries
                # are the signature of a broken denominator (abandoned=0 → 100%,
                # ROUND(weight) → 0). Mirrors the KPI strip's existing "drop 0".
                disp = val / hi  # → 0..1
                if round(disp, 3) <= 0.0 or round(disp, 3) >= 1.0:
                    return (False, f"degenerate boundary value {val:g} for bounded rate '{unit_or_range}'")
            elif round(val, 4) == 0.0:
                # Anything else — a band, a typical band (never a bound: real values
                # fall outside it), currency/days/ratio 0..∞ — is degenerate only when
                # it rounds to zero (no card should read $0 / 0d / 0.0).
                return (False, f"degenerate zero value for '{unit_or_range}'")
        except Exception:
            pass  # execution failed unexpectedly → don't punish the metric

        return (True, "")
    except Exception as exc:
        logger.debug("value_sql audit errored (fail-open): %s", exc)
        return (True, "")


def audit_chart_sql(chart_sql: str, table_cols: dict, conn) -> tuple[bool, str]:
    """Audit a metric's chart_sql — the SERIES that explains the metric (a trend or a
    top-N breakdown) on the Briefing. Same structural authorities as value_sql (dry-run +
    grain/fan-out guards + join value-domain guard), but the result check is shape-based,
    not range-based: a chart needs ≥2 rows and at least one non-degenerate numeric column
    (a single point, or an all-NULL/all-zero measure, is not a chart). Fail-open."""
    sql = (chart_sql or "").strip()
    if not sql:
        return (False, "empty")
    try:
        dialect = getattr(conn, "dialect", "duckdb")
        try:
            ok, why = conn.dry_run(sql)
            if not ok:
                return (False, f"does not bind: {why}")
        except Exception:
            pass

        from aughor.sql.fanout import (
            integer_division_risk, count_star_entity_fanout, count_star_chasm_fanout,
            avg_over_chasm_fanout, sum_over_chasm_fanout, cte_grain_mismatch_fanout,
            measure_times_key_arithmetic, avg_of_row_ratios,
        )
        uniq = make_uniqueness_oracle(conn, table_cols)
        grain = (integer_division_risk(sql)
                 or count_star_entity_fanout(sql, table_cols)
                 or count_star_chasm_fanout(sql, table_cols, dialect=dialect, is_unique_on=uniq)
                 or avg_over_chasm_fanout(sql, table_cols, dialect=dialect, is_unique_on=uniq)
                 or sum_over_chasm_fanout(sql, table_cols, dialect=dialect, is_unique_on=uniq)
                 or cte_grain_mismatch_fanout(sql, table_cols, dialect=dialect)
                 or measure_times_key_arithmetic(sql, table_cols, dialect=dialect)
                 or avg_of_row_ratios(sql, table_cols, dialect=dialect))
        if grain:
            return (False, f"grain bug: {grain}")
        try:
            from aughor.sql.join_guard import check_join_value_domains
            warns = check_join_value_domains(conn, sql)
            if warns:
                return (False, f"fabricated join: {warns[0].to_prompt_text()}")
        except Exception:
            pass

        try:
            res = conn.execute("profile-chart-sql", sql)
            if getattr(res, "error", None):
                return (False, f"errors: {res.error}")
            rows = getattr(res, "rows", []) or []
            if len(rows) < 2:
                return (False, "not a series (need ≥2 rows)")
            # At least one numeric column must carry a non-degenerate value across the
            # series — an all-NULL or all-zero measure draws a flat, meaningless chart.
            width = len(rows[0]) if rows else 0
            has_live_measure = False
            for ci in range(width):
                col = [r[ci] for r in rows if ci < len(r)]
                nums = []
                for c in col:
                    if c is None or c == "" or c == "NULL":
                        continue
                    try:
                        nums.append(float(c))
                    except (TypeError, ValueError):
                        nums = None
                        break  # a text column (label) — not the measure
                if nums and any(n != 0.0 for n in nums):
                    has_live_measure = True
                    break
            if not has_live_measure:
                return (False, "degenerate series (no live numeric column)")
        except Exception:
            pass
        return (True, "")
    except Exception as exc:
        logger.debug("chart_sql audit errored (fail-open): %s", exc)
        return (True, "")


def audit_finding_sql(sql: str, table_cols: dict, conn) -> tuple[bool, str]:
    """Audit a key-question SQL — a filtered/composite query that RETURNS ROWS (e.g.
    "the SKUs with >90% margin AND >10% returns"). Same structural authorities as the
    others (dry-run + grain/fan-out guards + join value-domain guard); the result check
    is "answers the question": ≥1 row with at least one non-null cell. (A 0-row result
    is a valid 'none qualify' answer but makes a vacuous finding, so it's rejected.)
    Fail-open on internal error."""
    s = (sql or "").strip()
    if not s:
        return (False, "empty")
    try:
        dialect = getattr(conn, "dialect", "duckdb")
        try:
            ok, why = conn.dry_run(s)
            if not ok:
                return (False, f"does not bind: {why}")
        except Exception:
            pass
        from aughor.sql.fanout import (
            integer_division_risk, count_star_entity_fanout, count_star_chasm_fanout,
            avg_over_chasm_fanout, sum_over_chasm_fanout, cte_grain_mismatch_fanout,
            measure_times_key_arithmetic, avg_of_row_ratios,
        )
        uniq = make_uniqueness_oracle(conn, table_cols)
        grain = (integer_division_risk(s)
                 or count_star_entity_fanout(s, table_cols)
                 or count_star_chasm_fanout(s, table_cols, dialect=dialect, is_unique_on=uniq)
                 or avg_over_chasm_fanout(s, table_cols, dialect=dialect, is_unique_on=uniq)
                 or sum_over_chasm_fanout(s, table_cols, dialect=dialect, is_unique_on=uniq)
                 or cte_grain_mismatch_fanout(s, table_cols, dialect=dialect)
                 or measure_times_key_arithmetic(s, table_cols, dialect=dialect)
                 or avg_of_row_ratios(s, table_cols, dialect=dialect))
        if grain:
            return (False, f"grain bug: {grain}")
        try:
            from aughor.sql.join_guard import check_join_value_domains
            warns = check_join_value_domains(conn, s)
            if warns:
                return (False, f"fabricated join: {warns[0].to_prompt_text()}")
        except Exception:
            pass
        try:
            res = conn.execute("profile-finding-sql", s)
            if getattr(res, "error", None):
                return (False, f"errors: {res.error}")
            rows = getattr(res, "rows", []) or []
            if not rows:
                return (False, "no rows (question has no answer)")
            if not any(c not in (None, "", "NULL") for r in rows for c in r):
                return (False, "all-NULL result")
        except Exception:
            pass
        return (True, "")
    except Exception as exc:
        logger.debug("finding_sql audit errored (fail-open): %s", exc)
        return (True, "")


# RC3 — a metric NAMED for a category/label ("Top Return Reason", "… by category",
# "distribution", "breakdown") must not be a scalar percent/ratio KPI: "Top Return Reason
# 0.4%" is nonsense — a reason is a label, not a number. Drop its value_sql so the strip
# never renders it as a scalar (the chart_sql breakdown, if any, still stands).
_LABEL_NAME_RE = re.compile(r"\b(reason|categor(?:y|ies)|distribution|breakdown|mix)\b", re.I)
_PCT_RATIO_UNIT_RE = re.compile(r"percent|ratio|\b0\s*-\s*1\b|0\s*-\s*100|%", re.I)


def name_sql_coherent(name: str, unit_or_range: str) -> tuple[bool, str]:
    """False when a category/label-named metric is declared as a scalar percent/ratio —
    the name↔value mismatch that renders 'Top Return Reason 0.4%'."""
    if _LABEL_NAME_RE.search(name or "") and _PCT_RATIO_UNIT_RE.search(unit_or_range or ""):
        return (False, f"name '{name}' implies a category/label but it is declared as a scalar "
                       f"'{unit_or_range}' — a category can't be a single percentage")
    return (True, "")


def audit_profile(profile, conn, schema: str) -> dict[str, str]:
    """Audit every metric's value_sql AND chart_sql IN PLACE: blank either if it
    fails and return {metric_name: reason} for the value_sql failures (so the caller
    can try a recipe-grounded regeneration). chart_sql failures are blanked silently
    (the Briefing just shows one fewer explainer chart). Never raises."""
    failures: dict[str, str] = {}
    try:
        from aughor.tools.schema import parse_schema_tables
        table_cols = parse_schema_tables(schema)
    except Exception:
        table_cols = {}
    for m in getattr(profile, "north_star_metrics", []) or []:
        vs = (getattr(m, "value_sql", "") or "").strip()
        if vs:
            # RC3 — name↔SQL coherence FIRST (static, no query cost). A category-named
            # metric must not surface as a scalar percentage KPI.
            ok, reason = name_sql_coherent(getattr(m, "name", ""), getattr(m, "unit_or_range", ""))
            if not ok:
                failures[m.name] = reason
                m.value_sql = ""
                continue
            ok, reason = audit_value_sql(vs, table_cols, conn, getattr(m, "unit_or_range", ""))
            if not ok:
                failures[m.name] = reason
                m.value_sql = ""  # drop it — KPI strip shows nothing rather than a wrong number
        cs = (getattr(m, "chart_sql", "") or "").strip()
        if cs:
            ok, reason = audit_chart_sql(cs, table_cols, conn)
            if not ok:
                logger.info("[profile] chart_sql dropped for %r: %s", m.name, reason)
                m.chart_sql = ""  # no explainer chart for this metric rather than a broken one
    return failures
