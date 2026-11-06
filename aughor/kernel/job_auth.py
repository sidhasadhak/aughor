"""The authority a job runs on — written once, when it is submitted (Track C1).

A job outlives the request that started it: it queues, runs, pauses, resumes after a restart. Until
2026-11-06 the job row carried its organisation and nothing else (``jobs.org_id``), so nobody could
say whose authority a running job was spending, with which roles, under which policy — and nothing
could re-check it later. The 10× program's Track C (`docs/TENX_PROGRAM_2026-11-05.md` §3) puts that
authority on the row, immutably; C2 will re-evaluate it at every effect (a send, an export, an action).

What is recorded, and nothing more than is known:

* ``person`` — who the job acts for: the identified caller when identity is enforced; the install's
  operator when it is not (one person owns the install); EMPTY when identity is enforced and no
  request named anyone — a clock, boot recovery, the platform itself. Empty is said, never filled in.
* ``org`` — the tenant the job runs in (the same value as ``jobs.org_id``).
* ``verified_by`` — how the person was known: ``oidc``, ``service principal``, ``proxy`` (a declared
  authenticating proxy), ``sign-in off`` (the operator, unverified by design), or ``none``.
* ``roles`` — the person's roles at submit; ``[]`` when there is no person.
* ``policy`` — the version of the route permission table (:func:`aughor.rbac.policy.policy_version`),
  so a later check can tell the rules changed under a waiting job.
* ``purpose`` — the job's kind; ``at`` — when the authority was taken.
"""
from __future__ import annotations

from typing import Optional


def job_auth_context(kind: str, org_id: Optional[str] = None) -> dict:
    """The authority a job submitted NOW runs on, from the request (or its absence) in context."""
    from aughor.org.context import current_actor, current_org_id, current_user_id
    from aughor.rbac.policy import policy_version
    from aughor.security.authz import Principal, identity_from_proxy, local_operator, require_identity_enabled
    from aughor.security.service_principals import PREFIX
    from aughor.util.time import now_iso_z

    org = org_id or current_org_id()
    if not require_identity_enabled():
        person, verified_by = current_actor() or local_operator(), "sign-in off"
    else:
        person = current_user_id()
        if not person:
            verified_by = "none"
        elif person.startswith(PREFIX):
            verified_by = "service principal"
        else:
            from aughor.security import oidc
            verified_by = "oidc" if oidc.configured() else "proxy" if identity_from_proxy() else "none"
    roles: list[str] = []
    if person:
        from aughor.rbac.resolver import resolve_roles
        roles = resolve_roles(Principal(user_id=person, org_id=org) if require_identity_enabled() else None)
    return {"person": person, "org": org, "verified_by": verified_by, "roles": roles,
            "policy": policy_version(), "purpose": kind, "at": now_iso_z()}
