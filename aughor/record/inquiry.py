"""The Inquiry — the durable object a deep analysis runs inside (the 2027 study §G and §I; phase 2,
P2-1), and the typed verdict every run books (§H "Failure"; P2-3).

A deep analysis today is a RUN: it produces a report and ends. An inquiry outlives its runs. It
holds the question, who opened it (a person · a monitor · a restated claim · a review), the runs
that worked it with their verdicts, the hypotheses as CLAIMS with their state (open · supported ·
refuted · abandoned), what it established, what it could not settle and what would settle it, its
state (open · waiting · closed) and the date it wakes without being asked. A refuted hypothesis
stays in the ledger: it is memory, read before the next run on the same connection proposes its
own, and a hypothesis already refuted is refused — recorded on the inquiry, said in the report.

Measured before this was written (the study §N): every hypothesis's verdict was saved in
``investigations.hypotheses_json`` and nothing ever read it back.

Kernel artifact kinds ``inquiry`` and ``run_verdict`` — no new store. The run itself stays the
``investigations`` row (its persisted name); the inquiry is booked beside it from the two places
every run already passes: `db/history.py::complete_investigation` and `::fail_investigation`.

Every run books a typed verdict, never an empty result: ``answered`` · ``contradicted`` ·
``no_data`` · ``no_definition`` · ``withheld`` · ``out_of_budget`` · ``tool_failed`` — so a
failure and a true negative never read alike (:func:`classify_failure` is code over the reason
the caller recorded; a reason it cannot place is ``tool_failed`` with the reason kept).
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from aughor.record import claims as _claims

KIND = "inquiry"
RUN_VERDICT_KIND = "run_verdict"

State = Literal["open", "waiting", "closed"]
#: The typed verdicts (the study §H). ``answered`` and ``contradicted`` are a completed run's;
#: the rest are the ways a run can end without an answer.
VERDICTS: tuple[str, ...] = ("answered", "contradicted", "no_data", "no_definition", "withheld",
                             "out_of_budget", "tool_failed")
#: How far back refuted hypotheses on a connection are memory for the next run.
REFUTED_MEMORY_DAYS = 90
#: Two hypotheses are the same claim when their content words overlap this far (Jaccard).
SAME_HYPOTHESIS = 0.5
#: An inquiry on the same subject opened this recently and not closed is woken, not doubled.
REOPEN_WITHIN_DAYS = 14
#: When no settling lag is learned, a waiting inquiry wakes after this many days.
DEFAULT_WAKE_DAYS = 7


class OpenItem(BaseModel):
    what: str
    settled_by: str = ""        # what would settle it; "" is said as unstated by the report


class Lesson(BaseModel):
    believed: str
    turned_out: str


class RunNote(BaseModel):
    run: str                    # the investigation id
    verdict: str                # one of VERDICTS
    why: str = ""
    at: str = ""


class Inquiry(BaseModel):
    question: str
    subject: str = ""           # the normalised object the question is about
    connection_id: str = ""
    opened_by: str = ""         # person:<id> | monitor:<id> | restated:<claim id> | review | mission:<id>
    hypotheses: list[str] = Field(default_factory=list)    # hypothesis claim ids
    runs: list[RunNote] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)        # what it established (claim ids)
    open: list[OpenItem] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    state: State = "open"
    waiting_for: str = ""       # days to settle | an owner | a decision
    closed_as: str = ""         # answered | overtaken | abandoned
    next_check: str = ""        # ISO date it wakes without being asked
    woke: list[dict] = Field(default_factory=list)         # {at, why}
    refused: list[dict] = Field(default_factory=list)      # hypotheses refused as already refuted
    lessons: list[Lesson] = Field(default_factory=list)
    opened_at: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    # read-only, filled by the ledger
    id: str = ""
    key: str = ""
    version: int = 0
    recorded_at: str = ""
    superseded_by: str = ""


_STOP = frozenset("a an the of in on for to by with and or is are was were did does do why how what which "
                  "when where who our we us my your their its it this that these those from at as be been has "
                  "have had last this week month year days day ago over per vs versus about into than then".split())
_WORD = re.compile(r"[a-z0-9]+")


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower()) if w not in _STOP and len(w) > 2}


def subject_of(question: str, metric_label: str = "") -> str:
    """The object a question is about, normalised: the declared metric when known, else the
    question's content words in order, joined — stable across casing and filler."""
    if (metric_label or "").strip():
        return "-".join(_WORD.findall(metric_label.lower()))
    words = [w for w in _WORD.findall(str(question or "").lower()) if w not in _STOP and len(w) > 2]
    return "-".join(words[:8]) or "question"


def inquiry_key(connection_id: str, subject: str, opened_id: str) -> str:
    return f"inquiry:{connection_id}:{subject}:{opened_id}"


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _from(art: dict) -> Inquiry:
    q = Inquiry.model_validate(dict(art.get("payload") or {}))
    q.id = str(art.get("id") or "")
    q.key = str(art.get("natural_key") or "")
    q.version = int(art.get("version") or 0)
    q.recorded_at = str(art.get("created_at") or "")
    q.superseded_by = str(art.get("superseded_by") or "")
    return q


def _book(q: Inquiry, *, lineage: Optional[list] = None) -> Inquiry:
    data = q.model_dump()
    for read_only in ("id", "key", "version", "recorded_at", "superseded_by"):
        data.pop(read_only, None)
    edges = list(lineage or []) + [("run", r.run, r.verdict) for r in q.runs[-3:]]
    aid = _ledger().artifact_write(KIND, q.key, data, conn_id=q.connection_id or None, lineage=edges)
    art = _ledger().artifact_by_id(aid)
    return _from(art) if art else q


# ── reading ────────────────────────────────────────────────────────────────────────────────

def get_inquiry(inquiry_id: str) -> Optional[Inquiry]:
    art = _ledger().artifact_by_id(inquiry_id)
    return _from(art) if art and art.get("kind") == KIND else None


def latest(key: str) -> Optional[Inquiry]:
    art = _ledger().artifact_latest(key)
    return _from(art) if art and art.get("kind") == KIND else None


def list_inquiries(*, conn_id: Optional[str] = None, state: Optional[str] = None,
                   subject: Optional[str] = None, limit: int = 200) -> list[Inquiry]:
    """Current inquiries, newest first."""
    out = []
    for art in _ledger().artifacts_of_kind(KIND, conn_id=conn_id, limit=max(limit * 4, 200)):
        q = _from(art)
        if state and q.state != state:
            continue
        if subject and q.subject != subject:
            continue
        out.append(q)
        if len(out) >= limit:
            break
    return out


def for_run(run_id: str, *, conn_id: Optional[str] = None) -> Optional[Inquiry]:
    """The inquiry a run belongs to, or None (a run from before inquiries existed)."""
    if not run_id:
        return None
    for q in list_inquiries(conn_id=conn_id, limit=2000):
        if (any(r.run == run_id for r in q.runs) or q.extra.get("first_run") == run_id
                or run_id in (q.extra.get("pending_runs") or [])):
            return q
    return None


def due(now: Optional[_dt.datetime] = None) -> list[Inquiry]:
    today = (now or _now()).date().isoformat()
    return [q for q in list_inquiries(limit=2000) if q.state == "waiting" and q.next_check and q.next_check <= today]


# ── opening and waking ─────────────────────────────────────────────────────────────────────

def open_inquiry(*, question: str, connection_id: str, opened_by: str, run_id: str = "",
                 subject: str = "", now: Optional[_dt.datetime] = None, mission: str = "") -> Inquiry:
    """Open an inquiry — or WAKE the one on the same subject opened in the last
    :data:`REOPEN_WITHIN_DAYS` and not closed, attaching the run to it rather than doubling.
    ``opened_by`` names the door: ``person:<id>`` · ``monitor:<id>`` · ``restated:<claim>`` ·
    ``review`` · ``mission:<id>``. ``mission`` (phase 5) is the mission the question bears on,
    when the door read one — kept on the inquiry so the mission's report can count what it opened."""
    now = now or _now()
    subject = subject or subject_of(question)
    since = (now - _dt.timedelta(days=REOPEN_WITHIN_DAYS)).isoformat()
    for q in list_inquiries(conn_id=connection_id or None, subject=subject, limit=50):
        if q.state != "closed" and q.opened_at >= since:
            if run_id and not any(r.run == run_id for r in q.runs):
                q.extra.setdefault("pending_runs", []).append(run_id)
            if mission and not q.extra.get("mission"):
                q.extra["mission"] = mission
            if q.state == "waiting":
                q.state = "open"
                q.woke.append({"at": now.isoformat(), "why": f"a new run was opened by {opened_by}"})
            return _book(q)
    q = Inquiry(question=(question or "").strip()[:500], subject=subject, connection_id=connection_id or "",
                opened_by=opened_by or "unidentified", state="open", opened_at=now.isoformat(),
                extra={**({"first_run": run_id} if run_id else {}), **({"mission": mission} if mission else {})})
    q.key = inquiry_key(connection_id or "-", subject, (run_id or now.strftime("%Y%m%dT%H%M%S%f")))
    if not run_id:
        # opened by a signal, not an ask: no run is running, so the run it waits for is PROPOSED with its cost
        q.extra["proposed_run"] = propose_run(q, now=now)
    return _book(q)


# ── a run proposed with its cost (the study §H "Cost"; the close-out, C4) ──────────────────

#: The run kind an inquiry proposes — the deep analysis, metered as a kernel job of this kind.
RUN_KIND = "investigation"
#: How many of the install's own metered runs the estimate reads, newest first.
COST_SAMPLE = 200


def _median(values: list[float]) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return float(vals[mid]) if len(vals) % 2 else float((vals[mid - 1] + vals[mid]) / 2)


def _metered_runs(connection_id: str, kind: str = RUN_KIND, *, limit: int = COST_SAMPLE) -> list[dict]:
    """The install's own finished runs of ``kind`` on this connection, with the tokens they spent — the
    outer twin of a nested run reports 0 tokens and is left out (`runners/investigation.py`)."""
    rows = _ledger().jobs_where(kinds=[kind], conn_id=connection_id or None, states=["SUCCEEDED"], limit=limit)
    return [r for r in rows if int(((r.get("metrics") or {}).get("total_tokens")) or 0) > 0]


def _minutes(row: dict) -> Optional[float]:
    a, b = _as_dt(str(row.get("started_at") or "")), _as_dt(str(row.get("finished_at") or ""))
    return round((b - a).total_seconds() / 60.0, 2) if a and b and b >= a else None


def _as_dt(value: str) -> Optional[_dt.datetime]:
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def run_cost_estimate(connection_id: str, *, kind: str = RUN_KIND) -> dict:
    """What a run of ``kind`` costs on THIS install, from its own metered runs — never a guess: the
    median tokens and minutes with the count they were read from; a dollar floor from the priced
    model calls of the last fortnight (the session log's retention) with the unpriced calls counted
    beside it, never added as zero; and the ceiling the run's charter sets. With no metered run yet,
    the ceiling is the only number and the estimate says so."""
    out: dict[str, Any] = {"kind": kind, "from": "", "tokens": None, "minutes": None, "n": 0,
                           "usd_floor": None, "usd_n": 0, "unpriced_calls": 0, "ceiling": {}}
    try:
        runs = _metered_runs(connection_id, kind)
    except Exception as exc:  # noqa: BLE001 — an unreadable job table leaves the estimate at the ceiling, said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the metered runs could not be read for a run's cost", counter="inquiry.cost")
        runs = []
    out["n"] = len(runs)
    out["tokens"] = _median([float((r.get("metrics") or {}).get("total_tokens") or 0) for r in runs])
    out["minutes"] = _median([m for m in (_minutes(r) for r in runs) if m is not None])
    try:
        from aughor.obs.session_log import recent_sessions
        priced = [r for r in recent_sessions(limit=COST_SAMPLE, scan=4000)
                  if r.get("conn_id") == connection_id and r.get("investigation_id")]
        costs = [float(r.get("cost_usd") or 0.0) for r in priced if int(r.get("unpriced_calls") or 0) == 0 and r.get("llm_calls")]
        out["usd_floor"] = round(_median(costs), 4) if costs else None
        out["usd_n"] = len(costs)
        out["unpriced_calls"] = sum(int(r.get("unpriced_calls") or 0) for r in priced)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the session log could not be read for a run's price", counter="inquiry.cost")
    try:
        from aughor.kernel.agents import charter_for_kind, effective_governance
        g = effective_governance(charter_for_kind(kind).id)
        out["ceiling"] = {"tokens": g.token_budget, "seconds": g.time_budget_s, "charter": charter_for_kind(kind).id}
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the charter's ceiling could not be read for a run's cost", counter="inquiry.cost")
    if out["n"]:
        out["from"] = (f"the install's own {out['n']} metered run{'s' if out['n'] != 1 else ''} of this kind on this "
                       f"connection (median); the dollar figure is a floor from {out['usd_n']} priced run"
                       f"{'s' if out['usd_n'] != 1 else ''} of the last fortnight"
                       + (f", {out['unpriced_calls']} model calls unpriced" if out["unpriced_calls"] else ""))
    else:
        out["from"] = "no metered run of this kind on this connection yet; the charter's ceiling is the only number"
    return out


def propose_run(q: Inquiry, *, now: Optional[_dt.datetime] = None) -> dict:
    """The run an inquiry waits for, proposed with what it costs and what its result could change
    (the study §H: "a run is proposed with what it costs and what its result could change; the
    cheapest test goes first; work stops when no open hypothesis could change the decision").
    Nothing here spends a model: the proposal is read from the inquiry and the install's own
    metering. When nothing is open — no open item, no open hypothesis — no run is proposed, and
    the proposal says why."""
    now = now or _now()
    open_hyps = []
    for cid in q.hypotheses:
        c = _claims.get(cid)
        if c is not None and c.state == "open":
            open_hyps.append({"claim": c.id, "text": c.statement.text[:200]})
    items = [{"what": o.what, "settled_by": o.settled_by} for o in q.open]
    # the cheapest test first: an open item that names what would settle it is the one a run can
    # close with the least work; the ones with nothing named come after, said as unstated
    items.sort(key=lambda o: (not bool(o["settled_by"]) or o["settled_by"].startswith("unstated"), o["what"]))
    could_change = {"open_items": items, "open_hypotheses": open_hyps,
                    **({"mission": q.extra["mission"]} if q.extra.get("mission") else {}),
                    "decisions": list(q.decisions)}
    proposal: dict[str, Any] = {"kind": RUN_KIND, "question": q.question, "proposed_at": now.isoformat(),
                                "could_change": could_change,
                                "rule": "the cheapest test goes first; work stops when no open hypothesis could change the decision"}
    if q.state == "closed":
        proposal.update({"proposed": False, "why": "the inquiry is closed"})
        return proposal
    if not items and not open_hyps and q.runs:
        proposal.update({"proposed": False,
                         "why": "nothing is open that a run could change — no open item, no open hypothesis; the question stands answered"})
        return proposal
    proposal.update({"proposed": True, "cost": run_cost_estimate(q.connection_id)})
    return proposal


def mission_for(connection_id: str, metric: str) -> str:
    """The active mission a metric bears on most (its id), or "" — what a door passes as
    ``mission`` when it opens an inquiry from a signal about that metric."""
    try:
        from aughor.record.mission import bearing
        hits = bearing(connection_id, metric=metric).get("missions") or []
        return str(hits[0]["mission"]) if hits else ""
    except Exception as exc:  # noqa: BLE001 — a signal that cannot read the missions still opens its inquiry
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the missions could not be read for an inquiry", counter="inquiry.mission")
        return ""


def wake(q: Inquiry, *, why: str, now: Optional[_dt.datetime] = None) -> Inquiry:
    now = now or _now()
    q.state = "open"
    q.woke.append({"at": now.isoformat(), "why": why})
    q.next_check = ""
    # the close-out (C4): a woken inquiry is a run waiting to be proposed — proposed WITH what it costs
    q.extra["proposed_run"] = propose_run(q, now=now)
    booked = _book(q)
    try:
        _ledger().emit("inquiry.woke", {"inquiry_id": booked.id, "key": booked.key, "why": why,
                                        "question": q.question[:200]}, conn_id=q.connection_id or None)
    except Exception as exc:  # noqa: BLE001 — the spine is observability
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the inquiry woke; only its spine event was lost", counter="inquiry.emit")
    return booked


def wake_due(now: Optional[_dt.datetime] = None) -> list[Inquiry]:
    """The settle tick's half: every waiting inquiry whose check date has come wakes (state
    ``open``, the reason recorded) — it is then a run waiting to be proposed, which the Now page
    and the inquiry door list; nothing here spends a model."""
    now = now or _now()
    return [wake(q, why=f"its check date {q.next_check} came", now=now) for q in due(now)]


def wake_for_claim(claim_id: str, *, why: str) -> list[Inquiry]:
    """A relied-on claim was restated: every inquiry that established it wakes."""
    if not claim_id:
        return []
    return [wake(q, why=why) for q in list_inquiries(limit=2000)
            if claim_id in q.claims and q.state != "closed"]


def close_inquiry(q: Inquiry, *, closed_as: str, lessons: Optional[list[Lesson]] = None, by: str = "") -> Inquiry:
    if closed_as not in ("answered", "overtaken", "abandoned"):
        raise ValueError("an inquiry closes as answered, overtaken or abandoned")
    q.state, q.closed_as, q.next_check = "closed", closed_as, ""
    q.lessons = list(q.lessons) + list(lessons or [])
    q.extra["closed_by"] = by or "system"
    q.extra["closed_at"] = _now().isoformat()
    return _book(q)


# ── the run's result ───────────────────────────────────────────────────────────────────────

_HYPOTHESIS_STATE = {"confirmed": "supported", "refuted": "refuted", "inconclusive": "open",
                     "untested": "abandoned", "skipped": "abandoned"}

_SETTLE_WORDS = re.compile(r"settl|partial (final )?period|still filling|late rows|holds \d+ of \d+ days", re.I)


def _settled_by(gap: str, lag: Optional[int]) -> str:
    if _SETTLE_WORDS.search(gap or ""):
        return (f"the connection's settling lag: {lag} day{'s' if lag != 1 else ''}" if lag
                else "the source's settling lag, not yet learned for this connection")
    return ""


def _hyp(h) -> dict:
    if isinstance(h, dict):
        return h
    return {k: getattr(h, k, None) for k in ("id", "description", "verdict", "key_finding", "confidence")}


def attach_run_result(*, run_id: str, connection_id: str, question: str, report: Optional[dict],
                      hypotheses: list, now: Optional[_dt.datetime] = None) -> Optional[Inquiry]:
    """A completed run lands on its inquiry: the hypotheses as claims with their state (a refuted
    one warranted by the run that refuted it), what the run established (its claims in the
    Record), the open items with what would settle each, the typed verdict, and the inquiry's
    own state — closed when nothing is open, waiting with a wake date when something is."""
    now = now or _now()
    report = report if isinstance(report, dict) else {}
    q = for_run(run_id, conn_id=connection_id or None)
    if q is None:
        q = open_inquiry(question=question or str(report.get("headline") or ""), connection_id=connection_id,
                         opened_by="person", run_id=run_id, now=now)
    # hypotheses → claims
    for h in hypotheses or []:
        d = _hyp(h)
        text = str(d.get("description") or "").strip()
        if not text:
            continue
        verdict = str(d.get("verdict") or "untested")
        state = _HYPOTHESIS_STATE.get(verdict, "open")
        finding = str(d.get("key_finding") or "").strip()
        claim = _claims.Claim(
            kind="hypothesis", tier="said", about=_claims.About(kind="connection", key=connection_id or ""),
            statement=_claims.Statement(text=text[:1000]), status="Provisional", as_of=now.date().isoformat(),
            warrants=[_claims.Warrant(kind="run", ref=run_id, detail=finding[:400])] if finding and state != "open" else [],
            author="inquirer", author_kind="agent", state=state,
            extra={"inquiry": q.key, "run": run_id, "hypothesis_id": str(d.get("id") or ""),
                   "run_verdict": verdict, **({"evidence": finding[:1000]} if finding else {})},
        )
        cid = _claims.book(claim, key=_claims.claim_key("hypothesis", connection_id or "-", q.key.rsplit(":", 1)[-1],
                                                         str(d.get("id") or text[:40])),
                           conn_id=connection_id or None)
        if cid not in q.hypotheses:
            q.hypotheses.append(cid)
    # what the run established — the claims the receipt writer booked for it
    try:
        from aughor.record.byproducts import relied_on_claims
        for cid in relied_on_claims(connection_id, run_id):
            if cid not in q.claims:
                q.claims.append(cid)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the inquiry could not read the run's claims; it records the run without them",
                 counter="inquiry.claims")
    # open items
    lag: Optional[int] = None
    try:
        from aughor.settling.store import learned_lag_days
        lag = learned_lag_days(connection_id) if connection_id else None
    except Exception:  # noqa: BLE001
        lag = None
    gaps = [str(g) for g in (report.get("data_gaps") or []) if str(g).strip()]
    q.open = [OpenItem(what=g[:500], settled_by=_settled_by(g, lag) or "unstated — the report named the gap "
                                                                        "without what would close it") for g in gaps]
    # verdict
    refuted = (report.get("causal_checks") or {}).get("refutation") if isinstance(report.get("causal_checks"), dict) else {}
    verdict = "contradicted" if (refuted or {}).get("status") == "refuted" else "answered"
    why = (str((refuted or {}).get("reason") or "the skeptic refuted the stated cause") if verdict == "contradicted"
           else str(report.get("headline") or "")[:300])
    book_run_verdict(run_id, kind=verdict, why=why, connection_id=connection_id, inquiry_key=q.key)
    q.runs = [r for r in q.runs if r.run != run_id] + [RunNote(run=run_id, verdict=verdict, why=why[:300],
                                                               at=now.isoformat())]
    q.extra.pop("pending_runs", None)
    # state
    if q.open:
        q.state = "waiting"
        q.waiting_for = ("days to settle" if any(_SETTLE_WORDS.search(o.what) for o in q.open)
                         else "data that would settle the open items")
        q.next_check = (now + _dt.timedelta(days=int(lag) if lag else DEFAULT_WAKE_DAYS)).date().isoformat()
    else:
        q.state, q.closed_as, q.next_check = "closed", "answered", ""
        q.extra["closed_at"] = now.isoformat()
    return _book(q)


def attach_run_failure(*, run_id: str, connection_id: str, status: str, reason: str,
                       now: Optional[_dt.datetime] = None) -> Optional[Inquiry]:
    """A run that ended without an answer: the typed verdict booked, the inquiry left OPEN
    (the question stands) with the verdict on its run list."""
    now = now or _now()
    kind = classify_failure(status, reason)
    q = for_run(run_id, conn_id=connection_id or None)
    book_run_verdict(run_id, kind=kind, why=(reason or status or "")[:500], connection_id=connection_id,
                     inquiry_key=q.key if q else "")
    if q is None:
        return None
    q.runs = [r for r in q.runs if r.run != run_id] + [RunNote(run=run_id, verdict=kind, why=(reason or "")[:300],
                                                               at=now.isoformat())]
    q.extra.pop("pending_runs", None)
    if q.state != "closed":
        q.state = "open"
    return _book(q)


# ── refuted hypotheses as memory ───────────────────────────────────────────────────────────

def refuted_on(connection_id: str, *, now: Optional[_dt.datetime] = None) -> list[_claims.Claim]:
    """The hypotheses refuted on this connection in the last :data:`REFUTED_MEMORY_DAYS`."""
    now = now or _now()
    since = (now - _dt.timedelta(days=REFUTED_MEMORY_DAYS)).isoformat()
    return [c for c in _claims.list_claims(kind="hypothesis", conn_id=connection_id or None, state="refuted", limit=500)
            if c.recorded_at >= since]


def refuted_block(connection_id: str, *, now: Optional[_dt.datetime] = None) -> tuple[str, list[_claims.Claim]]:
    """``(prompt block, the claims)``: what the planner is told before it proposes hypotheses."""
    refuted = refuted_on(connection_id, now=now)
    if not refuted:
        return "", []
    lines = ["ALREADY REFUTED ON THIS CONNECTION — tested and found false; do NOT propose these again "
             "(the Record keeps them as memory):"]
    for c in refuted[:8]:
        ev = str(c.extra.get("evidence") or "").strip()
        lines.append(f"- {c.statement.text}" + (f" — refuted because: {ev[:160]}" if ev else "")
                     + f" ({c.as_of or c.recorded_at[:10]})")
    return "\n".join(lines) + "\n\n", refuted


def refuse_already_refuted(hypotheses: list, refuted: list[_claims.Claim]) -> tuple[list, list[dict]]:
    """``(kept, refused)`` — a proposed hypothesis whose content words overlap a refuted one at
    :data:`SAME_HYPOTHESIS` or more is refused; the record names which claim refuted it."""
    if not refuted:
        return list(hypotheses), []
    kept, refused = [], []
    for h in hypotheses:
        text = str(_hyp(h).get("description") or "")
        words = content_words(text)
        hit = None
        for c in refuted:
            theirs = content_words(c.statement.text)
            if words and theirs:
                overlap = len(words & theirs) / len(words | theirs)
                if overlap >= SAME_HYPOTHESIS:
                    hit = (c, overlap)
                    break
        if hit is None:
            kept.append(h)
        else:
            c, overlap = hit
            refused.append({"hypothesis": text[:500], "refuted_by": c.id, "refuted_on": c.as_of or c.recorded_at[:10],
                            "overlap": round(overlap, 2), "evidence": str(c.extra.get("evidence") or "")[:300]})
    return kept, refused


def record_refused(run_id: str, connection_id: str, refused: list[dict]) -> Optional[Inquiry]:
    if not refused:
        return None
    q = for_run(run_id, conn_id=connection_id or None)
    if q is None:
        return None
    q.refused = list(q.refused) + [{**r, "run": run_id} for r in refused]
    return _book(q)


def refused_for_run(run_id: str, connection_id: str = "") -> list[dict]:
    """The hypotheses this run refused as already refuted, from its inquiry."""
    if not run_id:
        return []
    q = for_run(run_id, conn_id=connection_id or None)
    return [r for r in (q.refused if q else []) if r.get("run") == run_id]


def refused_caveat(refused: list[dict]) -> str:
    """The sentence a report carries when hypotheses were refused — said, never implied."""
    if not refused:
        return ""
    heads = "; ".join(f"“{r['hypothesis'][:80]}” (refuted {r.get('refuted_on', '')})" for r in refused[:3])
    more = f" and {len(refused) - 3} more" if len(refused) > 3 else ""
    return (f"Not re-tested: {len(refused)} hypothesis{'es' if len(refused) != 1 else ''} the Record holds as "
            f"already refuted on this connection — {heads}{more}.")


# ── typed run verdicts ─────────────────────────────────────────────────────────────────────

_FAILURE_RULES: tuple[tuple[str, str], ...] = (
    (r"timed out|time out|deadline|budget|cost cap|spend|token limit|iterations? exhausted|out of budget", "out_of_budget"),
    (r"withheld|clearance|not permitted|refused by policy|rbac|forbidden|no grant", "withheld"),
    (r"no (such )?(metric|definition)|not defined|undefined metric|unknown metric|no governed definition", "no_definition"),
    (r"no rows|returned nothing|empty result|no data|no conclusive evidence|zero rows|nothing to salvage", "no_data"),
    (r"contradict", "contradicted"),
)


def classify_failure(status: str, reason: str) -> str:
    """Code over the recorded reason — never a model. ``timed_out`` is out of budget by status; a
    reason no rule places is ``tool_failed`` with the reason kept beside it."""
    if (status or "") == "timed_out":
        return "out_of_budget"
    text = str(reason or "")
    for pattern, kind in _FAILURE_RULES:
        if re.search(pattern, text, re.I):
            return kind
    return "tool_failed"


def book_run_verdict(run_id: str, *, kind: str, why: str, connection_id: str = "", inquiry_key: str = "") -> str:
    if kind not in VERDICTS:
        raise ValueError(f"unknown run verdict {kind!r}; one of {', '.join(VERDICTS)}")
    return _ledger().artifact_write(
        RUN_VERDICT_KIND, f"verdict:run:{run_id}",
        {"run": run_id, "verdict": kind, "why": (why or "")[:1000], "inquiry": inquiry_key,
         "at": _now().isoformat()},
        conn_id=connection_id or None, lineage=[("verdict_of", run_id, kind)])


def run_verdict(run_id: str) -> Optional[dict]:
    art = _ledger().artifact_latest(f"verdict:run:{run_id}")
    return dict(art.get("payload") or {}) if art and art.get("kind") == RUN_VERDICT_KIND else None


def verdict_tallies(*, conn_id: Optional[str] = None, limit: int = 5000) -> dict[str, int]:
    """How runs ended, by verdict — the phase's "typed-failure share" metric."""
    out = {k: 0 for k in VERDICTS}
    for art in _ledger().artifacts_of_kind(RUN_VERDICT_KIND, conn_id=conn_id, limit=limit):
        out[str((art.get("payload") or {}).get("verdict") or "tool_failed")] = \
            out.get(str((art.get("payload") or {}).get("verdict") or "tool_failed"), 0) + 1
    return out
