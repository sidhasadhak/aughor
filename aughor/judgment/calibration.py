"""CP-2 — what the shadow corpus can be calibrated on, and what it cannot.

Arc CP's CP-2 was drafted as "run the battery, publish an ECE for the treatment Choice and
the three Scores". Building it showed that clause to be wrong, and this module is the
correction rather than a quieter version of the original.

**ECE needs a correctness label, and most of these levers have none.** Expected calibration
error asks: among predictions made with confidence about *p*, what fraction were right? That
question is unanswerable without knowing which were right. For `treatment` there is no such
fact — "how much work this ask deserved" is a judgement, not an observable, and nothing in a
run records it.

**And the obvious substitute is a trap.** `ran` — what the path actually did — is sitting
right there in every row, and scoring the judged treatment against it would produce a
confident-looking number. It would also be meaningless: Arc CP's census measured that the
current path chooses `deep_analysis` **0 times in 60 tool uses**, so agreement with `ran`
measures how well the judge reproduces a baseline already known to be broken. A judge that
scored 100% against it would be worthless, and one that scored 40% might be right. That is
why `agreed` is recorded as the arc's FALSIFIER — "is there any decision here to take" —
and never as its accuracy.

**Two levers are self-labelling, because the run answers them itself.** `steps_implied`
predicts how many queries a careful analyst would run, and the turn then runs some: `grids`
is a real number the prediction can be wrong against. `from_last_result` predicts that no
new query is needed, and a turn that ran none has confirmed it. Those two get a real ECE
from a real label, for free, with no model call and no human.

The rest get an honest **UNAVAILABLE with its own reason**, which is the posture JD-4's
battery already takes and the first thing an instrument owes anybody: *a number emitted here
would be a number somebody schedules work against.*

Nothing here calls a model or opens a warehouse. It folds rows.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

#: Ten bins, as JD-4's battery uses — kept identical so the two instruments' numbers can sit
#: in one table without a footnote about binning.
BINS = 10

#: Why a lever cannot be calibrated from the run alone. Stated per lever, because the reasons
#: genuinely differ and a single "no ground truth" would hide that two of them are one
#: labelling session away while two others are not.
NO_LABEL: dict[str, str] = {
    "treatment": ("no observable says which treatment an ask DESERVED. `ran` is not that "
                  "fact: the path it records picks `deep_analysis` 0 times in 60 tool uses, "
                  "so agreement with it measures fidelity to a broken baseline. Needs "
                  "human labels on a sample."),
    "intent": ("describe / compare / diagnose / forecast / act is a reading of the ask, and "
               "nothing in the run records which it was. Needs human labels — cheap ones, "
               "since the ask text is right there."),
    "specificity": ("whether the ask named measure, grain, window and filter is checkable by "
                    "a person in seconds but by nothing in the run. Needs human labels."),
    "stakes": ("how far a wrong answer would have travelled is counterfactual — the answer "
               "was not wrong, so nothing observed it travelling. Not labellable after the "
               "fact at all; it would have to be declared per destination instead."),
    "causal": ("whether an ask is asking WHY is a reading of the text. Needs human labels."),
    "governed_metric": ("checkable in principle against the metric store, but not from the "
                        "run: the row records no resolved metric id. Becomes labellable if "
                        "the turn records which metric it grounded on."),
    "follow_up": ("whether the ask depended on the previous turn needs the session's prior "
                  "turn, which the shadow row does not carry today."),
}


def _bucket(p: float) -> int:
    return min(BINS - 1, max(0, int(float(p) * BINS)))


def _ece(pairs: Iterable[tuple[float, bool]]) -> Optional[dict]:
    """Expected calibration error over :data:`BINS`, and the bins themselves.

    ``pairs`` is (stated confidence, was it right). Returns None for an empty corpus rather
    than 0.0 — a perfect score over no predictions is the most misleading number this module
    could produce.
    """
    rows = [(float(p), bool(ok)) for p, ok in pairs if p is not None]
    if not rows:
        return None
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(BINS)]
    for p, ok in rows:
        bins[_bucket(p)].append((p, ok))
    n = len(rows)
    ece = 0.0
    detail = []
    for i, b in enumerate(bins):
        if not b:
            continue
        conf = sum(p for p, _ in b) / len(b)
        acc = sum(1 for _, ok in b if ok) / len(b)
        ece += (len(b) / n) * abs(acc - conf)
        detail.append({"bin": i, "n": len(b), "confidence": round(conf, 4),
                       "accuracy": round(acc, 4)})
    return {"ece": round(ece, 4), "n": n, "bins": detail}


def _steps_label(row: Mapping[str, Any]) -> Optional[bool]:
    """Was `steps_implied` right, judged against the queries the turn actually ran?

    The levels are ("none", "one", "two or three", "four to six", "more than six"), so the
    prediction is a RANGE and the label is whether the observed count fell inside the band
    the weighted position rounds to. A band, not an exact match: predicting 2.6 when the
    turn ran three queries is a good prediction, and scoring it wrong would make the
    calibration number a measure of the scale's granularity rather than of the judge.
    """
    observed = row.get("observed_grids")
    pos = row.get("steps_implied_score")
    if observed is None or pos is None:
        return None
    bands = [(0, 0), (1, 1), (2, 3), (4, 6), (7, 10**6)]
    idx = min(len(bands) - 1, max(0, int(round(float(pos)))))
    lo, hi = bands[idx]
    return lo <= int(observed) <= hi


def _from_last_result_label(row: Mapping[str, Any]) -> Optional[bool]:
    """Was `from_last_result` right? The turn either ran a query or it did not."""
    observed = row.get("observed_grids")
    predicted = row.get("from_last_result")
    if observed is None or predicted is None:
        return None
    return bool(predicted) == (int(observed) == 0)


#: The levers the run itself can score, and how.
LABELLERS = {"steps_implied": _steps_label, "from_last_result": _from_last_result_label}


def calibrate(rows: Iterable[Mapping[str, Any]]) -> dict:
    """Fold shadow rows into a calibration report.

    Every lever appears in the output. The two the run can label carry an ECE; the rest
    carry their own reason for having none, because a report that silently omitted them
    would read as "these were fine".
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    out: dict[str, Any] = {"rows": len(rows), "levers": {}}

    for lever, label_of in LABELLERS.items():
        pairs = []
        for r in rows:
            ok = label_of(r)
            p = r.get(f"{lever}_p")
            if ok is not None and p is not None:
                pairs.append((p, ok))
        got = _ece(pairs)
        out["levers"][lever] = (
            {"available": True, **got} if got else
            {"available": False,
             "reason": ("no row carried both a stated probability and an observable "
                        "outcome — the corpus is empty, or the shadow ran without "
                        "`observed`")})

    for lever, why in NO_LABEL.items():
        out["levers"][lever] = {"available": False, "reason": why}

    # The arc's falsifier, beside the calibration rather than in a second report: if the
    # judged treatment agrees with what ran on essentially every ask, there is no decision
    # here to take and the arc's second movement is ceremony.
    decided = [r for r in rows if r.get("agreed") is not None]
    out["falsifier"] = {
        "rows_with_a_treatment": len(decided),
        "agreed_with_what_ran": sum(1 for r in decided if r["agreed"]),
        "agreement": (sum(1 for r in decided if r["agreed"]) / len(decided)) if decided else None,
        "reading": ("agreement near 1.0 means the judge reproduces today's routing and the "
                    "arc stops here; it is NOT an accuracy score — see this module's note on "
                    "why `ran` cannot serve as a label"),
    }
    return out


__all__ = ["BINS", "LABELLERS", "NO_LABEL", "calibrate"]
