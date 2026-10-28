"""What the live receipts of object security found (ROADMAP §3.65), each held here before the feature is part of the
platform.

The receipts ran on the samples connection with OC-7's declarations: Order's fulfilment group sees shipped and
delivered orders, support sees cancelled and refunded ones, and total_amount is finance's alone; ana is fulfilment,
ben support and finance, carl in no group, and an agent acted for a person. Nine places let a reader see more than
they may, or withheld something without saying so:

1. the conversation's schema tools handed the model a policied table's row count, its masked column's samples and
   every status value, the ones the reader may not see among them;
2. a policy refusal was routed to the model as a type mismatch to retry;
3. the policy's sentence reached the model and never the reader's answer;
4. a principal granted one entity read another through a link — the links route, a listing's columns, a query's
   grouping and filters;
5. a refusal at the organisation's level check was audited with no principal;
6. the dashboard-from-object door read as the person while an agent acted for them;
7. a listing's completeness said nothing was masked while a column was;
8. the dashboard from an object left a figure out for a reader the property is masked from, and did not say so;
9. a person's "Run now" kept no person on the run's start record.

Each test turns its feature on as the feature's own tests do; none calls a model or an outside service.
"""
from __future__ import annotations

import json

import pytest

from aughor.mcp import policy as P
from tests.unit.test_every_outside_caller_is_someone import _mint, held  # noqa: F401 — fixtures by name
from tests.unit.test_object_actions import CONN, ORDER, _Borrowed, db, graph  # noqa: F401 — fixtures by name
from tests.unit.test_one_row_policy_at_every_door import COUNT, as_reader, sql_door  # noqa: F401 — fixtures by name
from tests.unit.test_ontology_security import RETURNED, SHIPPED, secured  # noqa: F401 — fixtures by name

MASKED_FOR_ANA = "Order.total_amount is confidential — masked for user:ana; finance may read it"
#: Every status an order holds that ana's policy does not admit.
NOT_ANAS = {"cancelled", "refunded", "pending", "processing"}


@pytest.fixture
def borrowed(db, monkeypatch):  # noqa: F811
    """The conversation's tools open the samples database (a resolver that closes what it opens is lent it)."""
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn, *a, **k: _Borrowed(db))
    monkeypatch.setattr("aughor.routers.investigations.write_answer_receipt", lambda **kw: {})


@pytest.fixture
def served(secured, monkeypatch):  # noqa: F811
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: secured)
    return secured


@pytest.fixture
def served_open(graph, monkeypatch):  # noqa: F811
    """The samples ontology with no row policy or mask declared: what a grant alone decides."""
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    return graph


# ── 1. the schema tools ─────────────────────────────────────────────────────────

def test_the_schema_tools_hand_the_model_only_what_the_reader_may_read(sql_door, borrowed, as_reader):  # noqa: F811
    from aughor.agent.converse_tools import describe_table, list_tables
    as_reader("ana")
    described = describe_table(CONN, {"table": "orders"})
    said = json.dumps(described)
    assert "5,000 rows" not in said, "a policied table's row count reached the model"
    assert not {s for s in NOT_ANAS if s in said}, "a status ana may not see reached the model"
    assert "38.70" not in said, "a masked column's sample values reached the model"
    line = next(x for x in described["schema"].splitlines() if x.strip().startswith("total_amount"))
    assert "masked for you" in line and MASKED_FOR_ANA in line and "~ e.g." not in line
    assert "total_amount" in described["columns"], "a masked column is still listed"
    assert any("row count" in w and "withheld for user:ana" in w and "fulfilment: status in delivered, shipped" in w
               for w in described["withheld"]), described.get("withheld")
    listed = list_tables(CONN, {})
    assert "5,000 rows" not in listed["tables"] and "(500 rows)" in listed["tables"]       # customers: no policy
    assert any("ecommerce.orders" in w and "withheld for user:ana" in w for w in listed["withheld"])
    assert any(MASKED_FOR_ANA in w for w in listed["withheld"])
    assert "Bob Taylor" in describe_table(CONN, {"table": "customers"})["schema"]      # a table no policy narrows


# ── 2. a policy refusal is not a retry ──────────────────────────────────────────

def test_a_policy_refusal_is_said_to_the_reader_never_rewritten_around(sql_door, borrowed, as_reader):  # noqa: F811
    from aughor.agent.converse_tools import route_error, run_sql
    as_reader("ana")
    out = run_sql(CONN, {"sql": "SELECT SUM(total_amount) FROM orders"})
    assert out["error"].startswith("[OBJECT POLICY] refused")
    repair = out["repair"]
    assert repair["retryable"] is False and repair["kind"] == "policy", repair
    assert MASKED_FOR_ANA in repair["instruction"] and "do not rewrite" in repair["instruction"].lower()
    assert "Cast explicitly" not in repair["instruction"]
    blocked = route_error("[ROW POLICY] query blocked — the row-level access policy could not be safely applied")
    assert blocked["retryable"] is False and blocked["kind"] == "policy"


# ── 3. the policy's sentence reaches the reader ─────────────────────────────────

def test_the_policy_a_read_was_narrowed_or_refused_by_is_said_on_the_answer_once(sql_door, borrowed, as_reader):  # noqa: F811
    from aughor.agent.converse_tools import run_sql
    from aughor.answer.envelope import EnvelopeFolder
    as_reader("ana")
    frames: list = []

    def emit(kind, payload):
        frames.append((kind, payload))
    run_sql(CONN, {"sql": COUNT}, emit=emit)
    run_sql(CONN, {"sql": COUNT + " WHERE order_date >= DATE '2023-01-01'"}, emit=emit)
    run_sql(CONN, {"sql": "SELECT SUM(total_amount) FROM orders"}, emit=emit)
    folder = EnvelopeFolder(question="how many orders?", connection_id=CONN)
    for kind, payload in frames:
        folder.feed(kind, payload)
    caveats = folder.finish().caveats
    narrowed = [c for c in caveats if "only the Order objects user:ana may see are shown" in c]
    refused = [c for c in caveats if MASKED_FOR_ANA in c]
    assert len(narrowed) == 1 and len(refused) == 1, caveats


# ── 4. a principal's grant holds through a link ─────────────────────────────────

@pytest.fixture
def acts(monkeypatch):
    """The organisation lets agents act, so its policy admits the object query and listing doors (an unmapped POST is
    an act) and the principal's grant alone decides."""
    from aughor.orgsettings import agent_policy as AP
    monkeypatch.delenv("AUGHOR_AGENT_POLICY_LEVEL", raising=False)
    AP.save_agent_policy("default", level="act", set_by="ana")
    yield
    AP.clear_agent_policy("default")


def test_a_principal_granted_one_entity_reads_no_other_through_a_link(client, held, served_open, acts):  # noqa: F811
    from aughor.kernel.ledger import Ledger
    name, headers = _mint(client, areas=["objects:read"], entities=["Order"])
    params = {"connection_id": CONN}
    asked = {
        "the links route": client.get(f"/objects/order/{ORDER}/links/order_to_customer", params=params,
                                      headers=headers),
        "a listing's columns": client.post("/objects/v1/list", params=params, headers=headers, json={
            "entity": "order", "columns": ["status", "order_to_customer.full_name", "order_to_customer.email"]}),
        "a listing's filter": client.post("/objects/v1/list", params=params, headers=headers, json={
            "entity": "order", "columns": ["status"],
            "filters": [{"path": "order_to_customer.country", "value": "GB"}]}),
        "the object listing's columns": client.post("/objects/list", params=params, headers=headers, json={
            "entity": "order", "columns": ["order_to_customer.city"]}),
        "a query's filter": client.post("/objects/query", params=params, headers=headers, json={
            "object_type": "order", "measures": [{"agg": "count"}],
            "filters": [{"path": "order_to_customer.country", "value": "GB"}]}),
        "a query's grouping": client.post("/objects/query", params=params, headers=headers, json={
            "object_type": "order", "measures": [{"agg": "count"}], "by": ["order_to_customer.city"]}),
        "a query's measure": client.post("/objects/query", params=params, headers=headers, json={
            "object_type": "order", "measures": [{"agg": "count_distinct", "path": "order_to_customer.city"}]}),
    }
    for door, r in asked.items():
        assert r.status_code == 403, (door, r.status_code, r.text[:300])
        detail = r.json()["detail"]
        assert detail["code"] == P.CODE_ENTITY, (door, detail)
        assert "entity 'Customer' is not on this principal's grant (Order)" in detail["detail"], (door, detail)
    own = client.post("/objects/v1/list", params=params, headers=headers, json={"entity": "order", "columns": ["status"]})
    assert own.status_code == 200 and own.json()["rows"], own.text[:300]
    # the object's own page does not follow a link out of the grant — not even to count — and says why
    page = client.get(f"/objects/order/{ORDER}", params=params, headers=headers)
    assert page.status_code == 200, page.text[:300]
    out = {x["name"]: x for x in page.json()["links"]}["order_to_customer"]
    assert out["usable"] is False and "entity 'Customer' is not on this principal's grant (Order)" in out["why_not"]
    assert "pk" not in out
    # a person asking the same door follows the link: the grant held the principal, and only it
    assert client.get(f"/objects/order/{ORDER}/links/order_to_customer", params=params).status_code == 200
    # the call is audited once, refused, under the principal that asked
    rows = [e["payload"] for e in Ledger.default().events(kind="mcp.tool_call", limit=500)
            if (e.get("payload") or {}).get("principal") == f"service:{name}"
            and (e["payload"].get("route") or "").endswith("/links/{link}")]
    assert [(r["allowed"], r["code"]) for r in rows] == [(False, P.CODE_ENTITY)], rows
    # and its contract describes no entity outside the grant — no link, no action, no object parameter into one
    cut = client.get("/ontology/v1/contract", params=params, headers=headers).json()
    assert list(cut["entities"]) == ["Order"]
    assert "customer" not in json.dumps({k: v for k, v in cut.items() if k != "entities"}).lower()
    assert not any("customer" in json.dumps(e.get("x-aughor") or {}).lower() for e in cut["entities"].values())


# ── 5. every refusal names the principal ────────────────────────────────────────

def test_a_refusal_at_the_organisations_level_check_is_audited_under_the_principal_that_asked(client, held):  # noqa: F811
    from aughor.kernel.ledger import Ledger
    from aughor.orgsettings import agent_policy as AP
    AP.save_agent_policy("default", level="read", set_by="ana")
    try:
        name, headers = _mint(client, areas=["analysis:run"])
        r = client.post("/chat", json={"question": "how many orders?", "connection_id": "c1"}, headers=headers)
        assert r.status_code == 403 and r.json()["detail"]["code"] == P.CODE_LEVEL, r.text[:300]
    finally:
        AP.clear_agent_policy("default")
    refused = [e["payload"] for e in Ledger.default().events(kind="mcp.tool_call", limit=500)
               if (e.get("payload") or {}).get("code") == P.CODE_LEVEL and e["payload"].get("route") == "/chat"]
    assert refused and refused[0].get("principal") == f"service:{name}", refused[:1]


# ── 6. the from-object door and an acting agent ─────────────────────────────────

def test_the_from_object_door_reads_as_the_narrower_of_the_agent_and_the_person(client, served, monkeypatch):
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ben")                    # support and finance
    params = {"entity": "order", "connection_id": CONN}
    alone = client.get("/dashboards/from-object", params=params)
    acting = client.get("/dashboards/from-object", params=params, headers={"X-Aughor-Acting-Agent": "agent:nobody"})
    assert alone.status_code == acting.status_code == 200, (alone.text[:300], acting.text[:300])
    assert alone.json()["total"] > 0
    assert acting.json()["total"] == 0, "an agent in no group was shown its person's orders"
    assert any("agent:nobody" in c for c in acting.json()["caveats"]), acting.json()["caveats"]
    assert not any(f["path"] == "total_amount" for f in acting.json()["figures"])


# ── 7. a listing's completeness says what it masked ─────────────────────────────

def test_a_listing_says_in_its_completeness_the_property_it_masked(client, served, monkeypatch):
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    r = client.post("/objects/list", params={"connection_id": CONN, "schema_name": "ecommerce"},
                    json={"entity": "Order", "columns": ["status", "total_amount"], "limit": 50})
    assert r.status_code == 200, r.text[:300]
    said = r.json()["completeness"]
    assert said["masked"] == ["total_amount"] and said["state"] == "withheld", said
    assert MASKED_FOR_ANA in said["said"], said


# ── 8. the figure the dashboard left out is said ────────────────────────────────

def test_the_dashboard_from_an_object_says_the_figure_it_left_out_and_why(client, served, monkeypatch):
    params = {"entity": "order", "connection_id": CONN}
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ben")                    # finance reads the amount
    assert any(f["path"] == "total_amount" for f in client.get("/dashboards/from-object", params=params).json()["figures"])
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    out = client.get("/dashboards/from-object", params=params).json()
    assert not any(f["path"] == "total_amount" for f in out["figures"])
    left = [c for c in out["caveats"] if "Average total amount" in c]
    assert len(left) == 1 and MASKED_FOR_ANA in left[0], out["caveats"]


# ── 9. a run keeps who asked ────────────────────────────────────────────────────

def test_a_persons_run_now_keeps_who_asked_on_the_runs_start(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    body = {"conn_id": "conn-asked-by", "name": "Refund watch", "enabled": False,       # gated: nothing is dispatched
            "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
            "effects": [{"kind": "notify", "config": {"trigger_id": "t1"}}]}
    aid = client.post("/automations", json=body).json()["id"]
    ran = client.post(f"/automations/{aid}/run")
    assert ran.status_code == 200, ran.text[:300]
    kept = client.get(f"/automations/runs/{ran.json()['id']}/version").json()
    assert kept["kept"] and kept["trigger"]["via"] == "hand", kept
    assert kept["trigger"]["by"] == "user:ana", kept["trigger"]


# ── the quick body: what the model is handed, and what the reader is told ──────

class _NoModel(Exception):
    """Raised by the stub provider: no model is called in these tests."""


class _Coder:
    """The coder the quick body asks for its SQL. It records each prompt, and either writes ``sql`` as the answer or,
    with none, stops the turn there — every other model call is refused, as a provider that is down would be."""
    model = "stub"

    def __init__(self, sql: str = ""):
        self.sql, self.prompts = sql, []

    def complete(self, *a, **k):
        raise _NoModel("no model is called in tests")

    def complete_streaming(self, *a, system="", user="", response_model=None, **k):
        from aughor.routers.investigations import _ChatAnswer
        if response_model is not _ChatAnswer:
            raise _NoModel("no model is called in tests")
        self.prompts.append(user)
        if not self.sql:
            raise _NoModel("the prompt is what this test reads")
        return _ChatAnswer(sql=self.sql, headline="There are orders.")


def _quick(monkeypatch, db, coder: _Coder):  # noqa: F811
    """Run the quick body's whole pipeline on the samples database with ``coder`` as its model."""
    from aughor.routers.investigations import _answer_core
    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role="coder", *a, **k: coder)
    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema", lambda *a, **k: _Borrowed(db))
    frames: list = []
    try:
        result = _answer_core("how many orders are there by status", CONN, [], skip_clarify=True,
                              emit=lambda kind, payload: frames.append((kind, payload)))
    except _NoModel:
        result = None
    return result, frames


def test_the_quick_body_hands_its_model_only_what_the_reader_may_read(
        sql_door, borrowed, as_reader, db, monkeypatch):  # noqa: F811
    from aughor.tools.data_catalog import clear_cache
    clear_cache()
    unread = _Coder()
    _quick(monkeypatch, db, unread)                             # no request acts for anyone: the catalog as it was
    assert "| pending |" in unread.prompts[-1] and "38.70" in unread.prompts[-1]
    as_reader("ana")
    coder = _Coder()
    _quick(monkeypatch, db, coder)
    prompt = coder.prompts[-1]
    block = prompt[prompt.index("## ecommerce.orders"):]
    block = block[:block.index("\n## ", 1)] if "\n## " in block[1:] else block
    for outside in ("| pending |", "| processing |", "| cancelled |", "| refunded |"):
        assert outside not in block, f"a row ana may not see reached the model: {outside}"
    for amount in ("38.70", "62.40", "86.10"):
        assert amount not in prompt, "a masked column's value reached the model"
    assert "withheld for user:ana" in block and "fulfilment: status in delivered, shipped" in block
    assert MASKED_FOR_ANA in block and "masked for you" in block
    assert "Bob Taylor" in prompt or "## ecommerce.customers" not in prompt     # a table no policy narrows is as it was


def test_the_quick_body_says_the_policy_its_read_was_narrowed_or_refused_by_on_the_answer(
        sql_door, borrowed, as_reader, db, monkeypatch):  # noqa: F811
    from aughor.answer.envelope import EnvelopeFolder
    as_reader("ana")
    told = {}
    for sql in ("SELECT COUNT(*) AS n FROM ecommerce.orders", "SELECT SUM(total_amount) AS t FROM ecommerce.orders"):
        result, frames = _quick(monkeypatch, db, _Coder(sql))
        assert result is not None and result.outcome in ("answered", "query_failed"), result
        folder = EnvelopeFolder(question="how many orders are there", connection_id=CONN)
        for kind, payload in frames:
            folder.feed(kind, payload)
        told[result.outcome] = folder.finish().caveats
    narrowed = [c for c in told["answered"] if "only the Order objects user:ana may see are shown" in c]
    refused = [c for c in told["query_failed"] if MASKED_FOR_ANA in c]
    assert len(narrowed) == 1 and len(refused) == 1, told
