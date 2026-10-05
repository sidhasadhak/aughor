"""Writers into the Record — the study's §E shapes (phase 1, P1-2; the pack writer with phase 6; the
explorer's and the hub's with the arc's close-out).

The study counted five claim shapes that never met (§E): the Explorer's finding, the deep
analysis's finding, ``EvidenceClaim``, a pack's ``CoreClaim`` and the hub's ``ClaimCheck``. Each
becomes a WRITER into the one ledger (:mod:`aughor.record.claims`) rather than a store of its own —
all five are here now. The first two ride the spines already running:

- **the Trust Receipt** — `routers/investigations.py::_write_answer_receipt` is the one place every
  user-facing answer (chat · deep analysis · monitor · the conversation's ``run_sql``) is receipted,
  so :func:`book_from_receipt` there books every answer's claim by construction: an *observation*
  when the answer concluded something with a query behind it, warranted by the receipt; and for a
  deep analysis its *findings* beside it, read from the evidence ledger the analysis filled a
  moment earlier. A finding with its own SQL is ``measured``; one the narrator stated without a
  query is booked as what it is — a ``hypothesis`` at tier ``said`` — never raised by wording.
- **the daily re-check** — `answer/recheck.py` re-runs each recent answer's query; when the numbers
  moved, :func:`restate_answer_observation` restates the observation (a new version, the old text
  kept), warranted by a receipt of the re-check run, so "what did we believe on Tuesday" stays
  answerable from the ledger alone.

What is deliberately NOT written: a confidence. ``EvidenceClaim`` carried 0.8 or 0.5 by whether a
phase called itself significant; that number is gone from the model and from this writer. Counted
confidence arrives with P1-4, on read.

Every door here is best-effort by contract — the receipt and the re-check stand without the claim
— and says so through ``tolerate`` rather than failing the answer path.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from aughor.record import claims as _claims

#: The kernel artifact kind of a re-check's receipt — the run warrant of a restated observation.
RECHECK_RECEIPT_KIND = "answer_recheck"


def observation_key(connection_id: str, inv_id: str) -> str:
    """The natural key of the observation an answer booked: one per answer, restated in place."""
    return _claims.claim_key("observation", "answer", connection_id, inv_id)


def finding_key(connection_id: str, inv_id: str, evidence_id: str) -> str:
    return _claims.claim_key("finding", "deep", connection_id, inv_id, evidence_id)


def _today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _author(agent: Optional[dict]) -> tuple[str, str]:
    if agent and agent.get("id"):
        return f"agent:{agent['id']}", "agent"
    return "system", "system"


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


# ── from the Trust Receipt ─────────────────────────────────────────────────────────────────

def book_answer_observation(*, kind: str, natural_key: str, receipt_id: str, connection_id: str,
                            question: str, headline: str, sql: str,
                            metrics_used: Optional[list[str]] = None, agent: Optional[dict] = None,
                            canvas_id: str = "") -> Optional[str]:
    """Book the answer's headline as an observation at tier ``measured``, warranted by its receipt.
    Returns the claim's artifact id, or None when there is nothing to book: no receipt, no query
    behind the headline, or a headline that concluded nothing (the caller passes "" then — the
    same law the graph's finding node enforces)."""
    headline = (headline or "").strip()
    if not (receipt_id and connection_id and sql and headline):
        return None
    inv_id = natural_key.rsplit(":", 1)[-1] if natural_key else ""
    if not inv_id:
        return None
    author, author_kind = _author(agent)
    from aughor.kernel.ledger import CHAT_ANSWER_KIND
    next_check = ""
    falsifier = ""
    if kind == CHAT_ANSWER_KIND:
        try:
            from aughor.answer import recheck
            if recheck.enabled() and recheck.can_recheck(sql):
                next_check = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=1)).date().isoformat()
                falsifier = ("the answer's own query, re-run daily for 14 days (answers.recheck): a number "
                             "that moves past the noise band restates this claim")
            elif recheck.enabled():
                falsifier = ("not re-checked: the query reads the clock, so re-running it measures "
                             "another window")
        except Exception as exc:  # noqa: BLE001 — the falsifier is a note; the claim books without it
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the claim's falsifier could not be read; the claim books without it", counter="record.falsifier")
    claim = _claims.Claim(
        kind="observation", tier="measured",
        about=_claims.About(kind="connection", key=connection_id),
        statement=_claims.Statement(text=headline[:1000], metric=(metrics_used or [""])[0] or ""),
        status="Provisional", as_of=_today(),
        warrants=[_claims.Warrant(kind="run", ref=receipt_id, detail=sql[:400])],
        falsifier=falsifier, next_check=next_check,
        author=author, author_kind=author_kind,
        extra={"investigation_id": inv_id, "receipt_kind": kind, "question": (question or "")[:500],
               **({"canvas_id": canvas_id} if canvas_id else {}),
               **({"metrics_used": list(metrics_used)} if metrics_used else {})},
    )
    return _claims.book(claim, key=observation_key(connection_id, inv_id), conn_id=connection_id)


def book_deep_findings(*, investigation_id: str, connection_id: str, receipt_id: str,
                       agent: Optional[dict] = None) -> list[str]:
    """Book a deep analysis's findings from the evidence ledger it filled: a finding with its own
    query is ``measured`` on the report's receipt; one without is a ``hypothesis`` at tier
    ``said``, open. Returns the artifact ids booked (restated when the same finding was booked
    before — a partial report followed by the full one)."""
    if not (investigation_id and connection_id and receipt_id):
        return []
    from aughor.evidence.store import get_claims_for_investigation
    author, author_kind = _author(agent)
    out: list[str] = []
    for ev in get_claims_for_investigation(investigation_id):
        text = (ev.claim_text or "").strip()
        if not text:
            continue
        common: dict[str, Any] = dict(
            about=_claims.About(kind="connection", key=connection_id),
            statement=_claims.Statement(text=text[:1000], metric=ev.metric_used or ""),
            status="Provisional", as_of=(ev.data_freshness or ev.created_at or "")[:10] or _today(),
            author=author, author_kind=author_kind,
            extra={"investigation_id": investigation_id, "evidence_claim_id": ev.id,
                   **({"phase": ev.hypothesis_id} if ev.hypothesis_id else {})},
        )
        if ev.sql_source:
            claim = _claims.Claim(kind="finding", tier="measured",
                                  warrants=[_claims.Warrant(kind="run", ref=receipt_id,
                                                            detail=ev.sql_source[:400])], **common)
        else:
            common["extra"]["why_hypothesis"] = ("the deep analysis stated it without a query of its "
                                                "own behind it; a run or a person raises it")
            claim = _claims.Claim(kind="hypothesis", tier="said", state="open", **common)
        out.append(_claims.book(claim, key=finding_key(connection_id, investigation_id, ev.id),
                                conn_id=connection_id))
    return out


def book_from_receipt(*, kind: str, natural_key: str, receipt_id: Optional[str], connection_id: str,
                      question: str, headline: str, sql: str, metrics_used: Optional[list[str]] = None,
                      agent: Optional[dict] = None, canvas_id: str = "",
                      payload_extra: Optional[dict] = None) -> dict:
    """The receipt writer's one call: ``{"observation": id|None, "findings": [ids]}``."""
    out: dict[str, Any] = {"observation": None, "findings": []}
    if not receipt_id:
        return out
    out["observation"] = book_answer_observation(
        kind=kind, natural_key=natural_key, receipt_id=receipt_id, connection_id=connection_id,
        question=question, headline=headline, sql=sql, metrics_used=metrics_used, agent=agent,
        canvas_id=canvas_id)
    from aughor.kernel.ledger import DEEP_REPORT_KIND
    extra = payload_extra or {}
    if kind == DEEP_REPORT_KIND and extra.get("investigation_id") and not extra.get("partial"):
        out["findings"] = book_deep_findings(investigation_id=str(extra["investigation_id"]),
                                             connection_id=connection_id, receipt_id=receipt_id,
                                             agent=agent)
    return out


# ── from the daily re-check ───────────────────────────────────────────────────────────────

def restate_answer_observation(answer: dict, entry: dict, *, text: str = "") -> Optional[dict]:
    """A re-check found the answer's numbers moved: restate its observation. The new version carries
    the new statement (``text``, code-written by the re-check), the single changed value when there
    is one, the cause the re-check could tell (late rows · restated · unknown) and a run warrant —
    a receipt of the re-check itself, booked here as a kernel artifact of kind
    :data:`RECHECK_RECEIPT_KIND`, since the re-check ran a query and a measured claim names the run
    that produced it. The earlier version is kept with its text.

    Returns ``{"restated", "superseded", "recheck_receipt"}``, or None when the answer booked no
    observation (it predates the Record, or concluded nothing) — the caller says so on the entry."""
    if entry.get("status") != "changed":
        return None
    conn_id = str(answer.get("connection_id") or "")
    inv_id = str(answer.get("id") or "")
    if not (conn_id and inv_id):
        return None
    key = observation_key(conn_id, inv_id)
    prior = _claims.latest(key)
    if prior is None:
        return None
    sql = str((answer.get("report") or {}).get("sql") or "") or next(
        (w.detail for w in prior.warrants if w.kind == "run"), "")
    first_receipt = next((w.ref for w in prior.warrants if w.kind == "run"), "")
    changes = list(entry.get("changes") or [])
    receipt = _ledger().artifact_write(
        RECHECK_RECEIPT_KIND, f"recheck:{conn_id}:{inv_id}",
        {"investigation_id": inv_id, "sql": sql, "checked_at": entry.get("checked_at", ""),
         "status": entry["status"], "changes": changes[:10], "missing": entry.get("missing") or [],
         "missing_rows": entry.get("missing_rows", 0), "new_rows": entry.get("new_rows", 0),
         "compared": entry.get("compared", 0), "cause": entry.get("cause", "unknown"),
         "lag_days": entry.get("lag_days")},
        conn_id=conn_id,
        lineage=[("source_sql", "sql", sql[:2000])] + (
            [("rechecks", first_receipt, "the receipt of the answer as first given")] if first_receipt else []),
    )
    new = prior.model_copy(deep=True)
    new.confidence = None
    new.statement = _claims.Statement(
        text=(text or _restated_text(prior.statement.text, changes, entry))[:1000],
        metric=prior.statement.metric or (changes[0].get("column", "") if len(changes) == 1 else ""),
        value=float(changes[0]["new"]) if len(changes) == 1 and changes[0].get("new") is not None else None,
        unit=prior.statement.unit)
    new.warrants = [_claims.Warrant(kind="run", ref=receipt, detail=sql[:400])]
    new.as_of = str(entry.get("checked_at") or "")[:10] or _today()
    new.extra = {**prior.extra, "restated_by": "answers.recheck", "cause": entry.get("cause", "unknown"),
                 "changes": changes[:10], "missing_rows": entry.get("missing_rows", 0),
                 "lag_days": entry.get("lag_days"), "first_receipt": first_receipt}
    if entry.get("status") == "changed" and entry.get("cause") == "late_rows":
        # late rows settle; the next re-check may move it again
        new.status = "Provisional"
    restated = _claims.restate(key, new, conn_id=conn_id)
    # Phase 2 of the 2027 study — an inquiry that established the restated claim wakes, and a
    # decision that relied on it reopens.
    consequences = _claims.restated_consequences(prior.id, restated, how="restated by the re-check")
    return {"restated": restated, "superseded": prior.id, "recheck_receipt": receipt, **consequences}


# ── from a pack's map, measured on connect (phase 6) ───────────────────────────────────────

#: A pack's measured tier → the hypothesis state its claim carries in the Record.
PACK_CLAIM_STATE: dict[str, str] = {"expected": "open", "measured-true": "supported", "measured-false": "refuted",
                                    "human": "supported"}


def pack_claim_key(pack_id: str, connection_id: str, schema_name: str, kind: str, subject: str) -> str:
    return _claims.claim_key("pack", pack_id, connection_id, schema_name or "-", kind,
                             "".join(ch if ch.isalnum() else "-" for ch in subject)[:120])


def book_pack_claims(report, *, connection_id: str, schema_name: str = "", fingerprint: str = "") -> dict:
    """The pack writer — the fourth of the study's five claim shapes (§E): every claim in a pack's
    map, evaluated against THIS connection's graph and data (`packs/ontology_map.apply_core_claims`),
    booked into the Record as a HYPOTHESIS the pack made about the business: ``open`` while the data
    cannot speak (tier ``said``), ``supported`` or ``refuted`` once it has (tier ``mined`` — the
    platform's own scan, warranted by the build that measured it), and ``supported`` at tier
    ``declared`` when a person's declaration settled it (an attestation warrant names it). One claim
    per pack · connection · schema · subject, restated on every build, so "what did this pack expect
    of us, and what did the data say" is the Record's to answer on any date. Best-effort by contract.
    Returns ``{"booked", "by_state", "pack"}``."""
    pack_id = str(getattr(report, "pack_id", "") or "")
    claims = list(getattr(report, "claims", None) or [])
    if not (pack_id and connection_id and claims):
        return {"booked": 0, "by_state": {}, "pack": pack_id,
                "note": "nothing to book: no pack, no connection or no claims" if not claims else ""}
    build_ref = f"ontology:{connection_id}:{schema_name or '-'}:{fingerprint or 'build'}"
    by_state: dict[str, int] = {}
    booked = 0
    for c in claims:
        state = PACK_CLAIM_STATE.get(c.tier, "open")
        measured = f" — measured: {c.measured}" if c.measured else ""
        text = f"{c.kind}: {c.subject} — the pack expects {c.expected}{measured}"
        if c.tier == "human":
            tier, warrants = "declared", [_claims.Warrant(kind="attestation", ref=str(c.measured or "declared"), detail=(c.note or "")[:400])]
        elif c.tier in ("measured-true", "measured-false"):
            tier, warrants = "mined", [_claims.Warrant(kind="run", ref=build_ref, detail=(c.note or "")[:400])]
        else:
            tier, warrants = "said", []
        claim = _claims.Claim(
            kind="hypothesis", tier=tier, about=_claims.About(kind="connection", key=connection_id),
            statement=_claims.Statement(text=text[:1000]), status="Provisional" if state == "open" else "Final",
            as_of=_today(), warrants=warrants, author=f"pack:{pack_id}", author_kind="system", state=state,
            extra={"pack": pack_id, "claim_kind": c.kind, "subject": c.subject, "expected": c.expected, "measured": c.measured,
                   "tier_measured": c.tier, "note": c.note, "schema": schema_name or "", "writer": "pack"},
        )
        try:
            _claims.book(claim, key=pack_claim_key(pack_id, connection_id, schema_name, c.kind, c.subject), conn_id=connection_id)
        except Exception as exc:  # noqa: BLE001 — one claim the door refused does not stop the rest, and is said
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"a pack claim could not be booked ({c.kind} {c.subject})", counter="record.pack_claim",
                     conn_id=connection_id)
            continue
        booked += 1
        by_state[state] = by_state.get(state, 0) + 1
    return {"booked": booked, "by_state": by_state, "pack": pack_id}


def pack_claims(connection_id: str, *, pack_id: str = "", limit: int = 500) -> list[_claims.Claim]:
    """What packs expected of this connection and what the data said, as the Record holds it now."""
    return [c for c in _claims.list_claims(kind="hypothesis", conn_id=connection_id, limit=limit)
            if c.extra.get("writer") == "pack" and (not pack_id or c.extra.get("pack") == pack_id)]


# ── the Explorer's finding (the fifth shape's first half) ──────────────────────────────────

def explorer_finding_key(connection_id: str, schema_name: str, finding_id: str) -> str:
    """One claim per connection · schema · finding id. The schema is in the key because per-schema
    runs reuse ids (``pinned__0``, ``<domain>__<angle>__1``) and would otherwise restate each other."""
    return _claims.claim_key("finding", "explorer", connection_id, schema_name or "-", finding_id)


def book_explorer_finding(*, finding: dict, sql: str, connection_id: str, receipt_id: str,
                          schema_name: str = "", canvas_id: str = "") -> Optional[str]:
    """The explorer writer — the Explorer's finding, the first of the study's five shapes (§E),
    booked at the moment the explorer writes its own ``finding`` artifact (the emission tail in
    `explorer/agent.py`): a FINDING at tier ``measured``, warranted by that artifact — the run that
    produced it, with its SQL, its tables and the numeric-grounding guard that passed it. A finding
    the explorer re-reads unchanged on its next run is left alone (an unchanged finding is not a
    restatement, and a restatement is a Correction); one whose text changed is restated under its
    key, the old version kept. What is deliberately not copied: the explorer's own ``confidence``
    and ``novelty`` numbers — law 3 — and an ``unverified`` finding a person wrote by hand
    (`explorer/fix_persist`) never reaches this writer, so it books nothing.
    Returns the claim's artifact id, or None when there is nothing to book."""
    text = str((finding or {}).get("finding") or "").strip()
    fid = str((finding or {}).get("id") or "")
    if not (text and fid and sql and connection_id and receipt_id) or finding.get("unverified") or finding.get("invalid"):
        return None
    key = explorer_finding_key(connection_id, schema_name, fid)
    prior = _claims.latest(key)
    if prior is not None and prior.statement.text == text[:1000] and prior.state != "withdrawn":
        return prior.id
    measures = [str(m) for m in (finding.get("measures") or [])][:8]
    claim = _claims.Claim(
        kind="finding", tier="measured",
        about=_claims.About(kind="connection", key=connection_id),
        statement=_claims.Statement(text=text[:1000], metric=measures[0] if len(measures) == 1 else ""),
        status="Provisional", as_of=str(finding.get("generated_at") or "")[:10] or _today(),
        warrants=[_claims.Warrant(kind="run", ref=receipt_id, detail=sql[:400])],
        falsifier="the finding's own query, re-run before a Briefing (the live re-validation) and on a person's "
                  "re-check from the Evidence drawer; a number that no longer holds withdraws this claim",
        author="agent:explorer", author_kind="agent",
        extra={"writer": "explorer", "finding_id": fid, "domain": str(finding.get("domain") or ""),
               "angle": str(finding.get("angle") or ""), "measures": measures,
               "dimensions": [str(d) for d in (finding.get("dimensions") or [])][:8],
               "entities": [str(e) for e in (finding.get("entities_involved") or [])][:8],
               "schema": schema_name or "", **({"canvas_id": canvas_id} if canvas_id else {}),
               **({"pinned": True} if finding.get("pinned") else {}),
               **({"synthesized": True} if finding.get("synthesized") else {})},
    )
    return _claims.book(claim, key=key, conn_id=connection_id)


def withdraw_explorer_finding(*, connection_id: str, finding_id: str, reason: str,
                              schema_name: str = "", by: str = "system") -> Optional[str]:
    """A finding the re-validation found no longer holds, or a person dismissed, is WITHDRAWN in the
    Record: restated with ``state="withdrawn"``, ``valid_until`` today and the reason, the measured
    version kept beneath it — so the Corrections view lists it and "what did we believe" still
    answers. Returns the new version's id, or None when the finding was never booked or is already
    withdrawn."""
    key = explorer_finding_key(connection_id, schema_name, finding_id)
    prior = _claims.latest(key)
    if prior is None or prior.state == "withdrawn":
        return None
    new = prior.model_copy(deep=True)
    new.confidence = None
    new.state = "withdrawn"
    new.valid_until = _today()
    new.status = "Final"
    new.statement = _claims.Statement(text=f"Withdrawn: {prior.statement.text}"[:1000], metric=prior.statement.metric,
                                      value=prior.statement.value, unit=prior.statement.unit)
    new.extra = {**prior.extra, "withdrawn_reason": (reason or "")[:400], "withdrawn_by": by or "system"}
    return _claims.restate(key, new, conn_id=connection_id)


# ── the hub's ClaimCheck (the fifth shape's second half) ────────────────────────────────────

def said_claim_key(connection_id: str, object_ref: str, reply_id: str) -> str:
    """One claim per reply, never per object: a second reply on the same object is its own claim."""
    return _claims.claim_key("said", "hub", connection_id or "-",
                             "".join(ch if ch.isalnum() else "-" for ch in object_ref)[:120], reply_id)


def reply_id_for(*, reply_ts: str, author_ref: str, author: str, text: str) -> str:
    """The reply's own id when the bot sent it; else a hash of who said what — the same words by the
    same person are the same statement, a different reply is a different claim."""
    if reply_ts:
        return reply_ts.replace(".", "-")
    import hashlib
    return hashlib.sha1(f"{author_ref or author}|{text}".encode("utf-8")).hexdigest()[:12]


#: The hub's verification word → the claim's state.
SAID_CLAIM_STATE: dict[str, str] = {"measured": "supported", "contradicted": "refuted", "unchecked": "open"}


def book_said_claim(*, text: str, object_ref: str, connection_id: str, reply_id: str, check: dict,
                    author: str, author_ref: str = "", thread_ref: str = "", observed_at: str = "") -> Optional[str]:
    """The hub writer — the hub's ``ClaimCheck``, the last of the study's five shapes (§E): what a
    person said in a filed thread, booked as a SAID claim at tier ``said`` about the object the
    thread was filed on, with the check's verdict as its state (``supported`` when the data the
    thread was filed with agreed, ``refuted`` when it contradicted, ``open`` when nothing could be
    checked) and the measures it was checked against as a document warrant — the filing's snapshot,
    never a run, so the tier stays ``said``: the check is against a stamped reading, not a query.
    One claim per reply (`said_claim_key`), so a second reply on the same object is counted beside
    the first, not over it. Returns the artifact id, or None when there is no text or object."""
    text = (text or "").strip()
    if not (text and object_ref and reply_id):
        return None
    check = dict(check or {})
    verification = str(check.get("verification") or "unchecked")
    state = SAID_CLAIM_STATE.get(verification, "open")
    against = {k: v for k, v in (check.get("against") or {}).items() if isinstance(v, (int, float))}
    warrants = []
    if verification in ("measured", "contradicted") and thread_ref:
        warrants.append(_claims.Warrant(kind="document", ref=f"thread:{thread_ref}",
                                        detail=("checked against the measures the thread was filed with: "
                                                + ", ".join(f"{k}={v}" for k, v in list(against.items())[:6]))[:400]))
    claim = _claims.Claim(
        kind="said", tier="said", about=_claims.About(kind="object", key=object_ref),
        statement=_claims.Statement(text=text[:1000], metric=str((check.get("matched") or {}).get("label") or ""),
                                    value=(check.get("matched") or {}).get("value")),
        status="Provisional" if state == "open" else "Final",
        as_of=(observed_at or "")[:10] or _today(), warrants=warrants,
        author=author_ref or f"person:{author or 'someone'}", author_kind="person", state=state,
        extra={"writer": "hub", "verification": verification, "said": list(check.get("said") or [])[:8],
               "against": against, "matched": check.get("matched") or {}, "question": str(check.get("question") or ""),
               "question_to": str(check.get("question_to") or ""), "check_note": str(check.get("note") or ""),
               "thread": thread_ref, "reply_id": reply_id, "author_name": author or ""},
    )
    return _claims.book(claim, key=said_claim_key(connection_id, object_ref, reply_id), conn_id=connection_id or None)


def _restated_text(first: str, changes: list[dict], entry: dict) -> str:
    """A fallback statement when the re-check hands none: the numbers, then what was first said."""
    def what(c: dict) -> str:
        label = ", ".join(str(v) for v in (c.get("label") or {}).values() if v not in (None, ""))
        return f"{c.get('column', 'value')} for {label}" if label else str(c.get("column", "value"))
    parts = [f"{what(c)} is now {c.get('new')} (we said {c.get('old')})" for c in changes[:3]]
    if len(changes) > 3:
        parts.append(f"{len(changes) - 3} more changed")
    gone = int(entry.get("missing_rows") or 0)
    if gone:
        parts.append(f"{gone} row{'s' if gone != 1 else ''} no longer returned")
    return f"Restated: {'; '.join(parts)}. First said: {first}"
