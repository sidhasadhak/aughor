"""Counted confidence — the Record's third law made a number (the 2027 study §B and §G; phase 1,
P1-4).

A claim's confidence is never what its author felt; it is how often claims like it have been
right, counted: ``{reference_class, hit_rate, n}``. Two classes can be counted today because the
platform already measures them without a judge:

- **answers re-checked** — the daily re-check (`answer/recheck.py`) re-runs each recent chat
  answer's own query and records on the answer whether the numbers held. A hit is an answer whose
  measured re-checks never found a change past the noise band. This is the class of an
  OBSERVATION booked from a chat answer.
- **stated causes challenged** — a deep analysis that names a cause records what became of the
  one check that could refute it (`causal_checks.refutation`: survived · refuted · not run). A hit
  is a cause that survived. This is the class of a deep analysis's observation and findings.

A third counts itself once outcomes arrive: **predictions scored** — a hit is a prediction whose
outcome fell inside its band.

Each class is counted on the claim's own connection first; below :data:`MIN_N` it widens to every
connection and says so; below :data:`MIN_N` there too, the hit rate is NOT shown — the figure is
"too few to count", with the count. A hit rate shown without its *n* is the thing this module
exists to refuse. Filled on READ (`with_confidence`), never written: the ledger row carries no
number, so a count that grows tomorrow is right tomorrow.
"""
from __future__ import annotations

from typing import Optional

from aughor.record import claims as _claims

#: Below this many cases a hit rate is not shown — the study's own threshold (§W, phase 1 metrics:
#: "reference classes with n ≥ 30").
MIN_N = 30

RECHECKED = "answers re-checked"
CHALLENGED = "stated causes challenged"
PREDICTED = "predictions scored"
ALL = "all connections"


def _tally(name: str, connection_id: Optional[str]) -> tuple[int, int]:
    """``(n, hits)`` for a class on a connection (None = every connection)."""
    if name == RECHECKED:
        from aughor.db.history import recheck_tallies
        return recheck_tallies(connection_id=connection_id)
    if name == CHALLENGED:
        from aughor.db.history import challenge_tallies
        return challenge_tallies(connection_id=connection_id)
    if name == PREDICTED:
        scored = [c for c in _claims.list_claims(kind="prediction", state="scored", conn_id=connection_id,
                                                 limit=5000)]
        return len(scored), sum(1 for c in scored if c.extra.get("scored_against") == "inside")
    raise ValueError(f"no reference class named {name!r}")


def count_class(name: str, *, connection_id: Optional[str] = None) -> _claims.Confidence:
    """The class counted: on the connection when it has enough cases, else across every connection
    (said in ``scope``); the hit rate withheld, with the count, below :data:`MIN_N`."""
    n, hits = _tally(name, connection_id) if connection_id else (0, 0)
    scope = connection_id or ALL
    if n < MIN_N:
        n_all, hits_all = _tally(name, None)
        if connection_id and n_all > n:
            n, hits, scope = n_all, hits_all, ALL
        elif not connection_id:
            n, hits = n_all, hits_all
    if n < MIN_N:
        return _claims.Confidence(reference_class=name, hit_rate=None, n=n, scope=scope,
                                  note=f"too few to count: {n} case{'s' if n != 1 else ''} of the {MIN_N} needed")
    return _claims.Confidence(reference_class=name, hit_rate=round(hits / n, 3), n=n, scope=scope,
                              note=f"{hits} of {n} held" + ("" if scope != ALL or not connection_id else
                                                            "; counted across every connection, this one has too few"))


def reference_class_of(claim: _claims.Claim) -> Optional[str]:
    """Which class counts this claim, or None when none does yet."""
    from aughor.kernel.ledger import CHAT_ANSWER_KIND, DEEP_REPORT_KIND
    if claim.kind == "prediction":
        return PREDICTED
    receipt_kind = str(claim.extra.get("receipt_kind") or "")
    if claim.kind == "observation" and receipt_kind == CHAT_ANSWER_KIND:
        return RECHECKED
    if claim.kind == "observation" and receipt_kind == DEEP_REPORT_KIND:
        return CHALLENGED
    if claim.kind in ("finding", "hypothesis", "cause") and claim.extra.get("investigation_id"):
        return CHALLENGED
    return None


def why_uncounted(claim: _claims.Claim) -> str:
    return (f"no reference class counts a claim of kind '{claim.kind}'"
            + (f" booked from a '{claim.extra.get('receipt_kind')}' receipt" if claim.extra.get("receipt_kind") else "")
            + " yet; nothing is shown rather than a number nobody counted")


def counted(claim: _claims.Claim) -> Optional[_claims.Confidence]:
    name = reference_class_of(claim)
    if name is None:
        return None
    conn = claim.about.key if claim.about.kind == "connection" and claim.about.key else None
    return count_class(name, connection_id=conn)


def with_confidence(claim: _claims.Claim) -> _claims.Claim:
    """The claim as the reader should see it: confidence filled by the counter, on a copy — the
    ledger row stays without one, and the door still refuses a writer that sets it."""
    out = claim.model_copy(deep=True)
    try:
        out.confidence = counted(claim)
    except Exception as exc:  # noqa: BLE001 — a count that cannot be read shows nothing, never a stale number
        from aughor.kernel.errors import tolerate
        tolerate(exc, "counted confidence could not be read; the claim shows none",
                 counter="record.confidence")
        out.confidence = None
    return out
