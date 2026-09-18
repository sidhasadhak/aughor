"""The current-Workspace context — the sub-tenant key that rides every scoped READ.

The org contextvar (:mod:`aughor.org.context`) answers *which tenant*. This answers
*which sub-tenant within it*, and it exists for one reason: until now a workspace was
only ever a `workspace_id` query parameter threaded by hand into individual handlers.
That made the tenancy gate **opt-in** — `accessible_catalog_ids(None)` means unscoped,
so any caller who simply omitted the parameter saw every connection in the org. A
boundary a caller may decline is not a boundary.

Holding it in a contextvar — exactly like ``current_org_id()`` and ``current_job_id()``
— means a handler no longer has to remember. The gate reads the ambient workspace, so
a route added next year is scoped by default rather than by diligence.

**This module does not change behaviour on its own.** ``None`` still means unscoped, so
an install whose clients send no workspace behaves exactly as before; what changes is
that a client which DOES declare one has it applied everywhere instead of on the four
handlers that happened to take the parameter. Making a missing workspace fail closed is
a separate, deliberate flip — see ``require_workspace()``.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator, Optional

#: The active workspace for the running code. ``None`` means UNSCOPED — the caller
#: named no workspace, and org-wide visibility applies. It is deliberately not
#: defaulted to the default workspace: "no workspace was named" and "the default
#: workspace was named" are different facts, and collapsing them would silently scope
#: background work (schedulers, boot recovery) to one workspace's connections.
_current_workspace: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "aughor_current_workspace", default=None
)


def current_workspace_id() -> Optional[str]:
    """The workspace whose scope the current code runs under, or ``None`` if unscoped."""
    return _current_workspace.get()


def set_workspace_id(workspace_id: Optional[str]) -> "contextvars.Token[Optional[str]]":
    """Pin the current workspace; returns a token for :func:`reset_workspace_id`.

    An empty string normalises to ``None`` so a blank header reads as "unscoped"
    rather than as a workspace whose id is the empty string — which would fail closed
    against an unknown workspace and lock the caller out of everything.
    """
    return _current_workspace.set(workspace_id or None)


def reset_workspace_id(token: "contextvars.Token[Optional[str]]") -> None:
    try:
        _current_workspace.reset(token)
    except Exception as exc:  # reset across contexts is best-effort, like org.reset
        from aughor.kernel.errors import tolerate
        tolerate(exc, "workspace context reset", counter="workspace")


@contextmanager
def workspace_scope(workspace_id: Optional[str]) -> Iterator[None]:
    """Run a block under ``workspace_id``. Used by tests and by background work that
    acts on behalf of one workspace (a scheduled automation, a Slack bot's answer)."""
    token = set_workspace_id(workspace_id)
    try:
        yield
    finally:
        reset_workspace_id(token)
