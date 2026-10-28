"""Arc ED, ED-2 (ROADMAP §3.58) — every outside caller is someone.

Two halves. `security.principal_scopes`: a service principal a person minted may carry a grant — the areas it may work
in, the entities and declared actions it may name, the connections it may reach — that narrows the organisation's agent
policy on every request it makes, refused with a stable code, and its contract is cut to it. `mcp.caller_principals`:
over HTTP an outside program connects to the MCP server as that principal instead of with the server's shared token,
every call runs as it, and `tools/list` shows only what its grant admits.

The falsifier is ROADMAP's: two principals with different grants see the same `tools/list` → stop. It is driven here
through a real streamable-HTTP session against the real API in-process, not a list built by hand.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest

from aughor.mcp import callers
from aughor.mcp import policy as P
from aughor.mcp import server as S
from aughor.mcp.client import SERVICE_KEY_HEADER, SERVICE_NAME_HEADER, AughorClient
from aughor.security import service_principals as SP
from tests.unit.test_object_actions import db, graph  # noqa: F401 — fixtures by name


@pytest.fixture
def held(monkeypatch):
    monkeypatch.setenv("AUGHOR_SECURITY_PRINCIPAL_SCOPES", "1")
    monkeypatch.setenv("AUGHOR_MCP_CALLER_PRINCIPALS", "1")
    callers.forget()
    S.forget_policy()
    yield
    callers.forget()
    S.forget_policy()


def _mint(client, **grant) -> tuple[str, dict]:
    name = f"ed2-{uuid.uuid4().hex[:8]}"
    r = client.post("/ledger/v1/principals/service", json={"name": name, **grant})
    assert r.status_code == 201, r.text
    return name, {SP.NAME_HEADER: name, SP.KEY_HEADER: r.json()["key"]}


def test_the_mcp_client_spells_the_principal_headers_as_the_api_does():
    assert (SERVICE_NAME_HEADER, SERVICE_KEY_HEADER) == (SP.NAME_HEADER, SP.KEY_HEADER)


# ── the API: who a caller is ────────────────────────────────────────────────────

def test_the_api_says_who_a_presented_principal_is_and_refuses_a_bad_key(client, held):
    name, headers = _mint(client, areas=["catalog:read"], entities=["Order"])
    me = client.get("/ledger/v1/principals/service/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["principal"] == f"service:{name}" and me.json()["grant"]["areas"] == ["catalog:read"]
    bad = client.get("/ledger/v1/principals/service/me", headers={**headers, SP.KEY_HEADER: "not-the-key"})
    assert bad.status_code == 401
    assert client.get("/ledger/v1/principals/service/me").status_code == 404


def test_off_the_api_says_callers_are_off(client, held, monkeypatch):
    _, headers = _mint(client)
    monkeypatch.delenv("AUGHOR_MCP_CALLER_PRINCIPALS")
    r = client.get("/ledger/v1/principals/service/me", headers=headers)
    assert r.status_code == 404 and "off on this install" in r.json()["detail"]


def test_a_grant_is_kept_on_rotation_and_an_unknown_area_is_refused(client, held):
    name, _ = _mint(client, areas=["objects:read"], actions=["flag_order_for_review"])
    rotated = client.post("/ledger/v1/principals/service", json={"name": name})
    assert rotated.status_code == 201
    assert SP.grant(name)["areas"] == ["objects:read"] and SP.grant(name)["actions"] == ["flag_order_for_review"]
    refused = client.post("/ledger/v1/principals/service", json={"name": "ed2-bad-area", "areas": ["everything"]})
    assert refused.status_code == 422 and "everything" in refused.json()["detail"]


def test_a_principal_minted_without_a_grant_is_the_row_it_always_was():
    record, _ = SP.mint(f"ed2-plain-{uuid.uuid4().hex[:6]}", org_id="default", by="ana")
    assert not {"areas", "entities", "actions"} & set(record)


# ── the API: the grant narrows every request ────────────────────────────────────

def _refused(r) -> str:
    assert r.status_code == 403, (r.status_code, r.text)
    return r.json()["detail"]["code"]


def test_a_route_outside_the_grants_areas_is_refused_with_why(client, held):
    _, headers = _mint(client, areas=["ledger:read"])
    assert client.get("/ledger/v1/contract", headers=headers).status_code == 200
    detail = client.get("/jobs", headers=headers).json()["detail"]
    assert detail["code"] == P.CODE_AREA and "catalog:read" in detail["detail"] and "ledger:read" in detail["detail"]
    assert _refused(client.get("/ask/context", headers=headers)) == P.CODE_AREA        # a door in no area: closed


def test_an_entity_an_action_and_a_connection_off_the_grant_are_each_refused(client, held):
    """Through the builders' read doors, so the organisation's policy (`run`) admits each and the grant decides."""
    _, headers = _mint(client, areas=["objects:read"], entities=["Order"], actions=["flag_order_for_review"],
                       connections=["c1"])
    assert _refused(client.post("/objects/v1/list", params={"connection_id": "c1"}, headers=headers,
                                json={"entity": "Customer", "columns": ["name"]})) == P.CODE_ENTITY
    assert _refused(client.get("/ontology/v1/actions/cancel_order/schema", params={"connection_id": "c1"},
                               headers=headers)) == P.CODE_ACTION
    assert _refused(client.post("/objects/v1/list", params={"connection_id": "c2"}, headers=headers,
                                json={"entity": "Order", "columns": ["status"]})) == P.CODE_GRANT_CONNECTION
    within = client.post("/objects/v1/list", params={"connection_id": "c1"}, headers=headers,
                         json={"entity": "order", "columns": ["status"]})
    assert within.status_code != 403, within.text                      # past the gate: the door answers for itself


def test_off_the_grant_is_not_held(client, held, monkeypatch):
    _, headers = _mint(client, areas=["ledger:read"])
    monkeypatch.delenv("AUGHOR_SECURITY_PRINCIPAL_SCOPES")
    assert client.get("/jobs", headers=headers).status_code == 200


def test_the_contract_is_cut_to_the_grant():
    from aughor.rbac.principal_grant import narrow_contract
    contract = {"release": "r1", "entities": {"Order": {}, "Customer": {}}, "actions": {"flag": {}, "cancel": {}}}
    cut = narrow_contract(contract, {"entities": ["order"], "actions": ["flag"]})
    assert list(cut["entities"]) == ["Order"] and list(cut["actions"]) == ["flag"]
    assert cut["withheld"]["entities"] == 1 and cut["withheld"]["actions"] == 1
    assert narrow_contract(contract, {"entities": [], "actions": []}) is contract
    assert narrow_contract(contract, None) is contract


# ── the MCP server over HTTP: the falsifier ─────────────────────────────────────

def _session(tc, headers: dict, call_tool: str = "") -> list[str]:
    """One streamable-HTTP session: initialize, then tools/list — and, with ``call_tool``, that tool called. The tool
    names it lists."""
    base = {"accept": "application/json, text/event-stream", "content-type": "application/json", **headers}

    def call(body, sid=None):
        r = tc.post("/mcp/", json=body, headers={**base, **({"mcp-session-id": sid} if sid else {})})
        return r

    def payload(r):
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            data = [line[5:].strip() for line in r.text.splitlines() if line.startswith("data:")]
            return json.loads(data[-1])
        return r.json()

    init = call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "ed2", "version": "0"}}})
    assert init.status_code == 200, (init.status_code, init.text)
    sid = init.headers.get("mcp-session-id")
    call({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    listed = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    assert listed.status_code == 200, listed.text
    if call_tool:
        ran = call({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": call_tool, "arguments": {}}}, sid)
        assert ran.status_code == 200, ran.text
    return sorted(t["name"] for t in payload(listed)["result"]["tools"])


def test_two_principals_with_different_grants_list_different_tools(client, held, monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app
    monkeypatch.setattr(S, "_client", AughorClient(base_url="http://api", transport=httpx.ASGITransport(app=app)))
    reader_name, reader = _mint(client, areas=["catalog:read"])
    _, ledger = _mint(client, areas=["ledger:read", "ledger:write"])
    gate = S.http_app("the-shared-token", "127.0.0.1")
    with TestClient(gate, base_url="http://127.0.0.1:8765") as tc:
        mine = _session(tc, reader, call_tool="list_connections")
        theirs = _session(tc, ledger)
        shared = _session(tc, {"authorization": "Bearer the-shared-token"})
        assert mine and theirs and mine != theirs
        assert set(mine) <= {n for n, a in P.TOOL_AREAS.items() if a == "catalog:read"} and "list_connections" in mine
        assert set(theirs) == {"read_contract", "read_claims", "read_restatements", "post_claim"}
        assert set(mine) | set(theirs) < set(shared)                     # the shared token: the policy's whole list
        # the call ran as the caller, not as this process: the API audited it under the principal's own name
        from aughor.kernel.ledger import Ledger
        audited = [e for e in Ledger.default().events(kind="mcp.tool_call", limit=50)
                   if (e.get("payload") or {}).get("tool") == "list_connections"]
        assert audited and (audited[0]["payload"] or {}).get("principal") == f"service:{reader_name}", audited[:1]
        stranger = tc.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                           headers={**reader, SP.KEY_HEADER: "a-guessed-key", "authorization": "Bearer the-shared-token",
                                    "accept": "application/json, text/event-stream"})
        assert stranger.status_code == 401 and "do not match" in stranger.json()["detail"]


def test_a_principal_reads_the_contract_its_grant_names(client, held, graph, monkeypatch):  # noqa: F811
    """The builders' contract door, on the samples ontology: the entities and declared actions the grant names, and a
    count of what it left out."""
    from tests.unit.test_object_actions import CONN
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    _, headers = _mint(client, areas=["objects:read"], entities=["Order"])
    whole = client.get("/ontology/v1/contract", params={"connection_id": CONN})
    cut = client.get("/ontology/v1/contract", params={"connection_id": CONN}, headers=headers)
    assert whole.status_code == cut.status_code == 200, (whole.text, cut.text)
    assert len(whole.json()["entities"]) > 1 and list(cut.json()["entities"]) == ["Order"]
    assert cut.json()["withheld"]["entities"] == len(whole.json()["entities"]) - 1
    ts = client.get("/ontology/v1/types.d.ts", params={"connection_id": CONN}, headers=headers)
    assert ts.status_code == 200 and "interface Order" in ts.text and "interface Customer" not in ts.text
