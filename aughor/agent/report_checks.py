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
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
#: Compact forms ("$2.1M", "480K") are legitimate roundings of evidence values this
#: module cannot cheaply verify — grounding skips them rather than crying wolf.
_COMPACT_SUFFIX = re.compile(r"[\d.]\s*[KMBkmb]\b")


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
        f"the question makes a specific numeric claim ({', '.join(q_nums[:3])}) and the "
        "report never mentions it — confirm the figure, correct it with the measured "
        "value, or state plainly that the premise does not hold."]


def _evidence_number_set(evidence: str) -> set[str]:
    """Every number in the evidence, normalised (commas stripped), plus common
    roundings (0–2 decimals) so '406.083' grounds a written '406.08'."""
    out: set[str] = set()
    for n in _NUM_RE.findall(evidence or ""):
        clean = n.replace(",", "").strip("+-")
        if not clean or clean == ".":
            continue
        out.add(clean)
        f = _float_or_none(clean)
        if f is None:
            continue
        for dp in (0, 1, 2):
            out.add(f"{f:.{dp}f}".rstrip("0").rstrip(".") or "0")
            out.add(f"{abs(f):.{dp}f}".rstrip("0").rstrip(".") or "0")
    return out


def check_grounding(bold_texts: str, evidence: str) -> list[str]:
    """Every **bold** number in the report's prose must exist in the evidence.

    Bold is the report's own claim of decisiveness ('bold marks numbers already
    traceable to the evidence'), which makes it the honest scope for a cheap check:
    compact forms ($2.1M) and tiny integers (list ranks, '3 sub-categories') are
    skipped — unverifiable or trivially coincidental, and a false violation costs a
    real retry."""
    if not bold_texts or not evidence:
        return []
    have = _evidence_number_set(evidence)
    missing: list[str] = []
    for segment in _BOLD_RE.findall(bold_texts):
        if _COMPACT_SUFFIX.search(segment):
            continue
        for n in _NUM_RE.findall(segment):
            clean = n.replace(",", "").strip("+-")
            f = _float_or_none(clean) if clean else None
            if f is None or abs(f) < 10:
                continue
            if clean not in have:
                missing.append(f"**{segment.strip()}**")
                break
    if not missing:
        return []
    return [
        "these bolded figures do not appear anywhere in FULL EVIDENCE: "
        + ", ".join(dict.fromkeys(missing[:4]))
        + " — replace each with the evidence's own value or describe it qualitatively."]


def run_report_checks(synth: Any, question: str, evidence: str) -> list[str]:
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
    return violations
