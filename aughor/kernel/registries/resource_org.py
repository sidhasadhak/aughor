"""Resource → connection resolver registry — invert object-level authz's reach into
the agent's stores.

Object-level authorization (``security/authz.py``) resolves a resource's tenant by
mapping the resource to its owning connection, then the connection to its org —
``connections`` is the one platform table that carries ``org_id`` (DATA-06). The
platform-owned resources (connection, canvas, investigation) resolve inline, but the
agent-owned ones (monitor, alert, brief subscription) live in agent stores the
platform must NEVER import (the Platform↔Agent boundary). So each of those stores
registers a ``kind -> (resource_id -> conn_id | None)`` resolver here at startup
(``agent.bootstrap.register_agent_plugins``); ``authz`` consults the registry for any
kind it doesn't resolve itself.

With nothing registered the platform cannot own-check those kinds — and since Track A4
(2026-11-05) ``authz`` says so and REFUSES, rather than reading an unresolvable owner
as "allow": a kind without a resolver is ``UNRESOLVED``, a resolver that raises is
``UNRESOLVED`` (the failure is logged and counted here, then re-raised so the caller
cannot mistake it for "no owner"), and ``None`` from a resolver means exactly one
thing: the resource does not exist. Never for the localhost/identity-off path, which
short-circuits before resolution.
"""
from __future__ import annotations

from typing import Callable, Optional

from aughor.kernel.errors import tolerate

ConnResolver = Callable[[str], Optional[str]]

_RESOLVERS: dict[str, ConnResolver] = {}


def register_resource_conn_resolver(kind: str, fn: ConnResolver) -> None:
    """Register a resolver mapping a resource id of ``kind`` to its connection id
    (or None when unknown). Last registration for a kind wins (idempotent re-wire)."""
    _RESOLVERS[kind] = fn


def resolves_conn(kind: str) -> bool:
    return kind in _RESOLVERS


def resolve_resource_conn(kind: str, resource_id: str) -> Optional[str]:
    """The connection id owning a resource, via the registered resolver; ``None`` when the resource
    does not exist. Raises ``LookupError`` when no resolver is registered for the kind, and re-raises
    a resolver's own failure after logging it — neither is "no owner"."""
    fn = _RESOLVERS.get(kind)
    if fn is None:
        raise LookupError(f"no connection resolver is registered for {kind!r}")
    try:
        return fn(resource_id)
    except Exception as e:
        tolerate(e, f"resource-conn resolver {kind!r}", counter=f"authz.resolver.{kind}")
        raise


OrgResolver = Callable[[str], Optional[str]]

#: Resources that carry their OWN owner rather than a connection's — an uploaded document belongs to the
#: organisation that indexed it, whatever connection it was indexed beside (PENDING item 16). Consulted before
#: the connection resolvers; a registered kind's answer stands, even when it is None (a shared resource).
_ORG_RESOLVERS: dict[str, OrgResolver] = {}


def register_resource_org_resolver(kind: str, fn: OrgResolver) -> None:
    """Register a resolver mapping a resource id of ``kind`` straight to its owning org id (None when shared or
    unknown). Last registration for a kind wins."""
    _ORG_RESOLVERS[kind] = fn


def resolves_org(kind: str) -> bool:
    return kind in _ORG_RESOLVERS


def resolve_resource_org(kind: str, resource_id: str) -> Optional[str]:
    """The org owning a resource, via its registered org resolver: an org id, ``""`` for a resource that
    belongs to no organisation by record (shared), ``None`` for one that does not exist. Raises
    ``LookupError`` when no resolver is registered, and re-raises a resolver's failure after logging it."""
    fn = _ORG_RESOLVERS.get(kind)
    if fn is None:
        raise LookupError(f"no org resolver is registered for {kind!r}")
    try:
        return fn(resource_id)
    except Exception as e:
        tolerate(e, f"resource-org resolver {kind!r}", counter=f"authz.org_resolver.{kind}")
        raise


def registered_kinds() -> list[str]:
    """The resource kinds an agent has plugged in a resolver for (for the manifest)."""
    return sorted(set(_RESOLVERS) | set(_ORG_RESOLVERS))


def clear() -> None:
    """Drop every registered resolver (idempotent re-registration / test isolation)."""
    _RESOLVERS.clear()
    _ORG_RESOLVERS.clear()
