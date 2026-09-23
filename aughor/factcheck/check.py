"""Idea 7 · every number in a document, checked against the warehouse.

How a claim is checked. The document is split into the clauses that state a number (the
departure gate's own splitter, so a fact-check and a Slack send agree on what "a claim"
is); years, dates and counts of things ("3 regions") are not claims. Each clause is then
put to the platform's own quick answer path (`answer_core` — the pipeline behind `/ask`:
metric grounding, SQL generation, execution, the guard battery, a Trust Receipt per
answer) as the question "what is the actual figure for this claim?". The number the
warehouse returns is compared with the number the document wrote AT THE PRECISION IT WAS
WRITTEN (`numeral_matches_measure`, the same matcher the departure gate uses); a percentage
is also tried against a ratio. The verdict says why, and the SQL rides the provenance.

The semantic compiler was the first design — typed intent → grounded SQL, one cheap call —
and on theLook it mapped NONE of four plain claims (nor a plain question) to an intent, so
every claim came back "unchecked". A checker that cannot check is not honest either; the
answer path is what the platform trusts for its own numbers, so it is what checks
everyone else's. The cost is real and stated: one quick-answer turn per claim (a few model
calls, ~10 s), capped at `CHECK_CAP` claims per document, and always on a person's ask.

What is honestly unchecked, and says so: a claim the pipeline could not turn into one
number (a table came back, or nothing), a query that failed, an abstention.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from aughor.answer.envelope import AnswerEnvelope, Grid, Provenance
from aughor.explorer.grounding import Numeral, extract_numerals, numeral_matches_measure

logger = logging.getLogger(__name__)

#: A memo's first N claims are checked; the rest are named, not silently dropped.
CHECK_CAP = 25

#: What one check reads: the figure, the SQL that produced it, and what got in the way.
@dataclass
class Measurement:
    value: Optional[float] = None
    sql: str = ""
    rows: int = 0
    note: str = ""
    error: str = ""


Measure = Callable[[str], Measurement]

MEASURED, CONTRADICTED, UNCHECKED = "measured", "contradicted", "unchecked"


@dataclass
class Claim:
    text: str
    numerals: list[Numeral] = field(default_factory=list)

    @property
    def said(self) -> str:
        return ", ".join(n.text for n in self.numerals)


@dataclass
class ClaimVerdict:
    claim: str
    said: str
    verdict: str
    why: str
    measured: Optional[float] = None
    sql: str = ""


# ── the claims ───────────────────────────────────────────────────────────────────


def _is_year(n: Numeral) -> bool:
    return not n.suffix and n.decimals == 0 and 1900.0 <= float(n.value) <= 2100.0


def claims_in(text: str) -> list[Claim]:
    """The clauses of ``text`` that assert a measurement: a numeral with a magnitude suffix
    (K/M/B), a currency, a percent, or a number of at least a thousand. "3 regions", a year
    and a date are not claims a warehouse can confirm."""
    from aughor.govern.departure import numeric_clauses
    out: list[Claim] = []
    for clause in numeric_clauses(text or ""):
        nums = [n for n in extract_numerals(clause) if not _is_year(n)]
        kept = [n for n in nums if n.enforce or n.suffix == "%"]
        if kept:
            out.append(Claim(text=clause, numerals=kept))
    return out


# ── the measurer: the platform's own quick answer path ───────────────────────────


def claim_question(clause: str) -> str:
    return (f"According to the data, what is the actual figure for this claim: "
            f"\"{clause.strip()}\"? Answer with the single number for the period the claim names.")


def default_measurer(connection_id: str, schema_name: Optional[str] = None,
                     session_id: str = "") -> Measure:
    """`answer_core` bound to this connection — the real quick-answer pipeline, headless.
    Every check files under ``session_id`` (the fact-check's own id) so each claim's
    answer, SQL and Trust Receipt are one conversation in the history."""

    def measure(question: str) -> Measurement:
        from aughor.routers.investigations import answer_core
        res = answer_core(question, connection_id, [], emit=lambda *_a, **_k: None,
                          session_id=session_id, skip_clarify=True, assumed_default=True,
                          schema_scope=schema_name, surface="factcheck")
        error = str(getattr(res, "error", "") or "")
        sql = str(getattr(res, "sql", "") or "")
        rows = list(getattr(res, "rows", None) or [])
        caveats = [str(c) for c in (getattr(res, "caveats", None) or []) if c]
        note = "; ".join(caveats)[:200]
        if error:
            return Measurement(error=error[:160], sql=sql, note=note)
        if not sql or not rows:
            headline = str(getattr(res, "headline", "") or "")
            return Measurement(sql=sql, rows=len(rows), note=note or headline[:160])
        if len(rows) != 1:
            return Measurement(sql=sql, rows=len(rows), note=note)
        return Measurement(value=_first_number(rows), sql=sql, rows=1, note=note)

    return measure


# ── one claim ────────────────────────────────────────────────────────────────────


def _as_float(v) -> Optional[float]:
    """A cell as a number, or None — a label column is not a failure, just not a number."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _first_number(rows: list) -> Optional[float]:
    for r in rows[:1]:
        vals = list(r.values()) if isinstance(r, dict) else list(r)
        for v in vals:
            f = _as_float(v)
            if f is not None:
                return f
    return None


def _matches(n: Numeral, value: float) -> bool:
    if numeral_matches_measure(n, value):
        return True
    # A percentage written as "12%" against a ratio the definition returns as 0.12.
    return n.suffix == "%" and numeral_matches_measure(n, value * 100.0)


def check_claim(claim: Claim, *, measure: Measure) -> ClaimVerdict:
    try:
        m = measure(claim_question(claim.text))
    except Exception as exc:  # noqa: BLE001 — one claim's failure is its own verdict
        return ClaimVerdict(claim.text, claim.said, UNCHECKED, f"the check failed: {str(exc)[:120]}")
    if m.error:
        return ClaimVerdict(claim.text, claim.said, UNCHECKED, f"the query failed: {m.error}",
                            sql=m.sql)
    if m.value is None:
        if m.rows > 1:
            why = f"the data answered with {m.rows} rows, not one number"
        elif m.sql:
            why = "the query returned no number"
        else:
            why = "the platform could not turn the claim into a query" + (f" — {m.note}" if m.note else "")
        return ClaimVerdict(claim.text, claim.said, UNCHECKED, why, sql=m.sql)
    value = m.value
    caveat = f" (caveat: {m.note})" if m.note else ""
    hits = [n for n in claim.numerals if _matches(n, value)]
    if hits:
        return ClaimVerdict(claim.text, claim.said, MEASURED,
                            f"{hits[0].text} is what the data shows ({value:,.2f}){caveat}",
                            measured=value, sql=m.sql)
    closest = min(claim.numerals, key=lambda n: abs(float(n.value) - value))
    said_v = float(closest.value)
    value_cmp = value * 100.0 if (closest.suffix == "%" and abs(value) <= 1.0) else value
    rel = abs(said_v - value_cmp) / max(abs(value_cmp), 1e-9)
    return ClaimVerdict(claim.text, claim.said, CONTRADICTED,
                        f"said {closest.text}; the data shows {value:,.2f} ({rel:.0%} off){caveat}",
                        measured=value, sql=m.sql)


# ── the document ─────────────────────────────────────────────────────────────────


def factcheck(text: str, connection_id: str, *, schema_name: Optional[str] = None,
              measure: Optional[Measure] = None, cap: int = CHECK_CAP,
              source: str = "text") -> AnswerEnvelope:
    """Every numeric claim in ``text``, checked — as an answer envelope, filed as a turn."""
    claims = claims_in(text)
    checked, beyond = claims[:cap], claims[cap:]
    inv_id = uuid.uuid4().hex[:12]
    if measure is None:
        measure = default_measurer(connection_id, schema_name, session_id=f"factcheck:{inv_id}")
    verdicts = [check_claim(c, measure=measure) for c in checked]

    n = len(verdicts)
    counts = {v: sum(1 for x in verdicts if x.verdict == v) for v in (MEASURED, CONTRADICTED, UNCHECKED)}
    if n == 0:
        headline = "No numeric claims to check: nothing in the text states a measurement."
    else:
        headline = (f"{n} numeric claim{'s' if n != 1 else ''}: {counts[MEASURED]} match the data, "
                    f"{counts[CONTRADICTED]} contradicted, {counts[UNCHECKED]} could not be checked.")
    lines = []
    for v in verdicts:
        if v.verdict == CONTRADICTED:
            lines.append(f"- CONTRADICTED — \"{v.claim.strip()}\": {v.why}.")
    if beyond:
        lines.append(f"- {len(beyond)} further claim{'s' if len(beyond) != 1 else ''} beyond the cap of "
                     f"{cap} were not checked.")
    body = "\n".join(lines)
    caveats: list[str] = []
    if counts[CONTRADICTED]:
        caveats.append("A contradicted claim is measured with the approved definition and the window the "
                       "sentence names; the document may have used another.")
    if counts[UNCHECKED]:
        caveats.append(f"{counts[UNCHECKED]} claim{'s' if counts[UNCHECKED] != 1 else ''} could not be "
                       f"checked — each row says why; an approved definition makes a metric checkable.")
    grid = Grid(columns=["claim", "said", "measured", "verdict", "why"],
                rows=[[v.claim.strip(), v.said, v.measured, v.verdict, v.why] for v in verdicts]) if verdicts else None
    env = AnswerEnvelope(
        question=f"fact-check ({source}): {(text or '').strip()[:160]}",
        headline=headline, body=body, grid=grid, chart=None, caveats=caveats,
        provenance=Provenance(investigation_id=inv_id, connection_id=connection_id, mode="factcheck",
                              sql=[v.sql for v in verdicts if v.sql]),
    )
    try:
        from aughor.db.history import attach_envelope
        attach_envelope(inv_id, env.model_dump())
    except Exception as exc:  # noqa: BLE001 — the check is the answer; filing it is best-effort
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a fact-check that could not be filed is still returned", counter="factcheck.file")
    return env
