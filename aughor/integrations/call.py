"""VA-11 consumer — the one path that SPENDS a grant.

`fresh_access_token()` had no callers. This module is its only production caller, and
deliberately the only one: refresh policy, the scope check, the cap, the span and the
audit line all live on this path, so a second consumer added later inherits every one of
them by construction rather than by remembering.

The order is the design, and it is `govern.outbound`'s order one level up:

1. **Refusals that need no network happen first** — unknown operation, unknown grant,
   a grant for a different provider, a missing required param, a scope the user never
   consented to. Each is a sentence naming what to fix. Spending a token to be told this
   by the provider would be slower, less specific, and would burn a cap on a call that
   was never going to work.
2. **The token is fetched through the broker**, never read off the record — that is the
   one place refresh-before-expiry lives, and a caller with its own copy of the token is
   a caller with its own copy of the expiry rule.
3. **The call is wrapped in `govern.outbound.external_call`**, which checks the usage cap
   BEFORE the request, opens the span the run's waterfall reads, and records the
   `EXTERNAL_CALL` session event that makes it countable.
4. **The response is mapped by the operation's own mapper** into chain context. The raw
   provider body never leaves this module: a chain step publishes declared keys, not a
   vendor's JSON, because a later step binding `{"$from": "step1.payload"}` would post
   whatever the provider happened to return into whatever the chain happened to reach.

Nothing here decides WHETHER a user may hold a grant — that is the vault's question and
it was answered when they consented. This decides what a held grant may be spent on, and
says so out loud in an audit line attributed to the grant's owner.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote, urlencode

from aughor.integrations.models import Connection
from aughor.integrations.operations import Operation, get_operation, scope_granted

logger = logging.getLogger("aughor.integrations")

#: Reads are given longer than the OAuth dance: a mailbox query is a provider-side search,
#: not a token exchange. Still bounded — an automation step that hangs holds a worker.
TIMEOUT_SECONDS = 30.0


class CallRefused(Exception):
    """This call was not made, and the sentence says what to fix.

    Distinct from a call that WAS made and failed: the caller renders the two as
    different outcomes, because "your grant is missing a scope" is fixed by a person and
    "the provider returned 503" is fixed by waiting.
    """


class CallParamsMissing(CallRefused):
    """A required param of this operation is empty at the moment of the call.

    A subclass because callers refuse it the same way but REPORT it differently: an
    automation step records `invalid_params`, which is the status this plane already uses
    for "the step was asked to do something it cannot", and which reads on a run canvas as
    the author's problem rather than the provider's.
    """


class CallFailed(Exception):
    """The call was made and the provider refused or errored. ``status`` is its HTTP code."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _get(url: str, token: str) -> tuple[int, dict]:
    """One authorized GET, JSON back. A seam on purpose — tests replace THIS, so the
    resolution, scope and mapping logic above it is exercised for real while nothing
    leaves the machine (the same seam `broker._post` is, for the same reason)."""
    import httpx
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/json"},
                     timeout=TIMEOUT_SECONDS)
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body if isinstance(body, dict) else {}


def _provider_error(status: int, body: dict) -> str:
    """The provider's own words for why it refused, or an honest fallback.

    Google and Graph both nest under `error`; Google's is an object with `message`,
    Graph's is an object with `message` too, and some edges return a bare string. Read
    all three shapes rather than the one this week's fixture happened to have.
    """
    err = body.get("error")
    if isinstance(err, dict):
        detail = err.get("message") or err.get("code") or ""
        if detail:
            return str(detail)
    elif isinstance(err, str) and err:
        return err
    return f"HTTP {status}"


def build_url(operation: Operation, params: dict[str, Any]) -> str:
    """The request URL for this operation and these params.

    Path placeholders are percent-encoded per segment and query values are urlencoded, so
    a param carrying a slash or an ampersand cannot reach outside the shape this row
    declares. The host and path are constants of `operations.py` — authored config
    chooses the ROW, never the destination.
    """
    path = operation.path
    query: list[tuple[str, str]] = [(k, v) for k, v in operation.fixed_query]
    for param in operation.params:
        raw = params.get(param.name, param.default)
        value = "" if raw is None else str(raw)
        if param.in_path:
            path = path.replace("{" + param.name + "}", quote(value, safe=""))
        elif param.query_key and value != "":
            query.append((param.query_key, value))
    return f"{path}?{urlencode(query)}" if query else path


def _missing_params(operation: Operation, params: dict[str, Any]) -> list[str]:
    return [p.label for p in operation.params
            if p.required and not str(params.get(p.name, "") or "").strip()]


def resolve(operation_id: str, grant_id: str) -> tuple[Operation, Connection]:
    """The operation and the grant, or :class:`CallRefused` naming which one is wrong.

    Public because the AUTHORING surfaces need exactly this check without making a call:
    an automation is refused at save when it names an operation that does not exist, and
    the palette dims a row when no grant can run it.
    """
    from aughor.integrations.store import get_connection

    operation = get_operation(operation_id)
    if operation is None:
        raise CallRefused(f"unknown operation: {operation_id}")
    conn = get_connection(grant_id)
    if conn is None:
        raise CallRefused(f"unknown connection: {grant_id}")
    if conn.provider != operation.provider:
        # A grant for the wrong provider would spend a Google token against Graph and be
        # told so in a 401 that names neither. Say it here, where both names are known.
        raise CallRefused(
            f"'{operation.label}' needs a {operation.provider} connection, but "
            f"{grant_id} is a {conn.provider} one")
    if conn.status == "revoked":
        raise CallRefused("this connection was revoked")
    if conn.status == "needs_reconnect":
        raise CallRefused("this connection needs the user to reconnect — the provider "
                          "refused its refresh")
    if not scope_granted(operation, conn.scopes):
        raise CallRefused(
            f"this {conn.provider} connection was not granted '{operation.scope}' — "
            f"reconnect and consent to it before '{operation.label}' can run")
    return operation, conn


def call(operation_id: str, grant_id: str,
         params: Optional[dict[str, Any]] = None) -> dict:
    """Run one declared operation under one user's grant; return its published keys.

    Raises :class:`CallRefused` when the call was not made, :class:`CallFailed` when it
    was and the provider refused, and lets `govern.outbound.OutboundBlocked` through
    untouched — a usage cap is the platform's own refusal and deserves its own name at
    the call site, not a paraphrase inside a third exception.
    """
    from aughor.govern.outbound import external_call
    from aughor.integrations.broker import BrokerError, fresh_access_token

    params = dict(params or {})
    operation, conn = resolve(operation_id, grant_id)

    missing = _missing_params(operation, params)
    if missing:
        raise CallParamsMissing(f"'{operation.label}' needs {', '.join(missing)}")

    try:
        token = fresh_access_token(conn.id)
    except BrokerError as exc:
        # The broker's refusals are already sentences a person can act on (it says so in
        # its own docstring); re-wording them here would give the same condition two
        # spellings depending on which caller hit it.
        raise CallRefused(str(exc)) from exc

    url = build_url(operation, params)
    with external_call(operation.provider, operation_id,
                       attributes={"connection": conn.id}) as extra:
        status, body = _get(url, token)
        extra["ok"] = 200 <= status < 300
        extra["status"] = status
        if not (200 <= status < 300):
            # Raised INSIDE the context so the span and the session event record the
            # failure. A provider error recorded only on the success path is how a
            # failing counterparty stays invisible in exactly the week it matters.
            raise CallFailed(_provider_error(status, body), status=status)

    _audit(operation, conn)
    return operation.respond(body)


def _audit(operation: Operation, conn: Connection) -> None:
    """The grant was spent, and by whom — best-effort, never the reason a call fails."""
    try:
        from aughor.govern.actions import audit
        audit("integration.call", scope=operation.provider, decision="executed",
              actor=conn.user_id, detail=f"{operation.id} via connection {conn.id}")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "integration call audit is best-effort", counter="integration.audit")
