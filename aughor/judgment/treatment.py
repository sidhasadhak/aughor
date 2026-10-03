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


#: The TIER each treatment is served by, in the vocabulary of what serves a turn. Three of
#: the four are one tier: a lookup, a single query and a multi-query are all answered by the
#: light bodies (the fast path, or the conversation's tool loop), and only an investigation
#: earns the analyst. Until 2026-10-04 `agreed` compared the treatment's own words with the
#: door's depth ("multi_query" against "deep"), two vocabularies that share no member: on the
#: live corpus it read 0 of 109 and could never have read anything else, so the arc's
#: falsifier could not fire.
TIER_FOR = {"lookup": "light", "single_query": "light", "multi_query": "light",
            "investigation": "heavy"}


def observed_for_trace(trace_id: str) -> dict:
    """What a turn DID, read from its own session events — the label two levers are scored on.

    The count used to be taken off the answer's stream: one per `columns` frame. The stream's
    wrapper parses only the frames its sniff list names, `columns` was never on it, and so the
    count was 0 on every row the shadow ever wrote — 111 of 111 on the live install, measured
    2026-10-04, with the calibration reading an ECE of 0.88 off a label that was a constant.
    The comment beside it said nothing persisted the number. Since TJ-2 something does: every
    loop step is a `step` event under the run's trace, and every statement a `sql.execute`.

    ``queries`` is the number of deliberate queries: a loop step that returned rows, or one of
    the analyst's own investigation tools (each is a measured slice). A turn with no loop —
    the fast path — writes one statement by construction, so it is 1 when a statement ran.
    ``statements`` is everything that reached the warehouse, guards and repairs included.
    ``body`` is which body served: the analyst, the conversation, or the fast path.

    Returns ``{}`` when the trace cannot be read, so a row is left unlabelled rather than
    labelled zero.
    """
    if not trace_id:
        return {}
    try:
        from aughor.agent.analyst import INVESTIGATION_TOOLS
        from aughor.kernel.ledger import Ledger
        events = Ledger.default().session_events(trace_id=trace_id, limit=5000, ascending=True)
    except Exception as exc:  # noqa: BLE001 — an unreadable trace is an unlabelled row
        logger.debug("the turn's trace could not be read: %s", exc)
        return {}
    if not events:
        return {}
    names = {(e.get("kind"), e.get("name")) for e in events}
    steps = [e for e in events if e.get("kind") == "step"]
    statements = sum(1 for e in events
                     if e.get("kind") == "tool_call" and e.get("name") == "sql.execute")
    if steps:
        queries = sum(1 for e in steps
                      if e.get("row_count") is not None or e.get("name") in INVESTIGATION_TOOLS)
    else:
        queries = 1 if statements else 0
    body = ("analyst" if ("tool_call", "ask.analyst") in names
            else "converse" if ("tool_call", "ask.converse") in names else "quick")
    return {"queries": queries, "statements": statements, "body": body}


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
           observed: Optional[Mapping[str, Any]] = None,
           provider=None, answers: Optional[Mapping[str, Answer]] = None) -> Optional[dict]:
    """Record what this ask WOULD have been routed to, beside what actually ran.

    Returns the row it wrote, or None when it wrote nothing — off, or the emit is disabled.
    Call it once a turn has SETTLED: the classification is a model call, and putting one in
    front of a user's answer to collect data for a future wave would be paying for the
    experiment in the one currency the experiment is meant to save.

    ``observed`` is what the turn ACTUALLY did — the run's own facts, written into the same
    row as the prediction. It is here rather than in the analysis because it cannot be
    recovered afterwards: `grids` is counted off frames as they stream past and nothing
    persists that count. Two levers become self-labelling because of it (`steps_implied` has
    a real number to be wrong against, `from_last_result` a real "did any query run"), which
    is the difference between a corpus that can be calibrated and one that can only be
    described. See `judgment/calibration.py` for which levers that does and does not reach.

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
        from aughor import telemetry
        seen = {**observed_for_trace(telemetry.current_trace_id() or ""), **(observed or {})}
        for k, v in seen.items():
            row[f"observed_{k}"] = v
        # The comparison this corpus exists for, computed once at write time so the falsifier
        # ("the shadow agrees with what ran on essentially every ask, so there is no decision
        # here to take") is one fold over one column rather than a join per read.
        row["agreed"] = agreed(row)
        from aughor.obs.session_log import emit
        emit(TREATMENT_SHADOW, name="treatment_shadow", conn_id=conn_id or None, payload=row)
        return row
    except Exception as exc:  # noqa: BLE001 — see the docstring; a shadow never costs a turn
        logger.debug("treatment shadow skipped: %s", exc)
        return None


def served_tier(row: Mapping[str, Any]) -> Optional[str]:
    """The tier that served the turn: heavy for the analyst or a deep investigation, light for
    the fast path and the conversation. None when the row does not say which body ran."""
    body = row.get("observed_body")
    if not body:
        return None
    return "heavy" if body == "analyst" or row.get("observed_investigation") else "light"


def agreed(row: Mapping[str, Any]) -> Optional[bool]:
    """Did the judged treatment name the tier that served the turn? None when either is unknown."""
    judged = TIER_FOR.get(str(row.get("treatment") or ""))
    served = served_tier(row)
    if judged is None or served is None:
        return None
    return judged == served


def shadow_corpus(*, limit: int = 5000, org_id: Optional[str] = None) -> list[dict]:
    """The shadow rows, each with what its turn did.

    A row written before 2026-10-04 carries the dead stream count and no body. While its
    trace is still in the log (the log keeps 14 days) the turn's facts are read from it here,
    and agreement is taken again in the one vocabulary; once the trace is gone the row stays
    unlabelled. A row that already carries ``observed_queries`` is returned as written.
    """
    from aughor.kernel.ledger import Ledger
    out: list[dict] = []
    newest = Ledger.default().session_events(kind=TREATMENT_SHADOW, limit=limit, org_id=org_id)
    for ev in reversed(newest):
        row = dict(ev.get("payload") or {})
        if "observed_queries" not in row:
            for k, v in observed_for_trace(str(ev.get("trace_id") or "")).items():
                row[f"observed_{k}"] = v
            row["agreed"] = agreed(row)
        row["at"] = ev.get("at")
        out.append(row)
    return out


__all__ = ["LEVERS", "SHADOW_FLAG", "TIER_FOR", "TREATMENT_SHADOW", "agreed", "as_row",
           "classify", "observed_for_trace", "served_tier", "shadow", "shadow_corpus",
           "state_for"]
