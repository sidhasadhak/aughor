"""The wandering detector (Wave R3) — a deterministic brake on an exploration that has
stopped learning.

An exploration wave plans a sub-question, writes SQL, runs it, and spends a model call
interpreting the result. When a chain loses the thread it does not crash: it keeps doing
exactly that, productively-looking, until the iteration cap stops it. Three shapes, and a
counter that sees only the first is the reason the other two run to the cap:

* **repeat** — the planner emits SQL this run already executed. Free-tier models do this
  most, because a weaker planner re-derives the obvious query from the same schema. Cheap
  to catch and the only one that can be caught *before* dispatch.
* **no progress** — different SQL, byte-identical result, several steps running. The chain
  is rephrasing one question. A repeat counter cannot see this at all.
* **churn** — many *distinct* queries collapsing onto a handful of distinct results. The
  opposite failure: maximum variety, no convergence. A streak counter cannot see this
  either, because no two consecutive steps match.

Everything here is deterministic and reads only what the run already recorded
(``query_history``), so it needs no new state channel, races with nothing, and a parallel
wave branch can consult it on its own thread.

The detector never *decides* anything on its own — it returns a :class:`Verdict` and the
caller chooses. That matters because the honest response differs by signal: a repeat can
be answered from the prior result with no query and no model call, while churn is only
grounds for ending the wave early, never for suppressing a step's evidence.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

#: How many consecutive distinct-SQL / identical-result steps count as "no progress".
#: Two is a coincidence — a landscape query and its ORDER BY variant legitimately agree.
#: Three is a pattern.
NO_PROGRESS_STREAK = 3

#: Churn: at least this many completed queries before the spread is even meaningful.
CHURN_MIN_QUERIES = 6

#: …and at most this many DISTINCT results among them. Six queries that produced two
#: distinct answers is a chain circling, not a chain covering ground.
CHURN_MAX_DISTINCT_RESULTS = 2

#: A run may be vetoed this many times before the wave is ended gracefully. A veto is
#: cheap and occasionally right; a run that keeps earning them is not going to recover.
MAX_VETOES = 3

#: Marker written into a vetoed result's ``caveats``. Prefix-matched, so the human-readable
#: remainder can change without breaking detection.
VETO_MARKER = "wandering:"


@dataclass(frozen=True)
class Verdict:
    """What the detector saw. ``kind`` is "" when nothing is wrong."""

    kind: str = ""            # "" | "repeat" | "no_progress" | "churn"
    detail: str = ""          # human- and model-readable explanation
    prior_step: str = ""      # the step this repeats, when known

    @property
    def wandering(self) -> bool:
        return bool(self.kind)


# ── fingerprints ──────────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
_TRAILING_SEMI = re.compile(r";\s*$")


def args_fingerprint(sql: str) -> str:
    """A stable fingerprint for "this is the same query".

    Tries sqlglot first so formatting, alias case and whitespace cannot make one query
    look like two — the planner re-emits the same intent with different indentation
    constantly, and a raw string compare would miss most real repeats.

    Falls back to a normalized string when parsing fails. The fallback is deliberately
    *conservative*: it collapses whitespace and case only. A fingerprint that is too
    eager would veto a genuinely new query, and suppressing real evidence is a much worse
    failure than paying for one redundant one.

    Note that ``comments=False`` means two queries differing ONLY by a SQL comment are the
    same query here. That is intended — a comment cannot change what a query computes, so
    re-running it really is a repeat — but it is worth knowing when reading a measurement:
    a benchmark whose "distinct" queries vary only in a trailing comment will report a
    dedup rate that is entirely an artifact of its own fixture.
    """
    text = _TRAILING_SEMI.sub("", (sql or "").strip())
    if not text:
        return ""
    try:
        import sqlglot

        normalized = sqlglot.parse_one(text).sql(normalize=True, pretty=False, comments=False)
    except Exception:
        normalized = _WS_RE.sub(" ", text).lower()
    return hashlib.sha256(normalized.encode("utf-8", "replace")).hexdigest()[:16]


def result_fingerprint(columns: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    """A stable fingerprint for "this is the same answer".

    Column names are included: the same numbers under different headings are a different
    answer to a reader, and a chain that renamed its output did make progress.
    """
    h = hashlib.sha256()
    h.update("\x1f".join(str(c) for c in (columns or [])).encode("utf-8", "replace"))
    for row in (rows or []):
        h.update(b"\x1e")
        h.update("\x1f".join(str(v) for v in (row or [])).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


# ── reading the run's own history ─────────────────────────────────────────────

def _usable(results: Iterable[Any]) -> list[Any]:
    """Results that represent real executed evidence — no errors, and not our own vetoes.

    Excluding vetoes is load-bearing: a veto echoes the prior result verbatim, so counting
    it would make every veto look like fresh confirmation of no-progress and cascade the
    detector into terminating a healthy run.
    """
    out = []
    for r in results or []:
        if getattr(r, "error", None):
            continue
        if is_veto(r):
            continue
        out.append(r)
    return out


def is_veto(result: Any) -> bool:
    """True when ``result`` is a synthetic echo this detector produced."""
    return any(str(c).startswith(VETO_MARKER) for c in (getattr(result, "caveats", None) or []))


def find_repeat(sql: str, history: Iterable[Any]) -> Optional[Any]:
    """The earlier result that ran this same SQL, or None.

    Errored attempts are excluded on purpose: re-running a query that failed is how a
    repair *works*, and vetoing it would break the repair path outright.
    """
    fp = args_fingerprint(sql)
    if not fp:
        return None
    for prior in _usable(history):
        if args_fingerprint(getattr(prior, "sql", "")) == fp:
            return prior
    return None


def check_before_dispatch(sql: str, history: Iterable[Any]) -> Verdict:
    """The pre-dispatch check. Only ``repeat`` can be decided here — the other two signals
    need a result, and by then the query and its model call are already spent."""
    prior = find_repeat(sql, history)
    if prior is None:
        return Verdict()
    step = getattr(prior, "hypothesis_id", "") or "an earlier step"
    return Verdict(
        kind="repeat",
        detail=(f"This query is identical to the one already run for {step}. "
                f"Re-running it cannot produce new evidence, so the earlier result is "
                f"reused verbatim and this step adds nothing new to the analysis."),
        prior_step=step,
    )


def check_progress(history: Iterable[Any], *,
                   streak: int = NO_PROGRESS_STREAK,
                   churn_min: int = CHURN_MIN_QUERIES,
                   churn_max_distinct: int = CHURN_MAX_DISTINCT_RESULTS) -> Verdict:
    """The post-execution check over the whole run: no-progress streak, then churn.

    Streak is checked first because it is the more specific claim — a run can satisfy both,
    and "the last three steps returned the same thing" tells an operator more than "the run
    is not converging".
    """
    usable = _usable(history)
    if len(usable) < min(streak, churn_min):
        return Verdict()

    fps = [result_fingerprint(getattr(r, "columns", []), getattr(r, "rows", [])) for r in usable]

    tail = fps[-streak:]
    if len(tail) == streak and len(set(tail)) == 1:
        sqls = {args_fingerprint(getattr(r, "sql", "")) for r in usable[-streak:]}
        if len(sqls) > 1:      # identical SQL is a `repeat`, a different and cheaper story
            return Verdict(
                kind="no_progress",
                detail=(f"The last {streak} queries were different but returned identical "
                        f"results. The chain is rephrasing one question rather than "
                        f"advancing; further steps along this line will not add evidence."),
            )

    if len(usable) >= churn_min and len(set(fps)) <= churn_max_distinct:
        return Verdict(
            kind="churn",
            detail=(f"{len(usable)} queries have produced only {len(set(fps))} distinct "
                    f"result(s). The exploration is covering ground without converging; "
                    f"the remaining planned steps are unlikely to change the picture."),
        )

    return Verdict()


def veto_count(history: Iterable[Any]) -> int:
    """How many steps this run has already had vetoed."""
    return sum(1 for r in (history or []) if is_veto(r))


def should_terminate(history: Iterable[Any], *, max_vetoes: int = MAX_VETOES) -> Verdict:
    """Whether the wave should end gracefully rather than plan another round.

    'Gracefully' is the whole point: the caller routes to synthesis with everything
    gathered so far, so a wandering run still produces its answer. Nothing is discarded
    and nothing raises — the alternative (running to the iteration cap) reaches the same
    synthesis having spent a model call per redundant step to get there.
    """
    vetoes = veto_count(history)
    if vetoes >= max_vetoes:
        return Verdict(kind="repeat",
                       detail=(f"{vetoes} steps were vetoed as repeats of queries already "
                               f"run. The planner is circling; synthesizing what we have."))
    return check_progress(history)


# ── the explanatory synthetic result ──────────────────────────────────────────

def veto_result(step_id: str, sql: str, prior: Any, verdict: Verdict):
    """The result a vetoed step returns instead of executing.

    It carries the PRIOR result's columns and rows verbatim, so nothing downstream loses
    data — it is, after all, the same query, and a zero-row stand-in would trip every
    "suspicious empty result" heuristic we have and read as a finding of absence. What it
    adds is a caveat naming the step it duplicates, which is what makes the duplication
    visible in the trust receipt instead of silently absorbed.
    """
    from aughor.platform.contracts.execution import QueryResult

    return QueryResult(
        hypothesis_id=step_id,
        sql=sql,
        columns=list(getattr(prior, "columns", []) or []),
        rows=[list(r) for r in (getattr(prior, "rows", []) or [])],
        row_count=int(getattr(prior, "row_count", 0) or 0),
        error=None,
        stats=list(getattr(prior, "stats", []) or []),
        caveats=[f"{VETO_MARKER} {verdict.detail}"],
    )
