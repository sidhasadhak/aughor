"""Track A4 (docs/TENX_PROGRAM_2026-11-05.md §1.1): ownership has five answers, and only two allow.

Until 2026-11-05 `authorize_resource` returned True whenever the owner resolved to None — a shared
builtin, a missing id, a kind nobody registered a resolver for, and a resolver that raised were all
the same None, and all allowed. The rule here is PipesHub's (`docs/connectors/06-permissions.md`):
unknown is not empty, and a check that cannot answer refuses rather than returning full or empty.

The population is the REGISTRY's, not a hand-written list: every registered kind is driven through
a resolver that raises, so a kind added later is covered without anyone remembering to.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor.kernel.registries import resource_org as rreg
from aughor.security.authz import Ownership, Principal, authorize_resource, check_owner, resolve_ownership

ACME = Principal(user_id="amit", org_id="a4-acme")


@pytest.fixture
def probe_kind():
    """A kind of this test's own, unregistered again afterwards so the agent's resolvers stay."""
    kind = "a4-probe"
    yield kind
    rreg._RESOLVERS.pop(kind, None)
    rreg._ORG_RESOLVERS.pop(kind, None)


def test_localhost_owns_everything():
    assert resolve_ownership("connection", "whatever", None) is Ownership.OWNED
    assert authorize_resource("connection", "whatever", None) is True


def test_a_kind_without_a_resolver_is_unresolved_and_refused():
    assert resolve_ownership("no-such-kind", "x1", ACME) is Ownership.UNRESOLVED
    assert authorize_resource("no-such-kind", "x1", ACME) is False
    with pytest.raises(HTTPException) as exc:
        check_owner("no-such-kind", "x1", ACME)
    assert exc.value.status_code == 503 and "refusing rather than guessing" in exc.value.detail


def test_every_registered_resolver_that_raises_is_refused_not_allowed():
    """The property, over the live registry: no kind's failure reads as 'no owner'."""
    kinds = rreg.registered_kinds()
    assert kinds, "the agent registered nothing — the population is empty, so this test proves nothing"
    saved_conn, saved_org = dict(rreg._RESOLVERS), dict(rreg._ORG_RESOLVERS)
    try:
        def _boom(_id):
            raise RuntimeError("store unreachable")
        for kind in kinds:
            if kind in rreg._ORG_RESOLVERS:
                rreg.register_resource_org_resolver(kind, _boom)
            else:
                rreg.register_resource_conn_resolver(kind, _boom)
            assert resolve_ownership(kind, "r1", ACME) is Ownership.UNRESOLVED, kind
            assert authorize_resource(kind, "r1", ACME) is False, kind
    finally:
        rreg._RESOLVERS.clear(); rreg._RESOLVERS.update(saved_conn)
        rreg._ORG_RESOLVERS.clear(); rreg._ORG_RESOLVERS.update(saved_org)


def test_missing_shared_own_and_foreign_through_a_conn_resolver(probe_kind, monkeypatch):
    table = {"mine": "conn-acme", "theirs": "conn-globex", "builtin": "workspace", "gone": "conn-deleted"}
    rreg.register_resource_conn_resolver(probe_kind, lambda rid: table.get(rid))
    orgs = {"conn-acme": "a4-acme", "conn-globex": "a4-globex"}
    monkeypatch.setattr("aughor.db.registry.get_connection_org", lambda cid: orgs.get(cid))
    monkeypatch.setattr("aughor.db.registry.is_registered", lambda cid: cid in orgs or cid == "workspace")

    assert resolve_ownership(probe_kind, "mine", ACME) is Ownership.OWNED
    assert resolve_ownership(probe_kind, "theirs", ACME) is Ownership.FOREIGN
    assert resolve_ownership(probe_kind, "builtin", ACME) is Ownership.SHARED     # by record: a builtin id
    assert resolve_ownership(probe_kind, "gone", ACME) is Ownership.NOT_FOUND     # its connection is gone
    assert resolve_ownership(probe_kind, "unknown-id", ACME) is Ownership.NOT_FOUND
    assert resolve_ownership(probe_kind, "", ACME) is Ownership.NOT_FOUND

    with pytest.raises(HTTPException) as foreign:
        check_owner(probe_kind, "theirs", ACME)
    assert foreign.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        check_owner(probe_kind, "unknown-id", ACME)
    assert missing.value.status_code == 404 and "or not yours" in missing.value.detail
    check_owner(probe_kind, "mine", ACME)
    check_owner(probe_kind, "builtin", ACME)


def test_an_org_resolver_says_shared_with_an_empty_string_and_missing_with_none(probe_kind):
    rreg.register_resource_org_resolver(probe_kind, {"d1": "a4-acme", "d2": "a4-globex", "d3": ""}.get)
    assert resolve_ownership(probe_kind, "d1", ACME) is Ownership.OWNED
    assert resolve_ownership(probe_kind, "d2", ACME) is Ownership.FOREIGN
    assert resolve_ownership(probe_kind, "d3", ACME) is Ownership.SHARED
    assert resolve_ownership(probe_kind, "d4", ACME) is Ownership.NOT_FOUND


def test_a_connection_that_is_not_here_is_not_found_and_a_builtin_is_shared(monkeypatch):
    monkeypatch.setattr("aughor.db.registry.get_connection_org", lambda cid: None)
    monkeypatch.setattr("aughor.db.registry.is_registered", lambda cid: cid == "workspace")
    assert resolve_ownership("connection", "workspace", ACME) is Ownership.SHARED
    assert resolve_ownership("connection", "never-added", ACME) is Ownership.NOT_FOUND


def test_the_domain_carrier_is_the_ontologys_own_spelling():
    """authz spells the carrier itself (the platform must not import the agent); this keeps the two one."""
    from aughor.ontology.overrides import DOMAIN_CARRIER as theirs
    from aughor.security.authz import DOMAIN_CARRIER as ours
    assert ours == theirs
    assert resolve_ownership("connection", f"{ours}default", ACME) is Ownership.SHARED
