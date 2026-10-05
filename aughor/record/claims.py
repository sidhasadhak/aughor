"""Claims — the atom of the Record (the 2027 study §G; phase 1, ROADMAP §3.53).

A claim is a dated statement about the business that knows its warrant, its owner, its tier, its
status, how often claims like it have been right, and what would overturn it. It is a kernel
artifact of kind ``claim``: versioned, superseded never deleted, with lineage. The envelope is the
hub's (`hub/provenance.py`: the authority ladder, the scope ladder) and the clock is doubled —
``as_of`` is the data's date, ``recorded_at`` is when the platform booked it (the artifact row's
own ``created_at``). With both, "what did we believe on 3 March?" is :func:`as_recorded`.

Three laws, enforced at the door rather than hoped for:

1. **No fact without a warrant.** A claim at tier ``measured`` carries at least one ``run``
   warrant (the statement that produced it, by receipt); ``approved`` and ``declared`` need a
   person as author or an ``attestation`` warrant. The tier a claim cannot warrant is refused,
   never quietly lowered — a refusal says what would have been needed.
2. **No model-authored fact.** Tier ``inferred`` is not a claim. What a model concludes without a
   run behind it is a *hypothesis* (``kind="hypothesis"``) at tier ``said``, and it stays one
   until a run or a person raises it. There is deliberately no ``llm_inferred`` provenance.
3. **Confidence is counted or absent.** ``confidence`` is never set by a writer: it is filled on
   read by the counter (phase 1's P1-4) as {reference class, hit rate, n}, or left empty. A
   model's own estimate of its certainty has no field to land in.

Supersede, do not delete: :func:`restate` writes a new version under the same natural key; the
kernel sets ``superseded_by`` on the old row and keeps its payload, and the new version names
what it replaced in ``supersedes``.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from aughor.hub.provenance import AUTHORITY_LADDER

#: The artifact kind in the kernel ledger.
KIND = "claim"

ClaimKind = Literal["observation", "finding", "reading", "definition", "hypothesis",
                    "prediction", "said", "cause"]
#: A tier is a word of the hub's authority ladder, minus the one that is not a claim.
TIERS: tuple[str, ...] = tuple(t for t in AUTHORITY_LADDER if t != "inferred")
Status = Literal["Final", "Provisional", "To date"]
AboutKind = Literal["object", "segment", "type", "connection", "domain", "organisation"]
AuthorKind = Literal["person", "agent", "system"]
WarrantKind = Literal["run", "document", "attestation", "claim"]


class About(BaseModel):
    """What the claim is about, on the study's scope ladder (object → … → organisation)."""
    kind: AboutKind = "connection"
    key: str = ""


class Statement(BaseModel):
    """Typed where it can be; the prose is a label, not the claim."""
    text: str
    metric: str = ""
    value: Optional[float] = None
    unit: str = ""
    range_start: str = ""      # ISO date, inclusive
    range_end: str = ""        # ISO date, exclusive
    object_set: str = ""       # a verified segment or object-set expression


class Warrant(BaseModel):
    """Why the claim is entitled to be relied on."""
    kind: WarrantKind
    ref: str                   # a receipt id (run) · a document locator · a verdict id · a claim id
    detail: str = ""
    reproducible: Optional[bool] = None
    why_not: str = ""          # when reproducible is False


class Confidence(BaseModel):
    """A counted frequency — never a stated one. Filled by the counter on read
    (`aughor/record/confidence.py`). ``hit_rate`` is None below the counter's threshold: the count
    is shown, the rate is not, and ``note`` says why."""
    reference_class: str
    hit_rate: Optional[float]
    n: int
    scope: str = ""            # the connection counted, or "all connections"
    note: str = ""


class Claim(BaseModel):
    kind: ClaimKind
    about: About = Field(default_factory=About)
    statement: Statement
    tier: str
    status: Status = "Provisional"
    as_of: str = ""            # the data's date (ISO)
    valid_from: str = ""
    valid_until: str = ""
    warrants: list[Warrant] = Field(default_factory=list)
    falsifier: str = ""        # the check that would overturn it
    next_check: str = ""       # when the falsifier next runs (ISO)
    owner: str = ""            # a principal, or "" when unresolved — said, never implied
    author: str = ""
    author_kind: AuthorKind = "system"
    definition_version: str = ""   # the version of the definition it was measured under
    # Hypotheses and predictions carry their own state (the study §G); other kinds leave it "".
    state: str = ""            # hypothesis: open | supported | refuted | abandoned · prediction: open | scored
    extra: dict[str, Any] = Field(default_factory=dict)
    # Filled by the ledger on read, never by a writer.
    id: str = ""
    key: str = ""
    version: int = 0
    recorded_at: str = ""
    supersedes: str = ""       # the artifact id this version replaced
    superseded_by: str = ""    # the artifact id that replaced this version
    confidence: Optional[Confidence] = None


class ClaimRefused(ValueError):
    """The door said no, and why."""


def claim_key(*parts: str) -> str:
    """A natural key a writer can reuse to restate the same claim: ``claim:<part>:<part>…``."""
    return "claim:" + ":".join(str(p).strip() for p in parts if str(p).strip())


def _check(claim: Claim) -> None:
    if claim.tier not in TIERS:
        if claim.tier == "inferred":
            raise ClaimRefused("a model's inference is not a claim — book it as kind='hypothesis' at tier "
                               "'said', and raise it with a run or a person's attestation")
        raise ClaimRefused(f"unknown tier {claim.tier!r}; the ladder is {', '.join(TIERS)}")
    if not (claim.statement.text or "").strip():
        raise ClaimRefused("a claim states something; the statement's text is empty")
    kinds = {w.kind for w in claim.warrants}
    if claim.tier == "measured" and "run" not in kinds:
        raise ClaimRefused("tier 'measured' needs a run warrant — the receipt of the statement that "
                           "produced the number; without one the claim is at best 'said'")
    if claim.tier in ("approved", "declared") and claim.author_kind != "person" and "attestation" not in kinds:
        raise ClaimRefused(f"tier {claim.tier!r} is a person's: the author is a person, or an attestation "
                           "warrant names the verdict that approved it")
    if claim.confidence is not None:
        raise ClaimRefused("confidence is counted by the ledger, never written by a claim's author")
    if claim.kind == "prediction" and not claim.statement.metric:
        raise ClaimRefused("a prediction names the metric it is about")


def _payload(claim: Claim, *, supersedes: str = "") -> dict:
    data = claim.model_dump()
    for read_only in ("id", "key", "version", "recorded_at", "superseded_by", "confidence"):
        data.pop(read_only, None)
    data["supersedes"] = supersedes
    return data


def _from_artifact(art: dict) -> Claim:
    payload = dict(art.get("payload") or {})
    payload.pop("confidence", None)
    claim = Claim.model_validate(payload)
    claim.id = str(art.get("id") or "")
    claim.key = str(art.get("natural_key") or "")
    claim.version = int(art.get("version") or 0)
    claim.recorded_at = str(art.get("created_at") or "")
    claim.superseded_by = str(art.get("superseded_by") or "")
    return claim


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def book(claim: Claim, *, key: str, conn_id: Optional[str] = None,
         created_by_job: Optional[str] = None, lineage: Optional[list] = None) -> str:
    """Book a claim under ``key``. A key already booked is RESTATED (a new version; the old one
    superseded and kept). Returns the artifact id. Refuses what the three laws refuse."""
    _check(claim)
    if not key.startswith("claim:"):
        raise ClaimRefused("a claim's key starts with 'claim:' — use claim_key(...)")
    prior = _ledger().artifact_latest(key)
    supersedes = str(prior.get("id") or "") if prior and not prior.get("superseded_by") else ""
    edges = list(lineage or [])
    for w in claim.warrants:
        edges.append((f"warrant:{w.kind}", w.ref, (w.detail or "")[:400]))
    if supersedes:
        edges.append(("supersedes", supersedes, "restated"))
    conn = conn_id or (claim.about.key if claim.about.kind == "connection" else None)
    aid = _ledger().artifact_write(KIND, key, _payload(claim, supersedes=supersedes), conn_id=conn,
                                   created_by_job=created_by_job, lineage=edges)
    _events_out(claim, aid, key, supersedes, conn or "")
    return aid


def _events_out(claim: Claim, aid: str, key: str, supersedes: str, conn: str) -> None:
    """Phase 7 of the 2027 study — a restatement and a refutation are events out: journaled by
    kind (`kernel/events.py`) and delivered to the subscriptions that asked (`record/subscriptions`).
    Best-effort: the claim is booked whether or not anyone hears of it."""
    kinds: list[tuple[str, dict]] = []
    if supersedes:
        kinds.append(("claim.restated", {"claim_id": aid, "supersedes": supersedes, "key": key, "kind": claim.kind, "tier": claim.tier,
                                         "author": claim.author, "text": claim.statement.text[:300], "metric": claim.statement.metric,
                                         "value": claim.statement.value, "unit": claim.statement.unit, "as_of": claim.as_of}))
    if claim.kind == "hypothesis" and claim.state == "refuted":
        kinds.append(("claim.refuted", {"claim_id": aid, "key": key, "tier": claim.tier, "text": claim.statement.text[:300],
                                        "evidence": str(claim.extra.get("evidence") or "")[:300], "run": str(claim.extra.get("run") or "")}))
    for kind, payload in kinds:
        try:
            _ledger().emit(kind, payload, conn_id=conn or None)
            from aughor.record.subscriptions import notify
            notify(kind, payload, conn_id=conn)
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, f"the {kind} event could not go out; the claim stands", counter="claims.events_out", conn_id=conn or None)


def restate(key: str, claim: Claim, **kw) -> str:
    """Spelled out for readers: the same door as :func:`book` on a key that already exists."""
    if _ledger().artifact_latest(key) is None:
        raise ClaimRefused(f"nothing is booked under {key!r} to restate — book it first")
    return book(claim, key=key, **kw)


def get(claim_id: str) -> Optional[Claim]:
    art = _ledger().artifact_by_id(claim_id)
    return _from_artifact(art) if art and art.get("kind") == KIND else None


def latest(key: str) -> Optional[Claim]:
    art = _ledger().artifact_latest(key)
    return _from_artifact(art) if art and art.get("kind") == KIND else None


def versions(key: str, *, limit: int = 100) -> list[Claim]:
    """Every version, newest first — the restatements with their text kept."""
    return [_from_artifact(a) for a in _ledger().artifact_versions(key, limit=limit) if a.get("kind") == KIND]


def list_claims(*, kind: Optional[str] = None, about_kind: Optional[str] = None,
                about_key: Optional[str] = None, conn_id: Optional[str] = None,
                state: Optional[str] = None, limit: int = 200) -> list[Claim]:
    """Current claims, newest first; filters are exact matches on the payload."""
    out = []
    for art in _ledger().artifacts_of_kind(KIND, conn_id=conn_id, limit=max(limit * 4, 200)):
        c = _from_artifact(art)
        if kind and c.kind != kind:
            continue
        if about_kind and c.about.kind != about_kind:
            continue
        if about_key and c.about.key != about_key:
            continue
        if state and c.state != state:
            continue
        out.append(c)
        if len(out) >= limit:
            break
    return out


def _as_dt(value: str) -> Optional[_dt.datetime]:
    try:
        d = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def as_recorded(on: str, **filters) -> list[Claim]:
    """Belief as a VIEW (the study §G): the version of each claim that was current on the day
    ``on`` (ISO date or datetime, inclusive to its end) — not a second store. A claim first booked
    after ``on`` is absent; a claim restated after ``on`` appears as it stood then."""
    cutoff = _as_dt(on if "T" in str(on) else f"{on}T23:59:59.999999+00:00")
    if cutoff is None:
        raise ValueError(f"unreadable date {on!r}")
    seen: set[str] = set()
    out: list[Claim] = []
    current = list_claims(limit=filters.pop("limit", 2000), **filters)
    for c in current:
        if c.key in seen:
            continue
        seen.add(c.key)
        for v in versions(c.key):              # newest first
            at = _as_dt(v.recorded_at)
            if at is not None and at <= cutoff:
                out.append(v)
                break
    return out


def relied_on_by(claim_id: str) -> list[str]:
    """The decisions that relied on this claim (the study §G ``relied_on_by``) — read from the
    decisions, so a claim never has to be rewritten when a decision cites it. A decision cites the
    version that stood when it was taken, so every version of the claim is matched: the corrected
    claim still names the decision that stood on what it corrected."""
    from aughor.record.decisions import list_decisions
    asked = get(claim_id)
    ids = {claim_id} | ({v.id for v in versions(asked.key)} if asked is not None else set())
    return [d.id for d in list_decisions(limit=2000) if ids & set(d.relied_on)]


# ── a person says a claim is wrong (the study §V, screens 4 and 9) ─────────────────────────

def restated_consequences(prior_id: str, new_id: str, *, how: str) -> dict:
    """What a restatement sets in motion, whoever made it: every inquiry that established the
    claim wakes, and every decision that relied on it reopens. ``how`` finishes the sentence each
    is told ("restated by the re-check", "marked wrong by ana"). Best-effort on both — the
    restatement stands whether or not anything downstream could be told."""
    out: dict[str, list[str]] = {}
    try:
        from aughor.record.inquiry import wake_for_claim
        woke = wake_for_claim(prior_id, why=f"claim {prior_id} it established was {how}")
        if woke:
            out["woke_inquiries"] = [q.id for q in woke]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the restatement stands; the inquiries relying on it could not be woken",
                 counter="inquiry.wake_on_restate")
    try:
        from aughor.record.decisions import reopen_for_claim
        reopened = reopen_for_claim(prior_id, restated_as=new_id, why=f"a claim it relied on was {how}")
        if reopened:
            out["reopened_decisions"] = [d.id for d in reopened]
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the restatement stands; the decisions relying on it could not be reopened",
                 counter="decisions.reopen_on_restate")
    return out


def mark_wrong(claim_id: str, *, by: str, corrected: str = "", why: str = "") -> dict:
    """A person says a claim is wrong. It is RESTATED under its own key — the wrong version kept,
    superseded — and never deleted: a hypothesis as refuted, with the person's reason as its
    evidence; anything else as the person's corrected statement at tier ``declared``, warranted by
    their attestation and naming the version it corrects. A prediction is refused: it is scored
    when its day comes, not overruled. Returns the new version's id and what the restatement woke
    or reopened."""
    who = (by or "").strip()
    if not who or who == "unidentified" or who.startswith(("agent:", "system")) or who == "model":
        raise ClaimRefused("a person marks a claim wrong — say who")
    asked = get(claim_id)
    if asked is None:
        raise ClaimRefused(f"no claim {claim_id!r}")
    prior = latest(asked.key) or asked
    if prior.kind == "prediction":
        raise ClaimRefused("a prediction is scored when its day comes, by code; it is not marked wrong")
    corrected, why = (corrected or "").strip(), (why or "").strip()
    new = prior.model_copy(deep=True)
    new.confidence = None
    attestation = Warrant(kind="attestation", ref=who, detail=why[:400])
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    if prior.kind == "hypothesis":
        if prior.state == "refuted":
            raise ClaimRefused("this hypothesis is already held as refuted")
        if not (why or corrected):
            raise ClaimRefused("a refutation says why — what shows the hypothesis is false")
        new.state = "refuted"
        new.warrants = list(prior.warrants) + [attestation]
        new.extra = {**prior.extra, "evidence": (why or corrected)[:1000], "marked_wrong_by": who}
    else:
        if not corrected:
            raise ClaimRefused("marking a claim wrong takes the corrected statement — what is true instead")
        if corrected == prior.statement.text.strip():
            raise ClaimRefused("the corrected statement is the one already held")
        new.statement = Statement(text=corrected[:1000], metric=prior.statement.metric, unit=prior.statement.unit,
                                  range_start=prior.statement.range_start, range_end=prior.statement.range_end,
                                  object_set=prior.statement.object_set)
        new.tier, new.author, new.author_kind, new.as_of = "declared", who, "person", today
        new.warrants = [attestation, Warrant(kind="claim", ref=prior.id, detail="the version this corrects")]
        new.extra = {**prior.extra, "restated_by": "a person", "cause": "marked_wrong", "marked_wrong_by": who,
                     **({"marked_wrong_why": why[:1000]} if why else {})}
    conn = prior.about.key if prior.about.kind == "connection" else None
    new_id = book(new, key=prior.key, conn_id=conn)
    consequences = restated_consequences(prior.id, new_id, how=f"marked wrong by {who}")
    if prior.kind == "hypothesis" and prior.extra.get("inquiry"):
        # the inquiry that holds it proposed its next run while this was open; that proposal is re-read
        try:
            from aughor.record import inquiry as _inquiry
            q = _inquiry.latest(str(prior.extra["inquiry"]))
            if q is not None and q.state != "closed":
                _inquiry.keep_proposed_run(q)
        except Exception as exc:  # noqa: BLE001 — the refutation stands; only the inquiry's proposal is stale
            from aughor.kernel.errors import tolerate
            tolerate(exc, "the hypothesis is refuted; its inquiry's proposed run could not be re-read",
                     counter="inquiry.repropose_on_refute")
    return {"claim_id": new_id, "superseded": prior.id, **consequences}
