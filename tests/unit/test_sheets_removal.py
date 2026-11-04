"""Removing a sheet (Arc SH): what reads it is named first, and says why afterwards.

The falsifiers, each measured on a scratch store before this was built: a kept card printed `Catalog Error: Table with name
customers does not exist! Did you mean "sqlite_master"?`, and a count over a removed sheet read 0 on every row, a figure
nobody wrote.
"""
from __future__ import annotations

import pytest

ORDERS = "order_id,customer_id,price\no1,c1,10.00\no2,c2,20.00\no3,c9,30.00\n"
CUSTOMERS = "customer_id,customer_city\nc1,sao paulo\nc2,rio de janeiro\n"
PAYMENTS = "order_id,payment_value\no1,6.00\no1,4.00\no2,20.00\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana")
    from aughor.actions import overlay
    from aughor.cards import store as card_store
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    monkeypatch.setattr(card_store, "_DB_PATH", tmp_path / "cards.db")
    from aughor.sheets import projection
    projection.reset()
    yield tmp_path
    projection.reset()


def _make(env, name, text, by="user:ana"):
    from aughor.sheets import files, service
    path = env / f"{name}.csv"
    path.write_text(text)
    return service.create_from_file(files.stage(path, path.name), name=name, by=by)


@pytest.fixture
def client(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import cards, dashboards, sheets
    app = FastAPI()
    app.include_router(sheets.router)
    app.include_router(cards.router)
    app.include_router(dashboards.router)
    return TestClient(app)


def _query_card(client, sql="SELECT customer_id, customer_city FROM customers", title="The customers"):
    kept = client.post("/dashboards/queries?connection_id=sheets", json={"sql": sql, "title": title, "shown": {"as": "table"}})
    assert kept.status_code == 201, kept.text
    return kept.json()["card"]["id"]


def _dashboard(owner, title, card_ids, **publish):
    """A dashboard kept through its own door, holding these cards."""
    from aughor.cards.store import get_card
    from aughor.dashboards import versions
    from aughor.dashboards.compose import default_spec
    from aughor.dashboards.home import FIRST, Home
    home = Home("sheets", owner, FIRST)
    spec = default_spec(title, [get_card(c) for c in card_ids])
    assert versions.keep(home, spec, approved_by="user:ana", source="a person's own hand", written_by_model=False).kept
    if publish:
        assert versions.publish(home, publish["to"], approved_by="user:ana").kept
    return home


def _combined(env):
    """Orders reading Customers through a link, and totalling Payments twice."""
    from aughor.sheets import combine, model
    orders, customers, payments = _make(env, "Orders", ORDERS), _make(env, "Customers", CUSTOMERS), _make(env, "Payments", PAYMENTS)
    combine.link_keep(model.get(orders.id), "customer_id", customers.id, "customer_id", bring=["customer_city"], by="user:ana")
    combine.total_keep(model.get(orders.id), "order_id", payments.id, "order_id", "sum", "payment_value", name="paid", by="user:ana")
    combine.total_keep(model.get(orders.id), "order_id", payments.id, "order_id", "count", "", name="payments made", by="user:ana")
    return model.get(orders.id), customers, payments


# ── what reads a sheet, named before it goes ─────────────────────────────────────────────────────────────────────────

def test_a_sheet_nothing_reads_says_so(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    assert client.get(f"/sheets/{sheet.id}/dependents").json() == {"sheets": [], "dashboards": [], "cards": []}


def test_the_sheets_reading_it_are_named_with_the_columns_that_go_empty(env, client):
    orders, customers, payments = _combined(env)
    read = client.get(f"/sheets/{customers.id}/dependents").json()["sheets"]
    assert read == [{"id": orders.id, "name": "Orders", "maker": "ana", "empties": ["customer_city"], "links": ["customer_id"],
                     "withheld": False}]
    read = client.get(f"/sheets/{payments.id}/dependents").json()["sheets"]
    assert read[0]["empties"] == ["paid", "payments made"] and read[0]["links"] == []
    # what the sheet itself reads is not what reads it
    assert client.get(f"/sheets/{orders.id}/dependents").json()["sheets"] == []


def test_a_sheet_not_shared_with_the_asker_is_named_never_read(env, client):
    from aughor.sheets import combine, model, sharing
    customers = _make(env, "Customers", CUSTOMERS)
    private = _make(env, "Private orders", ORDERS, by="user:bo")
    combine.link_keep(private, "customer_id", customers.id, "customer_id", bring=["customer_city"], by="user:bo")
    sharing.set_sharing(model.get(private.id), "chosen", [{"kind": "person", "id": "cy", "level": "view"}], by="user:bo")
    assert client.get(f"/sheets/{customers.id}/dependents").json()["sheets"] == [
        {"id": private.id, "name": "Private orders", "maker": "bo", "empties": [], "links": [], "withheld": True}]


def test_the_dashboards_holding_a_card_over_its_table_are_named(env, client):
    customers = _make(env, "Customers", CUSTOMERS)
    _make(env, "Orders", ORDERS)
    first, second = _query_card(client), _query_card(client, "SELECT COUNT(*) AS n FROM customers", "How many")
    other = _query_card(client, "SELECT * FROM orders", "The orders")
    _dashboard("default", "Sales board", [first, second, other])
    read = client.get(f"/sheets/{customers.id}/dependents").json()
    assert len(read["dashboards"]) == 1
    board = read["dashboards"][0]
    assert sorted(board.pop("cards")) == ["How many", "The customers"]      # not The orders, which reads another table
    assert board == {"title": "Sales board", "yours": True, "owner": "", "count": 2, "pieces": [], "withheld": False}
    assert read["cards"] == []


def test_a_card_on_no_dashboard_is_named_too(env, client):
    customers = _make(env, "Customers", CUSTOMERS)
    _query_card(client)
    assert client.get(f"/sheets/{customers.id}/dependents").json()["cards"] == [{"title": "The customers", "yours": True}]


def test_a_replaced_card_does_not_count(env, client):
    from aughor.cards.store import get_card, upsert_card
    customers = _make(env, "Customers", CUSTOMERS)
    old = get_card(_query_card(client))
    upsert_card(old.model_copy(update={"provenance": old.provenance.model_copy(update={"superseded_by": "someone"})}))
    assert client.get(f"/sheets/{customers.id}/dependents").json()["cards"] == []


def test_a_dashboard_of_someone_elses_is_counted_and_its_title_withheld(env, client):
    from aughor.cards.store import upsert_card
    from aughor.cards.models import StoredCard
    customers = _make(env, "Customers", CUSTOMERS)
    theirs = upsert_card(StoredCard(connection_id="sheets", scope="user", scope_ref="bo", source="authored", kind="chart",
                                    title="Bo's private card", sql="SELECT * FROM customers", render={"shown": {"as": "table"}}))
    _dashboard("bo", "Bo's private board", [theirs.id])
    read = client.get(f"/sheets/{customers.id}/dependents").json()
    assert read["dashboards"] == [{"title": "", "yours": False, "owner": "bo", "cards": [], "count": 1, "pieces": [], "withheld": True}]
    assert "private" not in str(read)


# ── a dashboard made from a file (From a file): its cards, its filters and its Add a row name the sheet ─────────────────

def _from_a_file(client, sheet, *, cards=None, filters=({"column": "customer_city"},), scenario=None, add_row=True, ticked=True):
    """A dashboard kept through the From a file door, with what a draft would have read. No model is asked."""
    from aughor.dashboards.home import Home
    from aughor.sheets import dashboard_draft
    cards = [{"key": "how-many", "title": "How many", "as": "figure", "series": [{"column": "n"}],
              "sql": f"SELECT COUNT(*) AS n FROM {sheet.table}"},
             {"key": "rows", "title": "The rows", "as": "table", "sql": f"SELECT * FROM {sheet.table}"}] if cards is None else cards
    got, problems = dashboard_draft._read_proposal(sheet, {"title": "From the file", "cards": cards, "filters": list(filters),
                                                           **({"scenario": scenario} if scenario else {})})
    assert problems == []
    kept = client.post(f"/sheets/{sheet.id}/dashboard/keep", json={
        "title": got["title"], "cards": got["cards"] if ticked else [], "filters": got["filters"], "scenario": got["scenario"], "add_row": add_row})
    assert kept.status_code == 201, kept.text
    return Home("sheets", "default", kept.json()["dashboard_id"])


def test_a_dashboard_from_a_file_is_named_with_its_cards_its_filters_and_its_add_a_row(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    _from_a_file(client, sheet)
    read = client.get(f"/sheets/{sheet.id}/dependents").json()
    assert len(read["dashboards"]) == 1 and read["cards"] == []
    board = read["dashboards"][0]
    assert sorted(board.pop("cards")) == ["How many", "The rows"]
    assert board == {"title": "From the file", "yours": True, "owner": "", "count": 2, "pieces": ["filters", "add_row"], "withheld": False}


def test_a_dashboard_holding_no_card_is_named_by_its_filters_and_its_add_a_row(env, client):
    """A person may untick every card: what is left still reads the sheet."""
    sheet = _make(env, "Customers", CUSTOMERS)
    _from_a_file(client, sheet, ticked=False)
    assert client.get(f"/sheets/{sheet.id}/dependents").json()["dashboards"] == [
        {"title": "From the file", "yours": True, "owner": "", "cards": [], "count": 0, "pieces": ["filters", "add_row"], "withheld": False}]


def test_a_dashboard_made_from_another_sheet_is_not_named(env, client):
    customers, orders = _make(env, "Customers", CUSTOMERS), _make(env, "Orders", ORDERS)
    _from_a_file(client, orders, filters=({"column": "customer_id"},))
    assert client.get(f"/sheets/{customers.id}/dependents").json()["dashboards"] == []
    assert client.get(f"/sheets/{orders.id}/dependents").json()["dashboards"][0]["pieces"] == ["filters", "add_row"]


def test_a_card_a_scenario_shows_twice_is_named_once(env, client):
    from aughor.cards.store import get_card
    from aughor.dashboards import versions
    sheet = _make(env, "Orders", ORDERS)
    table = sheet.table
    home = _from_a_file(client, sheet, filters=(), add_row=False, cards=[
        {"key": "paid", "title": "Paid", "as": "figure", "series": [{"column": "paid"}], "sql": f"SELECT SUM(CAST(price AS DOUBLE)) AS paid FROM {table}"},
        {"key": "if-paid", "title": "If it were more", "as": "figure", "series": [{"column": "paid"}],
         "sql": f"SELECT SUM(CAST(price AS DOUBLE)) * (1 + {{{{uplift}}}} / 100.0) AS paid FROM {table}"},
    ], scenario={"inputs": [{"name": "uplift", "label": "Uplift", "unit": "percent", "start": 0, "min": 0, "max": 50, "step": 5}],
                 "file_card": "paid", "scenario_card": "if-paid"})
    made = sorted(get_card(c).title for c in versions.latest(home)["cards"])     # the rows are always offered
    assert made == ["If it were more", "Paid", "The rows"]
    board = client.get(f"/sheets/{sheet.id}/dependents").json()["dashboards"][0]
    assert sorted(board["cards"]) == made and board["count"] == 3                # a {{value}} is read as a statement


def test_someone_elses_dashboard_from_a_file_tells_no_title_and_no_piece(env, client):
    from aughor.dashboards import versions
    from aughor.dashboards.home import FIRST, Home
    from aughor.sheets import dashboard_draft
    sheet = _make(env, "Customers", CUSTOMERS)
    spec = dashboard_draft.spec_for("Bo's private board", [], sheet=sheet, filters=[{"column": "customer_city", "label": "City"}],
                                    scenario=None, add_row=True)
    kept = versions.keep(Home("sheets", "bo", FIRST), spec, approved_by="user:bo", source="a person's own hand", written_by_model=False)
    assert kept.kept, kept.sentences
    assert client.get(f"/sheets/{sheet.id}/dependents").json()["dashboards"] == [
        {"title": "", "yours": False, "owner": "bo", "cards": [], "count": 0, "pieces": [], "withheld": True}]


def test_a_dashboard_from_a_file_says_why_at_every_card_and_filter_once_its_sheet_is_gone(env, client):
    from aughor.cards.store import get_card
    from aughor.dashboards import versions
    sheet = _make(env, "Customers", CUSTOMERS)
    ids = versions.latest(_from_a_file(client, sheet))["cards"]
    assert all(get_card(c).render.get("standing") is True for c in ids)            # the cards this route keeps
    assert client.delete(f"/sheets/{sheet.id}").status_code == 200
    said = 'The sheet "Customers" was removed by you on '
    for card in ids:
        for ask in ({}, {"params": {"start": "2026-01-01", "end": "2026-02-01"}}):
            ran = client.post(f"/cards/{card}/run", **ask).json()
            assert ran["error"].startswith(said) and "Catalog Error" not in ran["error"]
        narrowed = client.post(f"/cards/{card}/run", json={"filters": [{"table": sheet.table, "column": "customer_city", "values": ["recife"]}]}).json()
        assert narrowed["error"].startswith(said)
    facet = client.post("/dashboards/queries/preview?connection_id=sheets", json={
        "sql": f'SELECT "customer_city" AS value, COUNT(*) AS n FROM "{sheet.table}" GROUP BY 1', "shown": {"as": "table"}}).json()
    assert facet["refused"][0].startswith(said)
    # its Add a row reads the sheet through its own door, and is told the same
    assert client.get(f"/sheets/{sheet.id}").json()["detail"].startswith(said)
    assert client.post(f"/sheets/{sheet.id}/rows", json={"values": {"customer_id": "c9"}}).json()["detail"].startswith(said)


def test_only_a_sheets_maker_asks_what_reads_it(env, client):
    sheet = _make(env, "Theirs", CUSTOMERS, by="user:bo")
    refused = client.get(f"/sheets/{sheet.id}/dependents")
    assert refused.status_code == 403 and "Only bo" in refused.json()["detail"]
    assert client.delete(f"/sheets/{sheet.id}").status_code == 403
    assert client.get("/sheets").json()["sheets"][0]["access"] == "edit"     # the page offers no Remove


# ── what read it, afterwards ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_card_that_lost_its_sheet_says_why_never_the_engines_words(env, client):
    customers = _make(env, "Customers", CUSTOMERS)
    card = _query_card(client)
    assert client.post(f"/cards/{card}/run").json()["error"] is None
    assert client.delete(f"/sheets/{customers.id}").status_code == 200
    out = client.post(f"/cards/{card}/run")
    assert out.status_code == 200 and out.json()["rows"] == []
    said = out.json()["error"]
    assert 'The sheet "Customers" was removed by you on ' in said and "A new sheet named" in said
    assert "Catalog Error" not in said and "sqlite_master" not in said


def test_a_card_cut_to_a_range_says_why_too(env, client):
    customers = _make(env, "Customers", CUSTOMERS)
    card = _query_card(client)
    client.delete(f"/sheets/{customers.id}")
    said = client.post(f"/cards/{card}/run?start=2026-01-01&end=2026-02-01").json()["error"]
    assert said.startswith('The sheet "Customers" was removed')


def test_a_pinned_card_runs_the_other_path_and_says_why_with_its_kind(env, client):
    from aughor.cards.models import StoredCard
    from aughor.cards.store import upsert_card
    customers = _make(env, "Customers", CUSTOMERS)
    pinned = upsert_card(StoredCard(connection_id="sheets", scope="connection", scope_ref="sheets", source="query_builder",
                                    kind="kpi", title="How many", sql="SELECT COUNT(*) FROM customers"))
    assert client.post(f"/cards/{pinned.id}/run").json()["error_kind"] is None
    client.delete(f"/sheets/{customers.id}")
    out = client.post(f"/cards/{pinned.id}/run").json()
    assert out["error"].startswith('The sheet "Customers" was removed') and out["error_kind"] == "sheet_removed"


def test_a_statement_says_who_removed_it_and_any_other_failure_stays_the_engines(env, client, monkeypatch):
    from aughor.db.connection import open_connection_for
    from aughor.sheets import model, service
    customers = _make(env, "Customers", CUSTOMERS)
    service.remove(model.get(customers.id), by="user:bo")
    db = open_connection_for("sheets")
    got = db.execute("t", "SELECT * FROM CUSTOMERS")
    assert got.error.startswith('The sheet "Customers" was removed by bo on ') and got.error_kind == "sheet_removed"
    other = db.execute("t", "SELECT * FROM never_a_sheet")
    assert "does not exist" in other.error and other.error_kind == "sql"


def test_a_new_sheet_of_that_name_is_read_in_its_place(env, client):
    customers = _make(env, "Customers", CUSTOMERS)
    card = _query_card(client)
    client.delete(f"/sheets/{customers.id}")
    assert _make(env, "Customers", "customer_id,customer_city\nc7,curitiba\n").table == customers.table
    out = client.post(f"/cards/{card}/run").json()
    assert out["error"] is None and out["rows"] == [["c7", "curitiba"]]


def test_the_last_removal_of_a_name_is_the_one_said(env, client):
    from aughor.db.connection import open_connection_for
    from aughor.sheets import model, service
    first = _make(env, "Customers", CUSTOMERS)
    service.remove(model.get(first.id), by="user:bo")
    second = _make(env, "Customers", CUSTOMERS)
    service.remove(model.get(second.id), by="user:cy")
    assert "removed by cy" in open_connection_for("sheets").execute("t", "SELECT * FROM customers").error


def test_a_total_of_a_removed_sheet_is_empty_never_a_count_of_nothing(env, client):
    from aughor.sheets import model, projection
    orders, _customers, payments = _combined(env)
    paid, made = orders.column("paid").id, orders.column("payments made").id
    assert [projection.read_row(orders, r)[made] for r in (1, 2, 3)] == [2, 1, 0]     # no payment for o3 is a true 0
    client.delete(f"/sheets/{payments.id}")
    rows = [projection.read_row(model.get(orders.id), r) for r in (1, 2, 3)]
    assert [r[made] for r in rows] == [None, None, None]
    assert [r[paid] for r in rows] == [None, None, None]
    assert ",0\n" not in client.get(f"/sheets/{orders.id}/csv").text
    # and the oracle agrees: the table is what a rebuild gives
    assert projection.check(model.get(orders.id))["same"] is True


def test_a_column_says_which_removed_sheet_it_read_and_keeps_nothing_new(env, client):
    from aughor.sheets import model
    orders, customers, payments = _combined(env)
    assert "reads_removed" not in str(client.get(f"/sheets/{orders.id}").json()["columns"])
    client.delete(f"/sheets/{customers.id}")
    client.delete(f"/sheets/{payments.id}")
    columns = {c["name"]: c.get("reads_removed") for c in client.get(f"/sheets/{orders.id}").json()["columns"]}
    assert columns == {"order_id": None, "customer_id": "Customers", "price": None, "customer_city": "Customers",
                       "paid": "Payments", "payments made": "Payments"}
    assert "reads_removed" not in model.get(orders.id).model_dump_json()


def test_a_removed_sheet_opened_by_its_link_says_so(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    client.delete(f"/sheets/{sheet.id}")
    gone = client.get(f"/sheets/{sheet.id}")
    assert gone.status_code == 404 and gone.json()["detail"].startswith('The sheet "Customers" was removed by you on ')
    assert client.get("/sheets/0123456789").json()["detail"] == "No such sheet"
    assert sheet.id not in str(client.get("/sheets").json()["sheets"])


# ── what stays ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_workspace_file_stays_and_makes_a_new_sheet_a_brought_one_goes_with_it(env, client):
    from aughor.sheets import files, service
    upload = env / "uploaded.csv"
    upload.write_text(CUSTOMERS)
    made = service.create_from_file(files.stage(upload, upload.name), name="From the workspace", by="user:ana",
                                    upload={"schema": "s", "file": upload.name})
    edited = client.patch(f"/sheets/{made.id}/cells", json={"cells": [
        {"row": 1, "column": "customer_city", "value": "edited", "version": 0}]})
    assert edited.status_code == 200
    client.delete(f"/sheets/{made.id}")
    assert upload.exists()
    again = service.create_from_file(files.stage(upload, upload.name), name="From the workspace", by="user:ana",
                                     upload={"schema": "s", "file": upload.name})
    from aughor.sheets import projection
    assert projection.read_row(again, 1)[again.column("customer_city").id] == "sao paulo"   # not with those edits

    brought = _make(env, "Brought", CUSTOMERS)
    kept = files.sheet_dir(brought.id)
    assert kept.exists()
    client.delete(f"/sheets/{brought.id}")
    assert not kept.exists()         # its only copy on the platform went with it: the page must not say it stays
