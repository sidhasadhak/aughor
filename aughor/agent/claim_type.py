"""What kind of claim this investigation's design can support — decided once, enforced everywhere.

Seven live runs of one question produced one defect class that no guard retired: the report
asserting more than its design licences. Run 3's headline read *"correlated with geography,
driven by localized state-level bottlenecks"* over a cross-sectional scan of an observational
table; run 7's summary called a p = 2.4e-155 finding "statistically insignificant". Each was
caught after the fact by a word-list, and **every word-list guard produced a false positive
within two runs** — `significant` under a negation, a label named as one end of a stable range.

A claim TYPE is the alternative. It is one value, set once from the design (not from the
prose), and it says which verbs the report may use at all. The model cannot write "driven by"
over an associational design because the sentence shape is refused, rather than because a
regex noticed a word. That retires the whole class instead of catching its members.

The ladder, weakest to strongest:

    descriptive    what the data contains          "X averages 0.57 days"
    associational  X and Y move together           "X varies with Y"
    predictive     X anticipates Y                 "X predicts Y"
    causal         X brings Y about                "X drives Y"

**A table of observations supports `associational` at most.** Getting to `causal` needs an
intervention recorded in the data or an assumption a HUMAN owns and the report states out
loud. A model may never promote its own claim type: inferring causal licence from a
correlation is precisely the failure this module exists to make unwritable.
"""
from __future__ import annotations

import re
from typing import Optional

#: Weakest to strongest. A report may always make a WEAKER claim than its licence.
CLAIM_TYPES = ("descriptive", "associational", "predictive", "causal")
_RANK = {name: i for i, name in enumerate(CLAIM_TYPES)}

#: Verbs that assert one thing BRINGS ABOUT another. Refused below `causal`.
_CAUSAL_VERB_RE = re.compile(
    r"\b(?:caus(?:e|es|ed|ing)|driv(?:e|es|en|ing)|drove|lead(?:s)?\s+to|led\s+to"
    r"|result(?:s|ed)?\s+in|bring(?:s)?\s+about|brought\s+about|produc(?:e|es|ed)"
    r"|trigger(?:s|ed)?|induc(?:e|es|ed)|attributable\s+to|because\s+of"
    r"|due\s+to|responsible\s+for|explains?\s+why|the\s+reason\s+for"
    r"|improv(?:e|es|ed)|worsen(?:s|ed)?|reduc(?:e|es|ed)|increas(?:e|es|ed)"
    r"|decreas(?:e|es|ed)|boost(?:s|ed)?|hurt(?:s)?|stem(?:s|med)?\s+from)\b", re.I)

#: Verbs that assert one thing ANTICIPATES another. Refused below `predictive`.
_PREDICTIVE_VERB_RE = re.compile(
    r"\b(?:predict(?:s|ed|or|ive)?|forecast(?:s|ed)?|anticipat(?:e|es|ed)"
    r"|will\s+(?:be|become|rise|fall|grow|drop)|expect(?:ed)?\s+to)\b", re.I)

#: Verbs that assert two things TRAVEL TOGETHER. Refused below `associational`.
_ASSOCIATIONAL_VERB_RE = re.compile(
    r"\b(?:correlat(?:e|es|ed|ion)|associat(?:e|es|ed|ion)|relat(?:es|ed|ionship)"
    r"|link(?:s|ed)?\s+to|varies\s+with|vary\s+with|depend(?:s|ent)\s+on"
    r"|tied\s+to|goes?\s+with)\b", re.I)

_VERBS_BY_TYPE = {
    "causal": _CAUSAL_VERB_RE,
    "predictive": _PREDICTIVE_VERB_RE,
    "associational": _ASSOCIATIONAL_VERB_RE,
}

#: Negations, so a report SAYING IT FOUND NOTHING is never refused for using the word it is
#: denying. "not correlated with location" is the honest answer to a correlation question and
#: must survive every gate below. Learned four times over in one day: a guard that reads a
#: word without the three words before it convicts the prose that agrees with it.
_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|neither|nor|nothing|none|without|isn'?t|aren'?t|does\s?n'?t|do\s?n'?t"
    r"|was\s?n'?t|were\s?n'?t|cannot|can'?t|hardly|barely|fail(?:s|ed)?\s+to"
    r"|little|minimal|negligible)\b(?:\s+\w+){0,4}\s+", re.I)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def is_at_least(claim_type: Optional[str], minimum: str) -> bool:
    """True when the licence reaches `minimum` on the ladder."""
    return _RANK.get((claim_type or "").strip().lower(), -1) >= _RANK.get(minimum, 99)


def resolve_claim_type(
    *,
    cross_sectional: bool,
    has_time_axis: bool,
    intervention_column: str = "",
    user_assumption: str = "",
    declared: str = "",
) -> tuple[str, str]:
    """The licence this design carries, and one sentence saying why.

    Deterministic on purpose. The intake model may SUGGEST a type via `declared`, but it can
    only ever weaken the result — a model that could promote its own licence would grant
    itself the causal language this module exists to withhold.

    `causal` is reachable two ways, both requiring something outside the model's judgement:
    an intervention/assignment column present in the data, or an assumption the USER wrote,
    which the caller passes verbatim and the report then states as a premise.
    """
    if intervention_column.strip():
        return "causal", (
            f"an intervention is recorded in the data ({intervention_column.strip()}), so a "
            f"causal contrast is identified by the design")
    if user_assumption.strip():
        return "causal", (
            f"the user supplied a causal assumption to work under — \"{user_assumption.strip()}\" "
            f"— which the report states as a premise rather than a finding")

    # Everything below is observational. An observation supports association at most.
    if cross_sectional or not has_time_axis:
        licence, why = "associational", (
            "this is a cross-sectional scan of observational data, which can show that two "
            "things travel together but cannot show that one brings the other about")
    else:
        licence, why = "descriptive", (
            "this is a period-over-period description of observational data, which can say "
            "what changed but not what made it change")

    # A model-declared type may only narrow.
    if declared and _RANK.get(declared.strip().lower(), 99) < _RANK[licence]:
        return declared.strip().lower(), (
            f"{why}; intake narrowed the claim further to {declared.strip().lower()}")
    return licence, why


def admissible_verbs_directive(claim_type: str, why: str) -> str:
    """The one line the narrator and synthesis prompts carry. Not a lecture — the contract
    that `check_claim_type` verifies, stated once so the model can satisfy it."""
    if is_at_least(claim_type, "causal"):
        return (
            "CLAIM LICENCE: causal — " + why + ". Causal language is permitted; still name "
            "the assumption or the design feature that licences it in the same sentence.")
    if is_at_least(claim_type, "predictive"):
        return (
            "CLAIM LICENCE: predictive — " + why + ". You may say one thing PREDICTS or "
            "ANTICIPATES another. You may NOT say it causes, drives, leads to, results in, "
            "improves, reduces or is responsible for anything.")
    if is_at_least(claim_type, "associational"):
        return (
            "CLAIM LICENCE: associational — " + why + ". You may say two things are "
            "correlated, associated, related, or vary together, and you may quantify how "
            "much. You may NOT say one causes, drives, leads to, results in, explains why, "
            "improves, reduces, or is responsible for the other, and you may NOT call any "
            "value a driver, a bottleneck or a root cause. Report the relationship and its "
            "size; leave the mechanism to the reader.")
    return (
        "CLAIM LICENCE: descriptive — " + why + ". Report what the data contains and how it "
        "changed. You may NOT assert that anything causes, drives, predicts or is correlated "
        "with anything else; no relationship was tested.")


def overreaching_sentences(prose: str, claim_type: str) -> list[tuple[str, str]]:
    """(sentence, verb) for each sentence claiming more than the licence allows.

    Negated uses are never overreach: "shipping delay is NOT driven by location" is the
    honest answer to a causal question and the sentence a good report writes. Only the
    affirmative use of a verb above the licence is returned.
    """
    if not prose or not claim_type:
        return []
    forbidden = [(name, rx) for name, rx in _VERBS_BY_TYPE.items()
                 if not is_at_least(claim_type, name)]
    if not forbidden:
        return []
    out: list[tuple[str, str]] = []
    for sentence in _SENTENCE_RE.split(prose):
        stripped = _NEGATION_RE.sub(" ", sentence)
        for _name, rx in forbidden:
            m = rx.search(stripped)
            if m:
                out.append((sentence.strip(), m.group(0)))
                break
    return out
