"""The perturbation-brittleness axis — does a meaning-preserving rewording change the answer?

Pass rate says whether a pipeline is right. It says nothing about whether it is right *for a
reason*. A suite can sit at 65% because it genuinely understands 65% of the questions, or
because it pattern-matches phrasings and would fall apart if a user typed the same question
slightly differently. Those are very different products and the same number.

REFRACT measures this with a model judging whether two answers agree, which imports the
judge's own noise into the measurement. Aughor does not need to: an eval answer is
**executed SQL**, so two answers can be compared by their result sets, deterministically, with
the comparator this repo already trusts (`user_agents.quality.results_match` —
order-insensitive, float-normalised, tolerant of extra columns). Same result set ⇒ zero
drift, decided by arithmetic rather than by a second opinion.

**The load-bearing constraint is that a perturbation must preserve meaning.** If a rewording
changes what was asked, a different answer is *correct*, and scoring it as brittleness would
manufacture a defect. That makes the perturbation set the most dangerous part of this module,
not the comparison — so the set is deliberately tiny, every entry carries the argument for
why it is meaning-preserving, and anything requiring a synonym table or a paraphrase model is
excluded on purpose. A brittleness score is only as honest as its weakest perturbation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from aughor.kernel.errors import tolerate


@dataclass(frozen=True)
class Perturbation:
    """One meaning-preserving rewriting, and the argument that it is one."""

    name: str
    apply: Callable[[str], str]
    rationale: str

    def __call__(self, question: str) -> str:
        return self.apply(question)


def _drop_trailing_punctuation(q: str) -> str:
    return q.rstrip().rstrip("?.!") or q


def _add_question_mark(q: str) -> str:
    body = q.rstrip()
    return body if body.endswith("?") else body + "?"


#: The default set. Every entry changes only surface form: capitalisation, whitespace,
#: terminal punctuation, or a courtesy wrapper. None substitutes a word, reorders a clause,
#: or touches a quantity, entity, or time expression — the four things that would change what
#: was asked. Extending this set is a measurement decision, not a refactor: a perturbation
#: that alters meaning converts a correct answer into a recorded brittleness.
DEFAULT_PERTURBATIONS: tuple[Perturbation, ...] = (
    Perturbation(
        "lowercase", lambda q: q.lower(),
        "Natural-language questions carry no meaning in capitalisation; a user typing in "
        "lower case is asking the identical question."),
    Perturbation(
        "trailing_punctuation", _drop_trailing_punctuation,
        "A question mark is optional in a search box. Removing it removes no information."),
    Perturbation(
        "question_mark", _add_question_mark,
        "The inverse of the above, so brittleness is not an artefact of which form the "
        "case happened to be authored in."),
    Perturbation(
        "whitespace", lambda q: q.replace(" ", "  "),
        "Doubled interior spaces read identically to a human and carry no constraint, but a "
        "pipeline that string-matches, hashes or caches on the raw question will notice."),
    Perturbation(
        "courtesy_suffix", lambda q: q.rstrip() + " Thanks!",
        "A trailing courtesy adds no constraint. Deliberately a SUFFIX: a prefix like "
        "'Please tell me ' composes ungrammatically with a question that is already an "
        "imperative ('Please tell me show me all the orders'), and a degraded input that "
        "confuses a model would be scored as brittleness the perturbation itself caused."),
)


@dataclass
class Brittleness:
    """How one case's answer survived rewording.

    ``measurable`` is separate from ``score`` on purpose: a case whose ORIGINAL run errored
    has no answer for a perturbation to differ from, so it is unmeasured rather than
    maximally brittle. Scoring it 0.0 would let a broken baseline masquerade as a fragile one.
    """

    case_id: str = ""
    measurable: bool = True
    reason: str = ""
    total: int = 0
    drifted: int = 0
    errored: int = 0
    details: list = field(default_factory=list)

    @property
    def score(self) -> Optional[float]:
        """1.0 = every rewording produced the same result set; 0.0 = every one changed it."""
        if not self.measurable or not self.total:
            return None
        return 1.0 - (self.drifted / self.total)

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "measurable": self.measurable,
                "reason": self.reason, "total": self.total, "drifted": self.drifted,
                "errored": self.errored,
                "score": None if self.score is None else round(self.score, 4),
                "details": self.details}


def _default_comparator(a: Any, b: Any) -> bool:
    from aughor.custom_agents.quality import results_match
    return results_match(a, b)


def brittleness(case: Any, target: Callable[[Any], Any], *,
                perturbations: Sequence[Perturbation] = DEFAULT_PERTURBATIONS,
                comparator: Optional[Callable[[Any, Any], bool]] = None) -> Brittleness:
    """Run ``case`` and each rewording of it, and report how often the answer changed.

    ``target`` is the same ``Target`` the suite runner uses, so brittleness measures the real
    answer path rather than a re-implementation of it. The case is copied per perturbation
    (``dataclasses.replace``-style, by shallow construction) so the original is never mutated
    — a mutated case would silently poison every later measurement in the run.
    """
    compare = comparator or _default_comparator
    out = Brittleness(case_id=getattr(case, "id", "") or "")

    original_question = getattr(case, "question", "") or ""
    if not original_question.strip():
        out.measurable = False
        out.reason = ("the case carries no natural-language question, so there is nothing to "
                      "reword — brittleness is undefined for a SQL-only case.")
        return out

    try:
        base = target(case)
    except Exception as exc:
        out.measurable = False
        out.reason = f"the unperturbed run raised {type(exc).__name__}: {exc}"
        tolerate(exc, "brittleness: baseline run failed; case unmeasured",
                 counter="evals.brittleness.baseline_failed")
        return out

    if getattr(base, "error", ""):
        out.measurable = False
        out.reason = (f"the unperturbed run errored ({base.error[:120]}), so there is no "
                      f"answer for a rewording to differ from. Unmeasured, not brittle.")
        return out

    for p in perturbations:
        reworded = p(original_question)
        if reworded == original_question:
            # A no-op rewriting is not evidence of robustness and must not inflate the score.
            out.details.append({"perturbation": p.name, "skipped": "no-op on this question"})
            continue
        variant = _with_question(case, reworded)
        if variant is None:
            out.details.append({"perturbation": p.name,
                                "skipped": "case shape will not carry a reworded question"})
            continue
        out.total += 1
        try:
            obs = target(variant)
        except Exception as exc:
            out.drifted += 1
            out.errored += 1
            out.details.append({"perturbation": p.name, "drifted": True,
                                "error": f"{type(exc).__name__}: {exc}"})
            continue
        if getattr(obs, "error", ""):
            # A meaning-preserving rewording that breaks the pipeline IS brittleness — the
            # answer changed from rows to no answer, which is the largest change available.
            out.drifted += 1
            out.errored += 1
            out.details.append({"perturbation": p.name, "drifted": True,
                                "error": obs.error[:200]})
            continue
        same = False
        try:
            same = bool(compare(base.rows, obs.rows))
        except Exception as exc:
            tolerate(exc, "brittleness: comparator failed; counted as drift",
                     counter="evals.brittleness.compare_failed")
        if not same:
            out.drifted += 1
        out.details.append({"perturbation": p.name, "drifted": not same,
                            "sql": (getattr(obs, "sql", "") or "")[:200]})
    return out


def _with_question(case: Any, question: str) -> Optional[Any]:
    """A copy of ``case`` carrying ``question``, or ``None`` if the shape will not take one.

    ``dataclasses.replace`` would be the obvious tool, but cases are duck-typed throughout
    the evals package (that is what lets one runner measure /ask, a headless investigation
    and a SQL replay), so this stays shape-agnostic and falls back to a shallow copy.

    Returning ``None`` rather than the original case is load-bearing. Handing the unperturbed
    case back would re-run the baseline question and score the identical result as a
    *survived* perturbation — silently inflating robustness on exactly the unusual case types
    where the rewriting could not be applied.
    """
    import copy
    import dataclasses

    if dataclasses.is_dataclass(case):
        try:
            return dataclasses.replace(case, question=question)
        except Exception as exc:
            tolerate(exc, "brittleness: replace() rejected the case; trying a shallow copy",
                     counter="evals.brittleness.replace_failed")
    try:
        clone = copy.copy(case)
        clone.question = question
        return clone
    except Exception as exc:
        tolerate(exc, "brittleness: case shape will not carry a reworded question; skipped",
                 counter="evals.brittleness.unrewritable")
        return None


def suite_robustness(cases: Sequence[Any], target: Callable[[Any], Any], *,
                     perturbations: Sequence[Perturbation] = DEFAULT_PERTURBATIONS,
                     comparator: Optional[Callable[[Any, Any], bool]] = None,
                     ) -> tuple[Optional[float], list]:
    """Mean robustness over the cases that could be measured, plus the per-case detail.

    Returns ``(None, details)`` when no case was measurable — an axis nobody could measure is
    absent, not zero, the same discipline `fidelity.axis_of` applies to `accuracy`.
    """
    details = [brittleness(c, target, perturbations=perturbations, comparator=comparator)
               for c in cases]
    scores = [b.score for b in details if b.score is not None]
    mean = (sum(scores) / len(scores)) if scores else None
    return mean, details
