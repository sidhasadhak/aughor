"""Pre-emission insight verification gate — the explorer's last-line trust screen, extracted
verbatim from explorer/agent.py (a 4k-line god-file) into a cohesive, independently-testable module.
Behavior is unchanged (pure move).

`verify_insight` is THE gate: a candidate finding is surfaced only if it passes every deterministic
check — SQL soundness, degenerate/boundary-saturated results, part>whole, vacuous CASE, impossible
magnitude/ratio, claim-grounding, and (via metric_coherence) the name↔SQL coherence + formula-drift
guards. The structural guards are its private helpers; the cross-module surface is PUBLIC
(`verify_insight`, `is_degenerate_result`, `has_fabricated_dimension`, `clamp_novelty`,
`mislabeled_per_grain`) so importers stay off the private-import ratchet.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.kernel.errors import tolerate
from aughor.explorer.metric_coherence import (
    drifted_registered_metric,
    metric_vocab_for,
    mislabeled_named_metric,
)

_RATE_CTX_RE = re.compile(
    r"\b(?:conversion|convert|rate|ratio|share|percent|pct|margin|occupancy|"
    r"utiliz|attach|win[\s_-]?rate|success[\s_-]?rate|load[\s_-]?factor)\b",
    re.IGNORECASE,
)

# A finding whose text says the query returned nothing / failed (used by is_degenerate_result +
# revalidate). These must not become insights: noise in the Briefing, broken monitors if clicked.
_NO_DATA_RE = re.compile(
    r"(returned no data|no data (found|available|to report|for)|0 \w+ (were |was )?found|"
    r"null values for all|no rows (returned|found|matched)|query (failed|errored)|"
    r"no matching (rows|records|data)|empty result set)",
    re.I,
)


def is_degenerate_result(rows, finding_text: str = "", sql: str = "", metric_ranges=None) -> bool:
    """True when a Phase-8 result carries no trustworthy data — so it never becomes an
    insight (and so never reaches the Briefing). Cases:

      1. the whole result is NULL (empty join/filter matched nothing), OR
      2. ANY numeric column is NULL across EVERY row, OR ZERO across every row — a metric
         that never computed because a join/linkage is broken (a `touchpoint_type=channel`
         join that matches nothing → revenue/ROAS all NULL) or a value was destroyed
         (`ROUND(weight, 4)` on a ~2e-07 weight → every ROAS = 0.0). RULE: a NULL **or
         all-zero** metric must not appear in a Briefing — it reads as a confident finding
         ("$0 ROAS — no revenue captured") when it is really a query bug; the underlying
         data ($491M revenue) is intact. OR
      3. a bounded RATE OUT OF its declared range — a 0..1 rate that comes out ≈1.0 in every
         segment (broken denominator → "100% conversion across all traffic sources") OR
         ABOVE 1 (a 141% conversion). The AUTHORITY is the profile when available: a finding
         is matched to its north-star metric and its DECLARED sane range applied — so a
         conversion (ratio 0-1) at 1.41 is dropped while a ROAS (ratio 0-∞) at 2.3 is kept.
         Without a profile match it falls back to a keyword rate-signal + boundary check
         (so a count-of-1 / always-true flag is not mistaken for a saturated rate). OR
      4. the interpretation text explicitly says "no data".

    A column with MIXED values (some at the boundary, some not) is real signal and
    survives — only a metric flat NULL / flat zero / out-of-range is dropped."""
    # The profile's declared range for THIS finding's metric, when we can match it —
    # the precise authority that tells a bounded conversion from an unbounded ROAS.
    matched = None
    if metric_ranges:
        try:
            from aughor.profile.validate import match_metric_range
            matched = match_metric_range(f"{finding_text}\n{sql}", metric_ranges)
        except Exception:
            matched = None
    m_kind, m_max = (matched if matched else (None, None))
    rate_ctx = bool(_RATE_CTX_RE.search(f"{sql}\n{finding_text}"))
    if rows:
        # Normalise to row-lists (dict rows → values in stable key order).
        if isinstance(rows[0], dict):
            keys = list(rows[0].keys())
            norm = [[r.get(k) for k in keys] for r in rows]
        else:
            norm = [list(r) for r in rows]
        ncols = max((len(r) for r in norm), default=0)
        for i in range(ncols):
            col = [r[i] for r in norm if i < len(r)]
            if not col:
                continue
            nonnull = [c for c in col if c is not None and c != "" and c != "NULL"]
            if not nonnull:
                return True          # entirely-NULL column → broken/empty linkage
            try:
                nums = [float(c) for c in nonnull]
            except (TypeError, ValueError):
                continue             # non-numeric (a dimension) — not a dead measure
            if all(n == 0.0 for n in nums):
                return True          # a NUMERIC column that is ZERO everywhere → no signal
            hi = max(nums)
            # (a) Profile-authoritative range check: the matched metric is a BOUNDED rate
            # and this column overshoots its ceiling → grain bug (conversion 1.41, 105%).
            # Applies to a single column too (a per-channel rate need not span ≥2 rows to
            # be impossible). A matched OPEN metric (ROAS) is explicitly exempt.
            if m_max is not None:
                # Normalise to a 0..1 fraction, TOLERATING the SQL emitting the other scale
                # than declared — a metric declared 'ratio 0-1' whose query returns 100.0, OR
                # declared 'percent 0-100' whose query returns 1.0. Both are the broken-
                # denominator / saturation signature; the old check missed them because the
                # raw value sat far from the declared ceiling. Works on a single segment too.
                fracs: list | None = [v / m_max for v in nums]
                if hi > m_max * 1.5:
                    alt = 100.0 if m_max == 1.0 else 1.0
                    if min(nums) >= 0.0 and hi <= alt * 1.5:
                        fracs = [v / alt for v in nums]   # SQL used the OTHER scale
                    else:
                        fracs = None                       # a count-like column, not this rate
                if fracs is not None:
                    if any(f > 1.05 for f in fracs):
                        return True      # above the bound → impossible rate (conversion 1.41)
                    if all(f >= 0.9995 for f in fracs):
                        return True      # saturated at the ceiling (100% repeat / 100% approved)
            # (b) Keyword fallback when no profile match — saturated-at-ceiling only (the
            # >bound case is unsafe without knowing bounded-vs-unbounded). Skip entirely
            # when we matched an OPEN metric (don't ceiling-drop a real ROAS=1.0).
            elif matched is None and rate_ctx and len(norm) >= 2:
                lo = min(nums)
                if 0.0 <= lo and hi <= 1.0005 and all(n >= 0.9995 for n in nums):
                    return True      # 0..1 rate pinned at 1.0 in every segment
                if 0.0 <= lo and hi <= 100.05 and all(n >= 99.95 for n in nums):
                    return True      # 0..100% rate pinned at 100 in every segment
    return bool(finding_text and _NO_DATA_RE.search(finding_text))


# Tokens that mark a SUM(... × weight) as the NORMALIZED multi-touch attribution idiom —
# where the per-order weights sum to 1, so SUM(measure × weight) over a fact⋈attribution
# join is NOT inflated (the F2 case). Such a SUM is exempt from the chasm DROP.
_WEIGHT_FACTOR_RE = re.compile(r"sum\s*\([^)]*\b(weight|share|alloc\w*|attribution)\b", re.IGNORECASE)
# Salient numbers a narration asserts — currency, comma-grouped counts, percentages.
_CLAIM_NUM_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\s?%")


def _safe_float(x):
    """float(x) or None — expected non-numeric cells are control flow, not an error."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _uniqueness_oracle_for(conn):
    """Build (and cache on conn) the cardinality oracle the fan-out chasm guards use to
    treat a 1:1 dimension as a non-satellite. Returns None if conn/schema unavailable."""
    if conn is None:
        return None
    try:
        from aughor.profile.validate import make_uniqueness_oracle
        from aughor.tools.schema import parse_schema_tables
        tc = getattr(conn, "_insight_table_cols", None)
        if tc is None:
            tc = parse_schema_tables(conn.get_schema())
            if hasattr(conn, "__dict__"):
                conn._insight_table_cols = tc
        return make_uniqueness_oracle(conn, tc)
    except Exception as _e:
        tolerate(_e, "insight-gate: cardinality oracle unavailable", counter="insight_gate.oracle_failed")
        return None


def _insight_sql_unsound(sql: str, conn=None) -> str | None:
    """Static SQL-trust battery for a CANDIDATE INSIGHT's query — the same authorities the
    profile audit applies, now enforced BEFORE an explorer finding can be emitted. Returns a
    one-line reason the query is untrustworthy, or None. High precision (errs toward keeping):

      • self-ratio tautology (X/X → always 1.0),
      • parent fan-out (SUM/AVG of a parent table's measure across a join to its child),
      • chasm fan-out (≥2 many-side satellites of one hub) for SUM/COUNT(*)/AVG — with the
        cardinality oracle (a 1:1 dimension is not a satellite) AND a carve-out for the
        normalized SUM(measure × weight) attribution idiom, which is fan-out-safe."""
    s = (sql or "").strip()
    if not s:
        return None
    try:
        from aughor.sql.fanout import (
            self_ratio_tautology, detect_fanout, sum_over_chasm_fanout,
            count_star_chasm_fanout, avg_over_chasm_fanout, measure_times_key_arithmetic,
            avg_of_row_ratios, dimension_ratio_chasm,
        )
    except Exception:
        return None

    taut = self_ratio_tautology(s)
    if taut:
        return taut

    idmath = measure_times_key_arithmetic(s)
    if idmath:
        return f"id-arithmetic: {idmath[:160]}"

    ratio = avg_of_row_ratios(s)
    if ratio:
        return f"avg-of-ratios: {ratio[:160]}"

    # Build the oracle FIRST — it parses + caches conn._insight_table_cols, so the fan-out
    # guards reuse that schema parse (no second private import of parse_schema_tables).
    oracle = _uniqueness_oracle_for(conn)
    table_cols = getattr(conn, "_insight_table_cols", None) or {}

    # Fan-out battery (one guarded block; fail-open via tolerate, never silent):
    #   • detect_fanout — high-precision multi-satellite/parent detector ("category GMV
    #     $457k > total GMV $251k"); exempt the normalized SUM(measure × weight) idiom.
    #   • chasm SUM/COUNT/AVG with the cardinality oracle (a 1:1 dimension isn't a satellite).
    #   • the SAME chasm battery re-run on each CTE BODY — the outer-scope guards miss a
    #     chasm HIDDEN inside a CTE (the ROAS bug: channel_revenue AS (SELECT SUM(...) FROM
    #     order_items JOIN attribution ...)).
    try:
        weighted = bool(_WEIGHT_FACTOR_RE.search(s))
        if not weighted:
            f = detect_fanout(s, table_cols)
            if f is not None:
                return f"fan-out: {f.to_prompt_text()[:160]}"
            # Backstop for the dimension-join ratio detect_fanout can't see (#159): if the
            # de-fan rewrite upstream couldn't adopt, drop rather than emit a fanned ratio.
            fdr = dimension_ratio_chasm(s, table_cols)
            if fdr is not None:
                return f"fan-out: {fdr.to_prompt_text()[:160]}"
        if oracle is not None:
            if not weighted:
                r = sum_over_chasm_fanout(s, table_cols, is_unique_on=oracle)
                if r:
                    return f"fan-out: {r[:160]}"
            for fn in (count_star_chasm_fanout, avg_over_chasm_fanout):
                r = fn(s, table_cols, is_unique_on=oracle)
                if r:
                    return f"fan-out: {r[:160]}"
            import sqlglot
            from sqlglot import exp as _exp
            for cte in sqlglot.parse_one(s, read="duckdb").find_all(_exp.CTE):
                body = cte.this.sql(dialect="duckdb")
                if _WEIGHT_FACTOR_RE.search(body):
                    continue
                rc = (sum_over_chasm_fanout(body, table_cols, is_unique_on=oracle)
                      or count_star_chasm_fanout(body, table_cols, is_unique_on=oracle)
                      or avg_over_chasm_fanout(body, table_cols, is_unique_on=oracle))
                if rc:
                    return f"fan-out in CTE '{cte.alias_or_name}': {rc[:140]}"
    except Exception as _e:
        tolerate(_e, "insight-gate: fan-out analysis", counter="insight_gate.fanout_failed")
    return None


# A column whose NAME is a count/row-tally is never a grand total nor a money "part" — it is a
# different measure. Used to stop a constant COUNT column (e.g. `n` = 210 weeks/channel) from being
# mistaken for the total that a money column "exceeds" (the spurious fan-out flag on a ratio scan).
_COUNT_COL_RE = re.compile(r'(^|[_\s])(n|cnt|count|num|rows?|records?|freq|samples?|observations?)([_\s]|$)', re.I)
# Beyond this overshoot the candidate "total" and the "part" are different MEASURES (a count next to
# money), not a fan-out over-count of the same measure — a real fan-out exceeds the total only modestly.
_PART_WHOLE_OVERSHOOT_CAP = 1000.0


def _part_exceeds_whole(rows, columns=None) -> str | None:
    """Internal-consistency check: a column that is CONSTANT across the result is a candidate
    grand total; if another numeric column has a value that EXCEEDS it, the 'parts' are bigger
    than the 'whole' — the signature of a fan-out total (the 'category GMV $457k > total GMV
    $251k' bug). Conservative: needs ≥2 rows, both columns at money/count magnitude (≥100), and
    a clear >5% overshoot — so a constant rate next to a count never trips it.

    Guards against the ratio-scan false positive: a constant COUNT column (`n`) sitting next to a
    money column is NOT a part/whole pair. Count columns are excluded by name (when `columns` are
    known) and, as a measure-agnostic backstop, an overshoot of orders of magnitude is ignored
    (a fan-out exceeds the total modestly; a count-vs-money mismatch exceeds it ~1000×+)."""
    if not rows or len(rows) < 2:
        return None
    norm = [list(r.values()) if isinstance(r, dict) else list(r) for r in rows]
    ncols = min((len(r) for r in norm), default=0)
    # Resolve column names from the explicit arg or, failing that, dict-row keys.
    names = None
    if columns and len(columns) >= ncols:
        names = [str(c) for c in columns[:ncols]]
    elif rows and isinstance(rows[0], dict):
        names = [str(k) for k in list(rows[0].keys())[:ncols]]
    count_idx = {i for i, nm in enumerate(names) if _COUNT_COL_RE.search(nm)} if names else set()
    cols = []
    for i in range(ncols):
        parsed = [_safe_float(r[i]) for r in norm]
        cols.append(parsed if all(v is not None for v in parsed) else None)
    for i, ci in enumerate(cols):
        if i in count_idx:
            continue                      # a count is never a grand total
        if not ci or len(set(ci)) != 1:
            continue                      # column i must be CONSTANT (a candidate total)
        total = ci[0]
        if abs(total) < 100:
            continue                      # too small to be a money/count total — skip (rates)
        for j, cj in enumerate(cols):
            if j == i or not cj or j in count_idx:
                continue                  # a count is never a money 'part' of the total
            mx = max(cj)
            if abs(total) * 1.05 < mx <= abs(total) * _PART_WHOLE_OVERSHOOT_CAP and mx >= 100:
                return (f"component exceeds total: a value {mx:.0f} exceeds the constant "
                        f"total {total:.0f} in the same result — fan-out over-count")
    return None


def _salient_number_pairs(text: str) -> list:
    """(token, float) for every salient number the narration asserts — currency, comma-grouped
    counts, percentages. The token is kept for human-readable messages."""
    out = []
    for tok in _CLAIM_NUM_RE.findall(text or ""):
        v = _safe_float(re.sub(r"[\$,%\s]", "", tok))
        if v is not None:
            out.append((tok, v))
    return out


def _result_cells(rows) -> list:
    """Flatten every numeric cell from the result (row cap keeps it cheap on wide results)."""
    cells = []
    for r in (rows or [])[:200]:
        row = r.values() if isinstance(r, dict) else r
        cells.extend(v for v in (_safe_float(c) for c in row) if v is not None)
    return cells


def _dedup_cells(cells: list, cap: int = 48) -> list:
    """Deduped, bounded subset for the O(n²) derivation scan."""
    uniq, seen = [], set()
    for c in cells:
        k = round(c, 6)
        if k not in seen:
            seen.add(k)
            uniq.append(c)
        if len(uniq) >= cap:
            break
    return uniq


def _number_grounded(v: float, cells: list, uniq: list) -> bool:
    """A number is grounded if it matches a cell (raw / ±percent-fraction, within 1%) OR is
    DERIVED from a cell pair — a % change ((b-a)/a·100), a share (b/a·100) or a raw delta (b-a).
    Crediting derivations stops the check crying wolf on valid arithmetic (e.g. a '+1,506%'
    growth computed from €986K → €15.84M that appears in no single cell)."""
    def close(a, b):
        return b != 0 and abs(a - b) <= abs(b) * 0.01 + 1e-6
    for c in cells:
        for cand in (c, c * 100.0, c / 100.0):  # percent ↔ fraction
            if close(v, cand):
                return True
    if v == 0.0:
        return True
    for a in uniq:
        if a == 0:
            continue
        for b in uniq:
            for cand in ((b - a) / a * 100.0, abs(b - a) / abs(a) * 100.0, b / a * 100.0, b - a):
                if close(v, cand):
                    return True
    return False


def _claim_numbers_grounded(finding_text: str, rows) -> str | None:
    """Conservative claim-grounding: every salient number the NARRATION asserts (currency,
    comma-grouped counts, percentages) should trace to the actual result. Flags ONLY gross
    fabrication — ≥2 salient numbers asserted and NONE grounded (raw or derived) in the rows.
    Rounding, abbreviations ($1.3M) and a single derived figure never trip it — false positives
    here would drop good insights, so the bar is deliberately high."""
    if not finding_text or not rows:
        return None
    pairs = _salient_number_pairs(finding_text)
    if len(pairs) < 2:
        return None
    cells = _result_cells(rows)
    if not cells:
        return None
    uniq = _dedup_cells(cells)
    if not any(_number_grounded(v, cells, uniq) for _, v in pairs):
        return (f"claim not grounded: none of the asserted figures "
                f"{[t for t, _ in pairs][:4]} appear in the query result")
    return None


def grounded_fraction(finding_text: str, rows) -> float:
    """Fraction of the text's salient numbers grounded (raw or derived) in the result cells.
    Used to break narrator↔query binding ties by NUMERIC evidence: a finding binds to the query
    whose result actually contains its numbers, so a z-score card can't inherit a PoP finding's
    numbers just because they share a dimension. 0.0 when there are no numbers or no cells."""
    pairs = _salient_number_pairs(finding_text)
    cells = _result_cells(rows)
    if not pairs or not cells:
        return 0.0
    uniq = _dedup_cells(cells)
    return sum(1 for _, v in pairs if _number_grounded(v, cells, uniq)) / len(pairs)


# RC4 — implausible ratio/turnover magnitude. A turnover or multiplier is bounded by
# reality (inventory turns a few × per year; a multiplier rarely exceeds tens). When a
# finding asserts a turnover/ratio/×-multiplier in the thousands it is virtually always a
# grain bug (e.g. SUM(units_sold)/AVG(units_on_hand) across all product-months → 96,295)
# — never a real signal. Deliberately conservative: a high cap and a narrow keyword set so
# it only fires on genuine grain explosions, never on a legitimate large count or revenue.
# A number DIRECTLY bound to a ratio word — "turnover of 96,295.6", "turnover (25.0x)",
# "ratio: 1,200", "turnover is 96295". No other digit may sit between the word and the
# number, so a nearby revenue figure ("$175.06M" two words away) is never captured — that
# loose-window false-positive is exactly what wrongly flagged a healthy 25× tier.
_RATIO_NUM_RE = re.compile(
    r"\b(?:turnover|multiplier|ratio)\b\s*(?:of|is|at|was|=|:|reached|hit|stands at)?\s*[\(\[]?\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*([kmb])?",
    re.I,
)
# "<number>x"/"<number>×" multiplier, and "<number> turnover/multiplier".
_TIMES_MULT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*[x×]\b", re.I)
_NUM_RATIO_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*\b(?:turnover|multiplier)\b", re.I)
_IMPLAUSIBLE_RATIO_CAP = 1000.0


def _parse_magnitude(num: str, suf: str = "") -> "Optional[float]":
    """Expand a numeric token ('96,295.6' + 'M') to a float; None if unparseable."""
    s = (num or "").strip().replace(",", "")
    try:
        base = float(s)
    except ValueError:
        return None
    return base * {"k": 1e3, "m": 1e6, "b": 1e9}.get((suf or "").lower(), 1.0)


def _implausible_ratio_claim(finding_text: str, cap: float = _IMPLAUSIBLE_RATIO_CAP) -> str:
    """Return a reason when the finding asserts a turnover/ratio/×-multiplier DIRECTLY bound
    to a number far beyond a sane bound (a grain-bug signature), else ''. Tightly scoped to
    the number that belongs to the ratio word so a legitimate large revenue/count nearby is
    never flagged."""
    t = finding_text or ""
    if not t:
        return ""
    candidates: list[tuple[str, str]] = []
    for rx in (_RATIO_NUM_RE, _TIMES_MULT_RE, _NUM_RATIO_RE):
        candidates += [(m.group(1), m.group(2) or "") for m in rx.finditer(t)]
    for num, suf in candidates:
        v = _parse_magnitude(num, suf)
        if v is not None and abs(v) > cap:
            return (f"implausible turnover/ratio magnitude in finding ({num.strip()}{suf} ≫ {cap:g}) "
                    "— almost certainly a grain bug, not a real signal")
    return ""


# Named-metric ↔ SQL coherence + relabel/drift guards live in metric_coherence.py (extracted
# from this god-file). verify_insight (below) and the Phase-8 emission sites import them.

def verify_insight(rows, finding_text: str = "", sql: str = "", metric_ranges=None, conn=None, *, columns=None, industry: str = "") -> tuple[bool, str]:
    """THE pre-emission trust gate: a candidate finding is surfaced ONLY if it passes every
    deterministic check. Returns (ok, reason). A SOTA platform treats generated claims as
    untrusted until verified — so the explorer self-weeds (tautologies, fan-out artifacts,
    boundary-saturated rates, fabricated numbers) instead of shipping confident nonsense to
    a Briefing. Supersedes the bare degenerate check at every emission site; fail-open only
    on internal error (never silently drops a sound finding due to a gate bug)."""
    try:
        why = _insight_sql_unsound(sql, conn)
        if why:
            return (False, why)
        if is_degenerate_result(rows, finding_text, sql, metric_ranges):
            return (False, "degenerate result (flat NULL / zero / boundary-pinned rate)")
        pw = _part_exceeds_whole(rows, columns=columns)
        if pw:
            return (False, pw)
        vc = _vacuous_case_dimension(sql, rows)
        if vc:
            return (False, vc)
        # Impossible-magnitude check (operating bands), shared with the briefing's triage so
        # there is ONE band KB. Lifted to the EMISSION gate so an impossible value (inventory
        # turnover 3,600×) never gets stored — protecting the insight cards and any other
        # consumer, not just the brief. Only the 'implausible' severity hard-rejects here; the
        # 'confound' severity is deliberately NOT rejected (an inverse relationship can be a
        # real finding — "churn falls as engagement rises") and stays a soft demotion at synthesis.
        try:
            from aughor.knowledge.triage import plausibility as _plausibility
            _pv = _plausibility(finding_text, sql)
            if _pv.severity == "implausible":
                return (False, _pv.reason)
        except Exception as _e:
            tolerate(_e, "insight-gate: plausibility band check", counter="insight_gate.plausibility_failed")
        # RC4 backstop — a generic implausible turnover/ratio CLAIM in the finding text that
        # the structural + operating-band checks above didn't already catch (runs last so the
        # more-specific reasons — vacuous CASE, operating band — win when they apply).
        ir = _implausible_ratio_claim(finding_text)
        if ir:
            return (False, ir)
        cg = _claim_numbers_grounded(finding_text, rows)
        if cg:
            return (False, cg)
        nm = mislabeled_named_metric(finding_text, sql, metric_vocab_for(conn, industry))
        if nm:
            return (False, nm)
        dr = drifted_registered_metric(finding_text, sql)
        if dr:
            return (False, dr)
        return (True, "")
    except Exception:
        return (True, "")  # fail-open: a gate bug must not suppress real findings


_LITERAL_DIM_RE = re.compile(r"""['"][^'"]*['"]\s+AS\s+(\w+)""", re.IGNORECASE)


def has_fabricated_dimension(sql: str) -> bool:
    """True when a query invents its dimension by aliasing a constant literal and
    grouping by it — e.g. ``SELECT 'Unknown' AS signup_source ... GROUP BY signup_source``.

    The model writes this when the real column doesn't exist, producing a vacuous
    single-group "breakdown" the narrator then presents as a real category ("the
    only channel represented"). High-precision: only fires when the SOLE grouping
    key is the constant — a real dimension alongside it is a legitimate breakdown.
    """
    if not sql:
        return False
    low = sql.lower()
    if "group by" not in low:
        return False
    gb = low.split("group by", 1)[1]
    gb = re.split(r"\b(order\s+by|having|limit|window|qualify)\b", gb, maxsplit=1)[0]
    keys = [k.strip() for k in gb.split(",") if k.strip()]
    if len(keys) != 1:
        return False  # another real dimension is present → legitimate breakdown
    key = keys[0]
    if key.startswith("'") or key.startswith('"'):
        return True  # GROUP BY 'literal'
    return any(m.group(1).lower() == key for m in _LITERAL_DIM_RE.finditer(sql))


# A CASE that buckets rows into string labels: capture each branch's THEN label and the
# ELSE default. ``.+?`` (non-greedy, DOTALL) tolerates quoted IN-lists inside the WHEN
# condition (``WHEN x IN ('A','B') THEN 'mass'``) — it stops at the branch's own THEN.
_CASE_THEN_RE = re.compile(r"\bWHEN\b.+?\bTHEN\s+'([^']+)'", re.IGNORECASE | re.DOTALL)
_CASE_ELSE_RE = re.compile(r"\bELSE\s+'([^']+)'\s+END\b", re.IGNORECASE)


def _vacuous_case_dimension(sql: str, rows) -> str | None:
    """Reason when a CASE that segments rows into labels collapses ENTIRELY into its ELSE
    default — i.e. the WHEN literals matched NO rows, so the derived dimension is a single
    meaningless bucket presented as a real segmentation.

    The canonical bug: ``CASE WHEN brand_name IN ('CeraVe','La Mer',…) THEN 'mass'/'luxury'
    … ELSE 'unknown'`` on data whose brands are actually ``Brand_000`` — every row falls to
    'unknown', the cross-tier comparison is vacuous, and a real ``brand_tier`` column was
    ignored. High-precision: needs ≥2 intended categories AND a result where ONLY the ELSE
    label appears and NONE of the THEN labels do (an empty ⋂ proves the scheme matched
    nothing). A query whose CASE produced even one real category never trips it."""
    if not sql or not rows:
        return None
    then_labels = {m.strip().lower() for m in _CASE_THEN_RE.findall(sql) if m.strip()}
    else_labels = {m.strip().lower() for m in _CASE_ELSE_RE.findall(sql) if m.strip()}
    if len(then_labels) < 2 or not else_labels:
        return None   # not a multi-branch labelled categorization with a default
    present: set[str] = set()
    for r in rows[:500]:
        cells = r.values() if isinstance(r, dict) else r
        for c in cells:
            if isinstance(c, str) and c.strip():
                present.add(c.strip().lower())
    if not present:
        return None
    if (else_labels & present) and not (then_labels & present):
        return (f"vacuous categorization: a CASE bucketed every row into its default "
                f"'{sorted(else_labels)[0]}' — the intended categories {sorted(then_labels)[:4]} "
                f"matched no rows (hardcoded literals absent from the data; a real category "
                f"column was likely ignored)")
    return None


def clamp_novelty(v) -> int:
    """Novelty is a 1-5 score (see the interpret prompt). The LLM occasionally
    echoes a data magnitude into it — e.g. revenue 77568 lands in `novelty`, which
    then pins confidence at 95% (``0.4 + novelty*0.1`` capped) and lets a junk
    finding own the headline (novelty drives ranking). Clamp to the valid range."""
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return 3


# Per-grain mislabel (#6): a line-item-grain column averaged and presented as a
# per-ORDER / per-customer metric. True AOV = SUM(revenue)/COUNT(DISTINCT order);
# `AVG(oi.line_total) AS aov` averages LINE ITEMS, undercounting (the $467-vs-$1108
# mislabel). High-precision: keys off a line-grain column name inside AVG() that's
# then labelled (alias or narration) as an order/customer-level metric.
_LINE_GRAIN_COL = re.compile(r"line_?(total|amount|item|price|value|subtotal|qty|quantity)|item_(total|amount|price|qty)", re.I)
_PER_ORDER_LABEL = re.compile(r"\baov\b|average\s+order\s+value|avg_?order_?value|order_?value|per[\s_]order|per[\s_]customer|per[\s_]basket", re.I)


def mislabeled_per_grain(sql: str, finding_text: str = "") -> bool:
    """True when SQL averages a line-item-grain column but the alias or the finding
    narrates it as a per-order/per-customer value — a semantic mislabel the numeric
    grounding can't catch (the averaged value is a real cell, just the wrong metric)."""
    if not sql:
        return False
    for m in re.finditer(r"AVG\s*\(([^)]*)\)(?:\s+AS\s+(\w+))?", sql, re.IGNORECASE):
        arg, alias = m.group(1), (m.group(2) or "")
        if _LINE_GRAIN_COL.search(arg) and (_PER_ORDER_LABEL.search(alias) or _PER_ORDER_LABEL.search(finding_text)):
            return True
    return False
