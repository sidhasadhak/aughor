"""The current-Org context — the tenant key that rides every persisted write.

Aughor is single-org today but *tenant-shaped*: every persisted object carries an
``org_id`` from day one (PLATFORM_ARCHITECTURE.md, Invariant #1) so multi-tenant
becomes a config flip, not a migration. The org for the running code is held in a
contextvar — exactly like ``current_job_id()`` in ``kernel/jobs.py`` — so data-path,
audit and metering writes can stamp it ambiently without threading an ``org_id``
parameter through every call chain. It defaults to ``DEFAULT_ORG_ID`` so unscoped
code (and a fresh single-org install) behaves identically.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator

# The single bootstrap tenant. Every store defaults its org_id column to this, and
# the contextvar below resolves to it whenever no org has been explicitly set.
DEFAULT_ORG_ID = "default"

_current_org: contextvars.ContextVar[str] = contextvars.ContextVar(
    "aughor_current_org", default=DEFAULT_ORG_ID
)


def current_org_id() -> str:
    """The org whose tenant scope the current code runs under (never empty)."""
    return _current_org.get() or DEFAULT_ORG_ID


def set_org_id(org_id: str) -> "contextvars.Token[str]":
    """Pin the current org; returns a token for :func:`reset_org_id`. An empty/None
    org falls back to ``DEFAULT_ORG_ID`` so the contextvar is never blank."""
    return _current_org.set(org_id or DEFAULT_ORG_ID)


def reset_org_id(token: "contextvars.Token[str]") -> None:
    try:
        _current_org.reset(token)
    except Exception as exc:  # reset across contexts is best-effort, like metering.reset
        from aughor.kernel.errors import tolerate
        tolerate(exc, "org context reset", counter="org")


@contextmanager
def using_org(org_id: str) -> Iterator[str]:
    """Scope a block to ``org_id`` and restore the prior org on exit."""
    token = set_org_id(org_id)
    try:
        yield current_org_id()
    finally:
        reset_org_id(token)


# ── Current user (for row-level policy — RBAC row filters keyed by the caller) ──
# Set alongside the org by the per-request identity middleware; defaults to empty so
# unscoped code and localhost behave identically.
_current_user: contextvars.ContextVar[str] = contextvars.ContextVar("aughor_current_user", default="")


def current_user_id() -> str:
    """The identified caller's user id, or "" when unidentified (localhost / no identity)."""
    return _current_user.get() or ""


def set_user_id(user_id: str) -> "contextvars.Token[str]":
    """Pin the current user id; returns a token for :func:`reset_user_id`."""
    return _current_user.set(user_id or "")


def reset_user_id(token: "contextvars.Token[str]") -> None:
    try:
        _current_user.reset(token)
    except Exception as exc:  # best-effort, like reset_org_id
        from aughor.kernel.errors import tolerate
        tolerate(exc, "user context reset", counter="org")


# ── The acting person (who a write is recorded under) ───────────────────────────
# Set on EVERY request by the API's context middleware, identity enforced or not: the signed-in
# person when there is one, else this install's own login. Kept apart from `_current_user`, which
# the RBAC row policy reads and which must stay empty when identity is off. Empty outside a
# request (a schedule, an automation run), where the caller names itself.
_current_actor: contextvars.ContextVar[str] = contextvars.ContextVar("aughor_current_actor", default="")


def current_actor() -> str:
    """Who the running request acts for, or "" outside a request. Never read from a request body:
    a person approving a metric or confirming its dates is the person signed in, not a name typed."""
    return _current_actor.get() or ""


def set_actor(actor: str) -> "contextvars.Token[str]":
    return _current_actor.set(actor or "")


def reset_actor(token: "contextvars.Token[str]") -> None:
    try:
        _current_actor.reset(token)
    except Exception as exc:  # best-effort, like reset_org_id
        from aughor.kernel.errors import tolerate
        tolerate(exc, "actor context reset", counter="org")


# ── Current session (correlates the turns of one conversation) ─────────────────
# Unlike org/user (header-derived, pinned by the identity middleware), the session
# id rides the request BODY (AskRequest.session_id), so it is pinned by the /ask
# stream itself. Holding it in a contextvar lets the telemetry seam attribute a
# trace to its conversation session ambiently — no threading through the graph —
# and it propagates into the deep-run job + parallel waves like org/user do.
_current_session: contextvars.ContextVar[str] = contextvars.ContextVar("aughor_current_session", default="")


def current_session_id() -> str:
    """The conversation session id for the running code, or "" when none."""
    return _current_session.get() or ""


def set_session_id(session_id: str) -> "contextvars.Token[str]":
    """Pin the current session id; returns a token for :func:`reset_session_id`."""
    return _current_session.set(session_id or "")


def reset_session_id(token: "contextvars.Token[str]") -> None:
    try:
        _current_session.reset(token)
    except Exception as exc:  # best-effort, like reset_org_id
        from aughor.kernel.errors import tolerate
        tolerate(exc, "session context reset", counter="org")
