"""DATA-06 on every door that names a connection (2026-09-14).

With identity on, a door that names a connection answers only the organisation that owns it. Before this, 175 of the
213 doors that named one never asked whose it was: a caller from one organisation read, edited and withdrew another
organisation's ontology by naming its connection (proven on the ontology doors first, `test_data06_tenant.py`).
`aughor.security.authz.connection_owner_guard` is now a router-level dependency on every router with such a door, so
a door added to one later is covered without anyone remembering to.

Both tests read the doors the app actually serves — the population is `aughor.api.app.routes`, never a hand list:
every door whose path or query names a connection depends on the guard (or is argued out below, with why), and
another organisation naming that connection is refused BY THE GUARD on each of them.
"""
from __future__ import annotations

import re

import pytest
from fastapi import HTTPException
from fastapi.dependencies.utils import get_flat_dependant
from fastapi.routing import APIRoute

from aughor.security.authz import Principal, connection_owner_guard
from starlette.requests import Request

#: Doors whose connection id is not a registry connection, each with why — argued here, never grown silently.
NOT_A_REGISTRY_CONNECTION = {
    "/integrations/connections/{conn_id}/revoke": "an integration grant, owned by its user (someone else's is a 404)",
    "/integrations/operations": "an integration grant's id scopes the operation roster to its provider",
}


def _names_a_connection(name: str) -> bool:
    return name in ("connection_id", "conn_id") or name.endswith("_connection_id")


def _doors() -> list[tuple[APIRoute, list[str]]]:
    from aughor.api import app
    found = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        flat = get_flat_dependant(route.dependant)
        named = [p.name for p in flat.path_params] + [p.alias for p in flat.query_params]
        if any(_names_a_connection(n) for n in named):
            found.append((route, named))
    return found


def _guarded(route: APIRoute) -> bool:
    return any(d.call is connection_owner_guard for d in route.dependant.dependencies)


def _door(route: APIRoute) -> str:
    return f"{sorted(route.methods)[0]} {route.path}"


def test_every_door_that_names_a_connection_depends_on_the_owner_guard():
    doors = _doors()
    assert len(doors) >= 150, len(doors)                              # the population is found in the app
    unguarded = sorted(_door(r) for r, _ in doors if r.path not in NOT_A_REGISTRY_CONNECTION and not _guarded(r))
    assert not unguarded, f"a door names a connection and never asks whose it is (DATA-06): {unguarded}"
    stale = sorted(set(NOT_A_REGISTRY_CONNECTION) - {r.path for r, _ in doors})
    assert not stale, f"no longer a door that names a connection — drop it from the exceptions: {stale}"


def _request(path_params: dict | None = None, query: str = "", principal: Principal | None = None) -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query.encode(),
                       "path_params": path_params or {}})
    if principal is not None:
        request.state.principal = principal
    return request


def test_the_guard_reads_every_name_a_connection_goes_by_in_the_path_and_the_query(tmp_path):
    """The guard itself, with no door behind it: fast, and a defect in the names it reads fails here rather than by
    letting the sweep below reach a real handler."""
    from aughor.db import registry
    from aughor.org.context import using_org

    with using_org("orgA"):
        theirs = registry.add_connection("orgA-names", "duckdb", str(tmp_path / "orgA.duckdb"))
    intruder = Principal(user_id="mallory", org_id="orgB")
    try:
        for request in (_request(path_params={"conn_id": theirs}, principal=intruder),
                        _request(path_params={"connection_id": theirs}, principal=intruder),
                        _request(query=f"conn_id={theirs}", principal=intruder),
                        _request(query=f"connection_id={theirs}", principal=intruder),
                        _request(query=f"reference_connection_id={theirs}", principal=intruder)):
            with pytest.raises(HTTPException) as refused:
                connection_owner_guard(request)
            assert refused.value.status_code == 403
        connection_owner_guard(_request(query=f"connection_ids={theirs}", principal=intruder))   # not a name it reads
        connection_owner_guard(_request(path_params={"conn_id": theirs}))                        # identity off
        connection_owner_guard(_request(path_params={"conn_id": theirs}, principal=Principal("ann", "orgA")))
    finally:
        registry.delete_connection(theirs)


def test_another_org_is_refused_by_the_guard_on_every_door_that_names_its_connection(client, monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    from aughor.db import registry
    from aughor.org.context import using_org

    with using_org("orgA"):
        theirs = registry.add_connection("orgA-doors", "duckdb", str(tmp_path / "orgA.duckdb"))
    answered = {}
    try:
        for route, named in _doors():
            if route.path in NOT_A_REGISTRY_CONNECTION or not _guarded(route):
                continue        # a door the guard does not hold is the test above's failure — never exercised here
            if route.path.endswith("/stream"):
                continue        # a stream that is NOT refused never ends; the structural test holds these doors
            url = route.path
            for param in re.findall(r"{([^}:]+)(?::[^}]+)?}", route.path):
                url = re.sub(r"{%s(?::[^}]+)?}" % re.escape(param), theirs if _names_a_connection(param) else "x", url)
            query = {n: theirs for n in named if _names_a_connection(n) and n not in route.param_convertors}
            method = sorted(route.methods)[0]
            r = client.request(method, url, params=query, headers={"X-Aughor-Org": "orgB"})
            answered[_door(route)] = (r.status_code, r.text[:100])
        assert len(answered) >= 140, len(answered)
        wrong = {door: got for door, got in answered.items() if got[0] != 403 or "belongs to another org" not in got[1]}
        assert not wrong, wrong
    finally:
        registry.delete_connection(theirs)
