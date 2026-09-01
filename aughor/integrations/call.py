"""DS-11 — spending a grant. The consumer VA-11 was built for and never got.

Measured on this tree before a line of it was written (2026-09-01): ``fresh_access_token``
had **zero** callers outside its own tests, and nothing outside ``routers/integrations.py``
imported ``aughor.integrations`` at all. The vault held tokens, refreshed them, revoked
them, audited the dance — and no capability on this platform could spend one. §7's
recurring failure, verbatim. This module is the repair, and it is deliberately the ONLY
door: one function, so refresh policy, scope checking, the approval gate, the outbound cap
and the audit line cannot be remembered by one caller and forgotten by the next.

**The order of the gates is the design**, and it is the same order the governed-write
executor uses, for the same reasons:

1. **The grant, resolved and judged.** Revoked and ``needs_reconnect`` are verdicts with
   sentences — the provider or a person already decided, and a retry cannot change it.
2. **Scopes, checked against what was GRANTED**, not what was asked for. A missing scope
   is refused here, naming the scope and the door, rather than sent and returned as the
   provider's own opaque 403 four hops from anything that could explain it.
3. **The params, built by the roster** — declared names only, path values percent-encoded.
4. **The approval gate, for a write only.** Our graduated gate is the POLICY authority
   (§3.4's rule: two gates that can disagree is strictly worse than one). A read is
   audited and proceeds; a write that is not allowlisted stops.
5. **The call, inside ``govern.outbound.external_call``** — the cap consulted BEFORE the
   work, a span around it, an ``EXTERNAL_CALL`` session event on every path. That is what
   makes a grant's traffic *countable* rather than merely instrumented.
6. **The audit line**, on every outcome, through the same ledger every other governed
   decision lands in.

**A write the gate stops is a QUESTION, not a fact** — and that is why it comes back as
``needs_approval`` rather than as one of the refusals beside it. Every other refusal here
describes the world (a revoked grant, a scope nobody consented to, an operation that does
not exist), and no amount of a person looking at it changes the answer. This one is
waiting for a human, so the automation plane turns it into a durable proposal and parks
the run on them — DS-8's machinery, reached by a second proposal kind the inbox learned
in DS-11's completion. On accept, the inbox calls back in here with ``approved=True``:
the gate is not asked twice, and everything else is.

**Known limit, stated rather than discovered (VA-10's to close).** The grant's owner is
recorded on every audit line, but ownership is not ENFORCED here: an automation fires from
cron with no identified user, so a rule that demanded ``conn.user_id == current_user_id()``
would refuse every scheduled step on a multi-user install. Discovery is scoped instead —
the registry and the routes offer only the caller's own grants — which is the same posture
the rest of this single-user-shaped platform takes today.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("aughor.integrations")

_TIMEOUT_S = 20.0

#: A provider that answers with more items than this ignored the limit we sent. REFUSED,
#: not truncated — W2's law, and for its reason: a silently shortened list is a chain that
#: acts on part of the world while its `count` describes all of it.
MAX_ITEMS = 200


@dataclass
class CallResult:
    """One attempt, in the vocabulary the automation plane already speaks.

    ``status`` distinguishes the four things a caller must treat differently:

    * ``executed`` — it happened, ``data`` carries the declared published keys.
    * ``refused`` — a verdict BEFORE the call. Terminal: identical inputs refuse
      identically, so a retry is the #200 lesson repeated.
    * ``needs_approval`` — the graduated gate stopped a WRITE. Alone among the refusals
      it is a question rather than a fact, because a person can answer it: the caller
      stages a proposal and parks on them.
    * ``blocked`` — a usage cap stopped it. **Nothing was sent**, so a retry once the
      window rolls over is legitimate, which is why it is not ``refused``.
    * ``failed`` — the provider refused it.
    * ``uncertain`` — the transport broke. It MAY have arrived; a retry could duplicate.
    """

    status: str
    message: str = ""
    data: dict = field(default_factory=dict)
    #: The provider's HTTP status, when there was one. Diagnostics only.
    http_status: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "executed"


def _request(method: str, url: str, *, headers: dict, query: dict,
             body: dict) -> tuple[int, Any]:
    """One HTTP call, ``(status, parsed-json)``. A seam on purpose: tests replace THIS,
    so every gate above it is exercised for real while nothing leaves the machine — the
    same choice ``broker._post`` made, and the reason both are trustworthy under test."""
    import httpx

    resp = httpx.request(method, url, headers=headers, params=query or None,
                         json=body if body else None, timeout=_TIMEOUT_S)
    try:
        payload = resp.json()
    except Exception:
        payload = None
    return resp.status_code, payload


def call_operation(connection_id: str, operation_id: str, params: Optional[dict] = None, *,
                   actor: str = "", approved: bool = False) -> CallResult:
    """Run one declared operation under one user's grant. Never raises.

    ``approved`` marks that a human already accepted this write in the proposal inbox, so
    the gate is not asked again — the accept IS the approval. Exactly the flag and exactly
    the reasoning the governed-write executor carries, and it bypasses the GATE only: the
    grant's verdicts, the scope check and the params are re-checked on the way through,
    because the world may have moved between staging and accepting.
    """
    from aughor.integrations.operations import (
        build_request, extract, get_operation, missing_scopes,
    )
    from aughor.integrations.providers import get_provider
    from aughor.integrations.store import get_connection

    op = get_operation(operation_id)
    if op is None:
        return CallResult("refused", f"unknown integration operation: '{operation_id}'")

    # Read the ENCRYPTED record first: everything below decides on metadata (provider,
    # status, scopes), and the token is fetched only once every gate has passed. A token
    # decrypted before the gates is a token in memory during a refusal.
    conn = get_connection(connection_id)
    if conn is None:
        return CallResult("refused", f"unknown integration connection: '{connection_id}'")
    if conn.provider != op.provider:
        return CallResult("refused",
                          f"'{op.label}' is a {op.provider} operation, but this grant is "
                          f"{conn.provider or 'unattributed'}")
    if conn.status == "revoked":
        return CallResult("refused", "this grant was revoked — connect again to use it")
    if conn.status == "needs_reconnect":
        return CallResult("refused",
                          f"{conn.provider} refused this grant's refresh — the user must "
                          f"reconnect it under Integrations")

    lacking = missing_scopes(op, conn.scopes)
    if lacking:
        return CallResult("refused",
                          f"this grant does not carry {', '.join(lacking)} — reconnect "
                          f"{conn.provider} and consent to it, then this step can run")

    try:
        url, query, body = build_request(op, dict(params or {}))
    except ValueError as exc:
        return CallResult("refused", str(exc))

    # 4 — the approval gate, writes only. Named `integration.<provider>.<operation>` so an
    # allowlist entry reads as the thing it permits, and scoped to the GRANT, which is the
    # grain a person actually reasons about ("this account may post to Slack").
    gov_action = op.gov_action
    if op.writes and approved:
        _audit(gov_action, connection_id, "approved", actor, conn.user_id,
               "human accept", True)
    elif op.writes:
        refusal = _gate(gov_action, connection_id, actor=actor, risk=op.risk)
        if refusal:
            # `needs_approval`, not `refused`, and the distinction is the whole of DS-11's
            # completion: every other refusal here is a fact about the world that no human
            # can change by looking at it, while this one is a question waiting for a
            # person. The caller turns it into a durable proposal and PARKS.
            return CallResult("needs_approval", refusal)

    try:
        token = _fresh_token(connection_id)
    except Exception as exc:
        _audit(gov_action, connection_id, "dispatch_error", actor, conn.user_id, str(exc),
               op.writes)
        return CallResult("refused", str(exc))

    provider = get_provider(op.provider)
    result = _send(op, url, query, body, token=token,
                   token_type=conn.token_type or "Bearer",
                   service=(provider.id if provider else op.provider))
    _audit(gov_action, connection_id,
           "executed" if result.ok else result.status, actor, conn.user_id,
           result.message or op.id, op.writes)
    if result.ok:
        try:
            result.data = extract(op, result.data)
        except Exception as exc:  # a shape we did not expect is a failure, not a crash
            logger.warning("integration %s: unreadable response shape: %s", op.id, exc)
            return CallResult("failed", f"{op.provider} answered in a shape "
                                        f"'{op.id}' does not know how to read",
                              http_status=result.http_status)
        over = len(result.data.get("items") or [])
        if over > MAX_ITEMS:
            # Refused AFTER a call that succeeded, so the audit line and the
            # `EXTERNAL_CALL` event both say `executed` while the STEP says refused.
            # That reads odd and is right: each is honest about its own subject — the
            # call did happen at the provider and must be counted, and what is being
            # refused is carrying a result this step cannot carry truthfully.
            return CallResult(
                "refused",
                f"{op.provider} returned {over} items for '{op.id}' — more than the "
                f"{MAX_ITEMS} a step may carry. Lower this step's limit and run it again.",
                http_status=result.http_status)
    return result


def _fresh_token(connection_id: str) -> str:
    """The one call into the broker. Imported here rather than at module scope so this
    module can be read (by the registry, by the palette) without dragging the OAuth dance
    into memory — the same containment `palette._prereqs` uses on its stores."""
    from aughor.integrations.broker import fresh_access_token
    return fresh_access_token(connection_id)


def _gate(gov_action: str, scope: str, *, actor: str, risk: str) -> str:
    """"" when the write may proceed, else the refusal sentence.

    Wraps the gate's ``HTTPException`` rather than letting it fly: this module's callers
    are an automation dispatcher and a route, and a 428 escaping into an engine loop
    would abort a chain where a refused step is the intended outcome.
    """
    from fastapi import HTTPException

    from aughor.govern.actions import ActionRisk, guard

    tier = {"low": ActionRisk.LOW, "high": ActionRisk.HIGH}.get(risk, ActionRisk.HIGH)
    try:
        guard(gov_action, scope, actor=actor, risk=tier)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return str(detail.get("hint") or "approval required for this write")
    return ""


def _send(op, url: str, query: dict, body: dict, *, token: str, token_type: str,
          service: str) -> CallResult:
    """The call itself, through the one outbound seam. Never raises."""
    from aughor.govern.outbound import OutboundBlocked, external_call

    headers = {"Authorization": f"{token_type or 'Bearer'} {token}",
               "Accept": "application/json"}
    try:
        with external_call(service, op.id,
                           attributes={"method": op.method,
                                       "writes": op.writes}) as extra:
            status, payload = _request(op.method, url, headers=headers, query=query,
                                       body=body)
            extra["http_status"] = status
    except OutboundBlocked as blocked:
        # Nothing was sent, so this is not "uncertain" and not a provider failure: the
        # budget refused it, and the same call is legitimate once the window rolls over.
        return CallResult("blocked", blocked.reason)
    except Exception as exc:
        # A transport failure MAY have delivered. For a write that distinction is the
        # difference between a retry and a duplicate, so it is carried, not flattened.
        logger.warning("integration %s unreachable: %s", op.id, exc)
        return CallResult("uncertain" if op.writes else "failed",
                          f"{service} was unreachable: {exc}")

    if not isinstance(payload, dict):
        payload = {}
    # Slack answers `200 {"ok": false, "error": …}`. A body-level failure read as success
    # is how an integration reports a message it never sent — the check `slackbots/post.py`
    # already carries, moved onto the operation as the provider fact it is.
    if status >= 400 or (op.ok_in_body and not payload.get("ok")):
        return CallResult("failed", _provider_error(payload, status), http_status=status)
    return CallResult("executed", "", data=payload, http_status=status)


def _provider_error(payload: dict, status: int) -> str:
    """The provider's own words, where it gave any — a sentence beats a status code.

    Bounded, because an error body is untrusted text that lands in a run history a person
    reads: Google returns prose, and an HTML error page from a proxy in front of an API is
    the classic way a 300 KB blob ends up in a stored automation run.
    """
    err = payload.get("error")
    if isinstance(err, dict):
        err = err.get("message") or err.get("status") or ""
    if not err:
        err = payload.get("error_description") or payload.get("message") or ""
    text = str(err or "").strip() or json.dumps(payload)[:200]
    return f"HTTP {status}: {text[:300]}" if status >= 400 else text[:300]


def _audit(action: str, scope: str, decision: str, actor: str, owner: str, detail: str,
           writes: bool) -> None:
    """One governed decision, attributed — best-effort, never the reason a call fails.

    The grant's OWNER rides in ``detail`` rather than in ``actor``: the actor is whoever
    caused the call (an agent, an automation, a person), the owner is whose consent is
    being spent, and collapsing the two would lose exactly the fact this record exists to
    keep. RC-4's lesson, one plane over.
    """
    try:
        from aughor.govern.actions import ActionRisk, audit
        audit(action, scope, decision, actor=actor,
              detail=f"grant of {owner or '(single-user install)'} · {detail}"[:500],
              risk=ActionRisk.HIGH if writes else ActionRisk.READ_ONLY)
    except Exception:
        logger.debug("integration audit skipped", exc_info=True)
