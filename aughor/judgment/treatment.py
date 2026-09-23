"""CP-1 — what treatment an ask earns, as a typed judgement rather than a tool the model picks.

Today the quick/deep split is a tool in the roster: the model may call `deep_analysis`
(`agent/converse_tools.py`) or not. Measured on 2026-09-23 for Arc CP's census, across 25
agentic turns and 60 tool uses, it picked it **zero times** — and `fast_path_turns` is
literally `total - converse` (`obs/session_log.py`), a residual rather than a decision. So
the split is not being made badly on the interactive path. It is not being made.

This module names the criteria instead, as the three primitives the seam types. It decides
NOTHING yet: CP-1 is shadow-only, CP-2 calibrates, and CP-3 is the first wave in which a
treatment changes what runs. That order is the arc's, and it exists because every
probability this platform produces is STATED by a model rather than measured from token
probabilities — `judgment/seam.py` says so about itself — and nothing routes on a number
the battery has not yet weighed.

**Two rules shape the bundle.**

*Classify only what is uncertain.* Where the answer is going, who asked, which connection is
in play and whether a prior turn exists are all KNOWN at call time. Asking a model to infer
a fact already in hand buys nothing and adds a way to be wrong, so the state carries those
as context and the QUESTIONS are only about the ask itself.

*Ask everything at once.* A Jev bundle is evaluated in parallel and its latency scales with
tokens rather than question count, so nine levers cost about what one does. Adding a lever
speculatively is cheap; a round trip per lever would not be.

**And it runs after the answer, never in front of it.** `shadow` is called once a turn has
settled, so a shadow experiment cannot add latency to a real answer or fail one. That is
also why it swallows everything: an experiment that can break a turn is not an experiment.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from aughor.judgment.seam import Answer, Choice, Noul, Score, judge

logger = logging.getLogger(__name__)

#: The event this wave writes. `/obs/route-mix` already folds `session_events` into the
#: quick/deep picture; the shadow rows land in the same substrate so the comparison is one
#: query over one table rather than a second store to reconcile.
TREATMENT_SHADOW = "treatment_shadow"

#: The flag. OFF by default and it must stay that way until someone decides to spend: a
#: classification is a MODEL CALL per settled turn, so switching this on starts spending on
#: every ask. That is the whole point of the wave — the corpus cannot be backfilled — but it
#: is the operator's money and therefore the operator's switch.
SHADOW_FLAG = "judgment.shadow_treatment"


# ── the levers ───────────────────────────────────────────────────────────────────────────

#: THE decision. Named to match Adaptive-RAG's collapse (no-retrieval / single-step /
#: multi-step) mapped onto what this platform actually has: a lookup answers from what is
#: already known, a single query writes one SQL, a multi-query joins several, and an
#: investigation runs the hypothesis loop that costs ~4x a chat turn (80,752 vs 20,242
#: tok/run, measured 2026-09-18).
TREATMENT = Choice(
    id="treatment",
    question=("How much work does answering this ask honestly require? Choose the SMALLEST "
              "treatment that could answer it completely."),
    options=("lookup", "single_query", "multi_query", "investigation"),
)

#: Intent, because it is what earns depth. A `diagnose` ask is the one that justifies the
#: hypothesis loop; an `act` belongs to the approval gate rather than to the answer path,
#: and routing it as an answer is how a request to DO something becomes a paragraph about it.
INTENT = Choice(
    id="intent",
    question="What is this ask FOR?",
    options=("describe", "compare", "diagnose", "forecast", "act"),
)

#: Does the ask name what it wants? The four levels are cumulative on purpose, so the scale
#: is ordered and a weighted position between two of them means something.
SPECIFICITY = Score(
    id="specificity",
    question=("How completely does the ask name what it wants — the measure, the grain, the "
              "time window and any filter?"),
    levels=("names none of them", "names the measure only",
            "names the measure and one more", "names all four"),
)

#: The budget, directly. A weighted position is wanted here rather than a rounded level:
#: 1.4 is a different budget from 2, which is why `Answer.score` exists.
STEPS_IMPLIED = Score(
    id="steps_implied",
    question="How many distinct queries would a careful analyst run to answer this?",
    levels=("none — it is already known", "one", "two or three", "four to six", "more than six"),
)

#: What being wrong costs, which sets both how much is said and how strictly the gate holds.
#: Adopted 2026-09-23 (§6 item 31 (d)): this may TIGHTEN a departure gate and never loosen
#: one — a score that could relax a safeguard would put the gate under the judgement of the
#: thing it exists to check.
STAKES = Score(
    id="stakes",
    question="If this answer were wrong, how far would the error travel before anyone caught it?",
    levels=("a private thread", "a team channel", "a scheduled post nobody is watching",
            "a document that leaves the company"),
)

#: The four cheap gates. Each maps to something the platform already does with the answer:
#: a causal ask needs a claim licence at the departure gate, an ungoverned metric is what
#: CB-5's `missing` hold is about, an ask answerable from the last result is the cheapest
#: exit there is, and a follow-up composes on state already in the thread.
CAUSAL = Noul(id="causal",
              proposition="The ask is asking WHY something happened, not only what happened.")
GOVERNED_METRIC = Noul(id="governed_metric",
                       proposition="The ask names a business metric by a defined name "
                                   "(such as revenue, churn or AOV) rather than describing "
                                   "a calculation in its own words.")
FROM_LAST_RESULT = Noul(id="from_last_result",
                        proposition="This ask could be answered from the rows already "
                                    "shown earlier in this conversation, with no new query.")
FOLLOW_UP = Noul(id="follow_up",
                 proposition="The ask depends on the previous turn to make sense — it "
                             "continues that question rather than starting a new one.")

#: The bundle, in one call.
LEVERS: tuple[Any, ...] = (TREATMENT, INTENT, SPECIFICITY, STEPS_IMPLIED, STAKES,
                           CAUSAL, GOVERNED_METRIC, FROM_LAST_RESULT, FOLLOW_UP)


def state_for(question: str, *, prior_turn: str = "") -> str:
    """The state the levers are judged against.

    The ask, plus the previous turn when there is one — `from_last_result` and `follow_up`
    are unanswerable without it, and a bundle that asks an unanswerable question gets a
    confident-looking guess rather than an abstention. Nothing else: the connection, the
    destination and the asker are known to the caller, and a lever that re-infers a known
    fact is a lever that can be wrong about it.
    """
    ask = (question or "").strip() or "(empty ask)"
    if not prior_turn.strip():
        return f"THE ASK:\n{ask}\n\nThere is no previous turn — this starts the conversation."
    return f"PREVIOUS TURN:\n{prior_turn.strip()}\n\nTHE ASK:\n{ask}"


def classify(question: str, *, prior_turn: str = "", provider=None) -> dict[str, Answer]:
    """Judge every lever for one ask, in one bundle. Never raises — `judge` turns a failed
    call into unavailable answers carrying their reason, which is what a caller needs in
    order to record that the classification did not happen rather than that it said nothing.
    """
    return judge(state_for(question, prior_turn=prior_turn), LEVERS, provider=provider)


def as_row(answers: Mapping[str, Answer]) -> dict:
    """The levers flattened for a log row: value, and for a score its continuous position.

    Confidence travels with every lever because CP-2 calibrates ON it and CP-3 escalates on
    it — a row that recorded only the winning value would be a corpus you cannot measure
    calibration against, which is the entire purpose of collecting it.
    """
    row: dict[str, Any] = {}
    for qid, a in answers.items():
        if not a.available:
            row[qid] = None
            row[f"{qid}_unavailable"] = a.reason[:120]
            continue
        row[qid] = a.value
        row[f"{qid}_p"] = round(float(a.probability or 0.0), 4)
        if a.score is not None:
            row[f"{qid}_score"] = round(float(a.score), 3)
    return row


def shadow(question: str, *, ran: str, prior_turn: str = "", conn_id: str = "",
           provider=None, answers: Optional[Mapping[str, Answer]] = None) -> Optional[dict]:
    """Record what this ask WOULD have been routed to, beside what actually ran.

    Returns the row it wrote, or None when it wrote nothing — off, or the emit is disabled.
    Call it once a turn has SETTLED: the classification is a model call, and putting one in
    front of a user's answer to collect data for a future wave would be paying for the
    experiment in the one currency the experiment is meant to save.

    Everything is swallowed. A shadow experiment that can fail a turn is not a shadow
    experiment, and the corpus is worth exactly nothing if collecting it breaks answers.
    """
    try:
        from aughor.kernel.flags import flag_enabled
        if not flag_enabled(SHADOW_FLAG):
            return None
        got = answers if answers is not None else classify(
            question, prior_turn=prior_turn, provider=provider)
        row = as_row(got)
        row["ran"] = ran
        # The comparison this corpus exists for, computed once at write time so the falsifier
        # ("the shadow agrees with what ran on essentially every ask, so there is no decision
        # here to take") is one fold over one column rather than a join per read.
        row["agreed"] = (row.get("treatment") == ran) if row.get("treatment") else None
        from aughor.obs.session_log import emit
        emit(TREATMENT_SHADOW, name="treatment_shadow", conn_id=conn_id or None, payload=row)
        return row
    except Exception as exc:  # noqa: BLE001 — see the docstring; a shadow never costs a turn
        logger.debug("treatment shadow skipped: %s", exc)
        return None


__all__ = ["LEVERS", "SHADOW_FLAG", "TREATMENT_SHADOW", "as_row", "classify", "shadow",
           "state_for"]
