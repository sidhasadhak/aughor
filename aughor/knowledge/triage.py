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


def plausibility(finding: str, sql: str = "") -> Verdict:
    """Deterministic trust verdict. Implausible magnitude beats confound beats ok —
    an impossible number is never worth surfacing even if it also reads causal."""
    if not finding:
        return _OK
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
