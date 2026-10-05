"""Writers into the Record — the first three of the study's §E shapes (phase 1, P1-2).

The study counted five claim shapes that never met (§E): the Explorer's finding, the deep
analysis's finding, ``EvidenceClaim``, a pack's ``CoreClaim`` and the hub's ``ClaimCheck``. Each
becomes a WRITER into the one ledger (:mod:`aughor.record.claims`) rather than a store of its own.
This module holds the writers that ride the two spines already running:

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
        except Exception:  # noqa: BLE001 — the falsifier is a note; the claim books without it
            pass
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
    # Phase 2 of the 2027 study — an inquiry that established the restated claim wakes.
    try:
        from aughor.record.inquiry import wake_for_claim
        woke = wake_for_claim(prior.id, why=f"claim {prior.id} it established was restated by the re-check")
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the restatement stands; the inquiries relying on it could not be woken",
                 counter="inquiry.wake_on_restate")
        woke = []
    return {"restated": restated, "superseded": prior.id, "recheck_receipt": receipt,
            **({"woke_inquiries": [q.id for q in woke]} if woke else {})}


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
