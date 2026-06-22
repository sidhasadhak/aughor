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
