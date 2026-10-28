"""Arc SH, SH-6 — its first piece: a dashboard made from a sheet (ROADMAP §3.64).

Each card offered is a query of the person's own on the Sheets connection, run once on the sheet before it is offered.
The receipt's falsifier is a test here: a card made from a sheet shows the grid's own total of the same rows, and a cell
edited in the sheet moves the card on its next read — a card over a sheet never settles.
"""
from __future__ import annotations

import pytest

from aughor.kernel.flags import flag_overrides

ORDERS = """order_id,order_status,order_purchase_timestamp,price
o1,delivered,2018-08-01 10:00:00,10.00
o2,delivered,2018-08-02 10:00:00,20.00
o3,shipped,2018-07-03 10:00:00,30.00
o4,canceled,2018-09-04 10:00:00,40.00
o5,delivered,2018-09-05 10:00:00,
o6,shipped,2018-09-06 10:00:00,60.00
"""

ON = {"sheets.core": True, "sheets.grid": True, "sheets.everywhere": True}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AUGHOR_SYSTEM_DB", str(tmp_path / "system.db"))
    from aughor.actions import overlay
    monkeypatch.setattr(overlay, "_DB_PATH", tmp_path / "overlay.db")
    from aughor.sheets import projection
    projection.reset()
    with flag_overrides(ON):
        yield tmp_path
    projection.reset()


def _orders(env):
    from aughor.sheets import files, service
    path = env / "orders.csv"
    path.write_text(ORDERS)
    return service.create_from_file(files.stage(path, path.name), name="Olist orders", by="user:ana",
                                    chosen={"order_status": "choice"})


def _piece(offer, key):
    return next(p for p in offer["pieces"] if p["key"].startswith(key))


def test_each_card_offered_shows_what_the_grid_counts_and_sums(env):
    from aughor.sheets import dashboard, projection
    sheet = _orders(env)
    offer = dashboard.propose(sheet)
    assert offer["rows"] == 6 and offer["view"] == "" and offer["title"] == "Olist orders"
    assert [p["kind"] for p in offer["pieces"]] == ["figure", "figure", "bar", "line", "table"]
    assert not any(p.get("refused") for p in offer["pieces"])
    totals = projection.read_rows(sheet, limit=1)["totals"]
    assert _piece(offer, "rows")["preview"]["value"] == 6
    price = sheet.column("price")
    assert float(_piece(offer, "sum-")["preview"]["value"]) == float(totals[price.id]["sum"]) == 160.0
    bar = _piece(offer, "by-")["preview"]
    assert bar["values"][0] == {"x": "delivered", "v": 3} and bar["of"] == 3
    assert _piece(offer, "over-")["preview"]["points"] == 3              # July, August, September 2018


def test_a_dashboard_from_a_view_reads_only_the_views_rows(env):
    from aughor.sheets import dashboard, projection, service
    from aughor.sheets.model import Condition, View
    sheet = _orders(env)
    status = sheet.column("order_status").id
    sheet = service.save_view(sheet, View(name="Delivered", filter=[Condition(column=status, op="is",
                                                                              value="delivered")]), by="user:ana")
    view = sheet.views[-1]
    offer = dashboard.propose(sheet, view)
    grid = projection.read_rows(sheet, conditions=view.filter, limit=1)
    assert offer["view"] == "Delivered" and offer["rows"] == grid["total"] == 3
    assert _piece(offer, "rows")["preview"]["value"] == 3
    assert float(_piece(offer, "sum-")["preview"]["value"]) == float(grid["totals"][sheet.column("price").id]["sum"])


def test_a_kept_card_follows_an_edit_to_the_sheet_on_its_next_read(env):
    """The falsifier: a card over a sheet never shows the value before an edit."""
    from aughor.dashboards import queries
    from aughor.db.connection import open_connection_for
    from aughor.sheets import dashboard, model, service
    sheet = _orders(env)
    offer = dashboard.propose(sheet)
    paid = _piece(offer, "sum-")
    db = open_connection_for(model.SHEETS_CONNECTION)

    def read() -> float:
        shown = queries.Shown.model_validate(paid["shown"])
        cols = queries.probe(db, offer["sql"], seconds=10)["columns"]
        return float(queries.run(db, offer["sql"], shown, cols, seconds=10)["shown"]["value"])

    assert read() == 160.0
    service.set_cells(model.get(sheet.id), [{"row": 5, "column": "price", "value": "5.00", "version": 0}],
                      by="user:bo")
    assert read() == 165.0


def test_off_no_dashboard_is_offered(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers import sheets as sheets_router
    sheet = _orders(env)
    app = FastAPI()
    app.include_router(sheets_router.router)
    client = TestClient(app)
    assert client.get(f"/sheets/{sheet.id}/dashboard").status_code == 200
    with flag_overrides({"sheets.everywhere": False}):
        assert client.get(f"/sheets/{sheet.id}/dashboard").status_code == 404
