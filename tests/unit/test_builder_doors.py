"""Arc OC-8 — doors for builders: the published ontology as a contract an outside program reads, lists and proposes on.

Held on the seeded samples warehouse through the real doors: the contract's schemas say what an Order holds and what
*Flag for review* takes; the TypeScript declares the same; a listing reads objects; a proposal is checked against the
action's schema and its own criteria, staged for a person and never run; a contract that moved refuses a stale
proposal. The MCP server offers one propose tool per declared action with the action's own schema, and an Ossie model
is read as proposals a person accepts — nothing declared until they do. With the flag off every door says it is off.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.actions import overlay as OVL
from aughor.actions.inbox import list_proposals
from aughor.ontology.builder_doors import action_schema, ontology_contract, typescript, validate_params
from tests.unit.test_object_actions import CONN, ORDER, _action, _declare, db, graph  # noqa: F401 — fixtures by name

PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def doors(graph, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AUGHOR_ONTOLOGY_BUILDER_DOORS", "1")
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    return graph


def test_the_contract_says_what_an_object_holds_and_what_a_proposal_carries(graph):  # noqa: F811
    contract = ontology_contract(graph, f"{CONN}/ecommerce@3")
    order = contract["entities"]["Order"]
    assert order["required"] == ["order_id"] and order["x-aughor"]["key"] == "order_id"
    assert order["properties"]["total_amount"]["anyOf"][0]["type"] == "number"
    assert order["properties"]["order_date"]["anyOf"] == [{"type": "string", "format": "date"}, {"type": "null"}]
    flag = contract["actions"]["flag_order_for_review"]
    assert flag["properties"]["order"]["pattern"] == "^order:.+$" and set(flag["required"]) == {"order", "reason"}
    assert flag["x-aughor"] == {"action": "flag_order_for_review", "kind": "annotate", "risk": "low",
                                "object_type": "order", "creates": "", "sets": ["review_flag"],
                                "release": f"{CONN}/ecommerce@3", "proposes_only": True}
    ts = typescript(contract)
    assert f'export type Release = "{CONN}/ecommerce@3";' in ts
    assert "export interface Order {" in ts and "  order_id: string;" in ts and "  total_amount: number | null;" in ts
    assert "export interface FlagOrderForReviewParams {" in ts and "export type ActionId = 'flag_order_for_review';" in ts


def test_the_declarations_compile_and_a_program_written_against_them_does(graph, tmp_path):  # noqa: F811
    """The live receipt found `export const RELEASE = … as const` in a .d.ts — which TypeScript refuses. Compiled here
    with the web's own tsc, where it is installed."""
    import pathlib
    import subprocess
    tsc = pathlib.Path(__file__).resolve().parents[2] / "web" / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        pytest.skip("the web's TypeScript is not installed here")
    (tmp_path / "shop.d.ts").write_text(typescript(ontology_contract(graph, f"{CONN}/ecommerce@3")))
    (tmp_path / "use.ts").write_text(
        'import type { ActionId, FlagOrderForReviewParams, Order, OrderSegment, Release } from "./shop";\n'
        f'export const release: Release = "{CONN}/ecommerce@3";\n'
        'export const action: ActionId = "flag_order_for_review";\n'
        'export const segment: OrderSegment | undefined = undefined;\n'
        'export const params = (o: Pick<Order, "order_id">): FlagOrderForReviewParams =>\n'
        '  ({ order: `order:${o.order_id}`, reason: "late" });\n')
    ran = subprocess.run([str(tsc), "--noEmit", "--strict", "--target", "es2020", "--moduleResolution", "node",
                          str(tmp_path / "use.ts")], capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0, ran.stdout + ran.stderr


def test_an_action_declared_on_Order_asks_for_the_name_a_listing_hands_out(graph):  # noqa: F811
    """theLook's Flag for review names its type `Order`; its listing names objects `order:<key>` — the contract must ask
    for what the listing gives, or a program that follows it is refused."""
    action = _action(graph).model_copy(deep=True)
    action.object_type = action.params[0].object_type = "Order"
    schema = action_schema(action, "", graph)
    assert schema["properties"]["order"]["pattern"] == "^order:.+$" and schema["x-aughor"]["object_type"] == "order"
    assert validate_params(schema, {"order": f"order:{ORDER}", "reason": "late"}) is None


def test_a_proposal_that_does_not_fit_the_action_is_refused_in_words(graph):  # noqa: F811
    schema = action_schema(_action(graph), "")
    assert "takes no parameter 'priority'" in validate_params(schema, {"order": "order:1", "reason": "x", "priority": 1})
    assert "needs 'reason'" in validate_params(schema, {"order": "order:1"})
    assert "names an object as order:.+" in validate_params(schema, {"order": "customer:1", "reason": "x"})
    assert validate_params(schema, {"order": f"order:{ORDER}", "reason": "late"}) is None


def test_with_the_flag_off_every_door_says_it_is_off(graph, client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("AUGHOR_ONTOLOGY_BUILDER_DOORS", raising=False)
    for method, path in (("get", "/ontology/v1/contract"), ("get", "/ontology/v1/types.d.ts"),
                         ("post", "/objects/v1/list"), ("post", "/objects/v1/actions/flag_order_for_review/propose")):
        body = {"entity": "Order"} if path.endswith("list") else {"params": {}}
        r = getattr(client, method)(path, params=PARAMS, **({"json": body} if method == "post" else {}))
        assert r.status_code == 404 and "doors for builders are off" in r.json()["detail"], path


def test_a_program_lists_objects_and_proposes_an_action_a_person_then_decides(doors, db, client):  # noqa: F811
    contract = client.get("/ontology/v1/contract", params=PARAMS)
    assert contract.status_code == 200 and "flag_order_for_review" in contract.json()["actions"]
    ts = client.get("/ontology/v1/types.d.ts", params=PARAMS)
    assert ts.status_code == 200 and "export interface Order {" in ts.text
    page = client.post("/objects/v1/list", params=PARAMS, json={"entity": "Order", "columns": ["status"], "limit": 3})
    assert page.status_code == 200 and page.json()["path"] == "listed" and len(page.json()["rows"]) == 3
    named = page.json()["objects"]                                            # as a proposal names them
    assert named == [f"order:{r[0]}" for r in page.json()["rows"]]
    assert validate_params(action_schema(_action(doors), ""), {"order": named[0], "reason": "x"}) is None
    proposed = client.post("/objects/v1/actions/flag_order_for_review/propose", params=PARAMS,
                           json={"params": {"order": f"order:{ORDER}", "reason": "late and unshipped"},
                                 "reasoning": "a script found it overdue"})
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["status"] == "awaiting_approval" and body["action_pin"]["hash"]
    [staged] = [p for p in list_proposals(connection_id=CONN, status="pending") if p.id == body["proposal_id"]]
    assert (staged.action_id, staged.source, staged.params["reason"]) == ("flag_order_for_review", "builder",
                                                                          "late and unshipped")
    assert OVL.object_edits(CONN) == []                                         # nothing ran: a person decides
    wrong = client.post("/objects/v1/actions/flag_order_for_review/propose", params=PARAMS,
                        json={"params": {"order": "customer:C1", "reason": "x"}})
    assert wrong.status_code == 422 and "names an object as order" in wrong.json()["detail"]


def test_a_proposal_read_under_a_contract_that_moved_is_refused(doors, client, monkeypatch):
    monkeypatch.setattr("aughor.ontology.release.current_id", lambda conn, schema: f"{CONN}/ecommerce@4")
    r = client.post("/objects/v1/actions/flag_order_for_review/propose", params=PARAMS,
                    json={"params": {"order": f"order:{ORDER}", "reason": "x"}, "release": f"{CONN}/ecommerce@3"})
    assert r.status_code == 409 and "The contract moved" in r.json()["detail"]


# ── the MCP server: one propose tool per declared action, with the action's own schema ───────────────────────────────

def test_the_mcp_server_offers_a_propose_tool_per_declared_action_with_its_schema(graph, monkeypatch):  # noqa: F811
    from mcp.shared.memory import create_connected_server_and_client_session

    from aughor.mcp import server as srv
    contract = ontology_contract(graph, f"{CONN}/ecommerce@3")
    proposed: list = []

    class _Api:
        async def ontology_contract(self, connection, *, schema=None):
            return contract

        async def propose_action(self, connection, action_id, params, *, reasoning="", release="", schema=None):
            proposed.append((connection, action_id, params, reasoning, release))
            return {"status": "awaiting_approval"}

        async def agent_policy(self):
            return {"effective": {"level": "act"}}

    api = _Api()
    monkeypatch.setenv("AUGHOR_MCP_ONTOLOGY", f"{CONN}/ecommerce")
    monkeypatch.setattr(srv, "mcp", srv.PolicedFastMCP("t"))
    monkeypatch.setattr(srv, "_client", api)
    monkeypatch.setattr(srv, "_DYNAMIC", {})
    monkeypatch.setattr(srv, "_LIVE_SOURCES", set())
    srv.forget_policy()

    async def run():
        assert await srv.register_ontology_tools(api) == ["propose_flag_order_for_review"]
        from aughor.mcp.policy import tool_level
        assert tool_level("propose_flag_order_for_review") == "act"
        async with create_connected_server_and_client_session(srv.mcp) as client:
            listed = {t.name: t for t in (await client.list_tools()).tools}
            schema = listed["propose_flag_order_for_review"].inputSchema
            assert schema["properties"]["order"]["pattern"] == "^order:.+$" and "reasoning" in schema["properties"]
            await client.call_tool("propose_flag_order_for_review",
                                   {"order": f"order:{ORDER}", "reason": "late", "reasoning": "overdue"})
        assert proposed == [(CONN, "flag_order_for_review", {"order": f"order:{ORDER}", "reason": "late"}, "overdue",
                             f"{CONN}/ecommerce@3")]

    asyncio.run(run())


def test_the_route_levels_read_a_listing_and_hold_a_proposal_as_an_act():
    from aughor.mcp.policy import route_level, tool_level
    assert route_level("POST", "/objects/v1/list") == "read" and tool_level("list_objects") == "read"
    assert route_level("POST", "/objects/v1/actions/{action_id}/propose") == "act"


# ── Ossie: a semantic model read as proposals a person accepts ─────────────────────────────────────────────────────

MODEL = """
version: 0.2.0.dev0
name: shop
datasets:
  - name: orders
    source: shop.public.orders
    primary_key: [order_id]
    description: An order a customer placed.
  - name: customers
    source: shop.public.customers
    primary_key: [customer_id]
    ai_context: {instructions: Someone who has placed at least one order.}
  - name: carts
    source: shop.public.carts
    primary_key: [cart_id, customer_id]
relationships:
  - name: placed_by
    from: orders
    to: customers
    from_columns: [customer_id]
    to_columns: [customer_id]
metrics:
  - name: order_value
    expression:
      dialects:
        - {dialect: ANSI_SQL, expression: "SUM(orders.total_amount)"}
  - name: tableau_only
    expression:
      dialects:
        - {dialect: TABLEAU, expression: "SUM([x])"}
"""


def test_an_ossie_model_is_read_as_proposals_and_nothing_is_declared_until_a_person_accepts(doors, client):
    from aughor.ontology.ossie import OssieRefused, parse, plan
    with pytest.raises(OssieRefused, match="any 0.2 draft"):
        parse("version: 1.0\nname: x\ndatasets: [{name: a, source: b}]")
    doors.entities["Customer"].description = ""
    rows = {r["id"]: r for r in plan(parse(MODEL), doors)}
    assert rows["dataset:orders"]["kind"] == "held" and "its own description" in rows["dataset:orders"]["says"]
    assert (rows["dataset:customers"]["kind"], rows["dataset:customers"]["spec"]) == (
        "describe", {"description": "Someone who has placed at least one order."})
    assert "composite key" in rows["dataset:carts"]["refused"]
    assert rows["metric:order_value"]["spec"]["sql"] == "SELECT SUM(total_amount) AS order_value FROM orders"
    assert "dialect this engine does not read" in rows["metric:tableau_only"]["refused"]
    preview = client.post("/ontology/v1/import/ossie/preview", params=PARAMS, json={"model": MODEL})
    assert preview.status_code == 200 and preview.json()["provenance"] == "ossie:shop@0.2.0.dev0"
    stray = client.post("/ontology/v1/import/ossie", params=PARAMS, json={"model": MODEL, "accept": ["dataset:carts"]})
    assert stray.status_code == 400 and "is not offered" in stray.json()["detail"]


def test_accepting_declares_each_part_through_its_own_door_as_the_persons_with_the_model_as_provenance(
        doors, client, tmp_path, monkeypatch):
    from aughor.semantic import metrics as m                # this test WRITES a metric: a registry of its own
    monkeypatch.setattr(m, "_DEFAULT_PATH", tmp_path / "metrics.json", raising=False)
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    doors.entities["Customer"].description = ""
    r = client.post("/ontology/v1/import/ossie", params=PARAMS,
                    json={"model": MODEL, "accept": ["dataset:customers", "metric:order_value"]})
    assert r.status_code == 200, r.text
    results = {x["id"]: x for x in r.json()["results"]}
    assert results["dataset:customers"]["ok"] is True, results
    assert results["metric:order_value"]["ok"] is True, results
    from aughor.ontology import overrides as OV
    described = OV.find_override(CONN, "ecommerce", "entity", "Customer")
    assert described is not None and described.fields["description"] == "Someone who has placed at least one order."
    from aughor.semantic.metrics import definition_at
    metric = definition_at("order_value", CONN, "ecommerce")
    assert metric is not None and metric.status == "draft" and "SUM(total_amount)" in metric.sql
