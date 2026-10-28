"""Decisions by email, inbound only (the decision-framework study §3.2; the user's call of 2026-10-27, ROADMAP §6 item
54(f), which reopens email for ARRIVALS only — §3.18's "no email in either direction" still holds for sending: the
platform never sends a mail).

Each decision has an address, ``decision+<id>@<the install's inbound domain>``. A mail provider the organisation sets
up posts each mail sent there to ``POST /doors/email`` with the install's inbound secret; nothing else reaches this
door, and no mailbox, inbox or thread is ever read — invited capture, never a crawl. Until the install sets both its
inbound domain and its secret, no address is shown — an address that could receive nothing is never offered — and the
decision and the door say which is missing (`missing`). Through a note's customs (the
quoted history dropped, capped, control-stripped, PII redacted), a mail is one of three things, decided by code from
its first line and its sender:

* **an approval** — its first line says *approve*, it comes from one of the decision's named approvers
  (``email:<address>``), and the provider verified its sender (DKIM pass). Booked as that person's approval, where:
  email. An approval that cannot be verified, or from someone not named, is kept as evidence and says why — never
  booked as an approval;
* **a dissent** — its first line says *dissent*, *object* or *disagree*: kept on the decision with the rest, from
  whoever sent it, the sender's verification said;
* **evidence** — anything else: a *said* claim warranted by a conversation (the mail's Message-ID, a hash of the words
  read, the sender's own words as shared), added to the decision as later evidence, dated — never as something it
  relied on when it was decided.

What a mail says is data. An instruction inside one is stored as its words and acts on nothing.
"""
from __future__ import annotations

import hmac
import os
import re
import uuid
from typing import Any

from pydantic import BaseModel, Field

DOMAIN_ENV = "AUGHOR_INBOUND_EMAIL_DOMAIN"
SECRET_ENV = "AUGHOR_INBOUND_EMAIL_SECRET"
#: The words a mail may carry into the Record, after its quoted history is dropped.
MAX_MAIL_CHARS = 2000
_ADDRESS = re.compile(r"decision\+([a-z0-9]{6,40})@([a-z0-9.-]+)", re.I)
_SENDER = re.compile(r"<\s*([^>\s]+@[^>\s]+)\s*>|([^\s<>,;]+@[^\s<>,;]+)")
_APPROVE = re.compile(r"^\W*(approve|approved|i approve)\b", re.I)
_DISSENT = re.compile(r"^\W*(dissent|i dissent|object|i object|disagree|i disagree)\b", re.I)
_QUOTE_START = re.compile(r"^(on .+ wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+|-{2,}\s*forwarded message\s*-{2,})$",
                          re.I)


class MailRefused(ValueError):
    """What the door will not take, with the status it answers and why."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class InboundMail(BaseModel):
    sender: str = ""
    to: list[str] = Field(default_factory=list)
    subject: str = ""
    text: str = ""
    message_id: str = ""
    dkim: str = ""               # the provider's verdict on the sender: pass · fail · none · "" (not said)


def domain() -> str:
    return os.environ.get(DOMAIN_ENV, "").strip().lower()


def _secret() -> str:
    return os.environ.get(SECRET_ENV, "").strip()


def _unset() -> str:
    """What the install has not set for a mail to arrive, in words ("no inbound mail domain (…)"); "" when nothing."""
    lacks = ([f"no inbound mail domain ({DOMAIN_ENV})"] if not domain() else []) + \
            ([f"no inbound secret ({SECRET_ENV})"] if not _secret() else [])
    return " and ".join(lacks)


def missing() -> str:
    """The sentence a decision shows where its address would be, while the install cannot receive a mail; ""
    once it can."""
    unset = _unset()
    return f"No address yet: this install sets {unset}." if unset else ""


def door_closed() -> str:
    """The sentence the door answers with while the install cannot receive a mail; "" once it can."""
    unset = _unset()
    return f"This door takes no mail yet: this install sets {unset}." if unset else ""


def address_for(decision_id: str) -> str:
    """The decision's address, or "" while the install sets no inbound domain or no secret (`missing` says which)."""
    return f"decision+{decision_id}@{domain()}" if (decision_id and not _unset()) else ""


def secret_ok(given: str) -> bool:
    """The provider's credential against the install's inbound secret, in constant time. No secret set → nothing
    is accepted: a door with no lock is closed, not open."""
    want = _secret()
    return bool(want) and hmac.compare_digest(str(given or "").strip(), want)


def _list(v: Any) -> list[str]:
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            if isinstance(x, dict):
                x = x.get("Email") or x.get("email") or x.get("address") or ""
            out += _list(x) if isinstance(x, str) else []
        return out
    return []


def normalise(payload: dict) -> InboundMail:
    """The mail as the platform reads it, from the platform's own shape (``from, to, cc, subject, text, message_id,
    dkim``) or a Postmark inbound webhook's (``From, To, Cc, Subject, TextBody, MessageID, Headers``)."""
    p = dict(payload or {})
    dkim = str(p.get("dkim") or "")
    if not dkim:
        for h in p.get("Headers") or []:
            if isinstance(h, dict) and str(h.get("Name", "")).lower() == "authentication-results":
                m = re.search(r"\bdkim=(\w+)", str(h.get("Value") or ""), re.I)
                if m:
                    dkim = m.group(1)
    return InboundMail(
        sender=str(p.get("from") or p.get("From") or p.get("FromFull", {}).get("Email") or ""),
        to=_list(p.get("to") or p.get("To") or p.get("ToFull")) + _list(p.get("cc") or p.get("Cc") or p.get("CcFull")),
        subject=str(p.get("subject") or p.get("Subject") or ""),
        text=str(p.get("text") or p.get("TextBody") or p.get("StrippedTextReply") or ""),
        message_id=str(p.get("message_id") or p.get("MessageID") or ""),
        dkim=dkim.lower())


def address_of(sender: str) -> str:
    m = _SENDER.search(sender or "")
    return (m.group(1) or m.group(2)).lower() if m else ""


def new_words(text: str) -> str:
    """What the sender wrote, without the quoted history beneath it."""
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if _QUOTE_START.match(s):
            break
        if s.startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _said(text: str) -> str:
    from aughor.security.pii import redact_text
    from aughor.util.prompt_safety import sanitize_db_text
    return redact_text(sanitize_db_text(text or "")[:MAX_MAIL_CHARS].strip())


def receive(mail: InboundMail) -> dict:
    """One mail to a decision's address: an approval, a dissent, or evidence — said which, and why."""
    want = domain()
    if not want:
        raise MailRefused(503, door_closed())
    found = [(m.group(1).lower(), m.group(2).lower()) for to in mail.to for m in [_ADDRESS.search(to or "")] if m]
    ids = [i for i, d in found if d == want]
    if not ids:
        raise MailRefused(404, "the mail is to no decision's address on this install")
    from aughor.kernel.ledger import Ledger
    from aughor.record import decisions as D
    art = Ledger.default().artifact_by_id(ids[0])
    if not art or art.get("kind") != D.DECISION_KIND:
        raise MailRefused(404, f"no decision {ids[0]} — the address names none")
    from aughor.org.context import using_org
    with using_org(str(art.get("org_id") or "default")):
        return _book(mail, ids[0])


def _book(mail: InboundMail, decision_id: str) -> dict:
    from aughor.record import decisions as D
    first_seen = D.get_decision(decision_id)
    d = D.latest_decision(first_seen.source) or first_seen
    sender = address_of(mail.sender)
    if not sender:
        raise MailRefused(422, "the mail names no sender")
    words = _said(new_words(mail.text))
    subject = _said(mail.subject)[:300]
    if not (words or subject):
        raise MailRefused(422, "the mail said nothing above its quoted history")
    first = next((ln for ln in (words or subject).splitlines() if ln.strip()), "")
    ref = f"email:{sender}"
    verified = mail.dkim == "pass"
    if _APPROVE.match(first) or (not words and _APPROVE.match(subject)):
        if ref not in (d.approvers or []):
            return _evidence(d, mail, sender, words, subject, why=f"{sender} is not one of this decision's named approvers, "
                                                                  "so the mail is kept as evidence, not as an approval")
        if not verified:
            return _evidence(d, mail, sender, words, subject, why=f"the provider did not verify {sender} (DKIM "
                                                                  f"{mail.dkim or 'not said'}), so the mail is kept "
                                                                  "as evidence, not as an approval")
        now, added = D.approve_decision(d.id, by=f"person:{sender}", ref=ref, where="email")
        return {"booked": "approval" if added else "nothing", "decision": now.id,
                "why": f"approved by {sender}" if added else f"{sender} had already approved it"}
    if _DISSENT.match(first) or (not words and _DISSENT.match(subject)):
        why = (words or subject)[:900] + ("" if verified else f" (the provider did not verify {sender})")
        now = D.amend_decision(d.id, by=f"person:{sender}", dissent_who=f"person:{sender}", dissent_why=why)
        return {"booked": "dissent", "decision": now.id, "why": f"{sender}'s dissent is kept on the decision"}
    return _evidence(d, mail, sender, words, subject, why="")


def _evidence(d, mail: InboundMail, sender: str, words: str, subject: str, *, why: str) -> dict:
    """A said claim warranted by the conversation, and the decision's next version naming it as later evidence."""
    from aughor.record import claims as C
    from aughor.record import decisions as D
    text = words or subject
    msg = (mail.message_id or "").strip("<> ") or uuid.uuid4().hex
    warrant = C.said_warrant("conversation", f"email:{msg}", text, shared=True,
                             detail=f"emailed to the decision by {sender}" + (f": “{subject}”" if subject else ""))
    claim = C.Claim(kind="said", tier="said", about=C.About(kind="connection", key=d.connection_id or ""),
                    statement=C.Statement(text=text[:1000]), status="Provisional", warrants=[warrant],
                    author=f"person:{sender}", author_kind="person",
                    extra={"decision": d.id, "via": "email", "subject": subject, "sender_verified": mail.dkim == "pass"})
    cid = C.book(claim, key=C.claim_key("said", "email", d.connection_id or "-", msg), conn_id=d.connection_id or None)
    now = D._current(d)
    now.extra["evidence"] = list(now.extra.get("evidence") or []) + [{
        **warrant.model_dump(), "claim": cid, "from": sender, "at": D._now(), "added_later": True}]
    new_id = D.book_decision(now)
    return {"booked": "evidence", "decision": new_id, "claim": cid,
            "why": why or f"kept as evidence on the decision, from {sender}"}
