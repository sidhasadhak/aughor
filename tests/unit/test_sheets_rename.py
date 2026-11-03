"""Renaming a sheet (Arc SH): a sheet's table is its API name, and its name is free (ROADMAP's rule: a rename never breaks a
consumer).

The falsifiers, each measured before this was built: a rename dropped the table every kept card named, so the card printed
`Catalog Error: Table with name customers does not exist!`; and a new sheet that took the old name then fed that card its
own rows, with nothing said.
"""
from __future__ import annotations

import pytest

CUSTOMERS = "customer_id,customer_city\nc1,sao paulo\nc2,rio de janeiro\n"
ORDERS = "order_id,customer_id,price\no1,c1,10.00\no2,c2,20.00\no3,c9,30.00\n"


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


def _make(env, name, text, file=""):
    from aughor.sheets import files, service
    path = env / f"{file or name}.csv"
    path.write_text(text)
    return service.create_from_file(files.stage(path, path.name), name=name, by="user:ana")


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


def _card(client, sql='SELECT customer_id, customer_city FROM "customers"', title="The customers"):
    kept = client.post("/dashboards/queries?connection_id=sheets", json={"sql": sql, "title": title, "shown": {"as": "table"}})
    assert kept.status_code == 201, kept.text
    return kept.json()["card"]["id"]


def _rename(client, sheet, name):
    done = client.patch(f"/sheets/{sheet.id}", json={"name": name})
    assert done.status_code == 200, done.text
    return done.json()


def test_a_rename_leaves_every_kept_card_reading(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    card = _card(client)
    assert client.post(f"/cards/{card}/run").json()["error"] is None
    renamed = _rename(client, sheet, "Clients in Brazil")
    assert renamed["name"] == "Clients in Brazil" and renamed["table"] == "customers"
    out = client.post(f"/cards/{card}/run").json()
    assert out["error"] is None and out["rows"] == [["c1", "sao paulo"], ["c2", "rio de janeiro"]]


def test_a_new_sheet_of_the_old_name_takes_its_own_table_and_no_card_with_it(env, client):
    """A rename left the name free, and the next sheet to take it fed the card its rows: a wrong answer with no error."""
    sheet = _make(env, "Customers", CUSTOMERS)
    card = _card(client)
    _rename(client, sheet, "Clients")
    other = _make(env, "Customers", "customer_id,customer_city\nc7,curitiba\n", file="other")
    assert other.table == "customers_2"
    assert client.post(f"/cards/{card}/run").json()["rows"] == [["c1", "sao paulo"], ["c2", "rio de janeiro"]]


def test_a_rename_keeps_the_rows_the_edits_and_what_reads_it(env, client):
    from aughor.sheets import combine, model, projection, service
    customers, orders = _make(env, "Customers", CUSTOMERS), _make(env, "Orders", ORDERS)
    combine.link_keep(model.get(orders.id), "customer_id", customers.id, "customer_id", bring=["customer_city"], by="user:ana")
    service.set_cells(model.get(customers.id), [{"row": 1, "column": "customer_city", "value": "edited", "version": 0}], by="user:ana")
    _rename(client, customers, "Clients")
    gone = model.get(customers.id)
    assert projection.read_row(gone, 1)[gone.column("customer_city").id] == "edited"
    assert projection.read_row(model.get(orders.id), 1)[model.get(orders.id).column("customer_city").id] == "edited"
    assert projection.check(gone)["same"] is True
    assert client.get(f"/sheets/{customers.id}/dependents").json()["sheets"][0]["name"] == "Orders"


def test_what_reads_it_is_still_found_after_a_rename(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    _card(client)
    _rename(client, sheet, "Clients")
    assert client.get(f"/sheets/{sheet.id}/dependents").json()["cards"] == [{"title": "The customers", "yours": True}]


def test_undoing_a_rename_gives_the_name_back_and_the_card_never_notices(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    card = _card(client)
    _rename(client, sheet, "Clients")
    _rename(client, sheet, "Buyers")
    assert client.post(f"/sheets/{sheet.id}/undo").status_code == 200
    assert client.get(f"/sheets/{sheet.id}").json()["name"] == "Clients"
    assert client.post(f"/cards/{card}/run").json()["error"] is None
    assert client.post(f"/sheets/{sheet.id}/undo").status_code == 200
    read = client.get(f"/sheets/{sheet.id}").json()
    assert (read["name"], read["table"]) == ("Customers", "customers")
    assert client.post(f"/sheets/{sheet.id}/redo").status_code == 200
    assert client.get(f"/sheets/{sheet.id}").json()["name"] == "Clients"
    assert client.post(f"/cards/{card}/run").json()["error"] is None


def test_the_history_says_it_was_renamed(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    _rename(client, sheet, "Clients")
    assert client.get(f"/sheets/{sheet.id}/changes").json()["changes"][0]["what"] == "renamed from Customers"


def test_a_removed_renamed_sheet_says_a_name_that_really_brings_the_card_back(env, client):
    """The sentence names what to do, so it is done here: the name it gives must make the table the card reads."""
    import re
    sheet = _make(env, "Customers", CUSTOMERS)
    card = _card(client)
    _rename(client, sheet, "Clients")
    client.delete(f"/sheets/{sheet.id}")
    said = client.post(f"/cards/{card}/run").json()["error"]
    assert said.startswith('The sheet "Clients" was removed by you on ')
    named = re.search(r'A new sheet named "([^"]+)"', said).group(1)
    assert named != "Clients"
    assert _make(env, named, "customer_id,customer_city\nc7,curitiba\n", file="again").table == "customers"
    assert client.post(f"/cards/{card}/run").json()["rows"] == [["c7", "curitiba"]]


def test_the_csv_is_named_as_the_sheet_is(env, client):
    sheet = _make(env, "Customers", CUSTOMERS)
    assert 'filename="customers.csv"' in client.get(f"/sheets/{sheet.id}/csv").headers["content-disposition"]
    _rename(client, sheet, "Clients in Brazil")
    assert 'filename="clients_in_brazil.csv"' in client.get(f"/sheets/{sheet.id}/csv").headers["content-disposition"]


def test_the_schema_says_which_sheet_a_table_is_only_when_its_name_no_longer_does(env, client):
    """A model reads a sheet by its table: a sheet asked for by its new name has to be findable, and only then is it said."""
    from aughor.db.connection import open_connection_for
    from aughor.sheets import model, service
    renamed = _make(env, "Customers", CUSTOMERS)
    _make(env, "Orders", ORDERS)
    assert _make(env, "Orders", ORDERS, file="twin").table == "orders_2"       # still says what it is
    _rename(client, renamed, "Clients in Brazil")
    lines = open_connection_for("sheets").get_schema().splitlines()
    assert [line for line in lines if "the sheet" in line] == [
        next(line for line in lines if line.startswith("TABLE:") and "customers" in line)]
    assert next(line for line in lines if "the sheet" in line).endswith('⬝ the sheet "Clients in Brazil"')
    service.rename(model.get(renamed.id), "Customers", by="user:ana")
    assert "the sheet" not in open_connection_for("sheets").get_schema()


# a warehouse's columns are written in square brackets at the end of a TABLE line, and a parser reads them there
@pytest.mark.parametrize("name", ["Clients", "Clients (2024)", "Clients (id int, city text)", "TABLE: other (x int)",
                                  "Clients [draft]", "Clients [id INTEGER, city TEXT]"])
def test_the_name_on_a_table_line_is_never_taken_for_a_table_or_a_column(env, client, name):
    from aughor.db.connection import open_connection_for
    from aughor.tools.schema import build_rich_schema, parse_schema_tables
    sheet = _make(env, "Customers", CUSTOMERS)
    read = lambda: open_connection_for("sheets").get_schema()                      # noqa: E731
    tables, rich = parse_schema_tables(read()), build_rich_schema(read())
    assert tables and rich
    _rename(client, sheet, name)
    assert f'the sheet "{name}"' in read()
    assert parse_schema_tables(read()) == tables
    assert build_rich_schema(read()) == rich
