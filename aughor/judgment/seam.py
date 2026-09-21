"""JD-1 — the judgment seam: a typed question is not a paragraph.

`judge(state, questions) -> answers`. One call per bundle over the EXISTING providers; each
question carries its own CLOSED schema; answers come back keyed by question id, each with a
probability. Three question kinds, after TypeSafe's Jev:

* :class:`Noul`   — the probability a proposition is true.
* :class:`Choice` — exactly one of a closed set of options.
* :class:`Score`  — a position on 2-10 ORDERED levels.

**Closed means the model cannot answer outside the set.** Each question becomes a field of a
response model built for this bundle, and a choice or score is a sub-model with ONE probability
field per option or level — so there is no field in which to name an option that does not exist,
and the model has to weigh every option rather than name one. The answer is the highest-weighted
option, read back in code. That is the half of Jev this repo can have today on its own providers.

**The probability is STATED, not measured.** The provider exposes no token probabilities
(`logprobs` appears nowhere in the tree, JD-4 found), so each answer's probability is a number
the model is asked for in the schema. That is not calibration — it is the input calibration is
measured ON, and `evals/judgment_battery_eval.py` (JD-4) is the instrument that says whether it
means anything. Nothing here may treat it as more than that.

**Not wired into any production path.** JD-1's receipt is "the same bundle answered through the
seam and through today's path agree on the golden set", and its falsifier is "if isolation
changes no answer and saves no call, it is ceremony — drop it". Both need model calls, which are
the operator's spend. So the seam ships with :func:`agreement`, which takes that receipt in one
call from two sets of answers, and the first consumer (JD-3's semops cascade, by the roadmap)
adopts it behind a flag once the receipt says it earns its place. A flag registered before
anything reads it would gate nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Union

from pydantic import BaseModel, Field, create_model

NOUL, CHOICE, SCORE = "noul", "choice", "score"

MIN_LEVELS, MAX_LEVELS = 2, 10


@dataclass(frozen=True)
class Noul:
    """How likely is ``proposition`` to be true, given the state."""
    id: str
    proposition: str


@dataclass(frozen=True)
class Choice:
    """Which ONE of ``options`` answers ``question``, given the state."""
    id: str
    question: str
    options: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError(f"{self.id}: a choice needs at least two options")
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"{self.id}: options must be distinct")


@dataclass(frozen=True)
class Score:
    """Where ``question`` sits on ``levels``, which are ORDERED lowest first."""
    id: str
    question: str
    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        if not MIN_LEVELS <= len(self.levels) <= MAX_LEVELS:
            raise ValueError(f"{self.id}: a score needs {MIN_LEVELS}-{MAX_LEVELS} levels")
        if len(set(self.levels)) != len(self.levels):
            raise ValueError(f"{self.id}: levels must be distinct")


Question = Union[Noul, Choice, Score]


@dataclass(frozen=True)
class Answer:
    """One question's answer — or, when ``available`` is False, the reason there is none.

    ``probability`` is the model's STATED probability for ``value`` (see the module note), and
    ``distribution`` is its stated probability per option or level, normalised to sum to 1. An
    unavailable answer carries no value and must carry its reason: "the model said 0.0" and "the
    call failed" are different answers and are never the same bytes.
    """
    id: str
    kind: str
    available: bool
    value: Any = None
    probability: Optional[float] = None
    distribution: Mapping[str, float] = field(default_factory=dict)
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.available and not self.reason.strip():
            raise ValueError(f"{self.id}: an unavailable answer must carry its reason")
        if self.available and self.probability is None:
            raise ValueError(f"{self.id}: an available answer must carry its probability")


def _field_for(q: Question):
    """The closed schema for one question, as a pydantic field."""
    if isinstance(q, Noul):
        return (float, Field(..., ge=0.0, le=1.0,
                             description=f"Probability, 0-1, that this is TRUE: {q.proposition}"))
    names = q.options if isinstance(q, Choice) else q.levels
    kind = "option" if isinstance(q, Choice) else "level"
    # One probability per option/level, keyed p0..pN in declared order (option text is not a
    # safe field name) — so the model has to weigh every option instead of naming one, and has
    # no field in which to name one that is not in the set.
    fields = {f"p{i}": (float, Field(..., ge=0.0, le=1.0, description=f"probability of {n!r}"))
              for i, n in enumerate(names)}
    sub = create_model(f"Q_{q.id}", **fields)
    order = ", ".join(f"p{i}={n!r}" for i, n in enumerate(names))
    ordered = " The levels are ORDERED lowest first." if isinstance(q, Score) else ""
    return (sub, Field(..., description=f"{q.question} Give a probability for each {kind} "
                                        f"({order}).{ordered}"))


def _response_model(questions: Sequence[Question]) -> type[BaseModel]:
    return create_model("JudgmentBundle", **{q.id: _field_for(q) for q in questions})


def _prompt(state: str, questions: Sequence[Question]) -> str:
    lines = [
        "Answer each question below INDEPENDENTLY, using only the STATE. Do not let one "
        "question's answer influence another's. Every number is a probability from 0 to 1.",
        "", "STATE:", state or "(empty)", "", "QUESTIONS:",
    ]
    for q in questions:
        if isinstance(q, Noul):
            lines.append(f"- {q.id} [true/false]: {q.proposition}")
        elif isinstance(q, Choice):
            lines.append(f"- {q.id} [choose one]: {q.question} Options: {list(q.options)}")
        else:
            lines.append(f"- {q.id} [ordered scale]: {q.question} Levels, lowest first: "
                         f"{list(q.levels)}")
    return "\n".join(lines)


def _normalise(raw: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in raw.values())
    if total <= 0:
        return {}
    return {k: max(0.0, float(v)) / total for k, v in raw.items()}


def _read(q: Question, got: Any) -> Answer:
    if isinstance(q, Noul):
        p = float(got)
        return Answer(q.id, NOUL, True, value=p >= 0.5, probability=p if p >= 0.5 else 1 - p,
                      distribution={"true": p, "false": 1 - p})
    names = q.options if isinstance(q, Choice) else q.levels
    dist = _normalise({n: getattr(got, f"p{i}") for i, n in enumerate(names)})
    if not dist:
        return Answer(q.id, CHOICE if isinstance(q, Choice) else SCORE, False,
                      reason="every stated probability was zero, so there is no answer to read")
    best = max(names, key=lambda n: dist[n])  # ties break by declared order
    return Answer(q.id, CHOICE if isinstance(q, Choice) else SCORE, True, value=best,
                  probability=dist[best], distribution=dist)


def judge(state: str, questions: Sequence[Question], *, provider=None,
          system: str = "You answer typed questions about a state. Answer each independently."
          ) -> dict[str, Answer]:
    """Answer a bundle of typed questions about one state in ONE call.

    Never raises on a failed CALL; raises ``ValueError`` on misuse (duplicate or non-identifier
    question ids), which is a bug in the caller, not a runtime condition.

    "One call" is the seam's request. A response that fails the schema triggers the provider's
    own bounded repair retry — a second call — as it does for every structured call in the
    platform; count calls at the provider, not here, when measuring what the seam saves.

    A failed call makes every answer unavailable with the reason, rather than raising or
    guessing: a caller that gets an unavailable answer knows to fall back, and one that got an
    exception mid-bundle would lose the answers that were fine.
    """
    qs = list(questions)
    ids = [q.id for q in qs]
    if not qs:
        return {}
    # Misuse raises; a failed CALL never does. Ids become field names in the response model.
    if len(set(ids)) != len(ids):
        raise ValueError("question ids must be unique within a bundle")
    bad = [i for i in ids if not str(i).isidentifier()]
    if bad:
        raise ValueError(f"question ids must be identifiers (they become schema fields): {bad}")
    try:
        if provider is None:
            from aughor.llm.provider import get_provider
            provider = get_provider("coder")
        bundle = provider.complete(system=system, user=_prompt(state, qs),
                                   response_model=_response_model(qs))
    except Exception as exc:  # noqa: BLE001 — a failed bundle is an answer, not a crash
        return {q.id: Answer(q.id, _kind(q), False, reason=f"the judgment call failed: {exc}")
                for q in qs}
    return {q.id: _read(q, getattr(bundle, q.id)) for q in qs}


def _kind(q: Question) -> str:
    return NOUL if isinstance(q, Noul) else CHOICE if isinstance(q, Choice) else SCORE


def agreement(today: Mapping[str, Any], seam: Mapping[str, Answer]) -> dict:
    """JD-1's receipt, in one call: how often the seam's answers match today's path.

    ``today`` maps a question id to the value today's path produced; ``seam`` is what
    :func:`judge` returned. Questions the seam could not answer are counted as unanswered, NOT
    as disagreements — an unavailable answer is not a wrong one, and folding it in would make a
    flaky call look like a different opinion. The falsifier ("if isolation changes no answer and
    saves no call, it is ceremony") needs this number beside the calls saved, which the caller
    counts because only it knows how many calls today's path made.
    """
    shared = [k for k in today if k in seam]
    answered = [k for k in shared if seam[k].available]
    agreed = [k for k in answered if seam[k].value == today[k]]
    return {
        "compared": len(shared),
        "answered": len(answered),
        "unanswered": len(shared) - len(answered),
        "agreed": len(agreed),
        "agreement": (len(agreed) / len(answered)) if answered else None,
        "disagreements": {k: {"today": today[k], "seam": seam[k].value}
                          for k in answered if k not in agreed},
    }


__all__ = ["Noul", "Choice", "Score", "Answer", "judge", "agreement", "NOUL", "CHOICE", "SCORE"]
