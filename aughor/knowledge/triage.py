"""
Briefing triage — CEO-grade brief selection.

The autonomous explorer emits many findings of uneven worth. A *daily executive*
brief must do two things the old "top-N by novelty" selection did not:

  1. LEAD with the finding that carries the most business weight — not the newest
     and not the most confident, but the one describing the biggest move in a metric
     the operator actually watches. (Why the missimi brief led with a noise-level
     ROAS split — 4.42 vs 4.46 — while margin and AOV slid unmentioned.)
  2. Never present an impossible number or an anti-causal correlation as fact. (Why
     it showed "inventory turnover 3,600×" — a broken denominator — and "stockouts
     fall as lead time rises" — a textbook confound — as confident insights.)

This module is the deterministic triage the synthesiser runs over candidate findings
BEFORE it writes the narrative:

  • impact_score()   — rank by (magnitude-of-change × north-star membership ×
                       confidence), so the headline is chosen by what moves the
                       business, not by novelty/recency.
  • plausibility()   — SUPPRESS impossible magnitudes (turnover 3,600×) and DEMOTE
                       anti-causal correlations (an inverse monotonic relationship
                       between two operational variables) to a flagged hypothesis
                       that can never lead the brief.
  • extract_change() — pull the contrasted numbers a finding asserts ("47% → 34%",
                       "4.42 vs 4.46") so a trivial contrast scores near-zero and a
                       real swing scores high.

Pure + dependency-light (regex only) so it is cheap to call on every finding and
trivial to unit-test. See tests/unit/test_triage.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ── change extraction ─────────────────────────────────────────────────────────

# A number with optional thousands grouping / decimals (currency + percent suffix
# stripped by the caller). Kept off ID/version middles by the surrounding patterns.
_N = r"-?\d[\d,]*(?:\.\d+)?"
_CUR = r"[$€£¥₹]?\s?"   # an optional leading currency symbol — captured number excludes it
_TR = r"%?"            # an optional trailing percent — "47% → 34%" must still parse the pair
# Contrasted-pair shapes the narrator (and the underlying SQL result) actually use:
#   "A → B" / "A -> B"        a before/after move
#   "A vs B" / "A versus B"   an A-against-B contrast (acq vs retention ROAS)
#   "from A to B"             an explicit transition
# Each side tolerates a currency prefix and a percent suffix so "from €75 to €56" and
# "from 50% to 34%" and "$1,200 → $900" all parse.
_PAIR_RES = [
    re.compile(rf"{_CUR}({_N}){_TR}\s*(?:→|-+>|–+>)\s*{_CUR}({_N}){_TR}"),
    re.compile(rf"{_CUR}({_N}){_TR}\s*(?:vs\.?|versus)\s*{_CUR}({_N}){_TR}", re.I),
    re.compile(rf"\bfrom\s+{_CUR}({_N}){_TR}\s+to\s+{_CUR}({_N}){_TR}\b", re.I),
]


@dataclass(frozen=True)
class Change:
    """The largest contrasted move a finding asserts."""
    big: float
    small: float
    rel: float   # |big-small| / max(|big|,|small|) — 0.0 for a trivial contrast, ~1+ for a swing


def _f(tok: str) -> Optional[float]:
    try:
        return float(tok.replace(",", ""))
    except (TypeError, ValueError):
        return None


def extract_change(finding: str) -> Optional[Change]:
    """The biggest contrasted move in ``finding`` (by relative magnitude), or None
    when it asserts no A-vs-B / A→B pair. A finding that only states a *level*
    ("affiliate is 86.8% of new-customer orders") returns None — its weight comes
    from north-star membership, not from a change."""
    if not finding:
        return None
    best: Optional[Change] = None
    for rx in _PAIR_RES:
        for m in rx.finditer(finding):
            a, b = _f(m.group(1)), _f(m.group(2))
            if a is None or b is None:
                continue
            denom = max(abs(a), abs(b))
            if denom == 0:
                continue
            rel = abs(a - b) / denom
            if best is None or rel > best.rel:
                hi, lo = (a, b) if abs(a) >= abs(b) else (b, a)
                best = Change(big=hi, small=lo, rel=rel)
    return best


# ── plausibility ───────────────────────────────────────────────────────────────

# Operating-band knowledge for OPEN-ended metrics (unit '0..∞') whose NAME still
# implies a realistic ceiling. The profile's bounded-rate guard can't catch these —
# turnover is declared 0..∞, so a value of 3,600 sails through. High-precision keys:
# only specific metric families, and only flagged when a value GROSSLY exceeds the
# band, so a real outlier near the edge is never dropped. (max_plausible, why).
_BANDS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"inventory\s+turn(?:over|s)?|stock\s+turn(?:over|s)?|inventory\s+turnover\s+ratio", re.I),
     100.0,
     "inventory turnover above ~100× signals a broken denominator (real annual turns run ~2–12×)"),
]

# A plain number NOT used as a percentage or currency rate — the magnitude a band
# check inspects. (We don't want "turnover rate 95%" to trip the turns band.)
_PLAIN_NUM = re.compile(rf"(?<![\w.$£€])({_N})(?!\s?%)")

# Inverse-monotonic relationship between two variables, stated as a standalone
# insight: "<metric> decreases/falls/drops … as … <driver> increases/rises/longer"
# (or the mirror). The explorer can establish correlation, never causation, so an
# inverse monotonic claim is the shape where a hidden-variable confound most often
# hides (the stockouts-fall-as-lead-time-rises case). DEMOTED, not suppressed.
_UP = r"(?:increas\w+|ris\w+|grow\w+|climb\w+|longer|higher|larger|more\b|up\b)"
_DOWN = r"(?:decreas\w+|declin\w+|drop\w*|fall\w*|shrink\w+|reduc\w+|fewer|lower|shorter|less\b|down\b)"
_GAP = r"[\w\s,()_./%-]*?"
_CONFOUND_RES = [
    re.compile(rf"\b{_DOWN}{_GAP}\bas\b{_GAP}{_UP}\b", re.I),   # outcome down  as driver up
    re.compile(rf"\b{_UP}{_GAP}\bas\b{_GAP}{_DOWN}\b", re.I),   # outcome up    as driver down
]


@dataclass(frozen=True)
class Verdict:
    """Trust verdict for one finding.

    severity: 'ok' | 'implausible' (suppress) | 'confound' (demote).
    ``ok`` is True only for 'ok' — both other severities keep the finding OUT of the
    synthesis lead; 'implausible' is hidden entirely, 'confound' is shown as a flagged
    hypothesis in the held-back strip."""
    ok: bool
    severity: str
    reason: str


_OK = Verdict(ok=True, severity="ok", reason="")


# ── aggregate ↔ column-type compatibility ────────────────────────────────────────
# The SQL engine silently COERCES a wrong-typed aggregate into a real-looking, meaningless
# number: SUM(signup_fy) over a VARCHAR fiscal-year sums the year integers, STDDEV over text
# casts and computes garbage. Grounding can't catch this — the query "succeeds" — so we refuse
# the finding by the column's DECLARED type. Only a BARE column is checked (an expression's or a
# CAST's type is unknown); an unmapped column is skipped, so it never misfires on an unknown
# schema. DELIBERATELY NOT type-checked, because they are valid idioms whose flagging would
# break real analytics:
#   • SUM/AVG(boolean)            — count / proportion of TRUE rows.
#   • COUNT / COUNT(DISTINCT) any — COUNT(DISTINCT customer_id) is the backbone of analytics;
#                                   "distinct of a measure" is a grain concern, not a type error.
#   • MIN / MAX any ordered type  — numbers, dates and text all order.

def _type_category(dtype: str) -> str:
    """Coarse category of a declared column type, for aggregate compatibility."""
    d = dtype.lower()
    if "interval" in d:                                             # additive (SUM/AVG ok)
        return "interval"
    if "bool" in d:
        return "boolean"
    if "[]" in d or re.search(r"json|blob|struct|\bmap\b|\blist\b|array|binary|bytea|geometry|union", d):
        return "complex"
    if re.search(r"int|dec|num|double|float|real|serial|money", d):
        return "numeric"
    if re.search(r"date|timestamp|time", d):
        return "temporal"
    if re.search(r"char|text|string|uuid|enum", d):
        return "text"
    return "unknown"


# Aggregate → the type categories it is meaningful on. A function ABSENT here is not
# type-checked (COUNT, MIN, MAX, STRING_AGG, MODE, ANY_VALUE, FIRST/LAST, …).
_AGG_OK: dict[str, frozenset] = {
    "sum": frozenset({"numeric", "interval", "boolean"}),
    "avg": frozenset({"numeric", "interval", "boolean"}),
    "stddev": frozenset({"numeric"}), "stddev_pop": frozenset({"numeric"}), "stddev_samp": frozenset({"numeric"}),
    "variance": frozenset({"numeric"}), "var_pop": frozenset({"numeric"}), "var_samp": frozenset({"numeric"}),
    "median": frozenset({"numeric"}), "quantile_cont": frozenset({"numeric"}), "percentile_cont": frozenset({"numeric"}),
    "corr": frozenset({"numeric"}), "covar_pop": frozenset({"numeric"}), "covar_samp": frozenset({"numeric"}),
    "kurtosis": frozenset({"numeric"}), "skewness": frozenset({"numeric"}), "geomean": frozenset({"numeric"}),
}

_CATEGORY_LABEL = {"text": "text", "temporal": "date/time", "complex": "structured",
                   "boolean": "boolean", "interval": "interval"}

# A single aggregate call over a BARE column (or table.col); DISTINCT / ALL allowed. An
# expression (SUM(price*qty)) or a CAST won't match the tight ")" and is left alone.
_AGG_CALL = re.compile(r"\b([a-z_]+)\s*\(\s*(?:all\s+|distinct\s+)?([a-z_]\w*(?:\.[a-z_]\w*)?)\s*\)", re.I)


def _aggregate_type_mismatch(sql: str, col_types: dict[str, str]) -> Optional[str]:
    """Why a finding is untrustworthy: its SQL applies a numeric aggregate (SUM/AVG/STDDEV/
    MEDIAN/…) to a column whose DECLARED type can't support it (text, date/time, a structured
    type — or interval/boolean for a stats aggregate). The result is a type-coercion artifact,
    not a measure. Fires only on a bare, TYPE-KNOWN column."""
    if not sql or not col_types:
        return None
    for m in _AGG_CALL.finditer(sql):
        fn, ref = m.group(1).lower(), m.group(2).lower()
        ok = _AGG_OK.get(fn)
        if ok is None:
            continue
        dtype = col_types.get(ref) or col_types.get(ref.split(".")[-1])
        if not dtype:
            continue
        cat = _type_category(dtype)
        if cat != "unknown" and cat not in ok:
            bare = ref.split(".")[-1]
            return (f"{fn.upper()}() over the {_CATEGORY_LABEL.get(cat, cat)} column '{bare}' ({dtype}) — "
                    f"a {fn.upper()} of a non-numeric column is a type-coercion artifact, not a real measure")
    return None


# ── averaging an already-computed rate ──────────────────────────────────────────
# A column whose NAME marks it as a stored rate / ratio / share / percentage (mirrors the
# proven semantic.measure_grain._RATE_RE). AVG() over such a column is an UNWEIGHTED mean of
# per-group rates: every group counts equally regardless of its denominator, so small groups
# dominate and the number is biased (the freight-% 1.48%-vs-2.17% class of scar). The correct
# group-level rate is the RATIO OF SUMS. This complements sql.fanout.avg_of_row_ratios, which
# catches the INLINE AVG(a/b) form; here we catch the pre-computed rate-COLUMN form.
_RATE_COL = re.compile(r"_(pct|percent|rate|ratio|share)$|(?:^|_)(pct|percent)(?:_|$)", re.I)


def _averages_a_rate(sql: str) -> Optional[str]:
    """Why a finding is untrustworthy: its SQL takes AVG() of a stored rate-named column, an
    unweighted mean of per-group rates that biases toward small groups. Fires only on a bare
    AVG of a rate-named column — AVG(a/b) (handled elsewhere), AVG(amount), a windowed AVG, or
    an AVG of an expression are all left alone (the tight ')' in _AGG_CALL won't match them)."""
    if not sql:
        return None
    for m in _AGG_CALL.finditer(sql):
        if m.group(1).lower() != "avg":
            continue
        bare = m.group(2).split(".")[-1]
        if _RATE_COL.search(bare):
            return (f"AVG('{bare}') averages an already-computed rate — an unweighted mean of "
                    f"per-group rates over-weights small groups and biases the result; the "
                    f"group rate is the ratio of sums SUM(numerator)/NULLIF(SUM(denominator),0)")
    return None


# ── COUNT(DISTINCT <measure>) — cardinality of a continuous quantity, not a count ────────
# Counting distinct values is meaningful for a KEY or a DIMENSION (distinct customers, distinct
# regions) but MEANINGLESS for a raw continuous measure (distinct revenues, distinct prices) —
# and it is a frequent mislabel ("4,213 customers" that is really COUNT(DISTINCT order_amount)).
# High precision: the column name must be a monetary/quantity token AND carry no key/dimension
# marker, so the analytics backbone COUNT(DISTINCT customer_id) and COUNT(DISTINCT price_tier)
# are left alone. (Complements the aggregate↔type check, which is about type, not grain.)
_COUNT_DISTINCT = re.compile(r"\bcount\s*\(\s*distinct\s+([a-z_]\w*(?:\.[a-z_]\w*)?)\s*\)", re.I)
_MEASURE_TOKEN = re.compile(
    r"(?:^|_)(price|cost|margin|amount|revenue|sales|spend|gmv|cogs|profit|freight|"
    r"subtotal|payment|turnover|markup|markdown)(?:$|_)", re.I)
_DIMENSIONISH = re.compile(
    r"(?:^|_)(id|key|sk|code|no|num|tier|band|segment|group|category|cat|bucket|class|"
    r"level|grade|rank|range|bin|zone|region|status|type|flag|name|label|kind|date|ts|"
    r"timestamp|at)(?:$|_)", re.I)


def _count_distinct_measure(sql: str) -> Optional[str]:
    """Why a finding is untrustworthy: COUNT(DISTINCT <measure>) counts how many distinct values
    a continuous measure takes — a cardinality of a quantity, not a business count, and often a
    mislabel. Fires only on a monetary/quantity-named column with no key/dimension marker, so
    COUNT(DISTINCT customer_id) / COUNT(DISTINCT price_tier) / COUNT(DISTINCT region) are safe."""
    if not sql:
        return None
    for m in _COUNT_DISTINCT.finditer(sql):
        bare = m.group(1).split(".")[-1]
        if _DIMENSIONISH.search(bare):
            continue
        if _MEASURE_TOKEN.search(bare):
            return (f"COUNT(DISTINCT {bare}) counts how many distinct values the measure "
                    f"'{bare}' takes — a cardinality of a continuous quantity, not a business "
                    f"count; a count of entities uses COUNT(DISTINCT <the entity id>)")
    return None


def plausibility(finding: str, sql: str = "", col_types: Optional[dict[str, str]] = None) -> Verdict:
    """Deterministic trust verdict. Implausible magnitude beats confound beats ok —
    an impossible number is never worth surfacing even if it also reads causal.

    `col_types` (bare + qualified column name → declared dtype) enables the non-additive
    aggregate check; omit it and that check simply no-ops."""
    if not finding:
        return _OK

    # (0) Aggregate–type mismatch — a numeric aggregate (SUM/AVG/STDDEV/…) over a column
    # whose type can't support it. Highest priority: the number is meaningless regardless of
    # what the prose claims about it.
    reason = _aggregate_type_mismatch(sql, col_types or {})
    if reason:
        return Verdict(False, "implausible", reason)

    # (0b) Averaging an already-computed rate — AVG(<rate column>) is a biased unweighted mean
    # of per-group rates; the number is methodologically wrong, not just imprecise, so it is
    # never worth headlining. The explorer re-derives the ratio of sums (its prompts mandate it).
    reason = _averages_a_rate(sql)
    if reason:
        return Verdict(False, "implausible", reason)

    # (0c) COUNT(DISTINCT <measure>) — the cardinality of a continuous quantity, not a count.
    reason = _count_distinct_measure(sql)
    if reason:
        return Verdict(False, "implausible", reason)

    hay = f"{finding}\n{sql}"

    # (1) Impossible magnitude — an open-ended metric grossly outside its operating band.
    for rx, ceiling, why in _BANDS:
        if rx.search(hay):
            nums = [v for v in (_f(t) for t in _PLAIN_NUM.findall(finding)) if v is not None]
            if any(abs(v) > ceiling for v in nums):
                worst = max(nums, key=abs)
                return Verdict(False, "implausible", f"{why} (asserted {worst:g}×)")

    # (2) Anti-causal correlation — inverse monotonic relationship stated as an insight.
    for rx in _CONFOUND_RES:
        if rx.search(finding):
            return Verdict(
                False, "confound",
                "correlational, not causal — an inverse relationship with a likely hidden "
                "variable; demoted to a hypothesis to test, not a lead finding",
            )
    return _OK


# ── north-star membership ───────────────────────────────────────────────────────

# Generic words in a metric name that don't identify WHICH metric it is (mirrors
# profile.validate._METRIC_GENERIC) — excluded so the distinctive tokens are the
# entity nouns (margin, repeat, order, retention …).
_GENERIC = frozenset(
    "rate ratio percent pct total average avg per the of and a an level overall "
    "current score index amount number count share gross net".split()
)


def north_star_tokens(names) -> list[frozenset]:
    """Distinctive token-sets for each north-star metric name, for membership tests."""
    out: list[frozenset] = []
    for name in (names or []):
        toks = frozenset(
            t for t in re.findall(r"[a-z][a-z0-9]{2,}", (name or "").lower())
            if t not in _GENERIC
        )
        if toks:
            out.append(toks)
    return out


def _hits_north_star(finding: str, tokensets: list[frozenset]) -> bool:
    """True when the finding clearly names one of the north-star metrics. A single-token
    name (e.g. 'margin') matches on that token; a multi-token name needs ≥2 of its tokens
    present — so "Average Order Value" ({order,value}) needs BOTH "order" and "value", and
    a bare "new-customer orders" no longer masquerades as an AOV finding."""
    if not finding or not tokensets:
        return False
    low = finding.lower()
    for toks in tokensets:
        hits = sum(1 for t in toks if t in low)
        need = 1 if len(toks) == 1 else 2
        if hits >= need:
            return True
    return False


# ── impact score ────────────────────────────────────────────────────────────────

def _clamp01(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


# What makes a finding lead-worthy, in order: how big the move is, whether it touches
# a metric the operator watches, a RISK tilt (lead with the fire), how sure we are, and
# (least) how novel it is. Tuned so a trivial contrast on a watched metric still loses to
# a real swing, and an equal-magnitude RISK edges out a GAIN — but a much larger gain still
# wins (the change term dominates the risk tilt).
_W_CHANGE, _W_NORTHSTAR, _W_RISK, _W_CONF, _W_NOVELTY = 0.40, 0.30, 0.15, 0.20, 0.10

# A "fire": a DECLINE in a metric where down-is-bad (margin, revenue, AOV, retention …).
# Detected from the prose so it applies to both metric moves and explorer findings.
_DOWN_IS_BAD = re.compile(
    r"margin|revenue|\baov\b|order\s+value|profit|gross|retention|repeat|\bsales\b|gmv|"
    r"\bltv\b|conversion|loyalty|lifetime\s+value", re.I)
_DECLINE = re.compile(
    r"fallen|\bfell\b|declin|dropp|decreas|erosion|eroded|shrink|shr[au]nk|contract|"
    r"worsen|slipp|slid|deteriorat|\bdown\b", re.I)


def _is_risk(finding: str) -> bool:
    """True when the finding describes a DECLINE in a down-is-bad metric — the 'fire' a CEO
    brief should lead with over an equal-sized gain."""
    return bool(_DOWN_IS_BAD.search(finding) and _DECLINE.search(finding))


def impact_score(finding: str, novelty, confidence, tokensets: list[frozenset]) -> float:
    """Business-impact score used to ORDER findings and pick the brief's lead. Replaces
    novelty-only ranking: a noise-level contrast (ROAS 4.42 vs 4.46) scores ~0 on the change
    term and falls below a real swing or a watched-metric finding; and a decline in a
    down-is-bad metric carries a risk tilt so the fire leads over an equal-magnitude gain."""
    ch = extract_change(finding)
    change = min(ch.rel, 1.0) if ch else 0.0
    ns = 1.0 if _hits_north_star(finding, tokensets) else 0.0
    risk = 1.0 if _is_risk(finding) else 0.0
    conf = _clamp01(confidence)
    nov = _clamp01((novelty or 0) / 5.0)
    return (_W_CHANGE * change + _W_NORTHSTAR * ns + _W_RISK * risk
            + _W_CONF * conf + _W_NOVELTY * nov)


# ── currency ─────────────────────────────────────────────────────────────────────

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "INR": "₹"}


def currency_symbol(code: Optional[str]) -> str:
    """Display symbol for an ISO currency code; falls back to the bare code so an
    unmapped currency still reads as '<CODE> 1,234' rather than a wrong '$'."""
    if not code:
        return "$"
    return _SYMBOLS.get(code.upper(), f"{code.upper()} ")
