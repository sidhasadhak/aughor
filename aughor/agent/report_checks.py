"""PE-2 — deterministic post-generation checks on a synthesized report.

The old synthesis prompt spent ~1,700 tokens per call LECTURING about sign
conventions, waterfall sums, grounding, and answering the question asked. These are
correctness CONTRACTS, and a contract belongs in code that verifies, not prose that
hopes: the repo's own benchmark receipt (deterministic guards > LLM machinery on
strong models) is the design authority here.

Each check returns violation sentences naming exactly what to fix — the shape a
one-shot retry can act on. Checks are conservative by construction: a check that
cannot decide says nothing, because a false violation costs a real retry (a whole
model call) and erodes trust in the ones that fire.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Numbers as models write them: 1,234.56 · -18 · 406.08 · 67.6
_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")
#: Sentence boundaries — the unit a violation is reported in, so the message shows the
#: claim rather than a bare number with no context.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
#: Compact forms ("$2.1M", "480K") are legitimate roundings of evidence values this
#: module cannot cheaply verify — grounding skips them rather than crying wolf.
_COMPACT_SUFFIX = re.compile(r"[\d.]\s*[KMBkmb]\b")


#: The named statistical pitfalls this codebase enforces, by the number `docs/PITFALLS.md`
#: gives them. One vocabulary for three readers: the narrator prompt cites the numbers it must
#: avoid, every violation string below names the pitfall it caught, and a person reading the
#: report can look the number up. Adding a check means adding its number here and its row
#: there — `tests/unit/test_pitfalls_contract.py` fails if the two drift apart.
PITFALLS = {
    2: "non-significant is not no effect",
    3: "statistically significant is not important",
    11: "a mean from a handful of records is not a finding",
    12: "an effect reported without its size",
    15: "correlation asserted as causation",
    17: "a whole-population claim from a truncated slice",
    32: "a measured quantity replaced by a 0/1 flag",
    36: "a claim the run's own evidence does not contain",
}


def pitfall(number: int) -> str:
    """`#3 (statistically significant is not important):` — the prefix a violation leads with."""
    name = PITFALLS.get(number)
    return f"#{number} ({name}):" if name else f"#{number}:"


def _float_or_none(s: str) -> Optional[float]:
    """A regex-matched token as a float, or None for the residue the pattern admits
    but float() does not ('.', ''). Expected-case parsing, not a swallowed failure."""
    try:
        return float(s)
    except ValueError:
        value = None
    return value


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


def _label_sign(label: str) -> Optional[int]:
    """The leading sign of an amount label ('-$287K' → -1, '+$120K' → +1). None when
    the label carries no explicit sign — an unsigned label is a style choice, not a
    provable contradiction."""
    s = (label or "").strip()
    if s.startswith("-"):
        return -1
    if s.startswith("+"):
        return 1
    return None


def check_signs(waterfall: list[dict]) -> list[str]:
    """Within one entry, amount_label and pct_of_total must not contradict."""
    out = []
    for w in waterfall or []:
        ls = _label_sign(str(w.get("amount_label") or ""))
        pct = w.get("pct_of_total")
        if ls is None or not isinstance(pct, (int, float)) or pct == 0:
            continue
        if ls != _sign(float(pct)):
            out.append(
                f"attribution_waterfall entry '{w.get('cause', '?')}' contradicts itself: "
                f"amount_label '{w.get('amount_label')}' and pct_of_total {pct} carry "
                "opposite signs — a cause pushed the metric one way, give both fields that sign.")
    return out


def check_waterfall_sums(waterfall: list[dict]) -> list[str]:
    """Signed contributions should account for roughly the whole change."""
    pcts = [float(w.get("pct_of_total")) for w in (waterfall or [])
            if isinstance(w.get("pct_of_total"), (int, float))]
    if len(pcts) < 2:
        return []
    total = sum(pcts)
    if 60.0 <= abs(total) <= 140.0:
        return []
    return [
        f"attribution_waterfall pct_of_total values sum to {total:.0f} — they should "
        "account for approximately ±100% of the change; add an 'Unexplained / residual' "
        "entry for the missing share instead of leaving it unaccounted."]


def _question_numbers(question: str) -> list[str]:
    """Specific numeric claims in the question ('is $14', 'dropped 18%') — the things
    a report must engage with to have answered the question. A trailing bare dot is
    sentence punctuation, not a decimal point ('…is $14.' claims 14, not '14.')."""
    out = []
    for n in _NUM_RE.findall(question or ""):
        n = n.rstrip(".").strip("+-")
        digits = n.replace(",", "").replace(".", "")
        if digits and n not in ("0",):
            out.append(n)
    return out


def check_question_addressed(question: str, report_texts: str) -> list[str]:
    """A question that makes a NUMERIC claim ('total revenue is $14') is answered only
    by a report that engages that number — confirming, correcting, or disputing it.
    The $14 specimen's report never mentioned 14 anywhere."""
    q_nums = _question_numbers(question)
    if not q_nums:
        return []
    text_norm = (report_texts or "").replace(",", "")
    missing = [n for n in q_nums if n.replace(",", "") not in text_norm]
    if len(missing) < len(q_nums):
        return []          # it engaged at least one claimed figure — addressed
    return [
        f"{pitfall(36)} the question makes a specific numeric claim ({', '.join(q_nums[:3])}) and the "
        "report never mentions it — confirm the figure, correct it with the measured "
        "value, or state plainly that the premise does not hold."]


def _evidence_number_set(evidence: str) -> set[str]:
    """Every number in the evidence, normalised (commas stripped), plus common
    roundings (0–2 decimals) so '406.083' grounds a written '406.08'.

    A rate is stored as a fraction and written as a percentage, so the SAME number appears
    two ways: the evidence holds `0.8131868131868132` and the report says `81.32`. A
    raw-string comparison called that fabricated and, on the very first live run, shipped
    "these figures do not appear anywhere in FULL EVIDENCE" over three correct figures and
    knocked the report from HIGH to MEDIUM. Each value therefore also enters the set at
    percent scale (and, for a report that quotes the fraction, at fraction scale).
    """
    out: set[str] = set()

    def _add_roundings(value: float) -> None:
        for dp in (0, 1, 2):
            out.add(f"{value:.{dp}f}".rstrip("0").rstrip(".") or "0")
            out.add(f"{abs(value):.{dp}f}".rstrip("0").rstrip(".") or "0")

    for n in _NUM_RE.findall(evidence or ""):
        clean = n.replace(",", "").strip("+-")
        if not clean or clean == ".":
            continue
        out.add(clean)
        f = _float_or_none(clean)
        if f is None:
            continue
        _add_roundings(f)
        # Cross-scale: a fraction in [-1, 1] is quotable as a percent, and a percent is
        # quotable as the fraction it came from. Bounded to those ranges so an ordinary
        # magnitude (a 406.08 revenue figure) never manufactures a spurious 40608.
        if abs(f) <= 1.0:
            _add_roundings(f * 100.0)
        elif abs(f) <= 100.0:
            _add_roundings(f / 100.0)
    return out


def check_grounding(prose: str, evidence: str) -> list[str]:
    """Every substantial number in the report's headline prose must exist in the evidence.

    This used to scan only `**bold**` spans, because the narrator was told to bold the
    decisive figure and bold was therefore the report's own claim of decisiveness. The
    emphasis is gone from the prompts (it reached the reader on nearly every number, which
    is emphasis on none), so keying on it would leave a guard that matches nothing and
    still looks alive — the failure this codebase has hit before, where a check goes blind
    because its key stopped matching.

    Sentences replace bold spans. The SCOPE is unchanged: the caller passes headline +
    executive summary + closing summary, the three fields where a fabricated figure does
    the most damage. If anything this catches more, since a number the model chose NOT to
    bold was never checked before. Compact forms ($2.1M) and tiny integers (list ranks,
    "3 sub-categories") are still skipped — unverifiable or trivially coincidental, and a
    false violation costs a real retry."""
    if not prose or not evidence:
        return []
    have = _evidence_number_set(evidence)
    missing: list[str] = []
    for segment in _SENTENCE_RE.split(prose):
        if _COMPACT_SUFFIX.search(segment):
            continue
        for n in _NUM_RE.findall(segment):
            clean = n.replace(",", "").strip("+-")
            f = _float_or_none(clean) if clean else None
            if f is None or abs(f) < 10:
                continue
            if clean not in have:
                missing.append(segment.strip())
                break
    if not missing:
        return []
    return [
        f"{pitfall(36)} these figures do not appear anywhere in FULL EVIDENCE: "
        + ", ".join(dict.fromkeys(missing[:4]))
        + " — replace each with the evidence's own value or describe it qualitatively."]


#: Claim words a noise-level ranking cannot support. Tight on purpose: each asserts that a
#: named value STANDS OUT, which is exactly what a verdict of "not evidence of a difference"
#: denies. Descriptive language ("the highest shown", "tightly clustered") is untouched,
#: because a narrator saying what the rows contain is not overclaiming.
STANDOUT_CLAIM_RE = re.compile(
    r"\bsignificantl?y?\b|\boutliers?\b|\bbottlenecks?\b|\bdrivers?\b|\bdriving\b|\bdriven by\b"
    r"|\blocalized (?:issue|problem|performance)\b|\bunderperform\w*\b|\bproblem areas?\b", re.I)
#: The same words under a negation are the narrator AGREEING with the verdict — "does not
#: suggest a significant performance issue", "not statistically significant", "no outlier",
#: "insignificant". A live run prepended the verdict to two sentences that already said it,
#: because the scan matched the word and never read the three words before it. Prose that
#: agrees is left as written; only an unnegated claim is corrected.
NEGATED_CLAIM_RE = re.compile(
    r"\b(?:not|no|never|neither|nor|nothing|none|without|isn't|aren't|doesn't|don't|wasn't|"
    r"weren't|cannot|can't|hardly|barely)\b(?:\s+\w+){0,3}\s+"
    r"(?:significantl?y?|outliers?|bottlenecks?|drivers?|driving|driven by|"
    r"localized (?:issue|problem|performance)|underperform\w*|problem areas?)\b"
    r"|\binsignificant\w*\b|\bnon-significant\b", re.I)


def makes_unnegated_standout_claim(text: str) -> bool:
    """True when the prose asserts a standout that its own verdict denies — a claim word
    that is NOT inside a negation. Every negated match is removed first, so what remains
    is only the words used affirmatively."""
    stripped = NEGATED_CLAIM_RE.sub(" ", text or "")
    return bool(STANDOUT_CLAIM_RE.search(stripped))



#: The deterministic verdicts a ranking carries when its own order is not evidence. Matched
#: against `stat_note`, which is written by code (`_ranking_noise_caveat`), never by a model —
#: so this key cannot drift the way a phrase-matching guard on model prose would.
_NOISE_VERDICT_RE = re.compile(
    r"not evidence of a difference|not distinguishable from sampling noise|too small to average",
    re.I)
#: A label short enough to collide with ordinary words is not evidence that the finding was
#: cited. Four characters is where "Ilam" and "Marion" clear and "US"/"NM" do not.
_MIN_LABEL_LEN = 4


def check_noise_findings_not_cited(phases: Any, prose: str) -> list[str]:
    """A standout named in the headline must not come from a ranking the statistics call noise.

    The live specimen: every geographic ranking carried "this ordering is not evidence of a
    difference … the shown groups hold 1–21 records each", the finding-level prose absorbed it
    ("likely driven by low sample sizes"), and the report's own headline still read "driven by
    localized state-level bottlenecks" over `Ilam | 3.2 | 5`. The synthesis was never shown the
    verdicts; now it is, and this verifies that being shown them changed the claim.

    High precision by construction: it fires only on a label that a code-written verdict has
    already flagged, taken from the top rows the narrator would reach for, and only when the
    SENTENCE naming that label makes an unnegated standout claim. The label alone is not
    enough — a live run wrote "delays remain stable, ranging from 0.56 days in South America
    to 0.65 days in Central Asia", a description explicitly framed as stable, and the check
    flagged Central Asia because the name appeared. A correct sentence cannot be retried into
    a different one, so the violation shipped and knocked a right report from HIGH to MEDIUM.
    A label is a word; this check is about claims.
    """
    if not prose:
        return []
    sentences = [s for s in _SENTENCE_RE.split(prose) if s.strip()]
    hits: list[str] = []
    for p in (phases or []):
        if not isinstance(p, dict) or p.get("_hidden"):
            continue
        for f in p.get("findings") or []:
            if not _NOISE_VERDICT_RE.search(str(f.get("stat_note") or "")):
                continue
            for row in (f.get("rows") or [])[:3]:
                if not row:
                    continue
                label = str(row[0]).strip()
                if len(label) < _MIN_LABEL_LEN or _float_or_none(label) is not None:
                    continue
                pat = re.compile(rf"\b{re.escape(label)}\b", re.I)
                if any(pat.search(s) and makes_unnegated_standout_claim(s) for s in sentences):
                    hits.append(label)
    if not hits:
        return []
    return [
        f"{pitfall(11)} the report names " + ", ".join(list(dict.fromkeys(hits))[:4])
        + " as standing out, but the finding each comes from carries a statistical verdict that its "
          "ordering is not evidence of a difference — say what the data supports (no group is "
          "distinguishable) or drop the claim; do not present a noise-level ranking as a driver."]


#: A p-value as the deterministic verdicts write it: "p = 2.376e-155", "p = 0.07168", "p = 1".
_P_VALUE_RE = re.compile(r"\bp\s*=\s*([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)")
#: The report asserting that nothing is statistically distinguishable.
_ASSERTS_NOT_SIGNIFICANT_RE = re.compile(
    r"not\s+(?:statistically\s+)?significant|no\s+(?:statistically\s+)?significant"
    r"|statistically\s+insignificant|\binsignificant\b|p\s*[>≥]\s*0?\.05", re.I)


def check_significance_claims(phases: Any, prose: str) -> list[str]:
    """"Not significant" must not be pressed into service to mean "does not matter".

    The live specimen: the report reached the right conclusion — location does not explain
    shipping delay — and justified it with "variations … are not significant (p > 0.05)"
    while the finding it rests on carries **p = 2.376e-155**. The test is overwhelmingly
    significant and the effect is 1.1% of the variation; those are different statements, and
    collapsing them puts a false claim under a true conclusion, where nobody re-checks it.

    Fires only when the report ASSERTS non-significance and a code-written verdict in the
    same run reports a p-value under 0.05 — so a report that says "significant but
    immaterial", or one whose findings really are all null, is untouched.
    """
    if not prose or not _ASSERTS_NOT_SIGNIFICANT_RE.search(prose):
        return []
    smallest = None
    for p in (phases or []):
        if not isinstance(p, dict) or p.get("_hidden"):
            continue
        for f in p.get("findings") or []:
            for m in _P_VALUE_RE.finditer(str(f.get("stat_note") or "")):
                val = _float_or_none(m.group(1))
                if val is not None and (smallest is None or val < smallest):
                    smallest = val
    if smallest is None or smallest >= 0.05:
        return []
    return [
        f"{pitfall(3)} the report says the differences are not statistically significant, but this run's "
        f"own test reports p = {smallest:.3g} — the difference IS statistically significant "
        f"and too small to act on, which is a different claim. Say that the effect is real "
        f"but immaterial (name the share of variation it explains); do not call it "
        f"insignificant or cite p > 0.05."]


def check_claim_type(claim_type: str, prose: str) -> list[str]:
    """The report may not claim more than its design licences.

    Every other check here catches an overreach after the model committed it, by matching a
    word — and each of those produced a false positive within two live runs. This one is
    different in kind: the licence is decided from the DESIGN before a word is written, the
    prompt states which verbs it admits, and this verifies the contract. Negated uses are
    never overreach, so the honest answer to a causal question — "shipping delay is not
    driven by location" — passes untouched.
    """
    from aughor.agent.claim_type import is_at_least, overreaching_sentences
    if not claim_type or is_at_least(claim_type, "causal"):
        return []
    hits = overreaching_sentences(prose, claim_type)
    if not hits:
        return []
    quoted = "; ".join(f'"{s[:90]}" ({v})' for s, v in hits[:3])
    return [
        f"{pitfall(15)} this analysis licences {claim_type} claims only, but these sentences "
        f"assert more than that: {quoted}. Restate them as what was measured — a relationship "
        f"and its size — or say plainly that the design cannot establish a cause."]


def run_report_checks(synth: Any, question: str, evidence: str, phases: Any = None,
                      claim_type: str = "") -> list[str]:
    """All checks over one synthesis result. Returns violation sentences (empty =
    clean). ``synth`` is the pydantic ADASynthesisModel or anything with the same
    attribute names."""
    def _get(name, default=""):
        v = getattr(synth, name, default)
        return v if v is not None else default

    waterfall = [w.model_dump() if hasattr(w, "model_dump") else dict(w)
                 for w in (_get("attribution_waterfall", []) or [])]
    prose = " ".join(str(_get(f)) for f in
                     ("headline", "executive_summary", "closing_summary"))
    violations: list[str] = []
    violations += check_signs(waterfall)
    violations += check_waterfall_sums(waterfall)
    violations += check_question_addressed(question, prose + " " + " ".join(
        str(g) for g in (_get("data_gaps", []) or [])))
    violations += check_grounding(prose, evidence)
    violations += check_noise_findings_not_cited(phases, prose)
    violations += check_significance_claims(phases, prose)
    violations += check_claim_type(claim_type, prose)
    return violations
